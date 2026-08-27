import os
import tempfile
import unittest

from core.project import Project, PromptLine
from core.route_batch_candidate_adoption import (
    GALLERY_VARIANT_PREVIEW_SOURCE,
    apply_selected_routes_candidate_adoption,
    build_route_batch_candidate_adoption_preview,
    build_selected_routes_candidate_adoption_preview,
    build_selected_routes_candidate_adoption_signature,
)
from core.route_operations import move_route_block, remove_route_block


def _line(line_id, text="prompt", *, line_type=None, deleted=False, **fields):
    current_index = fields.pop("current_index", 0)
    return PromptLine(
        id=line_id,
        original_file_name=line_id,
        original_index=0,
        current_index=current_index,
        original_text=text,
        current_text=text,
        tokens=[text],
        line_type=line_type,
        deleted=deleted,
        **fields,
    )


def _project(*lines):
    return Project(source_directory="source", prompt_lines=list(lines))


class SelectedRoutesCandidateAdoptionTests(unittest.TestCase):
    def test_preview_uses_project_route_and_line_order_not_click_or_current_index_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {}
            for name in ("a1", "a2", "b1", "c1"):
                paths[name] = os.path.join(tmpdir, f"{name}.png")
                open(paths[name], "wb").close()
            project = _project(
                _line("route_a", "Route A", line_type="separator", separator_label="Route A"),
                _line("a1", current_index=20, generated_candidates=[{"id": "ca1", "path": paths["a1"]}]),
                _line("a2", current_index=19, generated_candidates=[{"id": "ca2", "path": paths["a2"]}]),
                _line("route_b", "Route B", line_type="separator", separator_label="Route B"),
                _line("b1", generated_candidates=[{"id": "cb1", "path": paths["b1"]}]),
                _line("route_c", "Route C", line_type="separator", separator_label="Route C"),
                _line("c1", current_index=1, generated_candidates=[{"id": "cc1", "path": paths["c1"]}]),
            )

            preview = build_selected_routes_candidate_adoption_preview(
                project, ["route_c", "route_a"], path_exists=os.path.exists
            )

            self.assertEqual(["route_a", "route_c"], preview["selected_route_ids"])
            self.assertEqual(["a1", "a2", "c1"], preview["target_line_ids"])
            self.assertEqual(["a1", "a2", "c1"], [entry["line_id"] for entry in preview["entries"]])
            self.assertNotIn("b1", preview["target_line_ids"])

    def test_one_selected_route_matches_existing_single_route_plan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate_path = os.path.join(tmpdir, "candidate.png")
            open(candidate_path, "wb").close()
            line = _line("a1", generated_candidates=[{"id": "candidate", "path": candidate_path}])
            project = _project(
                _line("route_a", "Route A", line_type="separator", separator_label="Route A"),
                line,
            )

            selected = build_selected_routes_candidate_adoption_preview(
                project, ["route_a"], source="latest", path_exists=os.path.exists
            )
            single = build_route_batch_candidate_adoption_preview(
                [line],
                source="latest",
                scope="selected_route",
                route_id="route_a",
                route_label="Route A",
                path_exists=os.path.exists,
            )

            self.assertEqual(single["will_adopt_count"], selected["will_adopt_count"])
            self.assertEqual(single["entries"][0]["operation"], selected["entries"][0]["operation"])
            self.assertEqual(single["entries"][0]["after_image_path"], selected["entries"][0]["after_image_path"])

    def test_stale_current_index_does_not_change_selected_routes_signature(self):
        project = _project(
            _line("route_a", line_type="separator"),
            _line("a1", current_index=99, generated_candidates=[]),
        )
        before = build_selected_routes_candidate_adoption_signature(project, ["route_a"])
        project.prompt_lines[1].current_index = -100
        after = build_selected_routes_candidate_adoption_signature(project, ["route_a"])
        self.assertEqual(before, after)

    def test_preview_reports_drift_no_op_missing_trashed_and_variant_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            current_path = os.path.join(tmpdir, "current.png")
            variant_path = os.path.join(tmpdir, "variant.png")
            for path in (current_path, variant_path):
                open(path, "wb").close()
            project = _project(
                _line("route_a", "Route A", line_type="separator", separator_label="Route A"),
                _line(
                    "no_op",
                    text="current prompt",
                    negative_prompt="current negative",
                    selected_candidate_path=current_path,
                    generated_candidates=[{
                        "id": "same",
                        "path": current_path,
                        "prompt": "candidate prompt",
                        "negative_prompt": "candidate negative",
                        "generation_settings": {"steps": 30},
                    }],
                    source_generation_info={"source_generation_settings": {"steps": 20}},
                ),
                _line("trashed", generated_candidates=[{"path": "trash.png", "trashed": True}]),
                _line("missing", generated_candidates=[{"path": os.path.join(tmpdir, "missing.png")}]),
                _line(
                    "variant",
                    gallery_variants=[{"id": "variant_1", "path": variant_path, "kind": "gallery_variant"}],
                ),
            )

            candidate_preview = build_selected_routes_candidate_adoption_preview(
                project, ["route_a"], path_exists=os.path.exists
            )
            no_op = next(entry for entry in candidate_preview["entries"] if entry["line_id"] == "no_op")
            self.assertEqual("no_op", no_op["operation"])
            self.assertIn("prompt differs", no_op["drift_classifications"])
            self.assertIn("negative prompt differs", no_op["drift_classifications"])
            self.assertIn("generation metadata differs", no_op["drift_classifications"])
            self.assertEqual(
                {"trashed candidate only", "missing candidate file", "adoption target not found"},
                {
                    entry["skip_reason"]
                    for entry in candidate_preview["entries"]
                    if entry["line_id"] in {"trashed", "missing", "variant"}
                },
            )

            variant_preview = build_selected_routes_candidate_adoption_preview(
                project,
                ["route_a"],
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )
            variant = next(entry for entry in variant_preview["entries"] if entry["line_id"] == "variant")
            self.assertEqual("first_main_image", variant["operation"])
            self.assertEqual(variant_path, variant["after_image_path"])

    def test_apply_returns_atomic_clone_and_preserves_prompts_files_and_nonselected_routes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            candidate_path = os.path.join(tmpdir, "candidate.png")
            other_path = os.path.join(tmpdir, "other.png")
            for path in (main_path, candidate_path, other_path):
                open(path, "wb").close()
            source_candidate = {
                "id": "candidate",
                "path": candidate_path,
                "prompt": "candidate prompt",
                "negative_prompt": "candidate negative",
                "steps": 30,
                "sampler": "Euler",
                "origin_line_id": "origin-line",
                "origin_line_index": 7,
                "source": "comfy_generation",
            }
            old_source_info = {
                "source_kind": "imported_image_metadata",
                "source_image_path": main_path,
                "source_prompt": "old main prompt",
            }
            old_lineage = {
                "lineage_kind": "imported_image",
                "candidate_image_path": main_path,
            }
            a1 = _line(
                "a1",
                text="keep prompt",
                negative_prompt="keep negative",
                image_path=main_path,
                generated_candidates=[source_candidate.copy()],
                source_generation_info=old_source_info.copy(),
                lineage_info=old_lineage.copy(),
            )
            b1 = _line("b1", image_path=other_path, generated_candidates=[{"path": other_path}])
            project = _project(
                _line("route_a", "Route A", line_type="separator", separator_label="Route A"),
                a1,
                _line("route_b", "Route B", line_type="separator", separator_label="Route B"),
                b1,
            )
            preview = build_selected_routes_candidate_adoption_preview(
                project, ["route_a"], path_exists=os.path.exists
            )

            result = apply_selected_routes_candidate_adoption(
                project,
                ["route_a"],
                expected_signature=preview["signature"],
                path_exists=os.path.exists,
                now="2026-07-15T00:00:00+00:00",
            )

            self.assertTrue(result["applied"])
            self.assertIsNot(project, result["updated_project"])
            self.assertIsNone(a1.selected_candidate_path)
            updated_a1 = next(line for line in result["updated_project"].prompt_lines if line.id == "a1")
            updated_b1 = next(line for line in result["updated_project"].prompt_lines if line.id == "b1")
            self.assertEqual(candidate_path, updated_a1.selected_candidate_path)
            self.assertEqual(main_path, updated_a1.image_path)
            self.assertEqual("keep prompt", updated_a1.current_text)
            self.assertEqual("keep negative", updated_a1.negative_prompt)
            self.assertEqual("derived_candidate", updated_a1.source_generation_info["source_kind"])
            self.assertEqual(candidate_path, updated_a1.source_generation_info["source_image_path"])
            self.assertEqual("candidate prompt", updated_a1.source_generation_info["source_prompt"])
            self.assertEqual("candidate negative", updated_a1.source_generation_info["source_negative_prompt"])
            self.assertEqual(
                {"steps": "30", "sampler": "Euler"},
                updated_a1.source_generation_info["source_generation_settings"],
            )
            self.assertEqual(main_path, updated_a1.lineage_info["parent_image_path"])
            self.assertEqual(candidate_path, updated_a1.lineage_info["candidate_image_path"])
            self.assertEqual("origin-line", updated_a1.lineage_info["candidate_origin_line_id"])
            self.assertEqual(7, updated_a1.lineage_info["candidate_origin_line_index"])
            self.assertEqual(other_path, updated_b1.image_path)
            self.assertIsNone(updated_b1.selected_candidate_path)
            self.assertEqual(source_candidate, a1.generated_candidates[0])
            self.assertEqual(old_source_info, a1.source_generation_info)
            self.assertEqual(old_lineage, a1.lineage_info)
            self.assertTrue(os.path.exists(main_path))
            self.assertTrue(os.path.exists(candidate_path))

    def test_apply_rolls_back_when_injected_failure_occurs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate_path = os.path.join(tmpdir, "candidate.png")
            open(candidate_path, "wb").close()
            old_source_info = {"source_image_path": "old.png", "source_prompt": "old"}
            old_lineage = {"lineage_kind": "old", "parent_image_path": "older.png"}
            line = _line(
                "a1",
                generated_candidates=[{"path": candidate_path}],
                source_generation_info=old_source_info.copy(),
                lineage_info=old_lineage.copy(),
            )
            project = _project(_line("route_a", line_type="separator"), line)
            preview = build_selected_routes_candidate_adoption_preview(
                project, ["route_a"], path_exists=os.path.exists
            )

            def fail_after_mutation(_project, _result):
                raise RuntimeError("injected failure")

            result = apply_selected_routes_candidate_adoption(
                project,
                ["route_a"],
                expected_signature=preview["signature"],
                path_exists=os.path.exists,
                mutation_hook=fail_after_mutation,
            )

            self.assertFalse(result["applied"])
            self.assertIn("injected failure", result["error"])
            self.assertIsNone(result["updated_project"])
            self.assertIsNone(line.selected_candidate_path)
            self.assertEqual([{"path": candidate_path}], line.generated_candidates)
            self.assertEqual(old_source_info, line.source_generation_info)
            self.assertEqual(old_lineage, line.lineage_info)

    def test_no_op_does_not_rewrite_source_or_lineage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate_path = os.path.join(tmpdir, "candidate.png")
            open(candidate_path, "wb").close()
            source_info = {"source_image_path": "keep-source.png"}
            lineage_info = {"lineage_kind": "keep-lineage"}
            line = _line(
                "a1",
                selected_candidate_path=candidate_path,
                generated_candidates=[{"id": "candidate", "path": candidate_path, "prompt": "different"}],
                source_generation_info=source_info.copy(),
                lineage_info=lineage_info.copy(),
            )
            project = _project(_line("route_a", line_type="separator"), line)
            preview = build_selected_routes_candidate_adoption_preview(
                project, ["route_a"], path_exists=os.path.exists
            )

            result = apply_selected_routes_candidate_adoption(
                project,
                ["route_a"],
                expected_signature=preview["signature"],
                path_exists=os.path.exists,
            )

            self.assertFalse(result["applied"])
            self.assertEqual(0, result["applied_count"])
            self.assertEqual(source_info, line.source_generation_info)
            self.assertEqual(lineage_info, line.lineage_info)

    def test_gallery_variant_adoption_uses_candidate_provenance_and_old_main_parent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            variant_path = os.path.join(tmpdir, "variant.png")
            for path in (main_path, variant_path):
                open(path, "wb").close()
            variant = {
                "id": "variant_1",
                "kind": "gallery_variant",
                "path": variant_path,
                "source": "batch_candidate_adoption",
                "candidate_metadata": {
                    "prompt": "variant prompt",
                    "negative_prompt": "variant negative",
                    "steps": 42,
                    "origin_line_id": "variant-origin",
                },
            }
            line = _line(
                "a1",
                text="keep current prompt",
                negative_prompt="keep current negative",
                image_path=main_path,
                gallery_variants=[variant],
                source_generation_info={"source_image_path": main_path},
                lineage_info={"lineage_kind": "old"},
            )
            project = _project(_line("route_a", line_type="separator"), line)
            preview = build_selected_routes_candidate_adoption_preview(
                project,
                ["route_a"],
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            result = apply_selected_routes_candidate_adoption(
                project,
                ["route_a"],
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                expected_signature=preview["signature"],
                path_exists=os.path.exists,
            )

            updated = next(item for item in result["updated_project"].prompt_lines if item.id == "a1")
            self.assertTrue(result["applied"])
            self.assertEqual(variant_path, updated.selected_candidate_path)
            self.assertEqual("variant prompt", updated.source_generation_info["source_prompt"])
            self.assertEqual("variant negative", updated.source_generation_info["source_negative_prompt"])
            self.assertEqual({"steps": "42"}, updated.source_generation_info["source_generation_settings"])
            self.assertEqual(main_path, updated.lineage_info["parent_image_path"])
            self.assertEqual("variant-origin", updated.lineage_info["candidate_origin_line_id"])
            self.assertEqual("keep current prompt", updated.current_text)
            self.assertEqual("keep current negative", updated.negative_prompt)
            self.assertEqual({"source_image_path": main_path}, line.source_generation_info)
            self.assertEqual({"lineage_kind": "old"}, line.lineage_info)

    def test_signature_rejects_route_candidate_file_prompt_and_main_image_changes(self):
        mutations = (
            "move",
            "remove",
            "candidate",
            "file",
            "prompt_tail",
            "negative_tail",
            "generation",
            "lineage",
            "main",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmpdir:
                main_path = os.path.join(tmpdir, "main.png")
                candidate_path = os.path.join(tmpdir, "candidate.png")
                for path in (main_path, candidate_path):
                    with open(path, "wb") as handle:
                        handle.write(b"x")
                a1 = _line(
                    "a1",
                    text="p" * 300,
                    negative_prompt="n" * 300,
                    image_path=main_path,
                    generated_candidates=[{"id": "ca", "path": candidate_path}],
                    source_generation_info={"source_generation_settings": {"steps": 20}},
                    lineage_info={"source": "original"},
                )
                project = _project(
                    _line("route_a", "Route A", line_type="separator"),
                    a1,
                    _line("route_b", "Route B", line_type="separator"),
                    _line("b1"),
                )
                preview = build_selected_routes_candidate_adoption_preview(
                    project, ["route_a"], path_exists=os.path.exists
                )
                if mutation == "move":
                    move_route_block(project, "route_a", "down")
                elif mutation == "remove":
                    remove_route_block(project, "route_a", removal_id="remove-a")
                elif mutation == "candidate":
                    a1.generated_candidates[0]["prompt"] = "changed"
                elif mutation == "file":
                    with open(candidate_path, "ab") as handle:
                        handle.write(b"changed")
                elif mutation == "prompt_tail":
                    a1.current_text = ("p" * 240) + ("changed" * 10)
                elif mutation == "negative_tail":
                    a1.negative_prompt = ("n" * 240) + ("changed" * 10)
                elif mutation == "generation":
                    a1.source_generation_info["source_generation_settings"]["steps"] = 30
                elif mutation == "lineage":
                    a1.lineage_info["source"] = "changed"
                else:
                    a1.image_path = "different-main.png"

                result = apply_selected_routes_candidate_adoption(
                    project,
                    ["route_a"],
                    expected_signature=preview["signature"],
                    path_exists=os.path.exists,
                )
                self.assertTrue(result["stale_preview"])
                self.assertEqual(0, result["applied_count"])

    def test_selection_change_and_empty_or_invalid_selection_are_safe(self):
        project = _project(
            _line("route_a", line_type="separator"),
            _line("a1", generated_candidates=[]),
            _line("route_b", line_type="separator"),
            _line("b1", generated_candidates=[]),
        )
        preview = build_selected_routes_candidate_adoption_preview(project, ["route_a"])
        changed = apply_selected_routes_candidate_adoption(
            project, ["route_b"], expected_signature=preview["signature"]
        )
        self.assertTrue(changed["stale_preview"])

        for selected in ([], ["missing"], ["a1"], 123):
            safe_preview = build_selected_routes_candidate_adoption_preview(project, selected)
            self.assertFalse(safe_preview["valid"])
            self.assertEqual([], safe_preview["target_line_ids"])

    def test_malformed_candidate_and_variant_collections_are_read_only_and_safe(self):
        malformed_values = (None, 123, {"path": "candidate.png"}, object())
        for value in malformed_values:
            with self.subTest(value=type(value).__name__):
                line = _line("a1")
                line.generated_candidates = value
                line.gallery_variants = value
                project = _project(_line("route_a", line_type="separator"), line)

                preview = build_selected_routes_candidate_adoption_preview(project, ["route_a"])

                self.assertEqual(0, preview["will_adopt_count"])
                self.assertEqual("adoption target not found", preview["entries"][0]["skip_reason"])
                self.assertIs(value, line.generated_candidates)
                self.assertIs(value, line.gallery_variants)


if __name__ == "__main__":
    unittest.main()
