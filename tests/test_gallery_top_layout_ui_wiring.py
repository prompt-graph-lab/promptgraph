from pathlib import Path
import unittest


class GalleryTopLayoutUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        mode_start = app_source.index("def render_pro_gallery_mode")
        mode_end = app_source.index("def _restore_gallery_route_from_trash", mode_start)
        launcher_start = app_source.index("def render_gallery_operations_launcher")
        launcher_end = app_source.index("def render_gallery_active_operation_panel", launcher_start)
        cls.app_source = app_source
        cls.mode_source = app_source[mode_start:mode_end]
        cls.launcher_source = app_source[launcher_start:launcher_end]

    def test_gallery_top_level_regions_follow_issue_330_order(self):
        import_heading = self.mode_source.index('st.markdown("### Illustration Import / Source")')
        import_panel = self.mode_source.index("render_gallery_import_export_section(project)")
        operations_heading = self.mode_source.index('st.markdown("### Gallery Operations")')
        operations_launcher = self.mode_source.index("render_gallery_operations_launcher(project)")
        gallery_heading = self.mode_source.rindex('st.markdown("### Gallery")')

        self.assertLess(import_heading, import_panel)
        self.assertLess(import_panel, operations_heading)
        self.assertLess(operations_heading, operations_launcher)
        self.assertLess(operations_launcher, gallery_heading)
        self.assertGreaterEqual(self.mode_source.count("st.divider()"), 3)

    def test_operation_scope_panel_is_stable_and_inside_operations_region(self):
        operations_heading = self.mode_source.index('st.markdown("### Gallery Operations")')
        selected_controls = self.mode_source.index(
            "render_gallery_selected_routes_controls(project, selected_route_state)",
            operations_heading,
        )
        launcher = self.mode_source.index("render_gallery_operations_launcher(project)", selected_controls)
        gallery_heading = self.mode_source.rindex('st.markdown("### Gallery")')

        self.assertLess(operations_heading, selected_controls)
        self.assertLess(selected_controls, launcher)
        self.assertLess(launcher, gallery_heading)
        self.assertNotIn('if selected_route_state["selected_route_count"] > 0:', self.mode_source)
        self.assertNotIn("render_gallery_route_selection_entry", self.app_source)

    def test_generation_and_candidate_operations_precede_gallery_pagination(self):
        operation_calls = [
            self.launcher_source.index('"gallery_generation"'),
            self.launcher_source.index('"batch_candidate_adoption"'),
            self.launcher_source.index("render_gallery_batch_variant_promotion("),
        ]
        launcher = self.mode_source.index("render_gallery_operations_launcher(project)")
        gallery_heading = self.mode_source.rindex('st.markdown("### Gallery")')
        pagination = self.mode_source.index("render_gallery_pagination_controls(display_lines)")
        card_loop = self.mode_source.index("gallery_card_loop_start", pagination)

        self.assertEqual(3, len(operation_calls))
        self.assertLess(launcher, gallery_heading)
        self.assertLess(gallery_heading, pagination)
        self.assertLess(pagination, card_loop)

    def test_operation_scope_panel_is_compact_and_visible_for_zero_selection(self):
        controls_start = self.app_source.index("def render_gallery_selected_routes_controls")
        controls_end = self.app_source.index("def render_gallery_route_bulk_collapse_controls", controls_start)
        controls_source = self.app_source[controls_start:controls_end]

        self.assertIn('st.markdown("**Operation Scope / 操作対象**")', controls_source)
        self.assertIn('f"Selected Scenes: {selected_count} / {selectable_count}"', controls_source)
        self.assertIn("with st.container(border=True):", controls_source)
        self.assertNotIn(".metric(", controls_source)
        self.assertNotIn("if selected_count <= 0:", controls_source)

    def test_zero_selection_keeps_one_shared_control_owner(self):
        button_start = self.app_source.index("def _render_gallery_select_all_routes_button")
        context_start = self.app_source.index("def render_gallery_selected_routes_controls", button_start)
        button_source = self.app_source[button_start:context_start]
        controls_end = self.app_source.index("def render_gallery_route_bulk_collapse_controls", context_start)
        controls_source = self.app_source[context_start:controls_end]

        self.assertIn("_render_gallery_select_all_routes_button(project, selectable_count, selected_count)", controls_source)
        self.assertIn("disabled=not selected_count", controls_source)
        self.assertIn("disabled=not selectable_count", controls_source)
        self.assertIn("disabled=not selectable_count or selected_count == selectable_count", button_source)
        self.assertEqual(1, self.app_source.count('key="gallery_selected_routes_select_all"'))
        self.assertIn(
            "st.session_state.gallery_selected_route_ids = select_all_routes(project)",
            button_source,
        )


if __name__ == "__main__":
    unittest.main()
