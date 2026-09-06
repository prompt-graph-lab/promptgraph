import copy
import unittest

from core.module_token_rules import (
    _dedupe_prompt_tokens,
    _format_module_rule_text,
    _module_body_from_tokens,
    _module_tokens_from_body,
    _parse_module_rule_text,
    _prompt_token_match_key,
    _prompt_token_match_key_set,
)


class ModuleTokenRulesTests(unittest.TestCase):
    def test_rule_text_accepts_lines_commas_and_grouped_commas(self):
        self.assertEqual(
            _parse_module_rule_text(" 青い髪, Smile\r\nsmile, (red, blue:1.2)\n青い髪, sky "),
            ["青い髪", "Smile", "(red, blue:1.2)", "sky"],
        )

    def test_rule_deduplication_is_literal_not_weight_normalized(self):
        self.assertEqual(_parse_module_rule_text("Smile, (smile:1.2), SMILE, (Smile:1.2)"),
                         ["Smile", "(smile:1.2)"])

    def test_case_matching_keeps_lower_rather_than_casefold_semantics(self):
        self.assertEqual(_parse_module_rule_text("Straße, STRASSE, straße"), ["Straße", "STRASSE"])
        self.assertEqual(_dedupe_prompt_tokens(["Straße", "STRASSE", "straße"]), ["Straße", "STRASSE"])

    def test_empty_inputs(self):
        for value in (None, "", " , \n, "):
            with self.subTest(value=value):
                self.assertEqual(_parse_module_rule_text(value), [])
                self.assertEqual(_module_tokens_from_body(value), [])
        for value in (None, []):
            self.assertEqual(_format_module_rule_text(value), "")
            self.assertEqual(_module_body_from_tokens(value), "")
            self.assertEqual(_dedupe_prompt_tokens(value), [])
            self.assertEqual(_prompt_token_match_key_set(value), set())

    def test_formatting_preserves_order_and_duplicates(self):
        tokens = [" Smile ", "", "青い髪", "Smile", "  "]
        self.assertEqual(_format_module_rule_text(tokens), "Smile\n青い髪\nSmile")
        self.assertEqual(_module_body_from_tokens(tokens), "Smile, 青い髪, Smile")

    def test_body_parsing_preserves_groups_module_markers_and_duplicates(self):
        body = "<mod:face>, (red, blue:1.2), </mod:face>, smile, smile"
        self.assertEqual(_module_tokens_from_body(body),
                         ["<mod:face>", "(red, blue:1.2)", "</mod:face>", "smile", "smile"])
        self.assertEqual(_module_body_from_tokens(_module_tokens_from_body(body)), body)

    def test_match_keys_use_parser_base_word_without_changing_display_text(self):
        for token in (" Smile ", "(Smile:1.2)", "<mod:face>(Smile:1.2)</mod:face>"):
            with self.subTest(token=token):
                self.assertEqual(_prompt_token_match_key(token), "smile")
        self.assertEqual(_prompt_token_match_key("(red, blue:1.2)"), "red, blue")

    def test_match_keys_fall_back_to_structural_markers_and_unrecognized_weights(self):
        self.assertEqual(_prompt_token_match_key("<mod:Face>"), "<mod:face>")
        self.assertEqual(_prompt_token_match_key("</mod:Face>"), "</mod:face>")
        self.assertEqual(_prompt_token_match_key("(Smile:bad)"), "(smile:bad)")
        self.assertEqual(_prompt_token_match_key(None), "")

    def test_inspector_deduplication_retains_first_display_spelling(self):
        self.assertEqual(
            _dedupe_prompt_tokens([" (Smile:1.2) ", "smile", "(smile:0.8)", "blue", "BLUE", ""]),
            ["(Smile:1.2)", "blue"],
        )

    def test_match_key_set_ignores_empty_and_collapses_weight_variants(self):
        self.assertEqual(_prompt_token_match_key_set(["", " ", "Smile", "(smile:1.2)", "青い髪"]),
                         {"smile", "青い髪"})

    def test_helpers_do_not_modify_input_sequences(self):
        tokens = [" Smile ", "smile", "(Smile:1.2)", "青い髪"]
        before = copy.deepcopy(tokens)
        for helper in (_format_module_rule_text, _module_body_from_tokens,
                       _dedupe_prompt_tokens, _prompt_token_match_key_set):
            helper(tokens)
            self.assertEqual(tokens, before)


if __name__ == "__main__":
    unittest.main()
