"""Navigation lifecycle characterization, also runnable before extraction."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_graph_edit_illustration_browser_unsaved_navigation as baseline
from ui import graph_edit_browser_controller as controller

_line = baseline._line


class GraphEditBrowserControllerTests(baseline.GraphEditIllustrationBrowserUnsavedNavigationTests):
    def _namespace(self, state):
        for name, value in (
            ("st", SimpleNamespace(session_state=state)),
            ("GRAPH_EDIT_BROWSER_UNSAVED_WARNING", "unsaved warning"),
            ("get_line_by_id", controller.get_line_by_id),
        ):
            replacement = patch.object(controller, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        return vars(controller)

    def test_app_imports_actual_callbacks_and_reset(self):
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        imports = [node for node in ast.parse(source).body
                   if isinstance(node, ast.ImportFrom)
                   and node.module == "ui.graph_edit_browser_controller"]
        self.assertEqual(1, len(imports))
        namespace = {}
        exec(compile(ast.Module(body=imports, type_ignores=[]), "app.py", "exec"), namespace)
        for name in (
            "reset_graph_edit_illustration_browser_state",
            "discard_graph_edit_browser_current_page_drafts",
            "_on_graph_edit_browser_filter_changed",
            "_on_graph_edit_browser_page_size_changed",
            "_on_graph_edit_browser_page_input_changed",
            "_set_graph_edit_browser_page",
            "_set_graph_edit_browser_collapsed_group_keys",
            "_reveal_graph_edit_browser_current",
        ):
            self.assertIs(getattr(controller, name), namespace[name])

    def test_real_lookup_skips_deleted_duplicate_and_propagates_missing_project_fields(self):
        state = self._state()
        ns = self._namespace(state)
        live = state["project"].prompt_lines[0]
        state["project"].prompt_lines.insert(0, _line("line_1", deleted=True))
        self.assertIs(live, ns["get_line_by_id"](state["project"], "line_1"))
        self.assertIsNone(ns["get_line_by_id"](None, "line_1"))
        self.assertIsNone(ns["get_line_by_id"](state["project"], ""))
        with self.assertRaises(AttributeError):
            ns["get_line_by_id"](object(), "line_1")
    def test_ids_are_ordered_deduplicated_and_not_filtered_by_line_kind(self):
        state = self._state()
        for line_id in ("separator", "workbench", "42"):
            line = _line(line_id, None, None)
            line.is_separator = line_id == "separator"
            line.is_workbench = line_id == "workbench"
            state["project"].prompt_lines.append(line)
            state[f"text_{line_id}"] = None
        state["graph_edit_illustration_browser_page_line_ids"] = (
            None, "", 0, "separator", "separator", "workbench", 42, "missing"
        )
        ns = self._namespace(state)
        self.assertEqual(["separator", "workbench", "42"], ns["get_graph_edit_browser_unsaved_line_ids"](state["project"]))
        state["graph_edit_illustration_browser_page_line_ids"] = {"separator"}
        self.assertEqual([], ns["get_graph_edit_browser_unsaved_line_ids"](state["project"]))

    def test_defaults_and_notice_retention_differ_between_transitions(self):
        state = self._state()
        ns = self._namespace(state)
        state["graph_edit_illustration_browser_notice"] = "retain"
        state["_graph_edit_illustration_page_size_widget"] = None
        ns["_on_graph_edit_browser_page_size_changed"]()
        self.assertEqual(12, state["graph_edit_illustration_page_size"])
        self.assertEqual("retain", state["graph_edit_illustration_browser_notice"])
        state["_graph_edit_illustration_filter_widget"] = None
        ns["_on_graph_edit_browser_filter_changed"]()
        self.assertIsNone(state["graph_edit_illustration_filter"])
        self.assertEqual("", state["graph_edit_illustration_browser_notice"])
        for value in (None, "bad", float("inf"), -2):
            state["input"] = value
            ns["_on_graph_edit_browser_page_input_changed"]("input")
            self.assertEqual(1, state["graph_edit_illustration_page"])
        state["input"] = 999
        ns["_on_graph_edit_browser_page_input_changed"]("input")
        self.assertEqual(999, state["graph_edit_illustration_page"])
        ns["_set_graph_edit_browser_page"](None, 0)
        self.assertEqual(1, state["graph_edit_illustration_page"])

    def test_reveal_exception_preserves_partial_mutation_order(self):
        state = self._state()
        ns = self._namespace(state)
        before = dict(state)
        with self.assertRaises(ValueError):
            ns["_reveal_graph_edit_browser_current"]("scene:new", "bad")
        before["graph_edit_illustration_filter"] = "scene:new"
        self.assertEqual(before, state)
        with self.assertRaises(ValueError):
            ns["_set_graph_edit_browser_page"]("bad", 3)
        self.assertEqual(before, state)
        state["text_line_1"] = "draft"
        self.assertFalse(ns["_set_graph_edit_browser_page"]("bad", "bad"))

    def test_discard_rechecks_missing_and_deleted_lines(self):
        state = self._state()
        state["text_line_1"] = "draft"
        ns = self._namespace(state)
        for result in (None, _line("line_1", deleted=True)):
            calls = []
            def lookup(project, line_id):
                calls.append(line_id)
                return project.prompt_lines[0] if len(calls) == 1 else result
            ns["get_line_by_id"] = lookup
            self.assertEqual([], ns["discard_graph_edit_browser_current_page_drafts"](state["project"]))
            self.assertEqual(["line_1", "line_1"], calls)
            self.assertEqual("draft", state["text_line_1"])

    def test_lookup_failure_propagates_without_state_mutation(self):
        state = self._state()
        ns = self._namespace(state)
        before = dict(state)
        def lookup(project, line_id):
            raise RuntimeError("lookup failed")
        ns["get_line_by_id"] = lookup
        with self.assertRaisesRegex(RuntimeError, "lookup failed"):
            ns["_on_graph_edit_browser_filter_changed"]()
        self.assertEqual(before, state)
