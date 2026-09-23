import copy
import unittest
from unittest.mock import patch

from core.comfy_generation_prompt import prepare_generation_injection_line
from core.project import PromptLine


class ComfyGenerationPromptTests(unittest.TestCase):
    def line(self, tokens):
        return PromptLine(
            "line", "source.txt", 0, 0, "original", "stored prompt", tokens,
            negative_prompt="blur", generated_candidates=[{"path": "candidate.png"}],
            source_generation_info={"unknown": ["preserved"]},
        )

    def test_real_expansion_preserves_source_and_detaches_all_fields(self):
        line = self.line(["<mod:character>", "smile", "smile", "<mod:hidden>red</mod:hidden>"])
        before = copy.deepcopy(line)
        result = prepare_generation_injection_line(
            line, {"hidden"}, fallback_prompt="fallback",
            module_library={"character": {"body": "blue hair"}},
        )
        self.assertEqual(result.current_text, "blue hair, smile, smile")
        self.assertEqual(line, before)
        self.assertIsNot(result, line)
        self.assertEqual(result.tokens, line.tokens)
        self.assertIsNot(result.tokens, line.tokens)
        self.assertEqual(result.negative_prompt, "blur")
        result.generated_candidates[0]["path"] = "changed"
        result.source_generation_info["unknown"].append("changed")
        self.assertEqual(line, before)

    def test_empty_expansion_uses_existing_fallback_semantics(self):
        for fallback, expected in [("fallback", "fallback"), ("", ""), (None, "")]:
            with self.subTest(fallback=fallback):
                result = prepare_generation_injection_line(
                    self.line([]), set(), fallback_prompt=fallback, module_library={},
                )
                self.assertEqual(result.current_text, expected)

    def test_expansion_precedes_copy_and_preserves_argument_identity(self):
        line = self.line(["smile"])
        disabled, library, events = set(), {}, []
        original_copy = copy.deepcopy

        def expand(value, passed_disabled, **kwargs):
            self.assertIs(value, line)
            self.assertIs(passed_disabled, disabled)
            self.assertIs(kwargs["module_library"], library)
            self.assertIsNone(kwargs["fallback_prompt"])
            events.append("expand")
            return ["one", "one", "青"]

        def clone(value):
            events.append("copy")
            return original_copy(value)

        with patch("core.comfy_generation_prompt.get_active_tokens", side_effect=expand), \
                patch("core.comfy_generation_prompt.copy.deepcopy", side_effect=clone):
            result = prepare_generation_injection_line(
                line, disabled, fallback_prompt=None, module_library=library,
            )
        self.assertEqual(events, ["expand", "copy"])
        self.assertEqual(result.current_text, "one, one, 青")

    def test_expansion_exception_propagates_before_copy(self):
        failure = RuntimeError("expansion failed")
        with patch("core.comfy_generation_prompt.get_active_tokens", side_effect=failure), \
                patch("core.comfy_generation_prompt.copy.deepcopy") as clone:
            with self.assertRaises(RuntimeError) as caught:
                prepare_generation_injection_line(
                    self.line([]), None, fallback_prompt=None, module_library={},
                )
        self.assertIs(caught.exception, failure)
        clone.assert_not_called()


if __name__ == "__main__":
    unittest.main()
