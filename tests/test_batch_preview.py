"""Deterministic contracts for batch-edit preview strings, without Streamlit."""
import copy
import unittest

from core import batch_preview

F = vars(batch_preview)

class LiteralTests(unittest.TestCase):
    def test_literal_escaping_nonoverlap_and_empty(self):
        f = F["_highlight_literal_matches"]
        self.assertEqual(f("<aaa>&", "aa", "custom"), "&lt;<span style='custom'>aa</span>a&gt;&amp;")
        self.assertEqual(f("<&", None), "&lt;&amp;")
        self.assertEqual(f("ABC", "abc"), "ABC")
        with self.assertRaises(AttributeError):
            f(None, "x")


class TokenTests(unittest.TestCase):
    def test_query_modes_and_weight(self):
        f = F["_batch_token_query"]
        self.assertEqual(f(" (sky:1.2) ", "exact_token"), "sky")
        self.assertEqual(f("sky, blue", "exact_token"), "")
        self.assertEqual(f(" sky, blue ", "contains_token"), "sky, blue")
        self.assertEqual(f(None, "exact_token"), "")

    def test_token_matching_and_markers(self):
        f = F["_highlight_token_matches"]
        self.assertEqual(f("<mod:sky>, (sky:1.2), Sky", "sky", "exact_token"), "&lt;mod:sky&gt;, <span style='background-color:#fff3a3;'>(sky:1.2)</span>, Sky")
        self.assertEqual(f("sky", "sk", "contains_token"), "<span style='background-color:#fff3a3;'><span style='background-color:#ffb3b3;color:#7a0000;'>sk</span>y</span>")
        self.assertEqual(f("sky", "sk", "unknown"), "<span style='background-color:#fff3a3;'>sky</span>")
        self.assertEqual(f("a,  b &", "", "exact_token"), "a,  b &amp;")

    def test_replacement_highlights_all_matching_bases(self):
        f = F["_highlight_replace_result_tokens"]
        span = "<span style='background-color:#cfe8ff;color:#003b73;'>{}</span>"
        self.assertEqual(f("<mod:sky>, sky, (sky:2), Sky", "(sky:1.2)"), "&lt;mod:sky&gt;, " + span.format("sky") + ", " + span.format("(sky:2)") + ", Sky")
        self.assertEqual(f("a,  b &", "a, b"), "a,  b &amp;")
        self.assertEqual(f("<&", None), "&lt;&amp;")


class DuplicateTests(unittest.TestCase):
    def test_status_styles_order_and_no_mutation(self):
        marks = [{"token": "<&", "status": "remove"}, {"token": "a", "status": "preserve"}, {"token": "a", "status": "other"}]
        before = copy.deepcopy(marks)
        self.assertEqual(F["_highlight_duplicate_tokens"](marks), "<span style='background-color:#ffd6a5;color:#7a0000;border:1px solid #ff9f1c;'>&lt;&amp;</span>, <span style='background-color:#d8f3dc;color:#064e3b;border:1px solid #95d5b2;'>a</span>, a")
        self.assertEqual(marks, before)
        self.assertEqual(F["_highlight_duplicate_tokens"]([]), "")
        with self.assertRaises(KeyError):
            F["_highlight_duplicate_tokens"]([{"token": "x"}])


class SnippetTests(unittest.TestCase):
    def test_shortening_preserves_legacy_lengths_and_centering(self):
        f = F["_shorten_preview_text"]
        self.assertEqual(f(None), "")
        self.assertEqual(f("abc", max_chars=3), "abc")
        self.assertEqual(f("abcdefghij", max_chars=5), "abcd...")
        self.assertEqual(f("abcdefghij", "G", 4), "... efgh ...")
        self.assertEqual(f("abcdefghij", "j", 4), "... ghij")
        self.assertEqual(f("abc", max_chars=0), "ab...")

    def test_focus_precedence_and_first_removed_mark(self):
        f = F["_batch_preview_focus_text"]
        example = {"duplicate_token_marks": [{"status": "preserve", "token": "a"}, {"status": "remove"}, {"status": "remove", "token": "b"}]}
        before = copy.deepcopy(example)
        for operation in ("replace", "remove"):
            self.assertIs(f(example, operation, example, "edit"), example)
        self.assertEqual(f(example, "add", "search", "edit"), "edit")
        self.assertEqual(f(example, "remove_duplicates", "search", "edit"), "")
        self.assertEqual(f({}, "unknown", "search", "edit"), "")
        self.assertEqual(example, before)

    def test_removed_marker_first_only_and_unused_after(self):
        f = F["_removed_marker_preview"]
        self.assertEqual(f(" sky sky ", object(), " sky ", "literal"), " <removed: sky> sky ")
        self.assertEqual(f("<mod:sky>, sky, sky", None, "sky", "exact_token"), "<mod:sky>, <removed: sky>, sky")
        self.assertEqual(f("blue sky, sky", None, "sk", "contains_token"), "<removed: blue sky>, sky")
        self.assertEqual(f("a,  b", None, "", "exact_token"), "a,  b")
        self.assertEqual(f("a,  b", None, "z", "exact_token"), "a, b")


if __name__ == "__main__":
    unittest.main()
