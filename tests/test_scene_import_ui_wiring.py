import ast
from pathlib import Path
import unittest

from ui.scene_import_lifecycle import (
    SCENE_IMPORT_APPLY_RESULT_KEY,
    SCENE_IMPORT_FEEDBACK_KEY,
    SCENE_IMPORT_PREVIEW_KEY,
    SCENE_IMPORT_SOURCE_PATH_KEY,
    SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY,
    set_scene_import_source_path,
    set_scene_import_source_separator_id,
)
from ui.scene_import_panel import reset_scene_import_panel_state


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(source, node)


class SceneImportUIWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app_source = (root / "app.py").read_text(encoding="utf-8")
        cls.panel_source = (root / "ui" / "scene_import_panel.py").read_text(encoding="utf-8")
        cls.panel_module = ast.parse(cls.panel_source)
        cls.launcher_source = function_source(cls.app_source, "render_gallery_operations_launcher")
        cls.active_panel_source = function_source(cls.app_source, "render_gallery_active_operation_panel")
        cls.group_source = function_source(cls.app_source, "_gallery_operation_workflow_group")
        cls.reset_source = function_source(cls.app_source, "reset_gallery_route_action_session_state")
        cls.render_source = function_source(cls.panel_source, "render_scene_import_panel")
        cls.discovery_source = function_source(cls.panel_source, "_discover_source_routes")
        cls.input_sync_source = function_source(cls.panel_source, "_sync_source_inputs")
        cls.review_source = function_source(cls.panel_source, "_render_preview_review")
        cls.apply_result_source = function_source(cls.panel_source, "_render_apply_result")

    def test_operation_is_in_structural_edit_group_and_route_workflow(self):
        self.assertIn('"scene_import"', self.group_source)
        self.assertIn('"scene_import",\n                    "Scene Import / シーンを取り込む"', self.launcher_source)
        self.assertIn("Source画像・Candidates・Variantsはコピーせず", self.launcher_source)
        self.assertIn("現在のProject末尾へ追加します", self.launcher_source)
        self.assertIn('_render_gallery_active_operation_for_workflow(project, "route")', self.launcher_source)

    def test_active_panel_labels_dispatches_and_closes_scene_import(self):
        self.assertIn('"scene_import": "Scene Import / シーンを取り込む"', self.active_panel_source)
        self.assertIn('elif active_operation == "scene_import":', self.active_panel_source)
        self.assertIn("render_scene_import_panel(", self.active_panel_source)
        self.assertIn("synchronize_selected_routes=_set_gallery_selected_route_ids_after_structure_change", self.active_panel_source)
        self.assertIn("restore_focus_after_graph_update=restore_focus_after_graph_update", self.active_panel_source)
        self.assertIn("save_current_project_if_possible=save_current_project_if_possible", self.active_panel_source)
        self.assertIn("load_project_from_json=load_project_from_json", self.active_panel_source)
        close_source = self.active_panel_source.split('if header_cols[1].button("閉じる"', 1)[1].split(
            "st.caption(", 1
        )[0]
        self.assertIn('elif active_operation == "scene_import":', close_source)
        self.assertIn("reset_scene_import_panel_state(st.session_state)", close_source)

    def test_broad_gallery_project_reset_clears_scene_import_state(self):
        self.assertIn("reset_scene_import_panel_state(st.session_state)", self.reset_source)
        reset_function = function_source(self.panel_source, "reset_scene_import_panel_state")
        self.assertIn("reset_scene_import_operation_state(session_state)", reset_function)
        for widget_key in (
            "SCENE_IMPORT_SOURCE_PATH_WIDGET_KEY",
            "SCENE_IMPORT_SOURCE_SEPARATOR_WIDGET_KEY",
            "SCENE_IMPORT_CONFIRM_WIDGET_KEY",
        ):
            self.assertIn(widget_key, reset_function)
        self.assertIn("session_state.pop(key, None)", reset_function)

    def test_operation_reset_clears_only_scene_import_state(self):
        state = {
            SCENE_IMPORT_SOURCE_PATH_KEY: "C:/source.json",
            SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY: "separator-a",
            SCENE_IMPORT_PREVIEW_KEY: {"plan_id": "preview"},
            SCENE_IMPORT_APPLY_RESULT_KEY: {"applied": True},
            SCENE_IMPORT_FEEDBACK_KEY: {"kind": "success"},
            "_scene_import_source_path_widget": "C:/source.json",
            "_scene_import_source_separator_widget": "separator-a",
            "_scene_import_confirm_widget": True,
            "gallery_selected_route_ids": ["target-route"],
            "focused_line_id": "target-line",
            "history": ["undo"],
        }

        reset_scene_import_panel_state(state)

        self.assertEqual({
            "gallery_selected_route_ids": ["target-route"],
            "focused_line_id": "target-line",
            "history": ["undo"],
        }, state)

    def test_widget_mirrors_are_distinct_and_changes_use_lifecycle_setters(self):
        self.assertIn('"_scene_import_source_path_widget"', self.panel_source)
        self.assertIn('"_scene_import_source_separator_widget"', self.panel_source)
        self.assertIn('"_scene_import_confirm_widget"', self.panel_source)
        self.assertNotIn('key=SCENE_IMPORT_SOURCE_PATH_KEY', self.render_source)
        self.assertNotIn('key=SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY', self.render_source)
        self.assertIn("set_scene_import_source_path(session_state, source_path)", self.input_sync_source)
        self.assertIn("set_scene_import_source_separator_id(", self.input_sync_source)
        self.assertIn("session_state[SCENE_IMPORT_CONFIRM_WIDGET_KEY] = False", self.input_sync_source)

    def test_path_and_scene_selection_changes_clear_preview_and_confirmation(self):
        namespace = {
            "set_scene_import_source_path": set_scene_import_source_path,
            "set_scene_import_source_separator_id": set_scene_import_source_separator_id,
            "SCENE_IMPORT_SOURCE_SEPARATOR_WIDGET_KEY": "_scene_import_source_separator_widget",
            "SCENE_IMPORT_CONFIRM_WIDGET_KEY": "_scene_import_confirm_widget",
        }
        exec(self.input_sync_source, namespace)
        state = {
            SCENE_IMPORT_SOURCE_PATH_KEY: "C:/source-a.json",
            SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY: "separator-a",
            SCENE_IMPORT_PREVIEW_KEY: {"plan_id": "old"},
            SCENE_IMPORT_APPLY_RESULT_KEY: {"applied": True},
            SCENE_IMPORT_FEEDBACK_KEY: {"kind": "success", "code": "old"},
            "_scene_import_source_separator_widget": "separator-a",
            "_scene_import_confirm_widget": True,
        }

        changed_path = namespace["_sync_source_inputs"](
            state,
            "C:/source-b.json",
            "separator-a",
        )
        self.assertTrue(changed_path)
        self.assertNotIn(SCENE_IMPORT_PREVIEW_KEY, state)
        self.assertNotIn(SCENE_IMPORT_APPLY_RESULT_KEY, state)
        self.assertEqual("", state[SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY])
        self.assertEqual("", state["_scene_import_source_separator_widget"])
        self.assertFalse(state["_scene_import_confirm_widget"])

        state[SCENE_IMPORT_PREVIEW_KEY] = {"plan_id": "next"}
        state["_scene_import_confirm_widget"] = True
        changed_scene = namespace["_sync_source_inputs"](
            state,
            "C:/source-b.json",
            "separator-b",
        )
        self.assertTrue(changed_scene)
        self.assertNotIn(SCENE_IMPORT_PREVIEW_KEY, state)
        self.assertEqual("separator-b", state[SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY])
        self.assertFalse(state["_scene_import_confirm_widget"])

    def test_source_discovery_uses_existing_loader_and_gallery_route_options(self):
        self.assertIn("load_project_from_json(source_path)", self.discovery_source)
        self.assertIn("get_gallery_route_options(source_project)", self.discovery_source)
        self.assertIn('"separator_id": route_id', self.discovery_source)
        self.assertIn('"illustration_count": count', self.discovery_source)
        self.assertNotIn("session_state", self.discovery_source)
        self.assertIn("type(count) is not int or count < 0", self.discovery_source)

    def test_source_route_discovery_returns_only_selector_data_and_keeps_empty_scenes(self):
        namespace = {
            "Any": object,
            "load_project_from_json": lambda _path: source_project,
            "get_gallery_route_options": lambda project: [
                {"route_id": "separator-empty", "route_label": "Empty Scene", "line_count": 0},
                {"route_id": "separator-filled", "route_label": "Filled Scene", "line_count": 2},
            ],
        }
        source_project = object()
        exec(self.discovery_source, namespace)
        routes, error = namespace["_discover_source_routes"](
            "another.json",
            load_project_from_json=namespace["load_project_from_json"],
        )

        self.assertIsNone(error)
        self.assertEqual(
            [
                {"separator_id": "separator-empty", "label": "Empty Scene", "illustration_count": 0},
                {"separator_id": "separator-filled", "label": "Filled Scene", "illustration_count": 2},
            ],
            routes,
        )
        self.assertNotIn(source_project, routes)

    def test_selector_uses_separator_id_and_label_plus_count_for_display(self):
        self.assertIn('route_ids = [route["separator_id"] for route in routes]', self.render_source)
        self.assertIn("selector_options = [\"\", *route_ids]", self.render_source)
        self.assertIn("format_func=_route_label", self.render_source)
        self.assertIn("route.get('label', 'Scene')", self.render_source)
        self.assertIn("route.get('illustration_count', 0)", self.render_source)
        self.assertIn("current_widget_separator not in route_ids", self.render_source)
        self.assertIn("set_scene_import_source_separator_id(session_state, \"\")", self.render_source)

    def test_preview_is_explicit_and_dispatched_through_lifecycle_only(self):
        fresh_button = self.render_source.index('st.button("Fresh Preview"')
        preview_dispatch = self.render_source.index("build_scene_import_preview_from_source(", fresh_button)
        self.assertLess(fresh_button, preview_dispatch)
        self.assertEqual(1, self.render_source.count("build_scene_import_preview_from_source("))
        self.assertNotIn("preview_scene_import(", self.panel_source)
        self.assertIn("session_state[SCENE_IMPORT_CONFIRM_WIDGET_KEY] = False", self.render_source[preview_dispatch:])
        self.assertIn("preview = session_state.get(SCENE_IMPORT_PREVIEW_KEY)", self.render_source)

    def test_preview_review_includes_summary_modules_prompts_and_blockers(self):
        for expected in (
            "source_scene_label",
            "planned_illustrations",
            "target_line_count",
            "insertion_index",
            "planned_separator",
            "module_actions",
            '"reuse"',
            '"import"',
            '"conflict"',
            '"current_text"',
            '"negative_prompt"',
            '"plan_id"',
            '"projection_digest"',
            '"target_freshness_fingerprint"',
            "blockers",
        ):
            self.assertIn(expected, self.review_source)
        self.assertIn("Source画像", self.review_source)
        self.assertIn("Candidates", self.review_source)
        self.assertIn("Gallery Variants", self.review_source)
        self.assertNotIn('action.get("import_definition")', self.review_source)

    def test_apply_requires_valid_eligible_preview_and_explicit_one_scene_confirmation(self):
        self.assertIn('preview.get("valid") is True and preview.get("eligible") is True', self.render_source)
        self.assertIn('"このSceneを現在のProject末尾へ追加することを確認しました"', self.render_source)
        self.assertIn('disabled=not confirmed', self.render_source)
        self.assertIn('if not confirmable:', self.render_source)
        self.assertIn("_render_preview_review(preview)", self.render_source)
        self.assertLess(self.render_source.index("_render_preview_review(preview)"), self.render_source.index("st.checkbox("))

    def test_apply_uses_lifecycle_and_existing_host_callbacks_only(self):
        self.assertEqual(1, self.render_source.count("apply_and_publish_scene_import("))
        self.assertNotIn("apply_scene_import(", self.panel_source)
        self.assertIn("load_project_from_json=load_project_from_json", self.render_source)
        self.assertIn("synchronize_selected_routes=synchronize_selected_routes", self.render_source)
        self.assertIn("restore_focus_after_graph_update=restore_focus_after_graph_update", self.render_source)
        self.assertIn("save_current_project_if_possible=save_current_project_if_possible", self.render_source)
        self.assertIn("st.rerun()", self.render_source)

    def test_panel_does_not_duplicate_core_history_graph_or_save_owners(self):
        for forbidden in (
            "push_history(",
            "build_graph(",
            "save_project_to_json(",
            "save_current_project_if_possible(",
            "apply_scene_import(",
        ):
            self.assertNotIn(forbidden, self.panel_source)

    def test_apply_result_distinguishes_in_memory_success_and_host_persistence_feedback(self):
        self.assertIn('result.get("applied") is True', self.apply_result_source)
        self.assertIn("追加したIllustration", self.apply_result_source)
        self.assertIn("追加したModule", self.apply_result_source)
        self.assertIn("再利用したModule", self.apply_result_source)
        self.assertIn("既存自動保存表示", self.apply_result_source)
        self.assertIn("Fresh Previewを作成", self.apply_result_source)

    def test_no_agent_mutation_surface_is_added(self):
        self.assertNotIn("mcp_", self.panel_source.lower())
        self.assertNotIn("agent_", self.panel_source.lower())


if __name__ == "__main__":
    unittest.main()
