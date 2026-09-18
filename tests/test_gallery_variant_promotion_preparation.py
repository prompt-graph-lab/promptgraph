"""Characterize preparation separately from caller-owned publication."""

import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import gallery_variant_promotion as promotion
from core.parser import parse_prompt
from core.project import PromptLine


def source_line(**overrides):
    fields = dict(
        id="parent", original_file_name="parent.txt", original_index=3,
        current_index=7, original_text="old", current_text="cat, (red, blue:1.2)",
        tokens=["stale"], negative_prompt="negative", node_path=["old-node"],
        deleted=True, image_path="adopted.png", generated_image_path="generated.png",
        selected_candidate_path="selected.png", generated_candidates=[{"path": "candidate.png"}],
        gallery_variants=[{"path": "variant.png"}], line_type="workbench",
        separator_label="label", separator_color="red", workbench_source_line_id="origin",
        workbench_title="title", workbench_note="note", workbench_status="draft",
    )
    fields.update(overrides)
    return PromptLine(**fields)


class PromotionPreparationTests(unittest.TestCase):
    def prepare(self, source=None, variant=None, path="variants/promoted.png", metadata=None):
        return promotion.prepare_gallery_variant_promotion_line(
            source if source is not None else source_line(),
            variant if variant is not None else {}, path, "new-line",
            metadata if metadata is not None else {},
        )

    def test_materialization_resets_publication_fields_and_preserves_source_values(self):
        source = source_line()
        source.extra = {"unknown": [1]}
        before = copy.deepcopy(source.__dict__)
        result = self.prepare(source)
        self.assertIsNot(result, source)
        self.assertEqual(source.__dict__, before)
        self.assertEqual(result.id, "new-line")
        self.assertEqual(result.original_file_name, "promoted.png")
        self.assertEqual(result.original_text, source.current_text)
        self.assertEqual(result.current_text, source.current_text)
        self.assertEqual(result.tokens, parse_prompt(source.current_text))
        self.assertIsNot(result.tokens, source.tokens)
        self.assertEqual(result.duplicated_from, "parent")
        self.assertTrue(result.edited)
        self.assertFalse(result.deleted)
        self.assertEqual(result.image_path, "variants/promoted.png")
        for field in ("generated_image_path", "selected_candidate_path", "line_type",
                      "separator_label", "separator_color", "workbench_source_line_id",
                      "workbench_title", "workbench_note", "workbench_status"):
            self.assertIsNone(getattr(result, field), field)
        for field in ("generated_candidates", "gallery_variants"):
            self.assertEqual(getattr(result, field), [])
            self.assertIsNot(getattr(result, field), getattr(source, field))
        self.assertEqual(result.original_index, 3)
        self.assertEqual(result.current_index, 7)
        self.assertEqual(result.negative_prompt, "negative")
        self.assertEqual(result.node_path, source.node_path)
        self.assertIsNot(result.node_path, source.node_path)
        self.assertEqual(result.extra, source.extra)
        self.assertIsNot(result.extra["unknown"], source.extra["unknown"])

    def test_supplied_info_is_shallow_copied_and_inputs_are_not_mutated(self):
        variant = {
            "id": 12,
            "source_generation_info": {"nested": [1]},
            "lineage_info": {"nested": [2], "parent_line_id": "stale", "extra": True},
        }
        before = copy.deepcopy(variant)
        metadata = Mock(side_effect=AssertionError("must remain lazy"))
        result = self.prepare(variant=variant, metadata=metadata)
        self.assertEqual(variant, before)
        metadata.assert_not_called()
        for field in ("source_generation_info", "lineage_info"):
            self.assertIsNot(getattr(result, field), variant[field])
            self.assertIs(getattr(result, field)["nested"], variant[field]["nested"])
        self.assertEqual(result.lineage_info, {
            "nested": [2], "extra": True, "parent_line_id": "parent",
            "lineage_kind": "gallery_variant_promote_to_route", "parent_line_index": 7,
            "parent_line_label": "parent.txt", "parent_image_path": "selected.png",
            "promoted_from_variant_id": "12", "promoted_from_variant_path": "variants/promoted.png",
            "candidate_image_path": "variants/promoted.png",
        })

    def test_empty_dicts_suppress_fallback_but_non_dicts_do_not(self):
        for source_info, lineage_info, calls in (({}, {}, 0), ({}, None, 1),
                                                ([], {}, 1), (None, False, 2)):
            with self.subTest(source=source_info, lineage=lineage_info):
                metadata = Mock(return_value={"source_prompt": "metadata prompt"})
                result = self.prepare(variant={"source_generation_info": source_info,
                                               "lineage_info": lineage_info}, metadata=metadata)
                self.assertEqual(metadata.call_count, calls)
                if isinstance(source_info, dict):
                    self.assertEqual(result.source_generation_info, {})
                else:
                    self.assertEqual(result.source_generation_info["source_prompt"], "metadata prompt")

    def test_fallbacks_evaluate_metadata_independently_in_source_then_lineage_order(self):
        source = source_line()
        first, second = {"source_prompt": "first"}, {"source": "second", "run_index": 0}
        metadata = Mock(side_effect=[first, second])
        result = self.prepare(source, metadata=metadata)
        self.assertEqual(metadata.call_count, 2)
        self.assertEqual(result.source_generation_info["source_prompt"], "first")
        self.assertEqual(result.source_generation_info["source_negative_prompt"], "negative")
        self.assertEqual(result.lineage_info["created_from"], "second")
        self.assertEqual(result.lineage_info["candidate_run_index"], 0)
        self.assertEqual(first, {"source_prompt": "first"})
        self.assertEqual(second, {"source": "second", "run_index": 0})

    def test_parent_image_priority_and_preservation_when_no_parent_image(self):
        for selected, generated, adopted, expected in (
            ("selected", "generated", "adopted", "selected"),
            ("", "generated", "adopted", "generated"),
            (None, "", "adopted", "adopted"),
            (None, None, None, "existing"),
        ):
            with self.subTest(expected=expected):
                result = self.prepare(source_line(selected_candidate_path=selected,
                    generated_image_path=generated, image_path=adopted),
                    {"lineage_info": {"parent_image_path": "existing"}})
                self.assertEqual(result.lineage_info["parent_image_path"], expected)

    def test_falsey_identity_and_label_fallbacks_do_not_clean_legacy_values(self):
        source = source_line(original_file_name="", current_index=None)
        for variant_id in (None, "", 0, False):
            with self.subTest(variant_id=variant_id):
                result = self.prepare(source, {"id": variant_id,
                    "lineage_info": {"promoted_from_variant_id": "existing"}}, path="")
                self.assertEqual(result.original_file_name, "")
                self.assertEqual(result.lineage_info["parent_line_label"], "parent")
                self.assertIsNone(result.lineage_info["parent_line_index"])
                self.assertEqual(result.lineage_info["promoted_from_variant_id"], "existing")
                self.assertEqual(result.image_path, "")

    def test_metadata_mapping_is_passed_to_both_builders_unchanged(self):
        metadata = {"nested": [1]}
        with patch.object(promotion, "build_source_generation_info_from_candidate", return_value={}) as source_builder, \
             patch.object(promotion, "build_lineage_info_from_candidate", return_value={}) as lineage_builder:
            source = source_line()
            self.prepare(source, metadata=metadata)
            for builder in (source_builder, lineage_builder):
                args = builder.call_args.args
                self.assertIs(args[0], source)
                self.assertIs(args[2], metadata)

    def test_preparation_failures_propagate_in_order_without_mutating_source(self):
        stages = ("copy", "identity", "parse", "metadata", "source", "lineage")
        for failing_stage in stages:
            with self.subTest(stage=failing_stage):
                source = source_line()
                before = copy.deepcopy(source)
                events = []
                failure = ValueError(failing_stage)
                real_deepcopy = copy.deepcopy

                def step(name, result):
                    def run(*args):
                        events.append(name)
                        if name == failing_stage:
                            raise failure
                        return result(*args) if callable(result) else result
                    return run

                with patch.object(promotion.copy, "deepcopy", step("copy", real_deepcopy)), \
                     patch.object(promotion, "parse_prompt", step("parse", parse_prompt)), \
                     patch.object(promotion, "build_source_generation_info_from_candidate", step("source", {})), \
                     patch.object(promotion, "build_lineage_info_from_candidate", step("lineage", {})):
                    with self.assertRaises(ValueError) as raised:
                        promotion.prepare_gallery_variant_promotion_line(source, {}, "x.png",
                            step("identity", "new"), step("metadata", {}))
                self.assertIs(raised.exception, failure)
                full_order = ["copy", "identity", "parse", "metadata", "source", "metadata", "lineage"]
                self.assertEqual(events, full_order[:full_order.index(failing_stage) + 1])
                self.assertEqual(source, before)

    def test_invalid_prompt_raises_before_metadata_and_leaves_source_unchanged(self):
        source = source_line(current_text=123)
        before = copy.deepcopy(source)
        metadata = Mock()
        with self.assertRaises((TypeError, AttributeError)):
            self.prepare(source, metadata=metadata)
        metadata.assert_not_called()
        self.assertEqual(source, before)


class PromotionCallerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
        cls.node = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "promote_gallery_variant_to_route")

    def namespace(self, events, source, exists=True):
        def event(name, result=None):
            def run(*args, **kwargs):
                events.append(name)
                return result
            return run
        ns = dict(
            get_line_by_id=lambda *args: source,
            _normalize_candidate_path=lambda path: path,
            _runtime_asset_path=lambda path: path,
            os=SimpleNamespace(path=SimpleNamespace(exists=event("exists", exists))),
            push_history=event("history"),
            uuid=SimpleNamespace(uuid4=event("identity", SimpleNamespace(hex="12345678abcdef"))),
            _variant_record_for_promotion=event("metadata", {}),
            prepare_gallery_variant_promotion_line=promotion.prepare_gallery_variant_promotion_line,
            _promoted_route_insert_index=event("insert_index", 0),
            _reindex_project_lines=event("reindex"),
            st=SimpleNamespace(session_state=SimpleNamespace(get=lambda key: "focus")),
            build_graph=event("rebuild", "rebuilt"),
            restore_focus_after_graph_update=event("focus"),
            sync_text_areas=event("sync"),
            save_current_project_if_possible=event("save"),
        )
        exec(compile(ast.Module(body=[self.node], type_ignores=[]), "app.py", "exec"), ns)
        return ns

    def test_external_validation_precedes_history_and_preparation(self):
        events = []
        ns = self.namespace(events, source_line(), exists=False)
        ns["prepare_gallery_variant_promotion_line"] = Mock(side_effect=AssertionError("not reached"))
        project = SimpleNamespace(prompt_lines=[])
        self.assertIsNone(ns["promote_gallery_variant_to_route"](project, "parent", {"path": "x"}))
        self.assertEqual(events, ["exists"])
        self.assertEqual(project.prompt_lines, [])

    def test_history_precedes_copy_failure_and_identity_is_still_lazy(self):
        events = []
        ns = self.namespace(events, source_line())
        project = SimpleNamespace(prompt_lines=[])
        with patch.object(promotion.copy, "deepcopy", side_effect=RuntimeError("copy failed")):
            with self.assertRaisesRegex(RuntimeError, "copy failed"):
                ns["promote_gallery_variant_to_route"](project, "parent", {"path": "x"})
        self.assertEqual(events, ["exists", "history"])
        self.assertEqual(project.prompt_lines, [])

    def test_publication_remains_in_caller_with_manage_state_switch(self):
        for manage_state in (False, True):
            with self.subTest(manage_state=manage_state):
                events = []
                ns = self.namespace(events, source_line())
                project = SimpleNamespace(prompt_lines=[])
                result = ns["promote_gallery_variant_to_route"](project, "parent", {"path": "x"},
                                                               manage_state=manage_state)
                self.assertEqual(result, "line_12345678")
                self.assertEqual(len(project.prompt_lines), 1)
                self.assertEqual(project.prompt_lines[0].id, result)
                expected = ["exists"] + (["history"] if manage_state else [])
                expected += ["identity", "metadata", "metadata", "insert_index", "reindex"]
                if manage_state:
                    expected += ["rebuild", "focus", "sync", "save"]
                    self.assertEqual(ns["st"].session_state.highlighted_line_id, result)
                    self.assertEqual(ns["st"].session_state.project, "rebuilt")
                self.assertEqual(events, expected)


if __name__ == "__main__":
    unittest.main()
