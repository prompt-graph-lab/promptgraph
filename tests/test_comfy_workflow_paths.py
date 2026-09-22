import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core import comfy_workflow_paths as paths


class ComfyWorkflowPathsTests(unittest.TestCase):
    def test_path_context_is_lazy_and_relative_paths_use_project_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            context = Mock(return_value=os.path.join(directory, 'project.json'))
            for empty in ('', None, False):
                self.assertEqual(paths.resolve_comfy_workflow_path(empty, get_current_project_path=context), '')
            absolute = os.path.join(directory, 'workflow.json')
            self.assertEqual(paths.resolve_comfy_workflow_path(absolute, get_current_project_path=context), absolute)
            context.assert_not_called()
            self.assertEqual(paths.resolve_comfy_workflow_path('workflow.json', get_current_project_path=context), absolute)
            context.assert_called_once_with()
            self.assertEqual(paths.resolve_comfy_workflow_path('workflow.json', get_current_project_path=lambda: ''), os.path.abspath('workflow.json'))
            with patch.object(paths.os.path, 'expanduser', return_value=absolute):
                self.assertEqual(paths.resolve_comfy_workflow_path('~/workflow.json', get_current_project_path=Mock(side_effect=AssertionError)), absolute)

    def test_preset_listing_and_basename_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('z.JSON', 'A.json', 'ignored.txt'):
                (root / name).write_text('{}')
            (root / 'directory.json').mkdir()
            self.assertEqual(paths.list_comfy_workflow_presets(directory), ['A.json', 'z.JSON'])
            self.assertEqual(paths.list_comfy_workflow_presets(str(root / 'missing')), [])
            # Legacy behavior strips parent components rather than rejecting them.
            self.assertEqual(paths.resolve_comfy_workflow_preset_path(' ../missing.JSON ', directory), str(root / 'missing.JSON'))
            for name in ('', None, 'not-json.txt', '..'):
                self.assertEqual(paths.resolve_comfy_workflow_preset_path(name, directory), '')

    def test_precedence_short_circuit_and_repeated_exists_order(self):
        scenarios = [
            (True, [True], ('preset.json', 'preset'), ['preset.json'], False),
            (True, [False, True], ('project.json', 'project'), ['preset.json', 'project.json'], True),
            (True, [False, False, True], ('preset.json', 'preset'), ['preset.json', 'project.json', 'preset.json'], True),
            (False, [True], ('project.json', 'project'), ['project.json'], True),
            (False, [False, True], ('preset.json', 'preset'), ['project.json', 'preset.json'], True),
            (False, [False, False], ('project.json', 'fallback'), ['project.json', 'preset.json'], True),
        ]
        for forced, exists_results, expected, checks, resolved in scenarios:
            with self.subTest(forced=forced, checks=checks):
                resolver = Mock(return_value='project.json')
                with patch.object(paths.os.path, 'exists', side_effect=exists_results) as exists:
                    self.assertEqual(paths.resolve_effective_comfy_workflow_path('configured', 'preset.json', forced, resolve_project_path=resolver), expected)
                self.assertEqual([call.args[0] for call in exists.call_args_list], checks)
                self.assertEqual(resolver.call_count, int(resolved))

    def test_empty_fallback_directory_acceptance_and_exception_propagation(self):
        with patch.object(paths.os.path, 'exists', side_effect=AssertionError):
            self.assertEqual(paths.resolve_effective_comfy_workflow_path('', '', False, resolve_project_path=lambda _: ''), ('', 'fallback'))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(paths.resolve_effective_comfy_workflow_path(directory, '', False, resolve_project_path=lambda value: value), (directory, 'project'))
        error = RuntimeError('path resolution failed')
        with self.assertRaises(RuntimeError) as caught:
            paths.resolve_effective_comfy_workflow_path('configured', '', False, resolve_project_path=Mock(side_effect=error))
        self.assertIs(caught.exception, error)


if __name__ == '__main__':
    unittest.main()
