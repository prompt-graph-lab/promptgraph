import inspect
import unittest

from core.module_library_search import (
    build_global_module_search_document,
    filter_global_module_library,
    normalize_global_module_search_selection,
    normalize_module_library_search_text,
)


class _UnsupportedValue:
    pass


class _BrokenString:
    def __str__(self):
        raise ValueError("cannot stringify")


class _UnexpectedBrokenString:
    calls = 0

    def __str__(self):
        type(self).calls += 1
        raise RuntimeError("unexpected stringify failure")


class GlobalModuleLibrarySearchTests(unittest.TestCase):
    def setUp(self):
        self.library = {
            "milku_character": {
                "category": "Original Character",
                "body": (
                    "dark-skinned girl, rainbow hair, high twintails"
                ),
                "description": "Original heroine",
                "notes": "Milk-themed design",
                "attribute_groups": {
                    "hair_color": {
                        "name": "Hair Color",
                        "tokens": ["rainbow hair"],
                        "variants": [
                            {"label": "Sunset Gradient"},
                            {"label": "Blue Streak"},
                        ],
                    }
                },
            },
            "tomato_character": {
                "category": "Original Character",
                "body": "white hair, red theme",
                "description": "Tomato heroine",
            },
            "reimu_hakurei": {
                "category": "Touhou",
                "body": "shrine maiden, red ribbon",
                "notes": "博麗霊夢",
            },
            "sunset_beach": {
                "category": "Location",
                "body": "sunset, beach, orange sky",
            },
        }

    def test_normalization_is_nfkc_casefolded_and_whitespace_stable(self):
        self.assertEqual(
            normalize_module_library_search_text(
                "  ＭＩＬＫＵ\tRainbow\n  Hair  "
            ),
            "milku rainbow hair",
        )
        self.assertEqual(
            normalize_module_library_search_text("博麗　霊夢"),
            "博麗 霊夢",
        )
        self.assertEqual(normalize_module_library_search_text(None), "")
        self.assertEqual(normalize_module_library_search_text(123), "123")
        self.assertEqual(
            normalize_module_library_search_text(_BrokenString()),
            "",
        )
        self.assertEqual(
            normalize_module_library_search_text(_UnexpectedBrokenString()),
            "",
        )

    def test_name_category_content_and_description_fields_match(self):
        cases = {
            "milku": ["milku_character"],
            "ORIGINAL": ["milku_character", "tomato_character"],
            "rainbow": ["milku_character"],
            "heroine": ["milku_character", "tomato_character"],
            "milk-themed": ["milku_character"],
            "博麗": ["reimu_hakurei"],
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                result = filter_global_module_library(
                    self.library,
                    query=query,
                )
                self.assertEqual(result["matched_names"], expected)

    def test_attribute_group_and_variant_labels_are_searchable(self):
        self.assertEqual(
            filter_global_module_library(
                self.library,
                query="hair color",
            )["matched_names"],
            ["milku_character"],
        )
        self.assertEqual(
            filter_global_module_library(
                self.library,
                query="sunset gradient",
            )["matched_names"],
            ["milku_character"],
        )

    def test_multiple_terms_are_order_independent_and_use_and_matching(self):
        first = filter_global_module_library(
            self.library,
            query="milku rainbow",
        )
        second = filter_global_module_library(
            self.library,
            query="rainbow milku",
        )
        no_match = filter_global_module_library(
            self.library,
            query="rainbow tomato",
        )

        self.assertEqual(first["matched_names"], ["milku_character"])
        self.assertEqual(second["matched_names"], ["milku_character"])
        self.assertEqual(no_match["matched_names"], [])

    def test_partial_substring_matches_without_regex_interpretation(self):
        self.assertEqual(
            filter_global_module_library(
                self.library,
                query="twin",
            )["matched_names"],
            ["milku_character"],
        )
        self.assertEqual(
            filter_global_module_library(
                self.library,
                query=".*",
            )["matched_names"],
            [],
        )
        literal_library = {
            "literal": {"body": "uses .* as plain prompt text"}
        }
        self.assertEqual(
            filter_global_module_library(
                literal_library,
                query=".*",
            )["matched_names"],
            ["literal"],
        )

    def test_empty_query_and_filtered_results_preserve_relative_order(self):
        empty = filter_global_module_library(self.library)
        filtered = filter_global_module_library(
            self.library,
            query="red",
        )

        self.assertEqual(
            empty["matched_names"],
            list(self.library),
        )
        self.assertEqual(
            filtered["matched_names"],
            ["tomato_character", "reimu_hakurei"],
        )

    def test_category_and_query_are_combined_with_and(self):
        result = filter_global_module_library(
            self.library,
            query="red",
            category="Original Character",
        )
        none = filter_global_module_library(
            self.library,
            query="rainbow",
            category="Touhou",
        )
        all_categories = filter_global_module_library(
            self.library,
            query="red",
            category="All",
        )

        self.assertEqual(result["matched_names"], ["tomato_character"])
        self.assertEqual(none["matched_names"], [])
        self.assertEqual(
            all_categories["matched_names"],
            ["tomato_character", "reimu_hakurei"],
        )

    def test_nested_malformed_and_long_values_are_fail_soft(self):
        cyclic = {}
        cyclic["self"] = cyclic
        malformed = {
            "primitive": "simple prompt",
            "none": None,
            "nested": {
                "lists": [
                    {"label": "Nested Label"},
                    ("tuple value",),
                    {"set value"},
                ]
            },
            "cycle": cyclic,
            "binary": b"rainbow binary",
            "unsupported": _UnsupportedValue(),
            "very_long": [f"token-{index}" for index in range(5000)],
        }
        result = filter_global_module_library(
            malformed,
            query="token-4999",
        )

        self.assertEqual(result["matched_names"], ["very_long"])
        self.assertEqual(
            filter_global_module_library(
                malformed,
                query="nested label",
            )["matched_names"],
            ["nested"],
        )
        self.assertEqual(
            filter_global_module_library(
                malformed,
                query="rainbow binary",
            )["matched_names"],
            [],
        )
        _UnexpectedBrokenString.calls = 0
        self.assertEqual(
            filter_global_module_library(
                {_UnexpectedBrokenString(): {"body": "ignored"}},
                query="ignored",
            )["matched_names"],
            [],
        )
        self.assertEqual(_UnexpectedBrokenString.calls, 0)

    def test_internal_paths_timestamps_and_checksums_are_not_searchable(self):
        document = build_global_module_search_document(
            "safe_module",
            {
                "body": "visible prompt",
                "source_path": r"C:\private\library\secret.json",
                "created_at": "2026-07-31T00:00:00Z",
                "checksum": "deadbeef",
                "schema_version": "v99",
                "runtime_state": "temporary hidden state",
                "private_notes": "private searchable leak",
                "runtime_cache": {"label": "runtime cache leak"},
            },
        )

        self.assertIn("visible prompt", document)
        for excluded in (
            "private",
            "2026-07-31",
            "deadbeef",
            "v99",
            "temporary hidden",
            "private searchable leak",
            "runtime cache leak",
        ):
            self.assertNotIn(excluded, document)

    def test_selection_normalization_never_keeps_hidden_module(self):
        self.assertEqual(
            normalize_global_module_search_selection(
                "visible_b",
                ["visible_a", "visible_b"],
            ),
            "visible_b",
        )
        self.assertEqual(
            normalize_global_module_search_selection(
                "hidden",
                ["visible_a", "visible_b"],
            ),
            "visible_a",
        )
        self.assertEqual(
            normalize_global_module_search_selection("hidden", []),
            "",
        )

    def test_search_is_memory_only_without_persistence_or_discovery_calls(self):
        source = inspect.getsource(
            __import__(
                "core.module_library_search",
                fromlist=["module_library_search"],
            )
        )
        for forbidden in (
            "os.walk",
            "glob(",
            "import glob",
            "open(",
            "json.",
            "sqlite",
            "discover_animadex",
            "hashlib",
            "requests",
            "save_project",
            "save_global_module",
            "Image.open",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
