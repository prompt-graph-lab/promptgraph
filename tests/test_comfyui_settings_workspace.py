import ast
import os
import tempfile
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


class _RenderStub:
    def __init__(self, session_state):
        self.session_state = session_state
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def markdown(self, message):
        self.messages.append(("markdown", message))

    def caption(self, message):
        self.messages.append(("caption", message))

    def text_input(self, label, **kwargs):
        self.messages.append(("text_input", label, kwargs))

    def checkbox(self, label, **kwargs):
        self.messages.append(("checkbox", label, kwargs))


class ComfyUiSettingsWorkspaceTests(unittest.TestCase):
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

    def test_workspace_router_dispatches_all_real_workspaces(self):
        shell = self._function_source("render_management_workspace_shell")
        self.assertIn('if target == "project_management":', shell)
        self.assertIn("render_project_management_workspace()", shell)
        self.assertIn('if target == "module_attribute_authoring":', shell)
        self.assertIn("render_module_attribute_authoring_workspace()", shell)
        self.assertIn('if target == "comfyui_settings":', shell)
        self.assertIn("render_comfyui_settings_workspace()", shell)

    def test_no_management_workspace_placeholder_remains(self):
        shell = self._function_source("render_management_workspace_shell")
        self.assertNotIn("placeholder", shell.lower())
        self.assertNotIn("Planned destination", shell)

    def test_relocated_and_daily_widgets_each_have_one_render_owner(self):
        for key in (
            "comfy_url",
            "comfy_workflow_path",
            "force_shared_comfy_workflow",
            "comfy_workflow_preset",
        ):
            self.assertEqual(self.app_source.count(f'key="{key}"'), 1, key)

        workspace = self._function_source("render_comfyui_settings_workspace")
        daily = self._function_source("render_comfyui_daily_sidebar_section")
        for key in (
            "comfy_url",
            "comfy_workflow_path",
            "force_shared_comfy_workflow",
        ):
            self.assertIn(f'key="{key}"', workspace)
            self.assertNotIn(f'key="{key}"', daily)
        self.assertIn('key="comfy_workflow_preset"', daily)
        self.assertNotIn('key="comfy_workflow_preset"', workspace)

    def test_workflow_inspector_has_one_workspace_owner(self):
        workspace = self._function_source("render_comfyui_settings_workspace")
        daily = self._function_source("render_comfyui_daily_sidebar_section")
        self.assertEqual(
            workspace.count("render_comfy_workflow_inspector(st)"),
            1,
        )
        self.assertNotIn("render_comfy_workflow_inspector", daily)
        self.assertEqual(
            self.app_source.count(
                "render_comfy_workflow_inspector(st)"
            ),
            1,
        )

    def test_settings_workspace_has_no_generation_execution_calls(self):
        workspace_node = self.functions["render_comfyui_settings_workspace"]
        call_names = {
            node.func.id
            for node in ast.walk(workspace_node)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        for forbidden in (
            "generate_image_with_progress",
            "render_gallery_global_generation_controls",
            "_build_focus_line_generation_workflow",
            "_execute_selected_routes_gallery_generation_plan",
        ):
            self.assertNotIn(forbidden, call_names)
        self.assertIn("render_comfy_workflow_inspector", call_names)

    def test_session_initialization_preserves_values_and_never_saves(self):
        saves = []
        session_state = _SessionState(
            settings={
                "comfyui_url": "stored:8188",
                "comfyui_workflow_path": "stored.json",
                "comfyui_workflow_preset": "missing.json",
                "force_shared_comfy_workflow": True,
            },
            comfy_url="session:8188",
        )
        namespace = self._load_functions(
            "ensure_comfy_settings_session_state",
            namespace={
                "st": types.SimpleNamespace(session_state=session_state),
                "list_comfy_workflow_presets": lambda: ["valid.json"],
                "save_settings": lambda settings: saves.append(settings),
            },
        )

        options = namespace["ensure_comfy_settings_session_state"]()

        self.assertEqual(options, ["", "valid.json"])
        self.assertEqual(session_state.comfy_url, "session:8188")
        self.assertEqual(session_state.comfy_workflow_path, "stored.json")
        self.assertEqual(session_state.comfy_workflow_preset, "")
        self.assertTrue(session_state.force_shared_comfy_workflow)
        self.assertEqual(saves, [])

    def test_explicit_change_persists_actual_widget_values_once(self):
        saved = []
        settings = {}
        session_state = _SessionState(
            settings=settings,
            comfy_url="new:8188",
            comfy_workflow_path="new-workflow.json",
            comfy_workflow_preset="new-preset.json",
            force_shared_comfy_workflow=True,
        )
        namespace = self._load_functions(
            "update_comfy_settings",
            namespace={
                "st": types.SimpleNamespace(session_state=session_state),
                "save_settings": lambda value: saved.append(dict(value)),
            },
        )

        namespace["update_comfy_settings"]()

        self.assertEqual(len(saved), 1)
        self.assertEqual(
            saved[0],
            {
                "comfyui_url": "new:8188",
                "comfyui_workflow_path": "new-workflow.json",
                "comfyui_workflow_preset": "new-preset.json",
                "force_shared_comfy_workflow": True,
            },
        )

    def test_normal_rendering_does_not_save_settings(self):
        for name in (
            "ensure_comfy_settings_session_state",
            "render_comfyui_settings_workspace",
            "render_comfyui_daily_sidebar_section",
        ):
            self.assertNotIn("save_settings(", self._function_source(name))

    def test_workspace_uses_existing_resolver_and_renders_without_project(self):
        session_state = _SessionState(
            comfy_workflow_path="fallback.json",
            comfy_workflow_preset="preset.json",
        )
        st = _RenderStub(session_state)
        inspector_calls = []
        namespace = self._load_functions(
            "render_comfyui_settings_workspace",
            namespace={
                "st": st,
                "ensure_comfy_settings_session_state": lambda: None,
                "update_comfy_settings": lambda: None,
                "resolve_effective_comfy_workflow_path": (
                    lambda path: ("C:/resolved/workflow.json", "preset")
                ),
                "render_comfy_workflow_inspector": (
                    lambda container: inspector_calls.append(container)
                ),
            },
        )

        namespace["render_comfyui_settings_workspace"]()

        self.assertTrue(
            any(
                item[0] == "caption" and "Resolved source: preset" in item[1]
                for item in st.messages
            )
        )
        self.assertEqual([st], inspector_calls)

    def test_effective_workflow_resolution_precedence_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preset_dir = root / "workflows"
            preset_dir.mkdir()
            preset_path = preset_dir / "preset.json"
            preset_path.write_text("{}", encoding="utf-8")
            configured_path = root / "configured.json"
            configured_path.write_text("{}", encoding="utf-8")
            session_state = _SessionState(
                settings={
                    "comfyui_workflow_path": str(configured_path),
                    "comfyui_workflow_preset": "preset.json",
                    "force_shared_comfy_workflow": False,
                },
                comfy_workflow_path=str(configured_path),
                comfy_workflow_preset="preset.json",
                force_shared_comfy_workflow=False,
                current_project_path="",
            )
            namespace = self._load_functions(
                "resolve_comfy_workflow_path",
                "resolve_comfy_workflow_preset_path",
                "resolve_effective_comfy_workflow_path",
                namespace={
                    "os": os,
                    "st": types.SimpleNamespace(session_state=session_state),
                    "WORKFLOW_PRESET_DIR": str(preset_dir),
                },
            )
            resolve = namespace["resolve_effective_comfy_workflow_path"]

            self.assertEqual(resolve(), (str(configured_path), "project"))
            session_state.force_shared_comfy_workflow = True
            self.assertEqual(resolve(), (str(preset_path), "preset"))
            session_state.force_shared_comfy_workflow = False
            configured_path.unlink()
            self.assertEqual(resolve(), (str(preset_path), "preset"))
            preset_path.unlink()
            self.assertEqual(resolve()[1], "fallback")

    def test_focus_and_gallery_generation_keep_existing_session_keys(self):
        gallery_options = self._function_source(
            "_selected_routes_generation_options"
        )
        gallery_execution = self._function_source(
            "_execute_selected_routes_gallery_generation_plan"
        )
        focus_start = self.app_source.index(
            'if st.button("🎨 Generate with ComfyUI", type="primary"):'
        )
        focus_end = self.app_source.index(
            'with profile_block("Candidate Gallery render"):',
            focus_start,
        )
        focus = self.app_source[focus_start:focus_end]
        self.assertIn('"comfy_url"', gallery_options)
        self.assertIn('"comfy_workflow_path"', gallery_options)
        self.assertIn("resolve_effective_comfy_workflow_path", gallery_options)
        self.assertIn('"comfy_url"', gallery_execution)
        self.assertIn('"force_shared_comfy_workflow"', gallery_options)
        self.assertIn("st.session_state.comfy_url", focus)
        self.assertIn("st.session_state.comfy_workflow_path", focus)
        self.assertIn("resolve_effective_comfy_workflow_path", focus)
        self.assertIn('"force_shared_comfy_workflow"', focus)

    def test_back_and_project_transitions_do_not_reset_comfy_values(self):
        reset = self._function_source("reset_management_workspace_session_state")
        transitions = "\n".join(
            self._function_source(name)
            for name in (
                "load_project_json_into_session",
                "set_new_workspace_project",
                "duplicate_current_project_directory",
            )
        )
        for key in (
            "comfy_url",
            "comfy_workflow_path",
            "comfy_workflow_preset",
            "force_shared_comfy_workflow",
        ):
            self.assertNotIn(key, reset)
            self.assertNotIn(f'pop("{key}"', transitions)
            self.assertNotIn(f'pop(\\"{key}\\"', transitions)

    def test_no_project_persisted_comfy_settings_field_is_added(self):
        workspace = self._function_source("render_comfyui_settings_workspace")
        self.assertNotIn("save_project", workspace)
        self.assertNotIn("Project.", workspace)
        self.assertNotIn("st.session_state.project", workspace)


if __name__ == "__main__":
    unittest.main()
