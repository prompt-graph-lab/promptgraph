from pathlib import Path
import unittest


class GalleryGenerationSelectedRoutesUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app_source = (root / "app.py").read_text(encoding="utf-8")
        cls.project_source = (root / "core" / "project.py").read_text(encoding="utf-8")

    def test_scope_is_added_without_replacing_existing_scopes_or_single_route_selector(self):
        start = self.app_source.index("def render_gallery_global_generation_controls")
        source = self.app_source[start:self.app_source.index("def render_gallery_batch_candidate_adoption", start)]
        self.assertIn(
            '["all_lines", "current_route", "selected_route", "selected_routes", "selected_lines"]',
            source,
        )
        self.assertIn('if scope == "selected_route":', source)
        self.assertIn('key="_gallery_generation_selected_route_id_widget"', source)
        self.assertIn('"gallery_generation_selected_route_id"', source)
        self.assertIn('if scope == "selected_routes":', source)

    def test_selected_routes_use_common_selection_and_fresh_preflight(self):
        self.assertIn('st.session_state.get("gallery_selected_route_ids", [])', self.app_source)
        self.assertIn("build_selected_routes_generation_plan", self.app_source)
        self.assertIn("gallery_generation_selected_routes_preview", self.app_source)
        self.assertIn("validate_selected_routes_generation_submit", self.app_source)
        self.assertIn("full_preflight: bool = False", self.app_source)
        self.assertIn("full_preflight=False", self.app_source)
        self.assertEqual(2, self.app_source.count("full_preflight=True"))
        self.assertIn("fresh_plan = _build_selected_routes_gallery_generation_plan", self.app_source)
        self.assertIn("execute_gallery_generation_plan", self.app_source)
        self.assertNotIn("gallery_generation_selected_route_ids", self.app_source)

    def test_normal_rerun_is_cheap_and_full_preflight_is_button_or_submit_only(self):
        start = self.app_source.index("def render_gallery_global_generation_controls")
        end = self.app_source.index("def render_gallery_batch_candidate_adoption", start)
        source = self.app_source[start:end]
        current_plan = source.index("current_plan = _build_selected_routes_gallery_generation_plan")
        fresh_button = source.index('"Fresh Preview"')
        first_full = source.index("full_preflight=True")
        submit_full = source.rindex("full_preflight=True")
        self.assertLess(current_plan, fresh_button)
        self.assertIn("full_preflight=False", source[current_plan:fresh_button])
        self.assertGreater(first_full, fresh_button)
        self.assertGreater(submit_full, source.index("pro_gallery_selected_routes_generate"))

    def test_selected_routes_generation_stays_candidate_first_and_separate(self):
        start = self.app_source.index("def _execute_selected_routes_gallery_generation_plan")
        end = self.app_source.index("def render_gallery_global_generation_controls", start)
        execution_source = self.app_source[start:end]
        self.assertIn('"gallery_global_generate"', execution_source)
        self.assertIn("_append_line_generated_candidates", execution_source)
        self.assertNotIn("selected_candidate_path =", execution_source)
        self.assertNotIn("generated_image_path =", execution_source)
        self.assertNotIn("image_path =", execution_source)
        self.assertNotIn("apply_route_batch_candidate_adoption", execution_source)
        self.assertNotIn("module_swap", execution_source)

    def test_no_project_or_prompt_line_schema_field_is_added(self):
        self.assertNotIn("selected_route_ids:", self.project_source)
        self.assertNotIn("route_id:", self.project_source)
        self.assertNotIn("generation_plan:", self.project_source)


if __name__ == "__main__":
    unittest.main()
