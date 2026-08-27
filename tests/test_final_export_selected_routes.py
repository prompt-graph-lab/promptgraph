import copy
import json
import os
import tempfile
import unittest

from core.io import export_final_images, preview_final_image_export
from core.project import Project, PromptLine
from core.route_operations import resolve_selected_route_export_lines


def _line(line_id, text="prompt", *, line_type=None, deleted=False, current_index=0, image_path=None):
    return PromptLine(
        id=line_id,
        original_file_name=line_id,
        original_index=current_index,
        current_index=current_index,
        original_text=text,
        current_text=text,
        tokens=[text],
        line_type=line_type,
        deleted=deleted,
        image_path=image_path,
    )


def _project(tmpdir):
    route_a_image = os.path.join(tmpdir, "route_a.png")
    route_c_image = os.path.join(tmpdir, "route_c.png")
    workbench_image = os.path.join(tmpdir, "workbench.png")
    deleted_image = os.path.join(tmpdir, "deleted.png")
    for path, contents in (
        (route_a_image, b"route-a"),
        (route_c_image, b"route-c"),
        (workbench_image, b"workbench"),
        (deleted_image, b"deleted"),
    ):
        with open(path, "wb") as handle:
            handle.write(contents)

    lines = [
        _line("route_a", "Route A", line_type="separator", current_index=0),
        _line("a1", current_index=1, image_path=route_a_image),
        _line("a_workbench", line_type="workbench", current_index=2, image_path=workbench_image),
        _line("a_deleted", current_index=3, deleted=True, image_path=deleted_image),
        _line("a_empty", current_index=4),
        _line("route_b", "Route B", line_type="separator", current_index=5),
        _line("b1", current_index=6),
        _line("route_c", "Route C", line_type="separator", current_index=7),
        _line("c1", current_index=8, image_path=route_c_image),
    ]
    return Project(prompt_lines=lines), lines


class FinalExportSelectedRoutesTests(unittest.TestCase):
    def test_resolver_uses_project_order_and_excludes_special_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, _lines = _project(tmpdir)

            result = resolve_selected_route_export_lines(
                project,
                ["route_c", "route_a", "missing_route", "a1"],
            )

            self.assertEqual(["route_a", "route_c"], result["resolved_route_handles"])
            self.assertEqual(["Route A", "Route C"], result["resolved_route_labels"])
            self.assertEqual(["a1", "a_empty", "c1"], result["target_line_ids"])
            self.assertNotIn("route_a", result["target_line_ids"])
            self.assertNotIn("a_workbench", result["target_line_ids"])
            self.assertNotIn("a_deleted", result["target_line_ids"])
            self.assertTrue(any("missing Route id" in item for item in result["diagnostics"]))
            self.assertTrue(any("non-separator selected id: a1" in item for item in result["diagnostics"]))

    def test_duplicate_member_id_is_skipped_with_diagnostic(self):
        project = Project(
            prompt_lines=[
                _line("route_a", "Route A", line_type="separator", current_index=0),
                _line("duplicate", current_index=1),
                _line("duplicate", current_index=2),
            ]
        )

        result = resolve_selected_route_export_lines(project, ["route_a"])

        self.assertEqual([], result["target_line_ids"])
        self.assertFalse(result["valid"])
        self.assertTrue(any("ambiguous selected Route line id: duplicate" in item for item in result["diagnostics"]))

    def test_selected_routes_preview_keeps_resolved_project_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, lines = _project(tmpdir)
            lines[1].current_index = 20
            lines[-1].current_index = 1
            resolution = resolve_selected_route_export_lines(project, ["route_c", "route_a"])

            preview = preview_final_image_export(
                project,
                base_filename="final",
                target_line_ids=resolution["target_line_ids"],
                export_scope="selected_routes",
            )

            self.assertEqual(["a1", "c1"], [item["line_id"] for item in preview["items"]])
            preview_by_line_id = {item["line_id"]: item for item in preview["items"]}
            self.assertEqual("route_a", preview_by_line_id["a1"]["route_id"])
            self.assertEqual("route_c", preview_by_line_id["c1"]["route_id"])
            self.assertEqual([1, 8], [item["project_order"] for item in preview["items"]])

    def test_empty_selection_and_malformed_project_are_invalid_without_mutation(self):
        project = Project(prompt_lines=[])
        result = resolve_selected_route_export_lines(project, [])
        self.assertFalse(result["valid"])
        self.assertEqual("no selected Routes", result["reason"])

        malformed = Project(prompt_lines="invalid")
        malformed_result = resolve_selected_route_export_lines(malformed, ["route_a"])
        self.assertFalse(malformed_result["valid"])
        self.assertTrue(any("prompt_lines is not a list" in item for item in malformed_result["diagnostics"]))
        self.assertEqual("invalid", malformed.prompt_lines)

    def test_route_line_order_excludes_workbench_and_counts_image_less_normal_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_paths = {
                line_id: os.path.join(tmpdir, f"{line_id}.png")
                for line_id in ("a1", "a2", "a4")
            }
            for path in image_paths.values():
                with open(path, "wb") as handle:
                    handle.write(b"image")

            project = Project(
                prompt_lines=[
                    _line("route_a", "Route A", line_type="separator", current_index=0),
                    _line("a1", current_index=1, image_path=image_paths["a1"]),
                    _line("a_workbench", line_type="workbench", current_index=2),
                    _line("a2", current_index=3, image_path=image_paths["a2"]),
                    _line("a3", current_index=4),
                    _line("a4", current_index=5, image_path=image_paths["a4"]),
                ]
            )
            resolution = resolve_selected_route_export_lines(project, ["route_a"])
            output_dir = os.path.join(tmpdir, "exports")

            preview = preview_final_image_export(
                project,
                output_dir,
                target_line_ids=resolution["target_line_ids"],
                export_scope="selected_routes",
            )

            self.assertEqual(["a1", "a2", "a4"], [item["line_id"] for item in preview["items"]])
            self.assertEqual([0, 1, 3], [item["route_line_order"] for item in preview["items"]])
            self.assertEqual(["a3"], [item["line_id"] for item in preview["skipped_items"]])
            self.assertEqual([2], [item["route_line_order"] for item in preview["skipped_items"]])
            self.assertNotIn("a_workbench", resolution["target_line_ids"])

            export_summary = export_final_images(
                project,
                output_dir,
                strip_metadata=False,
                target_line_ids=resolution["target_line_ids"],
                export_scope="selected_routes",
            )
            with open(export_summary["manifest_path"], "r", encoding="utf-8") as handle:
                manifest = json.load(handle)

            self.assertEqual([0, 1, 3], [item["route_line_order"] for item in manifest["items"]])
            self.assertEqual([2], [item["route_line_order"] for item in manifest["skipped_items"]])

    def test_preview_and_export_keep_continuous_filename_order_and_manifest_route_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, lines = _project(tmpdir)
            lines[1].current_index = 20
            lines[-1].current_index = 1
            resolution = resolve_selected_route_export_lines(project, ["route_c", "route_a"])
            output_dir = os.path.join(tmpdir, "exports")
            before = copy.deepcopy(
                [(line.id, line.current_text, line.image_path, line.deleted) for line in lines]
            )

            preview = preview_final_image_export(
                project,
                output_dir,
                base_filename="final",
                start_index=1,
                digits=4,
                target_line_ids=resolution["target_line_ids"],
                export_scope="selected_routes",
                selected_route_handles=resolution["resolved_route_handles"],
                selected_route_labels=resolution["resolved_route_labels"],
                selected_route_count=resolution["selected_route_count"],
                route_summaries=resolution["route_summaries"],
            )

            self.assertEqual(["a1", "c1"], [item["line_id"] for item in preview["items"]])
            self.assertEqual([1, 8], [item["project_order"] for item in preview["items"]])
            self.assertEqual(["route_a", "route_c"], [item["route_id"] for item in preview["items"]])
            self.assertEqual([0, 0], [item["route_line_order"] for item in preview["items"]])
            self.assertEqual(["image_path", "image_path"], [item["source_image_field"] for item in preview["items"]])
            self.assertEqual(["final_0001.png", "final_0002.png"], [
                item["output_filename"] for item in preview["items"]
            ])
            self.assertEqual(1, preview["skipped_count"])
            self.assertEqual(["route_a", "route_c"], preview["selected_route_handles"])
            self.assertEqual(["Route A", "Route C"], preview["selected_route_labels"])
            self.assertEqual(2, preview["selected_route_count"])
            self.assertEqual(3, preview["target_line_count"])

            summary = export_final_images(
                project,
                output_dir,
                strip_metadata=False,
                base_filename="final",
                target_line_ids=resolution["target_line_ids"],
                export_scope="selected_routes",
                selected_route_handles=resolution["resolved_route_handles"],
                selected_route_labels=resolution["resolved_route_labels"],
                selected_route_count=resolution["selected_route_count"],
                route_summaries=resolution["route_summaries"],
            )

            self.assertEqual(2, summary["exported_count"])
            self.assertTrue(os.path.isfile(summary["manifest_path"]))
            with open(summary["manifest_path"], "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual("selected_routes", manifest["export_scope"])
            self.assertEqual(["route_a", "route_c"], manifest["selected_route_handles"])
            self.assertEqual(["Route A", "Route C"], manifest["selected_route_labels"])
            self.assertEqual(2, manifest["selected_route_count"])
            self.assertEqual(2, manifest["total_exported_count"])
            self.assertEqual(1, manifest["skipped_count"])
            self.assertEqual([1, 8], [item["project_order"] for item in manifest["items"]])
            self.assertEqual(["route_a", "route_c"], [item["route_id"] for item in manifest["items"]])
            self.assertEqual(["image_path", "image_path"], [item["source_image_field"] for item in manifest["items"]])
            self.assertEqual(before, [
                (line.id, line.current_text, line.image_path, line.deleted) for line in lines
            ])


if __name__ == "__main__":
    unittest.main()
