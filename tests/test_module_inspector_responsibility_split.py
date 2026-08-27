import ast
import unittest
from pathlib import Path


class ModuleInspectorResponsibilitySplitTests(unittest.TestCase):
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
        cls.outer_name = "render_module_inspector_edit_scope_section"
        cls.usage_name = "render_module_usage_inspection"
        cls.scope_name = "render_module_edit_scope_controls"
        cls.summary_name = "render_active_module_edit_scope_summary"
        cls.rename_name = "render_module_rename_controls"
        cls.rename_owner_name = "render_module_rename_authoring_section"
        cls.child_names = (
            cls.usage_name,
            cls.scope_name,
            cls.rename_name,
        )
        cls.outer = cls._source(cls.outer_name)
        cls.usage = cls._source(cls.usage_name)
        cls.scope = cls._source(cls.scope_name)
        cls.summary = cls._source(cls.summary_name)
        cls.rename = cls._source(cls.rename_name)
        cls.rename_owner = cls._source(cls.rename_owner_name)

    @classmethod
    def _source(cls, name):
        return ast.get_source_segment(
            cls.app_source,
            cls.functions[name],
        )

    @classmethod
    def _top_level_source(cls):
        start = cls.app_source.rindex("render_common_undo_sidebar_section()")
        return cls.app_source[start:]

    @staticmethod
    def _session_state_keys(nodes):
        direct_attributes = {
            node.attr
            for owner in nodes
            for node in ast.walk(owner)
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "st"
                and node.value.attr == "session_state"
                and node.attr not in {"get", "pop"}
            )
        }
        get_keys = {
            node.args[0].value
            for owner in nodes
            for node in ast.walk(owner)
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
        return direct_attributes | get_keys

    @staticmethod
    def _widget_keys(node):
        keys = []
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            for keyword in child.keywords:
                if (
                    keyword.arg == "key"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    keys.append(keyword.value.value)
        return keys

    def test_outer_and_three_responsibility_renderers_exist(self):
        for name in (self.outer_name, *self.child_names):
            self.assertIn(name, self.functions)

        self.assertEqual(
            [arg.arg for arg in self.functions[self.usage_name].args.args],
            ["selected_module", "selected_report"],
        )
        self.assertEqual(
            [arg.arg for arg in self.functions[self.scope_name].args.args],
            ["selected_module"],
        )
        self.assertEqual(
            [arg.arg for arg in self.functions[self.rename_name].args.args],
            ["selected_module", "module_names"],
        )

    def test_outer_owns_expander_project_report_selector_and_empty_states(self):
        for expected in (
            '"Module Inspector / Active Edit Scope"',
            "expanded=False",
            "if st.session_state.project:",
            "module_report = inspect_modules("
            "st.session_state.project, st.session_state.disabled_modules)",
            "module_names = sorted(module_report.keys())",
            "clear_module_edit_scope_if_missing(st.session_state.project)",
            "render_active_module_edit_scope_summary()",
            'st.selectbox("Module", module_names, '
            'key="module_inspector_selected")',
            "selected_report = module_report[selected_module]",
            "clear_module_edit_scope()",
            'st.info("No modules detected.")',
            'st.info("Load project first.")',
        ):
            self.assertIn(expected, self.outer)

        for child_source in (self.usage, self.scope, self.rename):
            self.assertNotIn("st.sidebar.expander", child_source)
            self.assertNotIn('key="module_inspector_selected"', child_source)

    def test_outer_retains_usage_and_scope_with_one_separator(self):
        calls = (
            "render_module_usage_inspection("
            "selected_module, selected_report)",
            "render_module_edit_scope_controls(selected_module)",
        )
        for call in calls:
            self.assertEqual(self.outer.count(call), 1)
        positions = [self.outer.index(call) for call in calls]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(self.outer.count('st.markdown("---")'), 1)
        separator = self.outer.index('st.markdown("---")')
        self.assertLess(positions[0], separator)
        self.assertLess(separator, positions[1])
        self.assertNotIn("render_module_rename_controls(", self.outer)

        self.assertEqual(
            self.rename_owner.count(
                "render_module_rename_controls(selected_module, module_names)"
            ),
            1,
        )

    def test_top_level_and_workspaces_call_only_outer_renderer(self):
        top_level = self._top_level_source()
        self.assertEqual(
            top_level.count(
                "render_module_inspector_edit_scope_section()"
            ),
            1,
        )
        for child_name in self.child_names:
            self.assertNotIn(f"{child_name}(", top_level)

        for function_name, function_node in self.functions.items():
            if "workspace" not in function_name:
                continue
            source = ast.get_source_segment(
                self.app_source,
                function_node,
            )
            for renderer_name in (self.outer_name, *self.child_names):
                self.assertNotIn(renderer_name, source)

    def test_widget_keys_have_exact_single_responsibility_ownership(self):
        expected_by_owner = {
            self.outer_name: ["module_inspector_selected"],
            self.usage_name: [],
            self.scope_name: [
                "module_scope_use_btn",
            ],
            self.summary_name: ["clear_active_module_edit_scope"],
            self.rename_name: [
                "_module_rename_new_name_widget",
                "module_rename_preview_btn",
                "module_rename_confirm_btn",
                "module_rename_cancel_btn",
            ],
            self.rename_owner_name: [
                "_module_rename_selected_widget",
            ],
        }
        all_expected = {
            key
            for keys in expected_by_owner.values()
            for key in keys
        }
        for owner, expected in expected_by_owner.items():
            actual = self._widget_keys(self.functions[owner])
            self.assertEqual(set(actual), set(expected))
            self.assertEqual(len(actual), len(expected))
        self.assertEqual(
            {
                key
                for owner in expected_by_owner
                for key in self._widget_keys(self.functions[owner])
            },
            all_expected,
        )
        for key in all_expected:
            self.assertEqual(self.app_source.count(f'key="{key}"'), 1)

    def test_no_new_session_state_key_is_introduced(self):
        nodes = [
            self.functions[name]
            for name in (
                self.outer_name,
                *self.child_names,
                self.summary_name,
                self.rename_owner_name,
                "initialize_module_rename_selection",
                "sync_module_rename_selected_widget",
                "initialize_module_rename_new_name_draft",
                "sync_module_rename_new_name_widget",
            )
        ]
        self.assertEqual(
            self._session_state_keys(nodes),
            {
                "project",
                "disabled_modules",
                "module_edit_scope_name",
                "module_rename_selected",
                "module_rename_new_name",
                "module_rename_preview",
                "focused_line_id",
                "_module_rename_new_name_widget",
                "_module_rename_selected_widget",
            },
        )

    def test_usage_child_is_read_only_and_preserves_inspection(self):
        for forbidden in (
            "st.session_state",
            "push_history(",
            "rename_module(",
            "save_",
            "st.rerun(",
            "clear_",
        ):
            self.assertNotIn(forbidden, self.usage)
        for expected in (
            'status = "Enabled" if selected_report["enabled"] '
            'else "Disabled"',
            '"Type: {selected_report.get(',
            '.metric("Illustrations", selected_report["line_count"])',
            '.metric("Occurrences", '
            'selected_report["occurrence_count"])',
            '.metric("Status", status)',
            'selected_report.get("library_body")',
            "affected_lines[:20]",
            '"Additional affected lines are hidden."',
            'line_info["inline_contents"] + '
            'line_info["range_contents"]',
            'line_info["malformed"]',
            '"Raw: ',
            '"Active: ',
        ):
            self.assertIn(expected, self.usage)

    def test_scope_child_preserves_gate_actions_metrics_and_limit(self):
        for expected in (
            'st.markdown("**Module Edit Scope**")',
            "if is_free():",
            '"Module Edit Scope is available in Pro."',
            'key="module_scope_use_btn"',
            "st.session_state.module_edit_scope_name = selected_module",
            "preview_module_scope(st.session_state.project, active_scope)",
            '.metric("Illustrations", scope_preview["affected_line_count"])',
            '.metric("Tokens", scope_preview["token_count"])',
            '.metric("Malformed", scope_preview["malformed_count"])',
            '.metric("Inline", scope_preview["inline_module_count"])',
            '.metric("Range tokens", '
            'scope_preview["range_token_count"])',
            'scope_preview["examples"][:10]',
            '"Malformed markers: ',
            '"Raw: ',
        ):
            self.assertIn(expected, self.scope)
        self.assertEqual(self.scope.count("st.rerun()"), 1)
        self.assertNotIn("clear_module_edit_scope()", self.scope)
        self.assertNotIn("module_scope_clear_btn", self.scope)
        self.assertNotIn("push_history(", self.scope)
        self.assertNotIn("rename_module(", self.scope)

    def test_rename_child_preserves_gates_stale_preview_and_validation(self):
        for expected in (
            "if is_free():",
            '"Module Rename is available in Pro."',
            "initialize_module_rename_new_name_draft()",
            'key="_module_rename_new_name_widget"',
            "on_change=sync_module_rename_new_name_widget",
            'st.session_state.get("module_rename_new_name", "")',
            'rename_preview_state.get("old_name") != selected_module',
            'rename_preview_state.get("new_name") != new_module_name',
            'any(ch in new_module_name for ch in '
            '("<", ">", ",", "\\n", "\\r"))',
            "name_exists = new_module_name in module_names "
            "and new_module_name != selected_module",
            '"Use a non-empty name without <, >, comma, or newline."',
            '"A module with that name already exists. '
            'Merge is not supported."',
            '"Choose a different module name."',
        ):
            self.assertIn(expected, self.rename)
        self.assertGreaterEqual(
            self.rename.count("clear_module_rename_preview()"),
            3,
        )

    def test_rename_preview_metrics_and_examples_are_preserved(self):
        for expected in (
            'key="module_rename_preview_btn"',
            "preview_rename_module(",
            "st.session_state.module_rename_preview = ",
            '.metric("Affected lines", '
            'rename_preview_state["affected_line_count"])',
            '.metric("Markers", '
            'rename_preview_state["marker_occurrence_count"])',
            '.metric("Inline", '
            'rename_preview_state["inline_occurrence_count"])',
            '.metric("Open", '
            'rename_preview_state["open_marker_count"])',
            '.metric("Close", '
            'rename_preview_state["close_marker_count"])',
            'rename_preview_state["malformed_marker_count"]',
            'for example in rename_preview_state["examples"]',
            '"Before: ',
            '"After: ',
        ):
            self.assertIn(expected, self.rename)

    def test_rename_confirm_sequence_and_migrations_are_preserved(self):
        confirm_start = self.rename.index(
            'if st.button("Confirm Rename Module", '
            'key="module_rename_confirm_btn"):'
        )
        cancel_start = self.rename.index(
            'if st.button("Cancel", key="module_rename_cancel_btn"):'
        )
        confirm = self.rename[confirm_start:cancel_start]
        ordered = (
            "current_modules = get_available_modules("
            "st.session_state.project)",
            'rename_preview_state.get("old_name") != selected_module',
            "new_module_name in current_modules "
            "and new_module_name != selected_module",
            "old_module_was_disabled = selected_module "
            "in st.session_state.disabled_modules",
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
        self.assertEqual(confirm.count("push_history()"), 1)
        self.assertEqual(confirm.count("rename_module("), 1)
        self.assertIn(
            "st.session_state.disabled_modules.discard(new_module_name)",
            confirm,
        )

    def test_cancel_remains_preview_only(self):
        cancel_start = self.rename.index(
            'if st.button("Cancel", key="module_rename_cancel_btn"):'
        )
        cancel = self.rename[cancel_start:]
        self.assertEqual(cancel.count("clear_module_rename_preview()"), 1)
        self.assertEqual(cancel.count("st.rerun()"), 1)
        for forbidden in (
            "rename_module(",
            "push_history(",
            "save_",
            "st.session_state.project =",
        ):
            self.assertNotIn(forbidden, cancel)

    def test_authoring_workspace_owns_rename_and_project_reset_is_scoped(self):
        workspace = self._source(
            "render_module_attribute_authoring_workspace"
        )
        for renderer_name in (
            self.outer_name,
            self.usage_name,
            self.scope_name,
            self.rename_name,
        ):
            self.assertNotIn(renderer_name, workspace)
        self.assertIn(
            "render_module_rename_authoring_section(project)",
            workspace,
        )

        reset = self._source(
            "reset_module_attribute_authoring_project_session_state"
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
