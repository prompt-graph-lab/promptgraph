import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.project_root_import import (
    apply_project_root_import,
    build_project_root_import_preview,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _line(image_path=""):
    return {
        "id": "line-1",
        "original_file_name": "001.png",
        "original_index": 0,
        "current_index": 0,
        "original_text": "prompt keeps old root text",
        "current_text": "prompt keeps old root text",
        "tokens": ["prompt"],
        "image_path": image_path,
        "future_line_field": {"keep": True},
    }


class ProjectRootImportApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "old" / "OldProject"
        self.root = self.base / "projects"
        self.source.mkdir(parents=True)
        self.image = self.source / "images" / "001.png"
        self.image.parent.mkdir()
        self.image.write_bytes(b"image-bytes")
        self.primary = self.source / "project.json"
        _write_json(
            self.primary,
            {
                "source_directory": str(self.source),
                "prompt_lines": [_line(str(self.image))],
                "nodes": {},
                "edges": [],
                "future_top": {"keep": "yes"},
            },
        )

    def tearDown(self):
        self.temp.cleanup()

    def _preview(self):
        return build_project_root_import_preview(
            str(self.primary),
            str(self.root),
            "OldProject",
        )

    def test_success_copies_without_mutating_source_and_commits_atomically(self):
        preview = self._preview()
        self.assertTrue(preview["valid"], preview["blockers"])
        source_project_bytes = self.primary.read_bytes()
        source_image_bytes = self.image.read_bytes()

        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            retry_delays=(0.0,),
        )

        self.assertTrue(result["success"], result)
        destination = self.root / "OldProject"
        imported_project = destination / "project.json"
        self.assertTrue(imported_project.is_file())
        self.assertEqual(source_project_bytes, self.primary.read_bytes())
        self.assertEqual(source_image_bytes, self.image.read_bytes())
        self.assertEqual(source_image_bytes, (destination / "images" / "001.png").read_bytes())
        data = json.loads(imported_project.read_text(encoding="utf-8"))
        self.assertEqual("images/001.png", data["prompt_lines"][0]["image_path"])
        self.assertEqual(str(destination), data["source_directory"])
        self.assertEqual({"keep": "yes"}, data["future_top"])
        self.assertIn("old root text", data["prompt_lines"][0]["current_text"])
        self.assertFalse(any(path.name.startswith(".promptgraph-import-") for path in self.root.iterdir()))

    def test_stale_source_change_blocks_before_destination_commit(self):
        preview = self._preview()
        self.image.write_bytes(b"changed")
        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            retry_delays=(0.0,),
        )
        self.assertFalse(result["success"])
        self.assertTrue(result["stale_preview"])
        self.assertFalse((self.root / "OldProject").exists())

    def test_fresh_preview_failure_is_reported_without_mutation(self):
        preview = self._preview()
        with patch(
            "core.project_root_import.build_project_root_import_preview",
            side_effect=OSError("source became unreadable"),
        ):
            result = apply_project_root_import(
                preview,
                expected_signature=preview["signature_digest"],
                retry_delays=(0.0,),
            )
        self.assertFalse(result["success"])
        self.assertTrue(result["stale_preview"])
        self.assertIn("source became unreadable", result["error"])
        self.assertFalse(self.root.exists())

    def test_source_project_digest_change_blocks_even_with_restored_stat(self):
        preview = self._preview()
        source_stat = self.primary.stat()
        payload = self.primary.read_bytes()
        replacement = payload.replace(b'"yes"', b'"no!"')
        self.assertEqual(len(payload), len(replacement))
        self.primary.write_bytes(replacement)
        os.utime(
            self.primary,
            ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
        )
        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            retry_delays=(0.0,),
        )
        self.assertFalse(result["success"])
        self.assertTrue(result["stale_preview"])
        self.assertFalse((self.root / "OldProject").exists())

    def test_copy_failure_cleans_staging_and_preserves_source(self):
        preview = self._preview()
        source_bytes = {path: path.read_bytes() for path in (self.primary, self.image)}
        calls = []

        def fail_second_copy(source, destination):
            calls.append(source)
            if len(calls) == 2:
                raise OSError("copy failed")
            from shutil import copy2

            return copy2(source, destination)

        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            copy_file=fail_second_copy,
            retry_delays=(0.0,),
        )
        self.assertFalse(result["success"])
        self.assertIn("copy failed", result["error"])
        self.assertFalse((self.root / "OldProject").exists())
        self.assertFalse(any(path.name.startswith(".promptgraph-import-") for path in self.root.iterdir()))
        for path, payload in source_bytes.items():
            self.assertEqual(payload, path.read_bytes())

    def test_copy_size_mismatch_cleans_staging(self):
        preview = self._preview()

        def truncate_copy(_source, destination):
            Path(destination).write_bytes(b"x")

        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            copy_file=truncate_copy,
            retry_delays=(0.0,),
        )
        self.assertFalse(result["success"])
        self.assertIn("size mismatch", result["error"])
        self.assertFalse((self.root / "OldProject").exists())
        self.assertFalse(any(path.name.startswith(".promptgraph-import-") for path in self.root.iterdir()))

    def test_source_entry_added_during_copy_blocks_final_commit(self):
        preview = self._preview()
        copied = []

        def add_source_entry_after_first_copy(source, destination):
            from shutil import copy2

            copy2(source, destination)
            copied.append(source)
            if len(copied) == 1:
                (self.source / "appeared-during-copy.bin").write_bytes(b"new")

        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            copy_file=add_source_entry_after_first_copy,
            retry_delays=(0.0,),
        )
        self.assertFalse(result["success"])
        self.assertTrue(result["stale_preview"])
        self.assertFalse((self.root / "OldProject").exists())
        self.assertFalse(any(path.name.startswith(".promptgraph-import-") for path in self.root.iterdir()))

    def test_staged_validation_failure_rolls_back(self):
        preview = self._preview()
        with patch(
            "core.project_root_import.validate_staged_project_import",
            return_value={"valid": False, "blockers": ["manifest validation failed"]},
        ):
            result = apply_project_root_import(
                preview,
                expected_signature=preview["signature_digest"],
                retry_delays=(0.0,),
            )
        self.assertFalse(result["success"])
        self.assertIn("manifest validation failed", result["error"])
        self.assertFalse((self.root / "OldProject").exists())
        self.assertFalse(any(path.name.startswith(".promptgraph-import-") for path in self.root.iterdir()))

    def test_destination_race_does_not_overwrite_or_merge(self):
        preview = self._preview()
        destination = self.root / "OldProject"
        destination.mkdir(parents=True)
        marker = destination / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            retry_delays=(0.0,),
        )
        self.assertFalse(result["success"])
        self.assertTrue(result["stale_preview"] or result["conflict"])
        self.assertEqual("keep", marker.read_text(encoding="utf-8"))

    def test_windows_retry_contract_retries_transient_rename(self):
        preview = self._preview()
        attempts = []

        def retry_once(source, destination):
            attempts.append((source, destination))
            if len(attempts) == 1:
                error = PermissionError("sharing violation")
                error.winerror = 32
                raise error
            return os.rename(source, destination)

        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            rename=retry_once,
            sleep=lambda _delay: None,
            retry_delays=(0.0, 0.0),
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(2, result["commit_attempts"])
        self.assertTrue(result["commit_retry_performed"])

    def test_retry_exhaustion_cleans_staging(self):
        preview = self._preview()

        def always_locked(_source, _destination):
            error = PermissionError("locked")
            error.winerror = 32
            raise error

        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            rename=always_locked,
            sleep=lambda _delay: None,
            retry_delays=(0.0, 0.0),
        )
        self.assertFalse(result["success"])
        self.assertIn("lock exhausted", result["error"])
        self.assertFalse((self.root / "OldProject").exists())
        self.assertFalse(any(path.name.startswith(".promptgraph-import-") for path in self.root.iterdir()))


if __name__ == "__main__":
    unittest.main()
