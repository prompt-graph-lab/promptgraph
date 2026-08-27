import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.io import (
    ProjectAssetsPreviewStaleError,
    collect_project_serialized_path_references,
    delete_verified_project_asset_source_duplicates,
    preview_verified_project_asset_duplicate_cleanup,
)
from core.project import Project, PromptLine


def _line(line_id="line-a", index=0, **kwargs):
    values = {
        "id": line_id,
        "original_file_name": f"{line_id}.txt",
        "original_index": index,
        "current_index": index,
        "original_text": "prompt",
        "current_text": "prompt",
        "tokens": ["prompt"],
    }
    values.update(kwargs)
    return PromptLine(**values)


def _write_project_marker(project_path: Path) -> bytes:
    original = b'{"saved":"project","unchanged":true}\r\n'
    project_path.write_bytes(original)
    return original


class VerifiedDuplicateCleanupPreviewTests(unittest.TestCase):
    def test_eligible_source_requires_referenced_identical_candidate_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            generated = project_root / "generated"
            candidates = project_root / "candidates"
            generated.mkdir()
            candidates.mkdir()
            source = generated / "different-source-name.png"
            retained = candidates / "retained-copy.png"
            source.write_bytes(b"byte-identical-image")
            retained.write_bytes(source.read_bytes())
            project_path = project_root / "custom-project-name.json"
            _write_project_marker(project_path)
            project = Project(
                prompt_lines=[
                    _line(
                        generated_candidates=[
                            {"path": "candidates/retained-copy.png"}
                        ]
                    )
                ]
            )

            before_project = copy.deepcopy(project)
            before_json = project_path.read_bytes()
            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )

            self.assertTrue(preview["valid"])
            self.assertEqual(preview["eligible_count"], 1)
            self.assertEqual(preview["eligible_bytes"], source.stat().st_size)
            self.assertEqual(preview["duplicate_group_count"], 1)
            self.assertEqual(preview["retained_copy_count"], 1)
            self.assertEqual(
                preview["eligible_items"][0]["source_relative_path"],
                "generated/different-source-name.png",
            )
            self.assertEqual(
                preview["eligible_items"][0]["retained_relative_paths"],
                ["candidates/retained-copy.png"],
            )
            self.assertEqual(len(preview["eligible_items"][0]["sha256"]), 64)
            self.assertEqual(project, before_project)
            self.assertEqual(project_path.read_bytes(), before_json)

    def test_each_serialized_source_reference_protects_the_generated_file(self):
        cases = {
            "image_path": lambda line, project, path: setattr(
                line,
                "image_path",
                path,
            ),
            "generated_image_path": lambda line, project, path: setattr(
                line,
                "generated_image_path",
                path,
            ),
            "selected_candidate_path": lambda line, project, path: setattr(
                line,
                "selected_candidate_path",
                path,
            ),
            "generated_candidate": lambda line, project, path: (
                line.generated_candidates.append({"path": path})
            ),
            "gallery_variant": lambda line, project, path: (
                line.gallery_variants.append({"id": "source", "path": path})
            ),
            "lineage_nested": lambda line, project, path: (
                line.lineage_info.update({"future": [{"asset": path}]})
            ),
            "provenance_nested": lambda line, project, path: (
                line.source_generation_info.update(
                    {"provenance": {"source_asset": path}}
                )
            ),
            "project_metadata_nested": lambda line, project, path: (
                project.project_metadata.update(
                    {"future": {"nested": [{"path": path}]}}
                )
            ),
        }
        for case_name, configure in cases.items():
            with self.subTest(case=case_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    project_root = Path(temp_dir)
                    generated = project_root / "generated"
                    candidates = project_root / "candidates"
                    generated.mkdir()
                    candidates.mkdir()
                    source = generated / "source.png"
                    retained = candidates / "retained.png"
                    source.write_bytes(b"same")
                    retained.write_bytes(b"same")
                    project_path = project_root / "project.json"
                    _write_project_marker(project_path)
                    line = _line(
                        generated_candidates=[
                            {"path": "candidates/retained.png"}
                        ]
                    )
                    project = Project(prompt_lines=[line])
                    configure(line, project, "generated/source.png")

                    preview = (
                        preview_verified_project_asset_duplicate_cleanup(
                            project,
                            str(project_path),
                        )
                    )

                    self.assertEqual(preview["eligible_count"], 0)
                    protected = next(
                        item
                        for item in preview["protected_items"]
                        if item["source_relative_path"]
                        == "generated/source.png"
                    )
                    self.assertGreaterEqual(
                        protected["source_reference_count"],
                        1,
                    )
                    self.assertEqual(
                        protected["reason"],
                        "source is still referenced",
                    )

    def test_reference_collection_normalizes_relative_absolute_and_dot_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            generated = project_root / "generated"
            candidates = project_root / "candidates"
            generated.mkdir()
            candidates.mkdir()
            source = generated / "source.png"
            retained = candidates / "retained.png"
            source.write_bytes(b"source")
            retained.write_bytes(b"retained")
            line = _line(
                image_path=str(source),
                generated_image_path="generated/./source.png",
                generated_candidates=[
                    {"path": "candidates\\nested\\..\\retained.png"}
                ],
            )
            project = Project(
                prompt_lines=[line],
                project_metadata={
                    "outside": "../outside.png",
                    "inside": "generated/../generated/source.png",
                },
            )

            result = collect_project_serialized_path_references(
                project,
                project_root=str(project_root),
            )

            source_key = os.path.normcase(os.path.realpath(source))
            retained_key = os.path.normcase(os.path.realpath(retained))
            self.assertIn(source_key, result["references"])
            self.assertIn(retained_key, result["references"])
            self.assertGreaterEqual(len(result["references"][source_key]), 3)
            self.assertNotIn(
                os.path.normcase(
                    os.path.realpath(project_root.parent / "outside.png")
                ),
                result["references"],
            )

    def test_unreferenced_or_nonidentical_retained_file_does_not_qualify(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            generated = project_root / "generated"
            candidates = project_root / "candidates"
            generated.mkdir()
            candidates.mkdir()
            unreferenced_source = generated / "unreferenced.png"
            mismatch_source = generated / "mismatch.png"
            unreferenced_copy = candidates / "unreferenced-copy.png"
            mismatch_copy = candidates / "mismatch-copy.png"
            unreferenced_source.write_bytes(b"same")
            unreferenced_copy.write_bytes(b"same")
            mismatch_source.write_bytes(b"aaaa")
            mismatch_copy.write_bytes(b"bbbb")
            project_path = project_root / "project.json"
            _write_project_marker(project_path)
            project = Project(
                prompt_lines=[
                    _line(
                        generated_candidates=[
                            {"path": "candidates/mismatch-copy.png"}
                        ]
                    )
                ]
            )

            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )

            self.assertEqual(preview["eligible_count"], 0)
            reasons = {
                item["source_relative_path"]: item["reason"]
                for item in preview["protected_items"]
            }
            self.assertEqual(
                reasons["generated/unreferenced.png"],
                "no referenced retained candidate copy",
            )
            self.assertEqual(
                reasons["generated/mismatch.png"],
                "hash mismatch",
            )

    def test_multiple_identical_candidates_keep_only_referenced_copies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            generated = project_root / "generated"
            candidates = project_root / "candidates"
            generated.mkdir()
            candidates.mkdir()
            source = generated / "source.png"
            referenced = candidates / "referenced.png"
            unreferenced = candidates / "unreferenced.png"
            for path in (source, referenced, unreferenced):
                path.write_bytes(b"same-image")
            project_path = project_root / "project.json"
            _write_project_marker(project_path)
            project = Project(
                prompt_lines=[
                    _line(
                        generated_candidates=[
                            {"path": "candidates/referenced.png"}
                        ]
                    )
                ]
            )

            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )

            self.assertEqual(preview["eligible_count"], 1)
            self.assertEqual(
                preview["eligible_items"][0]["retained_relative_paths"],
                ["candidates/referenced.png"],
            )
            self.assertEqual(preview["retained_copy_count"], 1)

    def test_unsaved_project_and_missing_directories_fail_closed(self):
        project = Project(prompt_lines=[_line()])
        unsaved = preview_verified_project_asset_duplicate_cleanup(
            project,
            "",
        )
        self.assertFalse(unsaved["valid"])
        self.assertEqual(unsaved["reason"], "Project not saved.")

        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "project.json"
            _write_project_marker(project_path)
            missing = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )
            self.assertTrue(missing["valid"])
            self.assertEqual(missing["eligible_count"], 0)
            self.assertIn(
                "generated directory missing",
                missing["warnings"],
            )
            self.assertIn(
                "candidates directory missing",
                missing["warnings"],
            )

    def test_missing_referenced_project_assets_are_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / "generated").mkdir()
            (project_root / "candidates").mkdir()
            project_path = project_root / "project.json"
            _write_project_marker(project_path)
            project = Project(
                prompt_lines=[
                    _line(
                        image_path="generated/missing-source.png",
                        generated_candidates=[
                            {"path": "candidates/missing-retained.png"}
                        ],
                    )
                ]
            )

            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )

            missing_paths = {
                item["relative_path"]
                for item in preview["skipped_items"]
                if item["reason"] == "missing"
            }
            self.assertEqual(
                missing_paths,
                {
                    "generated/missing-source.png",
                    "candidates/missing-retained.png",
                },
            )

    def test_unreadable_image_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            generated = project_root / "generated"
            candidates = project_root / "candidates"
            generated.mkdir()
            candidates.mkdir()
            source = generated / "source.png"
            retained = candidates / "retained.png"
            source.write_bytes(b"same")
            retained.write_bytes(b"same")
            project_path = project_root / "project.json"
            _write_project_marker(project_path)
            project = Project(
                prompt_lines=[
                    _line(
                        generated_candidates=[
                            {"path": "candidates/retained.png"}
                        ]
                    )
                ]
            )
            real_open = open

            def reject_source(path, *args, **kwargs):
                if os.path.normcase(os.path.abspath(path)) == os.path.normcase(
                    os.path.abspath(source)
                ):
                    raise PermissionError("simulated unreadable source")
                return real_open(path, *args, **kwargs)

            with mock.patch("builtins.open", side_effect=reject_source):
                preview = preview_verified_project_asset_duplicate_cleanup(
                    project,
                    str(project_path),
                )

            self.assertEqual(preview["eligible_count"], 0)
            skipped = next(
                item
                for item in preview["skipped_items"]
                if item["relative_path"] == "generated/source.png"
            )
            self.assertIn("unreadable", skipped["reason"])

    def test_repeated_preview_signature_is_stable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            generated = project_root / "generated"
            candidates = project_root / "candidates"
            generated.mkdir()
            candidates.mkdir()
            source = generated / "source.png"
            retained = candidates / "retained.png"
            source.write_bytes(b"same")
            retained.write_bytes(b"same")
            project_path = project_root / "project.json"
            _write_project_marker(project_path)
            project = Project(
                prompt_lines=[
                    _line(
                        generated_candidates=[
                            {"path": "candidates/retained.png"}
                        ]
                    )
                ]
            )

            first = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )
            second = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )

            self.assertEqual(first["signature"], second["signature"])

    @unittest.skipUnless(
        hasattr(os, "symlink"),
        "symlink support is required",
    )
    def test_symlink_source_and_retained_copy_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            generated = project_root / "generated"
            candidates = project_root / "candidates"
            outside = project_root / "outside"
            generated.mkdir()
            candidates.mkdir()
            outside.mkdir()
            target = outside / "target.png"
            target.write_bytes(b"same")
            source_link = generated / "source.png"
            retained_link = candidates / "retained.png"
            try:
                os.symlink(target, source_link)
                os.symlink(target, retained_link)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            project_path = project_root / "project.json"
            _write_project_marker(project_path)
            project = Project(
                prompt_lines=[
                    _line(
                        generated_candidates=[
                            {"path": "candidates/retained.png"}
                        ]
                    )
                ]
            )

            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )

            self.assertEqual(preview["eligible_count"], 0)
            self.assertGreaterEqual(preview["skipped_count"], 2)
            self.assertTrue(
                all(
                    item["reason"] == "symlink"
                    for item in preview["skipped_items"]
                )
            )


class VerifiedDuplicateCleanupApplyTests(unittest.TestCase):
    def _fixture(self, root: Path, names=("a",)):
        generated = root / "generated"
        candidates = root / "candidates"
        generated.mkdir()
        candidates.mkdir()
        lines = []
        sources = []
        retained = []
        for index, name in enumerate(names):
            source = generated / f"{name}.png"
            retained_copy = candidates / f"{name}-retained.png"
            content = f"image-{name}".encode()
            source.write_bytes(content)
            retained_copy.write_bytes(content)
            sources.append(source)
            retained.append(retained_copy)
            lines.append(
                _line(
                    line_id=f"line-{name}",
                    index=index,
                    generated_candidates=[
                        {"path": f"candidates/{name}-retained.png"}
                    ],
                    gallery_variants=[
                        {
                            "id": f"variant-{name}",
                            "path": f"candidates/{name}-retained.png",
                        }
                    ],
                    lineage_info={
                        "candidate_image_path": (
                            f"candidates/{name}-retained.png"
                        )
                    },
                )
            )
        project_path = root / "project.json"
        original_json = _write_project_marker(project_path)
        return (
            Project(prompt_lines=lines),
            project_path,
            original_json,
            sources,
            retained,
        )

    def test_valid_apply_deletes_sources_only_and_preserves_project_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, project_path, original_json, sources, retained = (
                self._fixture(root, names=("a", "b"))
            )
            before_project = copy.deepcopy(project)
            before_serialized = json.dumps(
                project,
                default=lambda value: value.__dict__,
                sort_keys=True,
            )
            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )

            result = delete_verified_project_asset_source_duplicates(
                project,
                str(project_path),
                preview,
            )

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["deleted_count"], 2)
            self.assertEqual(
                result["deleted_bytes"],
                sum(len(f"image-{name}".encode()) for name in ("a", "b")),
            )
            self.assertTrue(all(not path.exists() for path in sources))
            self.assertTrue(all(path.exists() for path in retained))
            self.assertEqual(project, before_project)
            self.assertEqual(
                json.dumps(
                    project,
                    default=lambda value: value.__dict__,
                    sort_keys=True,
                ),
                before_serialized,
            )
            self.assertEqual(project_path.read_bytes(), original_json)
            self.assertTrue(result["project_json_unchanged"])
            self.assertTrue(result["candidates_unchanged"])

    def test_scan_and_apply_each_run_one_full_preview_without_second_hash_pass(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, project_path, _, sources, retained = self._fixture(
                root,
                names=("a", "b"),
            )
            io_module = __import__("core.io", fromlist=["core.io"])
            real_preview = (
                io_module.preview_verified_project_asset_duplicate_cleanup
            )
            real_snapshot = io_module._cleanup_file_snapshot
            with mock.patch(
                "core.io.preview_verified_project_asset_duplicate_cleanup",
                wraps=real_preview,
            ) as preview_mock:
                stored_preview = (
                    io_module.preview_verified_project_asset_duplicate_cleanup(
                        project,
                        str(project_path),
                    )
                )
                self.assertEqual(preview_mock.call_count, 1)

                preview_mock.reset_mock()
                with mock.patch(
                    "core.io._cleanup_file_snapshot",
                    wraps=real_snapshot,
                ) as snapshot_mock:
                    result = (
                        delete_verified_project_asset_source_duplicates(
                            project,
                            str(project_path),
                            stored_preview,
                        )
                    )

                self.assertEqual(preview_mock.call_count, 1)
                self.assertEqual(
                    snapshot_mock.call_count,
                    len(sources) + len(retained),
                )
                self.assertEqual(result["status"], "success")

    def test_each_stale_change_blocks_all_deletion(self):
        mutations = {
            "source_missing": lambda source, retained, project: (
                source.unlink()
            ),
            "source_content": lambda source, retained, project: (
                source.write_bytes(b"changed")
            ),
            "retained_content": lambda source, retained, project: (
                retained.write_bytes(b"changed")
            ),
            "retained_deleted": lambda source, retained, project: (
                retained.unlink()
            ),
            "project_reference_added": lambda source, retained, project: (
                project.project_metadata.update(
                    {"new_reference": "generated/a.png"}
                )
            ),
            "retained_reference_removed": (
                lambda source, retained, project: (
                    project.prompt_lines[0].generated_candidates.clear(),
                    project.prompt_lines[0].gallery_variants.clear(),
                    project.prompt_lines[0].lineage_info.clear(),
                )
            ),
        }
        for name, mutation in mutations.items():
            with self.subTest(mutation=name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    project, project_path, _, sources, retained = (
                        self._fixture(root, names=("a", "b"))
                    )
                    preview = (
                        preview_verified_project_asset_duplicate_cleanup(
                            project,
                            str(project_path),
                        )
                    )
                    mutation(sources[0], retained[0], project)

                    with self.assertRaises(
                        ProjectAssetsPreviewStaleError
                    ):
                        delete_verified_project_asset_source_duplicates(
                            project,
                            str(project_path),
                            preview,
                        )

                    if name != "source_missing":
                        self.assertTrue(sources[0].exists())
                    self.assertTrue(sources[1].exists())

    def test_mtime_only_change_blocks_all_deletion(self):
        for target_name in ("source", "retained"):
            with self.subTest(target=target_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    project, project_path, _, sources, retained = (
                        self._fixture(root, names=("a", "b"))
                    )
                    preview = (
                        preview_verified_project_asset_duplicate_cleanup(
                            project,
                            str(project_path),
                        )
                    )
                    target = (
                        sources[0]
                        if target_name == "source"
                        else retained[0]
                    )
                    target_stat = target.stat()
                    os.utime(
                        target,
                        ns=(
                            target_stat.st_atime_ns,
                            target_stat.st_mtime_ns + 10_000_000,
                        ),
                    )

                    with self.assertRaises(
                        ProjectAssetsPreviewStaleError
                    ):
                        delete_verified_project_asset_source_duplicates(
                            project,
                            str(project_path),
                            preview,
                        )

                    self.assertTrue(all(path.exists() for path in sources))

    def test_new_earlier_eligible_item_changes_order_and_blocks_deletion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, project_path, _, sources, _ = self._fixture(
                root,
                names=("b", "c"),
            )
            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )
            new_source = root / "generated" / "a.png"
            new_retained = root / "candidates" / "a-retained.png"
            new_source.write_bytes(b"image-a")
            new_retained.write_bytes(b"image-a")
            project.prompt_lines.append(
                _line(
                    line_id="line-a",
                    index=2,
                    generated_candidates=[
                        {"path": "candidates/a-retained.png"}
                    ],
                )
            )

            with self.assertRaises(ProjectAssetsPreviewStaleError):
                delete_verified_project_asset_source_duplicates(
                    project,
                    str(project_path),
                    preview,
                )

            self.assertTrue(new_source.exists())
            self.assertTrue(all(path.exists() for path in sources))

    def test_project_path_and_eligible_order_changes_are_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, project_path, _, sources, _ = self._fixture(
                root,
                names=("a", "b"),
            )
            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )
            other_project_path = root / "other.json"
            _write_project_marker(other_project_path)

            with self.assertRaises(ProjectAssetsPreviewStaleError):
                delete_verified_project_asset_source_duplicates(
                    project,
                    str(other_project_path),
                    preview,
                )
            self.assertTrue(all(path.exists() for path in sources))

            tampered = copy.deepcopy(preview)
            tampered["eligible_items"].reverse()
            tampered["signature"] = "tampered-order"
            with self.assertRaises(ProjectAssetsPreviewStaleError):
                delete_verified_project_asset_source_duplicates(
                    project,
                    str(project_path),
                    tampered,
                )
            self.assertTrue(all(path.exists() for path in sources))

    def test_partial_remove_failure_stops_and_reports_deleted_and_remaining(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, project_path, original_json, sources, retained = (
                self._fixture(root, names=("a", "b", "c"))
            )
            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )
            real_remove = os.remove
            remove_count = 0

            def fail_second_remove(path):
                nonlocal remove_count
                remove_count += 1
                if remove_count == 2:
                    raise OSError("simulated second delete failure")
                return real_remove(path)

            with mock.patch(
                "core.io.os.remove",
                side_effect=fail_second_remove,
            ):
                result = delete_verified_project_asset_source_duplicates(
                    project,
                    str(project_path),
                    preview,
                )

            self.assertEqual(result["status"], "partial_failure")
            self.assertEqual(result["deleted_files"], ["generated/a.png"])
            self.assertEqual(result["failed_file"], "generated/b.png")
            self.assertEqual(
                result["remaining_eligible_files"],
                ["generated/b.png", "generated/c.png"],
            )
            self.assertFalse(sources[0].exists())
            self.assertTrue(sources[1].exists())
            self.assertTrue(sources[2].exists())
            self.assertTrue(all(path.exists() for path in retained))
            self.assertEqual(project_path.read_bytes(), original_json)

    def test_source_change_after_full_validation_blocks_first_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, project_path, original_json, sources, retained = (
                self._fixture(root, names=("a", "b"))
            )
            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )
            io_module = __import__("core.io", fromlist=["core.io"])
            real_metadata_check = (
                io_module._cleanup_file_metadata_matches
            )
            metadata_check_count = 0
            initial_check_count = len(sources) + len(retained)

            def mutate_source_after_full_validation(*args, **kwargs):
                nonlocal metadata_check_count
                matches = real_metadata_check(*args, **kwargs)
                metadata_check_count += 1
                if metadata_check_count == initial_check_count:
                    sources[0].write_bytes(b"replacement-source")
                return matches

            with mock.patch(
                "core.io._cleanup_file_metadata_matches",
                side_effect=mutate_source_after_full_validation,
            ):
                result = delete_verified_project_asset_source_duplicates(
                    project,
                    str(project_path),
                    preview,
                )

            self.assertEqual(result["status"], "stale")
            self.assertEqual(result["deleted_count"], 0)
            self.assertEqual(result["failed_file"], "generated/a.png")
            self.assertEqual(
                result["remaining_eligible_files"],
                ["generated/a.png", "generated/b.png"],
            )
            self.assertTrue(all(path.exists() for path in sources))
            self.assertTrue(all(path.exists() for path in retained))
            self.assertEqual(project_path.read_bytes(), original_json)

    def test_retained_change_after_first_delete_stops_before_second_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, project_path, original_json, sources, retained = (
                self._fixture(root, names=("a", "b", "c"))
            )
            preview = preview_verified_project_asset_duplicate_cleanup(
                project,
                str(project_path),
            )
            real_remove = os.remove
            remove_count = 0

            def remove_first_then_mutate_retained(path):
                nonlocal remove_count
                real_remove(path)
                remove_count += 1
                if remove_count == 1:
                    retained[1].write_bytes(b"replacement-retained")

            with mock.patch(
                "core.io.os.remove",
                side_effect=remove_first_then_mutate_retained,
            ):
                result = delete_verified_project_asset_source_duplicates(
                    project,
                    str(project_path),
                    preview,
                )

            self.assertEqual(result["status"], "partial_stale")
            self.assertEqual(result["deleted_files"], ["generated/a.png"])
            self.assertEqual(result["failed_file"], "generated/b.png")
            self.assertEqual(
                result["remaining_eligible_files"],
                ["generated/b.png", "generated/c.png"],
            )
            self.assertFalse(sources[0].exists())
            self.assertTrue(sources[1].exists())
            self.assertTrue(sources[2].exists())
            self.assertTrue(all(path.exists() for path in retained))
            self.assertEqual(project_path.read_bytes(), original_json)


if __name__ == "__main__":
    unittest.main()
