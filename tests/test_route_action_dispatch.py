from pathlib import Path
import unittest

from core.route_operations import (
    get_route_action_pending_updates,
)


class RouteActionUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    def test_separator_shortcuts_dispatch_to_existing_panels(self):
        self.assertIn("def _dispatch_gallery_route_action", self.app_source)
        start = self.app_source.index("def _dispatch_gallery_route_action")
        end = self.app_source.index("def _apply_pending_gallery_route_action", start)
        dispatch_source = self.app_source[start:end]
        self.assertIn("gallery_route_action_pending", dispatch_source)
        self.assertNotIn("gallery_generation_scope", dispatch_source)
        self.assertNotIn("route_batch_candidate_adoption_preview_scope", dispatch_source)
        self.assertNotIn("gallery_final_export_scope", dispatch_source)
        self.assertNotIn("lightweight_fork_scope", dispatch_source)

    def test_pending_apply_runs_before_gallery_operation_panels(self):
        mode_start = self.app_source.index("def render_pro_gallery_mode")
        remove_reset_call = self.app_source.index("_apply_pending_gallery_route_remove_reset(project)", mode_start)
        apply_call = self.app_source.index("_apply_pending_gallery_route_action(project)", mode_start)
        import_export_call = self.app_source.index("render_gallery_import_export_section(project)", mode_start)
        self.assertLess(remove_reset_call, import_export_call)
        self.assertLess(apply_call, import_export_call)

    def test_shortcut_ui_is_route_keyed_and_does_not_apply_directly(self):
        start = self.app_source.index("def _render_gallery_route_action_shortcuts")
        end = self.app_source.index("def render_gallery_route_separator_header", start)
        shortcut_source = self.app_source[start:end]

        self.assertIn("route_block.route_handle", shortcut_source)
        self.assertIn("pro_gallery_route_action_{action}_{separator_line.id}", shortcut_source)
        self.assertIn("st.rerun()", shortcut_source)
        self.assertNotIn("apply_", shortcut_source)
        self.assertNotIn("export_final_images", shortcut_source)
        self.assertNotIn("generate_image_with_progress", shortcut_source)

    def test_route_separator_move_buttons_use_block_move_helper(self):
        start = self.app_source.index("def render_gallery_route_separator_header")
        end = self.app_source.index("def render_gallery_workbench_card", start)
        header_source = self.app_source[start:end]

        self.assertIn("get_route_block_move_availability(project, line.id)", header_source)
        self.assertIn('move_route_block(project, separator_id, direction_key)', self.app_source)
        self.assertIn('_move_gallery_route_block_from_ui(project, line, "up")', header_source)
        self.assertIn('_move_gallery_route_block_from_ui(project, line, "down")', header_source)
        self.assertIn('help="Move the entire Scene block up."', header_source)
        self.assertIn('help="Move the entire Scene block down."', header_source)
        self.assertNotIn('move_prompt_line(project, line.id, "up")', header_source)
        self.assertNotIn('move_prompt_line(project, line.id, "down")', header_source)

    def test_route_move_preserves_line_ui_state_and_does_not_reset_collapse_state(self):
        start = self.app_source.index("def _move_gallery_route_block_from_ui")
        end = self.app_source.index("def _remove_gallery_route_block_from_ui", start)
        move_source = self.app_source[start:end]

        self.assertIn('previous_focus = st.session_state.get("focused_line_id")', move_source)
        self.assertIn('previous_highlight = st.session_state.get("highlighted_line_id")', move_source)
        self.assertIn('previous_expanded = st.session_state.get("gallery_expanded_line_id")', move_source)
        self.assertIn("get_route_move_ui_state(", move_source)
        self.assertIn('st.session_state.gallery_selected_route_separator_id = restored_state[', move_source)
        self.assertNotIn("gallery_collapsed_routes", move_source)
        self.assertNotIn("focused_line_id = separator_id", move_source)
        self.assertNotIn("highlighted_line_id = separator_id", move_source)
        self.assertNotIn("gallery_expanded_line_id = separator_id", move_source)

    def test_route_action_state_is_reset_on_project_transitions(self):
        self.assertGreaterEqual(
            self.app_source.count("reset_gallery_route_action_session_state()"),
            4,
        )
        self.assertIn('"gallery_selected_route_separator_id_pending"', self.app_source)
        self.assertIn('"gallery_operations_active"', self.app_source)
        self.assertIn('"gallery_route_action_pending"', self.app_source)
        self.assertIn('"gallery_generation_selected_route_id"', self.app_source)
        self.assertIn('"route_batch_candidate_adoption_preview_selected_route_id"', self.app_source)
        self.assertIn('"gallery_final_export_selected_route_id"', self.app_source)
        self.assertIn('"lightweight_fork_selected_route_id"', self.app_source)

    def test_route_remove_uses_core_helper_and_pending_widget_reset(self):
        self.assertIn("def _remove_gallery_route_block_from_ui", self.app_source)
        self.assertIn("remove_route_block(project, separator_id)", self.app_source)
        self.assertIn('"gallery_route_remove_pending_reset"', self.app_source)
        self.assertIn("Scene Remove", self.app_source)
        self.assertIn("confirmation_key", self.app_source)
        header_start = self.app_source.index("def render_gallery_route_separator_header")
        header_end = self.app_source.index("def render_gallery_workbench_card", header_start)
        self.assertNotIn("delete_lines([line.id])", self.app_source[header_start:header_end])

    def test_duplicate_route_baseline_is_confirmed_and_uses_early_reset(self):
        self.assertIn("def _duplicate_gallery_route_from_ui", self.app_source)
        self.assertIn("duplicate_route_as_baseline(", self.app_source)
        self.assertIn('"gallery_route_duplicate_pending_reset"', self.app_source)
        self.assertIn('"Duplicate Scene as Baseline"', self.app_source)
        self.assertIn('"New Scene label"', self.app_source)
        mode_start = self.app_source.index("def render_pro_gallery_mode")
        duplicate_reset = self.app_source.index("_apply_pending_gallery_route_duplicate_reset(project)", mode_start)
        import_export = self.app_source.index("render_gallery_import_export_section(project)", mode_start)
        self.assertLess(duplicate_reset, import_export)
        shortcut_start = self.app_source.index("def _render_gallery_route_action_shortcuts")
        shortcut_end = self.app_source.index("def render_gallery_route_separator_header", shortcut_start)
        shortcut_source = self.app_source[shortcut_start:shortcut_end]
        self.assertIn("pro_gallery_duplicate_route_confirm_", shortcut_source)
        self.assertIn("pro_gallery_duplicate_route_", shortcut_source)
        self.assertIn("image files are not copied", shortcut_source)

    def test_trash_contains_atomic_route_restore(self):
        start = self.app_source.index("def render_pro_trash_view_mode")
        end = self.app_source.index("def _make_route_snapshot", start)
        trash_source = self.app_source[start:end]
        self.assertIn("get_route_removal_diagnostics(project)", trash_source)
        self.assertIn("get_active_route_removal_records(project)", trash_source)
        self.assertIn('"Restore Scene"', trash_source)
        restore_start = self.app_source.index("def _restore_gallery_route_from_trash")
        restore_end = self.app_source.index("def render_pro_trash_view_mode", restore_start)
        restore_source = self.app_source[restore_start:restore_end]
        self.assertIn("restore_removed_route(", restore_source)
        self.assertIn("reset_gallery_route_action_session_state()", restore_source)


class RouteActionPendingStateTests(unittest.TestCase):
    def test_each_operation_applies_only_its_early_route_state(self):
        expected = {
            "generation": {
                "gallery_operations_active": "gallery_generation",
                "gallery_generation_scope": "selected_route",
                "gallery_generation_selected_route_id": "route_b",
            },
            "candidate_adoption": {
                "gallery_operations_active": "batch_candidate_adoption",
                "route_batch_candidate_adoption_preview_scope": "selected_route",
                "route_batch_candidate_adoption_preview_selected_route_id": "route_b",
            },
            "final_export": {
                "gallery_final_export_scope": "selected_route",
                "gallery_final_export_selected_route_id": "route_b",
            },
            "lightweight_fork": {
                "gallery_operations_active": "lightweight_fork",
                "lightweight_fork_scope": "selected_route",
                "lightweight_fork_selected_route_id": "route_b",
            },
        }

        for operation, operation_updates in expected.items():
            with self.subTest(operation=operation):
                result = get_route_action_pending_updates(
                    {
                        "operation": operation,
                        "route_handle": "route_b",
                        "route_label": "Route B",
                    }
                )
                self.assertTrue(result["apply"])
                self.assertEqual("route_b", result["updates"]["gallery_selected_route_separator_id"])
                self.assertTrue(operation_updates.items() <= result["updates"].items())
                self.assertEqual("route_b", result["updates"]["gallery_route_action_notice"]["route_handle"])

    def test_pending_apply_rejects_missing_or_unknown_payload(self):
        for pending in (None, {}, {"operation": "unknown", "route_handle": "route_b"}):
            with self.subTest(pending=pending):
                result = get_route_action_pending_updates(pending)
                self.assertFalse(result["apply"])
                self.assertEqual({}, result["updates"])

    def test_fork_pending_switches_route_even_when_fork_is_already_open(self):
        result = get_route_action_pending_updates(
            {
                "operation": "lightweight_fork",
                "route_handle": "route_c",
                "route_label": "Route C",
            }
        )
        self.assertTrue(result["apply"])
        self.assertEqual("lightweight_fork", result["updates"]["gallery_operations_active"])
        self.assertEqual("selected_route", result["updates"]["lightweight_fork_scope"])
        self.assertEqual("route_c", result["updates"]["lightweight_fork_selected_route_id"])
        self.assertIn("gallery_operation_focus", result["remove"])


if __name__ == "__main__":
    unittest.main()
