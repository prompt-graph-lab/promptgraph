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
    def __init__(self, events):
        self.events = events

    def subheader(self, message):
        self.events.append(("subheader", message))

    def caption(self, message):
        self.events.append(("sidebar_caption", message))


class _StreamlitStub:
    def __init__(self, disabled_modules, checkbox_values=None):
        self.session_state = _SessionState(
            disabled_modules=set(disabled_modules),
        )
        self.events = []
        self.sidebar = _Sidebar(self.events)
        self.checkbox_values = dict(checkbox_values or {})
        self.rerun_count = 0

    def caption(self, message):
        self.events.append(("caption", message))

    def info(self, message):
        self.events.append(("info", message))

    def expander(self, label, expanded=False):
        self.events.append(("expander", label, expanded))
        return _Expander()

    def checkbox(self, label, value, key):
        self.events.append(("checkbox", label, value, key))
        return self.checkbox_values.get(key, value)

    def rerun(self):
        self.rerun_count += 1


class ModuleAttributeApplySidebarExtractionTests(unittest.TestCase):
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
        cls.renderer_name = "render_module_attribute_apply_sidebar_section"
        cls.renderer_node = cls.functions[cls.renderer_name]
        cls.renderer_source = ast.get_source_segment(
            cls.app_source,
            cls.renderer_node,
        )
        cls.toggle_renderer_name = "render_module_toggle_controls"
        cls.toggle_renderer_node = cls.functions[cls.toggle_renderer_name]
        cls.toggle_renderer_source = ast.get_source_segment(
            cls.app_source,
            cls.toggle_renderer_node,
        )

    def _function_source(self, name):
        return ast.get_source_segment(self.app_source, self.functions[name])

    def _top_level_source(self):
        start = self.app_source.rindex("render_common_undo_sidebar_section()")
        return self.app_source[start:]

    def _load_toggle_renderer(
        self,
        *,
        modules,
        disabled_modules=(),
        checkbox_values=None,
    ):
        st = _StreamlitStub(disabled_modules, checkbox_values)
        namespace = {
            "st": st,
            "get_available_modules": lambda project: list(modules),
        }
        module = ast.Module(
            body=[self.toggle_renderer_node],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace[self.toggle_renderer_name], st

    def test_named_renderer_and_top_level_owner_preserve_sidebar_order(self):
        self.assertIn(self.renderer_name, self.functions)
        top_level = self._top_level_source()
        call = (
            "render_module_attribute_apply_sidebar_section("
            "st.session_state.project)"
        )
        self.assertEqual(top_level.count(call), 1)
        before = top_level.rfind(
            'st.sidebar.markdown("---")',
            0,
            top_level.index(call),
        )
        after = top_level.index(
            'st.sidebar.markdown("---")',
            top_level.index(call) + len(call),
        )
        analysis = top_level.index(
            'st.sidebar.subheader("Module / Attribute Analysis")'
        )
        self.assertGreaterEqual(before, 0)
        self.assertLess(before, top_level.index(call))
        self.assertLess(top_level.index(call), after)
        self.assertLess(after, analysis)

    def test_apply_labels_remain_in_sidebar_and_toggle_has_one_workspace_owner(self):
        for expected in (
            'st.sidebar.subheader("Module / Attribute Apply")',
            'st.sidebar.caption("Preview or apply Module references.")',
        ):
            self.assertIn(expected, self.renderer_source)
            self.assertEqual(self.app_source.count(expected), 1)
        self.assertIn(
            'with st.expander("Module Toggles", expanded=False):',
            self.toggle_renderer_source,
        )
        self.assertEqual(
            self.app_source.count(
                'with st.expander("Module Toggles", expanded=False):'
            ),
            1,
        )
        self.assertNotIn("st.sidebar", self.toggle_renderer_source)
        self.assertNotIn(
            'with st.sidebar.expander("Module Toggles"',
            self.renderer_source,
        )
        self.assertNotIn("mod_toggle_", self.renderer_source)
        self.assertNotIn("disabled_modules", self.renderer_source)
        top_level = self._top_level_source()
        self.assertNotIn(
            'st.sidebar.subheader("Module / Attribute Apply")',
            top_level,
        )

    def test_module_toggle_logic_and_messages_are_unchanged(self):
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
            self.assertIn(expected, self.toggle_renderer_source)

    def test_toggle_disable_and_enable_remain_session_only(self):
        project = object()
        render, st = self._load_toggle_renderer(
            modules=["pose", "outfit"],
            disabled_modules={"outfit"},
            checkbox_values={
                "mod_toggle_pose": False,
                "mod_toggle_outfit": True,
            },
        )

        render(project)

        self.assertEqual(st.session_state.disabled_modules, {"pose"})
        self.assertEqual(st.rerun_count, 2)
        self.assertEqual(
            [event for event in st.events if event[0] == "checkbox"],
            [
                ("checkbox", "Module pose", True, "mod_toggle_pose"),
                ("checkbox", "Module outfit", False, "mod_toggle_outfit"),
            ],
        )

    def test_no_project_and_no_modules_keep_existing_messages(self):
        for project, modules, message in (
            (None, ["ignored"], "Load project first."),
            (object(), [], "No modules detected."),
        ):
            with self.subTest(message=message):
                render, st = self._load_toggle_renderer(
                    modules=modules,
                )
                render(project)
                self.assertIn(("info", message), st.events)

    def test_relocated_children_have_one_apply_workspace_owner_each(self):
        self.assertNotIn(
            "render_attribute_group_swap_section",
            self.renderer_source,
        )
        swap_renderer = self._function_source(
            "render_attribute_group_swap_section"
        )
        self.assertIn(
            'with st.expander("Attribute Group Swap", '
            "expanded=False):",
            swap_renderer,
        )
        self.assertNotIn("st.sidebar", swap_renderer)

        owner_by_child = {}
        for child_name in (
            "render_insert_saved_module_reference_section",
            "render_module_candidate_selection_section",
            "render_attribute_group_swap_section",
        ):
            owners = []
            for function_name, function_node in self.functions.items():
                if any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == child_name
                    for node in ast.walk(function_node)
                ):
                    owners.append(function_name)
            owner_by_child[child_name] = owners
        self.assertEqual(
            owner_by_child,
            {
                "render_insert_saved_module_reference_section": [
                    "render_module_attribute_apply_workspace"
                ],
                "render_module_candidate_selection_section": [
                    "render_module_attribute_apply_workspace"
                ],
                "render_attribute_group_swap_section": [
                    "render_module_attribute_apply_workspace"
                ],
            },
        )

    def test_sidebar_renderer_is_not_called_from_other_workspaces(self):
        for owner in (
            "render_module_attribute_authoring_workspace",
            "render_management_workspace_shell",
            "render_project_management_workspace",
            "render_comfyui_settings_workspace",
        ):
            self.assertNotIn(
                self.renderer_name,
                self._function_source(owner),
            )

    def test_edit_scope_and_analysis_remain_outside_apply_renderer(self):
        for forbidden in (
            "render_module_inspector_edit_scope_section",
            "render_module_edit_scope_controls",
            "render_module_attribute_table_section",
            "render_project_module_inspector_section",
            "module_edit_scope_name",
            "module_scope_use_btn",
            "clear_active_module_edit_scope",
        ):
            self.assertNotIn(forbidden, self.renderer_source)

        top_level = self._top_level_source()
        apply_call = top_level.index(
            "render_module_attribute_apply_sidebar_section("
        )
        analysis = top_level.index(
            'st.sidebar.subheader("Module / Attribute Analysis")'
        )
        edit_scope = top_level.index(
            "render_module_inspector_edit_scope_section()"
        )
        self.assertLess(apply_call, analysis)
        self.assertLess(analysis, edit_scope)

    def test_outer_renderer_adds_no_state_save_history_or_project_mutation(self):
        combined_source = (
            self.renderer_source + "\n" + self.toggle_renderer_source
        )
        self.assertNotIn("push_history(", combined_source)
        self.assertNotIn("save_project", combined_source)
        self.assertNotIn("save_settings", combined_source)
        self.assertNotIn("st.session_state.project =", combined_source)

        direct_state = {
            node.attr
            for function_node in (
                self.renderer_node,
                self.toggle_renderer_node,
            )
            for node in ast.walk(function_node)
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "st"
                and node.value.attr == "session_state"
            )
        }
        self.assertEqual(direct_state, {"disabled_modules"})

        fixed_widget_keys = {
            keyword.value.value
            for node in ast.walk(self.toggle_renderer_node)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if (
                keyword.arg == "key"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            )
        }
        self.assertEqual(fixed_widget_keys, set())
        self.assertEqual(
            self.renderer_source.count(
                'key="open_module_attribute_apply_workspace"'
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
