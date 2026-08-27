from pathlib import Path
import unittest


class SelectedRoutesAttributeGroupSwapUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app_source = (root / "app.py").read_text(encoding="utf-8")
        cls.project_source = (root / "core" / "project.py").read_text(encoding="utf-8")
        start = cls.app_source.index("def _render_selected_routes_attribute_group_swap_preview")
        end = cls.app_source.index("def _lightweight_fork_selected_line_ids", start)
        cls.selected_routes_source = cls.app_source[start:end]
        gallery_start = cls.app_source.index("def render_gallery_attribute_group_swap_section")
        gallery_end = cls.app_source.index("def _lightweight_fork_selected_line_ids", gallery_start)
        cls.gallery_source = cls.app_source[gallery_start:gallery_end]
        apply_start = cls.app_source.index("def render_attribute_group_swap_section")
        apply_end = cls.app_source.index("def get_selected_line_for_attribute_preview", apply_start)
        cls.apply_source = cls.app_source[apply_start:apply_end]

    def test_selected_routes_scope_is_added_without_replacing_existing_scopes(self):
        for scope in (
            '"current_route"',
            '"selected_route"',
            '"selected_routes"',
            '"selected_lines"',
            '"all_lines"',
        ):
            self.assertIn(scope, self.gallery_source)
            self.assertIn(scope, self.apply_source)
        self.assertIn('key="gallery_attribute_group_swap_selected_route_id"', self.gallery_source)
        self.assertIn('key="_attribute_group_swap_selected_route_id_widget"', self.apply_source)

    def test_common_gallery_selection_is_used_without_a_second_route_list(self):
        self.assertIn('st.session_state.get("gallery_selected_route_ids", [])', self.selected_routes_source)
        self.assertIn("sanitize_selected_route_ids", self.selected_routes_source)
        self.assertNotIn("attribute_group_swap_selected_route_ids", self.app_source)
        self.assertNotIn("st.multiselect", self.selected_routes_source)

    def test_both_swap_panels_use_pure_display_snapshot(self):
        self.assertIn("groups = get_attribute_groups_snapshot(project)", self.gallery_source)
        self.assertIn("groups = get_attribute_groups_snapshot(project)", self.apply_source)
        self.assertNotIn("groups = get_project_attribute_groups(project)", self.gallery_source)
        self.assertNotIn("groups = get_project_attribute_groups(project)", self.apply_source)

    def test_normal_rerun_uses_cheap_signature_and_full_plan_is_preview_only(self):
        signature_call = self.selected_routes_source.index(
            "build_selected_routes_attribute_group_swap_signature"
        )
        preview_button = self.selected_routes_source.index('key=f"{key_prefix}_preview_btn"')
        full_plan_call = self.selected_routes_source.index(
            "build_selected_routes_attribute_group_swap_plan"
        )
        self.assertLess(signature_call, preview_button)
        self.assertGreater(full_plan_call, preview_button)
        self.assertEqual(
            1,
            self.selected_routes_source.count("build_selected_routes_attribute_group_swap_plan"),
        )
        confirm_reset = self.selected_routes_source.index(
            'st.session_state[f"{key_prefix}_selected_routes_confirm"] = False'
        )
        self.assertLess(preview_button, confirm_reset)
        self.assertLess(confirm_reset, full_plan_call)
        flow_start = self.selected_routes_source.index(
            "def _render_selected_routes_attribute_group_swap_flow"
        )
        before_preview = self.selected_routes_source[flow_start:preview_button]
        self.assertNotIn("push_history()", before_preview)
        self.assertNotIn("save_current_project_if_possible", before_preview)

    def test_route_diff_precedes_confirmation_and_apply(self):
        route_diff = self.selected_routes_source.index('st.markdown("**Scene / Illustration diff**")')
        hidden_count = self.selected_routes_source.index("hidden_count =", route_diff)
        confirm = self.selected_routes_source.index("confirm_key =", hidden_count)
        apply_button = self.selected_routes_source.index('key=f"{key_prefix}_apply_btn"', confirm)
        self.assertLess(route_diff, hidden_count)
        self.assertLess(hidden_count, confirm)
        self.assertLess(confirm, apply_button)

    def test_atomic_apply_commits_history_and_autosave_only_after_success(self):
        apply_call = self.selected_routes_source.index(
            "result = apply_selected_routes_attribute_group_swap"
        )
        success = self.selected_routes_source.index('if result.get("applied"):', apply_call)
        push = self.selected_routes_source.index("push_history()", success)
        assign = self.selected_routes_source.index(
            'st.session_state.project = result["updated_project"]', success
        )
        autosave = self.selected_routes_source.index(
            'save_current_project_if_possible("selected Routes attribute group swap applied")',
            success,
        )
        self.assertLess(apply_call, success)
        self.assertLess(success, push)
        self.assertLess(push, assign)
        self.assertLess(assign, autosave)

    def test_preview_discloses_slot_negative_metadata_drift_and_preserved_state(self):
        for text in (
            "Attribute Slot",
            "Negative Prompt: unchanged",
            "negative_when_disabled",
            "Drift risk",
            "本編画像",
            "Gallery Variant",
            "source_generation_info",
            "lineage_info",
        ):
            self.assertIn(text, self.selected_routes_source)

    def test_existing_group_keys_and_require_full_match_are_reused(self):
        self.assertIn('key="gallery_attribute_group_swap_from"', self.gallery_source)
        self.assertIn('key="gallery_attribute_group_swap_to"', self.gallery_source)
        self.assertIn('key="gallery_attribute_group_swap_require_full_match"', self.gallery_source)
        self.assertIn('key="_attribute_group_swap_from_widget"', self.apply_source)
        self.assertIn('key="_attribute_group_swap_to_widget"', self.apply_source)
        self.assertIn('key="_attribute_group_swap_scope_widget"', self.apply_source)
        self.assertIn(
            'key="_attribute_group_swap_selected_route_id_widget"',
            self.apply_source,
        )
        self.assertIn(
            'key="_attribute_group_swap_require_full_match_widget"',
            self.apply_source,
        )

    def test_unrelated_operations_and_schema_remain_disconnected(self):
        self.assertNotIn("apply_module_swap", self.selected_routes_source)
        self.assertNotIn("candidate_prompt_adoption", self.selected_routes_source)
        self.assertNotIn("execute_gallery_generation_plan", self.selected_routes_source)
        self.assertNotIn("selected_route_ids:", self.project_source)
        self.assertNotIn("route_id:", self.project_source)


if __name__ == "__main__":
    unittest.main()
