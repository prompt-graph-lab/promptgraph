"""Unpublished promotion preparation and the retained app lifecycle boundary."""

import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import gallery_variant_promotion as promotion
from core.parser import parse_prompt
from core.project import Project, PromptLine


def _line(**fields):
    values = dict(
        id="parent", original_file_name="parent.png", original_index=2,
        current_index=3, original_text="old", current_text="blue hair, smile",
        tokens=["stale"], negative_prompt="blur", deleted=True,
        image_path="parent.png", generated_image_path="generated.png",
        selected_candidate_path="selected.png",
        generated_candidates=[{"path": "candidate.png"}],
        gallery_variants=[{"id": "variant_1", "path": "variant.png"}],
        line_type="workbench", separator_label="label", separator_color="red",
        workbench_source_line_id="source", workbench_title="title",
        workbench_note="note", workbench_status="draft",
    )
    values.update(fields)
    return PromptLine(**values)


class GalleryVariantPromotionPreparationTests(unittest.TestCase):
    def test_prepared_copy_resets_main_sequence_and_preserves_aliasing_contract(self):
        source = _line()
        source.extra = {"unknown": [1]}
        variant = source.gallery_variants[0]
        variant["source_generation_info"] = {"settings": {"seed": 4}}
        variant["lineage_info"] = {"unknown": [2], "parent_image_path": "old.png"}
        before = copy.deepcopy(source.__dict__)
        metadata = Mock(side_effect=AssertionError("metadata must stay lazy"))

        result = promotion.prepare_gallery_variant_promotion_line(
            source, variant, "variants/new.png", "new", metadata,
        )

        self.assertIsNot(result, source)
        self.assertEqual(before, source.__dict__)
        self.assertEqual("new", result.id)
        self.assertEqual("new.png", result.original_file_name)
        self.assertEqual(source.current_text, result.original_text)
        self.assertEqual(source.current_text, result.current_text)
        self.assertEqual(parse_prompt(source.current_text), result.tokens)
        self.assertIsNot(result.tokens, source.tokens)
        self.assertEqual("parent", result.duplicated_from)
        self.assertTrue(result.edited)
        self.assertFalse(result.deleted)
        self.assertEqual("variants/new.png", result.image_path)
        for field in (
            "generated_image_path", "selected_candidate_path", "line_type",
            "separator_label", "separator_color", "workbench_source_line_id",
            "workbench_title", "workbench_note", "workbench_status",
        ):
            self.assertIsNone(getattr(result, field), field)
        for field in ("generated_candidates", "gallery_variants"):
            self.assertEqual([], getattr(result, field))
            self.assertIsNot(getattr(result, field), getattr(source, field))
        self.assertIsNot(result.generated_candidates, result.gallery_variants)
        self.assertEqual(source.extra, result.extra)
        self.assertIsNot(source.extra["unknown"], result.extra["unknown"])
        self.assertEqual("blur", result.negative_prompt)
        self.assertEqual((2, 3), (result.original_index, result.current_index))
        self.assertIsNot(result.source_generation_info, variant["source_generation_info"])
        self.assertIs(result.source_generation_info["settings"], variant["source_generation_info"]["settings"])
        self.assertIsNot(result.lineage_info, variant["lineage_info"])
        self.assertIs(result.lineage_info["unknown"], variant["lineage_info"]["unknown"])
        self.assertEqual("selected.png", result.lineage_info["parent_image_path"])
        self.assertEqual("variant_1", result.lineage_info["promoted_from_variant_id"])
        self.assertEqual("gallery_variant_promote_to_route", result.lineage_info["lineage_kind"])
        self.assertEqual("parent", result.lineage_info["parent_line_id"])
        self.assertEqual(3, result.lineage_info["parent_line_index"])
        self.assertEqual("parent.png", result.lineage_info["parent_line_label"])
        self.assertEqual("variants/new.png", result.lineage_info["candidate_image_path"])
        self.assertEqual("variants/new.png", result.lineage_info["promoted_from_variant_path"])
        metadata.assert_not_called()

    def test_falsey_values_and_empty_provenance_dicts_keep_legacy_defaults(self):
        source = _line(original_file_name="", current_text="", selected_candidate_path="",
                       generated_image_path=None, image_path=None, current_index=None)
        variant = {"id": 0, "source_generation_info": {},
                   "lineage_info": {"parent_image_path": "retained", "promoted_from_variant_id": "retained"}}
        result = promotion.prepare_gallery_variant_promotion_line(source, variant, "", "", Mock())
        self.assertEqual("", result.id)
        self.assertEqual("", result.original_file_name)
        self.assertEqual([], result.tokens)
        self.assertEqual({}, result.source_generation_info)
        self.assertEqual("parent", result.lineage_info["parent_line_label"])
        self.assertIsNone(result.lineage_info["parent_line_index"])
        self.assertEqual("retained", result.lineage_info["parent_image_path"])
        self.assertEqual("retained", result.lineage_info["promoted_from_variant_id"])

    def test_fallback_builders_use_original_source_and_separate_lazy_metadata(self):
        source = _line(selected_candidate_path="")
        variant = {"source_generation_info": None, "lineage_info": False}
        before = copy.deepcopy((source, variant))
        events = []
        records = [{"prompt_text": "candidate prompt"}, {"source": "second"}]
        source_builder = promotion.build_source_generation_info_from_candidate
        lineage_builder = promotion.build_lineage_info_from_candidate

        def metadata():
            events.append("metadata")
            return records.pop(0)

        def build_source(line, path, record):
            self.assertIs(source, line)
            events.append("source")
            return source_builder(line, path, record)

        def build_lineage(line, path, record):
            self.assertIs(source, line)
            events.append("lineage")
            return lineage_builder(line, path, record)

        with patch.object(promotion, "build_source_generation_info_from_candidate", build_source), patch.object(
            promotion, "build_lineage_info_from_candidate", build_lineage
        ):
            result = promotion.prepare_gallery_variant_promotion_line(source, variant, "v.png", "new", metadata)
        self.assertEqual(["metadata", "source", "metadata", "lineage"], events)
        self.assertEqual("candidate prompt", result.source_generation_info["source_prompt"])
        self.assertEqual("second", result.lineage_info["created_from"])
        self.assertEqual("generated.png", result.lineage_info["parent_image_path"])
        self.assertEqual(before, (source, variant))

    def test_failures_propagate_in_copy_id_parse_normalize_metadata_order(self):
        for failing in ("copy", "id", "parse", "normalize", "metadata", "source", "lineage"):
            with self.subTest(failing=failing):
                source = _line()
                before = copy.deepcopy(source)
                events = []
                error = RuntimeError(failing)
                deepcopy = copy.deepcopy
                normalize = promotion.normalize_candidate_line_for_main_sequence

                def stage(name, operation):
                    def call(*args):
                        events.append(name)
                        if name == failing:
                            raise error
                        return operation(*args)
                    return call

                with patch.object(promotion.copy, "deepcopy", stage("copy", deepcopy)), patch.object(
                    promotion, "parse_prompt", stage("parse", parse_prompt)
                ), patch.object(promotion, "normalize_candidate_line_for_main_sequence", stage("normalize", normalize)):
                    with patch.object(promotion, "build_source_generation_info_from_candidate", stage("source", lambda *_: {})), patch.object(
                        promotion, "build_lineage_info_from_candidate", stage("lineage", lambda *_: {})
                    ), self.assertRaises(RuntimeError) as caught:
                        promotion.prepare_gallery_variant_promotion_line(
                            source, {}, "v.png", stage("id", lambda: "new"),
                            stage("metadata", lambda: {}),
                        )
                self.assertIs(error, caught.exception)
                order = ["copy", "id", "parse", "normalize", "metadata", "source", "metadata", "lineage"]
                self.assertEqual(order[:order.index(failing) + 1], events)
                self.assertEqual(before, source)

    def test_each_provenance_dictionary_independently_skips_metadata_fallback(self):
        for source_info in ({}, None):
            for lineage_info in ({}, None):
                with self.subTest(source_info=source_info, lineage_info=lineage_info):
                    source = _line(selected_candidate_path=None, generated_image_path=None)
                    variant = {"source_generation_info": source_info, "lineage_info": lineage_info}
                    record = {"source": "candidate", "prompt_text": "candidate prompt"}
                    metadata = Mock(return_value=record)
                    result = promotion.prepare_gallery_variant_promotion_line(source, variant, "", "new", metadata)
                    direct = promotion.prepare_gallery_variant_promotion_line(source, variant, "", "new", record)
                    self.assertEqual(direct, result)
                    self.assertEqual(int(source_info is None) + int(lineage_info is None), metadata.call_count)
                    self.assertEqual("parent.png", result.original_file_name)
                    self.assertEqual("parent.png", result.lineage_info["parent_image_path"])

    def test_normalizer_returns_the_same_line(self):
        source = _line()
        self.assertIs(source, promotion.normalize_candidate_line_for_main_sequence(source))


class GalleryVariantPromotionCallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
        cls.caller = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                          and node.name == "promote_gallery_variant_to_route")

    def _load(self, project, events, *, fail_preparation=False, exists=True):
        class State(dict):
            __getattr__ = dict.__getitem__
            __setattr__ = dict.__setitem__

        state = State(focused_line_id="focus")
        prepared = []

        def prepare(*args, **kwargs):
            events.append("prepare")
            self.assertEqual([project.prompt_lines[0]], project.prompt_lines)
            if fail_preparation:
                raise ValueError("preparation failed")
            result = promotion.prepare_gallery_variant_promotion_line(*args, **kwargs)
            prepared.append(result)
            return result

        def graph(value):
            events.append("graph")
            self.assertIs(project, value)
            self.assertIs(prepared[0], value.prompt_lines[-1])
            return value

        namespace = dict(
            get_line_by_id=lambda *_: project.prompt_lines[0],
            _normalize_candidate_path=lambda path: events.append("normalize_path") or path,
            _runtime_asset_path=lambda path: events.append("resolve") or path,
            os=SimpleNamespace(path=SimpleNamespace(exists=lambda _: events.append("exists") or exists)),
            push_history=lambda: events.append("history"),
            prepare_gallery_variant_promotion_line=prepare,
            uuid=SimpleNamespace(uuid4=lambda: events.append("id") or SimpleNamespace(hex="123456789")),
            _variant_record_for_promotion=lambda _: events.append("metadata") or {},
            _promoted_route_insert_index=lambda *_: events.append("index") or 1,
            _reindex_project_lines=lambda _: events.append("reindex"),
            st=SimpleNamespace(session_state=state), build_graph=graph,
            restore_focus_after_graph_update=lambda focus: events.append(("focus", focus)),
            sync_text_areas=lambda: events.append("sync"),
            save_current_project_if_possible=lambda reason: events.append(("save", reason)),
        )
        exec(compile(ast.Module(body=[self.caller], type_ignores=[]), "app.py", "exec"), namespace)
        return namespace["promote_gallery_variant_to_route"], state, prepared

    def test_publication_identity_and_managed_or_batch_lifecycle(self):
        for manage_state in (True, False):
            with self.subTest(manage_state=manage_state):
                project = Project(prompt_lines=[_line()])
                events = []
                caller, state, prepared = self._load(project, events)
                result = caller(project, "parent", {"path": "v.png"}, manage_state=manage_state)
                expected = ["normalize_path", "resolve", "exists"]
                if manage_state:
                    expected += ["history"]
                expected += ["prepare", "id", "metadata", "metadata", "index", "reindex"]
                if manage_state:
                    expected += ["graph", ("focus", "focus"), "sync", ("save", "gallery variant promoted to route")]
                    self.assertIs(project, state.project)
                    self.assertEqual(result, state.highlighted_line_id)
                    self.assertEqual(result, state.gallery_expanded_line_id)
                else:
                    self.assertEqual({"focused_line_id": "focus"}, state)
                self.assertEqual(expected, events)
                self.assertEqual("line_12345678", result)
                self.assertIs(prepared[0], project.prompt_lines[1])

    def test_preparation_failure_leaves_history_but_no_publication_or_lifecycle(self):
        project = Project(prompt_lines=[_line()])
        before = copy.deepcopy(project)
        events = []
        caller, state, _ = self._load(project, events, fail_preparation=True)
        with self.assertRaisesRegex(ValueError, "preparation failed"):
            caller(project, "parent", {"path": "v.png"})
        self.assertEqual(["normalize_path", "resolve", "exists", "history", "prepare"], events)
        self.assertEqual(before, project)
        self.assertEqual({"focused_line_id": "focus"}, state)

    def test_missing_runtime_asset_stops_before_history_or_preparation(self):
        project = Project(prompt_lines=[_line()])
        events = []
        caller, _, prepared = self._load(project, events, exists=False)
        self.assertIsNone(caller(project, "parent", {"path": "v.png"}))
        self.assertEqual(["normalize_path", "resolve", "exists"], events)
        self.assertEqual([], prepared)
        self.assertEqual(1, len(project.prompt_lines))


if __name__ == "__main__":
    unittest.main()
