import ast
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from core.io import load_project_from_json, save_project_to_json
from core.project import Project, PromptLine


def _line(text="current prompt"):
    return PromptLine(
        id="line-1",
        original_file_name="001.png",
        original_index=0,
        current_index=0,
        original_text="original prompt",
        current_text=text,
        tokens=text.split(),
        negative_prompt="",
    )


class ProjectSaveAsSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_path = Path(__file__).resolve().parents[1] / "app.py"
        cls.app_source = cls.app_path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.app_source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        namespace = {
            "os": os,
            "hashlib": hashlib,
            "copy": copy,
        }
        for name in (
            "normalize_project_save_as_path",
            "inspect_project_save_as_destination",
            "build_project_save_as_pending_overwrite",
            "project_save_as_confirmation_is_fresh",
        ):
            node = cls.functions[name]
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            exec(compile(module, "app.py", "exec"), namespace)
        cls.namespace = namespace

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_normalization_and_unicode_snapshot_are_stable(self):
        target = self.root / "作品" / "カスタム.json"
        target.parent.mkdir()
        target.write_bytes(b'{"marker":"before"}\n')

        normalize = self.namespace["normalize_project_save_as_path"]
        inspect = self.namespace["inspect_project_save_as_destination"]
        absolute_snapshot = inspect(str(target))
        previous_cwd = os.getcwd()
        os.chdir(self.root)
        try:
            relative_snapshot = inspect(Path("作品") / "カスタム.json")
            normalized_relative = normalize(
                Path("作品") / "カスタム.json"
            )
        finally:
            os.chdir(previous_cwd)

        self.assertEqual(normalize(str(target)), normalized_relative)
        self.assertEqual(absolute_snapshot, relative_snapshot)
        self.assertEqual("file", absolute_snapshot["kind"])
        self.assertEqual(
            hashlib.sha256(target.read_bytes()).hexdigest(),
            absolute_snapshot["sha256"],
        )

    def test_snapshot_detects_bytes_and_type_changes(self):
        target = self.root / "target.json"
        target.write_bytes(b'{"marker":"before"}\n')
        inspect = self.namespace["inspect_project_save_as_destination"]

        before = inspect(target)
        replacement = b'{"marker":"befOre"}\n'
        self.assertEqual(before["size"], len(replacement))
        target.write_bytes(replacement)
        os.utime(
            target,
            ns=(before["mtime_ns"], before["mtime_ns"]),
        )
        after = inspect(target)
        self.assertNotEqual(before, after)
        self.assertEqual(before["size"], after["size"])
        self.assertEqual(before["mtime_ns"], after["mtime_ns"])
        self.assertNotEqual(before["sha256"], after["sha256"])

        target.unlink()
        missing = inspect(target)
        self.assertEqual("missing", missing["kind"])
        target.mkdir()
        directory = inspect(target)
        self.assertEqual("directory", directory["kind"])

    def test_confirmation_rejects_malformed_target_and_source_changes(self):
        target = self.root / "target.json"
        target.write_bytes(b'{"marker":"before"}\n')
        source = self.root / "source.json"
        project = object()
        inspect = self.namespace["inspect_project_save_as_destination"]
        build = self.namespace["build_project_save_as_pending_overwrite"]
        fresh = self.namespace["project_save_as_confirmation_is_fresh"]
        pending = build(inspect(target), source, project)

        self.assertTrue(fresh(pending, target, source, project)[0])
        self.assertFalse(fresh({}, target, source, project)[0])
        self.assertFalse(
            fresh(pending, self.root / "other.json", source, project)[0]
        )
        self.assertFalse(
            fresh(
                pending,
                target,
                self.root / "other-source.json",
                project,
            )[0]
        )
        self.assertFalse(fresh(pending, target, source, object())[0])

    def test_missing_snapshot_cannot_authorize_a_newly_occupied_target(self):
        target = self.root / "target.json"
        source = self.root / "source.json"
        project = object()
        inspect = self.namespace["inspect_project_save_as_destination"]
        build = self.namespace["build_project_save_as_pending_overwrite"]
        fresh = self.namespace["project_save_as_confirmation_is_fresh"]
        pending = build(inspect(target), source, project)

        target.write_bytes(b'{"appeared":true}\n')

        self.assertFalse(fresh(pending, target, source, project)[0])
        self.assertEqual("file", fresh(pending, target, source, project)[1]["kind"])

    def test_transition_owner_and_widget_keys_are_centralized(self):
        reset_source = ast.get_source_segment(
            self.app_source,
            self.functions["reset_graph_project_session_state"],
        )
        self.assertIn(
            "reset_project_save_as_confirmation_state()",
            reset_source,
        )
        for key in (
            'key="save_project_as_json_button"',
            'key="project_save_as_confirm_overwrite_button"',
            'key="project_save_as_cancel_overwrite_button"',
            "key=PROJECT_SAVE_AS_OVERWRITE_ACK_WIDGET_KEY",
        ):
            self.assertEqual(1, self.app_source.count(key))


class ProjectSaveAsOverwriteAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.app_path = cls.repo_root / "app.py"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def _project(self, text="current prompt"):
        project = Project(source_directory=str(self.root))
        project.prompt_lines = [_line(text)]
        project.line_map = {
            line.id: line for line in project.prompt_lines
        }
        return project

    def _start_app(self, name="CurrentProject"):
        project_dir = self.root / name
        project_dir.mkdir()
        project_path = project_dir / "project.json"
        project = self._project()
        save_project_to_json(project, project_path)

        at = AppTest.from_file(
            str(self.app_path),
            default_timeout=30,
        ).run(timeout=30)
        at.session_state["project"] = project
        at.session_state["current_project_path"] = str(project_path)
        at.session_state["startup_project_open_attempted"] = True
        at.session_state["history"] = ["keep-history"]
        at.run(timeout=30)
        return at, project_path, project

    @staticmethod
    def _element_by_key(elements, key):
        return next(element for element in elements if element.key == key)

    @staticmethod
    def _state_value(at, key, default=None):
        return at.session_state[key] if key in at.session_state else default

    @staticmethod
    def _destination_bytes(marker):
        return json.dumps(
            {
                "source_directory": "",
                "prompt_lines": [],
                "marker": marker,
            },
            ensure_ascii=False,
        ).encode("utf-8")

    def _existing_destination(self, name="ExistingProject"):
        destination_dir = self.root / name
        destination_dir.mkdir()
        destination = destination_dir / "custom.json"
        destination.write_bytes(self._destination_bytes("keep-before"))
        return destination

    def _arm(self, at, destination):
        self._element_by_key(
            at.text_input,
            "save_project_json_path",
        ).set_value(str(destination)).run(timeout=30)
        self._element_by_key(
            at.button,
            "save_project_as_json_button",
        ).click().run(timeout=30)
        return at

    def _acknowledge(self, at):
        self._element_by_key(
            at.checkbox,
            "_project_save_as_overwrite_acknowledged_widget",
        ).check().run(timeout=30)
        return at

    def _capture_success_state(self, at):
        return {
            "path": at.session_state["current_project_path"],
            "settings": copy.deepcopy(dict(at.session_state["settings"])),
            "history": copy.deepcopy(at.session_state["history"]),
            "last_saved_at": self._state_value(at, "last_saved_at", ""),
            "autosave_feedback": self._state_value(
                at,
                "autosave_feedback",
                "",
            ),
            "discovery_generation": self._state_value(
                at,
                "project_directory_discovery_refresh_generation",
                0,
            ),
            "assets_reset": self._state_value(
                at,
                "project_assets_confirm_reset_pending",
            ),
        }

    def _assert_no_success_transition(self, at, before):
        self.assertEqual(before["path"], at.session_state["current_project_path"])
        self.assertEqual(before["settings"], dict(at.session_state["settings"]))
        self.assertEqual(before["history"], at.session_state["history"])
        self.assertEqual(
            before["last_saved_at"],
            self._state_value(at, "last_saved_at", ""),
        )
        self.assertEqual(
            before["autosave_feedback"],
            self._state_value(at, "autosave_feedback", ""),
        )
        self.assertEqual(
            before["discovery_generation"],
            self._state_value(
                at,
                "project_directory_discovery_refresh_generation",
                0,
            ),
        )
        self.assertEqual(
            before["assets_reset"],
            self._state_value(
                at,
                "project_assets_confirm_reset_pending",
            ),
        )
        self.assertFalse(
            any(
                "プロジェクトを保存しました" in str(item.value)
                for item in at.success
            )
        )

    def test_existing_first_click_is_pure_and_shows_exact_target(self):
        at, _project_path, _project = self._start_app()
        destination = self._existing_destination()
        before_bytes = destination.read_bytes()
        before_digest = hashlib.sha256(before_bytes).hexdigest()
        before_state = self._capture_success_state(at)

        with mock.patch("core.io.json.dump") as dump_mock:
            self._arm(at, destination)

        self.assertEqual([], list(at.exception))
        dump_mock.assert_not_called()
        self.assertEqual(before_bytes, destination.read_bytes())
        self.assertEqual(
            before_digest,
            hashlib.sha256(destination.read_bytes()).hexdigest(),
        )
        self._assert_no_success_transition(at, before_state)
        self.assertIn("project_save_as_pending_overwrite", at.session_state)
        self.assertTrue(
            any(
                "既存のProject JSONがあります" in str(item.value)
                for item in at.warning
            )
        )
        self.assertTrue(
            any(
                os.path.abspath(destination) == str(item.value)
                for item in at.code
            )
        )
        self.assertTrue(
            self._element_by_key(
                at.button,
                "project_save_as_confirm_overwrite_button",
            ).disabled
        )

    def test_cancel_is_non_destructive_and_keeps_entered_path(self):
        at, _project_path, _project = self._start_app()
        destination = self._existing_destination()
        before_bytes = destination.read_bytes()
        before_state = self._capture_success_state(at)
        self._arm(at, destination)
        self._acknowledge(at)

        self._element_by_key(
            at.button,
            "project_save_as_cancel_overwrite_button",
        ).click().run(timeout=30)

        self.assertEqual(before_bytes, destination.read_bytes())
        self._assert_no_success_transition(at, before_state)
        self.assertNotIn("project_save_as_pending_overwrite", at.session_state)
        self.assertNotIn(
            "project_save_as_overwrite_acknowledged",
            at.session_state,
        )
        self.assertEqual(
            str(destination),
            self._element_by_key(
                at.text_input,
                "save_project_json_path",
            ).value,
        )

    def test_confirmed_overwrite_switches_only_after_success(self):
        at, project_path, _project = self._start_app()
        destination = self._existing_destination()
        before_bytes = destination.read_bytes()
        self._arm(at, destination)
        self._acknowledge(at)

        self._element_by_key(
            at.button,
            "project_save_as_confirm_overwrite_button",
        ).click().run(timeout=30)

        self.assertEqual([], list(at.exception))
        self.assertNotEqual(before_bytes, destination.read_bytes())
        self.assertNotIn(b"keep-before", destination.read_bytes())
        reopened = load_project_from_json(destination)
        self.assertEqual("current prompt", reopened.prompt_lines[0].current_text)
        self.assertEqual(
            os.path.abspath(destination),
            at.session_state["current_project_path"],
        )
        self.assertNotEqual(str(project_path), at.session_state["current_project_path"])
        self.assertEqual(
            os.path.abspath(destination),
            at.session_state["settings"]["last_project"],
        )
        self.assertEqual(
            os.path.abspath(destination),
            at.session_state["settings"]["recent_projects"][0]["path"],
        )
        self.assertNotIn("project_save_as_pending_overwrite", at.session_state)
        self.assertNotIn(
            "_project_save_as_overwrite_acknowledged_widget",
            at.session_state,
        )
        self.assertTrue(
            any(
                "プロジェクトを保存しました" in str(item.value)
                for item in at.success
            )
        )

    def test_path_change_invalidates_confirmation_without_writing_either_target(self):
        at, _project_path, _project = self._start_app()
        destination_a = self._existing_destination("DestinationA")
        destination_b = self._existing_destination("DestinationB")
        before_a = destination_a.read_bytes()
        before_b = destination_b.read_bytes()
        before_state = self._capture_success_state(at)
        self._arm(at, destination_a)
        self._acknowledge(at)

        self._element_by_key(
            at.text_input,
            "save_project_json_path",
        ).set_value(str(destination_b)).run(timeout=30)

        self.assertEqual(before_a, destination_a.read_bytes())
        self.assertEqual(before_b, destination_b.read_bytes())
        self._assert_no_success_transition(at, before_state)
        self.assertNotIn("project_save_as_pending_overwrite", at.session_state)
        self.assertFalse(
            any(
                item.key == "project_save_as_confirm_overwrite_button"
                for item in at.button
            )
        )
        self.assertTrue(
            any(
                "上書き対象が確認後に変更されました" in str(item.value)
                for item in at.warning
            )
        )

    def test_external_file_change_invalidates_confirmation(self):
        at, _project_path, _project = self._start_app()
        destination = self._existing_destination()
        before_state = self._capture_success_state(at)
        self._arm(at, destination)
        self._acknowledge(at)
        external_bytes = self._destination_bytes("external-change")
        destination.write_bytes(external_bytes)

        self._element_by_key(
            at.button,
            "project_save_as_confirm_overwrite_button",
        ).click().run(timeout=30)

        self.assertEqual(external_bytes, destination.read_bytes())
        self._assert_no_success_transition(at, before_state)
        self.assertNotIn("project_save_as_pending_overwrite", at.session_state)
        self.assertTrue(
            any(
                "上書き対象が確認後に変更されました" in str(item.value)
                for item in at.warning
            )
        )

    def test_disappeared_destination_requires_fresh_one_click_save(self):
        at, _project_path, _project = self._start_app()
        destination = self._existing_destination()
        before_state = self._capture_success_state(at)
        self._arm(at, destination)
        self._acknowledge(at)
        destination.unlink()

        self._element_by_key(
            at.button,
            "project_save_as_confirm_overwrite_button",
        ).click().run(timeout=30)

        self.assertFalse(destination.exists())
        self._assert_no_success_transition(at, before_state)
        self._element_by_key(
            at.button,
            "save_project_as_json_button",
        ).click().run(timeout=30)
        self.assertTrue(destination.is_file())
        self.assertEqual(
            os.path.abspath(destination),
            at.session_state["current_project_path"],
        )

    def test_file_type_or_source_project_change_is_rejected(self):
        for change_kind in ("directory", "source"):
            with self.subTest(change_kind=change_kind):
                at, _project_path, _project = self._start_app(
                    f"Current-{change_kind}"
                )
                destination = self._existing_destination(
                    f"Destination-{change_kind}"
                )
                before_state = self._capture_success_state(at)
                self._arm(at, destination)
                self._acknowledge(at)
                if change_kind == "directory":
                    destination.unlink()
                    destination.mkdir()
                else:
                    at.session_state["project"] = self._project("new source")

                self._element_by_key(
                    at.button,
                    "project_save_as_confirm_overwrite_button",
                ).click().run(timeout=30)

                if change_kind == "directory":
                    self.assertTrue(destination.is_dir())
                else:
                    self.assertIn(b"keep-before", destination.read_bytes())
                self._assert_no_success_transition(at, before_state)
                self.assertNotIn(
                    "project_save_as_pending_overwrite",
                    at.session_state,
                )

    def test_current_project_path_still_requires_confirmation(self):
        at, project_path, _project = self._start_app()
        before = project_path.read_bytes()

        self._element_by_key(
            at.text_input,
            "save_project_json_path",
        ).set_value(str(project_path)).run(timeout=30)
        self._element_by_key(
            at.button,
            "save_project_as_json_button",
        ).click().run(timeout=30)

        self.assertEqual(before, project_path.read_bytes())
        self.assertIn("project_save_as_pending_overwrite", at.session_state)

    def test_new_unicode_custom_destination_remains_one_click(self):
        at, _project_path, _project = self._start_app()
        destination_dir = self.root / "新しい作品"
        destination_dir.mkdir()
        destination = destination_dir / "カスタム名.json"

        self._element_by_key(
            at.text_input,
            "save_project_json_path",
        ).set_value(str(destination)).run(timeout=30)
        self._element_by_key(
            at.button,
            "save_project_as_json_button",
        ).click().run(timeout=30)

        self.assertTrue(destination.is_file())
        self.assertEqual(
            os.path.abspath(destination),
            at.session_state["current_project_path"],
        )
        self.assertNotIn("project_save_as_pending_overwrite", at.session_state)
        self.assertTrue(
            any(
                "プロジェクトを保存しました" in str(item.value)
                for item in at.success
            )
        )

    def test_confirmed_atomic_failure_preserves_target_and_success_state(self):
        at, _project_path, _project = self._start_app()
        destination = self._existing_destination()
        before_bytes = destination.read_bytes()
        before_state = self._capture_success_state(at)
        self._arm(at, destination)
        self._acknowledge(at)

        def partial_failure(_data, handle, **_kwargs):
            handle.write('{"partial":')
            handle.flush()
            raise OSError("synthetic confirmed overwrite failure")

        with mock.patch(
            "core.io.json.dump",
            side_effect=partial_failure,
        ):
            self._element_by_key(
                at.button,
                "project_save_as_confirm_overwrite_button",
            ).click().run(timeout=30)

        self.assertEqual(before_bytes, destination.read_bytes())
        json.loads(destination.read_text(encoding="utf-8"))
        self._assert_no_success_transition(at, before_state)
        self.assertIn("project_save_as_pending_overwrite", at.session_state)
        self.assertNotIn(
            "project_save_as_overwrite_acknowledged",
            at.session_state,
        )
        self.assertTrue(
            any(
                "Project JSONを保存できませんでした" in str(item.value)
                for item in at.error
            )
        )
        self.assertEqual(
            [],
            list(destination.parent.glob(f".{destination.name}.*.tmp")),
        )

    def test_successful_project_open_clears_pending_confirmation(self):
        at, _project_path, _project = self._start_app()
        destination = self._existing_destination()
        next_project_dir = self.root / "NextProject"
        next_project_dir.mkdir()
        next_project_path = next_project_dir / "project.json"
        save_project_to_json(self._project("next project"), next_project_path)
        self._arm(at, destination)
        self._acknowledge(at)

        self._element_by_key(
            at.text_input,
            "open_project_path",
        ).set_value(str(next_project_path)).run(timeout=30)
        next(
            button
            for button in at.button
            if button.label == "JSONファイルを開く"
        ).click().run(timeout=30)

        self.assertEqual([], list(at.exception))
        self.assertEqual(
            os.path.abspath(next_project_path),
            at.session_state["current_project_path"],
        )
        self.assertNotIn("project_save_as_pending_overwrite", at.session_state)
        self.assertNotIn(
            "project_save_as_overwrite_acknowledged",
            at.session_state,
        )
        self.assertNotIn(
            "_project_save_as_overwrite_acknowledged_widget",
            at.session_state,
        )
        self.assertIn(b"keep-before", destination.read_bytes())


if __name__ == "__main__":
    unittest.main()
