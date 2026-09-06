import ast
import copy
import unittest
from pathlib import Path

from core.operations import (
    MODULE_TYPES,
    get_module_body,
    get_module_core_tokens,
    get_module_min_match_tokens,
    get_module_type,
    get_project_module_library,
    validate_library_module_body,
)
from core.parser import parse_prompt
from core.project import Project
from tests.test_project_module_inspector_workspace_state import (
    _RenderStub,
    _SessionState,
)


class _AuthoringRenderStub(_RenderStub):
    def markdown(self, message):
        self.messages.append(("markdown", message))


class ProjectModuleEditorAuthoringRelocationTests(unittest.TestCase):
    helper_names = (
        "prepare_project_module_inspector_selection_widget_state",
        "sync_project_module_inspector_selection_widget_state",
        "prepare_project_module_inspector_body_widget_state",
        "sync_project_module_inspector_body_widget_state",
        "prepare_project_module_inspector_core_widget_state",
        "sync_project_module_inspector_core_widget_state",
        "prepare_project_module_inspector_type_widget_state",
        "sync_project_module_inspector_type_widget_state",
        "prepare_project_module_inspector_min_match_widget_state",
        "sync_project_module_inspector_min_match_widget_state",
    )

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

    def _source(self, name):
        return ast.get_source_segment(self.app_source, self.functions[name])

    def _load_functions(self, *names, namespace):
        module = ast.Module(
            body=[
                node for node in self.tree.body
                if isinstance(node, ast.ImportFrom)
                and node.module == "core.module_token_rules"
            ] + [self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def _top_level_source(self):
        start = self.app_source.rindex("render_common_undo_sidebar_section()")
        return self.app_source[start:]

    def _call_owners(self, called_name):
        owners = []
        for function_name, function_node in self.functions.items():
            for node in ast.walk(function_node):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == called_name
                ):
                    owners.append(function_name)
        return owners

    def _project(self):
        return Project(
            source_directory="fixture",
            module_library={
                "character": {
                    "body": "black hair, brown eyes",
                    "type": "character",
                    "core_tokens": ["black hair"],
                    "min_match_tokens": 1,
                },
                "pose": {
                    "body": "standing, smiling",
                    "type": "generic",
                    "core_tokens": ["standing"],
                    "min_match_tokens": 1,
                },
            },
        )

    def _runtime_namespace(self, st, calls):
        def render_token_inspector(
            project,
            namespace,
            module_name,
            body_key,
            core_key,
        ):
            calls.append(
                (
                    "editor",
                    project,
                    namespace,
                    module_name,
                    body_key,
                    core_key,
                )
            )

        namespace = {
            "st": st,
            "ACTIVE_MANAGEMENT_WORKSPACE_KEY": (
                "active_management_workspace"
            ),
            "profiled_render": lambda label: lambda function: function,
            "parse_prompt": parse_prompt,
            "MODULE_TYPES": MODULE_TYPES,
            "get_project_module_library": get_project_module_library,
            "get_module_body": get_module_body,
            "get_module_core_tokens": get_module_core_tokens,
            "get_module_type": get_module_type,
            "get_module_min_match_tokens": get_module_min_match_tokens,
            "validate_library_module_body": validate_library_module_body,
            "is_free": lambda: False,
            "render_module_token_inspector": render_token_inspector,
            "push_history": lambda: calls.append(("history",)),
            "set_module_entry": lambda *args: calls.append(("save", *args)),
            "build_graph": lambda project: calls.append(("build",)) or project,
            "restore_focus_after_graph_update": (
                lambda focus: calls.append(("restore", focus))
            ),
            "sync_text_areas": lambda: calls.append(("sync",)),
            "render_create_module_from_scratch_section": (
                lambda project: calls.append(("create", project))
            ),
            "render_module_rename_authoring_section": (
                lambda project: calls.append(("rename", project))
            ),
            "render_attribute_group_sidebar_manager": (
                lambda project: calls.append(("groups", project))
            ),
            "render_attribute_group_inspector_section": (
                lambda project: calls.append(("group-inspector", project))
            ),
        }
        return self._load_functions(
            *self.helper_names,
            "reset_management_workspace_session_state",
            "render_project_module_inspector_section",
            "render_module_attribute_authoring_workspace",
            namespace=namespace,
        )

    def test_editor_has_one_authoring_owner_and_main_area_label(self):
        renderer = self._source("render_project_module_inspector_section")
        self.assertIn(
            'with st.expander("Project Module Editor", expanded=False):',
            renderer,
        )
        self.assertNotIn("st.sidebar", renderer)
        self.assertNotIn('st.markdown("#### Project Module Editor")', self._source(
            "render_module_attribute_authoring_workspace"
        ))
        self.assertEqual(
            self._call_owners("render_project_module_inspector_section"),
            ["render_module_attribute_authoring_workspace"],
        )

        executable_calls = [
            node
            for node in ast.walk(self.tree)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "render_project_module_inspector_section"
            )
        ]
        self.assertEqual(len(executable_calls), 1)

    def test_authoring_order_and_sidebar_analysis_ownership(self):
        workspace_node = self.functions[
            "render_module_attribute_authoring_workspace"
        ]
        expected = (
            "render_create_module_from_scratch_section",
            "render_project_module_inspector_section",
            "render_module_rename_authoring_section",
            "render_attribute_group_sidebar_manager",
            "render_attribute_group_inspector_section",
        )
        calls = sorted(
            (
                node.lineno,
                node.func.id,
            )
            for node in ast.walk(workspace_node)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in expected
            )
        )
        self.assertEqual(tuple(name for _, name in calls), expected)

        top_level = self._top_level_source()
        table_call = (
            "render_module_attribute_table_section("
            "st.session_state.project)"
        )
        scope_call = "render_module_inspector_edit_scope_section()"
        self.assertIn(table_call, top_level)
        self.assertIn(scope_call, top_level)
        self.assertLess(top_level.index(table_call), top_level.index(scope_call))
        self.assertNotIn(
            "render_project_module_inspector_section("
            "st.session_state.project)",
            top_level,
        )

        table = self._source("render_module_attribute_table_section")
        scope = self._source("render_module_inspector_edit_scope_section")
        self.assertIn("st.sidebar.expander", table)
        self.assertIn('"Module Inspector / Active Edit Scope"', scope)

    def test_apply_and_gallery_owners_remain_separate(self):
        apply_workspace = self._source(
            "render_module_attribute_apply_workspace"
        )
        expected = (
            "render_module_toggle_controls(project)",
            "render_insert_saved_module_reference_section(project)",
            "render_module_candidate_selection_section(project)",
            "render_attribute_group_swap_section(project)",
        )
        positions = [apply_workspace.index(call) for call in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn(
            "render_project_module_inspector_section",
            apply_workspace,
        )
        for owner in (
            "render_module_attribute_apply_sidebar_section",
            "render_gallery_operations_workflow",
            "render_project_management_workspace",
        ):
            if owner in self.functions:
                self.assertNotIn(
                    "render_project_module_inspector_section",
                    self._source(owner),
                )

    def test_back_reopen_reconstructs_drafts_in_real_authoring_renderer(self):
        project = self._project()
        get_project_module_library(project)
        before = copy.deepcopy(project)
        state = _SessionState(
            project=project,
            edition="PRO",
            active_management_workspace="module_attribute_authoring",
            project_module_inspector_name="character",
            project_module_inspector_body_character=(
                "rainbow hair, blue eyes, smiling"
            ),
            project_module_inspector_core_character=(
                "rainbow hair\nblue eyes"
            ),
            project_module_inspector_type_character="style",
            project_module_inspector_min_match_character=2,
        )
        calls = []
        st = _AuthoringRenderStub(state)
        namespace = self._runtime_namespace(st, calls)

        namespace["render_module_attribute_authoring_workspace"]()
        first_operation_names = [call[0] for call in calls]
        self.assertEqual(
            first_operation_names,
            ["create", "editor", "rename", "groups", "group-inspector"],
        )

        for key in (
            "_project_module_inspector_name_widget",
            "_project_module_inspector_body_widget_character",
            "_project_module_inspector_core_widget_character",
            "_project_module_inspector_type_widget_character",
            "_project_module_inspector_min_match_widget_character",
        ):
            state.pop(key, None)

        namespace["reset_management_workspace_session_state"]()
        self.assertEqual(state.active_management_workspace, "")
        self.assertEqual(
            state.project_module_inspector_body_character,
            "rainbow hair, blue eyes, smiling",
        )
        self.assertEqual(
            state.project_module_inspector_core_character,
            "rainbow hair\nblue eyes",
        )
        self.assertEqual(state.project_module_inspector_type_character, "style")
        self.assertEqual(state.project_module_inspector_min_match_character, 2)

        state.active_management_workspace = "module_attribute_authoring"
        calls.clear()
        namespace["render_module_attribute_authoring_workspace"]()

        self.assertEqual(
            state._project_module_inspector_name_widget,
            "character",
        )
        self.assertEqual(
            state._project_module_inspector_body_widget_character,
            "rainbow hair, blue eyes, smiling",
        )
        self.assertEqual(
            state._project_module_inspector_core_widget_character,
            "rainbow hair\nblue eyes",
        )
        self.assertEqual(
            state._project_module_inspector_type_widget_character,
            "style",
        )
        self.assertEqual(
            state._project_module_inspector_min_match_widget_character,
            2,
        )
        self.assertEqual(project, before)
        self.assertNotIn(("history",), calls)
        self.assertFalse(any(call[0] == "save" for call in calls))
        self.assertFalse(any(call[0] == "build" for call in calls))
        self.assertEqual(st.rerun_count, 0)
        self.assertNotIn("autosave_feedback", state)

    def test_free_and_empty_module_messages_are_preserved(self):
        renderer = self._source("render_project_module_inspector_section")
        self.assertIn(
            'st.info("Project Module Inspector is available in Pro.")',
            renderer,
        )
        self.assertIn(
            'st.info("Create or load a project module before editing it.")',
            renderer,
        )
        self.assertLess(
            renderer.index("if is_free():"),
            renderer.index("get_project_module_library(project)"),
        )


if __name__ == "__main__":
    unittest.main()
