import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class GraphEditIllustrationBrowserStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_path = Path(__file__).resolve().parents[1] / "app.py"
        cls.source = cls.app_path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _source(self, name):
        return ast.get_source_segment(self.source, self.functions[name])

    def _load(self, names, namespace):
        module = ast.Module(
            body=[self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def test_reset_restores_only_browser_defaults_and_widget_mirror(self):
        state = _SessionState(
            graph_edit_illustration_filter="scene:old",
            graph_edit_illustration_page=7,
            graph_edit_illustration_page_size=48,
            graph_edit_collapsed_group_keys={"scene:scene_old"},
            graph_edit_illustration_browser_notice="old notice",
            graph_edit_illustration_browser_page_line_ids=["line_7"],
            _graph_edit_illustration_filter_widget="scene:old",
            _graph_edit_illustration_page_size_widget=48,
            _graph_edit_illustration_page_top=7,
            gallery_page=9,
            highlighted_line_id="line_7",
        )
        namespace = self._load(
            ["reset_graph_edit_illustration_browser_state"],
            {
                "st": SimpleNamespace(session_state=state),
                "GRAPH_EDIT_BROWSER_FILTER_KEY": "graph_edit_illustration_filter",
                "GRAPH_EDIT_BROWSER_PAGE_KEY": "graph_edit_illustration_page",
                "GRAPH_EDIT_BROWSER_PAGE_SIZE_KEY": "graph_edit_illustration_page_size",
                "GRAPH_EDIT_BROWSER_COLLAPSED_KEY": "graph_edit_collapsed_group_keys",
                "GRAPH_EDIT_BROWSER_NOTICE_KEY": "graph_edit_illustration_browser_notice",
                "GRAPH_EDIT_BROWSER_PAGE_LINE_IDS_KEY": "graph_edit_illustration_browser_page_line_ids",
                "GRAPH_EDIT_BROWSER_FILTER_WIDGET_KEY": "_graph_edit_illustration_filter_widget",
                "GRAPH_EDIT_BROWSER_PAGE_SIZE_WIDGET_KEY": "_graph_edit_illustration_page_size_widget",
                "GRAPH_EDIT_BROWSER_PAGE_TOP_WIDGET_KEY": "_graph_edit_illustration_page_top",
                "GRAPH_EDIT_BROWSER_FILTER_ALL": "all",
                "GRAPH_EDIT_BROWSER_DEFAULT_PAGE_SIZE": 12,
            },
        )
        namespace["reset_graph_edit_illustration_browser_state"]()
        self.assertEqual("all", state["graph_edit_illustration_filter"])
        self.assertEqual(1, state["graph_edit_illustration_page"])
        self.assertEqual(12, state["graph_edit_illustration_page_size"])
        self.assertEqual(set(), state["graph_edit_collapsed_group_keys"])
        self.assertEqual("", state["graph_edit_illustration_browser_notice"])
        self.assertEqual([], state["graph_edit_illustration_browser_page_line_ids"])
        self.assertNotIn("_graph_edit_illustration_filter_widget", state)
        self.assertNotIn("_graph_edit_illustration_page_size_widget", state)
        self.assertNotIn("_graph_edit_illustration_page_top", state)
        self.assertEqual(9, state["gallery_page"])
        self.assertEqual("line_7", state["highlighted_line_id"])

    def test_canonical_graph_project_reset_owns_shared_project_resets(self):
        save_as_reset = Mock()
        widget_reset = Mock()
        browser_reset = Mock()
        namespace = self._load(
            ["reset_graph_project_session_state"],
            {
                "reset_project_save_as_confirmation_state": save_as_reset,
                "reset_graph_control_widget_state": widget_reset,
                "reset_graph_edit_illustration_browser_state": browser_reset,
            },
        )
        namespace["reset_graph_project_session_state"]()
        save_as_reset.assert_called_once_with()
        widget_reset.assert_called_once_with()
        browser_reset.assert_called_once_with()

    def test_filter_and_page_size_callbacks_do_not_touch_project_or_gallery(self):
        state = _SessionState(
            graph_edit_illustration_page=4,
            _graph_edit_illustration_filter_widget="scene:scene_a",
            _graph_edit_illustration_page_size_widget=24,
            _graph_edit_illustration_page_top=4,
            graph_edit_illustration_browser_notice="notice",
            project=object(),
            gallery_page=8,
            highlighted_line_id="line_4",
            selected_node_ids=["node"],
        )
        namespace = self._load(
            [
                "_reset_graph_edit_browser_page",
                "_on_graph_edit_browser_filter_changed",
                "_on_graph_edit_browser_page_size_changed",
            ],
            {
                "st": SimpleNamespace(session_state=state),
                "GRAPH_EDIT_BROWSER_PAGE_KEY": "graph_edit_illustration_page",
                "GRAPH_EDIT_BROWSER_FILTER_KEY": "graph_edit_illustration_filter",
                "GRAPH_EDIT_BROWSER_PAGE_SIZE_KEY": "graph_edit_illustration_page_size",
                "GRAPH_EDIT_BROWSER_FILTER_WIDGET_KEY": "_graph_edit_illustration_filter_widget",
                "GRAPH_EDIT_BROWSER_PAGE_SIZE_WIDGET_KEY": "_graph_edit_illustration_page_size_widget",
                "GRAPH_EDIT_BROWSER_PAGE_TOP_WIDGET_KEY": "_graph_edit_illustration_page_top",
                "GRAPH_EDIT_BROWSER_NOTICE_KEY": "graph_edit_illustration_browser_notice",
                "GRAPH_EDIT_BROWSER_FILTER_ALL": "all",
                "GRAPH_EDIT_BROWSER_PAGE_SIZE_OPTIONS": (12, 24, 48),
                "GRAPH_EDIT_BROWSER_DEFAULT_PAGE_SIZE": 12,
                "block_graph_edit_browser_navigation_if_unsaved": lambda _project: False,
            },
        )
        project = state["project"]
        namespace["_on_graph_edit_browser_filter_changed"]()
        self.assertEqual("scene:scene_a", state["graph_edit_illustration_filter"])
        self.assertEqual(1, state["graph_edit_illustration_page"])
        self.assertEqual("", state["graph_edit_illustration_browser_notice"])
        namespace["_on_graph_edit_browser_page_size_changed"]()
        self.assertEqual(24, state["graph_edit_illustration_page_size"])
        self.assertIs(project, state["project"])
        self.assertEqual(8, state["gallery_page"])
        self.assertEqual("line_4", state["highlighted_line_id"])
        self.assertEqual(["node"], state["selected_node_ids"])

    def test_explicit_reveal_callback_changes_only_browser_location(self):
        project = object()
        state = _SessionState(
            graph_edit_illustration_filter="all",
            graph_edit_illustration_page=1,
            graph_edit_illustration_browser_notice="",
            _graph_edit_illustration_filter_widget="all",
            _graph_edit_illustration_page_top=1,
            project=project,
            gallery_page=5,
            highlighted_line_id="line_9",
            focused_line_id="line_9",
            selected_node_ids=["node"],
        )
        namespace = self._load(
            ["_reveal_graph_edit_browser_current"],
            {
                "st": SimpleNamespace(session_state=state),
                "GRAPH_EDIT_BROWSER_FILTER_KEY": "graph_edit_illustration_filter",
                "GRAPH_EDIT_BROWSER_PAGE_KEY": "graph_edit_illustration_page",
                "GRAPH_EDIT_BROWSER_NOTICE_KEY": "graph_edit_illustration_browser_notice",
                "GRAPH_EDIT_BROWSER_FILTER_WIDGET_KEY": "_graph_edit_illustration_filter_widget",
                "GRAPH_EDIT_BROWSER_PAGE_TOP_WIDGET_KEY": "_graph_edit_illustration_page_top",
                "block_graph_edit_browser_navigation_if_unsaved": lambda _project: False,
            },
        )
        namespace["_reveal_graph_edit_browser_current"]("scene:scene_c", 3)
        self.assertEqual("scene:scene_c", state["graph_edit_illustration_filter"])
        self.assertEqual(3, state["graph_edit_illustration_page"])
        self.assertNotIn("_graph_edit_illustration_filter_widget", state)
        self.assertNotIn("_graph_edit_illustration_page_top", state)
        self.assertIs(project, state["project"])
        self.assertEqual(5, state["gallery_page"])
        self.assertEqual("line_9", state["highlighted_line_id"])
        self.assertEqual("line_9", state["focused_line_id"])
        self.assertEqual(["node"], state["selected_node_ids"])

    def test_success_paths_use_canonical_owner_and_failed_load_guard_precedes_it(self):
        load = self._source("load_project_json_into_session")
        self.assertLess(
            load.index("if not os.path.exists(project_path):"),
            load.index("reset_graph_project_session_state()"),
        )
        self.assertEqual(1, load.count("reset_graph_project_session_state()"))
        for owner in (
            "set_new_workspace_project",
            "render_prompt_import_export_panel",
        ):
            self.assertIn("reset_graph_project_session_state()", self._source(owner))

    def test_same_project_mode_and_gallery_owners_do_not_reset_browser(self):
        reset_call = "reset_graph_edit_illustration_browser_state()"
        for owner in (
            "render_management_workspace_shell",
            "render_gallery_edit_mode",
            "render_trash_mode",
        ):
            if owner in self.functions:
                self.assertNotIn(reset_call, self._source(owner))
        browser_functions = "\n".join(
            self._source(name)
            for name in self.functions
            if "graph_edit_browser" in name
        )
        self.assertNotIn("gallery_page", browser_functions)
        self.assertNotIn("gallery_collapsed", browser_functions)
        self.assertNotIn("selected_gallery", browser_functions)


if __name__ == "__main__":
    unittest.main()
