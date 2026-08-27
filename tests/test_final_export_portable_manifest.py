import copy
import hashlib
import json
import ntpath
import os
import posixpath
import shutil
import tempfile
import unittest
from pathlib import Path

from core.io import (
    FINAL_EXPORT_MANIFEST_VERSION,
    FINAL_EXPORT_PATH_CONTRACT,
    _build_portable_final_export_manifest,
    _portable_final_export_output_path,
    _portable_final_export_project_file,
    _portable_final_export_source_reference,
    export_final_images,
    preview_final_image_export,
)
from core.project import Project, PromptLine


def _line(
    line_id,
    *,
    image_path=None,
    original_file_name=None,
    text="prompt",
    negative_prompt="negative",
    line_type=None,
    index=0,
):
    return PromptLine(
        id=line_id,
        original_file_name=(
            original_file_name
            if original_file_name is not None
            else f"{line_id}.txt"
        ),
        original_index=index,
        current_index=index,
        original_text=text,
        current_text=text,
        tokens=[text],
        negative_prompt=negative_prompt,
        image_path=image_path,
        line_type=line_type,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FinalExportPortableHelperTests(unittest.TestCase):
    def test_project_file_projection_handles_windows_posix_and_unicode(self):
        cases = {
            r"C:\Users\PrivateName\Project\milku-set.json": "milku-set.json",
            r"\\server\share\private\project.json": "project.json",
            "/home/private/作品/カスタム.json": "カスタム.json",
            r"C:drive-relative.json": "drive-relative.json",
            "": "",
            "..": "",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(
                    expected,
                    _portable_final_export_project_file(value),
                )

    def test_source_projection_is_project_relative_external_or_unknown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "PRIVATE_PROJECT_MARKER"
            project_root.mkdir()
            project_path = project_root / "custom.json"
            project_path.write_text("{}", encoding="utf-8")
            local_source = project_root / "candidates" / "line" / "候補.png"
            local_source.parent.mkdir(parents=True)
            local_source.write_bytes(b"local")
            external_source = root / "PRIVATE_EXTERNAL_MARKER" / "external.png"
            external_source.parent.mkdir()
            external_source.write_bytes(b"external")

            self.assertEqual(
                {
                    "source_image_path": "candidates/line/候補.png",
                    "source_image_scope": "project",
                },
                _portable_final_export_source_reference(
                    str(local_source),
                    str(project_path),
                ),
            )
            self.assertEqual(
                {
                    "source_image_path": "external.png",
                    "source_image_scope": "external",
                },
                _portable_final_export_source_reference(
                    str(external_source),
                    str(project_path),
                ),
            )
            self.assertEqual(
                {
                    "source_image_path": "",
                    "source_image_scope": "unknown",
                },
                _portable_final_export_source_reference(
                    str(root / "missing.png"),
                    str(project_path),
                ),
            )

    def test_output_projection_is_verified_and_flat(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_dir = root / "export"
            export_dir.mkdir()
            exported = export_dir / "final_0001.png"
            exported.write_bytes(b"image")
            outside = root / "outside.png"
            outside.write_bytes(b"outside")

            self.assertEqual(
                "final_0001.png",
                _portable_final_export_output_path(
                    str(exported),
                    str(export_dir),
                    output_filename="final_0001.png",
                ),
            )
            with self.assertRaises(ValueError):
                _portable_final_export_output_path(
                    str(outside),
                    str(export_dir),
                    output_filename="outside.png",
                )
            with self.assertRaises(ValueError):
                _portable_final_export_output_path(
                    str(exported),
                    str(export_dir),
                    output_filename="different.png",
                )

    def test_project_symlink_escape_is_external(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            project_path = project_root / "project.json"
            project_path.write_text("{}", encoding="utf-8")
            external = root / "private" / "real.png"
            external.parent.mkdir()
            external.write_bytes(b"external")
            link = project_root / "refs" / "linked.png"
            link.parent.mkdir()
            try:
                link.symlink_to(external)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            self.assertEqual(
                {
                    "source_image_path": "linked.png",
                    "source_image_scope": "external",
                },
                _portable_final_export_source_reference(
                    str(link),
                    str(project_path),
                ),
            )

    def test_manifest_builder_does_not_mutate_internal_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = root / "project.json"
            project_path.write_text("{}", encoding="utf-8")
            source = root / "generated" / "source.png"
            source.parent.mkdir()
            source.write_bytes(b"source")
            export_dir = root / "exports"
            export_dir.mkdir()
            output = export_dir / "final_0001.png"
            output.write_bytes(b"source")
            preview = {
                "base_filename": "final",
                "start_index": 1,
                "digits": 4,
                "export_scope": "all_lines",
                "selected_route_handles": [],
                "selected_route_labels": [],
                "selected_route_count": 0,
                "route_summaries": [],
                "skipped_items": [],
            }
            exported_items = [
                {
                    "line_id": "line-1",
                    "line_index": 0,
                    "project_order": 0,
                    "source_original_filename": r"C:\private\source.txt",
                    "source_image_path": str(source),
                    "source_image_field": "image_path",
                    "output_filename": output.name,
                    "output_path": str(output),
                    "route": {"route_id": "route-1"},
                    "prompt_text": r"C:\UserAuthored\prompt stays unchanged",
                    "negative_prompt": "negative",
                }
            ]
            before_preview = copy.deepcopy(preview)
            before_items = copy.deepcopy(exported_items)

            manifest = _build_portable_final_export_manifest(
                preview=preview,
                exported_items=exported_items,
                export_dir=str(export_dir),
                project_path=str(project_path),
                strip_metadata=False,
                metadata_stripped_count=0,
                skipped_line_ids=[],
                warnings=[],
                exported_at="2026-08-04T00:00:00+00:00",
            )

            self.assertEqual(before_preview, preview)
            self.assertEqual(before_items, exported_items)
            self.assertEqual("source.txt", manifest["items"][0]["source_original_filename"])
            self.assertEqual(
                r"C:\UserAuthored\prompt stays unchanged",
                manifest["items"][0]["prompt_text"],
            )


class FinalExportPortableManifestTests(unittest.TestCase):
    def _assert_portable_path_fields(self, manifest):
        self.assertFalse(ntpath.isabs(manifest["project_path"]))
        self.assertFalse(posixpath.isabs(manifest["project_path"]))
        self.assertEqual("", ntpath.splitdrive(manifest["project_path"])[0])
        self.assertNotIn("/", manifest["project_path"])
        self.assertNotIn("\\", manifest["project_path"])
        self.assertEqual(".", manifest["output_dir"])
        for item in manifest["items"]:
            for field in (
                "source_image_path",
                "output_path",
                "source_original_filename",
            ):
                value = item[field]
                self.assertFalse(ntpath.isabs(value), (field, value))
                self.assertFalse(posixpath.isabs(value), (field, value))
                self.assertEqual("", ntpath.splitdrive(value)[0], (field, value))
                self.assertNotIn("..", value.replace("\\", "/").split("/"))
            self.assertNotIn("\\", item["source_image_path"])
            self.assertNotIn("\\", item["output_path"])
            self.assertNotIn("/", item["source_original_filename"])
            self.assertNotIn("\\", item["source_original_filename"])

    def test_export_manifest_is_share_safe_and_movable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_marker = "PRIVATE_USER_MARKER_7E9C"
            external_marker = "PRIVATE_EXTERNAL_MARKER_4B2A"
            export_marker = "PRIVATE_EXPORT_MARKER_9C1D"
            project_root = root / project_marker / "作品"
            project_root.mkdir(parents=True)
            project_path = project_root / "みるく-set.json"
            project_path.write_text("{}", encoding="utf-8")

            sources = {
                "candidate": project_root / "candidates" / "line_1" / "候補.png",
                "generated": project_root / "generated" / "生成.png",
                "ref": project_root / "refs" / "参照.jpg",
                "external": root / external_marker / "source" / "外部.webp",
            }
            for index, source in enumerate(sources.values(), start=1):
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(f"image-{index}".encode("utf-8"))

            route = _line(
                "route-a",
                text="海辺のScene",
                line_type="separator",
                index=0,
            )
            route.separator_label = "海辺/Route"
            candidate_line = _line(
                "candidate",
                image_path=str(sources["ref"]),
                original_file_name=r"C:\private\候補.txt",
                text=r"user text C:\Users\Authored\keep",
                index=1,
            )
            candidate_line.selected_candidate_path = str(sources["candidate"])
            candidate_line.generated_image_path = str(sources["generated"])
            generated_line = _line(
                "generated",
                original_file_name="nested/path/生成.txt",
                text="生成 prompt",
                index=2,
            )
            generated_line.generated_image_path = str(sources["generated"])
            ref_line = _line(
                "ref",
                image_path=str(sources["ref"]),
                original_file_name="参照.txt",
                text="参照 prompt",
                index=3,
            )
            external_line = _line(
                "external",
                image_path=str(sources["external"]),
                original_file_name="外部.txt",
                text="外部 prompt",
                index=4,
            )
            skipped = _line(
                "skipped",
                original_file_name=r"C:\private\skipped.txt",
                text="skip prompt",
                index=5,
            )
            project = Project(
                prompt_lines=[
                    route,
                    candidate_line,
                    generated_line,
                    ref_line,
                    external_line,
                    skipped,
                ]
            )
            project_before = copy.deepcopy(project)
            source_bytes = {
                name: path.read_bytes() for name, path in sources.items()
            }
            output_dir = root / export_marker / "final"

            preview = preview_final_image_export(
                project,
                str(output_dir),
                project_path=str(project_path),
                base_filename="みるく",
                export_scope="selected_routes",
                selected_route_handles=["route-a"],
                selected_route_labels=["海辺/Route"],
                selected_route_count=1,
                route_summaries=[
                    {
                        "route_id": "route-a",
                        "route_label": "海辺/Route",
                    }
                ],
            )
            preview_before = copy.deepcopy(preview)
            self.assertTrue(os.path.isabs(preview["output_dir"]))
            self.assertTrue(
                all(
                    os.path.isabs(item["source_image_path"])
                    and os.path.isabs(item["output_path"])
                    for item in preview["items"]
                )
            )

            summary = export_final_images(
                project,
                str(output_dir),
                project_path=str(project_path),
                strip_metadata=False,
                base_filename="みるく",
                export_scope="selected_routes",
                selected_route_handles=["route-a"],
                selected_route_labels=["海辺/Route"],
                selected_route_count=1,
                route_summaries=[
                    {
                        "route_id": "route-a",
                        "route_label": "海辺/Route",
                    }
                ],
            )

            self.assertEqual(preview_before, preview)
            self.assertEqual(project_before, project)
            self.assertTrue(os.path.isabs(summary["output_dir"]))
            self.assertTrue(
                all(os.path.isabs(path) for path in summary["exported_paths"])
            )
            self.assertTrue(os.path.isabs(summary["manifest_path"]))
            raw_manifest = Path(summary["manifest_path"]).read_text(
                encoding="utf-8"
            )
            manifest = json.loads(raw_manifest)

            for marker in (project_marker, external_marker, export_marker):
                self.assertNotIn(marker, raw_manifest)
            for private_root in (
                str(project_root),
                str(project_path),
                str(output_dir),
                str(sources["external"].parent),
            ):
                self.assertNotIn(private_root, raw_manifest)
            self.assertEqual(
                FINAL_EXPORT_MANIFEST_VERSION,
                manifest["manifest_version"],
            )
            self.assertEqual(
                FINAL_EXPORT_PATH_CONTRACT,
                manifest["path_contract"],
            )
            self.assertEqual("みるく-set.json", manifest["project_path"])
            self.assertEqual("みるく-set.json", manifest["project_name"])
            self.assertEqual(".", manifest["output_dir"])
            self.assertEqual("selected_routes", manifest["export_scope"])
            self.assertEqual(["route-a"], manifest["selected_route_handles"])
            self.assertEqual(["海辺/Route"], manifest["selected_route_labels"])
            self.assertEqual(
                [
                    "みるく_0001.png",
                    "みるく_0002.png",
                    "みるく_0003.jpg",
                    "みるく_0004.webp",
                ],
                [item["output_path"] for item in manifest["items"]],
            )
            self.assertEqual(
                ["project", "project", "project", "external"],
                [item["source_image_scope"] for item in manifest["items"]],
            )
            self.assertEqual(
                [
                    "candidates/line_1/候補.png",
                    "generated/生成.png",
                    "refs/参照.jpg",
                    "外部.webp",
                ],
                [item["source_image_path"] for item in manifest["items"]],
            )
            self.assertEqual(
                ["候補.txt", "生成.txt", "参照.txt", "外部.txt"],
                [item["source_original_filename"] for item in manifest["items"]],
            )
            self.assertEqual(
                "skipped.txt",
                manifest["skipped_items"][0]["source_original_filename"],
            )
            self.assertEqual(
                r"user text C:\Users\Authored\keep",
                manifest["items"][0]["prompt_text"],
            )
            self._assert_portable_path_fields(manifest)

            exported_before_move = {
                item["output_path"]: _sha256(
                    Path(summary["manifest_path"]).parent / item["output_path"]
                )
                for item in manifest["items"]
            }
            moved_root = root / "MOVED_PRIVATE_MARKER" / "shared-export"
            moved_root.parent.mkdir()
            shutil.move(str(output_dir), str(moved_root))
            moved_manifest_path = moved_root / "export_manifest.json"
            moved_manifest = json.loads(
                moved_manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(".", moved_manifest["output_dir"])
            for item in moved_manifest["items"]:
                resolved = (moved_manifest_path.parent / item["output_path"]).resolve()
                self.assertTrue(resolved.is_file())
                self.assertEqual(
                    os.path.commonpath(
                        [str(resolved), str(moved_manifest_path.parent.resolve())]
                    ),
                    str(moved_manifest_path.parent.resolve()),
                )
                self.assertEqual(
                    exported_before_move[item["output_path"]],
                    _sha256(resolved),
                )
            for name, path in sources.items():
                self.assertEqual(source_bytes[name], path.read_bytes())

    def test_selection_priority_and_trashed_candidate_fallback_are_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = root / "project.json"
            project_path.write_text("{}", encoding="utf-8")
            paths = {
                name: root / "generated" / f"{name}.png"
                for name in ("selected", "generated", "main", "trashed")
            }
            for name, path in paths.items():
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(name.encode("utf-8"))

            priority = _line(
                "priority",
                image_path=str(paths["main"]),
                index=0,
            )
            priority.selected_candidate_path = str(paths["selected"])
            priority.generated_image_path = str(paths["generated"])
            fallback = _line(
                "fallback",
                image_path=str(paths["main"]),
                index=1,
            )
            fallback.selected_candidate_path = str(paths["trashed"])
            fallback.generated_image_path = str(paths["generated"])
            fallback.generated_candidates = [
                {"path": str(paths["trashed"]), "trashed": True}
            ]
            project = Project(prompt_lines=[priority, fallback])

            preview = preview_final_image_export(
                project,
                str(root / "exports"),
                project_path=str(project_path),
            )
            self.assertEqual(
                [str(paths["selected"]), str(paths["generated"])],
                [item["source_image_path"] for item in preview["items"]],
            )
            self.assertEqual(
                ["selected_candidate_path", "generated_image_path"],
                [item["source_image_field"] for item in preview["items"]],
            )

            summary = export_final_images(
                project,
                str(root / "exports"),
                project_path=str(project_path),
            )
            manifest = json.loads(
                Path(summary["manifest_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                ["generated/selected.png", "generated/generated.png"],
                [item["source_image_path"] for item in manifest["items"]],
            )
            self.assertEqual(
                ["project", "project"],
                [item["source_image_scope"] for item in manifest["items"]],
            )

    def test_metadata_strip_and_manifest_disabled_contracts_are_unchanged(self):
        try:
            from PIL import Image
            from PIL.PngImagePlugin import PngInfo
        except ImportError:
            self.skipTest("Pillow unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = root / "project.json"
            project_path.write_text("{}", encoding="utf-8")
            source = root / "generated" / "source.png"
            source.parent.mkdir()
            metadata = PngInfo()
            metadata.add_text("prompt", "synthetic metadata")
            Image.new("RGB", (4, 4), (12, 34, 56)).save(
                source,
                pnginfo=metadata,
            )
            source_before = source.read_bytes()
            project = Project(
                prompt_lines=[_line("line", image_path=str(source))]
            )

            copied = export_final_images(
                project,
                str(root / "copy"),
                project_path=str(project_path),
                strip_metadata=False,
            )
            self.assertEqual(
                source_before,
                Path(copied["exported_paths"][0]).read_bytes(),
            )
            copied_manifest = json.loads(
                Path(copied["manifest_path"]).read_text(encoding="utf-8")
            )
            self.assertFalse(copied_manifest["metadata_stripped"])
            self.assertEqual(0, copied_manifest["metadata_stripped_count"])

            stripped = export_final_images(
                project,
                str(root / "stripped"),
                project_path=str(project_path),
                strip_metadata=True,
            )
            with Image.open(stripped["exported_paths"][0]) as image:
                self.assertNotIn("prompt", image.info)
                self.assertEqual((4, 4), image.size)
            stripped_manifest = json.loads(
                Path(stripped["manifest_path"]).read_text(encoding="utf-8")
            )
            self.assertTrue(stripped_manifest["metadata_stripped"])
            self.assertEqual(1, stripped_manifest["metadata_stripped_count"])
            self.assertEqual(source_before, source.read_bytes())

            no_manifest_dir = root / "without-manifest"
            no_manifest = export_final_images(
                project,
                str(no_manifest_dir),
                project_path=str(project_path),
                strip_metadata=False,
                write_manifest=False,
            )
            self.assertEqual("", no_manifest["manifest_path"])
            self.assertFalse(
                (no_manifest_dir / "export_manifest.json").exists()
            )
            self.assertTrue(
                os.path.isabs(no_manifest["exported_paths"][0])
            )


if __name__ == "__main__":
    unittest.main()
