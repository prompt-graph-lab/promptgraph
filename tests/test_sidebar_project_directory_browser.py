import ast
import os
import types
import unittest
from pathlib import Path


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class SidebarProjectDirectoryBrowserTests(unittest.TestCase):
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
        cls.project_open_start = cls.app_source.index(
            'with st.sidebar.expander("プロジェクトを開く", expanded=False):'
        )
        cls.advanced_start = cls.app_source.index(
            'with st.sidebar.expander("Advanced", expanded=False):',
            cls.project_open_start,
        )
        cls.project_open_source = cls.app_source[
            cls.project_open_start:cls.advanced_start
        ]

    def _source(self, name):
        return ast.get_source_segment(self.app_source, self.functions[name])

    def _load(self, *names, namespace):
        module = ast.Module(
            body=[self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def test_browser_has_one_sidebar_owner_before_recent(self):
        self.assertEqual(2, self.app_source.count("render_project_directory_browser()"))
        browser_call = self.project_open_source.index("render_project_directory_browser()")
        recent_heading = self.project_open_source.index("**最近のプロジェクト**")
        self.assertLess(browser_call, recent_heading)
        self.assertIn("st.divider()", self.project_open_source[browser_call:recent_heading])

        management = self._source("render_project_management_workspace")
        self.assertNotIn("render_project_directory_browser", management)
        for body_marker in (
            "def render_gallery_mode",
            "def render_overall_edit_mode",
            "def render_focus_edit_mode",
        ):
            if body_marker in self.app_source:
                start = self.app_source.index(body_marker)
                next_def = self.app_source.find("\ndef ", start + 1)
                body = self.app_source[start:next_def if next_def >= 0 else None]
                self.assertNotIn("render_project_directory_browser", body)

    def test_browser_uses_effective_root_cache_and_explicit_refresh(self):
        source = self._source("render_project_directory_browser")
        self.assertIn("default_projects_dir()", source)
        self.assertIn("normalize_project_discovery_path", source)
        self.assertIn('st.code(project_root or default_projects_dir()', source)
        self.assertIn('"一覧を更新"', source)
        self.assertIn('key="refresh_project_directory_browser"', source)
        self.assertIn("request_project_directory_discovery_refresh()", source)
        self.assertIn("_get_project_directory_discovery_snapshot(project_root)", source)

        cache_source = self._source("_get_project_directory_discovery_snapshot")
        self.assertIn("resolve_cached_project_discovery", cache_source)
        self.assertIn("project_directory_discovery_cache", cache_source)
        self.assertIn("project_directory_discovery_refresh_generation", cache_source)
        self.assertIn("current_project_path", cache_source)
        for forbidden in (
            "os.walk",
            ".rglob",
            "glob(",
            "load_project_from_json",
            "load_project_json_into_session",
            "build_graph",
            "save_project_to_json",
            "push_history",
            "save_settings",
        ):
            self.assertNotIn(forbidden, cache_source)

    def test_refresh_request_only_increments_session_generation(self):
        session_state = _SessionState(
            project_directory_discovery_refresh_generation=2,
            project={"keep": True},
            history=["keep"],
            settings={"keep": True},
            current_project_path="keep.json",
        )
        namespace = self._load(
            "request_project_directory_discovery_refresh",
            namespace={"st": types.SimpleNamespace(session_state=session_state)},
        )

        namespace["request_project_directory_discovery_refresh"]()

        self.assertEqual(3, session_state.project_directory_discovery_refresh_generation)
        self.assertEqual({"keep": True}, session_state.project)
        self.assertEqual(["keep"], session_state.history)
        self.assertEqual({"keep": True}, session_state.settings)
        self.assertEqual("keep.json", session_state.current_project_path)

    def test_root_change_and_removed_selection_normalize_without_opening(self):
        root_a = os.path.abspath("projects-a")
        root_b = os.path.abspath("projects-b")
        entry_a = os.path.join(root_a, "alpha", "project.json")
        entry_b = os.path.join(root_b, "beta", "project.json")
        session_state = _SessionState(
            project_directory_selection_root=os.path.realpath(root_a),
            project_directory_selected_path=entry_a,
            project={"keep": True},
            history=["keep"],
        )
        namespace = self._load(
            "_normalize_project_directory_browser_selection",
            namespace={
                "st": types.SimpleNamespace(session_state=session_state),
                "normalize_project_discovery_path": lambda value: os.path.realpath(
                    os.path.abspath(value)
                ),
            },
        )

        selected = namespace["_normalize_project_directory_browser_selection"](
            root_b,
            [{"project_path": entry_b}],
        )

        self.assertEqual(entry_b, selected)
        self.assertEqual(entry_b, session_state.project_directory_selected_path)
        self.assertEqual({"keep": True}, session_state.project)
        self.assertEqual(["keep"], session_state.history)

        selected = namespace["_normalize_project_directory_browser_selection"](
            root_b,
            [],
        )
        self.assertEqual("", selected)
        self.assertNotIn("project_directory_selected_path", session_state)

    def test_ui_distinguishes_projects_forks_current_missing_and_diagnostics(self):
        source = self._source("render_project_directory_browser")
        for expected in (
            "Projects:",
            "Derived Projects:",
            "Project rootはまだ存在しません",
            "Project rootがディレクトリではありません",
            "Project root内にPromptGraph Projectが見つかりませんでした",
            "Derived Project manifest unavailable",
            "現在開いています",
            "選択したプロジェクトを開く",
            "Discovery",
        ):
            self.assertIn(expected, source)
        self.assertIn('key="project_directory_selected_path"', source)
        self.assertIn('key="open_selected_project_directory"', source)

    def test_open_revalidates_then_uses_only_existing_authoritative_loader(self):
        source = self._source("render_project_directory_browser")
        open_handler = source.index('"選択したプロジェクトを開く"')
        handler_source = source[open_handler:]
        self.assertGreaterEqual(
            source.count("validate_project_discovery_open_path("),
            2,
        )
        self.assertLess(
            handler_source.index("validate_project_discovery_open_path("),
            handler_source.index("load_project_json_into_session(selected_open_path)"),
        )
        self.assertIn("except Exception as exc", handler_source)
        self.assertIn("st.error", handler_source)
        self.assertEqual(1, handler_source.count("load_project_json_into_session("))
        self.assertNotIn("load_project_from_json", handler_source)
        self.assertNotIn("build_graph", handler_source)
        self.assertNotIn("push_history", handler_source)
        self.assertNotIn("save_project_to_json", handler_source)

    def test_successful_app_owned_creation_requests_future_refresh(self):
        new_project = self._source("render_new_project_management_section")
        self.assertLess(
            new_project.index("set_new_workspace_project(project_path)"),
            new_project.index("request_project_directory_discovery_refresh()"),
        )

        duplicate = self._source("duplicate_current_project_directory")
        self.assertLess(
            duplicate.index("load_project_json_into_session(destination_project_path)"),
            duplicate.index("request_project_directory_discovery_refresh()"),
        )
        self.assertGreater(
            duplicate.index("request_project_directory_discovery_refresh()"),
            duplicate.index("except Exception as exc"),
        )

        fork = self._source("render_lightweight_fork_preview_section")
        success_branch = fork.index('if result.get("success"):')
        request = fork.index("request_project_directory_discovery_refresh()", success_branch)
        self.assertGreater(request, success_branch)

    def test_save_as_requests_refresh_only_for_new_file_inside_effective_root(self):
        commit_start = self.app_source.index(
            "def _commit_project_save_as("
        )
        commit_end = self.app_source.index(
            "def confirm_project_save_as_overwrite(",
            commit_start,
        )
        commit = self.app_source[commit_start:commit_end]
        self.assertIn("not target_existed", commit)
        self.assertIn("project_discovery_path_is_within", commit)
        self.assertIn("default_projects_dir()", commit)
        self.assertIn("request_project_directory_discovery_refresh()", commit)
        self.assertLess(
            commit.index(
                "save_project_to_json(st.session_state.project, normalized_path)"
            ),
            commit.index("request_project_directory_discovery_refresh()"),
        )

    def test_recent_and_advanced_owners_and_widget_keys_remain_unique(self):
        self.assertEqual(1, self.app_source.count('key="project_directory_selected_path"'))
        self.assertEqual(1, self.app_source.count('key="open_selected_project_directory"'))
        self.assertEqual(1, self.app_source.count('key="refresh_project_directory_browser"'))
        self.assertEqual(1, self.app_source.count('key="open_project_path"'))
        self.assertEqual(1, self.app_source.count('key="save_project_json_path"'))
        self.assertEqual(1, self.app_source.count('st.button("最近のプロジェクトを開く")'))


if __name__ == "__main__":
    unittest.main()
