import copy
import json
import unittest
from unittest.mock import patch

from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine
import core.scene_import as scene_import_module
from core.scene_import import (
    SCENE_IMPORT_APPLY_CONTRACT_VERSION,
    SCENE_IMPORT_PREVIEW_CONTRACT_VERSION,
    apply_scene_import,
    preview_scene_import,
)


def _line(line_id, text="", *, index=0, line_type=None, **fields):
    values = {
        "id": line_id,
        "original_file_name": line_id,
        "original_index": index,
        "current_index": index,
        "original_text": text,
        "current_text": text,
        "tokens": parse_prompt(text),
        "negative_prompt": "",
        "line_type": line_type,
    }
    values.update(fields)
    return PromptLine(**values)


def _source_project(*, empty=False, module_body="blue eyes"):
    lines = [
        _line(
            "source-separator",
            "Source Scene",
            index=0,
            line_type="separator",
            separator_label="Source Scene",
            separator_color="violet",
        )
    ]
    if not empty:
        lines.append(
            _line(
                "source-line",
                "<mod:hero>, red hair",
                index=len(lines),
                negative_prompt=" bad anatomy, low quality ",
                image_path=r"C:\private\source.png",
                generated_image_path="generated.png",
                selected_candidate_path="candidate.png",
                generated_candidates=[{"path": "candidate.png"}],
                gallery_variants=[{"path": "variant.png"}],
                source_generation_info={"private": "source"},
                lineage_info={"private": "lineage"},
                duplicated_from="source-parent",
            )
        )
    lines.append(_line("source-next", "Next Scene", index=len(lines), line_type="separator"))
    return Project(
        prompt_lines=lines,
        module_library={"hero": {"body": module_body}},
    )


def _target_project(*, module=None):
    project = Project(
        prompt_lines=[
            _line(
                "target-separator",
                "Existing Scene",
                index=0,
                line_type="separator",
                separator_label="Existing Scene",
            ),
            _line("target-line", "existing, target", index=1),
        ],
        module_library={} if module is None else {"hero": module},
        project_metadata={"unrelated": {"keep": ["value"]}},
    )
    return build_graph(project)


def _preview(source=None, target=None, *, empty=False):
    source = source or _source_project(empty=empty)
    target = target or _target_project()
    return source, target, preview_scene_import(source, "source-separator", target)


def _reseal_preview(preview):
    preview["projection_digest"] = scene_import_module._digest(
        scene_import_module._preview_projection_payload(preview)
    )
    unsigned = {key: value for key, value in preview.items() if key != "plan_id"}
    preview["plan_id"] = scene_import_module._digest(unsigned)


class SceneImportApplyTests(unittest.TestCase):
    def test_success_materializes_exact_reviewed_block_receipt_modules_and_graph(self):
        source, target, reviewed = _preview()
        source_before = copy.deepcopy(source)
        target_before = copy.deepcopy(target)
        old_line_refs = list(target.prompt_lines)

        result = apply_scene_import(source, "source-separator", target, reviewed)

        self.assertTrue(result["applied"])
        self.assertEqual(SCENE_IMPORT_APPLY_CONTRACT_VERSION, result["contract_version"])
        self.assertEqual("scene_import", result["operation"])
        self.assertEqual(reviewed["plan_id"], result["reviewed_plan_id"])
        self.assertEqual(reviewed["projection_digest"], result["projection_digest"])
        self.assertEqual(reviewed["planned_separator"]["id"], result["target_separator_id"])
        self.assertEqual([row["id"] for row in reviewed["planned_illustrations"]], result["imported_illustration_ids"])
        self.assertEqual(["hero"], result["imported_module_names"])
        self.assertEqual([], result["reused_module_names"])
        self.assertEqual(reviewed["target_line_count"] + 2, result["resulting_target_line_count"])

        self.assertEqual(target_before.prompt_lines, target.prompt_lines[:len(old_line_refs)])
        self.assertTrue(all(actual is expected for actual, expected in zip(target.prompt_lines, old_line_refs)))
        self.assertEqual(reviewed["insertion_index"], len(old_line_refs))
        imported = target.prompt_lines[len(old_line_refs):]
        self.assertEqual(reviewed["resulting_scene_block_order"], [line.id for line in imported])
        self.assertEqual(
            [
                {key: value for key, value in row.items() if key != "node_path"}
                for row in [reviewed["planned_separator"], *reviewed["planned_illustrations"]]
            ],
            [
                {key: value for key, value in vars(line).items() if key != "node_path"}
                for line in imported
            ],
        )
        self.assertEqual("Source Scene", imported[0].separator_label)
        self.assertEqual("violet", imported[0].separator_color)
        self.assertEqual("<mod:hero>, red hair", imported[1].current_text)
        self.assertEqual("<mod:hero>, red hair", imported[1].original_text)
        self.assertEqual(" bad anatomy, low quality ", imported[1].negative_prompt)
        self.assertEqual(reviewed["planned_illustrations"][0]["tokens"], imported[1].tokens)
        self.assertIsNone(imported[1].image_path)
        self.assertIsNone(imported[1].generated_image_path)
        self.assertIsNone(imported[1].selected_candidate_path)
        self.assertEqual([], imported[1].generated_candidates)
        self.assertEqual([], imported[1].gallery_variants)
        self.assertEqual({}, imported[1].source_generation_info)
        self.assertEqual({}, imported[1].lineage_info)
        self.assertIsNone(imported[1].duplicated_from)
        self.assertIsNone(imported[1].workbench_source_line_id)
        self.assertEqual([0, 1, 2, 3], [line.current_index for line in target.prompt_lines])

        action = reviewed["module_actions"][0]
        self.assertEqual(action["import_definition"], target.module_library["hero"])
        self.assertIsNot(source.module_library["hero"], target.module_library["hero"])
        receipts = target.project_metadata["scene_transfers"]
        self.assertEqual(reviewed["planned_receipt_append_index"], 0)
        self.assertEqual([reviewed["planned_receipt"]], receipts)
        self.assertEqual(target_before.project_metadata["unrelated"], target.project_metadata["unrelated"])
        self.assertEqual(source_before, source)
        self.assertEqual({line.id for line in target.prompt_lines}, set(target.line_map))
        self.assertTrue(all(target.line_map[line.id] is line for line in target.prompt_lines))
        self.assertEqual(target_before.merge_by_word_only, target.merge_by_word_only)
        self.assertEqual(target_before.line_groups, target.line_groups)
        self.assertTrue(target.nodes)

    def test_empty_scene_imports_only_the_reviewed_separator(self):
        source, target, reviewed = _preview(empty=True)
        target_count = len(target.prompt_lines)
        source_before = copy.deepcopy(source)

        result = apply_scene_import(source, "source-separator", target, reviewed)

        self.assertTrue(result["applied"])
        self.assertEqual([], result["imported_illustration_ids"])
        self.assertEqual(target_count + 1, len(target.prompt_lines))
        imported = target.prompt_lines[-1]
        self.assertEqual(reviewed["planned_separator"]["id"], imported.id)
        self.assertEqual("separator", imported.line_type)
        self.assertEqual(target_count, imported.current_index)
        self.assertEqual(source_before, source)

    def test_reused_module_is_not_replaced_or_mutated(self):
        source = _source_project(module_body="blue eyes")
        target_module = {"body": "blue eyes", "reference_assets": ["target-local.png"]}
        target = _target_project(module=target_module)
        original_module_ref = target.module_library["hero"]
        original_module = copy.deepcopy(original_module_ref)
        reviewed = preview_scene_import(source, "source-separator", target)
        self.assertEqual("reuse", reviewed["module_actions"][0]["action"])

        result = apply_scene_import(source, "source-separator", target, reviewed)

        self.assertTrue(result["applied"])
        self.assertEqual(["hero"], result["reused_module_names"])
        self.assertIs(original_module_ref, target.module_library["hero"])
        self.assertEqual(original_module, target.module_library["hero"])

    def test_irrelevant_target_asset_changes_do_not_stale_and_are_preserved(self):
        source, target, reviewed = _preview()
        target.prompt_lines[1].image_path = r"D:\asset.png"
        target.prompt_lines[1].generated_candidates = [{"path": "candidate.png"}]
        target.prompt_lines[1].gallery_variants = [{"path": "variant.png"}]
        original_line = target.prompt_lines[1]

        result = apply_scene_import(source, "source-separator", target, reviewed)

        self.assertTrue(result["applied"])
        self.assertIs(original_line, target.prompt_lines[1])
        self.assertEqual(r"D:\asset.png", target.prompt_lines[1].image_path)
        self.assertEqual([{"path": "candidate.png"}], target.prompt_lines[1].generated_candidates)
        self.assertEqual([{"path": "variant.png"}], target.prompt_lines[1].gallery_variants)

    def test_stale_states_reject_without_mutating_either_project(self):
        mutations = {
            "source_prompt": lambda source, target: setattr(
                source.prompt_lines[1], "current_text", "changed source prompt"
            ),
            "source_module": lambda source, target: source.module_library["hero"].update(
                {"body": "changed Module body"}
            ),
            "target_prompt": lambda source, target: setattr(
                target.prompt_lines[1], "current_text", "changed target prompt"
            ),
            "target_structure": lambda source, target: setattr(
                target.prompt_lines[1], "deleted", True
            ),
            "target_merge_mode": lambda source, target: setattr(
                target, "merge_by_word_only", False
            ),
            "target_receipt_namespace": lambda source, target: target.project_metadata.update(
                {"scene_transfers": [{"transfer_id": "new-receipt"}]}
            ),
            "target_index": lambda source, target: setattr(
                target.prompt_lines[1], "current_index", 20
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                source, target, reviewed = _preview()
                mutate(source, target)
                source_before = copy.deepcopy(source)
                target_before = copy.deepcopy(target)

                result = apply_scene_import(source, "source-separator", target, reviewed)

                self.assertFalse(result["applied"])
                self.assertEqual(source_before, source)
                self.assertEqual(target_before, target)

    def test_referenced_target_module_conflict_rejects_without_mutation(self):
        source = _source_project()
        target = _target_project(module={"body": "blue eyes"})
        reviewed = preview_scene_import(source, "source-separator", target)
        target.module_library["hero"]["body"] = "different semantic definition"
        before = copy.deepcopy(target)

        result = apply_scene_import(source, "source-separator", target, reviewed)

        self.assertFalse(result["applied"])
        self.assertEqual("current_preview_ineligible", result["reason"])
        self.assertEqual(before, target)

    def test_target_id_collision_after_review_rejects_without_mutation(self):
        source, target, reviewed = _preview()
        collision_id = reviewed["planned_separator"]["id"]
        target.prompt_lines.append(_line(collision_id, "new target row", index=len(target.prompt_lines)))
        before = copy.deepcopy(target)

        result = apply_scene_import(source, "source-separator", target, reviewed)

        self.assertFalse(result["applied"])
        self.assertEqual("reviewed_preview_stale", result["reason"])
        self.assertEqual(before, target)

    def test_invalid_current_source_or_target_fails_closed_without_mutation(self):
        source, target, reviewed = _preview()
        source.prompt_lines[0].deleted = True
        source_before = copy.deepcopy(source)
        target_before = copy.deepcopy(target)
        source_result = apply_scene_import(source, "source-separator", target, reviewed)
        self.assertFalse(source_result["applied"])
        self.assertEqual("source_now_invalid", source_result["reason"])
        self.assertEqual(source_before, source)
        self.assertEqual(target_before, target)

        source, target, reviewed = _preview()
        target.prompt_lines[0].current_index = 2
        source_before = copy.deepcopy(source)
        target_before = copy.deepcopy(target)
        target_result = apply_scene_import(source, "source-separator", target, reviewed)
        self.assertFalse(target_result["applied"])
        self.assertEqual("target_now_invalid", target_result["reason"])
        self.assertEqual(source_before, source)
        self.assertEqual(target_before, target)

    def test_same_project_object_is_rejected_without_mutation(self):
        source, target, reviewed = _preview()
        before = copy.deepcopy(source)

        result = apply_scene_import(source, "source-separator", source, reviewed)

        self.assertFalse(result["applied"])
        self.assertEqual("same_project", result["reason"])
        self.assertEqual(before, source)

    def test_conflict_preview_is_ineligible_and_not_applied(self):
        source = _source_project(module_body="blue eyes")
        target = _target_project(module={"body": "different"})
        reviewed = preview_scene_import(source, "source-separator", target)
        before = copy.deepcopy(target)

        result = apply_scene_import(source, "source-separator", target, reviewed)

        self.assertFalse(reviewed["eligible"])
        self.assertFalse(result["applied"])
        self.assertEqual("reviewed_preview_ineligible", result["reason"])
        self.assertEqual(before, target)

    def test_malformed_or_incompatible_reviewed_preview_is_rejected(self):
        source, target, reviewed = _preview()
        invalid_values = [
            (None, "malformed_reviewed_preview"),
            ([], "malformed_reviewed_preview"),
            ({**reviewed, "contract_version": "other"}, "incompatible_reviewed_preview"),
            ({key: value for key, value in reviewed.items() if key != "planned_receipt"}, "malformed_reviewed_preview"),
            ({**reviewed, "valid": False}, "reviewed_preview_invalid"),
            ({**reviewed, "eligible": False}, "reviewed_preview_ineligible"),
        ]
        for index, (bad_review, reason) in enumerate(invalid_values):
            with self.subTest(index=index):
                target_copy = copy.deepcopy(target)
                source_copy = copy.deepcopy(source)
                source_before = copy.deepcopy(source_copy)
                target_before = copy.deepcopy(target_copy)

                result = apply_scene_import(source_copy, "source-separator", target_copy, bad_review)

                self.assertFalse(result["applied"])
                self.assertEqual(reason, result["reason"])
                self.assertEqual(source_before, source_copy)
                self.assertEqual(target_before, target_copy)

    def test_cycle_or_custom_object_in_reviewed_preview_is_rejected(self):
        source, target, reviewed = _preview()
        circular = copy.deepcopy(reviewed)
        circular["unexpected"] = circular
        custom = copy.deepcopy(reviewed)
        custom["planned_receipt"]["unexpected"] = object()
        for bad_review in (circular, custom):
            with self.subTest(value=type(bad_review["planned_receipt"].get("unexpected"))):
                before = copy.deepcopy(target)
                result = apply_scene_import(source, "source-separator", target, bad_review)
                self.assertFalse(result["applied"])
                self.assertEqual("malformed_reviewed_preview", result["reason"])
                self.assertEqual(before, target)

    def test_altered_digests_are_rejected(self):
        source, target, reviewed = _preview()
        for key in ("plan_id", "projection_digest"):
            with self.subTest(key=key):
                altered = copy.deepcopy(reviewed)
                altered[key] = "sha256:" + "0" * 64
                if altered[key] == reviewed[key]:
                    altered[key] = "sha256:" + "1" * 64
                before = copy.deepcopy(target)
                result = apply_scene_import(source, "source-separator", target, altered)
                self.assertFalse(result["applied"])
                self.assertEqual("reviewed_preview_integrity_mismatch", result["reason"])
                self.assertEqual(before, target)

    def test_tampered_rows_module_actions_and_receipt_reject_even_when_resealed(self):
        mutators = {
            "planned_row": lambda review: review["planned_illustrations"][0].update(
                {"current_text": "tampered prompt"}
            ),
            "module_action": lambda review: review["module_actions"][0].update(
                {"action": "reuse"}
            ),
            "receipt": lambda review: review["planned_receipt"].update(
                {"target_separator_id": "tampered-separator"}
            ),
        }
        for name, mutate in mutators.items():
            with self.subTest(name=name):
                source, target, reviewed = _preview()
                tampered = copy.deepcopy(reviewed)
                mutate(tampered)
                _reseal_preview(tampered)
                source_before = copy.deepcopy(source)
                target_before = copy.deepcopy(target)

                result = apply_scene_import(source, "source-separator", target, tampered)

                self.assertFalse(result["applied"])
                self.assertEqual("reviewed_preview_stale", result["reason"])
                self.assertEqual(source_before, source)
                self.assertEqual(target_before, target)

    def test_staging_module_receipt_graph_and_postcondition_failures_roll_back(self):
        failures = [
            ("staging", "staging_failed", "deepcopy"),
            ("materialization", "row_materialization_failed", "_materialize_preview_row"),
            ("module", "module_import_invariant_failed", "_apply_preview_modules"),
            ("receipt", "receipt_append_invariant_failed", "_append_preview_receipt"),
            ("graph", "graph_rebuild_failed", "build_graph"),
            ("postcondition", "postcondition_failed", "_verify_staged_apply"),
        ]
        for name, expected_reason, seam in failures:
            with self.subTest(name=name):
                source, target, reviewed = _preview()
                source_before = copy.deepcopy(source)
                target_before = copy.deepcopy(target)
                if seam == "deepcopy":
                    context = patch.object(scene_import_module.copy, "deepcopy", side_effect=RuntimeError("private"))
                elif seam == "build_graph":
                    context = patch.object(scene_import_module, seam, side_effect=RuntimeError("private"))
                else:
                    context = patch.object(scene_import_module, seam, side_effect=RuntimeError("private"))
                with context:
                    result = apply_scene_import(source, "source-separator", target, reviewed)

                self.assertFalse(result["applied"])
                self.assertEqual(expected_reason, result["reason"])
                self.assertEqual(source_before, source)
                self.assertEqual(target_before, target)

    def test_reapplying_the_same_review_does_not_duplicate_scene(self):
        source, target, reviewed = _preview()
        first = apply_scene_import(source, "source-separator", target, reviewed)
        self.assertTrue(first["applied"])
        after_first = copy.deepcopy(target)

        second = apply_scene_import(source, "source-separator", target, reviewed)

        self.assertFalse(second["applied"])
        self.assertEqual("reviewed_preview_stale", second["reason"])
        self.assertEqual(after_first, target)

    def test_apply_result_is_bounded_and_json_safe(self):
        source, target, reviewed = _preview()

        result = apply_scene_import(source, "source-separator", target, reviewed)
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)

        self.assertTrue(result["applied"])
        self.assertLessEqual(len(result["blockers"]), 16)
        self.assertLess(len(encoded), 20_000)
        self.assertNotIn("blue eyes", encoded)
        self.assertNotIn("Project(", encoded)
        self.assertNotIn("PromptLine(", encoded)
        self.assertNotIn("source_directory", result)


if __name__ == "__main__":
    unittest.main()
