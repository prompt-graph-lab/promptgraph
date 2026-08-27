import ast
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def _line(line_id, text="stored", negative="stored negative", *, deleted=False):
    return SimpleNamespace(
        id=line_id,
        current_text=text,
        negative_prompt=negative,
        deleted=deleted,
    )


class GraphEditIllustrationBrowserUnsavedNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        cls.source = app_path.read_text(encoding="utf-8")
        tree = ast.parse(cls.source)
        cls.functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _load(self, names, state):
        module = ast.Module(
            body=[self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        namespace = {
            "st": SimpleNamespace(session_state=state),
            "GRAPH_EDIT_BROWSER_PAGE_LINE_IDS_KEY": (
                "graph_edit_illustration_browser_page_line_ids"
            ),
            "GRAPH_EDIT_BROWSER_NOTICE_KEY": (
                "graph_edit_illustration_browser_notice"
            ),
            "GRAPH_EDIT_BROWSER_UNSAVED_WARNING": "unsaved warning",
            "GRAPH_EDIT_BROWSER_PAGE_KEY": "graph_edit_illustration_page",
            "GRAPH_EDIT_BROWSER_FILTER_KEY": "graph_edit_illustration_filter",
            "GRAPH_EDIT_BROWSER_PAGE_SIZE_KEY": "graph_edit_illustration_page_size",
            "GRAPH_EDIT_BROWSER_COLLAPSED_KEY": "graph_edit_collapsed_group_keys",
            "GRAPH_EDIT_BROWSER_FILTER_WIDGET_KEY": (
                "_graph_edit_illustration_filter_widget"
            ),
            "GRAPH_EDIT_BROWSER_PAGE_SIZE_WIDGET_KEY": (
                "_graph_edit_illustration_page_size_widget"
            ),
            "GRAPH_EDIT_BROWSER_PAGE_TOP_WIDGET_KEY": (
                "_graph_edit_illustration_page_top"
            ),
            "GRAPH_EDIT_BROWSER_FILTER_ALL": "all",
            "GRAPH_EDIT_BROWSER_PAGE_SIZE_OPTIONS": (12, 24, 48),
            "GRAPH_EDIT_BROWSER_DEFAULT_PAGE_SIZE": 12,
            "get_line_by_id": lambda project, line_id: next(
                (
                    line
                    for line in getattr(project, "prompt_lines", [])
                    if line.id == line_id
                ),
                None,
            ),
        }
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def _state(self):
        project = SimpleNamespace(
            prompt_lines=[_line("line_1"), _line("line_2", "hidden")]
        )
        return _SessionState(
            project=project,
            graph_edit_illustration_browser_page_line_ids=["line_1"],
            graph_edit_illustration_browser_notice="",
            graph_edit_illustration_page=1,
            graph_edit_illustration_filter="all",
            graph_edit_illustration_page_size=12,
            _graph_edit_illustration_filter_widget="all",
            _graph_edit_illustration_page_size_widget=12,
            _graph_edit_illustration_page_top=1,
            history=["existing"],
            selected_node_ids=["node"],
        )

    def _namespace(self, state):
        return self._load(
            [
                "get_graph_edit_browser_unsaved_line_ids",
                "block_graph_edit_browser_navigation_if_unsaved",
                "discard_graph_edit_browser_current_page_drafts",
                "_reset_graph_edit_browser_page",
                "_on_graph_edit_browser_filter_changed",
                "_on_graph_edit_browser_page_size_changed",
                "_on_graph_edit_browser_page_input_changed",
                "_set_graph_edit_browser_page",
                "_set_graph_edit_browser_collapsed_group_keys",
                "_reveal_graph_edit_browser_current",
            ],
            state,
        )

    def test_positive_draft_blocks_page_buttons_without_side_effects(self):
        state = self._state()
        state["text_line_1"] = "unsaved positive"
        project_before = copy.deepcopy(state["project"])
        history_before = list(state["history"])
        namespace = self._namespace(state)

        changed = namespace["_set_graph_edit_browser_page"](2, 4)

        self.assertFalse(changed)
        self.assertEqual(1, state["graph_edit_illustration_page"])
        self.assertEqual("all", state["graph_edit_illustration_filter"])
        self.assertEqual(project_before.prompt_lines, state["project"].prompt_lines)
        self.assertEqual(history_before, state["history"])
        self.assertEqual("unsaved warning", state["graph_edit_illustration_browser_notice"])

        self.assertFalse(namespace["_set_graph_edit_browser_page"](4, 4))
        self.assertEqual(1, state["graph_edit_illustration_page"])
        self.assertFalse(
            namespace["_set_graph_edit_browser_collapsed_group_keys"](
                {"scene:scene_a"}
            )
        )
        self.assertNotIn("graph_edit_collapsed_group_keys", state)

    def test_page_number_filter_and_page_size_callbacks_restore_mirrors(self):
        state = self._state()
        state["text_line_1"] = "unsaved positive"
        namespace = self._namespace(state)

        state["_graph_edit_illustration_page_top"] = 3
        namespace["_on_graph_edit_browser_page_input_changed"](
            "_graph_edit_illustration_page_top"
        )
        self.assertEqual(1, state["graph_edit_illustration_page"])
        self.assertEqual(1, state["_graph_edit_illustration_page_top"])

        state["_graph_edit_illustration_filter_widget"] = "scene:scene_b"
        namespace["_on_graph_edit_browser_filter_changed"]()
        self.assertEqual("all", state["graph_edit_illustration_filter"])
        self.assertEqual("all", state["_graph_edit_illustration_filter_widget"])

        state["_graph_edit_illustration_page_size_widget"] = 48
        namespace["_on_graph_edit_browser_page_size_changed"]()
        self.assertEqual(12, state["graph_edit_illustration_page_size"])
        self.assertEqual(12, state["_graph_edit_illustration_page_size_widget"])

    def test_negative_only_draft_blocks_filter_and_reveal(self):
        state = self._state()
        state["negative_text_line_1"] = "unsaved negative"
        namespace = self._namespace(state)

        self.assertEqual(
            ["line_1"],
            namespace["get_graph_edit_browser_unsaved_line_ids"](state["project"]),
        )
        state["_graph_edit_illustration_filter_widget"] = "scene:scene_b"
        namespace["_on_graph_edit_browser_filter_changed"]()
        namespace["_reveal_graph_edit_browser_current"]("scene:scene_c", 2)

        self.assertEqual("all", state["graph_edit_illustration_filter"])
        self.assertEqual(1, state["graph_edit_illustration_page"])
        self.assertEqual("line_1", state["graph_edit_illustration_browser_page_line_ids"][0])

    def test_detector_ignores_selection_hidden_missing_and_deleted_ids(self):
        state = self._state()
        state["chk_line_1"] = True
        state["text_line_2"] = "hidden draft"
        state["text_missing"] = "missing draft"
        state["graph_edit_illustration_browser_page_line_ids"] = [
            "line_1",
            "missing",
            "deleted",
        ]
        state["project"].prompt_lines.append(_line("deleted", deleted=True))
        namespace = self._namespace(state)

        self.assertEqual(
            [],
            namespace["get_graph_edit_browser_unsaved_line_ids"](state["project"]),
        )

    def test_discard_restores_both_widgets_then_navigation_succeeds(self):
        state = self._state()
        state["text_line_1"] = "unsaved positive"
        state["negative_text_line_1"] = "unsaved negative"
        project_before = copy.deepcopy(state["project"])
        history_before = list(state["history"])
        namespace = self._namespace(state)
        self.assertFalse(namespace["_set_graph_edit_browser_page"](2, 4))

        discarded = namespace["discard_graph_edit_browser_current_page_drafts"](
            state["project"]
        )

        self.assertEqual(["line_1"], discarded)
        self.assertEqual("stored", state["text_line_1"])
        self.assertEqual("stored negative", state["negative_text_line_1"])
        self.assertEqual(project_before.prompt_lines, state["project"].prompt_lines)
        self.assertEqual(history_before, state["history"])
        self.assertEqual("", state["graph_edit_illustration_browser_notice"])
        self.assertTrue(namespace["_set_graph_edit_browser_page"](2, 4))
        self.assertEqual(2, state["graph_edit_illustration_page"])

    def test_saved_project_values_clear_detector_and_allow_navigation(self):
        state = self._state()
        state["text_line_1"] = "saved positive"
        state["negative_text_line_1"] = "saved negative"
        namespace = self._namespace(state)
        self.assertEqual(
            ["line_1"],
            namespace["get_graph_edit_browser_unsaved_line_ids"](state["project"]),
        )

        line = state["project"].prompt_lines[0]
        line.current_text = state["text_line_1"]
        line.negative_prompt = state["negative_text_line_1"]

        self.assertEqual(
            [],
            namespace["get_graph_edit_browser_unsaved_line_ids"](state["project"]),
        )
        self.assertTrue(namespace["_set_graph_edit_browser_page"](2, 4))
        self.assertEqual(2, state["graph_edit_illustration_page"])


if __name__ == "__main__":
    unittest.main()
