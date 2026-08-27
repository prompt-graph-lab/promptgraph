import ast
from collections import Counter
from pathlib import Path
import unittest

from core.gallery_operation_scope_presentation import (
    GALLERY_OPERATION_SCOPE_PRESENTATION,
    get_gallery_operation_scope_presentation,
)


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
PRESENTATION_SOURCE = (
    ROOT / "core" / "gallery_operation_scope_presentation.py"
).read_text(encoding="utf-8")


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(source, node)


class GalleryOperationScopeClarityTests(unittest.TestCase):
    def test_capability_registry_pins_every_audited_operation(self):
        expected = {
            "module_swap": ("all", "line_group", "route", "selected_routes"),
            "attribute_group_swap": (
                "current_route",
                "selected_route",
                "selected_routes",
                "selected_lines",
                "all_lines",
            ),
            "batch_edit": (
                "all",
                "focus",
                "selected",
                "current_route",
                "selected_route",
                "group::*",
            ),
            "lightweight_fork": (
                "all_lines",
                "current_route",
                "selected_route",
                "selected_routes",
                "selected_lines",
            ),
            "gallery_generation": (
                "all_lines",
                "current_route",
                "selected_route",
                "selected_routes",
                "selected_lines",
            ),
            "batch_candidate_adoption": (
                "all_lines",
                "selected_lines",
                "current_route",
                "selected_route",
                "selected_routes",
            ),
            "batch_promote_variants": (
                "current_route",
                "selected_route",
                "selected_routes",
                "selected_lines",
                "all_lines",
            ),
            "candidate_route_creation": (
                "focused_line",
                "selected_lines",
                "current_route",
                "all_lines",
            ),
            "prompt_revert": (
                "all_lines",
                "current_route",
                "selected_route",
                "selected_lines",
            ),
            "module_candidates": (),
        }
        self.assertEqual(set(expected), set(GALLERY_OPERATION_SCOPE_PRESENTATION))
        for action_key, scope_ids in expected.items():
            self.assertEqual(
                scope_ids,
                GALLERY_OPERATION_SCOPE_PRESENTATION[action_key]["supported_scope_ids"],
            )
            for field in (
                "renderer_scope_labels",
                "uses_shared_selected_scenes",
                "has_single_scene_selector",
                "uses_selected_illustrations",
                "uses_current_context",
                "has_user_selectable_scope",
                "all_illustrations_may_include_outside_scenes",
            ):
                self.assertIn(field, GALLERY_OPERATION_SCOPE_PRESENTATION[action_key])

        self.assertEqual(
            ("すべてのイラスト", "Illustration Group", "Scene", "Selected Scenes"),
            GALLERY_OPERATION_SCOPE_PRESENTATION["module_swap"]["renderer_scope_labels"],
        )
        self.assertEqual(
            ("All", "Selected Illustrations (N)", "Current Scene", "Selected Scene", "Selected Scenes"),
            GALLERY_OPERATION_SCOPE_PRESENTATION["batch_candidate_adoption"]["renderer_scope_labels"],
        )
        self.assertFalse(
            GALLERY_OPERATION_SCOPE_PRESENTATION["module_candidates"]["has_user_selectable_scope"]
        )

    def test_registry_matches_authoritative_renderer_literals(self):
        renderer_literals = {
            "module_swap": (
                "render_module_swap_section",
                'scope_options = {\n            "all":',
                '"line_group":',
                '"route":',
                '"selected_routes":',
            ),
            "attribute_group_swap": (
                "render_gallery_attribute_group_swap_section",
                'options=["current_route", "selected_route", "selected_routes", "selected_lines", "all_lines"]',
            ),
            "gallery_generation": (
                "render_gallery_global_generation_controls",
                'scope_options = ["all_lines", "current_route", "selected_route", "selected_routes", "selected_lines"]',
            ),
            "batch_candidate_adoption": (
                "render_gallery_batch_candidate_adoption",
                '"all_lines",\n            "selected_lines",\n            "current_route",\n            "selected_route",\n            "selected_routes",',
            ),
            "candidate_route_creation": (
                "render_candidate_route_creation_section",
                'options=["focused_line", "selected_lines", "current_route", "all_lines"]',
            ),
            "prompt_revert": (
                "render_gallery_prompt_revert_section",
                '["all_lines", "current_route", "selected_route", "selected_lines"]',
            ),
        }
        for action_key, (renderer_name, *needles) in renderer_literals.items():
            renderer = function_source(APP_SOURCE, renderer_name)
            for needle in needles:
                self.assertIn(needle, renderer, action_key)

        variant_source = (ROOT / "core" / "gallery_variant_promotion.py").read_text(encoding="utf-8")
        self.assertIn(
            'VALID_SCOPES = (\n    "current_route",\n    "selected_route",\n    "selected_routes",\n    "selected_lines",\n    "all_lines",\n)',
            variant_source,
        )

    def test_shared_selected_scenes_usage_is_declared_only_for_readers(self):
        shared_readers = {
            "module_swap",
            "attribute_group_swap",
            "lightweight_fork",
            "gallery_generation",
            "batch_candidate_adoption",
            "batch_promote_variants",
        }
        declared = {
            key
            for key, entry in GALLERY_OPERATION_SCOPE_PRESENTATION.items()
            if entry["uses_shared_selected_scenes"]
        }
        self.assertEqual(shared_readers, declared)
        for key in shared_readers:
            self.assertIn(
                "selected_routes",
                GALLERY_OPERATION_SCOPE_PRESENTATION[key]["supported_scope_ids"],
            )
        for key in set(GALLERY_OPERATION_SCOPE_PRESENTATION) - shared_readers:
            self.assertNotIn(
                "selected_routes",
                GALLERY_OPERATION_SCOPE_PRESENTATION[key]["supported_scope_ids"],
            )

    def test_registry_is_display_only_and_not_imported_by_core_engines(self):
        self.assertIn("presentation metadata, not an execution capability registry", PRESENTATION_SOURCE)
        for path in (ROOT / "core").glob("*.py"):
            if path.name == "gallery_operation_scope_presentation.py":
                continue
            self.assertNotIn("gallery_operation_scope_presentation", path.read_text(encoding="utf-8"))
        for forbidden in (
            "from core.route_operations",
            "build_graph",
            "save_project_to_json",
            "push_history",
            "st.session_state",
            "os.walk",
            "glob(",
        ):
            self.assertNotIn(forbidden, PRESENTATION_SOURCE)

    def test_stable_panel_has_one_owner_and_is_passive(self):
        panel = function_source(APP_SOURCE, "render_gallery_selected_routes_controls")
        mode = function_source(APP_SOURCE, "render_pro_gallery_mode")
        self.assertEqual(1, APP_SOURCE.count("Operation Scope / 操作対象"))
        self.assertIn("Selected Scenes: {selected_count} / {selectable_count}", panel)
        self.assertIn("Illustrations outside Scenes are not included.", panel)
        self.assertIn("are therefore different targets.", panel)
        self.assertIn("operation’s own Target / Scope", panel)
        self.assertEqual(1, APP_SOURCE.count('key="gallery_selected_routes_select_all"'))
        self.assertEqual(1, APP_SOURCE.count('key="gallery_selected_routes_invert"'))
        self.assertEqual(1, APP_SOURCE.count('key="gallery_selected_routes_clear"'))
        self.assertNotIn("outside_scenes", panel)
        self.assertNotIn('if selected_route_state["selected_route_count"] > 0:', mode)
        self.assertLess(
            mode.index("render_gallery_selected_routes_controls(project, selected_route_state)"),
            mode.index("render_gallery_operations_launcher(project)"),
        )
        for forbidden in (
            "build_",
            "preview_",
            "apply_",
            "execute_",
            "generate_image",
            "push_history",
            "save_project",
            "st.session_state.project =",
        ):
            self.assertNotIn(forbidden, panel)

    def test_selected_scene_summary_is_bounded_and_disambiguates_duplicate_labels(self):
        source = function_source(APP_SOURCE, "_bounded_gallery_selected_scene_summary")
        namespace = {"Counter": Counter}
        exec(source, namespace)
        state = {
            "selectable_route_summaries": [
                {"route_handle": "scene_a", "label": "Same"},
                {"route_handle": "scene_b", "label": "Same"},
                {"route_handle": "scene_c", "label": "Third"},
                {"route_handle": "scene_d", "label": "Fourth"},
            ],
            "selected_route_summaries": [
                {"route_handle": "scene_a", "label": "Same"},
                {"route_handle": "scene_b", "label": "Same"},
                {"route_handle": "scene_c", "label": "Third"},
                {"route_handle": "scene_d", "label": "Fourth"},
            ],
        }
        self.assertEqual(
            "Same (scene_a), Same (scene_b), Third +1",
            namespace["_bounded_gallery_selected_scene_summary"](state),
        )

    def test_zero_selection_render_is_inert_and_keeps_all_controls_available(self):
        class FakeStreamlit:
            def __init__(self):
                self.session_state = {
                    "gallery_selected_route_ids": [],
                    "gallery_operations_active": "module_swap",
                    "history": ["unchanged"],
                    "project": object(),
                }
                self.captions = []
                self.buttons = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def container(self, **_kwargs):
                return self

            def expander(self, *_args, **_kwargs):
                return self

            def columns(self, count):
                return [self] * count

            def markdown(self, _text):
                pass

            def caption(self, text):
                self.captions.append(text)

            def dataframe(self, *_args, **_kwargs):
                pass

            def button(self, label, **kwargs):
                self.buttons.append((label, kwargs))
                return False

            def rerun(self):
                raise AssertionError("passive render must not rerun")

        fake = FakeStreamlit()
        original_state = dict(fake.session_state)
        namespace = {
            "st": fake,
            "Counter": Counter,
            "iter_gallery_operation_scope_presentations": (
                lambda: iter(GALLERY_OPERATION_SCOPE_PRESENTATION.values())
            ),
            "select_all_routes": lambda _project: (_ for _ in ()).throw(
                AssertionError("passive render selected Scenes")
            ),
            "invert_selected_routes": lambda *_args: (_ for _ in ()).throw(
                AssertionError("passive render inverted Scenes")
            ),
            "clear_selected_routes": lambda _project: (_ for _ in ()).throw(
                AssertionError("passive render cleared Scenes")
            ),
        }
        for name in (
            "_render_gallery_select_all_routes_button",
            "_bounded_gallery_selected_scene_summary",
            "_render_gallery_operation_scope_matrix",
            "render_gallery_selected_routes_controls",
        ):
            exec(function_source(APP_SOURCE, name), namespace)

        state = {
            "selected_route_count": 0,
            "selected_route_ids": [],
            "selectable_route_ids": ["scene_a", "scene_b", "scene_c"],
            "selected_route_summaries": [],
            "selectable_route_summaries": [
                {"route_handle": "scene_a", "label": "A"},
                {"route_handle": "scene_b", "label": "B"},
                {"route_handle": "scene_c", "label": "C"},
            ],
            "selected_main_line_count": 0,
            "selected_candidate_count": 0,
            "selected_gallery_variant_count": 0,
        }
        namespace["render_gallery_selected_routes_controls"](object(), state)

        self.assertIn("Selected Scenes: 0 / 3", fake.captions)
        buttons = {label: kwargs for label, kwargs in fake.buttons}
        self.assertFalse(buttons["すべてのシーンを選択"]["disabled"])
        self.assertFalse(buttons["選択を反転"]["disabled"])
        self.assertTrue(buttons["選択をクリア"]["disabled"])
        self.assertEqual(original_state, fake.session_state)

    def test_active_panel_adds_one_capability_line_before_each_body(self):
        panel = function_source(APP_SOURCE, "render_gallery_active_operation_panel")
        capability = function_source(APP_SOURCE, "_render_gallery_operation_scope_capability")
        self.assertEqual(1, panel.count("_render_gallery_operation_scope_capability(active_operation)"))
        self.assertLess(
            panel.index("_render_gallery_operation_scope_capability(active_operation)"),
            panel.index('if active_operation == "module_swap":'),
        )
        self.assertIn("Supported targets / 対応対象:", capability)
        self.assertIn("does not control this operation", capability)
        self.assertNotIn("st.session_state", capability)

    def test_lower_group_explains_shared_selection_boundary(self):
        launcher = function_source(APP_SOURCE, "render_gallery_operations_launcher")
        self.assertIn("rather than the shared", launcher)
        self.assertIn("unless the operation explicitly offers Selected Scenes", launcher)
        self.assertLess(
            launcher.index("rather than the shared"),
            launcher.index("render_gallery_batch_variant_promotion("),
        )

    def test_presentation_lookup_is_immutable_and_unknown_safe(self):
        entry = get_gallery_operation_scope_presentation("gallery_generation")
        self.assertIsNotNone(entry)
        with self.assertRaises(TypeError):
            entry["title"] = "changed"
        self.assertIsNone(get_gallery_operation_scope_presentation("unknown"))


if __name__ == "__main__":
    unittest.main()
