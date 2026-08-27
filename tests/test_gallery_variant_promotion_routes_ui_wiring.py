from pathlib import Path
import unittest


class GalleryVariantPromotionRoutesUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app_source = (root / "app.py").read_text(encoding="utf-8")
        cls.core_source = (root / "core" / "gallery_variant_promotion.py").read_text(encoding="utf-8")
        start = cls.app_source.index("def render_gallery_batch_variant_promotion")
        end = cls.app_source.index("\ndef render_candidate_route_creation_section", start)
        cls.ui_source = cls.app_source[start:end]

    def test_five_scopes_and_route_sources_are_wired(self):
        for scope in (
            "current_route",
            "selected_route",
            "selected_routes",
            "selected_lines",
            "all_lines",
        ):
            self.assertIn(f'"{scope}"', self.core_source)
        self.assertIn("options=list(VARIANT_PROMOTION_SCOPES)", self.ui_source)
        self.assertIn("normalize_batch_variant_promotion_scope", self.ui_source)
        self.assertIn(
            'route_widget_key = "gallery_variant_promotion_selected_route_id"',
            self.ui_source,
        )
        self.assertIn("key=route_widget_key", self.ui_source)
        self.assertIn('st.session_state.get("gallery_selected_route_ids", [])', self.ui_source)
        self.assertIn("_gallery_route_anchor_line_id(project, selected_line_ids)", self.ui_source)

    def test_ui_clarifies_main_line_addition_and_placement(self):
        self.assertIn("Batch Promote Variants（Variantを本編列へ昇格）", self.ui_source)
        self.assertIn("新しい通常Galleryイラストとして本編列へ追加します", self.ui_source)
        self.assertIn("シーン区切りも新規作成しません", self.ui_source)
        self.assertIn('"after_parent": "親イラストの直後"', self.app_source)
        self.assertNotIn("親シーンの後", self.app_source)
        self.assertIn('"Variantsを本編列へ昇格"', self.ui_source)

    def test_fresh_preview_route_and_line_summaries_precede_confirmation(self):
        fresh_preview = self.ui_source.index('"Fresh Preview"')
        route_table = self.ui_source.index("route_rows =")
        line_details = self.ui_source.index('with st.expander("Illustration details"')
        confirmation = self.ui_source.index("confirm_promotion = st.checkbox")
        apply_button = self.ui_source.index('"Variantsを本編列へ昇格"', confirmation)
        self.assertLess(fresh_preview, route_table)
        self.assertLess(route_table, line_details)
        self.assertLess(line_details, confirmation)
        self.assertLess(confirmation, apply_button)
        self.assertIn("Previewが古くなっています。Fresh Previewを再実行してください。", self.ui_source)
        self.assertIn("disabled=not preview_current or stored_plan", self.ui_source)

    def test_full_plan_runs_only_for_fresh_preview_and_stale_check_is_lightweight(self):
        resolver = self.ui_source.index(
            "target_resolution = resolve_batch_variant_promotion_targets("
        )
        fresh_button = self.ui_source.index('if st.button(\n            "Fresh Preview"')
        full_plan = self.ui_source.index(
            "build_batch_variant_promotion_plan(project, **plan_kwargs)",
            fresh_button,
        )
        stored_preview = self.ui_source.index(
            'stored_plan = st.session_state.get("gallery_variant_promotion_preview")',
            full_plan,
        )
        lightweight_signature = self.ui_source.index(
            "build_batch_variant_promotion_signature(",
            stored_preview,
        )
        self.assertLess(resolver, fresh_button)
        self.assertLess(fresh_button, full_plan)
        self.assertLess(full_plan, stored_preview)
        self.assertLess(stored_preview, lightweight_signature)
        self.assertNotIn(
            "build_batch_variant_promotion_plan(",
            self.ui_source[resolver:fresh_button],
        )

    def test_apply_revalidates_and_commits_once(self):
        apply_start = self.ui_source.index("result = apply_batch_promote_gallery_variants")
        apply_source = self.ui_source[apply_start:]
        self.assertIn("stored_plan=stored_plan", apply_source)
        self.assertEqual(1, apply_source.count("push_history()"))
        self.assertEqual(1, apply_source.count("build_graph("))
        self.assertEqual(1, apply_source.count("save_current_project_if_possible("))
        self.assertNotIn("sync_text_areas()", apply_source)
        self.assertIn("apply_batch_variant_promotion_plan(", self.app_source)

    def test_session_reset_and_gallery_region_order_are_preserved(self):
        reset_start = self.app_source.index("def reset_gallery_route_action_session_state")
        reset_end = self.app_source.index("def _gallery_selected_route_widget_key", reset_start)
        reset_source = self.app_source[reset_start:reset_end]
        for key in (
            "gallery_variant_promotion_preview",
            "gallery_variant_promotion_confirm",
            "gallery_variant_promotion_selected_route_id",
        ):
            self.assertIn(f'"{key}"', reset_source)

        mode_start = self.app_source.index("def render_pro_gallery_mode")
        mode_end = self.app_source.index("def _restore_gallery_route_from_trash", mode_start)
        mode_source = self.app_source[mode_start:mode_end]
        launcher_start = self.app_source.index("def render_gallery_operations_launcher")
        launcher_end = self.app_source.index("def render_gallery_active_operation_panel", launcher_start)
        launcher_source = self.app_source[launcher_start:launcher_end]
        operations = mode_source.index('st.markdown("### Gallery Operations")')
        promotion = launcher_source.index("render_gallery_batch_variant_promotion(")
        gallery = mode_source.rindex('st.markdown("### Gallery")')
        pagination = mode_source.index("render_gallery_pagination_controls(display_lines)", gallery)
        self.assertGreaterEqual(promotion, 0)
        self.assertLess(operations, mode_source.index("render_gallery_operations_launcher(project)"))
        self.assertLess(mode_source.index("render_gallery_operations_launcher(project)"), gallery)
        self.assertLess(gallery, pagination)


if __name__ == "__main__":
    unittest.main()
