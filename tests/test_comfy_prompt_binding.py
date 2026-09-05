import copy
import unittest
from types import SimpleNamespace

from core.comfy_prompt_binding import (
    _infer_workflow_prompt_node_ids,
    _replace_clip_text_prompts,
    _workflow_submitted_prompt_debug,
)


def text_node(text, class_type="CLIPTextEncode", **inputs):
    return {"class_type": class_type, "inputs": {"text": text, **inputs}}


def sampler(positive="p", negative="n"):
    return {"class_type": "KSamplerAdvanced", "inputs": {
        "positive": [positive, 0], "negative": {"node_id": negative},
    }}


class ComfyPromptBindingTests(unittest.TestCase):
    def setUp(self):
        self.line = SimpleNamespace(current_text='青い髪, "smile"\nportrait', negative_prompt="blur")

    def test_sampler_roles_override_metadata_matches_and_preserve_unrelated_fields(self):
        workflow = {"p": text_node("old"), "n": text_node("old negative"),
                    "s": sampler(), "unused": text_node("old"), "extension": {"future": [1, 2]}}
        before_line = copy.deepcopy(vars(self.line))
        self.assertEqual(_replace_clip_text_prompts(workflow, self.line, {"prompt_text": "old"}), 2)
        self.assertEqual(workflow["p"]["inputs"]["text"], self.line.current_text)
        self.assertEqual(workflow["n"]["inputs"]["text"], "blur")
        self.assertEqual(workflow["unused"]["inputs"]["text"], "old")
        self.assertEqual(workflow["extension"], {"future": [1, 2]})
        self.assertEqual(vars(self.line), before_line)

    def test_upstream_traversal_handles_cycles_missing_links_and_deduplicates_per_role(self):
        workflow = {"p": text_node("p", "CustomText", cycle=["bridge", 0]),
                    "q": text_node("q"), "n": text_node("n"),
                    "bridge": {"inputs": {"first": ["p", 0], "second": ["q", 0], "missing": ["gone", 0]}},
                    "s": sampler("bridge"), "s2": sampler("bridge")}
        self.assertEqual(_infer_workflow_prompt_node_ids(workflow), {
            "positive": ["q", "p"], "negative": ["n"],
        })
        self.assertEqual(_replace_clip_text_prompts(workflow, self.line), 3)

    def test_wrapped_nodes_and_sampler_type_fallback(self):
        workflow = {"nodes": {"p": text_node("p"), "n": text_node("n"),
                              "s": {"type": "ksampler", "inputs": {"positive": ["p", 0], "negative": ["n", 0]}}},
                    "extra": "keep"}
        self.assertEqual(_replace_clip_text_prompts(workflow, self.line), 2)
        self.assertEqual(workflow["extra"], "keep")
        debug = _workflow_submitted_prompt_debug(workflow, self.line)
        self.assertEqual(debug["submitted_positive_prompts"], [self.line.current_text])
        self.assertEqual(debug["submitted_negative_prompts"], ["blur"])

    def test_metadata_fallback_matches_exact_text_once_per_role(self):
        workflow = {"a": text_node("old"), "b": text_node("negative"), "c": text_node("old")}
        self.assertEqual(_replace_clip_text_prompts(workflow, self.line, {
            "prompt_text": "old", "negative_prompt": "negative",
        }), 2)
        self.assertEqual(workflow["a"]["inputs"]["text"], self.line.current_text)
        self.assertEqual(workflow["b"]["inputs"]["text"], "blur")
        self.assertEqual(workflow["c"]["inputs"]["text"], "old")

    def test_single_clip_fallback_and_ambiguous_multiple_clip_noop(self):
        single = {"a": text_node("old")}
        self.assertEqual(_replace_clip_text_prompts(single, self.line), 1)
        self.assertEqual(single["a"]["inputs"]["text"], self.line.current_text)
        multiple = {"a": text_node("old"), "b": text_node("other")}
        before = copy.deepcopy(multiple)
        self.assertEqual(_replace_clip_text_prompts(multiple, self.line), 0)
        self.assertEqual(multiple, before)

    def test_partial_role_resolution_uses_metadata_for_missing_role(self):
        workflow = {"p": text_node("old"), "n": text_node("neg"), "s": sampler(negative="missing")}
        self.assertEqual(_replace_clip_text_prompts(workflow, self.line, {"negative_prompt": "neg"}), 2)
        self.assertEqual(workflow["n"]["inputs"]["text"], "blur")

    def test_shared_node_retains_negative_last_assignment_and_assignment_count(self):
        workflow = {"p": text_node("old"), "s": sampler(negative="p")}
        self.assertEqual(_replace_clip_text_prompts(workflow, self.line), 2)
        self.assertEqual(workflow["p"]["inputs"]["text"], "blur")

    def test_empty_line_prompts_are_written_as_empty_strings(self):
        workflow = {"p": text_node("old"), "n": text_node("neg"), "s": sampler()}
        self.assertEqual(_replace_clip_text_prompts(workflow, SimpleNamespace()), 2)
        self.assertEqual(workflow["p"]["inputs"]["text"], "")
        self.assertEqual(workflow["n"]["inputs"]["text"], "")

    def test_unsupported_shapes_and_malformed_nodes_are_noops(self):
        for workflow in (None, [], "invalid", {}, {"nodes": []},
                         {"a": None, "b": {"inputs": []}, "c": text_node(42)}):
            with self.subTest(workflow=workflow):
                before = copy.deepcopy(workflow)
                self.assertEqual(_replace_clip_text_prompts(workflow, self.line), 0)
                self.assertEqual(workflow, before)

    def test_debug_is_read_only_and_reports_expected_and_actual_prompts(self):
        workflow = {"p": text_node("actual"), "n": text_node("actual neg"), "s": sampler()}
        before = copy.deepcopy(workflow)
        self.assertEqual(_workflow_submitted_prompt_debug(workflow, self.line), {
            "expected_positive_prompt": self.line.current_text,
            "expected_negative_prompt": "blur",
            "positive_node_ids": ["p"], "negative_node_ids": ["n"],
            "submitted_positive_prompts": ["actual"], "submitted_negative_prompts": ["actual neg"],
        })
        self.assertEqual(workflow, before)


if __name__ == "__main__":
    unittest.main()
