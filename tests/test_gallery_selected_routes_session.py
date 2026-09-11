"""Selected Routes lifecycle characterization, runnable before and after extraction."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.route_operations import (
    initialize_selected_route_widget_state,
    sanitize_selected_route_ids,
    toggle_selected_route,
)
from test_selected_routes import _project


NAMES = (
    "_gallery_selected_route_widget_key",
    "_initialize_gallery_selected_route_widget",
    "_clear_gallery_selected_route_widget_keys",
    "reset_gallery_selected_route_session_state",
    "_apply_pending_gallery_selected_route_widget_reset",
    "_sanitize_gallery_selected_route_session_state",
    "_on_gallery_route_selection_changed",
    "_set_gallery_selected_route_ids_after_structure_change",
)
PREFIX = "pro_gallery_route_selected_"


class Session(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


class GallerySelectedRoutesSessionTests(unittest.TestCase):
    def setUp(self):
        self.state = Session(project=_project())
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)
                   and n.module == "ui.gallery_selected_routes_session"]
        if imports:
            from ui import gallery_selected_routes_session as owner
            replacement = patch.object(owner, "st", SimpleNamespace(session_state=self.state))
            replacement.start()
            self.addCleanup(replacement.stop)
            self.ns = vars(owner)
            imported = {}
            exec(compile(ast.Module(body=imports, type_ignores=[]), "app.py", "exec"), imported)
            for name in NAMES:
                self.assertIs(imported[name], self.ns[name])
        else:
            nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
            self.assertEqual(len(NAMES), len(nodes))
            self.ns = dict(st=SimpleNamespace(session_state=self.state),
                           SELECTED_ROUTE_WIDGET_PREFIX=PREFIX,
                           initialize_selected_route_widget_state=initialize_selected_route_widget_state,
                           sanitize_selected_route_ids=sanitize_selected_route_ids,
                           toggle_selected_route=toggle_selected_route)
            exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), self.ns)

    def test_widget_initialization_retains_existing_widget_then_sanitize_uses_durable_ids(self):
        self.state.gallery_selected_route_ids = ["route_a"]
        self.state[PREFIX + "route_a"] = False
        key = self.ns["_initialize_gallery_selected_route_widget"](" route_a ")
        self.assertEqual(PREFIX + "route_a", key)
        self.assertFalse(self.state[key])
        self.ns["_sanitize_gallery_selected_route_session_state"](self.state.project)
        self.assertTrue(self.state[key])
        self.assertEqual(PREFIX, self.ns["_gallery_selected_route_widget_key"](0))

    def test_sanitize_copies_ids_preserves_project_order_and_cleanup_flags(self):
        original = ["route_d", "route_a", "route_a", "missing"]
        self.state.gallery_selected_route_ids = original
        self.state.update({PREFIX + "route_a": False, PREFIX + "missing": True, "other": 9})
        result = self.ns["_sanitize_gallery_selected_route_session_state"](
            self.state.project, sync_widgets=True, cleanup_widgets=False)
        self.assertEqual(["route_a", "route_d"], self.state.gallery_selected_route_ids)
        self.assertIsNot(result["selected_route_ids"], self.state.gallery_selected_route_ids)
        self.assertEqual(["route_d", "route_a", "route_a", "missing"], original)
        self.assertFalse(self.state[PREFIX + "route_a"])
        self.assertIn(PREFIX + "missing", self.state)
        self.ns["_sanitize_gallery_selected_route_session_state"](self.state.project, sync_widgets=False)
        self.assertNotIn(PREFIX + "missing", self.state)
        self.assertFalse(self.state[PREFIX + "route_a"])
        self.assertEqual(9, self.state.other)

    def test_callback_uses_widget_truthiness_and_current_project_without_syncing_widgets(self):
        self.state.gallery_selected_route_ids = ["route_d"]
        self.state[PREFIX + "route_a"] = "false"
        self.ns["_on_gallery_route_selection_changed"](" route_a ")
        self.assertEqual(["route_a", "route_d"], self.state.gallery_selected_route_ids)
        self.assertEqual("false", self.state[PREFIX + "route_a"])
        del self.state[PREFIX + "route_a"]
        self.ns["_on_gallery_route_selection_changed"]("route_a")
        self.assertEqual(["route_d"], self.state.gallery_selected_route_ids)

    def test_structure_change_defers_sorted_deduplicated_widget_reset(self):
        self.state.gallery_selected_route_ids = ["route_d", "route_a", "route_b"]
        for handle in ("route_a", "route_b", "route_d"):
            self.state[PREFIX + handle] = True
        result = self.ns["_set_gallery_selected_route_ids_after_structure_change"](
            self.state.project, removed_route_handles=(" route_b ", "route_a", "route_b", None))
        self.assertEqual(["route_d"], result["selected_route_ids"])
        self.assertEqual({"route_handles": ["route_a", "route_b"]},
                         self.state.gallery_selected_route_widget_pending_reset)
        self.assertTrue(self.state[PREFIX + "route_a"])
        self.ns["_apply_pending_gallery_selected_route_widget_reset"]()
        self.assertNotIn(PREFIX + "route_a", self.state)
        self.assertNotIn(PREFIX + "route_b", self.state)
        self.assertTrue(self.state[PREFIX + "route_d"])
        self.assertNotIn("gallery_selected_route_widget_pending_reset", self.state)

    def test_undo_style_sanitize_retains_pending_and_does_not_restore_selection(self):
        pending = {"route_handles": ["route_a"]}
        self.state.gallery_selected_route_widget_pending_reset = pending
        self.state.gallery_selected_route_ids = ["route_d"]
        self.state[PREFIX + "route_a"] = True
        self.ns["_set_gallery_selected_route_ids_after_structure_change"](self.state.project)
        self.assertEqual(["route_d"], self.state.gallery_selected_route_ids)
        self.assertIs(pending, self.state.gallery_selected_route_widget_pending_reset)
        self.assertTrue(self.state[PREFIX + "route_a"])

    def test_pending_missing_handles_clears_all_but_invalid_payload_only_consumes(self):
        for payload, clears in ((False, False), ([], False), ({"route_handles": []}, False), ({}, True)):
            with self.subTest(payload=payload):
                self.state[PREFIX + "route_a"] = True
                self.state.gallery_selected_route_widget_pending_reset = payload
                self.ns["_apply_pending_gallery_selected_route_widget_reset"]()
                self.assertEqual(not clears, PREFIX + "route_a" in self.state)
                self.assertNotIn("gallery_selected_route_widget_pending_reset", self.state)
        self.state[PREFIX + "route_a"] = True
        self.ns["_clear_gallery_selected_route_widget_keys"](" route_a ")
        self.assertNotIn(PREFIX + "route_a", self.state)

    def test_project_reset_invalidates_exact_previews_and_preserves_other_state(self):
        keys = ("gallery_selected_route_widget_pending_reset", "module_swap_preview",
                "module_swap_selected_routes_confirm", "gallery_attribute_group_swap_preview",
                "gallery_attribute_group_swap_selected_routes_confirm", "attribute_group_swap_preview",
                "attribute_group_swap_selected_routes_confirm")
        self.state.update(dict.fromkeys(keys, True))
        self.state[PREFIX + "route_a"] = True
        self.state.gallery_selected_route_ids = ["route_a"]
        self.state.gallery_selected_route_separator_id = "route_b"
        project = self.state.project
        self.ns["reset_gallery_selected_route_session_state"]()
        self.assertEqual(dict(project=project, gallery_selected_route_ids=[],
                              gallery_selected_route_separator_id="route_b"), self.state)
        self.assertIs(project, self.state.project)

    def test_exceptions_preserve_pending_consumption_and_prior_sanitize_write(self):
        self.state.gallery_selected_route_widget_pending_reset = {"route_handles": 42}
        with self.assertRaises(TypeError):
            self.ns["_apply_pending_gallery_selected_route_widget_reset"]()
        self.assertNotIn("gallery_selected_route_widget_pending_reset", self.state)
        self.state.gallery_selected_route_ids = ["route_d", "route_a", "route_a"]
        with self.assertRaises(TypeError):
            self.ns["_set_gallery_selected_route_ids_after_structure_change"](
                self.state.project, removed_route_handles=None)
        self.assertEqual(["route_a", "route_d"], self.state.gallery_selected_route_ids)
