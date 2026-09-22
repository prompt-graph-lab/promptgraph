import ast
from contextlib import ExitStack
from datetime import datetime
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest import mock

from core import project_directory_duplication as duplication


ROOT = Path(__file__).resolve().parents[1]
HELPERS = {
    "_sanitize_duplicate_project_dir_name",
    "_source_project_directory",
    "_default_duplicate_project_dir_name",
    "_duplicate_project_destination_dir",
    "_find_copied_project_json",
    "duplicate_current_project_directory",
}


class Session(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def load_functions(source, *, frozen=False):
    """Execute the real import boundary without running Streamlit startup."""
    tree = ast.parse(source)
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "core.project_directory_duplication":
            nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in HELPERS:
            if frozen and node.name == "duplicate_current_project_directory":
                # Capture the locals at the original save boundary. All original
                # preflight statements and early returns remain unmodified.
                save_index = next(i for i, stmt in enumerate(node.body) if isinstance(stmt, ast.Try))
                node.body = node.body[:save_index] + ast.parse('''
return {
    "valid": True, "error": "",
    "source_project_path": source_project_path,
    "source_project_dir": source_project_dir,
    "clean_name": clean_name, "destination_dir": destination_dir,
}
''').body
            nodes.append(node)
    namespace = {"os": os, "shutil": shutil, "datetime": datetime}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "app-functions", "exec"), namespace)
    return namespace


class DuplicationPlannerTests(unittest.TestCase):
    def plan(self, path="projects/Book/project.json", name="Copy", **kwargs):
        predicates = dict(path_is_file=lambda _: True, path_is_dir=lambda _: True, path_exists=lambda _: False)
        predicates.update(kwargs)
        return duplication.plan_project_directory_duplication(path, name, **predicates)

    def test_name_normalization_keeps_legacy_windows_behavior(self):
        for raw, expected in [
            (None, ""), (False, ""), (0, ""), ("", ""), (" . .. ", ""),
            (' . A/B\\C<>:"|?* . ', "A_B_C_______"),
            ("CON", "CON"), ("NUL.txt", "NUL.txt"),
            ("A\x00B", "A\x00B"), ("みるく", "みるく"), (12, "12"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(expected, duplication.sanitize_duplicate_project_dir_name(raw))

    def test_source_paths_expand_user_and_normalize_without_stripping(self):
        for path in ["projects/Book/../Book/project.json", "~/Book/project.json", " project.json ", Path("Book/project.json"), os.path.abspath(os.sep)]:
            with self.subTest(path=path):
                expected = os.path.abspath(os.path.expanduser(path))
                self.assertEqual((expected, os.path.dirname(expected)), duplication.source_project_directory(path))
        for path in [None, "", False, 0]:
            self.assertEqual(("", ""), duplication.source_project_directory(path))
        with self.assertRaises(TypeError):
            duplication.source_project_directory(42)

    def test_success_fields_and_no_filesystem_writes(self):
        with mock.patch.object(os, "makedirs", side_effect=AssertionError("write")), mock.patch.object(shutil, "copytree", side_effect=AssertionError("copy")):
            result = self.plan(name=" . New/Book. ")
        source = os.path.abspath("projects/Book/project.json")
        self.assertEqual({
            "valid": True, "error": "", "source_project_path": source,
            "source_project_dir": os.path.dirname(source), "clean_name": "New_Book",
            "destination_dir": os.path.abspath("projects/New_Book"),
        }, result)

    def test_first_blocker_and_predicate_order(self):
        cases = [
            ("", "Copy", True, True, False, "現在のプロジェクトパスがありません。", []),
            ("Book/project.json", "", False, False, True, "元のプロジェクトJSONが見つかりません。", ["file"]),
            ("Book/project.json", "", True, False, True, "元のプロジェクトディレクトリが見つかりません。", ["file", "dir"]),
            ("Book/project.json", "..", True, True, True, "複製先プロジェクト名が必要です。", ["file", "dir"]),
            ("Book/project.json", "Copy", True, True, True, "複製先ディレクトリは既に存在します。", ["file", "dir", "exists"]),
        ]
        for path, name, file, directory, exists, error, expected_calls in cases:
            with self.subTest(error=error):
                calls = []
                def predicate(label, value):
                    def check(path):
                        calls.append(label)
                        return value
                    return check
                result = self.plan(path, name, path_is_file=predicate("file", file), path_is_dir=predicate("dir", directory), path_exists=predicate("exists", exists))
                self.assertEqual({"valid": False, "error": error}, result)
                self.assertEqual(expected_calls, calls)

    def test_default_collision_search_checks_unsuffixed_then_numeric_order(self):
        checked = []
        def exists(path):
            checked.append(path)
            return len(checked) < 12
        self.assertEqual("Book_copy_11", duplication.default_duplicate_project_dir_name("projects/Book/project.json", path_exists=exists))
        parent = os.path.abspath("projects")
        self.assertEqual([os.path.join(parent, "Book_copy")] + [os.path.join(parent, f"Book_copy_{i}") for i in range(1, 12)], checked)
        self.assertEqual("MyProject_copy", duplication.default_duplicate_project_dir_name(None, path_exists=mock.Mock(side_effect=AssertionError)))

    def test_destination_skips_name_when_source_is_empty(self):
        name = mock.Mock()
        name.__str__ = mock.Mock(side_effect=AssertionError("name evaluated"))
        self.assertEqual("", duplication.duplicate_project_destination_dir("", name))
        for name in ["", ".", "..", None, False]:
            self.assertEqual("", duplication.duplicate_project_destination_dir("Book/project.json", name))

    def test_predicate_exceptions_propagate_unchanged(self):
        for predicate in ["path_is_file", "path_is_dir", "path_exists"]:
            for error in [PermissionError("denied"), OSError("filesystem failure"), ValueError("invalid path")]:
                with self.subTest(predicate=predicate, error=error):
                    with self.assertRaises(type(error)) as raised:
                        self.plan(**{predicate: mock.Mock(side_effect=error)})
                    self.assertIs(error, raised.exception)
        error = PermissionError("collision check denied")
        with self.assertRaises(PermissionError) as raised:
            duplication.default_duplicate_project_dir_name("Book/project.json", path_exists=mock.Mock(side_effect=error))
        self.assertIs(error, raised.exception)

    def test_uses_exists_not_lexists_for_legacy_dangling_link_semantics(self):
        with mock.patch.object(os.path, "exists", return_value=False) as exists, mock.patch.object(os.path, "lexists", side_effect=AssertionError("lexists")):
            self.assertTrue(self.plan(path_exists=None)["valid"])
            self.assertEqual("Book_copy", duplication.default_duplicate_project_dir_name("Book/project.json"))
        self.assertEqual(2, exists.call_count)


class DuplicationDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = load_functions((ROOT / "tests/fixtures/project_directory_duplication_before.py").read_text(encoding="utf-8"), frozen=True)

    def evaluate(self, path, name, *, frozen, file=True, directory=True, exists=False, failure=None):
        calls = []
        def predicate(label, value):
            def check(path):
                calls.append((label, path))
                if failure == label:
                    raise PermissionError("denied at " + label)
                return value
            return check
        predicates = dict(isfile=predicate("file", file), isdir=predicate("dir", directory), exists=predicate("exists", exists))
        try:
            with ExitStack() as stack:
                if failure in ("abspath", "expanduser"):
                    stack.enter_context(mock.patch.object(os.path, failure, side_effect=OSError("path failure")))
                if frozen:
                    for key, value in predicates.items():
                        stack.enter_context(mock.patch.object(os.path, key, value))
                    self.before["st"] = SimpleNamespace(session_state=Session(project=object(), current_project_path=path))
                    result = self.before["duplicate_current_project_directory"](name)
                    if isinstance(result, tuple):
                        result = {"valid": result[0], "error": result[1]}
                else:
                    result = duplication.plan_project_directory_duplication(path, name, path_is_file=predicates["isfile"], path_is_dir=predicates["isdir"], path_exists=predicates["exists"])
                return result, calls
        except Exception as exc:
            return (type(exc), str(exc)), calls

    def test_preflight_results_fields_errors_and_read_order_match_frozen_base(self):
        paths = [None, "", False, 0, 42, b"Book/project.json", "project.json", "~/Book/project.json", "Book/../Book/project.json", " project.json ", Path("Book/project.json"), os.path.abspath(os.sep)]
        names = [None, False, 0, "", ".", "..", " ... ", "Copy", ' . A/B\\C<>:"|?* . ', "CON", "A\x00B", "みるく"]
        scenarios = [{}, {"file": False}, {"directory": False}, {"exists": True}] + [{"failure": key} for key in ["file", "dir", "exists", "expanduser", "abspath"]]
        for path in paths:
            for name in names:
                for scenario in scenarios:
                    with self.subTest(path=path, name=name, scenario=scenario):
                        self.assertEqual(self.evaluate(path, name, frozen=True, **scenario), self.evaluate(path, name, frozen=False, **scenario))

    def test_preview_helpers_match_frozen_base(self):
        for path in [None, "", "project.json", "~/Book/project.json", os.path.abspath(os.sep)]:
            for collisions in [0, 1, 3, 11]:
                before_calls, after_calls = [], []
                def exists(calls):
                    def check(path):
                        calls.append(path)
                        return len(calls) <= collisions
                    return check
                self.before["st"] = SimpleNamespace(session_state=Session(current_project_path=path))
                with mock.patch.object(os.path, "exists", exists(before_calls)):
                    expected = self.before["_default_duplicate_project_dir_name"]()
                actual = duplication.default_duplicate_project_dir_name(path, path_exists=exists(after_calls))
                self.assertEqual((expected, before_calls), (actual, after_calls))
            self.assertEqual(self.before["_source_project_directory"](), duplication.source_project_directory(path))
            for name in [None, "..", "Book/Copy", "CON", " .みるく. "]:
                self.assertEqual(self.before["_duplicate_project_destination_dir"](name), duplication.duplicate_project_destination_dir(path, name))

    def test_repeated_path_resolution_failures_match_frozen_base(self):
        # The legacy preflight normalizes the source again when resolving the
        # destination. Preserve failures during that second resolution as well.
        for operation, call_numbers in [("expanduser", [1, 2]), ("abspath", [1, 2, 3])]:
            original = getattr(os.path, operation)
            for fail_on in call_numbers:
                results = []
                for frozen in [True, False]:
                    calls = []
                    def resolve(path):
                        calls.append(path)
                        if len(calls) == fail_on:
                            raise OSError("resolution failed")
                        return original(path)
                    with mock.patch.object(os.path, operation, resolve):
                        result = self.evaluate("Book/project.json", "Copy", frozen=frozen)
                    results.append((result, calls))
                self.assertEqual(results[0], results[1])
                self.assertEqual((OSError, "resolution failed"), results[0][0][0])

    def test_app_copy_and_publication_statements_match_frozen_base(self):
        tails = []
        for source in [ROOT / "tests/fixtures/project_directory_duplication_before.py", ROOT / "app.py"]:
            tree = ast.parse(source.read_text(encoding="utf-8"))
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "duplicate_current_project_directory")
            save_index = next(i for i, stmt in enumerate(function.body) if isinstance(stmt, ast.Try))
            tails.append([ast.dump(stmt) for stmt in function.body[save_index:]])
        self.assertEqual(tails[0], tails[1])


class DuplicationAppWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_functions((ROOT / "app.py").read_text(encoding="utf-8"))

    def setUp(self):
        self.events = []
        self.session = Session(project=object(), current_project_path="projects/Book/project.json")
        self.app["st"] = SimpleNamespace(session_state=self.session)
        def event(label, result=None):
            def run(*args, **kwargs):
                self.events.append((label, args, kwargs))
                return result
            return mock.Mock(side_effect=run)
        self.app.update(
            save_project_to_json=event("save"),
            ensure_current_project_folder_layout=event("layout"),
            shutil=SimpleNamespace(copytree=event("copy"), ignore_patterns=shutil.ignore_patterns),
            _find_copied_project_json=event("find", os.path.abspath("projects/Copy/project.json")),
            load_project_json_into_session=event("load", True),
            request_project_directory_discovery_refresh=event("refresh"),
        )
        for predicate, value in [("isfile", True), ("isdir", True), ("exists", False)]:
            self.enterContext(mock.patch.object(os.path, predicate, return_value=value))

    def test_real_imports_and_successful_lifecycle_order(self):
        self.assertIs(duplication.plan_project_directory_duplication, self.app["plan_project_directory_duplication"])
        self.assertIs(duplication.sanitize_duplicate_project_dir_name, self.app["_sanitize_duplicate_project_dir_name"])
        source = os.path.abspath(self.session.current_project_path)
        destination = os.path.abspath("projects/Copy")
        self.assertEqual((source, os.path.dirname(source)), self.app["_source_project_directory"]())
        self.assertEqual("Book_copy", self.app["_default_duplicate_project_dir_name"]())
        self.assertEqual(destination, self.app["_duplicate_project_destination_dir"]("Copy"))
        success, message = self.app["duplicate_current_project_directory"]("Copy")
        self.assertTrue(success)
        self.assertEqual("プロジェクトディレクトリを複製して開きました: " + os.path.join(destination, "project.json"), message)
        self.assertEqual(["save", "layout", "copy", "find", "load", "refresh"], [event[0] for event in self.events])
        self.app["save_project_to_json"].assert_called_once_with(self.session.project, source)
        self.assertEqual((os.path.dirname(source), destination), self.events[2][1])
        ignore = self.events[2][2]["ignore"]
        ignored = [".promptgraph_cache", ".draft.tmp", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".DS_Store", "Thumbs.db"]
        self.assertEqual(set(ignored), ignore(source, ignored + ["refs", "project.json"]))
        self.assertEqual("project duplicated", self.session.autosave_feedback)

    def test_blocked_destination_never_saves_or_copies(self):
        with mock.patch.object(os.path, "exists", return_value=True):
            self.assertEqual((False, "複製先ディレクトリは既に存在します。"), self.app["duplicate_current_project_directory"]("Copy"))
        self.assertEqual([], self.events)

    def test_no_project_guard_precedes_path_normalization(self):
        self.session.project = None
        self.session.current_project_path = 42
        self.assertEqual((False, "先にプロジェクトを読み込むか作成してください。"), self.app["duplicate_current_project_directory"]("Copy"))
        self.assertEqual([], self.events)

    def test_preflight_exception_is_not_wrapped_as_save_failure(self):
        with mock.patch.object(os.path, "isfile", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(PermissionError, "denied"):
                self.app["duplicate_current_project_directory"]("Copy")
        self.assertEqual([], self.events)

    def test_save_failure_prevents_copy_and_publication(self):
        self.app["save_project_to_json"].side_effect = OSError("save failed")
        self.assertEqual((False, "複製前のプロジェクト保存に失敗しました: save failed"), self.app["duplicate_current_project_directory"]("Copy"))
        self.assertEqual([], self.events)

    def test_copy_failure_still_propagates(self):
        self.app["shutil"].copytree.side_effect = FileExistsError("racing destination")
        with self.assertRaisesRegex(FileExistsError, "racing destination"):
            self.app["duplicate_current_project_directory"]("Copy")
        self.assertEqual(["save", "layout"], [event[0] for event in self.events])

    def test_failed_load_does_not_refresh_discovery_or_publish_feedback(self):
        self.app["load_project_json_into_session"].side_effect = None
        self.app["load_project_json_into_session"].return_value = False
        self.assertEqual((False, "複製先project JSONを開けませんでした。"), self.app["duplicate_current_project_directory"]("Copy"))
        self.app["request_project_directory_discovery_refresh"].assert_not_called()
        self.assertNotIn("autosave_feedback", self.session)


if __name__ == "__main__":
    unittest.main()
