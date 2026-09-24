from pathlib import Path
import unittest


class RouteBatchCandidateAdoptionSelectedRoutesUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    def test_selected_routes_scope_uses_shared_session_selection(self):
        start = cls_start = self.app_source.index("def render_gallery_batch_candidate_adoption")
        end = self.app_source.index("\ndef render_gallery_batch_variant_promotion", start)
        source = self.app_source[cls_start:end]
        self.assertIn('"selected_routes": "Selected Scenes"', source)
        self.assertIn('st.session_state.get("gallery_selected_route_ids", [])', source)
        self.assertIn("sanitize_selected_route_ids", source)
        self.assertNotIn("route_batch_candidate_adoption_selected_route_ids", source)

    def test_selected_routes_hides_existing_single_route_selector(self):
        start = self.app_source.index("def render_gallery_batch_candidate_adoption")
        end = self.app_source.index("\ndef render_gallery_batch_variant_promotion", start)
        source = self.app_source[start:end]
        selector_start = source.index('if preview_scope == "selected_route":')
        selector_end = source.index('if preview_scope == "selected_routes":', selector_start)
        selector_source = source[selector_start:selector_end]
        self.assertIn("route_batch_candidate_adoption_preview_selected_route_id", selector_source)
        self.assertIn("_route_batch_candidate_adoption_preview_selected_route_id_widget", selector_source)
        self.assertNotIn("gallery_selected_route_ids", selector_source)

    def test_preview_signature_and_atomic_apply_are_wired(self):
        self.assertIn("build_selected_routes_candidate_adoption_signature", self.app_source)
        self.assertIn("build_selected_routes_candidate_adoption_preview", self.app_source)
        self.assertIn("apply_selected_routes_candidate_adoption", self.app_source)
        self.assertIn("expected_signature=preview_signature", self.app_source)
        self.assertIn("apply_and_publish_selected_routes_candidate_adoption(", self.app_source)
        apply_start = self.app_source.index('if st.button(\n                "Apply Scene Candidate Adoption"')
        apply_end = self.app_source.index("        st.divider()", apply_start)
        apply_source = self.app_source[apply_start:apply_end]
        self.assertIn('if preview_scope == "selected_routes":', apply_source)
        self.assertIn('                else:\n                    prev_focus', apply_source)
        self.assertLess(apply_source.index("apply_and_publish_selected_routes_candidate_adoption("),
                        apply_source.index("                st.rerun()"))

    def test_selected_routes_remain_disconnected_from_unrelated_operations(self):
        self.assertNotIn("gallery_generation_selected_route_ids", self.app_source)
        self.assertNotIn("gallery_module_swap_selected_route_ids", self.app_source)
        self.assertNotIn("candidate_prompt_adoption_selected_route_ids", self.app_source)


if __name__ == "__main__":
    unittest.main()
