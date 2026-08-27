import ast
import unittest
from pathlib import Path


class ModuleInspectorEditScopeExtractionTests(unittest.TestCase):
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
        cls.renderer_name = "render_module_inspector_edit_scope_section"
        cls.renderer_node = cls.functions[cls.renderer_name]
        cls.renderer_source = ast.get_source_segment(
            cls.app_source,
            cls.renderer_node,
        )
        cls.child_names = (
            "render_module_usage_inspection",
            "render_module_edit_scope_controls",
            "render_module_rename_controls",
        )
        cls.summary_name = "render_active_module_edit_scope_summary"
        cls.rename_owner_name = "render_module_rename_authoring_section"
        cls.panel_nodes = [
            cls.renderer_node,
            *(cls.functions[name] for name in cls.child_names),
            cls.functions[cls.summary_name],
            cls.functions[cls.rename_owner_name],
        ]
        cls.panel_source = "\n".join(
            ast.get_source_segment(cls.app_source, node)
            for node in cls.panel_nodes
        )

    def _function_source(self, name):
        return ast.get_source_segment(self.app_source, self.functions[name])

    def _top_level_source(self):
        start = self.app_source.rindex("render_common_undo_sidebar_section()")
        return self.app_source[start:]

    def test_named_renderer_owns_the_active_scope_sidebar_expander(self):
        self.assertIn(self.renderer_name, self.functions)
        self.assertIn(
            '"Module Inspector / Active Edit Scope"',
            self.renderer_source,
        )
        self.assertEqual(self.renderer_source.count("expanded=False"), 1)

        top_level_with_labels = []
        for node in self.tree.body:
            if not isinstance(node, ast.With):
                continue
            for item in node.items:
                call = item.context_expr
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "expander"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                ):
                    top_level_with_labels.append(call.args[0].value)
        self.assertNotIn(
            "Module Inspector / Active Edit Scope",
            top_level_with_labels,
        )

    def test_top_level_calls_renderer_once_in_unchanged_sidebar_order(self):
        top_level = self._top_level_source()
        call = "render_module_inspector_edit_scope_section()"
        self.assertEqual(top_level.count(call), 1)
        self.assertLess(
            top_level.index(
                "render_module_attribute_table_section("
                "st.session_state.project)"
            ),
            top_level.index(call),
        )
        self.assertLess(
            top_level.index(call),
            top_level.index("render_comfyui_daily_sidebar_section()"),
        )
        self.assertNotIn(
            "render_project_module_inspector_section("
            "st.session_state.project)",
            top_level,
        )

    def test_renderer_is_not_called_from_any_other_renderer(self):
        owners = []
        for function_name, function_node in self.functions.items():
            for node in ast.walk(function_node):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == self.renderer_name
                ):
                    owners.append(function_name)
        self.assertEqual(owners, [])

        for excluded_owner in (
            "render_module_attribute_authoring_workspace",
            "render_project_management_workspace",
            "render_comfyui_settings_workspace",
            "render_gallery_operations_workflow",
        ):
            if excluded_owner in self.functions:
                self.assertNotIn(
                    self.renderer_name,
                    self._function_source(excluded_owner),
                )

    def test_relocated_widget_keys_are_unique_and_action_keys_unchanged(self):
        widget_keys = (
            "module_inspector_selected",
            "module_scope_use_btn",
            "clear_active_module_edit_scope",
            "_module_rename_selected_widget",
            "_module_rename_new_name_widget",
            "module_rename_preview_btn",
            "module_rename_confirm_btn",
            "module_rename_cancel_btn",
        )
        for key in widget_keys:
            with self.subTest(key=key):
                self.assertIn(f'key="{key}"', self.panel_source)
                self.assertEqual(self.app_source.count(f'key="{key}"'), 1)

    def test_existing_helpers_and_display_limits_are_preserved(self):
        for expected in (
            "inspect_modules(",
            "clear_module_edit_scope_if_missing(",
            "preview_module_scope(",
            "preview_rename_module(",
            "rename_module(",
            "clear_module_rename_preview()",
        ):
            self.assertIn(expected, self.panel_source)
        self.assertIn("affected_lines[:20]", self.panel_source)
        self.assertIn(
            'st.caption("Additional affected lines are hidden.")',
            self.panel_source,
        )
        self.assertIn(
            'scope_preview["examples"][:10]',
            self.panel_source,
        )

    def test_free_no_project_and_no_module_states_are_preserved(self):
        self.assertEqual(self.panel_source.count("if is_free():"), 2)
        self.assertIn(
            'st.caption("Module Edit Scope is available in Pro.")',
            self.panel_source,
        )
        self.assertIn(
            'st.caption("Module Rename is available in Pro.")',
            self.panel_source,
        )
        self.assertIn('st.info("Load project first.")', self.renderer_source)

        no_modules = self.renderer_source.index(
            'st.info("No modules detected.")'
        )
        clear_scope = self.renderer_source.rfind(
            "clear_module_edit_scope()",
            0,
            no_modules,
        )
        self.assertGreaterEqual(clear_scope, 0)
        self.assertLess(clear_scope, no_modules)

    def test_session_state_keys_are_unchanged_and_no_new_key_is_added(self):
        direct_attributes = {
            node.attr
            for panel_node in self.panel_nodes
            for node in ast.walk(panel_node)
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "st"
                and node.value.attr == "session_state"
                and node.attr != "get"
            )
        }
        get_keys = {
            node.args[0].value
            for panel_node in self.panel_nodes
            for node in ast.walk(panel_node)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "st"
                and node.func.value.attr == "session_state"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            )
        }
        self.assertEqual(
            direct_attributes | get_keys,
            {
            "project",
            "disabled_modules",
            "module_edit_scope_name",
            "module_rename_selected",
            "module_rename_new_name",
            "module_rename_preview",
            "focused_line_id",
        },
        )

    def test_stale_preview_and_collision_guards_are_preserved(self):
        old_name_guard = (
            'rename_preview_state.get("old_name") != selected_module'
        )
        new_name_guard = (
            'rename_preview_state.get("new_name") != new_module_name'
        )
        rename_source = self._function_source(
            "render_module_rename_controls"
        )
        self.assertIn(old_name_guard, rename_source)
        self.assertIn(new_name_guard, rename_source)
        self.assertLess(
            rename_source.index(old_name_guard),
            rename_source.index(new_name_guard),
        )
        self.assertIn(
            "name_exists = new_module_name in module_names "
            "and new_module_name != selected_module",
            rename_source,
        )
        self.assertEqual(
            rename_source.count(
                "A module with that name already exists. "
                "Merge is not supported."
            ),
            3,
        )

    def test_confirm_sequence_and_migrations_are_preserved(self):
        rename_source = self._function_source(
            "render_module_rename_controls"
        )
        confirm_start = rename_source.index(
            'if st.button("Confirm Rename Module", '
            'key="module_rename_confirm_btn"):'
        )
        cancel_start = rename_source.index(
            'if st.button("Cancel", key="module_rename_cancel_btn"):'
        )
        confirm = rename_source[confirm_start:cancel_start]

        self.assertEqual(confirm.count("push_history()"), 1)
        self.assertEqual(confirm.count("rename_module("), 1)
        ordered = (
            "old_module_was_disabled = "
            "selected_module in st.session_state.disabled_modules",
            "push_history()",
            'prev_focus = st.session_state.get("focused_line_id")',
            "st.session_state.project = rename_module(",
            'st.session_state.get("module_edit_scope_name") '
            "== selected_module",
            "st.session_state.module_edit_scope_name = new_module_name",
            "st.session_state.disabled_modules.discard(selected_module)",
            "st.session_state.disabled_modules.add(new_module_name)",
            "restore_focus_after_graph_update(prev_focus)",
            "sync_text_areas()",
            "clear_module_rename_preview()",
            "st.rerun()",
        )
        positions = [confirm.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            "st.session_state.disabled_modules.discard(new_module_name)",
            confirm,
        )

    def test_cancel_clears_only_preview_and_reruns(self):
        rename_source = self._function_source(
            "render_module_rename_controls"
        )
        cancel_start = rename_source.index(
            'if st.button("Cancel", key="module_rename_cancel_btn"):'
        )
        cancel = rename_source[cancel_start:]
        self.assertEqual(cancel.count("clear_module_rename_preview()"), 1)
        self.assertEqual(cancel.count("st.rerun()"), 1)
        self.assertNotIn("rename_module(", cancel)
        self.assertNotIn("push_history()", cancel)

    def test_workspace_relocation_and_transition_cleanup_are_explicit(self):
        workspace = self._function_source(
            "render_module_attribute_authoring_workspace"
        )
        reset = self._function_source(
            "reset_module_attribute_authoring_project_session_state"
        )
        self.assertNotIn(self.renderer_name, workspace)
        for child_name in (
            "render_module_usage_inspection",
            "render_module_edit_scope_controls",
            "render_module_rename_controls",
        ):
            self.assertNotIn(child_name, workspace)
        self.assertIn(
            "render_module_rename_authoring_section(project)",
            workspace,
        )
        for key in (
            "module_rename_selected",
            "module_rename_new_name",
            "module_rename_preview",
            "_module_rename_selected_widget",
            "_module_rename_new_name_widget",
        ):
            self.assertIn(f'"{key}"', reset)
        for key in (
            "module_edit_scope_name",
            "disabled_modules",
            "focused_line_id",
            "selected_node_ids",
        ):
            self.assertNotIn(key, reset)


if __name__ == "__main__":
    unittest.main()
