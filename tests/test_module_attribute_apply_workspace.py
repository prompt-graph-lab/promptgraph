import ast
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


class _Expander:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _Sidebar:
    def __init__(self, events, click=False):
        self.events = events
        self.click = click

    def subheader(self, message):
        self.events.append(("subheader", message))

    def caption(self, message):
        self.events.append(("sidebar_caption", message))

    def button(
        self,
        label,
        *,
        key,
        width="content",
        disabled=False,
    ):
        self.events.append(
            (
                "button",
                label,
                key,
                width,
                disabled,
            )
        )
        return self.click and not disabled


class _StreamlitStub:
    def __init__(
        self,
        *,
        project=None,
        disabled_modules=(),
        checkbox_values=None,
        sidebar_click=False,
    ):
        self.session_state = _SessionState(
            project=project,
            disabled_modules=set(disabled_modules),
        )
        self.events = []
        self.sidebar = _Sidebar(self.events, sidebar_click)
        self.checkbox_values = dict(checkbox_values or {})
        self.rerun_count = 0

    def info(self, message):
        self.events.append(("info", message))

    def caption(self, message):
        self.events.append(("caption", message))

    def expander(self, label, expanded=False):
        self.events.append(("expander", label, expanded))
        return _Expander()

    def checkbox(self, label, value, key):
        self.events.append(("checkbox", label, value, key))
        return self.checkbox_values.get(key, value)

    def rerun(self):
        self.rerun_count += 1


class ModuleAttributeApplyWorkspaceTests(unittest.TestCase):
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
        cls.target = "module_attribute_apply"
        cls.sidebar_name = "render_module_attribute_apply_sidebar_section"
        cls.workspace_name = "render_module_attribute_apply_workspace"
        cls.toggle_name = "render_module_toggle_controls"
        cls.insert_name = "render_insert_saved_module_reference_section"
        cls.candidate_name = "render_module_candidate_selection_section"
        cls.swap_name = "render_attribute_group_swap_section"

    def _function_source(self, name):
        return ast.get_source_segment(
            self.app_source,
            self.functions[name],
        )

    def _load_functions(self, *names, namespace):
        module = ast.Module(
            body=[self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def _call_owners(self, callee):
        owners = []
        for name, function in self.functions.items():
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == callee
                for node in ast.walk(function)
            ):
                owners.append(name)
        return owners

    def test_target_is_registered_once_with_expected_metadata(self):
        target_block = self.app_source.split(
            "MANAGEMENT_WORKSPACE_TARGETS = {",
            maxsplit=1,
        )[1].split("_APP_RERUN_STARTED_AT", maxsplit=1)[0]
        self.assertEqual(
            target_block.count(f'"{self.target}": {{'),
            1,
        )
        self.assertIn('"title": "Module / Attribute Apply"', target_block)
        for planned_area in (
            "Module Toggles",
            "Saved Module reference insertion",
            "Module Candidate Selection",
            "Attribute Group Swap",
            "Apply scope and contextual inspection",
        ):
            self.assertIn(f'"{planned_area}"', target_block)
        self.assertIn(
            "Module Toggles, Saved Module Reference Insertion, Module ",
            target_block,
        )
        self.assertIn(
            "Candidate Selection, and Attribute Group Swap are in the Apply ",
            target_block,
        )
        self.assertIn(
            "workspace. Module Edit Scope remains in Sidebar Analysis because ",
            target_block,
        )
        self.assertIn(
            "it is persistent editing context used by daily editing surfaces.",
            target_block,
        )
        self.assertIn(
            "Broader contextual Apply inspection remains future work.",
            target_block,
        )
        self.assertNotIn("Swap remains in the Sidebar", target_block)
        self.assertNotIn("requires its own durability audit", target_block)

    def test_normalization_and_shell_route_accept_apply_target_once(self):
        normalize = self._function_source(
            "normalize_management_workspace_target"
        )
        self.assertIn(
            "if clean_target in MANAGEMENT_WORKSPACE_TARGETS:",
            normalize,
        )
        shell = self._function_source(
            "render_management_workspace_shell"
        )
        self.assertEqual(
            shell.count(f'if target == "{self.target}":'),
            1,
        )
        self.assertEqual(
            shell.count(f"{self.workspace_name}()"),
            1,
        )
        self.assertEqual(
            shell.count('key="close_active_management_workspace"'),
            1,
        )
        self.assertEqual(
            shell.count("reset_management_workspace_session_state()"),
            1,
        )

    def test_general_workspace_launchers_remain_management_only(self):
        launchers = self._function_source(
            "render_management_workspace_launchers"
        )
        expected = (
            (
                "Project Management",
                "project_management",
                "open_project_management_workspace",
            ),
            (
                "Module / Attribute Authoring",
                "module_attribute_authoring",
                "open_module_attribute_authoring_workspace",
            ),
            (
                "ComfyUI Settings",
                "comfyui_settings",
                "open_comfyui_settings_workspace",
            ),
        )
        for label, target, key in expected:
            self.assertEqual(launchers.count(f'"{label}"'), 1)
            self.assertEqual(launchers.count(f'"{target}"'), 1)
            self.assertEqual(launchers.count(f'"{key}"'), 1)
        self.assertNotIn(self.target, launchers)
        self.assertNotIn("Open Apply Workspace", launchers)

    def test_sidebar_owns_only_the_apply_launcher(self):
        sidebar = self._function_source(self.sidebar_name)
        swap_renderer = self._function_source(
            "render_attribute_group_swap_section"
        )
        self.assertEqual(
            self.app_source.count(
                'key="open_module_attribute_apply_workspace"'
            ),
            1,
        )
        for expected in (
            '"Open Apply Workspace"',
            'key="open_module_attribute_apply_workspace"',
            'width="stretch"',
            "disabled=not bool(project)",
            f'open_management_workspace("{self.target}")',
            "st.rerun()",
            "Module Toggles, Saved Module Reference Insertion, and Module ",
            "Candidate Selection, and Attribute Group Swap are managed in the ",
            "Apply workspace.",
        ):
            self.assertIn(expected, sidebar)
        self.assertNotIn("mod_toggle_", sidebar)
        self.assertNotIn("disabled_modules", sidebar)
        self.assertNotIn('expander("Module Toggles"', sidebar)
        self.assertNotIn(self.insert_name, sidebar)
        self.assertNotIn(self.candidate_name, sidebar)
        self.assertNotIn(self.swap_name, sidebar)
        self.assertNotIn("Attribute Group Swap render", sidebar)
        self.assertIn(
            'with st.expander("Attribute Group Swap", '
            "expanded=False):",
            swap_renderer,
        )
        self.assertNotIn("st.sidebar", swap_renderer)

    def test_sidebar_launcher_disables_without_project_and_opens_with_project(self):
        for project, click, expected_disabled, expected_open in (
            (None, True, True, []),
            (object(), True, False, [self.target]),
        ):
            with self.subTest(project=project):
                st = _StreamlitStub(
                    project=project,
                    sidebar_click=click,
                )
                opened = []
                child_calls = []
                namespace = self._load_functions(
                    self.sidebar_name,
                    namespace={
                        "st": st,
                        "open_management_workspace": opened.append,
                    },
                )

                namespace[self.sidebar_name](project)

                button = next(
                    event for event in st.events if event[0] == "button"
                )
                self.assertEqual(button[1], "Open Apply Workspace")
                self.assertEqual(
                    button[2],
                    "open_module_attribute_apply_workspace",
                )
                self.assertEqual(button[3], "stretch")
                self.assertEqual(button[4], expected_disabled)
                self.assertEqual(opened, expected_open)
                self.assertEqual(
                    st.rerun_count,
                    1 if expected_open else 0,
                )
                self.assertEqual(
                    child_calls,
                    [],
                )

    def test_workspace_exclusively_owns_four_apply_operations_in_order(self):
        workspace = self._function_source(self.workspace_name)
        toggle = self._function_source(self.toggle_name)
        self.assertEqual(
            self._call_owners(self.toggle_name),
            [self.workspace_name],
        )
        self.assertEqual(
            self._call_owners(self.insert_name),
            [self.workspace_name],
        )
        self.assertEqual(
            self._call_owners(self.candidate_name),
            [self.workspace_name],
        )
        self.assertEqual(
            self._call_owners(self.swap_name),
            [self.workspace_name],
        )
        self.assertIn(
            'project = st.session_state.get("project")',
            workspace,
        )
        children = (
            "render_module_toggle_controls(project)",
            "render_insert_saved_module_reference_section(project)",
            "render_module_candidate_selection_section(project)",
            "render_attribute_group_swap_section(project)",
        )
        positions = [workspace.index(child) for child in children]
        self.assertEqual(positions, sorted(positions))
        for child in children:
            self.assertEqual(workspace.count(child), 1)
        self.assertNotIn("render_module_edit_scope_controls", workspace)
        self.assertNotIn("render_module_usage_inspection", workspace)
        self.assertIn(
            'with st.expander("Module Toggles", expanded=False):',
            toggle,
        )
        self.assertNotIn("st.sidebar", toggle)
        self.assertEqual(
            self.app_source.count('key=f"mod_toggle_{mod_id}"'),
            1,
        )

        project = object()
        st = _StreamlitStub(project=project)
        child_calls = []
        namespace = self._load_functions(
            self.workspace_name,
            namespace={
                "st": st,
                self.toggle_name: lambda value: child_calls.append(
                    ("toggle", value)
                ),
                self.insert_name: lambda value: child_calls.append(
                    ("insert", value)
                ),
                self.candidate_name: lambda value: child_calls.append(
                    ("candidate", value)
                ),
                self.swap_name: lambda value: child_calls.append(
                    ("swap", value)
                ),
            },
        )
        namespace[self.workspace_name]()
        self.assertEqual(
            child_calls,
            [
                ("toggle", project),
                ("insert", project),
                ("candidate", project),
                ("swap", project),
            ],
        )

    def test_toggle_behavior_rehydrates_from_disabled_modules(self):
        project = object()
        st = _StreamlitStub(
            project=project,
            disabled_modules={"outfit"},
            checkbox_values={
                "mod_toggle_pose": False,
                "mod_toggle_outfit": True,
            },
        )
        namespace = self._load_functions(
            self.toggle_name,
            namespace={
                "st": st,
                "get_available_modules": (
                    lambda value: ["pose", "outfit"]
                ),
            },
        )

        namespace[self.toggle_name](project)

        self.assertEqual(
            [event for event in st.events if event[0] == "checkbox"],
            [
                ("checkbox", "Module pose", True, "mod_toggle_pose"),
                (
                    "checkbox",
                    "Module outfit",
                    False,
                    "mod_toggle_outfit",
                ),
            ],
        )
        self.assertEqual(st.session_state.disabled_modules, {"pose"})
        self.assertEqual(st.rerun_count, 2)

    def test_toggle_messages_and_mutation_boundary_are_preserved(self):
        toggle = self._function_source(self.toggle_name)
        for expected in (
            "available_modules = get_available_modules(project)",
            "for mod_id in available_modules:",
            "mod_id not in st.session_state.disabled_modules",
            'f"Module {mod_id}"',
            'key=f"mod_toggle_{mod_id}"',
            "st.session_state.disabled_modules.discard(mod_id)",
            "st.session_state.disabled_modules.add(mod_id)",
            "if new_val != current_val:",
            "st.rerun()",
            'st.info("Load project first.")',
            'st.info("No modules detected.")',
        ):
            self.assertIn(expected, toggle)
        for forbidden in (
            "push_history(",
            "st.session_state.project =",
            "save_project",
            "save_settings",
            "autosave",
        ):
            self.assertNotIn(forbidden, toggle)

    def test_back_preserves_production_and_toggle_state(self):
        session_state = _SessionState(
            active_management_workspace=self.target,
            disabled_modules={"pose"},
            gallery_main_mode_enabled=True,
            trash_view_mode_enabled=False,
            focused_line_id="line-1",
            highlighted_line_id="line-2",
            selected_node_ids=["node-1"],
            gallery_selected_route_ids=["route-1"],
            gallery_operation_focus="module_swap",
            module_edit_scope_name="pose",
            history=[{"before": True}],
            project=object(),
            current_project_path="project.json",
        )
        namespace = self._load_functions(
            "reset_management_workspace_session_state",
            namespace={
                "st": type("St", (), {"session_state": session_state})(),
                "ACTIVE_MANAGEMENT_WORKSPACE_KEY": (
                    "active_management_workspace"
                ),
            },
        )
        before = {
            key: value
            for key, value in session_state.items()
            if key != "active_management_workspace"
        }

        namespace["reset_management_workspace_session_state"]()

        self.assertEqual(session_state.active_management_workspace, "")
        self.assertEqual(
            {
                key: value
                for key, value in session_state.items()
                if key != "active_management_workspace"
            },
            before,
        )

    def test_project_transition_and_failed_load_boundaries_are_unchanged(self):
        loader = self._function_source("load_project_json_into_session")
        self.assertLess(
            loader.index(
                "project = load_project_from_json(project_path)"
            ),
            loader.index("reset_management_workspace_session_state()"),
        )
        self.assertLess(
            loader.index("reset_management_workspace_session_state()"),
            loader.index("st.session_state.project = project"),
        )
        before_success = loader[
            : loader.index("project = load_project_from_json(project_path)")
        ]
        self.assertNotIn(
            "reset_management_workspace_session_state()",
            before_success,
        )
        self.assertNotIn("disabled_modules", loader)

    def test_edit_scope_authoring_and_gallery_do_not_gain_toggle_or_launcher(self):
        excluded_owners = (
            "render_module_inspector_edit_scope_section",
            "render_module_attribute_authoring_workspace",
            "render_gallery_operations_launcher",
            "render_gallery_active_operation_panel",
            "render_pro_gallery_mode",
        )
        for owner in excluded_owners:
            source = self._function_source(owner)
            self.assertNotIn(
                "open_module_attribute_apply_workspace",
                source,
            )
            self.assertNotIn(self.toggle_name, source)
            self.assertNotIn(self.insert_name, source)
        workspace = self._function_source(self.workspace_name)
        for forbidden in (
            "module_inspector_selected",
            "module_edit_scope_name",
            "module_scope_use_btn",
            "clear_active_module_edit_scope",
            "render_module_attribute_table_section",
            "render_project_module_inspector_section",
        ):
            self.assertNotIn(forbidden, workspace)


if __name__ == "__main__":
    unittest.main()
