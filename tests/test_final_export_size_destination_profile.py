import ast
import copy
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.io import (
    _final_export_source_size,
    export_final_images,
    preview_final_image_export,
    profile_final_export_destination,
)
from core.project import Project, PromptLine


def _line(
    line_id,
    *,
    image_path=None,
    line_type=None,
    deleted=False,
    index=0,
):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.txt",
        original_index=index,
        current_index=index,
        original_text=line_id,
        current_text=line_id,
        tokens=[line_id],
        image_path=image_path,
        line_type=line_type,
        deleted=deleted,
    )


def _saved_project_path(root: Path) -> Path:
    project_path = root / "project.json"
    project_path.write_text('{"saved":true}\n', encoding="utf-8")
    return project_path


def _usage(total=10_000, used=1_000, free=9_000):
    return mock.Mock(total=total, used=used, free=free)


class FinalExportSizeAggregationTests(unittest.TestCase):
    def test_sizes_sum_per_export_item_without_source_deduplication(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_a = root / "a.png"
            source_b = root / "b.png"
            excluded = root / "excluded.png"
            source_a.write_bytes(b"a" * 10)
            source_b.write_bytes(b"b" * 20)
            excluded.write_bytes(b"x" * 99)
            project_path = _saved_project_path(root)
            project = Project(
                prompt_lines=[
                    _line("route", line_type="separator", index=0),
                    _line("a", image_path=str(source_a), index=1),
                    _line("b", image_path=str(source_b), index=2),
                    _line("a_again", image_path=str(source_a), index=3),
                    _line("empty", index=4),
                    _line(
                        "workbench",
                        image_path=str(excluded),
                        line_type="workbench",
                        index=5,
                    ),
                    _line(
                        "deleted",
                        image_path=str(excluded),
                        deleted=True,
                        index=6,
                    ),
                ]
            )
            output_dir = root / "exports" / "final" / "future"

            with mock.patch(
                "core.io.shutil.disk_usage",
                return_value=_usage(),
            ):
                preview = preview_final_image_export(
                    project,
                    str(output_dir),
                    project_path=str(project_path),
                    use_timestamp_subfolder=True,
                )

            self.assertEqual(preview["exportable_count"], 3)
            self.assertEqual(preview["skipped_count"], 1)
            self.assertEqual(preview["source_total_bytes"], 40)
            self.assertEqual(preview["source_size_known_count"], 3)
            self.assertEqual(preview["source_size_unknown_count"], 0)
            self.assertEqual(
                [item["source_size_bytes"] for item in preview["items"]],
                [10, 20, 10],
            )
            self.assertTrue(
                all(
                    item["source_size_available"]
                    for item in preview["items"]
                )
            )
            self.assertFalse(output_dir.exists())

    def test_target_scope_counts_only_selected_exportable_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_a = root / "a.png"
            source_b = root / "b.png"
            source_a.write_bytes(b"a" * 10)
            source_b.write_bytes(b"b" * 20)
            project = Project(
                prompt_lines=[
                    _line("a", image_path=str(source_a), index=0),
                    _line("b", image_path=str(source_b), index=1),
                    _line("empty", index=2),
                ]
            )

            preview = preview_final_image_export(
                project,
                target_line_ids=["b", "empty"],
                export_scope="selected_routes",
            )

            self.assertEqual(
                [item["line_id"] for item in preview["items"]],
                ["b"],
            )
            self.assertEqual(preview["source_total_bytes"], 20)
            self.assertEqual(preview["skipped_count"], 1)

    def test_source_size_failure_is_unknown_without_failing_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_a = root / "a.png"
            source_b = root / "b.png"
            source_a.write_bytes(b"a" * 10)
            source_b.write_bytes(b"b" * 20)
            project = Project(
                prompt_lines=[
                    _line("a", image_path=str(source_a), index=0),
                    _line("b", image_path=str(source_b), index=1),
                ]
            )
            real_size = _final_export_source_size

            def size_or_failure(path):
                if os.path.normcase(path) == os.path.normcase(str(source_b)):
                    return {
                        "source_size_bytes": None,
                        "source_size_available": False,
                        "source_size_error": "simulated stat failure",
                    }
                return real_size(path)

            with mock.patch(
                "core.io._final_export_source_size",
                side_effect=size_or_failure,
            ):
                preview = preview_final_image_export(project)

            self.assertEqual(preview["source_total_bytes"], 10)
            self.assertEqual(preview["source_size_known_count"], 1)
            self.assertEqual(preview["source_size_unknown_count"], 1)
            failed = next(
                item for item in preview["items"] if item["line_id"] == "b"
            )
            self.assertIsNone(failed["source_size_bytes"])
            self.assertFalse(failed["source_size_available"])
            self.assertEqual(
                failed["source_size_error"],
                "simulated stat failure",
            )
            self.assertEqual(
                preview["destination_profile"]["capacity_status"],
                "unknown",
            )

    def test_source_stat_failure_helper_is_fail_soft(self):
        with mock.patch(
            "core.io.os.stat",
            side_effect=OSError("unreadable"),
        ):
            result = _final_export_source_size("unreadable.png")

        self.assertFalse(result["source_size_available"])
        self.assertIsNone(result["source_size_bytes"])
        self.assertIn("unreadable", result["source_size_error"])


class FinalExportDestinationProfileTests(unittest.TestCase):
    def test_project_local_destination_kinds_and_path_normalization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = _saved_project_path(root)
            final_root = root / "exports" / "final"
            timestamp_dir = final_root / "2026-07-31_1200"
            custom_dir = final_root / "custom"
            outside_dir = root / "elsewhere"

            with mock.patch(
                "core.io.shutil.disk_usage",
                return_value=_usage(),
            ):
                final_profile = profile_final_export_destination(
                    str(final_root / "child" / ".."),
                    project_path=str(project_path),
                    planned_items=[],
                )
                timestamp_profile = profile_final_export_destination(
                    str(timestamp_dir),
                    project_path=str(project_path),
                    planned_items=[],
                    use_timestamp_subfolder=True,
                )
                custom_profile = profile_final_export_destination(
                    str(custom_dir),
                    project_path=str(project_path),
                    planned_items=[],
                    use_timestamp_subfolder=False,
                )
                outside_profile = profile_final_export_destination(
                    str(outside_dir),
                    project_path=str(project_path),
                    planned_items=[],
                )

            self.assertEqual(
                final_profile["destination_kind"],
                "final_root",
            )
            self.assertTrue(final_profile["is_final_root"])
            self.assertEqual(
                timestamp_profile["destination_kind"],
                "timestamp_subfolder",
            )
            self.assertEqual(
                timestamp_profile["destination_label"],
                "Project-local timestamp folder",
            )
            self.assertEqual(
                custom_profile["destination_kind"],
                "final_subfolder",
            )
            self.assertEqual(
                outside_profile["destination_kind"],
                "outside_final_root",
            )
            self.assertTrue(outside_profile["inside_project"])
            self.assertFalse(outside_profile["inside_final_root"])

    def test_unsaved_malformed_and_different_drive_destinations_are_unknown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = _saved_project_path(root)

            unsaved = profile_final_export_destination(
                str(root / "exports" / "final"),
                planned_items=[],
            )
            malformed = profile_final_export_destination(
                "bad\x00path",
                project_path=str(project_path),
                planned_items=[],
            )

            self.assertEqual(unsaved["destination_kind"], "unknown")
            self.assertEqual(malformed["destination_kind"], "unknown")
            if os.name == "nt":
                different_drive = profile_final_export_destination(
                    r"Z:\promptgraph\exports\final",
                    project_path=str(project_path),
                    planned_items=[],
                )
                self.assertEqual(
                    different_drive["destination_kind"],
                    "unknown",
                )

    @unittest.skipUnless(os.name == "nt", "Windows case folding")
    def test_windows_case_normalization_keeps_final_root_classification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = _saved_project_path(root)
            final_root = str(root / "exports" / "final")

            profile = profile_final_export_destination(
                final_root.upper(),
                project_path=str(project_path).upper(),
                planned_items=[],
            )

            self.assertEqual(profile["destination_kind"], "final_root")

    def test_uncreated_output_uses_nearest_existing_parent_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = _saved_project_path(root)
            output_dir = root / "exports" / "final" / "future"
            items = [
                {
                    "output_path": str(output_dir / "final_0001.png"),
                    "output_filename": "final_0001.png",
                    "source_size_available": True,
                    "source_size_bytes": 100,
                }
            ]

            with mock.patch(
                "core.io.shutil.disk_usage",
                return_value=_usage(free=1_000),
            ) as disk_usage:
                profile = profile_final_export_destination(
                    str(output_dir),
                    project_path=str(project_path),
                    planned_items=items,
                    use_timestamp_subfolder=True,
                )

            disk_usage.assert_called_once_with(str(root))
            self.assertEqual(
                profile["nearest_existing_parent"],
                str(root),
            )
            self.assertFalse(profile["destination_exists"])
            self.assertEqual(profile["capacity_status"], "sufficient")
            self.assertFalse(output_dir.exists())

    def test_capacity_insufficient_and_unknown_are_fail_soft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = _saved_project_path(root)
            final_root = root / "exports" / "final"
            known_items = [
                {
                    "source_size_available": True,
                    "source_size_bytes": 200,
                }
            ]

            with mock.patch(
                "core.io.shutil.disk_usage",
                return_value=_usage(free=100),
            ):
                insufficient = profile_final_export_destination(
                    str(final_root),
                    project_path=str(project_path),
                    planned_items=known_items,
                )
            with mock.patch(
                "core.io.shutil.disk_usage",
                side_effect=OSError("disk unavailable"),
            ):
                unknown_disk = profile_final_export_destination(
                    str(final_root),
                    project_path=str(project_path),
                    planned_items=known_items,
                )
            with mock.patch(
                "core.io.shutil.disk_usage",
                return_value=_usage(free=1_000),
            ):
                unknown_source = profile_final_export_destination(
                    str(final_root),
                    project_path=str(project_path),
                    planned_items=[
                        {
                            "source_size_available": False,
                            "source_size_bytes": None,
                        }
                    ],
                )

            self.assertEqual(
                insufficient["capacity_status"],
                "insufficient",
            )
            self.assertEqual(unknown_disk["capacity_status"], "unknown")
            self.assertEqual(
                unknown_source["capacity_status"],
                "unknown",
            )
            self.assertTrue(unknown_disk["warnings"])

    def test_planned_overwrites_bytes_and_manifest_are_aggregated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = _saved_project_path(root)
            final_root = root / "exports" / "final"
            final_root.mkdir(parents=True)
            output_a = final_root / "final_0001.png"
            output_b = final_root / "final_0002.png"
            output_a.write_bytes(b"a" * 5)
            output_b.write_bytes(b"b" * 7)
            (final_root / "export_manifest.json").write_text(
                "{}",
                encoding="utf-8",
            )
            items = [
                {
                    "output_path": str(output_a),
                    "output_filename": output_a.name,
                    "source_size_available": True,
                    "source_size_bytes": 1,
                },
                {
                    "output_path": str(output_b),
                    "output_filename": output_b.name,
                    "source_size_available": True,
                    "source_size_bytes": 1,
                },
                {
                    "output_path": str(final_root / "final_0003.png"),
                    "output_filename": "final_0003.png",
                    "source_size_available": True,
                    "source_size_bytes": 1,
                },
            ]

            with mock.patch(
                "core.io.shutil.disk_usage",
                return_value=_usage(),
            ):
                profile = profile_final_export_destination(
                    str(final_root),
                    project_path=str(project_path),
                    planned_items=items,
                )

            self.assertEqual(profile["existing_output_count"], 2)
            self.assertEqual(profile["existing_output_bytes"], 12)
            self.assertTrue(profile["manifest_exists"])
            self.assertEqual(profile["planned_output_count"], 3)

    def test_existing_output_stat_error_warns_without_failing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = _saved_project_path(root)
            final_root = root / "exports" / "final"
            bad_output = "bad\x00output.png"

            with mock.patch(
                "core.io.shutil.disk_usage",
                return_value=_usage(),
            ):
                profile = profile_final_export_destination(
                    str(final_root),
                    project_path=str(project_path),
                    planned_items=[
                        {
                            "output_path": bad_output,
                            "output_filename": "bad.png",
                            "source_size_available": True,
                            "source_size_bytes": 1,
                        }
                    ],
                )

            self.assertEqual(profile["existing_output_count"], 0)
            self.assertTrue(
                any(
                    "Existing output size unavailable" in warning
                    for warning in profile["warnings"]
                )
            )


class FinalExportSignatureAndRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        cls.app_source = app_path.read_text(encoding="utf-8")
        tree = ast.parse(cls.app_source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_final_export_preview_signature"
        )
        namespace = {
            "os": os,
            "json": json,
            "hashlib": __import__("hashlib"),
        }
        exec(ast.get_source_segment(cls.app_source, function), namespace)
        cls.signature = staticmethod(
            namespace["_final_export_preview_signature"]
        )

    def _signature_input(self):
        resolution = {
            "scope": "selected_routes",
            "resolved_route_handles": ["route-a"],
            "resolved_route_labels": ["Route A"],
            "route_summaries": [{"route_id": "route-a"}],
            "line_ids": ["line-a"],
        }
        preview = {
            "base_filename": "final",
            "items": [
                {
                    "line_id": "line-a",
                    "project_order": 1,
                    "source_image_path": "generated/a.png",
                    "source_image_field": "image_path",
                    "source_size_bytes": 10,
                    "source_size_available": True,
                    "output_filename": "final_0001.png",
                }
            ],
            "skipped_items": [],
            "destination_profile": {
                "disk_free_bytes": 100,
                "disk_used_bytes": 900,
                "capacity_status": "sufficient",
            },
        }
        return resolution, preview

    def _call_signature(
        self,
        resolution,
        preview,
        *,
        output_dir="exports/final/run",
        start_index=1,
        strip_metadata=True,
    ):
        return self.signature(
            resolution,
            preview,
            output_dir=output_dir,
            base_filename="final",
            start_index=start_index,
            digits=4,
            strip_metadata=strip_metadata,
        )

    def test_volatile_destination_capacity_does_not_change_signature(self):
        resolution, preview = self._signature_input()
        first = self._call_signature(resolution, preview)
        preview["destination_profile"] = {
            "disk_free_bytes": 1,
            "disk_used_bytes": 999,
            "capacity_status": "insufficient",
            "nearest_existing_parent": "different",
        }

        self.assertEqual(first, self._call_signature(resolution, preview))

    def test_export_inputs_change_signature(self):
        resolution, preview = self._signature_input()
        baseline = self._call_signature(resolution, preview)

        changed_path = copy.deepcopy(preview)
        changed_path["items"][0]["source_image_path"] = "generated/b.png"
        self.assertNotEqual(
            baseline,
            self._call_signature(resolution, changed_path),
        )

        changed_filename = copy.deepcopy(preview)
        changed_filename["items"][0]["output_filename"] = "other_0001.png"
        self.assertNotEqual(
            baseline,
            self._call_signature(resolution, changed_filename),
        )

        changed_routes = copy.deepcopy(resolution)
        changed_routes["resolved_route_handles"] = ["route-b"]
        self.assertNotEqual(
            baseline,
            self._call_signature(changed_routes, preview),
        )
        self.assertNotEqual(
            baseline,
            self._call_signature(
                resolution,
                preview,
                start_index=2,
            ),
        )
        self.assertNotEqual(
            baseline,
            self._call_signature(
                resolution,
                preview,
                strip_metadata=False,
            ),
        )

    def test_export_bytes_manifest_schema_and_project_remain_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jpg"
            source_bytes = b"synthetic-jpeg-bytes"
            source.write_bytes(source_bytes)
            project_path = _saved_project_path(root)
            project = Project(
                prompt_lines=[
                    _line("line-a", image_path=str(source), index=0)
                ]
            )
            project_before = copy.deepcopy(project)
            output_dir = root / "exports" / "final" / "run"

            summary = export_final_images(
                project,
                str(output_dir),
                project_path=str(project_path),
                strip_metadata=False,
            )

            exported = Path(summary["exported_paths"][0])
            self.assertEqual(exported.name, "final_0001.jpg")
            self.assertEqual(exported.read_bytes(), source_bytes)
            self.assertEqual(source.read_bytes(), source_bytes)
            self.assertEqual(project, project_before)
            manifest = json.loads(
                Path(summary["manifest_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["manifest_version"], 2)
            self.assertEqual(
                manifest["path_contract"],
                "portable-relative-v1",
            )
            self.assertEqual(manifest["project_path"], "project.json")
            self.assertEqual(manifest["output_dir"], ".")
            self.assertNotIn("source_total_bytes", manifest)
            self.assertNotIn("destination_profile", manifest)
            self.assertNotIn("capacity_status", manifest)
            self.assertNotIn("existing_output_count", manifest)
            self.assertNotIn("source_size_bytes", manifest["items"][0])
            self.assertEqual(
                set(manifest["items"][0]),
                {
                    "output_filename",
                    "source_line_id",
                    "source_line_index",
                    "project_order",
                    "source_original_filename",
                    "source_image_path",
                    "source_image_scope",
                    "source_image_field",
                    "output_path",
                    "route",
                    "route_id",
                    "route_label",
                    "route_order",
                    "route_line_order",
                    "prompt_text",
                    "negative_prompt",
                },
            )

    def test_self_overwrite_guard_remains_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "final_0001.png"
            source_bytes = b"project-linked-source"
            source.write_bytes(source_bytes)
            project = Project(
                prompt_lines=[
                    _line("line-a", image_path=str(source), index=0)
                ]
            )

            summary = export_final_images(
                project,
                str(root),
                strip_metadata=False,
            )

            self.assertEqual(summary["exported_count"], 0)
            self.assertEqual(source.read_bytes(), source_bytes)
            self.assertTrue(
                any(
                    "matches a project-linked source image" in warning
                    for warning in summary["warnings"]
                )
            )

    def test_png_metadata_strip_changes_only_exported_copy(self):
        try:
            from PIL import Image
            from PIL.PngImagePlugin import PngInfo
        except ImportError:
            self.skipTest("Pillow unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.png"
            metadata = PngInfo()
            metadata.add_text("prompt", "synthetic prompt")
            Image.new("RGB", (4, 4), (12, 34, 56)).save(
                source,
                pnginfo=metadata,
            )
            source_before = source.read_bytes()
            line = _line("line-a", image_path=str(source), index=0)
            line.generated_candidates = [
                {"path": str(root / "candidate.png")}
            ]
            line.gallery_variants = [
                {"id": "variant-a", "path": str(root / "variant.png")}
            ]
            project = Project(prompt_lines=[line])
            project_before = copy.deepcopy(project)
            output_dir = root / "exports" / "final" / "run"

            summary = export_final_images(
                project,
                str(output_dir),
                strip_metadata=True,
            )

            exported = Path(summary["exported_paths"][0])
            with Image.open(source) as source_image:
                self.assertEqual(
                    source_image.info.get("prompt"),
                    "synthetic prompt",
                )
            with Image.open(exported) as exported_image:
                self.assertNotIn("prompt", exported_image.info)
            self.assertEqual(source.read_bytes(), source_before)
            self.assertEqual(project, project_before)
            self.assertEqual(summary["metadata_stripped_count"], 1)

    def test_preview_implementation_has_no_recursive_or_content_reads(self):
        source = inspect.getsource(preview_final_image_export)
        profile_source = inspect.getsource(
            profile_final_export_destination
        )
        combined = source + profile_source
        for forbidden in (
            "os.walk(",
            "hashlib.",
            "Image.open(",
            "os.makedirs(",
            "open(",
            "export_final_images(",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertIn("os.stat(", profile_source)
        self.assertEqual(profile_source.count("shutil.disk_usage("), 1)


if __name__ == "__main__":
    unittest.main()
