import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import gallery_variant_promotion as promotion
from core.project import Project, PromptLine


def source_line(**fields):
    values = dict(
        id="parent", original_file_name="parent.png", original_index=3,
        current_index=7, original_text="old", current_text=" sky, (red, blue), , sun ",
        tokens=["stale"], negative_prompt=" keep negative ",
        image_path="original.png", generated_image_path="generated.png",
        selected_candidate_path="selected.png", generated_candidates=[{"nested": []}],
        gallery_variants=[{"id": "old"}], node_path=["retained"], deleted=True,
        line_type="workbench", separator_label="route", separator_color="red",
        workbench_source_line_id="origin", workbench_title="title",
        workbench_note="note", workbench_status="draft",
    )
    values.update(fields)
    return PromptLine(**values)


class PromotionPreparationTests(unittest.TestCase):
    def prepare(self, line=None, variant=None, path="variants/new.png", metadata=None):
        return promotion.prepare_gallery_variant_promotion_line(
            line if line is not None else source_line(),
            variant if variant is not None else {}, path, "new-id",
            metadata if metadata is not None else {},
        )

    def test_materializes_source_prompt_and_resets_publication_state(self):
        source = source_line()
        variant = {"id": "v", "candidate_metadata": {"prompt": "other prompt"}}
        before = copy.deepcopy((source, variant))
        result = self.prepare(source, variant, metadata=variant["candidate_metadata"])
        self.assertIsInstance(result, PromptLine)
        self.assertIsNot(result, source)
        self.assertEqual("new-id", result.id)
        self.assertEqual("new.png", result.original_file_name)
        self.assertEqual(source.current_text, result.original_text)
        self.assertEqual(source.current_text, result.current_text)
        self.assertEqual(["sky", "(red, blue)", "sun"], result.tokens)
        self.assertEqual(" keep negative ", result.negative_prompt)
        self.assertEqual("parent", result.duplicated_from)
        self.assertTrue(result.edited)
        self.assertFalse(result.deleted)
        self.assertEqual("variants/new.png", result.image_path)
        for field in ("generated_image_path", "selected_candidate_path", "line_type",
                      "separator_label", "separator_color", "workbench_source_line_id",
                      "workbench_title", "workbench_note", "workbench_status"):
            self.assertIsNone(getattr(result, field), field)
        self.assertEqual([], result.generated_candidates)
        self.assertEqual([], result.gallery_variants)
        self.assertEqual((3, 7), (result.original_index, result.current_index))
        self.assertEqual(source.node_path, result.node_path)
        self.assertIsNot(source.node_path, result.node_path)
        self.assertEqual(before, (source, variant))
        self.assertEqual("other prompt", result.source_generation_info["source_prompt"])

    def test_supplied_records_are_shallow_copies_with_unknown_fields(self):
        source_info = {"unknown": {"nested": []}}
        lineage = {"custom": [], "parent_image_path": "old.png"}
        variant = {"id": 12, "source_generation_info": source_info, "lineage_info": lineage}
        result = self.prepare(variant=variant)
        self.assertIsNot(source_info, result.source_generation_info)
        self.assertIs(source_info["unknown"], result.source_generation_info["unknown"])
        self.assertIsNot(lineage, result.lineage_info)
        self.assertIs(lineage["custom"], result.lineage_info["custom"])
        self.assertEqual("old.png", lineage["parent_image_path"])
        self.assertEqual("gallery_variant_promote_to_route", result.lineage_info["lineage_kind"])
        self.assertEqual("parent", result.lineage_info["parent_line_id"])
        self.assertEqual(7, result.lineage_info["parent_line_index"])
        self.assertEqual("parent.png", result.lineage_info["parent_line_label"])
        self.assertEqual("12", result.lineage_info["promoted_from_variant_id"])
        self.assertEqual("variants/new.png", result.lineage_info["promoted_from_variant_path"])
        self.assertEqual("variants/new.png", result.lineage_info["candidate_image_path"])

    def test_empty_dicts_skip_metadata_and_non_dicts_fall_back_independently(self):
        for source_info, lineage_info, calls in (({}, {}, 0), ({}, None, 1),
                                                (None, {}, 1), ([], "legacy", 2)):
            with self.subTest(source=source_info, lineage=lineage_info):
                metadata = Mock(return_value={"source": "legacy-source"})
                result = self.prepare(variant={"source_generation_info": source_info,
                                               "lineage_info": lineage_info}, metadata=metadata)
                self.assertEqual(calls, metadata.call_count)
                if source_info == {}:
                    self.assertEqual({}, result.source_generation_info)
                else:
                    self.assertEqual("derived_candidate", result.source_generation_info["source_kind"])

    def test_each_fallback_receives_a_fresh_metadata_evaluation(self):
        metadata = Mock(side_effect=[{"prompt": "first"}, {"source": "second"}])
        result = self.prepare(metadata=metadata)
        self.assertEqual("first", result.source_generation_info["source_prompt"])
        self.assertEqual("second", result.lineage_info["created_from"])
        self.assertEqual(2, metadata.call_count)

    def test_parent_image_precedence_and_absent_image_retains_supplied_lineage(self):
        for selected, generated, image, expected in (
            ("selected", "generated", "image", "selected"),
            ("", "generated", "image", "generated"),
            (None, "", "image", "image"), (None, None, None, "inherited"),
        ):
            with self.subTest(expected=expected):
                result = self.prepare(source_line(selected_candidate_path=selected,
                    generated_image_path=generated, image_path=image),
                    {"lineage_info": {"parent_image_path": "inherited"}})
                self.assertEqual(expected, result.lineage_info["parent_image_path"])

    def test_falsey_id_preserves_existing_variant_id_and_label_falls_back(self):
        for variant_id in (None, "", 0, False):
            with self.subTest(variant_id=variant_id):
                result = self.prepare(source_line(original_file_name="", current_index=None),
                    {"id": variant_id, "lineage_info": {"promoted_from_variant_id": "old"}},
                    path="folder/")
                self.assertEqual("", result.original_file_name)
                self.assertEqual("parent", result.lineage_info["parent_line_label"])
                self.assertIsNone(result.lineage_info["parent_line_index"])
                self.assertEqual("old", result.lineage_info["promoted_from_variant_id"])

    def test_empty_basename_uses_source_filename_and_empty_prompt_parses(self):
        result = self.prepare(source_line(current_text=""), path="folder/")
        self.assertEqual("parent.png", result.original_file_name)
        self.assertEqual([], result.tokens)

    def test_deepcopy_failure_precedes_identity_and_metadata(self):
        class Uncopyable:
            def __deepcopy__(self, memo):
                raise RuntimeError("copy failed")
        source = source_line()
        source.extra = Uncopyable()
        identity, metadata = Mock(), Mock()
        with self.assertRaisesRegex(RuntimeError, "copy failed"):
            promotion.prepare_gallery_variant_promotion_line(source, {}, "new.png", identity, metadata)
        identity.assert_not_called()
        metadata.assert_not_called()

    def test_identity_failure_precedes_prompt_parsing(self):
        with patch.object(promotion, "parse_prompt") as parse:
            with self.assertRaisesRegex(RuntimeError, "id failed"):
                promotion.prepare_gallery_variant_promotion_line(source_line(), {}, "new.png",
                    Mock(side_effect=RuntimeError("id failed")), {})
            parse.assert_not_called()

    def test_invalid_prompt_failure_follows_identity_and_precedes_metadata(self):
        source = source_line(current_text=None)
        identity, metadata = Mock(return_value="new-id"), Mock()
        with self.assertRaises(TypeError):
            promotion.prepare_gallery_variant_promotion_line(source, {}, "new.png", identity, metadata)
        identity.assert_called_once_with()
        metadata.assert_not_called()
        self.assertEqual("parent", source.id)
        self.assertTrue(source.deleted)

    def test_metadata_and_builder_exceptions_propagate_before_lineage(self):
        for failure in ("metadata", "source", "lineage"):
            with self.subTest(failure=failure):
                events = []
                error = RuntimeError(failure)
                def step(name, result):
                    def run(*args):
                        events.append(name)
                        if name == failure:
                            raise error
                        return result
                    return run
                source = source_line()
                before = copy.deepcopy(source)
                with patch.object(promotion, "build_source_generation_info_from_candidate",
                                  side_effect=step("source", {})), patch.object(
                        promotion, "build_lineage_info_from_candidate", side_effect=step("lineage", {})):
                    with self.assertRaises(RuntimeError) as caught:
                        self.prepare(source, metadata=step("metadata", {}))
                self.assertIs(error, caught.exception)
                expected = ["metadata", "source", "metadata", "lineage"]
                self.assertEqual(expected[:expected.index(failure) + 1], events)
                self.assertEqual(before, source)


class PromotionCallerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
        cls.function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                            and node.name == "promote_gallery_variant_to_route")

    def caller(self, exists=True, failure=False):
        events = []
        source = source_line(deleted=False)
        project = Project(prompt_lines=[source])
        def prepare(*args, **kwargs):
            events.append("prepare")
            self.assertTrue(callable(kwargs["new_line_id"]))
            self.assertTrue(callable(kwargs["promotion_metadata"]))
            if failure:
                raise ValueError("preparation failed")
            return promotion.prepare_gallery_variant_promotion_line(*args, **kwargs)
        namespace = dict(
            get_line_by_id=lambda *_: source,
            _normalize_candidate_path=lambda path: path,
            _runtime_asset_path=lambda path: path,
            os=SimpleNamespace(path=SimpleNamespace(exists=lambda _: exists)),
            push_history=lambda: events.append("history"),
            prepare_gallery_variant_promotion_line=prepare,
            uuid=SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="12345678abcdef")),
            _variant_record_for_promotion=lambda _: {},
            _promoted_route_insert_index=lambda *_: len(project.prompt_lines),
            _reindex_project_lines=lambda _: events.append("reindex"),
        )
        exec(compile(ast.Module(body=[self.function], type_ignores=[]), "app.py", "exec"), namespace)
        return namespace["promote_gallery_variant_to_route"], project, events

    def test_missing_asset_precedes_history_and_preparation(self):
        caller, project, events = self.caller(exists=False)
        self.assertIsNone(caller(project, "parent", {"path": "new.png"}))
        self.assertEqual([], events)
        self.assertEqual(1, len(project.prompt_lines))

    def test_preparation_failure_follows_history_without_insertion(self):
        caller, project, events = self.caller(failure=True)
        with self.assertRaisesRegex(ValueError, "preparation failed"):
            caller(project, "parent", {"path": "new.png"})
        self.assertEqual(["history", "prepare"], events)
        self.assertEqual(1, len(project.prompt_lines))

    def test_unmanaged_call_inserts_and_reindexes_without_ui_or_history(self):
        caller, project, events = self.caller()
        self.assertEqual("line_12345678", caller(project, "parent", {"path": "new.png"}, manage_state=False))
        self.assertEqual(["prepare", "reindex"], events)
        self.assertEqual(["parent", "line_12345678"], [line.id for line in project.prompt_lines])

    def test_managed_call_publishes_only_after_preparation_and_insertion(self):
        caller, project, events = self.caller()
        class Session(dict):
            __getattr__ = dict.__getitem__
            __setattr__ = dict.__setitem__
        session = Session(focused_line_id="parent")
        def rebuild(value):
            self.assertEqual(2, len(value.prompt_lines))
            events.append("rebuild")
            return value
        caller.__globals__.update(
            st=SimpleNamespace(session_state=session), build_graph=rebuild,
            restore_focus_after_graph_update=lambda value: events.append(("focus", value)),
            sync_text_areas=lambda: events.append("sync"),
            save_current_project_if_possible=lambda reason: events.append(("save", reason)),
        )
        result = caller(project, "parent", {"path": "new.png"})
        self.assertEqual(["history", "prepare", "reindex", "rebuild", ("focus", "parent"),
                          "sync", ("save", "gallery variant promoted to route")], events)
        self.assertIs(project, session.project)
        self.assertEqual(result, session.highlighted_line_id)
        self.assertEqual(result, session.gallery_expanded_line_id)


if __name__ == "__main__":
    unittest.main()
