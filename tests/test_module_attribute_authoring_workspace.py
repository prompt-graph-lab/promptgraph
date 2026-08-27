import ast
import copy
import types
import unittest
from pathlib import Path

from core.operations import (
    build_attribute_group_negative_preview,
    create_library_module,
    rename_attribute_group,
    set_attribute_group_negative_metadata,
    set_attribute_group_slot,
    update_module_entry_preserving_metadata,
)
from core.project import Project, PromptLine


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _RenderStub:
    def __init__(self, session_state):
        self.session_state = session_state
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def markdown(self, message):
        self.messages.append(("markdown", message))


class ModuleAttributeAuthoringWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.app_source = (cls.root / "app.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.app_source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _function_source(self, name):
        return ast.get_source_segment(self.app_source, self.functions[name])

    def _load_functions(self, *names, namespace):
        module = ast.Module(
            body=[self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def _top_level_source(self):
        start = self.app_source.rindex("render_common_undo_sidebar_section()")
        return self.app_source[start:]

    def test_all_management_targets_dispatch_to_real_workspaces(self):
        shell = self._function_source("render_management_workspace_shell")
        expected = (
            ("project_management", "render_project_management_workspace()"),
            (
                "module_attribute_authoring",
                "render_module_attribute_authoring_workspace()",
            ),
            (
                "module_attribute_apply",
                "render_module_attribute_apply_workspace()",
            ),
            ("comfyui_settings", "render_comfyui_settings_workspace()"),
        )
        for target, render_call in expected:
            self.assertIn(f'if target == "{target}":', shell)
            self.assertEqual(shell.count(render_call), 1)
        self.assertNotIn("placeholder", shell.lower())
        self.assertNotIn("Planned destination", shell)

    def test_no_project_workspace_is_safe_and_does_not_invoke_authoring(self):
        calls = []
        session_state = _SessionState(project=None)
        st = _RenderStub(session_state)
        namespace = self._load_functions(
            "render_module_attribute_authoring_workspace",
            namespace={
                "st": st,
                "render_create_module_from_scratch_section": (
                    lambda project: calls.append(("module", project))
                ),
                "render_project_module_inspector_section": (
                    lambda project: calls.append(("editor", project))
                ),
                "render_module_rename_authoring_section": (
                    lambda project: calls.append(("rename", project))
                ),
                "render_attribute_group_sidebar_manager": (
                    lambda project: calls.append(("manager", project))
                ),
                "render_attribute_group_inspector_section": (
                    lambda project: calls.append(("inspector", project))
                ),
            },
        )

        namespace["render_module_attribute_authoring_workspace"]()

        self.assertEqual(calls, [])
        self.assertIsNone(session_state.project)
        self.assertTrue(
            any(
                kind == "info" and "Create or open a Project" in message
                for kind, message in st.messages
            )
        )
        workspace = self._function_source(
            "render_module_attribute_authoring_workspace"
        )
        for forbidden in (
            "load_project",
            "create_new_workspace",
            "Project(",
            "save_project",
            "save_global_module_library",
        ):
            self.assertNotIn(forbidden, workspace)

    def test_workspace_calls_each_moved_renderer_once_without_mutating_project(self):
        calls = []
        project = Project(
            source_directory="fixture",
            module_library={
                "pose": {
                    "body": "standing",
                    "type": "generic",
                    "extension": {"keep": True},
                }
            },
            attribute_groups={
                "outfit": {
                    "name": "Outfit",
                    "slot": "outfit",
                    "tokens": ["dress"],
                    "created_from": "test",
                    "negative_tags": ["hat"],
                    "negative_when_disabled": ["dress"],
                    "negative_notes": "metadata only",
                    "extension": {"keep": True},
                }
            },
        )
        before = copy.deepcopy(project)
        st = _RenderStub(_SessionState(project=project))
        namespace = self._load_functions(
            "render_module_attribute_authoring_workspace",
            namespace={
                "st": st,
                "render_create_module_from_scratch_section": (
                    lambda value: calls.append(("module", value))
                ),
                "render_project_module_inspector_section": (
                    lambda value: calls.append(("editor", value))
                ),
                "render_module_rename_authoring_section": (
                    lambda value: calls.append(("rename", value))
                ),
                "render_attribute_group_sidebar_manager": (
                    lambda value: calls.append(("manager", value))
                ),
                "render_attribute_group_inspector_section": (
                    lambda value: calls.append(("inspector", value))
                ),
            },
        )

        namespace["render_module_attribute_authoring_workspace"]()

        self.assertEqual(
            [name for name, _ in calls],
            ["module", "editor", "rename", "manager", "inspector"],
        )
        self.assertTrue(all(value is project for _, value in calls))
        self.assertEqual(project, before)

    def test_each_moved_renderer_has_one_call_owner(self):
        expected = (
            "render_create_module_from_scratch_section",
            "render_project_module_inspector_section",
            "render_module_rename_authoring_section",
            "render_attribute_group_sidebar_manager",
            "render_attribute_group_inspector_section",
        )
        call_owners = {name: [] for name in expected}
        for function_name, function_node in self.functions.items():
            for node in ast.walk(function_node):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in call_owners
                ):
                    call_owners[node.func.id].append(function_name)

        for name in expected:
            self.assertEqual(
                call_owners[name],
                ["render_module_attribute_authoring_workspace"],
                name,
            )
        rename_control_owners = []
        for function_name, function_node in self.functions.items():
            for node in ast.walk(function_node):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "render_module_rename_controls"
                ):
                    rename_control_owners.append(function_name)
        self.assertEqual(
            rename_control_owners,
            ["render_module_rename_authoring_section"],
        )

    def test_moved_renderers_use_workspace_container_and_keep_widget_keys(self):
        expected_keys = {
            "render_create_module_from_scratch_section": (
                "global_module_save_name",
                "global_module_load_name",
                "blank_module_name",
                "blank_module_body",
                "create_module_name",
                "create_module_body",
                "create_module_targets",
                "replace_with_module_targets",
            ),
            "render_attribute_group_sidebar_manager": (
                "attribute_group_sidebar_create_name",
                "attribute_group_sidebar_create_slot",
                "attribute_group_sidebar_create_tokens",
                "attribute_group_sidebar_selected",
            ),
            "render_attribute_group_inspector_section": (
                "attribute_group_inspector_selected",
                "attribute_group_rename_input_",
                "attribute_group_slot_edit_select_",
                "attribute_group_negative_tags_",
                "attribute_group_negative_when_disabled_",
                "attribute_group_negative_notes_",
            ),
            "render_module_rename_authoring_section": (
                "_module_rename_selected_widget",
            ),
        }
        for name, keys in expected_keys.items():
            source = self._function_source(name)
            self.assertIn("with st.expander(", source)
            self.assertNotIn("st.sidebar", source)
            for key in keys:
                self.assertIn(key, source)

        for name in (
            "render_create_module_from_scratch_section",
            "render_attribute_group_sidebar_manager",
            "render_attribute_group_inspector_section",
        ):
            self.assertIn("if is_free():", self._function_source(name))
        self.assertIn(
            "if is_free():",
            self._function_source("render_module_rename_controls"),
        )

    def test_sidebar_retains_apply_launcher_analysis_and_edit_scope_only(self):
        top_level = self._top_level_source()
        self.assertNotIn(
            'st.sidebar.subheader("Module / Attribute Authoring")',
            top_level,
        )
        for expected in (
            "render_module_attribute_apply_sidebar_section("
            "st.session_state.project)",
            'st.sidebar.subheader("Module / Attribute Analysis")',
            "render_module_attribute_table_section(st.session_state.project)",
            "render_module_inspector_edit_scope_section()",
        ):
            self.assertIn(expected, top_level)
        self.assertNotIn(
            "render_project_module_inspector_section(st.session_state.project)",
            top_level,
        )

        apply_section = self._function_source(
            "render_module_attribute_apply_sidebar_section"
        )
        for expected in (
            'st.sidebar.subheader("Module / Attribute Apply")',
            "Open Apply Workspace",
        ):
            self.assertIn(expected, apply_section)
        self.assertNotIn(
            "render_attribute_group_swap_section(project)",
            apply_section,
        )
        self.assertNotIn(
            "render_insert_saved_module_reference_section(project)",
            apply_section,
        )
        apply_workspace = self._function_source(
            "render_module_attribute_apply_workspace"
        )
        self.assertIn(
            "render_insert_saved_module_reference_section(project)",
            apply_workspace,
        )
        self.assertIn(
            "render_module_candidate_selection_section(project)",
            apply_workspace,
        )
        self.assertIn(
            "render_attribute_group_swap_section(project)",
            apply_workspace,
        )

        mixed_inspector = self._function_source(
            "render_module_inspector_edit_scope_section"
        )
        self.assertIn(
            '"Module Inspector / Active Edit Scope"',
            mixed_inspector,
        )
        rename_controls = self._function_source(
            "render_module_rename_controls"
        )
        for expected in (
            'key="_module_rename_new_name_widget"',
            'key="module_rename_preview_btn"',
            'key="module_rename_confirm_btn"',
            'key="module_rename_cancel_btn"',
        ):
            self.assertIn(expected, rename_controls)
        workspace = self._function_source(
            "render_module_attribute_authoring_workspace"
        )
        for renderer in (
            "render_module_inspector_edit_scope_section",
            "render_module_usage_inspection",
            "render_module_edit_scope_controls",
            "render_module_rename_controls",
        ):
            self.assertNotIn(renderer, workspace)
        self.assertIn(
            "render_module_rename_authoring_section(project)",
            workspace,
        )
        self.assertNotIn(
            "render_module_rename_controls(",
            mixed_inspector,
        )
        self.assertEqual(mixed_inspector.count('st.markdown("---")'), 1)

        contextual_start = self.app_source.index(
            'st.markdown("#### Module / Attribute Authoring")'
        )
        contextual = self.app_source[contextual_start:contextual_start + 1600]
        for expected in (
            "render_selected_token_attribute_labeler(",
            "render_selected_token_attribute_group_builder(",
            "render_selected_token_core_optional_selector(",
            "render_selected_token_batch_attribute_labeler(",
            "render_selected_token_module_builder(",
        ):
            self.assertIn(expected, contextual)

    def test_workspace_excludes_apply_swap_analysis_and_gallery_calls(self):
        workspace = self._function_source(
            "render_module_attribute_authoring_workspace"
        )
        for forbidden in (
            "render_insert_saved_module_reference_section",
            "render_module_candidate_selection_section",
            "render_attribute_group_swap_section",
            "render_module_swap_section",
            "render_module_attribute_table_section",
            "render_pro_gallery_mode",
        ):
            self.assertNotIn(forbidden, workspace)
        self.assertEqual(
            workspace.count(
                "render_project_module_inspector_section(project)"
            ),
            1,
        )
        for operation_key in (
            "attribute_group_swap_from",
            "attribute_group_swap_to",
            "attribute_group_swap_scope",
            "attribute_group_swap_selected_route_id",
            "attribute_group_swap_require_full_match",
            "attribute_group_swap_preview",
        ):
            self.assertNotIn(operation_key, workspace)

    def test_project_transition_cleanup_is_scoped_and_back_preserves_state(self):
        session_state = _SessionState(
            active_management_workspace="module_attribute_authoring",
            project=object(),
            gallery_main_mode_enabled=True,
            comfy_url="localhost:8188",
            global_module_manager_selected="global_character",
            global_module_manager_body_global_character="body",
            global_module_load_name="global_character",
            global_module_library_search_query="rainbow",
            _global_module_library_search_query_widget="rainbow",
            global_module_library_session_cache={
                "path": "fixture/global_modules.json",
                "library": {"global_character": {"body": "rainbow"}},
            },
            global_module_save_name="old_project_module",
            global_module_load_overwrite=True,
            blank_module_name="old draft",
            create_module_preview={"old": True},
            attribute_group_sidebar_selected="old_group",
            attribute_group_inspector_selected="old_group",
            attribute_group_negative_tags_old_group="old",
            module_rename_selected="pose",
            module_rename_new_name="new pose",
            module_rename_preview={"old_name": "pose", "new_name": "new pose"},
            _module_rename_selected_widget="pose",
            _module_rename_new_name_widget="new pose",
            selected_node_ids=["old-node"],
        )
        st = types.SimpleNamespace(session_state=session_state)
        namespace = self._load_functions(
            "reset_management_workspace_session_state",
            "reset_module_attribute_authoring_project_session_state",
            namespace={
                "st": st,
                "ACTIVE_MANAGEMENT_WORKSPACE_KEY": (
                    "active_management_workspace"
                ),
            },
        )

        namespace["reset_management_workspace_session_state"]()
        self.assertEqual(session_state.active_management_workspace, "")
        self.assertEqual(session_state.attribute_group_sidebar_selected, "old_group")
        self.assertEqual(session_state.module_rename_selected, "pose")
        self.assertEqual(session_state.module_rename_new_name, "new pose")
        self.assertIn("module_rename_preview", session_state)
        self.assertEqual(session_state.selected_node_ids, ["old-node"])

        namespace[
            "reset_module_attribute_authoring_project_session_state"
        ]()
        for removed in (
            "global_module_save_name",
            "global_module_load_overwrite",
            "blank_module_name",
            "create_module_preview",
            "attribute_group_sidebar_selected",
            "attribute_group_inspector_selected",
            "attribute_group_negative_tags_old_group",
            "module_rename_selected",
            "module_rename_new_name",
            "module_rename_preview",
            "_module_rename_selected_widget",
            "_module_rename_new_name_widget",
        ):
            self.assertNotIn(removed, session_state)
        for preserved in (
            "project",
            "gallery_main_mode_enabled",
            "comfy_url",
            "global_module_manager_selected",
            "global_module_manager_body_global_character",
            "global_module_load_name",
            "global_module_library_search_query",
            "_global_module_library_search_query_widget",
            "global_module_library_session_cache",
            "selected_node_ids",
        ):
            self.assertIn(preserved, session_state)

        loader = self._function_source("load_project_json_into_session")
        self.assertLess(
            loader.index("project = load_project_from_json(project_path)"),
            loader.index(
                "reset_module_attribute_authoring_project_session_state()"
            ),
        )
        self.assertLess(
            loader.index(
                "reset_module_attribute_authoring_project_session_state()"
            ),
            loader.index("st.session_state.project = project"),
        )
        new_project = self._function_source("set_new_workspace_project")
        self.assertIn(
            "reset_module_attribute_authoring_project_session_state()",
            new_project,
        )
        prompt_import = self._function_source("render_prompt_import_export_panel")
        self.assertEqual(
            prompt_import.count(
                "reset_module_attribute_authoring_project_session_state()"
            ),
            2,
        )
        self.assertIn("st.session_state.selected_node_ids = []", loader)
        self.assertIn("st.session_state.selected_node_ids = []", new_project)

    def test_unknown_module_metadata_survives_existing_authoring_update(self):
        existing = {
            "body": "old pose",
            "type": "generic",
            "category": "Other",
            "extension": {"owner": "plugin", "version": 3},
        }

        updated = update_module_entry_preserving_metadata(
            existing,
            "pose",
            "new pose",
            "generic",
            ["new pose"],
            1,
            "Other",
        )

        self.assertEqual(
            updated["extension"],
            {"owner": "plugin", "version": 3},
        )
        self.assertEqual(updated["body"], "new pose")

    def test_unknown_attribute_metadata_survives_existing_edits(self):
        project = Project(
            attribute_groups={
                "outfit": {
                    "name": "Outfit",
                    "slot": "outfit",
                    "tokens": ["dress"],
                    "created_from": "test",
                    "negative_tags": [],
                    "negative_when_disabled": [],
                    "negative_notes": "",
                    "extension": {"owner": "plugin", "version": 2},
                }
            }
        )

        renamed = rename_attribute_group(project, "outfit", "Wardrobe")
        self.assertEqual(renamed, "wardrobe")
        self.assertTrue(set_attribute_group_slot(project, renamed, "appearance"))
        self.assertTrue(
            set_attribute_group_negative_metadata(
                project,
                renamed,
                ["hat"],
                ["dress"],
                "metadata only",
            )
        )

        self.assertEqual(
            project.attribute_groups[renamed]["extension"],
            {"owner": "plugin", "version": 2},
        )

    def test_module_creation_and_negative_preview_do_not_rewrite_lines(self):
        line = PromptLine(
            id="line-1",
            original_file_name="fixture.txt",
            original_index=0,
            current_index=0,
            original_text="dress, smile",
            current_text="dress, smile",
            tokens=["dress", "smile"],
            negative_prompt="low quality",
        )
        project = Project(
            prompt_lines=[line],
            attribute_groups={
                "outfit": {
                    "name": "Outfit",
                    "slot": "outfit",
                    "tokens": ["dress"],
                    "created_from": "test",
                    "negative_tags": ["hat"],
                    "negative_when_disabled": ["dress"],
                    "negative_notes": "preview only",
                    "extension": {"keep": True},
                }
            },
        )
        line_before = copy.deepcopy(line)
        project_before_preview = copy.deepcopy(project)

        self.assertTrue(
            create_library_module(project, "pose", "standing", "generic")
        )
        self.assertEqual(line, line_before)

        preview_source = copy.deepcopy(project)
        preview = build_attribute_group_negative_preview(
            preview_source,
            "outfit",
            preview_source.prompt_lines[0],
        )
        self.assertEqual(preview_source, project)
        self.assertEqual(
            preview_source.prompt_lines[0].negative_prompt,
            "low quality",
        )
        self.assertIn("dress", preview["negative_when_disabled"])
        self.assertEqual(
            project_before_preview.prompt_lines[0].negative_prompt,
            project.prompt_lines[0].negative_prompt,
        )


if __name__ == "__main__":
    unittest.main()
