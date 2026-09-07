import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, Mock, patch

from core import comfy_workflow_preparation


class ComfyWorkflowPreparationTests(unittest.TestCase):
    def test_group_mapping_uses_grouped_prompt_and_does_not_mutate_line(self):
        line = SimpleNamespace(current_text="smile", negative_prompt="blur")
        before = copy.deepcopy(vars(line))
        mapping = {"group_map": {"default": "positive"}, "positive": {}}
        injected = Mock(return_value={"mapped": True})

        with patch("core.comfyui.build_prompt_by_group", return_value={"default": ["expanded"]}) as grouped, \
                patch.object(comfy_workflow_preparation, "inject_prompt_to_workflow", injected):
            result = comfy_workflow_preparation._build_line_workflow_from_text(
                '{"p": {"inputs": {"text": "__PROMPT__"}}}',
                line,
                {"comfy_mapping": mapping},
                project=object(),
                disabled_modules={"disabled"},
            )

        self.assertEqual(result, ({"mapped": True}, ""))
        grouped.assert_called_once_with(ANY, line, {"disabled"})
        injected.assert_called_once_with(
            {"p": {"inputs": {"text": "__PROMPT__"}}},
            {"default": ["expanded"]},
            mapping,
            fallback_prompt="smile",
        )
        self.assertEqual(vars(line), before)

    def test_placeholder_replacement_preserves_json_escaping(self):
        line = SimpleNamespace(current_text='quote " slash \\ and\n青', negative_prompt="blur")
        workflow_text = (
            '{"p": {"class_type": "CLIPTextEncode", "inputs": {"text": "__PROMPT__"}}, '
            '"n": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}}}'
        )

        result, warning = comfy_workflow_preparation._build_line_workflow_from_text(
            workflow_text, line, {},
        )

        self.assertEqual(result["p"]["inputs"]["text"], line.current_text)
        self.assertEqual(result["n"]["inputs"]["text"], "old negative")
        self.assertEqual(warning, "")
        self.assertEqual(json.loads(workflow_text)["p"]["inputs"]["text"], "__PROMPT__")

    def test_clip_binding_warning_is_preserved_when_no_target_exists(self):
        line = SimpleNamespace(current_text="smile", negative_prompt="blur")

        result, warning = comfy_workflow_preparation._build_line_workflow_from_text(
            '{"unknown": {}}', line, {},
        )

        self.assertEqual(result, {"unknown": {}})
        self.assertEqual(warning, "The workflow JSON does not contain '__PROMPT__'. The prompt may not be injected.")

    def test_malformed_workflow_json_propagates_in_each_preparation_branch(self):
        cases = (
            ("group mapping", '{', {"comfy_mapping": {"group_map": {}}}),
            ("placeholder", '{"p": {"inputs": {"text": "__PROMPT__"}', {}),
            ("plain", "not-json", {}),
        )
        line = SimpleNamespace(current_text="smile")
        for label, workflow_text, settings in cases:
            with self.subTest(label=label), self.assertRaises(json.JSONDecodeError):
                comfy_workflow_preparation._build_line_workflow_from_text(
                    workflow_text, line, settings,
                )


if __name__ == "__main__":
    unittest.main()
