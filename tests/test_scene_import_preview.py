import copy
import hashlib
import json
import unittest
from dataclasses import fields
from unittest.mock import patch

from core.parser import parse_prompt
from core.project import Project, PromptLine
import core.scene_import as scene_import_module
from core.scene_import import (
    SCENE_IMPORT_PREVIEW_CONTRACT_VERSION,
    preview_scene_import,
)
from core.scene_portability import project_scene_portability_payload


def _line(line_id, text="", *, line_type=None, deleted=False, **fields):
    values = {
        "id": line_id,
        "original_file_name": line_id,
        "original_index": 0,
        "current_index": 0,
        "original_text": text,
        "current_text": text,
        "tokens": parse_prompt(text),
        "negative_prompt": "",
        "line_type": line_type,
        "deleted": deleted,
    }
    values.update(fields)
    return PromptLine(**values)


def _without_planned_id(value):
    return {key: item for key, item in value.items() if key != "id"}


def _source_project(*, module=None, text="  <mod:hero>, exact positive  ", empty=False):
    lines = [
        _line("source-before", "outside"),
        _line(
            "source-separator",
            "Source Scene",
            line_type="separator",
            separator_label="Source Scene",
            separator_color="violet",
            edited=True,
        ),
    ]
    if not empty:
        lines.extend([
            _line(
                "source-line-a",
                text,
                negative_prompt=" negative stays exact ",
                image_path=r"C:\private\source.png",
                generated_image_path="generated.png",
                selected_candidate_path="candidate.png",
                generated_candidates=[{"path": "candidate.png"}],
                gallery_variants=[{"path": "variant.png"}],
                source_generation_info={"private": "generation"},
                lineage_info={"private": "lineage"},
                edited=True,
            ),
            _line("source-line-b", "second prompt", negative_prompt="second negative"),
        ])
    lines.append(_line("source-next", "Next Scene", line_type="separator"))
    return Project(prompt_lines=lines, module_library={"hero": module or {"body": "red hair, blue eyes"}})


def _target_project():
    return Project(
        prompt_lines=[
            _line("target-separator", "Existing Scene", line_type="separator", separator_label="Existing Scene"),
            _line("target-line", "existing prompt", original_index=1, current_index=1),
        ],
        module_library={},
        project_metadata={"unrelated": {"keep": True}},
    )


class SceneImportPreviewTests(unittest.TestCase):
    def test_ordinary_preview_reuses_source_projection_and_plans_tail_block(self):
        source = _source_project()
        target = _target_project()
        source_before = copy.deepcopy(source)
        target_before = copy.deepcopy(target)
        projection = project_scene_portability_payload(source, "source-separator")

        result = preview_scene_import(source, "source-separator", target)

        self.assertTrue(result["valid"])
        self.assertTrue(result["eligible"])
        self.assertEqual(SCENE_IMPORT_PREVIEW_CONTRACT_VERSION, result["contract_version"])
        self.assertEqual("scene_import", result["operation"])
        self.assertEqual(projection["source_scene_fingerprint"], result["source_scene_fingerprint"])
        self.assertEqual("Source Scene", result["planned_separator"]["separator_label"])
        self.assertEqual("violet", result["planned_separator"]["separator_color"])
        self.assertEqual("Source Scene", result["planned_separator"]["current_text"])
        self.assertEqual(len(target.prompt_lines), result["target_line_count"])
        self.assertEqual(len(target.prompt_lines), result["insertion_index"])
        self.assertEqual(len(target.prompt_lines), result["planned_separator"]["original_index"])
        self.assertEqual(len(target.prompt_lines) + 1, result["planned_illustrations"][0]["original_index"])
        self.assertEqual(
            [result["planned_separator"]["id"]]
            + [line["id"] for line in result["planned_illustrations"]],
            result["resulting_scene_block_order"],
        )
        prompt_line_fields = {item.name for item in fields(PromptLine)}
        self.assertEqual(prompt_line_fields, set(result["planned_separator"]))
        self.assertEqual(prompt_line_fields, set(result["planned_illustrations"][0]))
        self.assertEqual(source_before, source)
        self.assertEqual(target_before, target)

    def test_fresh_ids_and_complete_preview_are_deterministic(self):
        source = _source_project()
        target = _target_project()

        first = preview_scene_import(source, "source-separator", target)
        second = preview_scene_import(source, "source-separator", target)

        self.assertEqual(first, second)
        source_ids = {line.id for line in source.prompt_lines}
        target_ids = {line.id for line in target.prompt_lines}
        planned_ids = {first["planned_separator"]["id"]} | {
            line["id"] for line in first["planned_illustrations"]
        }
        self.assertTrue(planned_ids.isdisjoint(source_ids))
        self.assertTrue(planned_ids.isdisjoint(target_ids))
        self.assertEqual(len(planned_ids), 3)
        self.assertTrue(first["plan_id"].startswith("sha256:"))
        self.assertTrue(first["projection_digest"].startswith("sha256:"))

    def test_deterministic_id_collisions_advance_the_bounded_counter(self):
        source = _source_project(module={"body": "red hair"})
        target = _target_project()
        target.prompt_lines.append(
            _line("separator_import_" + "a" * 32, "collision", current_index=2)
        )
        original_digest = scene_import_module._digest

        def collide_first_separator(value):
            if value.get("kind") == "separator" and value.get("collision_counter") == 0:
                return "sha256:" + "a" * 64
            return original_digest(value)

        with patch.object(scene_import_module, "_digest", side_effect=collide_first_separator):
            result = preview_scene_import(source, "source-separator", target)
        self.assertTrue(result["eligible"])
        self.assertNotEqual("separator_import_" + "a" * 32, result["planned_separator"]["id"])

        target = _target_project()
        target.project_metadata["scene_transfers"] = [{"transfer_id": "transfer_" + "b" * 32}]

        def collide_first_transfer(value):
            if "source_to_target_map" in value and value.get("collision_counter") == 0:
                return "sha256:" + "b" * 64
            return original_digest(value)

        with patch.object(scene_import_module, "_digest", side_effect=collide_first_transfer):
            transfer_result = preview_scene_import(source, "source-separator", target)
        self.assertTrue(transfer_result["eligible"])
        self.assertNotEqual("transfer_" + "b" * 32, transfer_result["planned_receipt"]["transfer_id"])

    def test_empty_scene_plans_only_a_fresh_separator(self):
        result = preview_scene_import(_source_project(empty=True), "source-separator", _target_project())

        self.assertTrue(result["eligible"])
        self.assertEqual([], result["planned_illustrations"])
        self.assertEqual([result["planned_separator"]["id"]], result["resulting_scene_block_order"])
        self.assertEqual([], result["source_to_target_map"]["illustrations"])

    def test_prompts_are_verbatim_tokens_are_rebuilt_and_transient_state_is_cleared(self):
        source = _source_project()
        result = preview_scene_import(source, "source-separator", _target_project())
        planned = result["planned_illustrations"][0]

        self.assertEqual("  <mod:hero>, exact positive  ", planned["current_text"])
        self.assertEqual(planned["current_text"], planned["original_text"])
        self.assertEqual(" negative stays exact ", planned["negative_prompt"])
        self.assertEqual(parse_prompt(planned["current_text"]), planned["tokens"])
        for line in result["planned_illustrations"]:
            self.assertIsNone(line["image_path"])
            self.assertIsNone(line["generated_image_path"])
            self.assertIsNone(line["selected_candidate_path"])
            self.assertEqual([], line["generated_candidates"])
            self.assertEqual([], line["gallery_variants"])
            self.assertEqual({}, line["source_generation_info"])
            self.assertEqual({}, line["lineage_info"])
            self.assertIsNone(line["duplicated_from"])
            self.assertIsNone(line["workbench_source_line_id"])
            self.assertIsNone(line["workbench_title"])
            self.assertIsNone(line["workbench_note"])
            self.assertIsNone(line["workbench_status"])
        serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
        for excluded in (r"C:\private\source.png", "generated.png", "candidate.png", "variant.png"):
            self.assertNotIn(excluded, serialized)

    def test_module_missing_is_import_and_identical_portable_definition_is_reuse(self):
        module = {
            "body": "red hair, blue eyes",
            "type": "generic",
            "category": "character",
            "extra": {"note": "portable"},
        }
        source = _source_project(module=module)
        missing = preview_scene_import(source, "source-separator", _target_project())
        self.assertEqual(["import"], [action["action"] for action in missing["module_actions"]])
        source_snapshot = project_scene_portability_payload(source, "source-separator")["module_snapshots"][0]
        self.assertEqual(source_snapshot["definition"], missing["module_actions"][0]["import_definition"])

        target = _target_project()
        target.module_library["hero"] = copy.deepcopy(module)
        reused = preview_scene_import(source, "source-separator", target)
        self.assertTrue(reused["eligible"])
        self.assertEqual(["reuse"], [action["action"] for action in reused["module_actions"]])
        self.assertIsNone(reused["module_actions"][0]["import_definition"])

    def test_module_equality_ignores_reference_assets_and_machine_local_path_metadata(self):
        source_module = {
            "body": "red hair, blue eyes",
            "type": "generic",
            "category": "character",
            "thumbnail_path": r"C:\source\thumb.png",
            "reference_assets": {"hero": {"path": "refs/modules/hero.png"}},
            "source_note": {"old_location": r"D:\old\module.json"},
        }
        target_module = {
            "body": "red hair, blue eyes",
            "type": "generic",
            "category": "character",
            "thumbnail_path": r"Z:\different\thumb.png",
            "reference_assets": {"hero": {"path": "refs/modules/other.png"}},
            "source_note": {"old_location": r"E:\elsewhere\module.json"},
        }
        source = _source_project(module=source_module)
        target = _target_project()
        target.module_library["hero"] = target_module
        source_before = copy.deepcopy(source)
        target_before = copy.deepcopy(target)

        result = preview_scene_import(source, "source-separator", target)

        self.assertTrue(result["eligible"])
        self.assertEqual("reuse", result["module_actions"][0]["action"])
        self.assertEqual(source_before, source)
        self.assertEqual(target_before, target)

    def test_same_name_semantic_module_difference_is_conflict_and_ineligible(self):
        source = _source_project(module={"body": "red hair, blue eyes"})
        target = _target_project()
        target.module_library["hero"] = {"body": "green hair, blue eyes"}

        result = preview_scene_import(source, "source-separator", target)

        self.assertTrue(result["valid"])
        self.assertFalse(result["eligible"])
        self.assertIn("module_conflict", result["blockers"])
        self.assertEqual("conflict", result["module_actions"][0]["action"])
        self.assertEqual("same_name_definition_differs", result["module_actions"][0]["reason"])

    def test_malformed_relevant_target_module_blocks_preview(self):
        source = _source_project()
        target = _target_project()
        target.module_library["hero"] = {"body": object()}

        result = preview_scene_import(source, "source-separator", target)

        self.assertFalse(result["valid"])
        self.assertIn("malformed_target_module", result["blockers"])

    def test_unrelated_target_modules_do_not_change_module_actions_or_plan(self):
        source = _source_project(module={"body": "red hair, blue eyes"})
        target_a = _target_project()
        target_b = _target_project()
        target_b.module_library["unrelated"] = {"body": "unrelated"}

        result_a = preview_scene_import(source, "source-separator", target_a)
        result_b = preview_scene_import(source, "source-separator", target_b)

        self.assertEqual(result_a["module_actions"], result_b["module_actions"])
        self.assertEqual(result_a["target_freshness_fingerprint"], result_b["target_freshness_fingerprint"])
        self.assertEqual(result_a["plan_id"], result_b["plan_id"])

    def test_duplicate_target_ids_and_same_project_are_rejected(self):
        target = _target_project()
        target.prompt_lines.append(_line("target-line", "duplicate"))
        result = preview_scene_import(_source_project(), "source-separator", target)
        self.assertFalse(result["valid"])
        self.assertIn("ambiguous_target_line_id", result["blockers"])

        source = _source_project()
        same_project = preview_scene_import(source, "source-separator", source)
        self.assertFalse(same_project["valid"])
        self.assertIn("same_project", same_project["blockers"])

    def test_correspondence_and_planned_receipt_are_deterministic_and_path_free(self):
        source = _source_project()
        target = _target_project()
        first = preview_scene_import(source, "source-separator", target)
        second = preview_scene_import(source, "source-separator", target)

        self.assertEqual(first["source_to_target_map"], second["source_to_target_map"])
        self.assertEqual(first["planned_receipt"], second["planned_receipt"])
        self.assertEqual(first["planned_receipt"]["transfer_id"], second["planned_receipt"]["transfer_id"])
        self.assertEqual("source-separator", first["planned_receipt"]["source_separator_id"])
        self.assertEqual("source-line-a", first["source_to_target_map"]["illustrations"][0]["source_line_id"])
        self.assertNotEqual("source-line-a", first["source_to_target_map"]["illustrations"][0]["target_line_id"])
        self.assertNotIn("source_directory", json.dumps(first))
        self.assertNotIn(r"C:\private", json.dumps(first))
        self.assertEqual(0, first["planned_receipt_append_index"])

        target.project_metadata["scene_transfers"] = [{
            "transfer_id": first["planned_receipt"]["transfer_id"],
            "note": "previous receipt",
        }]
        next_transfer = preview_scene_import(source, "source-separator", target)
        self.assertNotEqual(first["planned_receipt"]["transfer_id"], next_transfer["planned_receipt"]["transfer_id"])
        self.assertNotIn(
            next_transfer["planned_receipt"]["transfer_id"],
            {receipt["transfer_id"] for receipt in target.project_metadata["scene_transfers"]},
        )

    def test_malformed_receipt_namespace_blocks_without_replacing_it(self):
        target = _target_project()
        target.project_metadata["scene_transfers"] = "not a receipt list"
        before = copy.deepcopy(target.project_metadata)

        result = preview_scene_import(_source_project(), "source-separator", target)

        self.assertFalse(result["valid"])
        self.assertIn("malformed_receipt_namespace", result["blockers"])
        self.assertEqual(before, target.project_metadata)

    def test_freshness_and_plan_change_for_target_prompt_structure_module_and_receipts(self):
        source = _source_project(module={"body": "red hair, blue eyes"})
        target = _target_project()
        baseline = preview_scene_import(source, "source-separator", target)

        target.prompt_lines[1].current_text = "changed prompt"
        prompt_changed = preview_scene_import(source, "source-separator", target)
        self.assertNotEqual(baseline["target_freshness_fingerprint"], prompt_changed["target_freshness_fingerprint"])
        self.assertNotEqual(baseline["plan_id"], prompt_changed["plan_id"])

        target.prompt_lines[1].current_text = "existing prompt"
        target.prompt_lines[1].deleted = True
        structure_changed = preview_scene_import(source, "source-separator", target)
        self.assertNotEqual(baseline["target_freshness_fingerprint"], structure_changed["target_freshness_fingerprint"])
        target.prompt_lines[1].deleted = False
        target.module_library["hero"] = {"body": "different existing module"}
        module_changed = preview_scene_import(source, "source-separator", target)
        self.assertNotEqual(baseline["target_freshness_fingerprint"], module_changed["target_freshness_fingerprint"])

        target.module_library.clear()
        target.project_metadata["scene_transfers"] = [{"transfer_id": "existing-transfer", "note": "kept"}]
        receipt_changed = preview_scene_import(source, "source-separator", target)
        self.assertNotEqual(baseline["target_freshness_fingerprint"], receipt_changed["target_freshness_fingerprint"])

    def test_invalid_source_projection_is_preserved_as_a_bounded_blocker(self):
        source = _source_project()
        source.prompt_lines.append(_line("source-line-a", "duplicate provenance elsewhere"))

        result = preview_scene_import(source, "source-separator", _target_project())

        self.assertFalse(result["valid"])
        self.assertEqual(["source_projection_invalid"], result["blockers"])
        self.assertIn("ambiguous_illustration_id", result["source_projection_blockers"])
        self.assertLessEqual(len(result["diagnostics"]), 16)

    def test_target_current_index_must_match_physical_prompt_line_order(self):
        cases = {
            "duplicate": [0, 0],
            "stale": [0, 10],
            "out_of_order": [1, 0],
        }
        for name, indexes in cases.items():
            with self.subTest(name=name):
                target = _target_project()
                for line, index in zip(target.prompt_lines, indexes):
                    line.current_index = index
                before = copy.deepcopy(target)

                result = preview_scene_import(_source_project(), "source-separator", target)

                self.assertFalse(result["valid"])
                self.assertIn("stale_target_current_index", result["blockers"])
                self.assertEqual(before, target)

    def test_target_merge_mode_is_exact_bool_and_freshness_input_only(self):
        source = _source_project(module={"body": "red hair, blue eyes"})
        target = _target_project()
        target.module_library = {"hero": {"body": "red hair, blue eyes"}}
        baseline = preview_scene_import(source, "source-separator", target)
        before = copy.deepcopy(target)

        target.merge_by_word_only = False
        changed = preview_scene_import(source, "source-separator", target)

        self.assertTrue(baseline["valid"])
        self.assertTrue(changed["valid"])
        self.assertNotEqual(
            baseline["target_freshness_fingerprint"],
            changed["target_freshness_fingerprint"],
        )
        self.assertNotEqual(baseline["plan_id"], changed["plan_id"])
        self.assertEqual(
            [_without_planned_id(row) for row in baseline["planned_illustrations"]],
            [_without_planned_id(row) for row in changed["planned_illustrations"]],
        )
        self.assertEqual(
            _without_planned_id(baseline["planned_separator"]),
            _without_planned_id(changed["planned_separator"]),
        )
        self.assertEqual(baseline["module_actions"], changed["module_actions"])
        after_previews = copy.deepcopy(target)
        after_previews.merge_by_word_only = True
        self.assertEqual(before, after_previews)

        target.merge_by_word_only = 1
        invalid_mode_before = copy.deepcopy(target)
        invalid = preview_scene_import(source, "source-separator", target)
        self.assertFalse(invalid["valid"])
        self.assertIn("invalid_target_merge_by_word_only", invalid["blockers"])
        self.assertEqual(invalid_mode_before, target)

    def test_invalid_path_shaped_source_handle_is_not_echoed(self):
        result = preview_scene_import(_source_project(), r"C:\private\source.json", _target_project())

        self.assertFalse(result["valid"])
        self.assertIsNone(result["source_separator_id"])
        self.assertNotIn(r"C:\private", json.dumps(result))

    def test_irrelevant_image_candidate_and_variant_state_do_not_affect_plan(self):
        source = _source_project(module={"body": "red hair, blue eyes"})
        target = _target_project()
        first = preview_scene_import(source, "source-separator", target)
        target.prompt_lines[1].image_path = r"C:\images\new.png"
        target.prompt_lines[1].generated_candidates.append({"path": "candidate.png"})
        target.prompt_lines[1].gallery_variants.append({"path": "variant.png"})
        second = preview_scene_import(source, "source-separator", target)

        self.assertEqual(first["target_freshness_fingerprint"], second["target_freshness_fingerprint"])
        self.assertEqual(first["plan_id"], second["plan_id"])

    def test_projection_digest_binds_planned_rows_and_plan_id_binds_reviewed_envelope(self):
        target = _target_project()
        source_a = _source_project(module={"body": "red hair"}, text="red hair")
        source_b = _source_project(module={"body": "red hair"}, text="blue eyes")
        first = preview_scene_import(source_a, "source-separator", target)
        second = preview_scene_import(source_b, "source-separator", target)

        self.assertNotEqual(first["projection_digest"], second["projection_digest"])
        self.assertNotEqual(first["plan_id"], second["plan_id"])

        reviewed = {
            "contract_version": SCENE_IMPORT_PREVIEW_CONTRACT_VERSION,
            "operation": "scene_import",
            "source_scene_fingerprint": first["source_scene_fingerprint"],
            "target_freshness_fingerprint": first["target_freshness_fingerprint"],
            "target_line_count": first["target_line_count"],
            "insertion_index": first["insertion_index"],
            "planned_separator": first["planned_separator"],
            "planned_illustrations": first["planned_illustrations"],
            "resulting_scene_block_order": first["resulting_scene_block_order"],
            "module_actions": first["module_actions"],
            "source_to_target_map": first["source_to_target_map"],
            "planned_receipt": first["planned_receipt"],
            "planned_receipt_append_index": first["planned_receipt_append_index"],
        }
        canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        projection_digest = "sha256:" + hashlib.sha256(canonical(reviewed).encode("utf-8")).hexdigest()
        self.assertEqual(projection_digest, first["projection_digest"])
        unsigned = {key: value for key, value in first.items() if key != "plan_id"}
        plan_id = "sha256:" + hashlib.sha256(canonical(unsigned).encode("utf-8")).hexdigest()
        self.assertEqual(plan_id, first["plan_id"])

    def test_preview_is_json_safe_and_preserves_all_project_state(self):
        source = _source_project()
        target = _target_project()
        source_before = copy.deepcopy(source)
        target_before = copy.deepcopy(target)

        result = preview_scene_import(source, "source-separator", target)

        json.dumps(result, ensure_ascii=False, allow_nan=False)
        self.assertEqual(source_before, source)
        self.assertEqual(target_before, target)
        self.assertEqual(source_before.module_library, source.module_library)
        self.assertEqual(target_before.module_library, target.module_library)
        self.assertEqual(source_before.project_metadata, source.project_metadata)
        self.assertEqual(target_before.project_metadata, target.project_metadata)
        self.assertEqual(source_before.prompt_lines, source.prompt_lines)
        self.assertEqual(target_before.prompt_lines, target.prompt_lines)
        self.assertEqual(source_before.nodes, source.nodes)
        self.assertEqual(target_before.nodes, target.nodes)
        self.assertEqual(source_before.edges, source.edges)
        self.assertEqual(target_before.edges, target.edges)

    def test_target_malformed_persisted_line_state_blocks(self):
        target = _target_project()
        target.prompt_lines[1].tokens = "not a list"

        result = preview_scene_import(_source_project(), "source-separator", target)

        self.assertFalse(result["valid"])
        self.assertIn("malformed_target_line_state", result["blockers"])

    def test_invalid_target_container_blocks_without_mutation(self):
        source = _source_project()
        before = copy.deepcopy(source)

        result = preview_scene_import(source, "source-separator", None)

        self.assertFalse(result["valid"])
        self.assertIn("invalid_target_project", result["blockers"])
        self.assertEqual(before, source)


if __name__ == "__main__":
    unittest.main()
