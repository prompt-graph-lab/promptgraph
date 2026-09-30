import json
import ntpath
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core import settings, comfy_workflow_paths
from tests import test_comfyui_settings_workspace as workspace_tests
from core.project import Project
from core.io import save_project_to_json


class ComfyWorkflowPresetDirectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workspace_tests.ComfyUiSettingsWorkspaceTests.setUpClass()

    def load_app(self, state, bundled, saved, *names):
        harness = workspace_tests.ComfyUiSettingsWorkspaceTests()
        return harness._load_functions(
            "get_active_comfy_workflow_preset_directory",
            "list_comfy_workflow_presets",
            "resolve_comfy_workflow_preset_path",
            "get_comfy_workflow_preset_directory_error",
            "update_comfy_workflow_preset_directory",
            "reset_comfy_workflow_preset_directory",
            "ensure_comfy_settings_session_state",
            *names,
            namespace={
                "os": os, "st": workspace_tests._RenderStub(state),
                "WORKFLOW_PRESET_DIR": str(bundled),
                "comfy_workflow_paths": comfy_workflow_paths,
                "save_settings": lambda value: saved.append(dict(value)),
            },
        )

    def test_missing_and_blank_settings_use_bundled_without_persisting_absolute_path(self):
        with tempfile.TemporaryDirectory() as directory:
            bundled = str(Path(directory) / 'workflows')
            for config in ({}, {"comfyui_workflow_preset_directory": ""}, {"comfyui_workflow_preset_directory": "  "}):
                self.assertEqual(settings.get_comfyui_workflow_preset_directory(config, bundled), bundled)
            with patch.object(settings, 'SETTINGS_FILE', str(Path(directory) / 'settings.json')):
                self.assertEqual(settings.load_settings()['comfyui_workflow_preset_directory'], '')
                Path(settings.SETTINGS_FILE).write_text(json.dumps({'comfyui_workflow_preset': 'old.json'}))
                self.assertEqual(settings.load_settings()['comfyui_workflow_preset_directory'], '')

    def test_absolute_home_and_windows_normalization_retains_invalid_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(settings.normalize_comfyui_workflow_preset_directory(' '+directory+' '), directory)
        self.assertEqual(settings.normalize_comfyui_workflow_preset_directory('~/presets'), os.path.abspath(os.path.expanduser('~/presets')))
        windows_os = types.SimpleNamespace(name='nt', fspath=os.fspath, path=ntpath)
        with patch.object(settings, 'os', windows_os):
            self.assertEqual(settings.normalize_comfyui_workflow_preset_directory(' C:/presets/../workflows '), 'C:\\workflows')
            for invalid in ('C:\\bad*path', 'C:\\bad\x00path', 'C:\\bad\npath'):
                self.assertEqual(settings.normalize_comfyui_workflow_preset_directory(invalid), invalid)

    def test_external_discovery_resolution_and_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root/'bundled'
            external = root/'external'
            bundled.mkdir()
            external.mkdir()
            (bundled/'bundled.json').write_text('{}')
            for name in ('z.JSON', 'a.json', 'ignore.txt'):
                (external/name).write_text('{}')
            (external/'folder.json').mkdir()
            (external/'nested').mkdir()
            (external/'nested'/'hidden.json').write_text('{}')
            state = workspace_tests._SessionState(settings={'comfyui_workflow_preset_directory': str(external)}, comfy_workflow_preset='a.json')
            ns = self.load_app(state, bundled, [], 'resolve_comfy_workflow_path', 'resolve_effective_comfy_workflow_path')
            self.assertEqual(ns['list_comfy_workflow_presets'](), ['a.json', 'z.JSON'])
            self.assertEqual(ns['resolve_comfy_workflow_preset_path']('a.json'), str(external/'a.json'))
            project_workflow = root/'workflow.json'
            project_workflow.write_text('{}')
            state.comfy_workflow_path = str(project_workflow)
            self.assertEqual(ns['resolve_effective_comfy_workflow_path'](), (str(project_workflow), 'project'))
            state.force_shared_comfy_workflow = True
            self.assertEqual(ns['resolve_effective_comfy_workflow_path'](), (str(external/'a.json'), 'preset'))
            state.force_shared_comfy_workflow = False
            project_workflow.unlink()
            self.assertEqual(ns['resolve_effective_comfy_workflow_path']()[1], 'preset')

    def test_broken_external_paths_never_list_or_resolve_bundled_presets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root/'bundled'
            bundled.mkdir()
            (bundled/'preset.json').write_text('{}')
            nondirectory = root/'file'
            nondirectory.write_text('x')
            for broken in (str(root/'missing'), str(nondirectory), str(root/'bad\x00path'), str(root/'bad\npath'), str(bundled/'bad*'/'..')):
                state = workspace_tests._SessionState(settings={'comfyui_workflow_preset_directory': broken}, comfy_workflow_preset='preset.json')
                saved = []
                ns = self.load_app(state, bundled, saved, 'resolve_comfy_workflow_path', 'resolve_effective_comfy_workflow_path')
                self.assertTrue(ns['get_active_comfy_workflow_preset_directory']())
                self.assertNotEqual(ns['get_active_comfy_workflow_preset_directory'](), str(bundled))
                self.assertEqual(ns['list_comfy_workflow_presets'](), [])
                self.assertTrue(ns['get_comfy_workflow_preset_directory_error']())
                self.assertEqual(ns['resolve_effective_comfy_workflow_path']('')[1], 'fallback')
                self.assertEqual(saved, [])

    def test_explicit_switch_and_reset_reconcile_filename_and_save_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root/'bundled'
            bundled.mkdir()
            external = root/'external'
            external.mkdir()
            (bundled/'same.json').write_text('{}')
            (external/'same.json').write_text('{}')
            (external/'external-only.json').write_text('{}')
            state = workspace_tests._SessionState(settings={'comfyui_workflow_preset': 'same.json'}, comfy_workflow_preset='same.json')
            saved = []
            ns = self.load_app(state, bundled, saved)
            ns['ensure_comfy_settings_session_state']()
            self.assertEqual(saved, [])
            state.comfy_workflow_preset_directory = str(external)
            ns['update_comfy_workflow_preset_directory']()
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[-1]['comfyui_workflow_preset'], 'same.json')
            ns['reset_comfy_workflow_preset_directory']()
            self.assertEqual(len(saved), 2)
            self.assertEqual(saved[-1]['comfyui_workflow_preset_directory'], '')
            self.assertEqual(state.comfy_workflow_preset, 'same.json')
            state.comfy_workflow_preset_directory = str(external)
            ns['update_comfy_workflow_preset_directory']()
            state.comfy_workflow_preset = 'external-only.json'
            ns['reset_comfy_workflow_preset_directory']()
            self.assertEqual(len(saved), 4)
            self.assertEqual(state.comfy_workflow_preset, '')
            self.assertEqual(saved[-1]['comfyui_workflow_preset'], '')
            state.comfy_workflow_preset = 'same.json'
            state.comfy_workflow_preset_directory = str(root/'missing')
            ns['update_comfy_workflow_preset_directory']()
            self.assertEqual(len(saved), 5)
            self.assertEqual(saved[-1]['comfyui_workflow_preset'], '')
            self.assertEqual(state.comfy_workflow_preset, '')
            self.assertFalse((root/'missing').exists())

    def test_passive_directory_settings_status_does_not_save_and_shows_broken_path(self):
        with tempfile.TemporaryDirectory() as directory:
            state = workspace_tests._SessionState(settings={'comfyui_workflow_preset_directory': str(Path(directory)/'missing')})
            saved = []
            ns = self.load_app(state, directory, saved, 'render_comfy_workflow_preset_directory_settings')
            stub = ns['st']
            stub.button = lambda *args, **kwargs: stub.messages.append(('button', args, kwargs))
            stub.warning = lambda text: stub.messages.append(('warning', text))
            ns['ensure_comfy_settings_session_state']()
            ns['render_comfy_workflow_preset_directory_settings']()
            ns['render_comfy_workflow_preset_directory_settings']()
            self.assertEqual(saved, [])
            self.assertTrue(any(message[0]=='warning' for message in stub.messages))
            self.assertNotIn('comfyui_workflow_preset_directory', (Path(__file__).resolve().parents[1]/'core/project.py').read_text(encoding='utf-8'))

    def test_directory_change_keeps_project_serialization_and_does_not_save_project(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Project()
            project_file = Path(directory)/'project.json'
            save_project_to_json(project, str(project_file))
            before = project_file.read_bytes()
            state = workspace_tests._SessionState(settings={}, project=project,
                comfy_workflow_preset_directory=str(Path(directory)/'external'))
            ns = self.load_app(state, directory, [])
            ns['save_project_to_json'] = lambda *_args: self.fail('Directory change must not save Project')
            ns['update_comfy_workflow_preset_directory']()
            self.assertIs(state.project, project)
            self.assertEqual(project_file.read_bytes(), before)
            save_project_to_json(project, str(project_file))
            self.assertEqual(project_file.read_bytes(), before)
            self.assertNotIn('comfyui_workflow_preset_directory', json.loads(before))

    def test_generation_and_debug_consumers_keep_central_resolver(self):
        harness = workspace_tests.ComfyUiSettingsWorkspaceTests()
        for name in (
            'build_single_line_workflow',
            'render_single_line_comfy_execution',
            '_build_focus_line_generation_workflow',
            '_build_focus_line_workflow_preview',
            'render_comfy_workflow_debug_preview',
            'render_comfy_workflow_inspector',
            '_selected_routes_generation_options',
        ):
            self.assertIn('resolve_effective_comfy_workflow_path(', harness._function_source(name))


if __name__ == '__main__':
    unittest.main()
