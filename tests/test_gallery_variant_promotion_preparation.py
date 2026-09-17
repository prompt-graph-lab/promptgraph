import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import gallery_variant_promotion as promotion
from core.parser import parse_prompt
from core.project import PromptLine


def source_line():
    return PromptLine(
        id="parent", original_file_name="parent.png", original_index=2,
        current_index=4, original_text="old", current_text="cat, blue sky",
        tokens=["stale"], negative_prompt="blur", deleted=True,
        selected_candidate_path="selected.png", generated_image_path="generated.png",
        image_path="original.png", generated_candidates=[{"path": "candidate.png"}],
        gallery_variants=[{"path": "variant.png"}], node_path=["node"],
        line_type="workbench", separator_label="route", separator_color="red",
        workbench_source_line_id="other", workbench_title="title",
        workbench_note="note", workbench_status="draft",
    )


class PrepareGalleryVariantPromotionTests(unittest.TestCase):
    def test_preparation_resets_fields_and_preserves_copy_and_alias_contracts(self):
        source = source_line()
        variant = {
            "id": "v1", "source_generation_info": {"nested": [1]},
            "lineage_info": {"nested": [2], "custom": "keep"},
        }
        before = copy.deepcopy((source, variant))
        metadata = Mock(side_effect=AssertionError("must stay lazy"))
        result = promotion.prepare_gallery_variant_promotion_line(
            source, variant, "variant.png", "new", metadata,
        )
        self.assertIsNot(result, source)
        self.assertEqual((source, variant), before)
        self.assertEqual(result.id, "new")
        self.assertEqual(result.original_file_name, "variant.png")
        self.assertEqual(result.original_text, source.current_text)
        self.assertEqual(result.current_text, source.current_text)
        self.assertEqual(result.tokens, parse_prompt(source.current_text))
        self.assertEqual(result.duplicated_from, "parent")
        self.assertTrue(result.edited)
        self.assertFalse(result.deleted)
        self.assertEqual(result.image_path, "variant.png")
        for field in ("generated_image_path", "selected_candidate_path", "line_type",
                      "separator_label", "separator_color", "workbench_source_line_id",
                      "workbench_title", "workbench_note", "workbench_status"):
            self.assertIsNone(getattr(result, field), field)
        self.assertEqual(result.generated_candidates, [])
        self.assertEqual(result.gallery_variants, [])
        self.assertEqual(result.negative_prompt, "blur")
        self.assertEqual(result.current_index, 4)
        self.assertEqual(result.node_path, source.node_path)
        self.assertIsNot(result.node_path, source.node_path)
        for field in ("source_generation_info", "lineage_info"):
            self.assertIsNot(getattr(result, field), variant[field])
            self.assertIs(getattr(result, field)["nested"], variant[field]["nested"])
        self.assertEqual(result.lineage_info, {
            "nested": [2], "custom": "keep", "lineage_kind": "gallery_variant_promote_to_route",
            "parent_line_id": "parent", "parent_line_index": 4,
            "parent_line_label": "parent.png", "parent_image_path": "selected.png",
            "promoted_from_variant_id": "v1", "promoted_from_variant_path": "variant.png",
            "candidate_image_path": "variant.png",
        })
        metadata.assert_not_called()

    def test_falsey_values_and_empty_dicts_do_not_trigger_metadata_fallback(self):
        source = source_line()
        source.original_file_name = ""
        source.current_index = None
        source.selected_candidate_path = ""
        source.generated_image_path = None
        source.image_path = None
        variant = {"id": 0, "source_generation_info": {},
                   "lineage_info": {"parent_image_path": "retained.png", "promoted_from_variant_id": "old"}}
        result = promotion.prepare_gallery_variant_promotion_line(
            source, variant, "", "", Mock(side_effect=AssertionError),
        )
        self.assertEqual(result.id, "")
        self.assertEqual(result.original_file_name, "")
        self.assertEqual(result.source_generation_info, {})
        self.assertEqual(result.lineage_info["parent_line_label"], "parent")
        self.assertIsNone(result.lineage_info["parent_line_index"])
        self.assertEqual(result.lineage_info["parent_image_path"], "retained.png")
        self.assertEqual(result.lineage_info["promoted_from_variant_id"], "old")

    def test_fallback_metadata_is_requested_separately_and_in_order(self):
        source = source_line()
        variant = {"source_generation_info": None, "lineage_info": []}
        before = copy.deepcopy((source, variant))
        events = []
        records = [{"prompt_text": "metadata prompt"}, {"source": "second record"}]
        def metadata(value):
            self.assertIs(value, variant)
            events.append("metadata")
            return records[len(events) - 1]
        result = promotion.prepare_gallery_variant_promotion_line(source, variant, "v.png", "new", metadata)
        self.assertEqual(events, ["metadata", "metadata"])
        self.assertEqual(result.source_generation_info["source_prompt"], "metadata prompt")
        self.assertEqual(result.lineage_info["created_from"], "second record")
        self.assertEqual((source, variant), before)

    def test_failures_propagate_before_later_preparation(self):
        for stage in ("copy", "id", "parse", "normalize", "metadata", "source", "lineage"):
            with self.subTest(stage=stage):
                source = source_line()
                variant = {}
                before = copy.deepcopy((source, variant))
                events = []
                failure = RuntimeError(stage)
                clone = copy.deepcopy(source)
                def step(name, value):
                    def run(*args):
                        events.append(name)
                        if name == stage:
                            raise failure
                        return value
                    return run
                metadata = Mock(side_effect=step("metadata", {}))
                with patch.object(promotion.copy, "deepcopy", step("copy", clone)), \
                     patch.object(promotion, "parse_prompt", step("parse", [])), \
                     patch.object(promotion, "normalize_candidate_line_for_main_sequence", step("normalize", clone)), \
                     patch.object(promotion, "build_source_generation_info_from_candidate", step("source", {})), \
                     patch.object(promotion, "build_lineage_info_from_candidate", step("lineage", {})):
                    with self.assertRaises(RuntimeError) as raised:
                        promotion.prepare_gallery_variant_promotion_line(
                            source, variant, "v.png", step("id", "new"), metadata,
                        )
                self.assertIs(raised.exception, failure)
                expected = ["copy", "id", "parse", "normalize", "metadata", "source", "metadata", "lineage"]
                self.assertEqual(events, expected[:expected.index(stage) + 1])
                self.assertEqual((source, variant), before)

    def test_builder_results_and_normalized_clone_are_returned_without_recopies(self):
        clone = source_line()
        source_info, lineage_info = {}, {}
        with patch.object(promotion.copy, "deepcopy", return_value=clone), \
             patch.object(promotion, "build_source_generation_info_from_candidate", return_value=source_info), \
             patch.object(promotion, "build_lineage_info_from_candidate", return_value=lineage_info):
            result = promotion.prepare_gallery_variant_promotion_line(source_line(), {}, "v.png", "new", lambda v: {})
        self.assertIs(result, clone)
        self.assertIs(result.source_generation_info, source_info)
        self.assertIs(result.lineage_info, lineage_info)
        self.assertIsNone(result.line_type)


class PromotionCallerOwnershipTests(unittest.TestCase):
    def namespace(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "promote_gallery_variant_to_route")
        source = source_line()
        events = []
        prepared = SimpleNamespace(id="new")
        state = SimpleNamespace(get=lambda key: "focused")
        namespace = {
            "os": SimpleNamespace(path=SimpleNamespace(exists=lambda path: events.append("exists") or True)),
            "get_line_by_id": lambda *args: source,
            "_normalize_candidate_path": lambda path: events.append("normalize path") or path,
            "_runtime_asset_path": lambda path: events.append("resolve") or path,
            "push_history": lambda: events.append("history"),
            "uuid": SimpleNamespace(uuid4=lambda: events.append("uuid") or SimpleNamespace(hex="123456789")),
            "_variant_record_for_promotion": Mock(),
            "_promoted_route_insert_index": lambda *args: events.append("insert index") or 0,
            "_reindex_project_lines": lambda project: events.append("reindex"),
            "build_graph": lambda project: events.append("graph") or project,
            "restore_focus_after_graph_update": lambda value: events.append("focus"),
            "sync_text_areas": lambda: events.append("sync"),
            "save_current_project_if_possible": lambda reason: events.append("save"),
            "st": SimpleNamespace(session_state=state),
        }
        def prepare(actual_source, variant, path, new_id, metadata):
            events.append("prepare")
            self.assertIs(actual_source, source)
            self.assertIs(metadata, namespace["_variant_record_for_promotion"])
            self.assertEqual(new_id(), "line_12345678")
            return prepared
        namespace["prepare_gallery_variant_promotion_line"] = prepare
        exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)
        return namespace, events, prepared, state

    def test_caller_publishes_exact_prepared_object_and_owns_lifecycle(self):
        for manage_state in (True, False):
            with self.subTest(manage_state=manage_state):
                ns, events, prepared, state = self.namespace()
                project = SimpleNamespace(prompt_lines=[])
                self.assertEqual(ns["promote_gallery_variant_to_route"](
                    project, "parent", {"path": "v.png"}, manage_state=manage_state), "new")
                self.assertIs(project.prompt_lines[0], prepared)
                expected = ["normalize path", "resolve", "exists"]
                if manage_state:
                    expected += ["history"]
                expected += ["prepare", "uuid", "insert index", "reindex"]
                if manage_state:
                    expected += ["graph", "focus", "sync", "save"]
                    self.assertIs(state.project, project)
                    self.assertEqual(state.highlighted_line_id, "new")
                    self.assertEqual(state.gallery_expanded_line_id, "new")
                self.assertEqual(events, expected)

    def test_validation_and_preparation_failure_precede_publication(self):
        ns, events, _, _ = self.namespace()
        project = SimpleNamespace(prompt_lines=[])
        ns["os"].path.exists = lambda path: False
        self.assertIsNone(ns["promote_gallery_variant_to_route"](project, "parent", {"path": "missing"}))
        self.assertEqual(events, ["normalize path", "resolve"])
        ns["os"].path.exists = lambda path: True
        failure = ValueError("preparation failed")
        ns["prepare_gallery_variant_promotion_line"] = Mock(side_effect=failure)
        events.clear()
        with self.assertRaises(ValueError) as raised:
            ns["promote_gallery_variant_to_route"](project, "parent", {"path": "v.png"})
        self.assertIs(raised.exception, failure)
        self.assertEqual(events, ["normalize path", "resolve", "history"])
        self.assertEqual(project.prompt_lines, [])


if __name__ == "__main__":
    unittest.main()
