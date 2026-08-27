import copy
import json
import os
import tempfile
import unittest

from core.io import load_project_from_json, save_project_to_json
from core.lightweight_fork import build_lightweight_fork_preview, materialize_lightweight_fork
from core.lightweight_fork_append import (
    append_selected_routes_to_existing_fork,
    build_lightweight_fork_append_preview,
    load_existing_fork_snapshot,
)
from core.project import Project, PromptLine


def _line(line_id, index, *, text="prompt", image_path="", line_type=None, deleted=False):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.png",
        original_index=index,
        current_index=index,
        original_text=text,
        current_text=text,
        tokens=[text],
        negative_prompt=f"negative {text}",
        image_path=image_path,
        line_type=line_type,
        deleted=deleted,
        separator_label=text if line_type == "separator" else None,
        separator_color="blue" if line_type == "separator" else None,
    )


class LightweightForkAppendTests(unittest.TestCase):
    def _read_json(self, path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _read_bytes(self, path):
        with open(path, "rb") as handle:
            return handle.read()

    def _image(self, directory, name, payload=b"image"):
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def _source(self, tmpdir):
        a = self._image(tmpdir, "a.png", b"a")
        b1 = self._image(tmpdir, "b1.png", b"b1")
        b2 = self._image(tmpdir, "b2.png", b"b2")
        lines = [
            _line("route_a", 20, text="Route A", line_type="separator"),
            _line("a1", 21, text="A prompt", image_path=a),
            _line("route_b", 1, text="Route B", line_type="separator"),
            _line("b1", 2, text="B1 prompt", image_path=b1),
            _line("b_workbench", 3, text="scratch", image_path=b1, line_type="workbench"),
            _line("b_deleted", 4, text="deleted", image_path=b1, deleted=True),
            _line("b2", 5, text="B2 prompt", image_path=b2),
            _line("route_c", 0, text="Route C", line_type="separator"),
            _line("c1", 6, text="C missing"),
        ]
        project = Project(prompt_lines=lines)
        project.module_library = {"module": {"body": "keep"}}
        project.attribute_groups = {"group": {"slot": "outfit", "tokens": ["keep"]}}
        project.project_metadata = {"custom": {"keep": True}}
        source_path = os.path.join(tmpdir, "source-project.json")
        save_project_to_json(project, source_path)
        return project, source_path

    def _existing_fork(self, tmpdir, project, source_path):
        preview = build_lightweight_fork_preview(
            project.prompt_lines,
            fork_name="existing_fork",
            scope="selected_routes",
            project_path=source_path,
            selected_route_ids=["route_a"],
            path_exists=os.path.exists,
        )
        result = materialize_lightweight_fork(
            project,
            source_project_path=source_path,
            stored_preview=preview,
            destination_parent_dir=tmpdir,
            fork_name="existing_fork",
            created_at_provider=lambda: "2026-07-16T00:00:00+00:00",
        )
        self.assertTrue(result["success"], result)
        return result["project_path"], result["manifest_path"]

    def _preview(self, project, source_path, fork_path, selected=("route_b",)):
        return build_lightweight_fork_append_preview(
            project,
            source_project_path=source_path,
            selected_route_ids=list(selected),
            existing_fork_project_path=fork_path,
            current_open_project_path=source_path,
        )

    def test_preview_orders_routes_detects_existing_and_plans_next_sequence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, _manifest_path = self._existing_fork(tmpdir, project, source_path)

            preview = self._preview(project, source_path, fork_path, ("route_b", "route_a", "route_c"))

            self.assertTrue(preview["valid"], preview)
            self.assertEqual(["route_a", "route_b", "route_c"], preview["selected_route_ids"])
            self.assertEqual(["route_b"], preview["appendable_route_ids"])
            self.assertEqual(["route_a"], preview["already_materialized_route_ids"])
            self.assertEqual(["route_c"], preview["blocked_route_ids"])
            self.assertEqual(2, preview["materializable_count"])
            self.assertEqual(2, preview["next_image_sequence_number"])
            self.assertEqual(
                ["0002_b1.png", "0003_b2.png"],
                [entry["planned_destination_filename"] for entry in preview["entries"] if entry["materializable"]],
            )

    def test_selected_but_unmaterialized_route_can_be_appended_after_image_is_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            initial_preview = build_lightweight_fork_preview(
                project.prompt_lines,
                fork_name="existing_fork",
                scope="selected_routes",
                project_path=source_path,
                selected_route_ids=["route_a", "route_c"],
                path_exists=os.path.exists,
            )
            initial_result = materialize_lightweight_fork(
                project,
                source_project_path=source_path,
                stored_preview=initial_preview,
                destination_parent_dir=tmpdir,
                fork_name="existing_fork",
            )
            self.assertTrue(initial_result["success"], initial_result)
            manifest = self._read_json(initial_result["manifest_path"])
            self.assertEqual(["route_a", "route_c"], manifest["selected_route_ids"])
            self.assertEqual({"route_a"}, {
                entry.get("route_id") for entry in manifest["materialized_entries"]
            })

            c_image = self._image(tmpdir, "c1.png", b"c1")
            project.prompt_lines[8].image_path = c_image
            save_project_to_json(project, source_path)
            preview = self._preview(
                project,
                source_path,
                initial_result["project_path"],
                ("route_c",),
            )
            self.assertTrue(preview["valid"], preview)
            self.assertEqual(["route_c"], preview["appendable_route_ids"])
            self.assertEqual([], preview["already_materialized_route_ids"])

            append_result = append_selected_routes_to_existing_fork(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_c"],
                existing_fork_project_path=initial_result["project_path"],
                stored_preview=preview,
                current_open_project_path=source_path,
            )
            self.assertTrue(append_result["success"], append_result)
            loaded = load_project_from_json(initial_result["project_path"])
            self.assertEqual(["Route A", "A prompt", "Route C", "C missing"], [
                line.current_text for line in loaded.prompt_lines
            ])
            repeated = self._preview(
                project,
                source_path,
                initial_result["project_path"],
                ("route_c",),
            )
            self.assertEqual([], repeated["appendable_route_ids"])
            self.assertEqual(["route_c"], repeated["already_materialized_route_ids"])

    def test_recoverable_selected_route_diagnostics_do_not_block_valid_route(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, _manifest_path = self._existing_fork(tmpdir, project, source_path)
            project.prompt_lines[7].deleted = True
            save_project_to_json(project, source_path)

            preview = self._preview(
                project,
                source_path,
                fork_path,
                ("route_b", "missing", "route_c", "b1", "route_b"),
            )

            self.assertTrue(preview["valid"], preview)
            self.assertEqual(["route_b"], preview["selected_route_ids"])
            self.assertEqual(["route_b"], preview["appendable_route_ids"])
            warnings = "\n".join(preview["warning_diagnostics"])
            self.assertIn("missing selected Route excluded: missing", warnings)
            self.assertIn("deleted selected Route excluded: route_c", warnings)
            self.assertIn("non-separator selected id excluded: b1", warnings)
            self.assertIn("duplicate selected Route ignored: route_b", warnings)
            self.assertEqual([], preview["fatal_diagnostics"])

            invalid = self._preview(
                project,
                source_path,
                fork_path,
                ("missing", "route_c", "b1"),
            )
            self.assertFalse(invalid["valid"])
            self.assertIn("no valid selected Routes", invalid["fatal_diagnostics"])

            result = append_selected_routes_to_existing_fork(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_b", "missing", "route_c", "b1", "route_b"],
                existing_fork_project_path=fork_path,
                stored_preview=preview,
                current_open_project_path=source_path,
            )
            self.assertTrue(result["success"], result)
            self.assertEqual(["route_b"], result["appended_route_ids"])

    def test_duplicate_member_line_id_is_fatal_even_when_another_line_is_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, _manifest_path = self._existing_fork(tmpdir, project, source_path)
            duplicate_image = self._image(tmpdir, "duplicate-b1.png")
            project.prompt_lines.insert(7, _line("b1", 7, text="duplicate", image_path=duplicate_image))
            save_project_to_json(project, source_path)

            preview = self._preview(project, source_path, fork_path)

            self.assertFalse(preview["valid"])
            self.assertTrue(any(
                diagnostic == "ambiguous selected Route line id: b1"
                for diagnostic in preview["fatal_diagnostics"]
            ))

    def test_ambiguous_separator_is_excluded_without_blocking_another_route(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, _manifest_path = self._existing_fork(tmpdir, project, source_path)
            project.prompt_lines.append(
                _line("route_c", 9, text="Duplicate Route C", line_type="separator")
            )
            save_project_to_json(project, source_path)

            preview = self._preview(
                project,
                source_path,
                fork_path,
                ("route_b", "route_c"),
            )

            self.assertTrue(preview["valid"], preview)
            self.assertEqual(["route_b"], preview["appendable_route_ids"])
            self.assertTrue(any(
                "ambiguous selected Route excluded: route_c" == diagnostic
                for diagnostic in preview["warning_diagnostics"]
            ))
            self.assertEqual([], preview["fatal_diagnostics"])

    def test_empty_line_id_inside_selected_route_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, _manifest_path = self._existing_fork(tmpdir, project, source_path)
            project.prompt_lines.insert(6, _line("", 6, text="malformed"))
            save_project_to_json(project, source_path)

            preview = self._preview(project, source_path, fork_path)

            self.assertFalse(preview["valid"])
            self.assertTrue(any(
                diagnostic == "malformed source Line in selected Route: route_b"
                for diagnostic in preview["fatal_diagnostics"]
            ))

    def test_append_preserves_existing_edits_and_appends_fresh_route(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, manifest_path = self._existing_fork(tmpdir, project, source_path)
            raw = self._read_json(fork_path)
            existing_line = next(line for line in raw["prompt_lines"] if line.get("line_type") != "separator")
            existing_line["current_text"] = "  edited Fork prompt\n"
            existing_line["negative_prompt"] = "edited negative"
            existing_line["generated_candidates"] = [{"path": "images/candidate.png", "custom": {"keep": True}}]
            existing_line["gallery_variants"] = [{"path": "images/variant.png", "kind": "gallery_variant"}]
            existing_line["custom_line_metadata"] = {"keep": True}
            raw["custom_top_level"] = {"keep": True}
            with open(fork_path, "w", encoding="utf-8") as handle:
                json.dump(raw, handle, indent=2)
            before_source = copy.deepcopy(project)
            before_existing_line = copy.deepcopy(existing_line)

            preview = self._preview(project, source_path, fork_path)
            result = append_selected_routes_to_existing_fork(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_b"],
                existing_fork_project_path=fork_path,
                stored_preview=preview,
                current_open_project_path=source_path,
                created_at_provider=lambda: "2026-07-16T01:00:00+00:00",
            )

            self.assertTrue(result["success"], result)
            self.assertEqual(before_source, project)
            updated_raw = self._read_json(fork_path)
            self.assertEqual({"keep": True}, updated_raw["custom_top_level"])
            self.assertEqual(before_existing_line, updated_raw["prompt_lines"][1])
            self.assertEqual(
                ["separator", None, "separator", None, None],
                [line.get("line_type") for line in updated_raw["prompt_lines"]],
            )
            new_lines = updated_raw["prompt_lines"][2:]
            self.assertEqual(["Route B", "B1 prompt", "B2 prompt"], [line["current_text"] for line in new_lines])
            self.assertTrue(all(line["id"] not in {"route_b", "b1", "b2"} for line in new_lines))
            for line in new_lines[1:]:
                self.assertEqual([], line["generated_candidates"])
                self.assertEqual([], line["gallery_variants"])
                self.assertEqual({}, line["source_generation_info"])
                self.assertEqual({}, line["lineage_info"])
            manifest = self._read_json(manifest_path)
            self.assertEqual("2026-07-16T00:00:00+00:00", manifest["created_at"])
            self.assertEqual("2026-07-16T01:00:00+00:00", manifest["updated_at"])
            self.assertEqual(["route_a", "route_b"], manifest["selected_route_ids"])
            self.assertEqual(1, len(manifest["append_history"]))
            self.assertEqual(["route_b"], manifest["append_history"][0]["selected_route_ids"])
            self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(fork_path), "images", "0002_b1.png")))
            self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(fork_path), "images", "0003_b2.png")))
            repeated = self._preview(project, source_path, fork_path)
            self.assertEqual([], repeated["appendable_route_ids"])
            self.assertEqual(["route_b"], repeated["already_materialized_route_ids"])

    def test_partial_route_appends_only_materializable_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, _manifest_path = self._existing_fork(tmpdir, project, source_path)
            os.remove(project.prompt_lines[6].image_path)
            preview = self._preview(project, source_path, fork_path)

            self.assertEqual(["route_b"], preview["appendable_route_ids"])
            self.assertEqual(1, preview["materializable_count"])
            self.assertEqual(1, preview["missing_image_count"])
            result = append_selected_routes_to_existing_fork(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_b"],
                existing_fork_project_path=fork_path,
                stored_preview=preview,
                current_open_project_path=source_path,
            )

            self.assertTrue(result["success"], result)
            loaded = load_project_from_json(fork_path)
            self.assertEqual(["Route A", "A prompt", "Route B", "B1 prompt"], [line.current_text for line in loaded.prompt_lines])
            self.assertEqual(1, result["skipped_line_count"])

    def test_all_selected_routes_already_materialized_is_no_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, manifest_path = self._existing_fork(tmpdir, project, source_path)
            preview = self._preview(project, source_path, fork_path, ("route_a",))
            project_before = self._read_bytes(fork_path)
            manifest_before = self._read_bytes(manifest_path)

            result = append_selected_routes_to_existing_fork(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_a"],
                existing_fork_project_path=fork_path,
                stored_preview=preview,
                current_open_project_path=source_path,
            )

            self.assertFalse(result["success"])
            self.assertIn("already present", result["error"])
            self.assertEqual(project_before, self._read_bytes(fork_path))
            self.assertEqual(manifest_before, self._read_bytes(manifest_path))

    def test_stale_source_destination_manifest_and_images_are_rejected(self):
        mutations = ("source", "project", "manifest", "image")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmpdir:
                project, source_path = self._source(tmpdir)
                fork_path, manifest_path = self._existing_fork(tmpdir, project, source_path)
                preview = self._preview(project, source_path, fork_path)
                if mutation == "source":
                    saved = load_project_from_json(source_path)
                    saved.prompt_lines[3].current_text = "changed after preview"
                    save_project_to_json(saved, source_path)
                elif mutation == "project":
                    with open(fork_path, "a", encoding="utf-8") as handle:
                        handle.write(" ")
                elif mutation == "manifest":
                    with open(manifest_path, "a", encoding="utf-8") as handle:
                        handle.write(" ")
                else:
                    with open(os.path.join(os.path.dirname(fork_path), "images", "0001_a.png"), "ab") as handle:
                        handle.write(b"changed")

                result = append_selected_routes_to_existing_fork(
                    project,
                    source_project_path=source_path,
                    selected_route_ids=["route_b"],
                    existing_fork_project_path=fork_path,
                    stored_preview=preview,
                    current_open_project_path=source_path,
                )
                self.assertFalse(result["success"], result)
                self.assertTrue(result["stale_preview"], result)

    def test_failure_before_swap_cleans_staging_and_preserves_fork(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, manifest_path = self._existing_fork(tmpdir, project, source_path)
            preview = self._preview(project, source_path, fork_path)
            before_project = self._read_bytes(fork_path)
            before_manifest = self._read_bytes(manifest_path)

            def fail_after_manifest(phase):
                if phase == "after_manifest_write":
                    raise RuntimeError("injected failure")

            result = append_selected_routes_to_existing_fork(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_b"],
                existing_fork_project_path=fork_path,
                stored_preview=preview,
                current_open_project_path=source_path,
                phase_hook=fail_after_manifest,
            )

            self.assertFalse(result["success"])
            self.assertEqual(before_project, self._read_bytes(fork_path))
            self.assertEqual(before_manifest, self._read_bytes(manifest_path))
            self.assertFalse(any("append-staging" in name for name in os.listdir(os.path.dirname(fork_path))))

    def test_failure_after_final_rename_rolls_back_existing_fork(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, manifest_path = self._existing_fork(tmpdir, project, source_path)
            preview = self._preview(project, source_path, fork_path)
            before_project = self._read_bytes(fork_path)
            before_manifest = self._read_bytes(manifest_path)

            def fail_after_final_rename(phase):
                if phase == "after_final_rename":
                    raise RuntimeError("injected post-swap failure")

            result = append_selected_routes_to_existing_fork(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_b"],
                existing_fork_project_path=fork_path,
                stored_preview=preview,
                current_open_project_path=source_path,
                phase_hook=fail_after_final_rename,
            )

            self.assertFalse(result["success"])
            self.assertTrue(result["rollback_performed"], result)
            self.assertEqual(before_project, self._read_bytes(fork_path))
            self.assertEqual(before_manifest, self._read_bytes(manifest_path))

    def test_backup_cleanup_failure_rolls_back_existing_fork(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, manifest_path = self._existing_fork(tmpdir, project, source_path)
            preview = self._preview(project, source_path, fork_path)
            before_project = self._read_bytes(fork_path)
            before_manifest = self._read_bytes(manifest_path)

            def fail_backup_cleanup(path):
                if ".append-backup." in path:
                    raise OSError("injected backup cleanup failure")
                return __import__("shutil").rmtree(path)

            result = append_selected_routes_to_existing_fork(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_b"],
                existing_fork_project_path=fork_path,
                stored_preview=preview,
                current_open_project_path=source_path,
                rmtree=fail_backup_cleanup,
            )

            self.assertFalse(result["success"])
            self.assertTrue(result["rollback_performed"], result)
            self.assertEqual(before_project, self._read_bytes(fork_path))
            self.assertEqual(before_manifest, self._read_bytes(manifest_path))

    def test_image_numbering_uses_max_existing_prefix_without_filling_gaps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, _manifest_path = self._existing_fork(tmpdir, project, source_path)
            images_dir = os.path.join(os.path.dirname(fork_path), "images")
            self._image(images_dir, "0004_old.png")

            preview = self._preview(project, source_path, fork_path)

            self.assertEqual(5, preview["next_image_sequence_number"])
            self.assertEqual(
                ["0005_b1.png", "0006_b2.png"],
                [entry["planned_destination_filename"] for entry in preview["entries"] if entry["materializable"]],
            )

    def test_invalid_manifest_source_and_currently_open_fork_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            fork_path, manifest_path = self._existing_fork(tmpdir, project, source_path)
            manifest = self._read_json(manifest_path)
            manifest["source_project_path"] = os.path.join(tmpdir, "different.json")
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            preview = self._preview(project, source_path, fork_path)
            self.assertFalse(preview["valid"])
            self.assertIn("different source Project", preview["reason"])

            manifest["source_project_path"] = source_path
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            open_preview = build_lightweight_fork_append_preview(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_b"],
                existing_fork_project_path=fork_path,
                current_open_project_path=fork_path,
            )
            self.assertFalse(open_preview["valid"])
            self.assertIn("currently open", open_preview["reason"])

    def test_loader_rejects_missing_wrong_and_malformed_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = os.path.join(tmpdir, "project.json")
            save_project_to_json(Project(), project_path)
            missing = load_existing_fork_snapshot(project_path)
            self.assertFalse(missing["valid"])
            self.assertIn("manifest", missing["reason"])

            os.makedirs(os.path.join(tmpdir, "images"))
            manifest_path = os.path.join(tmpdir, "manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump({"operation": "other", "manifest_version": 1}, handle)
            wrong = load_existing_fork_snapshot(project_path)
            self.assertFalse(wrong["valid"])
            self.assertIn("not a Lightweight Fork", wrong["reason"])

            with open(manifest_path, "w", encoding="utf-8") as handle:
                handle.write("{")
            malformed = load_existing_fork_snapshot(project_path)
            self.assertFalse(malformed["valid"])

            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "operation": "lightweight_fork_final_sequence",
                    "manifest_version": 1,
                    "source_project_path": os.path.join(tmpdir, "source.json"),
                }, handle)
            with open(project_path, "w", encoding="utf-8") as handle:
                json.dump({"prompt_lines": "malformed"}, handle)
            malformed_project = load_existing_fork_snapshot(project_path)
            self.assertFalse(malformed_project["valid"])
            self.assertIn("could not be loaded", malformed_project["reason"])

    def test_manifest_selection_without_materialization_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = os.path.join(tmpdir, "project.json")
            save_project_to_json(Project(), project_path)
            os.makedirs(os.path.join(tmpdir, "images"))
            with open(os.path.join(tmpdir, "manifest.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "operation": "lightweight_fork_final_sequence",
                    "manifest_version": 1,
                    "source_project_path": os.path.join(tmpdir, "source.json"),
                    "selected_route_ids": ["route_a"],
                    "source_route_blocks": [{"route_handle": "route_a"}],
                }, handle)

            snapshot = load_existing_fork_snapshot(project_path)

            self.assertFalse(snapshot["valid"])
            self.assertIn("does not identify materialized Routes", snapshot["reason"])


if __name__ == "__main__":
    unittest.main()
