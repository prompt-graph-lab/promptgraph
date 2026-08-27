import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest


class SessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(source, node)


class GalleryRouteOperationPanelUnificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )
        cls.route_operations_source = (
            Path(__file__).resolve().parents[1] / "core" / "route_operations.py"
        ).read_text(encoding="utf-8")
        cls.launcher_source = function_source(
            cls.app_source,
            "render_gallery_operations_launcher",
        )
        cls.panel_source = function_source(
            cls.app_source,
            "render_gallery_active_operation_panel",
        )
        cls.button_source = function_source(
            cls.app_source,
            "_render_gallery_operation_buttons",
        )
        cls.reset_source = function_source(
            cls.app_source,
            "reset_gallery_route_action_session_state",
        )

    def _state_namespace(self, initial=None):
        state = SessionState(initial or {})
        namespace = {"st": SimpleNamespace(session_state=state)}
        for name in (
            "_prepare_gallery_operation_widget_state",
            "_sync_gallery_operation_widget_state",
            "_clear_gallery_operation_safety_confirmation",
            "_gallery_operation_workflow_group",
        ):
            exec(function_source(self.app_source, name), namespace)
        return state, namespace

    def test_phase_actions_map_to_their_own_workflow_positions(self):
        state, namespace = self._state_namespace()
        group = namespace["_gallery_operation_workflow_group"]

        self.assertEqual("route", group("module_swap"))
        self.assertEqual("generation", group("gallery_generation"))
        self.assertEqual("adoption", group("batch_candidate_adoption"))
        self.assertEqual("line", group("candidate_route_creation"))
        self.assertEqual("", group("unknown"))

    def test_hidden_widget_mirror_restores_generation_draft(self):
        state, namespace = self._state_namespace(
            {
                "gallery_generation_scope": "selected_routes",
                "gallery_generation_selected_routes_preview": {"signature": "fresh"},
            }
        )
        prepare = namespace["_prepare_gallery_operation_widget_state"]
        sync = namespace["_sync_gallery_operation_widget_state"]

        prepare(
            "gallery_generation_scope",
            "_gallery_generation_scope_widget",
            "all_lines",
            options=["all_lines", "selected_routes", "current_route"],
        )
        self.assertEqual("selected_routes", state["_gallery_generation_scope_widget"])

        state["_gallery_generation_scope_widget"] = "current_route"
        sync("gallery_generation_scope", "_gallery_generation_scope_widget")
        state.pop("_gallery_generation_scope_widget")
        prepare(
            "gallery_generation_scope",
            "_gallery_generation_scope_widget",
            "all_lines",
            options=["all_lines", "selected_routes", "current_route"],
        )

        self.assertEqual("current_route", state["gallery_generation_scope"])
        self.assertEqual("current_route", state["_gallery_generation_scope_widget"])
        self.assertEqual(
            {"signature": "fresh"},
            state["gallery_generation_selected_routes_preview"],
        )

    def test_hidden_widget_mirror_restores_adoption_draft(self):
        state, namespace = self._state_namespace(
            {
                "route_batch_candidate_adoption_preview_scope": "selected_route",
                "route_batch_candidate_adoption_preview_selected_route_id": "route_b",
                "route_batch_candidate_adoption_preview": {"signature": "fresh"},
            }
        )
        prepare = namespace["_prepare_gallery_operation_widget_state"]

        prepare(
            "route_batch_candidate_adoption_preview_scope",
            "_route_batch_candidate_adoption_preview_scope_widget",
            "all_lines",
            options=["all_lines", "selected_route", "selected_routes"],
        )
        prepare(
            "route_batch_candidate_adoption_preview_selected_route_id",
            "_route_batch_candidate_adoption_preview_selected_route_id_widget",
            "route_a",
            options=["route_a", "route_b"],
        )

        self.assertEqual(
            "selected_route",
            state["_route_batch_candidate_adoption_preview_scope_widget"],
        )
        self.assertEqual(
            "route_b",
            state["_route_batch_candidate_adoption_preview_selected_route_id_widget"],
        )
        self.assertEqual(
            {"signature": "fresh"},
            state["route_batch_candidate_adoption_preview"],
        )

    def test_safety_clear_preserves_drafts_previews_and_gallery_state(self):
        durable = {
            "gallery_generation_scope": "selected_routes",
            "gallery_generation_selected_routes_preview": {"signature": "generation"},
            "route_batch_candidate_adoption_preview_scope": "selected_routes",
            "route_batch_candidate_adoption_preview": {"signature": "adoption"},
            "gallery_selected_route_ids": ["route_a", "route_b"],
            "focused_line_id": "line_a",
            "gallery_expanded_line_id": "line_b",
            "gallery_page": 3,
            "history": ["snapshot"],
            "project": object(),
        }
        one_shot = {
            "_gallery_generation_selected_routes_confirm_widget": True,
            "_route_batch_candidate_adoption_all_confirm_phrase_widget": "APPLY ALL",
            "_route_batch_candidate_adoption_confirm_widget": True,
            "_gallery_candidate_adoption_confirm_widget": True,
        }
        state, namespace = self._state_namespace({**durable, **one_shot})

        namespace["_clear_gallery_operation_safety_confirmation"]()

        for key, value in durable.items():
            self.assertIs(state[key], value) if key == "project" else self.assertEqual(state[key], value)
        for key in one_shot:
            self.assertNotIn(key, state)

    def test_launcher_is_thin_and_switches_only_active_operation(self):
        self.assertIn("st.session_state.gallery_operations_active = action_key", self.button_source)
        self.assertEqual(1, self.button_source.count("st.rerun()"))
        self.assertIn("_clear_gallery_operation_safety_confirmation()", self.button_source)
        for forbidden in (
            "st.session_state.project =",
            "push_history(",
            "save_current_project_if_possible(",
            "preview_",
            "generate_image_with_progress(",
            "gallery_selected_route_ids =",
            "gallery_move_targets =",
            "gallery_page =",
            "focused_line_id =",
        ):
            self.assertNotIn(forbidden, self.button_source)

    def test_panel_has_one_header_close_owner_and_embedded_bodies(self):
        self.assertEqual(1, self.panel_source.count('key="gallery_operations_close"'))
        self.assertIn('"gallery_generation": "Scene Generation / シーンを一括生成"', self.panel_source)
        self.assertIn(
            '"batch_candidate_adoption": "Scene Batch Candidate Adoption"',
            self.panel_source,
        )
        self.assertEqual(2, self.panel_source.count("embedded=True"))
        self.assertIn("_clear_gallery_operation_safety_confirmation()", self.panel_source)
        self.assertIn("_render_gallery_operation_context(project, get_selected_line_ids(project))", self.panel_source)
        self.assertLess(
            self.panel_source.index("if active_operation not in labels:"),
            self.panel_source.index("with st.container(border=True):"),
        )

    def test_embedded_mode_skips_only_the_owner_expander(self):
        namespace = {"contextmanager": contextmanager}

        class FakeStreamlit:
            def __init__(self):
                self.expander_calls = 0

            @contextmanager
            def expander(self, _label, *, expanded):
                self.expander_calls += 1
                yield

        fake = FakeStreamlit()
        namespace["st"] = fake
        exec(function_source(self.app_source, "_gallery_operation_body_container"), namespace)
        container = contextmanager(namespace["_gallery_operation_body_container"])

        with container("Generation", expanded=False, embedded=True):
            pass
        self.assertEqual(0, fake.expander_calls)
        with container("Generation", expanded=False, embedded=False):
            pass
        self.assertEqual(1, fake.expander_calls)

    def test_project_transition_reset_clears_operation_drafts_and_previews(self):
        for key in (
            "gallery_operations_active",
            "gallery_generation_scope",
            "gallery_generation_selected_route_id",
            "gallery_generation_run_count",
            "gallery_generation_selected_routes_preview",
            "route_batch_candidate_adoption_preview_source",
            "route_batch_candidate_adoption_preview_scope",
            "route_batch_candidate_adoption_preview_selected_route_id",
            "route_batch_candidate_adoption_preview",
            "gallery_candidate_adoption_source",
            "gallery_candidate_adoption_mode",
            "gallery_candidate_adoption_scope",
            "gallery_candidate_adoption_preview",
        ):
            self.assertIn(f'"{key}"', self.reset_source)
        self.assertGreaterEqual(
            self.app_source.count("reset_gallery_route_action_session_state()"),
            4,
        )

    def test_failed_json_project_load_preserves_current_operation_state(self):
        load_source = function_source(self.app_source, "load_project_json_into_session")
        read_project = load_source.index("project = load_project_from_json(project_path)")
        build_project = load_source.index("project = build_graph(project)")
        clear_history = load_source.index("st.session_state.history = []")
        reset_operations = load_source.index("reset_gallery_route_action_session_state()")
        commit_project = load_source.index("st.session_state.project = project")

        self.assertLess(read_project, build_project)
        self.assertLess(build_project, clear_history)
        self.assertLess(clear_history, reset_operations)
        self.assertLess(reset_operations, commit_project)

        current_project = object()
        initial_state = SessionState(
            {
                "project": current_project,
                "history": ["undo"],
                "gallery_operations_active": "gallery_generation",
                "gallery_generation_scope": "selected_routes",
                "gallery_generation_selected_routes_preview": {"signature": "fresh"},
            }
        )

        @contextmanager
        def profile_block(_label):
            yield

        def fail_load(_path):
            raise ValueError("invalid synthetic Project")

        namespace = {
            "os": SimpleNamespace(path=SimpleNamespace(exists=lambda _path: True)),
            "st": SimpleNamespace(session_state=initial_state, warning=lambda _message: None),
            "profile_block": profile_block,
            "load_project_from_json": fail_load,
        }
        exec(load_source, namespace)
        with self.assertRaisesRegex(ValueError, "invalid synthetic Project"):
            namespace["load_project_json_into_session"]("broken.json")

        self.assertIs(current_project, initial_state["project"])
        self.assertEqual(["undo"], initial_state["history"])
        self.assertEqual("gallery_generation", initial_state["gallery_operations_active"])
        self.assertEqual("selected_routes", initial_state["gallery_generation_scope"])
        self.assertEqual(
            {"signature": "fresh"},
            initial_state["gallery_generation_selected_routes_preview"],
        )

    def test_route_shortcuts_open_the_unified_generation_and_adoption_panels(self):
        pending_source = function_source(
            self.route_operations_source,
            "get_route_action_pending_updates",
        )
        self.assertIn('"generation": "gallery_generation"', pending_source)
        self.assertIn('"candidate_adoption": "batch_candidate_adoption"', pending_source)
        self.assertIn('"final_export":', pending_source)
        self.assertIn('updates["gallery_operation_focus"] = operation', pending_source)


if __name__ == "__main__":
    unittest.main()
