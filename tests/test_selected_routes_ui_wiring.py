from pathlib import Path
import unittest


class SelectedRoutesUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    def test_selected_routes_session_state_and_controls_are_present(self):
        self.assertIn('"gallery_selected_route_ids"', self.app_source)
        self.assertIn("def _sanitize_gallery_selected_route_session_state", self.app_source)
        self.assertIn("def render_gallery_selected_routes_controls", self.app_source)
        self.assertIn('"すべてのシーンを選択"', self.app_source)
        self.assertIn('"選択をクリア"', self.app_source)
        self.assertIn('"選択を反転"', self.app_source)
        self.assertIn('**Operation Scope / 操作対象**', self.app_source)
        self.assertIn('SELECTED_ROUTE_WIDGET_PREFIX = "pro_gallery_route_selected_"', self.app_source)
        self.assertIn("def _initialize_gallery_selected_route_widget", self.app_source)

    def test_selection_controls_render_before_separator_cards(self):
        mode_start = self.app_source.index("def render_pro_gallery_mode")
        launcher_call = self.app_source.index("render_gallery_operations_launcher(project)", mode_start)
        controls_call = self.app_source.index("render_gallery_selected_routes_controls(project, selected_route_state)", mode_start)
        separator_card_call = self.app_source.index("render_gallery_route_separator_header(", mode_start)
        self.assertLess(controls_call, launcher_call)
        self.assertLess(controls_call, separator_card_call)
        self.assertNotIn(
            'if selected_route_state["selected_route_count"] > 0:',
            self.app_source[mode_start:controls_call],
        )
        self.assertNotIn("render_gallery_route_selection_entry", self.app_source)
        self.assertIn("_apply_pending_gallery_selected_route_widget_reset()", self.app_source[mode_start:controls_call])
        self.assertIn("_sanitize_gallery_selected_route_session_state(project)", self.app_source[mode_start:controls_call])

    def test_separator_checkbox_uses_route_keyed_callback(self):
        start = self.app_source.index("def render_gallery_route_separator_header")
        end = self.app_source.index("def render_gallery_workbench_card", start)
        header_source = self.app_source[start:end]
        self.assertIn("st.checkbox(", header_source)
        self.assertIn("widget_key = _initialize_gallery_selected_route_widget(line.id)", header_source)
        self.assertIn("key=widget_key", header_source)
        self.assertIn("on_change=_on_gallery_route_selection_changed", header_source)
        self.assertIn(SELECTED_ROUTE_WIDGET_PREFIX_LITERAL, self.app_source)

    def test_project_switches_reset_selection_and_structure_changes_sanitize(self):
        self.assertGreaterEqual(
            self.app_source.count("reset_gallery_selected_route_session_state()"),
            4,
        )
        self.assertIn("_set_gallery_selected_route_ids_after_structure_change", self.app_source)
        self.assertIn("removed_route_handles=(separator_id,)", self.app_source)
        self.assertIn("gallery_selected_route_widget_pending_reset", self.app_source)

    def test_existing_single_route_selectors_remain_separate(self):
        for key in (
            "gallery_selected_route_separator_id",
            "gallery_generation_selected_route_id",
            "gallery_final_export_selected_route_id",
            "lightweight_fork_selected_route_id",
            "route_batch_candidate_adoption_preview_selected_route_id",
        ):
            self.assertIn(f'"{key}"', self.app_source)
        self.assertNotIn("gallery_selected_route_ids=", self.app_source)

    def test_lightweight_fork_uses_selected_routes_without_a_second_selector(self):
        selector_start = self.app_source.index("def _render_lightweight_fork_single_route_selector")
        selector_end = self.app_source.index("def _render_lightweight_fork_append_section", selector_start)
        selector_source = self.app_source[selector_start:selector_end]
        fork_start = self.app_source.index("def render_lightweight_fork_preview_section")
        fork_source = self.app_source[fork_start:]
        self.assertIn('"selected_routes"', fork_source)
        self.assertIn("resolve_selected_routes_fork_plan", fork_source)
        self.assertIn('st.session_state.get("gallery_selected_route_ids", [])', fork_source)
        self.assertNotIn("lightweight_fork_selected_route_ids", fork_source)
        self.assertIn("_render_lightweight_fork_single_route_selector(project)", fork_source)
        self.assertIn("key=LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY", selector_source)
        self.assertIn("on_change=_on_lightweight_fork_single_route_widget_changed", selector_source)

    def test_selected_routes_are_not_connected_to_existing_operation_panels(self):
        mode_start = self.app_source.index("def render_pro_gallery_mode")
        mode_source = self.app_source[mode_start:]
        self.assertIn("render_gallery_selected_routes_controls", mode_source)
        launcher_start = self.app_source.index("def render_gallery_operations_launcher")
        launcher_end = self.app_source.index("def render_gallery_active_operation_panel", launcher_start)
        self.assertNotIn("gallery_selected_route_ids", self.app_source[launcher_start:launcher_end])


SELECTED_ROUTE_WIDGET_PREFIX_LITERAL = "SELECTED_ROUTE_WIDGET_PREFIX = \"pro_gallery_route_selected_\""


if __name__ == "__main__":
    unittest.main()
