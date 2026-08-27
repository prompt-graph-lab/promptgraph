from pathlib import Path
import unittest


class SelectedRoutesModuleSwapUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app_source = (root / "app.py").read_text(encoding="utf-8")
        cls.project_source = (root / "core" / "project.py").read_text(encoding="utf-8")
        start = cls.app_source.index("def _render_selected_routes_module_swap_preview")
        end = cls.app_source.index("def render_global_module_candidate_scanner_section", start)
        cls.module_swap_source = cls.app_source[start:end]

    def test_selected_routes_scope_is_added_without_replacing_existing_scopes(self):
        for scope in ('"all"', '"line_group"', '"route"', '"selected_routes"'):
            self.assertIn(scope, self.module_swap_source)
        self.assertIn('key="module_swap_routes"', self.module_swap_source)
        self.assertIn('if scope_key == "selected_routes":', self.module_swap_source)

    def test_common_gallery_selection_is_used_without_a_second_route_list(self):
        self.assertIn('st.session_state.get("gallery_selected_route_ids", [])', self.module_swap_source)
        self.assertIn("sanitize_selected_route_ids", self.module_swap_source)
        self.assertNotIn("module_swap_selected_route_ids", self.app_source)
        selected_branch = self.module_swap_source.index('if scope_key == "selected_routes":')
        module_body = self.module_swap_source.index("source_body = get_module_body", selected_branch)
        self.assertNotIn("st.multiselect", self.module_swap_source[selected_branch:module_body])

    def test_normal_rerun_uses_signature_and_full_plan_is_preview_only(self):
        signature_call = self.module_swap_source.index("build_selected_routes_module_swap_signature")
        preview_button = self.module_swap_source.index('key="module_swap_preview_btn"')
        full_plan_call = self.module_swap_source.index("build_selected_routes_module_swap_plan")
        self.assertLess(signature_call, preview_button)
        self.assertGreater(full_plan_call, preview_button)
        self.assertEqual(1, self.module_swap_source.count("build_selected_routes_module_swap_plan"))

    def test_atomic_apply_commits_history_and_autosave_only_after_success(self):
        apply_call = self.module_swap_source.index("result = apply_selected_routes_module_swap")
        success = self.module_swap_source.index('if result.get("applied"):', apply_call)
        push = self.module_swap_source.index("push_history()", success)
        assign = self.module_swap_source.index('st.session_state.project = result["updated_project"]', success)
        autosave = self.module_swap_source.index(
            'save_current_project_if_possible("Selected Routes Module Swap applied")', success
        )
        self.assertLess(apply_call, success)
        self.assertLess(success, push)
        self.assertLess(push, assign)
        self.assertLess(assign, autosave)

    def test_route_diff_precedes_confirmation_and_apply(self):
        route_diff = self.module_swap_source.index('st.markdown("**Scene / Illustration diff**")')
        hidden_count = self.module_swap_source.index("hidden_count =", route_diff)
        confirm = self.module_swap_source.index('key="module_swap_selected_routes_confirm"')
        apply_button = self.module_swap_source.index('key="module_swap_selected_routes_apply_btn"')
        self.assertLess(route_diff, hidden_count)
        self.assertLess(hidden_count, confirm)
        self.assertLess(confirm, apply_button)

    def test_preview_discloses_drift_and_preserved_image_candidate_provenance(self):
        for text in (
            "Drift risk",
            "本編画像",
            "Gallery Variant",
            "source_generation_info",
            "lineage_info",
            "Negative Prompt: unchanged",
        ):
            self.assertIn(text, self.module_swap_source)

    def test_unrelated_operations_and_schema_remain_disconnected(self):
        self.assertNotIn("apply_attribute_group_swap", self.module_swap_source)
        self.assertNotIn("candidate_prompt_adoption", self.module_swap_source)
        self.assertNotIn("execute_gallery_generation_plan", self.module_swap_source)
        self.assertNotIn("selected_route_ids:", self.project_source)
        self.assertNotIn("route_id:", self.project_source)


if __name__ == "__main__":
    unittest.main()
