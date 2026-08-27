import copy
import os
import tempfile
import unittest

from core.io import load_project_from_json, save_project_to_json
from core.project import Project, PromptLine
from core.route_operations import (
    get_active_route_removal_record,
    get_active_route_removal_records,
    get_route_removal_diagnostics,
    get_route_remove_ui_state,
    list_active_route_removal_records,
    remove_route_block,
    resolve_route_block,
    restore_removed_route,
    restore_route_block,
)


def _line(line_id, text="prompt", *, line_type=None, deleted=False, **fields):
    return PromptLine(
        id=line_id,
        original_file_name=line_id,
        original_index=0,
        current_index=0,
        original_text=text,
        current_text=text,
        tokens=[text],
        line_type=line_type,
        deleted=deleted,
        **fields,
    )


def _route_project():
    separator = _line(
        "route_a",
        "Route A",
        line_type="separator",
        separator_label="Route A",
    )
    main_line = _line(
        "line_a",
        "A prompt",
        image_path="source.png",
        generated_candidates=[{"path": "candidate.png", "tag": "keep"}],
        gallery_variants=[{"path": "variant.png", "kind": "gallery_variant"}],
        lineage_info={"parent": "source"},
    )
    workbench = _line(
        "workbench_a",
        "Workbench prompt",
        line_type="workbench",
        workbench_source_line_id="line_a",
    )
    individually_deleted = _line("line_deleted", "Previously deleted", deleted=True)
    next_separator = _line("route_b", "Route B", line_type="separator")
    next_line = _line("line_b", "B prompt")
    return Project(
        prompt_lines=[separator, main_line, workbench, individually_deleted, next_separator, next_line],
        project_metadata={"existing": {"keep": True}},
    )


class RouteRemoveRestoreTests(unittest.TestCase):
    def test_remove_trashes_the_contiguous_block_and_persists_the_pre_remove_mask(self):
        project = _route_project()
        original_order = [line.id for line in project.prompt_lines]
        original_main = project.prompt_lines[1]
        original_candidates = list(original_main.generated_candidates)
        original_variants = list(original_main.gallery_variants)
        original_lineage = dict(original_main.lineage_info)

        result = remove_route_block(
            project,
            "route_a",
            now="2026-07-14T00:00:00+00:00",
            removal_id="route_remove_test",
        )

        self.assertTrue(result["removed"])
        self.assertEqual("route_remove_test", result["record_id"])
        self.assertEqual(
            ["route_a", "line_a", "workbench_a", "line_deleted"],
            result["affected_line_ids"],
        )
        self.assertEqual(["route_a", "line_a", "workbench_a"], result["changed_to_deleted_line_ids"])
        self.assertEqual(original_order, [line.id for line in project.prompt_lines])
        self.assertTrue(all(line.deleted for line in project.prompt_lines[:4]))
        self.assertFalse(project.prompt_lines[4].deleted)
        self.assertEqual(
            {
                "route_a": False,
                "line_a": False,
                "workbench_a": False,
                "line_deleted": True,
            },
            result["record"]["pre_remove_deleted"],
        )
        self.assertEqual(original_candidates, original_main.generated_candidates)
        self.assertEqual(original_variants, original_main.gallery_variants)
        self.assertEqual(original_lineage, original_main.lineage_info)
        self.assertEqual(["route_remove_test"], [record["id"] for record in get_active_route_removal_records(project)])
        self.assertEqual(["line_deleted"], result["already_deleted_line_ids"])

        duplicate = remove_route_block(project, "route_a")
        self.assertFalse(duplicate["removed"])
        self.assertEqual("active removal record already exists", duplicate["reason"])

    def test_restore_uses_the_mask_and_leaves_previously_deleted_lines_deleted(self):
        project = _route_project()
        remove_route_block(project, "route_a", now="2026-07-14T00:00:00+00:00", removal_id="remove-1")
        project.project_metadata["route_removals"][0]["future_record_field"] = {
            "keep": True,
        }

        # Individual restore is still allowed inside Trash. Route restore must
        # not re-delete that line, even though it was deleted before the Route remove.
        next(line for line in project.prompt_lines if line.id == "line_deleted").deleted = False
        result = restore_route_block(project, "route_a", now="2026-07-14T00:01:00+00:00")

        self.assertTrue(result["restored"])
        self.assertTrue(result["consumed"])
        self.assertEqual(["route_a", "line_a", "workbench_a"], result["restored_line_ids"])
        self.assertEqual([], result["preserved_deleted_line_ids"])
        self.assertTrue(all(not line.deleted for line in project.prompt_lines[:4]))
        self.assertEqual([], get_active_route_removal_records(project))
        self.assertEqual("consumed", result["record"]["status"])
        self.assertEqual("2026-07-14T00:01:00+00:00", result["record"]["restored_at"])
        self.assertEqual({"keep": True}, result["record"]["future_record_field"])

    def test_partial_restore_reports_missing_lines_and_restores_remaining_lines(self):
        project = _route_project()
        remove_route_block(project, "route_a", removal_id="partial-remove")
        project.prompt_lines.pop(1)

        result = restore_removed_route(project, "partial-remove")

        self.assertTrue(result["restored"])
        self.assertEqual("partial restore with missing lines", result["reason"])
        self.assertEqual(["line_a"], result["missing_line_ids"])
        self.assertIn("line_a", result["diagnostics"][0])
        self.assertFalse(next(line for line in project.prompt_lines if line.id == "route_a").deleted)
        self.assertFalse(next(line for line in project.prompt_lines if line.id == "workbench_a").deleted)
        self.assertEqual([], get_active_route_removal_records(project))

    def test_malformed_route_namespace_and_unknown_metadata_are_not_overwritten(self):
        project = _route_project()
        project.project_metadata["future_namespace"] = {"keep": ["value"]}
        project.project_metadata["route_removals"] = {"legacy": "malformed"}
        before_metadata = dict(project.project_metadata)

        remove_result = remove_route_block(project, "route_a")
        restore_result = restore_route_block(project, "route_a")

        self.assertFalse(remove_result["removed"])
        self.assertEqual("malformed removal record", remove_result["reason"])
        self.assertFalse(restore_result["restored"])
        self.assertEqual("malformed removal record", restore_result["reason"])
        self.assertEqual(before_metadata, project.project_metadata)

        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = os.path.join(temp_dir, "project.json")
            save_project_to_json(project, project_path)
            loaded = load_project_from_json(project_path)
        self.assertEqual(before_metadata["existing"], loaded.project_metadata["existing"])
        self.assertEqual(before_metadata["future_namespace"], loaded.project_metadata["future_namespace"])
        self.assertEqual(before_metadata["route_removals"], loaded.project_metadata["route_removals"])

    def test_malformed_active_record_is_diagnosed_without_creating_a_second_record(self):
        project = _route_project()
        project.project_metadata["route_removals"] = [{
            "id": "malformed-active",
            "route_handle": "route_a",
            "status": "active",
        }]

        result = remove_route_block(project, "route_a", removal_id="replacement")

        self.assertFalse(result["removed"])
        self.assertEqual("malformed removal record", result["reason"])
        self.assertTrue(result["diagnostics"])
        self.assertEqual(
            ["malformed-active"],
            [record.get("id") for record in project.project_metadata["route_removals"]],
        )

    def test_duplicate_removal_id_is_hidden_and_restore_is_rejected_without_mutation(self):
        project = _route_project()
        remove_route_block(project, "route_a", removal_id="duplicate-id")
        duplicate_record = copy.deepcopy(project.project_metadata["route_removals"][0])
        duplicate_record["route_handle"] = "route_b"
        duplicate_record["separator_line_id"] = "route_b"
        duplicate_record["future_record_field"] = {"keep": "both"}
        project.project_metadata["route_removals"].append(duplicate_record)
        before_metadata = copy.deepcopy(project.project_metadata)
        before_deleted = [line.deleted for line in project.prompt_lines]

        self.assertEqual([], get_active_route_removal_records(project))
        self.assertIn("duplicate Route removal id: duplicate-id", get_route_removal_diagnostics(project))

        result = restore_removed_route(project, "duplicate-id")
        by_handle = restore_removed_route(project, "route_a")

        self.assertFalse(result["restored"])
        self.assertEqual("duplicate removal id", result["reason"])
        self.assertFalse(by_handle["restored"])
        self.assertEqual("duplicate removal id", by_handle["reason"])
        self.assertEqual(before_metadata, project.project_metadata)
        self.assertEqual(before_deleted, [line.deleted for line in project.prompt_lines])

    def test_duplicate_active_route_handle_is_hidden_and_restore_is_rejected(self):
        project = _route_project()
        remove_route_block(project, "route_a", removal_id="route-a-one")
        duplicate_record = copy.deepcopy(project.project_metadata["route_removals"][0])
        duplicate_record["id"] = "route-a-two"
        duplicate_record["future_record_field"] = {"keep": True}
        project.project_metadata["route_removals"].append(duplicate_record)
        before_metadata = copy.deepcopy(project.project_metadata)
        before_deleted = [line.deleted for line in project.prompt_lines]

        self.assertEqual([], get_active_route_removal_records(project))
        self.assertIn("ambiguous active Route handle: route_a", get_route_removal_diagnostics(project))

        by_handle = restore_removed_route(project, "route_a")
        by_id = restore_removed_route(project, "route-a-one")

        self.assertFalse(by_handle["restored"])
        self.assertEqual("ambiguous active Route handle", by_handle["reason"])
        self.assertFalse(by_id["restored"])
        self.assertEqual("ambiguous active Route handle", by_id["reason"])
        self.assertEqual(before_metadata, project.project_metadata)
        self.assertEqual(before_deleted, [line.deleted for line in project.prompt_lines])

    def test_multiple_records_are_selected_by_removal_id_and_one_active_record_per_route(self):
        project = _route_project()
        remove_route_block(project, "route_a", removal_id="route-a-first")
        restore_removed_route(project, "route-a-first")
        remove_route_block(project, "route_a", removal_id="route-a-second")
        remove_route_block(project, "route_b", removal_id="route-b-first")

        active_ids = [record["id"] for record in list_active_route_removal_records(project)]
        self.assertEqual(["route-a-second", "route-b-first"], active_ids)
        self.assertEqual("route-a-second", get_active_route_removal_record(project, "route_a")["id"])
        duplicate = remove_route_block(project, "route_a", removal_id="route-a-third")
        self.assertFalse(duplicate["removed"])
        self.assertEqual("active removal record already exists", duplicate["reason"])

        restored = restore_removed_route(project, "route-b-first")

        self.assertTrue(restored["restored"])
        self.assertEqual("route-b-first", restored["removal_id"])
        self.assertIsNone(get_active_route_removal_record(project, "route_b"))
        self.assertEqual("route-a-second", get_active_route_removal_record(project, "route_a")["id"])

    def test_route_remove_ui_state_clears_removed_line_state_and_preserves_other_route_selection(self):
        project = _route_project()
        remove_route_block(project, "route_a", removal_id="ui-state")

        state = get_route_remove_ui_state(
            project,
            route_handle="route_a",
            focused_line_id="line_a",
            highlighted_line_id="line_b",
            expanded_line_id="line_a",
            selected_route_separator_id="route_b",
        )

        self.assertIsNone(state["focused_line_id"])
        self.assertEqual("line_b", state["highlighted_line_id"])
        self.assertIsNone(state["gallery_expanded_line_id"])
        self.assertEqual("route_b", state["gallery_selected_route_separator_id"])
        self.assertEqual("route_a", state["removed_route_handle"])

    def test_restore_preserves_a_pre_remove_deleted_line_when_it_was_not_individually_restored(self):
        project = _route_project()
        remove_route_block(project, "route_a", removal_id="remove-2")

        result = restore_route_block(project, "route_a", removal_id="remove-2")

        self.assertTrue(result["restored"])
        self.assertEqual(["route_a", "line_a", "workbench_a"], result["restored_line_ids"])
        self.assertEqual(["line_deleted"], result["preserved_deleted_line_ids"])
        self.assertFalse(project.prompt_lines[0].deleted)
        self.assertFalse(project.prompt_lines[1].deleted)
        self.assertFalse(project.prompt_lines[2].deleted)
        self.assertTrue(project.prompt_lines[3].deleted)

    def test_save_load_preserves_active_removal_record_for_later_restore(self):
        project = _route_project()
        remove_route_block(project, "route_a", removal_id="persisted-remove")

        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = os.path.join(temp_dir, "project.json")
            save_project_to_json(project, project_path)
            loaded = load_project_from_json(project_path)

        self.assertEqual(["persisted-remove"], [record["id"] for record in get_active_route_removal_records(loaded)])
        self.assertTrue(all(line.deleted for line in loaded.prompt_lines[:4]))
        self.assertTrue(resolve_route_block(loaded, "route_a").deleted)

        result = restore_route_block(loaded, "route_a")

        self.assertTrue(result["restored"])
        self.assertFalse(all(line.deleted for line in loaded.prompt_lines[:3]))
        self.assertTrue(loaded.prompt_lines[3].deleted)
        self.assertEqual([], get_active_route_removal_records(loaded))

    def test_invalid_or_missing_route_does_not_mutate_metadata_or_lines(self):
        project = _route_project()
        before_deleted = [line.deleted for line in project.prompt_lines]

        missing = remove_route_block(project, "missing")
        not_separator = remove_route_block(project, "line_a")

        self.assertFalse(missing["removed"])
        self.assertEqual("separator not found", missing["reason"])
        self.assertFalse(not_separator["removed"])
        self.assertEqual("target is not separator", not_separator["reason"])
        self.assertEqual(before_deleted, [line.deleted for line in project.prompt_lines])
        self.assertNotIn("route_removals", project.project_metadata)

    def test_partial_restore_consumes_record_when_record_line_is_missing(self):
        project = _route_project()
        remove_route_block(project, "route_a", removal_id="missing-line")
        project.prompt_lines.pop(1)
        before_deleted = [line.deleted for line in project.prompt_lines]

        result = restore_route_block(project, "route_a")

        self.assertTrue(result["restored"])
        self.assertEqual("partial restore with missing lines", result["reason"])
        self.assertEqual(["line_a"], result["missing_line_ids"])
        self.assertNotEqual(before_deleted, [line.deleted for line in project.prompt_lines])
        self.assertEqual([], get_active_route_removal_records(project))

    def test_restore_with_no_changed_lines_remaining_is_distinct_and_keeps_record(self):
        project = _route_project()
        remove_route_block(project, "route_a", removal_id="no-lines")
        project.prompt_lines = [
            line for line in project.prompt_lines if line.id == "line_deleted"
        ]

        result = restore_removed_route(project, "no-lines")

        self.assertFalse(result["restored"])
        self.assertEqual("no restorable lines", result["reason"])
        self.assertEqual(["route_a", "line_a", "workbench_a"], result["missing_line_ids"])
        self.assertEqual(["no-lines"], [record["id"] for record in get_active_route_removal_records(project)])


if __name__ == "__main__":
    unittest.main()
