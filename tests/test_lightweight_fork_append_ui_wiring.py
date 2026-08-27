import os
import unittest


class LightweightForkAppendUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        with open(app_path, encoding="utf-8") as handle:
            cls.app_source = handle.read()
        start = cls.app_source.index("def _render_lightweight_fork_append_section")
        end = cls.app_source.index("def render_lightweight_fork_preview_section", start)
        cls.append_section = cls.app_source[start:end]

    def test_create_and_append_modes_are_both_available(self):
        self.assertIn('"派生Projectを作成"', self.app_source)
        self.assertIn('"既存の派生Projectへ追加"', self.app_source)
        self.assertIn('if mode == "append_existing":', self.app_source)
        self.assertIn("派生Projectを作成", self.app_source)

    def test_append_supports_shared_single_and_selected_route_targets(self):
        self.assertIn('"Target Scenes"', self.append_section)
        self.assertIn('["selected_route", "selected_routes"]', self.append_section)
        self.assertIn('key="lightweight_fork_scope"', self.append_section)
        self.assertIn('st.session_state.get("lightweight_fork_selected_route_id", "")', self.append_section)
        self.assertIn('st.session_state.get("gallery_selected_route_ids", [])', self.append_section)
        self.assertIn("resolve_lightweight_fork_append_targets", self.append_section)
        self.assertIn("_render_lightweight_fork_single_route_selector", self.append_section)
        self.assertEqual(3, self.app_source.count("_render_lightweight_fork_single_route_selector(project)"))
        self.assertGreaterEqual(self.append_section.count("selected_route_ids=append_route_ids"), 2)
        self.assertNotIn("multiselect(", self.append_section)
        self.assertNotIn('key="lightweight_fork_append_scope"', self.app_source)

    def test_append_signature_uses_scope_paths_and_resolved_target_state(self):
        self.assertIn("build_lightweight_fork_append_input_signature", self.append_section)
        self.assertIn("source_project_path=current_project_path", self.append_section)
        self.assertIn("destination_project_path=existing_fork_project_path", self.append_section)
        self.assertIn("target_resolution=target_resolution", self.append_section)

    def test_detailed_preview_precedes_confirmation_and_append(self):
        preview_render = self.append_section.index("_render_lightweight_fork_append_preview(preview)")
        confirmation = self.append_section.index("st.checkbox(", preview_render)
        append_button = self.append_section.index('"選択中のシーンを追加"', confirmation)
        self.assertLess(preview_render, confirmation)
        self.assertLess(confirmation, append_button)

    def test_append_requires_fresh_preview_and_does_not_touch_source_history_or_autosave(self):
        self.assertIn('"Fresh Preview"', self.append_section)
        self.assertIn("build_lightweight_fork_append_preview", self.append_section)
        self.assertIn("append_selected_routes_to_existing_fork", self.append_section)
        self.assertNotIn("push_history", self.append_section)
        self.assertNotIn("save_current_project_if_possible", self.append_section)

    def test_append_offers_discovered_fork_selectbox_and_manual_fallback(self):
        self.assertIn('"既存の派生Project"', self.append_section)
        self.assertIn("lightweight_fork_append_candidate", self.append_section)
        self.assertIn("別の派生Projectを指定...", self.append_section)
        self.assertIn("一致する派生Projectがありません", self.append_section)
        self.assertIn("lightweight_fork_append_project_path", self.append_section)
        self.assertIn("派生Project一覧を更新", self.append_section)
        self.assertIn("_render_lightweight_fork_candidate_summary", self.append_section)
        self.assertIn('candidate.get("materialized_route_count", 0)', self.app_source)

    def test_discovered_selection_still_uses_authoritative_fresh_preview(self):
        selectbox = self.append_section.index('"既存の派生Project"')
        preview = self.append_section.index('"Fresh Preview"', selectbox)
        builder = self.append_section.index("build_lightweight_fork_append_preview", preview)
        apply_call = self.append_section.index("append_selected_routes_to_existing_fork", builder)
        self.assertLess(selectbox, preview)
        self.assertLess(preview, builder)
        self.assertLess(builder, apply_call)

    def test_project_switch_reset_clears_append_state(self):
        reset_start = self.app_source.index("def reset_lightweight_fork_session_state")
        reset_end = self.app_source.index("def reset_gallery_route_action_session_state", reset_start)
        reset_source = self.app_source[reset_start:reset_end]
        for key in (
            "lightweight_fork_append_preview",
            "lightweight_fork_append_result",
            "lightweight_fork_append_input_signature",
            "lightweight_fork_append_widget_reset_pending",
            "lightweight_fork_discovery_cache",
        ):
            self.assertIn(key, reset_source)
        route_reset_start = self.app_source.index("def reset_gallery_route_action_session_state")
        route_reset_end = self.app_source.index("def _gallery_selected_route_widget_key", route_reset_start)
        route_reset_source = self.app_source[route_reset_start:route_reset_end]
        self.assertIn('"lightweight_fork_scope"', route_reset_source)
        self.assertIn("request_lightweight_fork_single_route_state_reset(st.session_state)", route_reset_source)
        gallery_start = self.app_source.index("def render_pro_gallery_mode")
        gallery_source = self.app_source[gallery_start:]
        pending_reset = gallery_source.index(
            "apply_pending_lightweight_fork_single_route_widget_reset(st.session_state)"
        )
        operations = gallery_source.index("render_gallery_operations_launcher(project)")
        self.assertLess(pending_reset, operations)
        render_start = self.app_source.index("def render_lightweight_fork_preview_section")
        render_end = self.app_source.index("def render_gallery_operations_launcher", render_start)
        render_source = self.app_source[render_start:render_end]
        self.assertIn("lightweight_fork_action_mode", render_source)
        self.assertIn("lightweight_fork_append_project_path", render_source)
        self.assertIn("lightweight_fork_append_candidate", render_source)
        self.assertIn("lightweight_fork_append_confirmation", render_source)

    def test_create_append_mode_switch_preserves_shared_route_target(self):
        render_start = self.app_source.index("def render_lightweight_fork_preview_section")
        render_end = self.app_source.index("def render_gallery_operations_launcher", render_start)
        render_source = self.app_source[render_start:render_end]
        append_branch = render_source.index('if mode == "append_existing":')
        create_scope = render_source.index('key="lightweight_fork_scope"', append_branch)
        self.assertLess(append_branch, create_scope)
        self.assertNotIn('pop("lightweight_fork_scope"', render_source)
        self.assertNotIn('pop("lightweight_fork_selected_route_id"', render_source)

    def test_single_route_selector_separates_durable_and_temporary_widget_state(self):
        selector_start = self.app_source.index("def _render_lightweight_fork_single_route_selector")
        selector_end = self.app_source.index("def _render_lightweight_fork_append_section", selector_start)
        selector_source = self.app_source[selector_start:selector_end]
        self.assertIn('st.session_state.get("lightweight_fork_selected_route_id", "")', selector_source)
        self.assertIn("initialize_lightweight_fork_single_route_widget_state(st.session_state)", selector_source)
        self.assertIn("key=LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY", selector_source)
        self.assertIn("on_change=_on_lightweight_fork_single_route_widget_changed", selector_source)
        self.assertNotIn('key="lightweight_fork_selected_route_id"', selector_source)


if __name__ == "__main__":
    unittest.main()
