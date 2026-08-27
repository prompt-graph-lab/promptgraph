import copy
from pathlib import Path
import tempfile
import unittest

from core.gallery_generation import (
    build_selected_routes_generation_plan,
    execute_gallery_generation_plan,
    ingest_gallery_generation_outputs,
    validate_selected_routes_generation_submit,
)
from core.project import Project, PromptLine
from core.route_operations import move_route_block, remove_route_block


def _line(line_id, text="prompt", *, line_type=None, deleted=False, **fields):
    return PromptLine(
        id=line_id,
        original_file_name=line_id,
        original_index=0,
        current_index=0,
        original_text=text,
        current_text=text,
        tokens=[text] if text else [],
        line_type=line_type,
        deleted=deleted,
        **fields,
    )


def _project():
    lines = [
        _line("route_a", "Route A", line_type="separator", separator_label="Route A", separator_color="blue"),
        _line("a1", "A1 prompt", image_path=None, negative_prompt="A1 negative"),
        _line("a_workbench", "Workbench", line_type="workbench"),
        _line("a2", "A2 prompt", image_path="a2-main.png"),
        _line("a_deleted", "deleted", deleted=True),
        _line("route_b", "Route B", line_type="separator", separator_label="Route B"),
        _line("b1", "B1 prompt"),
        _line("route_c", "Route C", line_type="separator", separator_label="Route C", separator_color="green"),
        _line("c1", "C1 prompt"),
    ]
    for index, line in enumerate(lines):
        line.current_index = index
    return Project(prompt_lines=lines)


def _builder(line, run_index):
    return {
        "workflow_json": {
            "line": line.id,
            "prompt": line.current_text,
            "negative": line.negative_prompt,
            "run": run_index,
            "model": "model.safetensors",
        },
        "warning": "",
    }


def _plan(project, selected=("route_c", "route_a"), **kwargs):
    options = kwargs.pop("generation_options", {"model": "model.safetensors", "steps": 20})
    return build_selected_routes_generation_plan(
        project,
        list(selected),
        run_count=kwargs.pop("run_count", 1),
        generation_options=options,
        project_path=kwargs.pop("project_path", "C:/project/project.json"),
        request_builder=kwargs.pop("request_builder", _builder),
        **kwargs,
    )


def _candidate_factory(path, line, request):
    return {
        "path": path,
        "created_at": "2026-07-15T00:00:00+00:00",
        "source": "gallery_global_generate",
        "origin_line_id": line.id,
        "origin_line_index": line.current_index,
        "run_index": request["run_index"],
        "prompt_text": line.current_text,
        "negative_prompt": line.negative_prompt,
    }


def _append_candidates(line, records):
    existing = line.generated_candidates if isinstance(line.generated_candidates, list) else []
    seen = {item.get("path") for item in existing if isinstance(item, dict)}
    line.generated_candidates = existing + [item for item in records if item.get("path") not in seen]


class SelectedRoutesGenerationPlanTests(unittest.TestCase):
    def test_plan_uses_physical_project_and_route_order(self):
        project = _project()
        project.prompt_lines[1].current_index = 90
        project.prompt_lines[3].current_index = 1
        project.prompt_lines[8].current_index = 2
        before = copy.deepcopy(project)

        plan = _plan(project, selected=("route_c", "route_a"), run_count=2)

        self.assertTrue(plan["valid"])
        self.assertEqual(["route_a", "route_c"], plan["resolved_route_handles"])
        self.assertEqual(["a1", "a2", "c1"], plan["target_line_ids"])
        self.assertEqual(
            ["a1", "a1", "a2", "a2", "c1", "c1"],
            [request["source_line_id"] for request in plan["request_plan"]],
        )
        self.assertNotIn("b1", plan["target_line_ids"])
        self.assertEqual(before, project)

    def test_target_policy_excludes_special_deleted_and_duplicate_lines_but_includes_image_less(self):
        project = _project()
        project.prompt_lines.insert(4, _line("a2", "duplicate A2"))

        plan = _plan(project, selected=("route_a",))

        self.assertIn("a1", plan["target_line_ids"])
        self.assertIsNone(project.prompt_lines[1].image_path)
        self.assertNotIn("a2", plan["target_line_ids"])
        self.assertNotIn("a_workbench", plan["target_line_ids"])
        self.assertNotIn("a_deleted", plan["target_line_ids"])
        self.assertTrue(any("duplicate or ambiguous Line id" in item for item in plan["diagnostics"]))
        self.assertFalse(plan["valid"])

    def test_empty_and_invalid_selections_are_safe(self):
        empty = _plan(_project(), selected=())
        self.assertFalse(empty["valid"])
        self.assertEqual("Selected Routesがありません。", empty["reason"])
        self.assertEqual([], empty["request_plan"])

        project = _project()
        project.prompt_lines[5].deleted = True
        invalid = _plan(project, selected=("missing", "a1", "route_b", "route_c"))
        self.assertEqual(["route_c"], invalid["resolved_route_handles"])
        self.assertEqual(["c1"], invalid["target_line_ids"])
        self.assertTrue(invalid["valid"])
        self.assertGreaterEqual(len(invalid["diagnostics"]), 3)

    def test_one_selected_route_matches_its_physical_active_normal_members(self):
        plan = _plan(_project(), selected=("route_a",))
        self.assertEqual(["a1", "a2"], plan["target_line_ids"])
        self.assertEqual(1, plan["selected_route_count"])
        self.assertEqual(2, plan["request_count"])

    def test_full_prompt_and_negative_prompt_changes_make_preview_stale(self):
        project = _project()
        project.prompt_lines[1].current_text = "p" * 300
        project.prompt_lines[1].negative_prompt = "n" * 300
        stored = _plan(project, selected=("route_a",))

        project.prompt_lines[1].current_text = "p" * 299 + "x"
        prompt_changed = _plan(project, selected=("route_a",))
        self.assertNotEqual(stored["signature"], prompt_changed["signature"])

        project.prompt_lines[1].current_text = "p" * 300
        project.prompt_lines[1].negative_prompt = "n" * 299 + "x"
        negative_changed = _plan(project, selected=("route_a",))
        self.assertNotEqual(stored["signature"], negative_changed["signature"])

    def test_signature_tracks_structure_selection_project_path_and_request_options(self):
        base_project = _project()
        base = _plan(base_project, selected=("route_a", "route_c"))

        moved_project = _project()
        move_route_block(moved_project, "route_c", "up")
        self.assertNotEqual(base["signature"], _plan(moved_project, selected=("route_a", "route_c"))["signature"])

        removed_project = _project()
        remove_route_block(removed_project, "route_c", removal_id="remove-c")
        self.assertNotEqual(base["signature"], _plan(removed_project, selected=("route_a", "route_c"))["signature"])
        self.assertNotEqual(base["signature"], _plan(_project(), selected=("route_a",))["signature"])
        self.assertNotEqual(base["signature"], _plan(_project(), project_path="D:/other.json")["signature"])

        for key, value in (
            ("workflow", "other.json"),
            ("model", "other.safetensors"),
            ("sampler", "euler"),
            ("steps", 30),
            ("seed_mode", "fixed"),
            ("batch_size", 4),
            ("output_directory", "D:/outputs"),
        ):
            with self.subTest(key=key):
                changed = _plan(_project(), generation_options={key: value})
                self.assertNotEqual(base["signature"], changed["signature"])

    def test_preflight_builder_failure_blocks_every_request(self):
        calls = []

        def builder(line, run_index):
            calls.append((line.id, run_index))
            if line.id == "a2":
                raise ValueError("invalid workflow")
            return _builder(line, run_index)

        plan = _plan(_project(), selected=("route_a",), request_builder=builder)
        submitted = []
        result = execute_gallery_generation_plan(
            _project(),
            plan,
            submitter=lambda request: submitted.append(request) or ["out.png"],
            candidate_factory=_candidate_factory,
            candidate_appender=_append_candidates,
        )

        self.assertEqual([("a1", 1), ("a2", 1)], calls)
        self.assertFalse(plan["valid"])
        self.assertEqual([], submitted)
        self.assertEqual(0, result["submitted_count"])

    def test_cheap_plan_skips_builder_and_full_preflight_builds_once_per_line(self):
        project = _project()
        calls = []

        def builder(line, run_index):
            calls.append((line.id, run_index))
            return _builder(line, run_index)

        cheap = _plan(
            project,
            selected=("route_a", "route_c"),
            run_count=20,
            request_builder=None,
        )
        self.assertEqual([], calls)
        self.assertFalse(cheap["preflight_complete"])
        self.assertEqual(60, cheap["request_count"])
        self.assertEqual([], cheap["request_plan"])

        full = _plan(
            project,
            selected=("route_a", "route_c"),
            run_count=20,
            request_builder=builder,
        )
        self.assertEqual([("a1", 1), ("a2", 1), ("c1", 1)], calls)
        self.assertEqual(3, len(full["workflow_plan"]))
        self.assertEqual(60, full["request_count"])
        self.assertTrue(full["preflight_complete"])
        self.assertTrue(all("workflow_json" not in request for request in full["request_plan"]))

    def test_cheap_input_signature_tracks_prompt_workflow_settings_and_project_path(self):
        project = _project()
        base = _plan(
            project,
            selected=("route_a",),
            request_builder=None,
            generation_options={"workflow_file_signature": {"sha256": "one"}, "steps": 20},
        )
        project.prompt_lines[1].current_text = "changed"
        prompt_changed = _plan(
            project,
            selected=("route_a",),
            request_builder=None,
            generation_options={"workflow_file_signature": {"sha256": "one"}, "steps": 20},
        )
        self.assertNotEqual(base["input_signature"], prompt_changed["input_signature"])

        workflow_changed = _plan(
            _project(),
            selected=("route_a",),
            request_builder=None,
            generation_options={"workflow_file_signature": {"sha256": "two"}, "steps": 20},
        )
        settings_changed = _plan(
            _project(),
            selected=("route_a",),
            request_builder=None,
            generation_options={"workflow_file_signature": {"sha256": "one"}, "steps": 30},
        )
        path_changed = _plan(
            _project(),
            selected=("route_a",),
            request_builder=None,
            generation_options={"workflow_file_signature": {"sha256": "one"}, "steps": 20},
            project_path="D:/other.json",
        )
        self.assertNotEqual(base["input_signature"], workflow_changed["input_signature"])
        self.assertNotEqual(base["input_signature"], settings_changed["input_signature"])
        self.assertNotEqual(base["input_signature"], path_changed["input_signature"])

    def test_malformed_inputs_return_invalid_diagnostics(self):
        malformed = build_selected_routes_generation_plan(
            Project(prompt_lines="invalid"),
            "route_a",
            run_count="bad",
            generation_options=object(),
        )
        self.assertFalse(malformed["valid"])
        self.assertEqual([], malformed["request_plan"])
        self.assertTrue(any("prompt_lines is not a list" in item for item in malformed["diagnostics"]))

        project = _project()
        project.prompt_lines[1].generated_candidates = object()
        malformed_candidates = _plan(project, selected=("route_a",))
        self.assertFalse(malformed_candidates["valid"])
        self.assertTrue(
            any("generated_candidates is malformed" in item for item in malformed_candidates["diagnostics"])
        )


class SelectedRoutesGenerationExecutionTests(unittest.TestCase):
    def test_stale_validation_prevents_submit(self):
        project = _project()
        stored = _plan(project, selected=("route_a",))
        project.prompt_lines[1].current_text = "changed"
        current = _plan(project, selected=("route_a",))

        validation = validate_selected_routes_generation_submit(stored, current)

        self.assertFalse(validation["allowed"])
        self.assertIn("Preview", validation["reason"])

    def test_full_preview_matches_unchanged_cheap_signature(self):
        project = _project()
        stored = _plan(project, selected=("route_a",))
        current = _plan(project, selected=("route_a",), request_builder=None)
        validation = validate_selected_routes_generation_submit(stored, current)
        self.assertTrue(validation["allowed"])

    def test_submit_preflight_rejects_changed_resolved_workflow(self):
        project = _project()
        stored = _plan(project, selected=("route_a",))

        def changed_builder(line, run_index):
            value = _builder(line, run_index)
            value["workflow_json"]["model"] = "changed.safetensors"
            return value

        current = _plan(
            project,
            selected=("route_a",),
            request_builder=changed_builder,
        )
        validation = validate_selected_routes_generation_submit(stored, current)
        self.assertFalse(validation["allowed"])
        self.assertIn("Workflow Preview", validation["reason"])

    def test_execution_is_candidate_first_and_preserves_line_and_route_state(self):
        project = _project()
        line = project.prompt_lines[1]
        line.selected_candidate_path = "selected.png"
        line.generated_image_path = "generated.png"
        line.image_path = "main.png"
        line.source_generation_info = {"source": "main.png"}
        line.lineage_info = {"parent": "parent.png"}
        before_lines = [item.id for item in project.prompt_lines]
        before_fields = copy.deepcopy({
            "selected": line.selected_candidate_path,
            "generated": line.generated_image_path,
            "image": line.image_path,
            "prompt": line.current_text,
            "negative": line.negative_prompt,
            "source": line.source_generation_info,
            "lineage": line.lineage_info,
        })
        plan = _plan(project, selected=("route_a",))

        with tempfile.TemporaryDirectory() as temp_dir:
            def submitter(request):
                path = Path(temp_dir) / f"{request['source_line_id']}.png"
                path.touch()
                return [str(path)]

            result = execute_gallery_generation_plan(
                project,
                plan,
                submitter=submitter,
                candidate_factory=_candidate_factory,
                candidate_appender=_append_candidates,
            )

        self.assertEqual(2, result["candidate_count"])
        candidate = line.generated_candidates[0]
        self.assertEqual("a1.png", Path(candidate["path"]).name)
        self.assertEqual("a1", candidate["origin_line_id"])
        self.assertEqual("A1 prompt", candidate["prompt_text"])
        self.assertEqual("A1 negative", candidate["negative_prompt"])
        self.assertEqual(before_lines, [item.id for item in project.prompt_lines])
        self.assertEqual(before_fields["selected"], line.selected_candidate_path)
        self.assertEqual(before_fields["generated"], line.generated_image_path)
        self.assertEqual(before_fields["image"], line.image_path)
        self.assertEqual(before_fields["prompt"], line.current_text)
        self.assertEqual(before_fields["negative"], line.negative_prompt)
        self.assertEqual(before_fields["source"], line.source_generation_info)
        self.assertEqual(before_fields["lineage"], line.lineage_info)

    def test_partial_failure_keeps_real_success_and_never_creates_fake_candidate(self):
        project = _project()
        plan = _plan(project, selected=("route_a",))

        with tempfile.TemporaryDirectory() as temp_dir:
            real_path = Path(temp_dir) / "real-a1.png"
            real_path.touch()

            def submitter(request):
                if request["source_line_id"] == "a2":
                    raise RuntimeError("queue failed")
                return [str(real_path)]

            result = execute_gallery_generation_plan(
                project,
                plan,
                submitter=submitter,
                candidate_factory=_candidate_factory,
                candidate_appender=_append_candidates,
            )

        self.assertEqual(2, result["submitted_count"])
        self.assertEqual(1, result["completed_request_count"])
        self.assertEqual(1, result["candidate_count"])
        self.assertEqual("gallery_generation:a2:1", result["failures"][0]["request_id"])
        self.assertEqual(["real-a1.png"], [Path(item["path"]).name for item in project.prompt_lines[1].generated_candidates])
        self.assertEqual([], project.prompt_lines[3].generated_candidates)

    def test_each_run_receives_a_fresh_copy_of_the_line_workflow(self):
        project = _project()
        plan = _plan(project, selected=("route_a",), run_count=2)
        submitted_workflows = []
        with tempfile.TemporaryDirectory() as temp_dir:
            def submitter(request):
                workflow = request["workflow_json"]
                self.assertNotIn("submitted", workflow)
                submitted_workflows.append(workflow)
                workflow["submitted"] = True
                path = Path(temp_dir) / f"{request['request_id'].replace(':', '-')}.png"
                path.touch()
                return [str(path)]

            result = execute_gallery_generation_plan(
                project,
                plan,
                submitter=submitter,
                candidate_factory=_candidate_factory,
                candidate_appender=_append_candidates,
            )

        self.assertEqual(4, result["completed_request_count"])
        self.assertTrue(
            all(
                left is not right
                for index, left in enumerate(submitted_workflows)
                for right in submitted_workflows[index + 1:]
            )
        )

    def test_results_route_by_line_id_after_move_and_reject_deleted_missing_or_ambiguous_sources(self):
        project = _project()
        request_a = {"request_id": "req-a", "source_line_id": "a1", "run_index": 1}
        request_c = {"request_id": "req-c", "source_line_id": "c1", "run_index": 1}
        move_route_block(project, "route_c", "up")

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = {
                "req-a": Path(temp_dir) / "a.png",
                "req-c": Path(temp_dir) / "c.png",
            }
            for path in paths.values():
                path.touch()
            for request in (request_c, request_a):
                result = ingest_gallery_generation_outputs(
                    project,
                    request,
                    [str(paths[request["request_id"]])],
                    candidate_factory=_candidate_factory,
                    candidate_appender=_append_candidates,
                )
                self.assertEqual(1, result["added_count"])
        by_id = {line.id: line for line in project.prompt_lines}
        self.assertEqual("a.png", Path(by_id["a1"].generated_candidates[0]["path"]).name)
        self.assertEqual("c.png", Path(by_id["c1"].generated_candidates[0]["path"]).name)

        by_id["a1"].deleted = True
        deleted = ingest_gallery_generation_outputs(
            project, request_a, ["deleted.png"],
            candidate_factory=_candidate_factory, candidate_appender=_append_candidates,
        )
        self.assertEqual(0, deleted["added_count"])
        self.assertIn("deleted", deleted["reason"])

        missing = ingest_gallery_generation_outputs(
            project, {"request_id": "missing", "source_line_id": "missing"}, ["missing.png"],
            candidate_factory=_candidate_factory, candidate_appender=_append_candidates,
        )
        self.assertEqual(0, missing["added_count"])

        project.prompt_lines.append(_line("c1", "duplicate"))
        ambiguous = ingest_gallery_generation_outputs(
            project, request_c, ["ambiguous.png"],
            candidate_factory=_candidate_factory, candidate_appender=_append_candidates,
        )
        self.assertEqual(0, ambiguous["added_count"])
        self.assertIn("ambiguous", ambiguous["reason"])

    def test_duplicate_result_path_is_not_registered_twice(self):
        project = _project()
        request = {"request_id": "req-a", "source_line_id": "a1", "run_index": 1}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "same.png"
            path.touch()
            first = ingest_gallery_generation_outputs(
                project, request, [str(path)],
                candidate_factory=_candidate_factory, candidate_appender=_append_candidates,
            )
            second = ingest_gallery_generation_outputs(
                project, request, [str(path)],
                candidate_factory=_candidate_factory, candidate_appender=_append_candidates,
            )
        self.assertEqual(1, first["added_count"])
        self.assertEqual(0, second["added_count"])
        self.assertEqual(1, len(project.prompt_lines[1].generated_candidates))

    def test_missing_outputs_are_diagnostic_and_mixed_outputs_register_only_existing_files(self):
        project = _project()
        request = {"request_id": "req-a", "source_line_id": "a1", "run_index": 1}
        with tempfile.TemporaryDirectory() as temp_dir:
            existing = Path(temp_dir) / "existing.png"
            missing = Path(temp_dir) / "missing.png"
            existing.touch()

            mixed = ingest_gallery_generation_outputs(
                project,
                request,
                [str(existing), str(missing)],
                candidate_factory=_candidate_factory,
                candidate_appender=_append_candidates,
            )
            self.assertEqual(1, mixed["added_count"])
            self.assertEqual([str(existing)], mixed["added_paths"])
            self.assertTrue(any("missing generation output" in item for item in mixed["diagnostics"]))

            missing_project = _project()
            missing_project.prompt_lines[1].generated_candidates = [{"path": "existing-candidate.png"}]
            missing_before = copy.deepcopy(missing_project.prompt_lines[1])
            missing_only = ingest_gallery_generation_outputs(
                missing_project,
                request,
                [str(missing)],
                candidate_factory=_candidate_factory,
                candidate_appender=_append_candidates,
            )
            self.assertEqual(0, missing_only["added_count"])
            self.assertEqual("no existing generation outputs", missing_only["reason"])
            self.assertEqual(missing_before, missing_project.prompt_lines[1])

            relative_project = _project()
            relative = ingest_gallery_generation_outputs(
                relative_project,
                request,
                ["existing.png"],
                candidate_factory=_candidate_factory,
                candidate_appender=_append_candidates,
                resolve_path=lambda path: str(Path(temp_dir) / path),
                path_exists=lambda path: Path(path).is_file(),
            )
            self.assertEqual(1, relative["added_count"])
            self.assertEqual([str(existing)], relative["added_paths"])


if __name__ == "__main__":
    unittest.main()
