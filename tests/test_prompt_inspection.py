import unittest

from core.prompt_inspection import (
    _prompt_token_diff,
    detect_novelai_syntax_fragments,
    extract_module_reference_names_from_text,
    get_structural_stats,
)


class PromptInspectionTests(unittest.TestCase):
    def test_diff_preserves_duplicate_counts_order_and_case(self):
        self.assertEqual(
            _prompt_token_diff("a, b, a, C", "a, c, b, b"),
            {
                "source_tokens": ["a", "b", "a", "C"],
                "current_tokens": ["a", "c", "b", "b"],
                "removed": ["a", "C"],
                "added": ["c", "b"],
                "shared_count": 2,
            },
        )

    def test_diff_reordering_is_not_an_addition_or_removal(self):
        diff = _prompt_token_diff("青い髪, smile", "smile, 青い髪")
        self.assertEqual((diff["added"], diff["removed"], diff["shared_count"]), ([], [], 2))

    def test_diff_keeps_literal_comma_semantics_inside_weighted_groups(self):
        # This display diff deliberately does not use the syntax-aware parser.
        diff = _prompt_token_diff("(red, blue:1.2), , sky", "(red, green:1.2), sky")
        self.assertEqual(diff["source_tokens"], ["(red", "blue:1.2)", "sky"])
        self.assertEqual(diff["removed"], ["blue:1.2)"])
        self.assertEqual(diff["added"], ["green:1.2)"])

    def test_empty_diagnostics(self):
        for text in (None, "", " , , "):
            with self.subTest(text=text):
                self.assertEqual(extract_module_reference_names_from_text(text), [])
                self.assertEqual(detect_novelai_syntax_fragments(text), [])
                self.assertEqual(_prompt_token_diff(text, "")["shared_count"], 0)

    def test_module_references_include_closing_and_inline_names_in_first_seen_order(self):
        text = "<mod:衣装>, red, </mod:衣装>, <mod:face>smile</mod:face>, <mod:Face>"
        self.assertEqual(extract_module_reference_names_from_text(text), ["衣装", "face", "Face"])

    def test_novelai_fragments_are_diagnostics_not_syntax_conversion(self):
        text = "1.2::blue, normal, {a, b::c}, 1.2::blue, X::Y, x::y"
        self.assertEqual(
            detect_novelai_syntax_fragments(text),
            ["1.2::blue", "{a, b::c}", "X::Y", "x::y"],
        )

    def test_structural_stats_empty_and_identical(self):
        self.assertEqual(get_structural_stats("", ""), {
            "token_delta": 0, "mod_count": 0, "has_weights": False, "change_ratio": 0,
        })
        self.assertEqual(get_structural_stats("a, b", "a, b")["change_ratio"], 0)
        self.assertEqual(get_structural_stats("", "a")["change_ratio"], 0)

    def test_structural_stats_use_display_tokens_and_raw_module_markers(self):
        stats = get_structural_stats("smile", "<mod:face>, (smile:1.2), </mod:face>, sky")
        self.assertEqual(stats, {
            "token_delta": 1, "mod_count": 1, "has_weights": True, "change_ratio": 1.0,
        })


if __name__ == "__main__":
    unittest.main()
