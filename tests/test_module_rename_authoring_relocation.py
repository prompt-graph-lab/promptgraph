import ast
import types
import unittest
from pathlib import Path


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class ModuleRenameAuthoringRelocationTests(unittest.TestCase):
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
        cls.workspace = cls._source("render_module_attribute_authoring_workspace")
        cls.wrapper = cls._source("render_module_rename_authoring_section")
        cls.controls = cls._source("render_module_rename_controls")
        cls.sidebar = cls._source("render_module_inspector_edit_scope_section")
        cls.usage = cls._source("render_module_usage_inspection")
        cls.scope = cls._source("render_module_edit_scope_controls")

    @classmethod
    def _source(cls, name):
        return ast.get_source_segment(cls.app_source, cls.functions[name])

    @classmethod
    def _load_functions(cls, *names, namespace):
        module = ast.Module(
            body=[cls.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

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

    def test_authoring_wrapper_exists_once_in_required_workspace_order(self):
        self.assertIn("render_module_rename_authoring_section", self.functions)
        rename_call = "render_module_rename_authoring_section(project)"
        self.assertEqual(self.workspace.count(rename_call), 1)
        ordered = (
            "render_create_module_from_scratch_section(project)",
            "render_project_module_inspector_section(project)",
            'st.markdown("#### Rename Module")',
            rename_call,
            "render_attribute_group_sidebar_manager(project)",
            "render_attribute_group_inspector_section(project)",
        )
        positions = [self.workspace.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_wrapper_owns_non_sidebar_expander_and_old_module_universe(self):
        self.assertIn(
            'with st.expander("Rename Module", expanded=False):',
            self.wrapper,
        )
        self.assertNotIn("st.sidebar", self.wrapper)
        self.assertIn(
            "module_report = inspect_modules(\n"
            "            project,\n"
            "            st.session_state.disabled_modules,\n"
            "        )",
            self.wrapper,
        )
        self.assertIn("module_names = sorted(module_report.keys())", self.wrapper)
        self.assertNotIn("get_project_module_library(", self.wrapper)
        self.assertNotIn("clear_module_edit_scope", self.wrapper)

    def test_wrapper_owns_dedicated_selector_and_controls_call(self):
        for expected in (
            "initialize_module_rename_selection(module_names)",
            'st.selectbox(\n            "Module",',
            'key="_module_rename_selected_widget"',
            "on_change=sync_module_rename_selected_widget",
            "st.session_state.module_rename_selected = selected_module",
            "render_module_rename_controls(selected_module, module_names)",
        ):
            self.assertIn(expected, self.wrapper)
        self.assertEqual(
            self._call_owners("render_module_rename_controls"),
            ["render_module_rename_authoring_section"],
        )

    def test_sidebar_retains_selector_usage_scope_and_one_separator_only(self):
        for expected in (
            '"Module Inspector / Active Edit Scope"',
            "expanded=False",
            "inspect_modules(st.session_state.project, "
            "st.session_state.disabled_modules)",
            'key="module_inspector_selected"',
            "render_module_usage_inspection(selected_module, selected_report)",
            "render_module_edit_scope_controls(selected_module)",
        ):
            self.assertIn(expected, self.sidebar)
        self.assertEqual(self.sidebar.count('st.markdown("---")'), 1)
        self.assertNotIn("render_module_rename_controls(", self.sidebar)
        self.assertNotIn("_module_rename_selected_widget", self.sidebar)
        self.assertEqual(
            self._call_owners("render_module_inspector_edit_scope_section"),
            [],
        )

    def test_visible_rename_widget_keys_have_one_application_owner(self):
        expected_keys = {
            "_module_rename_selected_widget": (
                "render_module_rename_authoring_section"
            ),
            "_module_rename_new_name_widget": "render_module_rename_controls",
            "module_rename_preview_btn": "render_module_rename_controls",
            "module_rename_confirm_btn": "render_module_rename_controls",
            "module_rename_cancel_btn": "render_module_rename_controls",
        }
        key_owners = {key: [] for key in expected_keys}
        for function_name, function_node in self.functions.items():
            for node in ast.walk(function_node):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if (
                        keyword.arg == "key"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value in key_owners
                    ):
                        key_owners[keyword.value.value].append(function_name)
        for key, expected_owner in expected_keys.items():
            self.assertEqual(key_owners[key], [expected_owner], key)

        all_widget_keys = {
            keyword.value.value
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if (
                keyword.arg == "key"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            )
        }
        for durable_key in (
            "module_rename_selected",
            "module_rename_new_name",
            "module_rename_preview",
        ):
            self.assertNotIn(durable_key, all_widget_keys)

    def test_hidden_widget_state_rehydrates_from_durable_state_after_back(self):
        session_state = _SessionState(
            active_management_workspace="module_attribute_authoring",
            module_rename_selected="pose",
            module_rename_new_name="new pose",
            module_rename_preview={
                "old_name": "pose",
                "new_name": "new pose",
            },
        )
        st = types.SimpleNamespace(session_state=session_state)
        namespace = self._load_functions(
            "reset_management_workspace_session_state",
            "initialize_module_rename_selection",
            "initialize_module_rename_new_name_draft",
            namespace={
                "st": st,
                "ACTIVE_MANAGEMENT_WORKSPACE_KEY": (
                    "active_management_workspace"
                ),
            },
        )

        namespace["reset_management_workspace_session_state"]()
        self.assertEqual(session_state.active_management_workspace, "")
        self.assertEqual(session_state.module_rename_selected, "pose")
        self.assertEqual(session_state.module_rename_new_name, "new pose")
        self.assertIn("module_rename_preview", session_state)

        self.assertEqual(
            namespace["initialize_module_rename_selection"](["pose", "style"]),
            "pose",
        )
        self.assertEqual(
            session_state._module_rename_selected_widget,
            "pose",
        )
        self.assertEqual(
            namespace["initialize_module_rename_new_name_draft"](),
            "new pose",
        )
        self.assertEqual(
            session_state._module_rename_new_name_widget,
            "new pose",
        )

    def test_selection_and_draft_callbacks_update_durable_state(self):
        session_state = _SessionState(
            _module_rename_selected_widget="style",
            _module_rename_new_name_widget="  renamed style  ",
        )
        st = types.SimpleNamespace(session_state=session_state)
        namespace = self._load_functions(
            "sync_module_rename_selected_widget",
            "sync_module_rename_new_name_widget",
            namespace={"st": st},
        )

        namespace["sync_module_rename_selected_widget"]()
        namespace["sync_module_rename_new_name_widget"]()

        self.assertEqual(session_state.module_rename_selected, "style")
        self.assertEqual(session_state.module_rename_new_name, "renamed style")

    def test_invalid_selection_repairs_without_project_mutation(self):
        project = object()
        session_state = _SessionState(
            project=project,
            module_rename_selected="missing",
            _module_rename_selected_widget="missing",
        )
        st = types.SimpleNamespace(session_state=session_state)
        namespace = self._load_functions(
            "initialize_module_rename_selection",
            namespace={"st": st},
        )

        selected = namespace["initialize_module_rename_selection"](
            ["pose", "style"]
        )

        self.assertEqual(selected, "pose")
        self.assertEqual(session_state.module_rename_selected, "pose")
        self.assertEqual(session_state._module_rename_selected_widget, "pose")
        self.assertIs(session_state.project, project)

        self.assertEqual(namespace["initialize_module_rename_selection"]([]), "")
        self.assertNotIn("module_rename_selected", session_state)
        self.assertNotIn("_module_rename_selected_widget", session_state)
        self.assertIs(session_state.project, project)

    def test_project_transition_cleanup_removes_only_rename_owned_state(self):
        session_state = _SessionState(
            module_rename_selected="pose",
            module_rename_new_name="new pose",
            module_rename_preview={"old_name": "pose"},
            _module_rename_selected_widget="pose",
            _module_rename_new_name_widget="new pose",
            module_inspector_selected="pose",
            module_edit_scope_name="pose",
            disabled_modules={"pose"},
            global_module_manager_selected="global-pose",
            gallery_main_mode_enabled=True,
        )
        st = types.SimpleNamespace(session_state=session_state)
        namespace = self._load_functions(
            "reset_module_attribute_authoring_project_session_state",
            namespace={"st": st},
        )

        namespace["reset_module_attribute_authoring_project_session_state"]()

        for removed in (
            "module_rename_selected",
            "module_rename_new_name",
            "module_rename_preview",
            "_module_rename_selected_widget",
            "_module_rename_new_name_widget",
        ):
            self.assertNotIn(removed, session_state)
        for preserved in (
            "module_inspector_selected",
            "module_edit_scope_name",
            "disabled_modules",
            "global_module_manager_selected",
            "gallery_main_mode_enabled",
        ):
            self.assertIn(preserved, session_state)

    def test_successful_project_transitions_use_cleanup_but_failures_do_not(self):
        loader = self._source("load_project_json_into_session")
        self.assertLess(
            loader.index('if not os.path.exists(project_path):'),
            loader.index("return False"),
        )
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

        new_project = self._source("set_new_workspace_project")
        self.assertEqual(
            new_project.count(
                "reset_module_attribute_authoring_project_session_state()"
            ),
            1,
        )
        prompt_import = self._source("render_prompt_import_export_panel")
        self.assertEqual(
            prompt_import.count(
                "reset_module_attribute_authoring_project_session_state()"
            ),
            2,
        )
        startup = self._source("auto_open_last_project_on_startup")
        self.assertIn("open_project=load_project_json_into_session", startup)
        duplicate = self._source("duplicate_current_project_directory")
        self.assertIn(
            "load_project_json_into_session(destination_project_path)",
            duplicate,
        )

    def test_no_project_and_no_module_states_remain_safe(self):
        guard = 'if not project:\n        st.info('
        self.assertIn(guard, self.workspace)
        self.assertIn(
            "Create or open a Project before editing Modules or "
            "Attribute Groups.",
            self.workspace,
        )
        self.assertIn('st.info("No modules detected.")', self.wrapper)
        no_modules = self.wrapper.index('st.info("No modules detected.")')
        self.assertLess(
            self.wrapper.index(
                "initialize_module_rename_selection(module_names)"
            ),
            no_modules,
        )
        self.assertNotIn("clear_module_edit_scope", self.wrapper)

    def test_free_gate_and_user_visible_rename_strings_are_preserved(self):
        self.assertIn("if is_free():", self.controls)
        self.assertIn(
            'st.caption("Module Rename is available in Pro.")',
            self.controls,
        )
        self.assertNotIn("Rename Module Preview", self.controls.split("else:", 1)[0])
        self.assertNotIn('st.markdown("**Rename Module**")', self.controls)

    def test_stale_preview_and_validation_rules_are_preserved(self):
        for expected in (
            'rename_preview_state.get("old_name") != selected_module',
            'rename_preview_state.get("new_name") != new_module_name',
            "clear_module_rename_preview()",
            '("<", ">", ",", "\\n", "\\r")',
            "new_module_name in module_names "
            "and new_module_name != selected_module",
            '"Use a non-empty name without <, >, comma, or newline."',
            '"A module with that name already exists. '
            'Merge is not supported."',
            '"Choose a different module name."',
        ):
            self.assertIn(expected, self.controls)

    def test_preview_metrics_examples_and_read_only_boundary_are_preserved(self):
        preview_start = self.controls.index(
            'if st.button("Rename Module Preview", '
            'key="module_rename_preview_btn"):'
        )
        confirm_start = self.controls.index(
            'if st.button("Confirm Rename Module", '
            'key="module_rename_confirm_btn"):'
        )
        preview = self.controls[preview_start:confirm_start]
        for expected in (
            "preview_rename_module(",
            "st.session_state.module_rename_preview = ",
            'rename_preview_state["affected_line_count"]',
            'rename_preview_state["marker_occurrence_count"]',
            'rename_preview_state["inline_occurrence_count"]',
            'rename_preview_state["open_marker_count"]',
            'rename_preview_state["close_marker_count"]',
            'rename_preview_state["malformed_marker_count"]',
            'rename_preview_state["examples"]',
            '"Before: ',
            '"After: ',
        ):
            self.assertIn(expected, preview)
        for forbidden in (
            "st.session_state.project = rename_module(",
            "push_history(",
            "save_project",
            "save_project_to_json",
        ):
            self.assertNotIn(forbidden, preview)

    def test_confirm_order_migrations_and_no_explicit_save_are_preserved(self):
        confirm_start = self.controls.index(
            'if st.button("Confirm Rename Module", '
            'key="module_rename_confirm_btn"):'
        )
        cancel_start = self.controls.index(
            'if st.button("Cancel", key="module_rename_cancel_btn"):'
        )
        confirm = self.controls[confirm_start:cancel_start]
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
            "st.session_state.module_rename_selected = new_module_name",
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
        for forbidden in (
            "save_project(",
            "save_project_to_json(",
            "autosave",
        ):
            self.assertNotIn(forbidden, confirm)

    def test_cancel_is_preview_only_and_preserves_durable_draft(self):
        cancel_start = self.controls.index(
            'if st.button("Cancel", key="module_rename_cancel_btn"):'
        )
        cancel = self.controls[cancel_start:]
        self.assertEqual(cancel.count("clear_module_rename_preview()"), 1)
        self.assertEqual(cancel.count("st.rerun()"), 1)
        for forbidden in (
            "rename_module(",
            "push_history(",
            "save_",
            "module_rename_new_name",
            "module_rename_selected",
        ):
            self.assertNotIn(forbidden, cancel)

    def test_usage_remains_read_only_and_edit_scope_remains_sidebar_owned(self):
        for forbidden in (
            "st.session_state",
            "push_history(",
            "rename_module(",
            "st.rerun(",
        ):
            self.assertNotIn(forbidden, self.usage)
        for expected in (
            'st.markdown("**Module Edit Scope**")',
            'key="module_scope_use_btn"',
            "preview_module_scope(st.session_state.project, active_scope)",
        ):
            self.assertIn(expected, self.scope)
        self.assertNotIn("module_scope_clear_btn", self.scope)
        self.assertEqual(
            self._call_owners("render_module_edit_scope_controls"),
            ["render_module_inspector_edit_scope_section"],
        )

    def test_workspace_description_states_the_remaining_sidebar_boundary(self):
        workspace_node = self.functions[
            "render_module_attribute_authoring_workspace"
        ]
        info_call = next(
            node
            for node in ast.walk(workspace_node)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "info"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            )
        )
        description = info_call.args[0].value
        self.assertIn(
            "Reusable Module and Attribute authoring and maintenance.",
            description,
        )
        self.assertIn("Project Module editing", description)
        self.assertIn("Module Attribute Table", description)
        self.assertIn(
            "Module usage inspection",
            description,
        )
        self.assertIn(
            "Active Edit Scope remain in Sidebar Analysis.",
            description,
        )
        self.assertNotIn(
            "Rename Module also remains in the Sidebar",
            self.workspace,
        )


if __name__ == "__main__":
    unittest.main()
