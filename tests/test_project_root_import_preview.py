import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.project_root_import import build_project_root_import_preview


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _project(lines=None, **updates):
    payload = {
        "source_directory": "",
        "prompt_lines": list(lines or []),
        "nodes": {},
        "edges": [],
        "unknown_top": {"keep": True},
    }
    payload.update(updates)
    return payload


class ProjectRootImportPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "old-projects" / "OldProject"
        self.root = self.base / "project-root"
        self.source.mkdir(parents=True)
        self.primary = self.source / "project.json"
        _write_json(self.primary, _project())

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_preview_is_mutation_free_and_reports_inventory(self):
        (self.source / "images").mkdir()
        (self.source / "images" / "001.png").write_bytes(b"12345")
        (self.source / "exports").mkdir()
        (self.source / "exports" / "kept.txt").write_text("keep", encoding="utf-8")
        (self.source / ".promptgraph_cache").mkdir()
        (self.source / ".promptgraph_cache" / "ignored.bin").write_bytes(b"ignore")
        (self.source / "Thumbs.db").write_bytes(b"ignore")
        source_bytes = self.primary.read_bytes()

        preview = build_project_root_import_preview(
            str(self.primary),
            str(self.root),
            "OldProject",
        )

        self.assertTrue(preview["valid"], preview["blockers"])
        self.assertEqual(str(self.root / "OldProject"), preview["destination_directory"])
        self.assertEqual(str(self.root / "OldProject" / "project.json"), preview["destination_project_path"])
        self.assertEqual(3, preview["counts"]["file_count"])
        self.assertEqual(2, preview["counts"]["ignored_count"])
        self.assertEqual(1, preview["counts"]["project_json_count"])
        self.assertGreater(preview["counts"]["total_bytes"], 5)
        self.assertTrue(preview["signature_digest"])
        self.assertEqual(source_bytes, self.primary.read_bytes())
        self.assertFalse(self.root.exists())
        self.assertFalse((self.root / "OldProject").exists())
        self.assertIn("exports/kept.txt", [item["relative_path"] for item in preview["source_inventory"]])

    def test_multiple_project_jsons_are_planned_and_arbitrary_json_is_untouched(self):
        _write_json(self.source / "alternate.json", _project())
        _write_json(self.source / "workflow.json", {"1": {"class_type": "KSampler"}})
        (self.source / "broken.json").write_text("{ invalid", encoding="utf-8")
        preview = build_project_root_import_preview(
            str(self.primary),
            str(self.root),
            "OldProject",
        )
        self.assertTrue(preview["valid"], preview["blockers"])
        self.assertEqual(2, preview["counts"]["project_json_count"])
        self.assertEqual(
            ["alternate.json", "project.json"],
            [plan["relative_path"] for plan in preview["project_json_plans"]],
        )
        self.assertGreaterEqual(preview["counts"]["auxiliary_json_warning_count"], 1)
        self.assertFalse(any(plan["relative_path"] == "workflow.json" for plan in preview["project_json_plans"]))

    def test_already_inside_root_is_blocked(self):
        root = self.base / "project-root"
        inside = root / "Inside"
        primary = inside / "project.json"
        _write_json(primary, _project())
        preview = build_project_root_import_preview(str(primary), str(root), "InsideCopy")
        self.assertFalse(preview["valid"])
        self.assertTrue(any("already inside" in item for item in preview["blockers"]))

    def test_destination_conflict_and_unsafe_name_are_blocked_without_suffixing(self):
        (self.root / "OldProject").mkdir(parents=True)
        conflict = build_project_root_import_preview(str(self.primary), str(self.root), "oldproject")
        self.assertFalse(conflict["valid"])
        self.assertTrue(any("already exists" in item for item in conflict["blockers"]))
        unsafe = build_project_root_import_preview(str(self.primary), str(self.root), "nested/name")
        self.assertFalse(unsafe["valid"])
        self.assertTrue(any("direct-child" in item for item in unsafe["blockers"]))

    def test_destination_root_inside_source_is_blocked(self):
        preview = build_project_root_import_preview(
            str(self.primary),
            str(self.source / "projects"),
            "OldProject",
        )
        self.assertFalse(preview["valid"])
        self.assertTrue(any("must not be inside" in item for item in preview["blockers"]))

    def test_missing_and_malformed_primary_are_blocked(self):
        missing = build_project_root_import_preview(
            str(self.source / "missing.json"),
            str(self.root),
            "OldProject",
        )
        self.assertFalse(missing["valid"])
        self.primary.write_text("{ invalid", encoding="utf-8")
        malformed = build_project_root_import_preview(
            str(self.primary),
            str(self.root),
            "OldProject",
        )
        self.assertFalse(malformed["valid"])
        self.assertTrue(any("unreadable" in item for item in malformed["blockers"]))

    def test_symlink_child_is_fail_closed_when_supported(self):
        target = self.base / "outside.bin"
        target.write_bytes(b"outside")
        link = self.source / "linked.bin"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable")
        preview = build_project_root_import_preview(str(self.primary), str(self.root), "OldProject")
        self.assertFalse(preview["valid"])
        self.assertTrue(any("Symlink or reparse" in item for item in preview["blockers"]))

    def test_ignored_cache_symlink_is_not_traversed(self):
        outside = self.base / "outside-cache"
        outside.mkdir()
        (outside / "secret.bin").write_bytes(b"outside")
        link = self.source / ".promptgraph_cache"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlink creation is unavailable")
        preview = build_project_root_import_preview(str(self.primary), str(self.root), "OldProject")
        self.assertTrue(preview["valid"], preview["blockers"])
        self.assertIn(
            ".promptgraph_cache",
            [item["relative_path"] for item in preview["ignored"]],
        )
        self.assertNotIn(
            ".promptgraph_cache/secret.bin",
            [item["relative_path"] for item in preview["source_inventory"]],
        )

    def test_graph_validation_failure_blocks_preview(self):
        with patch("core.project_root_import.build_graph", side_effect=ValueError("bad graph")):
            preview = build_project_root_import_preview(
                str(self.primary), str(self.root), "OldProject"
            )
        self.assertFalse(preview["valid"])
        self.assertTrue(any("graph validation failed" in item for item in preview["blockers"]))

    def test_directory_mtime_does_not_create_false_stale_signature(self):
        images = self.source / "images"
        images.mkdir()
        (images / "001.png").write_bytes(b"image")
        before = build_project_root_import_preview(str(self.primary), str(self.root), "OldProject")
        stat_result = images.stat()
        os.utime(images, ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 1_000_000))
        after = build_project_root_import_preview(str(self.primary), str(self.root), "OldProject")
        self.assertEqual(before["signature_digest"], after["signature_digest"])

    def test_inventory_and_examples_have_stable_natural_order(self):
        for name in ("10.png", "2.png", "1.png"):
            (self.source / name).write_bytes(name.encode("ascii"))
        preview = build_project_root_import_preview(str(self.primary), str(self.root), "OldProject")
        names = [
            item["relative_path"]
            for item in preview["source_inventory"]
            if item["relative_path"].endswith(".png")
        ]
        self.assertEqual(["1.png", "2.png", "10.png"], names)


if __name__ == "__main__":
    unittest.main()
