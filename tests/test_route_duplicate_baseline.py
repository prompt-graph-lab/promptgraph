import copy
import os
import tempfile
import unittest

from core.io import load_project_from_json, save_project_to_json
from core.project import Project, PromptLine
from core.route_operations import (
    duplicate_route_as_baseline,
    get_route_duplicate_ui_state,
    resolve_route_block,
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


def _project():
    separator = _line(
        "route_a",
        "Route A",
        line_type="separator",
        separator_label="Route A",
        separator_color="blue",
    )
    main = _line(
        "line_a",
        "A prompt",
        image_path="fallback.png",
        generated_image_path="generated.png",
        selected_candidate_path="selected.png",
        negative_prompt="avoid text",
        source_generation_info={"engine": "keep"},
        lineage_info={"parent": "keep"},
        generated_candidates=[
            {
                "path": "selected.png",
                "prompt_text": "Candidate B prompt",
                "negative_prompt": "avoid Candidate B",
                "steps": 28,
                "seed": 1234,
                "source": "candidate_generation",
            },
            {"path": "candidate.png", "trashed": True},
        ],
        gallery_variants=[{"path": "variant.png", "kind": "gallery_variant"}],
    )
    main.custom_runtime_metadata = {"preserve": True}
    workbench = _line(
        "workbench_a",
        "Workbench prompt",
        line_type="workbench",
        workbench_source_line_id="line_a",
        workbench_title="Keep title",
        workbench_note="Keep note",
        workbench_status="preview",
        generated_candidates=[{"path": "workbench-candidate.png"}],
        gallery_variants=[{"path": "workbench-variant.png", "kind": "gallery_variant"}],
    )
    deleted = _line(
        "line_deleted",
        "Deleted member",
        deleted=True,
        image_path="deleted.png",
        generated_candidates=[{"path": "deleted-candidate.png"}],
    )
    next_separator = _line(
        "route_b",
        "Route B",
        line_type="separator",
        separator_label="Route B",
    )
    next_line = _line("line_b", "B prompt")
    project = Project(
        prompt_lines=[separator, main, workbench, deleted, next_separator, next_line],
        project_metadata={"unknown": {"preserve": True}},
    )
    for index, line in enumerate(project.prompt_lines):
        line.current_index = index
    return project


def _deterministic_id_factory(source_id, role):
    return f"new_{role}_{source_id}"


class RouteDuplicateBaselineTests(unittest.TestCase):
    def test_duplicates_contiguous_route_with_fresh_ids_and_preserved_source(self):
        project = _project()
        source_before = copy.deepcopy(project)

        result = duplicate_route_as_baseline(
            project,
            "route_a",
            label="Route A Baseline",
            id_factory=_deterministic_id_factory,
            now="2026-07-14T00:00:00+00:00",
        )

        self.assertTrue(result["duplicated"])
        self.assertEqual("new_separator_route_a", result["new_route_handle"])
        self.assertEqual(
            [
                "route_a",
                "line_a",
                "workbench_a",
                "line_deleted",
                "new_separator_route_a",
                "new_line_line_a",
                "new_workbench_workbench_a",
                "new_line_line_deleted",
                "route_b",
                "line_b",
            ],
            [line.id for line in project.prompt_lines],
        )
        self.assertEqual(list(range(len(project.prompt_lines))), [line.current_index for line in project.prompt_lines])
        self.assertEqual(source_before.prompt_lines[:4], project.prompt_lines[:4])
        self.assertEqual(
            ["new_separator_route_a", "new_line_line_a", "new_workbench_workbench_a", "new_line_line_deleted"],
            result["new_line_ids"],
        )
        self.assertEqual("Route A Baseline", project.prompt_lines[4].separator_label)
        self.assertTrue(project.prompt_lines[7].deleted)
        self.assertEqual("route_b", resolve_route_block(project, "route_b").route_handle)
        self.assertEqual(
            [line.id for line in project.prompt_lines[4:8]],
            [line.id for line in resolve_route_block(project, "new_separator_route_a").block_lines],
        )

    def test_clears_candidate_state_but_retains_resolved_main_path_and_metadata(self):
        project = _project()
        result = duplicate_route_as_baseline(
            project,
            "route_a",
            id_factory=_deterministic_id_factory,
            now="2026-07-14T00:00:00+00:00",
        )
        duplicate = next(line for line in project.prompt_lines if line.id == result["line_id_map"]["line_a"])

        self.assertEqual("selected.png", duplicate.image_path)
        self.assertIsNone(duplicate.selected_candidate_path)
        self.assertIsNone(duplicate.generated_image_path)
        self.assertEqual([], duplicate.generated_candidates)
        self.assertEqual([], duplicate.gallery_variants)
        self.assertEqual("A prompt", duplicate.current_text)
        self.assertEqual("avoid text", duplicate.negative_prompt)
        self.assertEqual("derived_candidate", duplicate.source_generation_info["source_kind"])
        self.assertEqual("selected.png", duplicate.source_generation_info["source_image_path"])
        self.assertEqual("Candidate B prompt", duplicate.source_generation_info["source_prompt"])
        self.assertEqual("avoid Candidate B", duplicate.source_generation_info["source_negative_prompt"])
        self.assertEqual("Candidate B prompt", duplicate.source_generation_info["source_raw_metadata"]["prompt_text"])
        self.assertEqual("selected.png", duplicate.lineage_info["adopted_candidate_path"])
        self.assertEqual("keep", duplicate.lineage_info["parent"])
        self.assertEqual("duplicate_route_as_baseline", duplicate.lineage_info["operation"])
        self.assertEqual("line_a", duplicate.duplicated_from)
        self.assertEqual({"unknown": {"preserve": True}}, project.project_metadata)
        self.assertFalse(os.path.exists("selected.png"))

    def test_missing_selected_candidate_record_uses_safe_fallback_and_diagnostic(self):
        project = _project()
        project.prompt_lines[1].generated_candidates = [{"path": "other.png", "prompt_text": "Other"}]

        result = duplicate_route_as_baseline(
            project,
            "route_a",
            id_factory=_deterministic_id_factory,
        )
        duplicate = next(line for line in project.prompt_lines if line.id == result["line_id_map"]["line_a"])

        self.assertTrue(result["duplicated"])
        self.assertTrue(any("selected Candidate record not found" in diagnostic for diagnostic in result["diagnostics"]))
        self.assertEqual("derived_candidate", duplicate.source_generation_info["source_kind"])
        self.assertEqual("selected.png", duplicate.source_generation_info["source_image_path"])
        self.assertEqual("A prompt", duplicate.source_generation_info["source_prompt"])
        self.assertEqual("avoid text", duplicate.source_generation_info["source_negative_prompt"])
        self.assertEqual("selected.png", duplicate.lineage_info["adopted_candidate_path"])

    def test_workbench_source_is_remapped_and_experimental_state_is_cleared(self):
        project = _project()
        result = duplicate_route_as_baseline(
            project,
            "route_a",
            id_factory=_deterministic_id_factory,
        )
        duplicate = next(line for line in project.prompt_lines if line.id == result["line_id_map"]["workbench_a"])

        self.assertEqual(result["line_id_map"]["line_a"], duplicate.workbench_source_line_id)
        self.assertEqual("Workbench prompt", duplicate.current_text)
        self.assertEqual("Keep title", duplicate.workbench_title)
        self.assertEqual("Keep note", duplicate.workbench_note)
        self.assertIsNone(duplicate.workbench_status)
        self.assertEqual([], duplicate.generated_candidates)
        self.assertEqual([], duplicate.gallery_variants)
        self.assertIsNone(duplicate.selected_candidate_path)
        self.assertEqual("workbench-candidate.png", next(line for line in project.prompt_lines if line.id == "workbench_a").generated_candidates[0]["path"])

    def test_empty_and_last_route_can_be_duplicated(self):
        project = Project(
            prompt_lines=[
                _line("route_empty", "Empty", line_type="separator", separator_label="Empty"),
                _line("route_last", "Last", line_type="separator", separator_label="Last"),
                _line("last_line", "Last prompt"),
            ]
        )
        result = duplicate_route_as_baseline(
            project,
            "route_empty",
            label="Empty Copy",
            id_factory=_deterministic_id_factory,
        )
        self.assertTrue(result["duplicated"])
        self.assertEqual(
            ["route_empty", "new_separator_route_empty", "route_last", "last_line"],
            [line.id for line in project.prompt_lines],
        )

    def test_invalid_inputs_leave_project_unchanged(self):
        cases = []

        project = _project()
        project.prompt_lines[0].deleted = True
        cases.append((project, "route_a", {}, "separator is deleted"))

        project = _project()
        project.project_metadata["route_removals"] = [{
            "id": "remove-1",
            "route_handle": "route_a",
            "line_ids": ["route_a"],
            "pre_remove_deleted": {"route_a": False},
            "changed_to_deleted_line_ids": ["route_a"],
            "status": "active",
        }]
        cases.append((project, "route_a", {}, "active removal record exists"))

        project = _project()
        project.prompt_lines[2].workbench_source_line_id = "missing"
        cases.append((project, "route_a", {}, "malformed Workbench source"))

        project = _project()
        cases.append((project, "route_a", {"label": "   "}, "invalid label"))

        for project, route_handle, kwargs, reason in cases:
            with self.subTest(reason=reason):
                before = copy.deepcopy(project)
                result = duplicate_route_as_baseline(
                    project,
                    route_handle,
                    id_factory=_deterministic_id_factory,
                    **kwargs,
                )
                self.assertFalse(result["duplicated"])
                self.assertEqual(reason, result["reason"])
                self.assertEqual(before, project)

    def test_id_collision_and_duplicate_source_ids_are_rejected(self):
        project = _project()
        before = copy.deepcopy(project)
        result = duplicate_route_as_baseline(
            project,
            "route_a",
            id_factory=lambda source_id, role: "line_a",
        )
        self.assertFalse(result["duplicated"])
        self.assertEqual("duplicate ID collision", result["reason"])
        self.assertEqual(before, project)

        project = _project()
        project.prompt_lines[2].id = "line_a"
        before = copy.deepcopy(project)
        result = duplicate_route_as_baseline(project, "route_a", id_factory=_deterministic_id_factory)
        self.assertFalse(result["duplicated"])
        self.assertEqual("duplicate ID collision", result["reason"])
        self.assertEqual(before, project)

    def test_ui_state_preserves_focus_and_inherits_source_collapse(self):
        project = _project()
        result = duplicate_route_as_baseline(
            project,
            "route_a",
            id_factory=_deterministic_id_factory,
        )
        new_route = result["new_route_handle"]
        state = get_route_duplicate_ui_state(
            project,
            source_route_handle="route_a",
            new_route_handle=new_route,
            focused_line_id="line_a",
            highlighted_line_id="line_b",
            expanded_line_id="workbench_a",
            collapsed_routes={"route_a": False, "route_b": True},
        )
        self.assertEqual("line_a", state["focused_line_id"])
        self.assertEqual("line_b", state["highlighted_line_id"])
        self.assertEqual("workbench_a", state["gallery_expanded_line_id"])
        self.assertEqual(new_route, state["gallery_selected_route_separator_id"])
        self.assertFalse(state["gallery_collapsed_routes"]["route_a"])
        self.assertFalse(state["gallery_collapsed_routes"][new_route])
        self.assertTrue(state["gallery_collapsed_routes"]["route_b"])

        default_state = get_route_duplicate_ui_state(
            project,
            source_route_handle="route_a",
            new_route_handle=new_route,
            collapsed_routes={},
        )
        self.assertTrue(default_state["gallery_collapsed_routes"][new_route])

        invalid_state = get_route_duplicate_ui_state(
            project,
            source_route_handle="route_a",
            new_route_handle=new_route,
            focused_line_id="missing",
            highlighted_line_id="deleted-member",
            expanded_line_id="missing",
            collapsed_routes={"route_a": True},
        )
        self.assertIsNone(invalid_state["focused_line_id"])
        self.assertIsNone(invalid_state["highlighted_line_id"])
        self.assertIsNone(invalid_state["gallery_expanded_line_id"])

    def test_round_trip_retains_duplicate_structure_and_metadata(self):
        project = _project()
        result = duplicate_route_as_baseline(
            project,
            "route_a",
            id_factory=_deterministic_id_factory,
            now="2026-07-14T00:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "project.json")
            save_project_to_json(project, path)
            loaded = load_project_from_json(path)

        duplicated_separator = next(line for line in loaded.prompt_lines if line.id == result["new_route_handle"])
        duplicated_workbench = next(line for line in loaded.prompt_lines if line.id == result["line_id_map"]["workbench_a"])
        duplicated_line = next(line for line in loaded.prompt_lines if line.id == result["line_id_map"]["line_a"])
        self.assertEqual("Route A Baseline", duplicated_separator.separator_label)
        self.assertEqual(result["line_id_map"]["line_a"], duplicated_workbench.workbench_source_line_id)
        self.assertEqual("selected.png", duplicated_line.image_path)
        self.assertEqual([], duplicated_line.generated_candidates)
        self.assertEqual([], duplicated_line.gallery_variants)
        self.assertEqual("derived_candidate", duplicated_line.source_generation_info["source_kind"])
        self.assertEqual("Candidate B prompt", duplicated_line.source_generation_info["source_prompt"])
        self.assertEqual("selected.png", duplicated_line.source_generation_info["source_image_path"])
        self.assertEqual({"preserve": True}, loaded.project_metadata["unknown"])
        self.assertNotIn("route_removals", loaded.project_metadata)


if __name__ == "__main__":
    unittest.main()
