import json
import tempfile
import unittest
from pathlib import Path

from core.io import load_project_from_json
from core.lightweight_fork_append import (
    build_lightweight_fork_append_preview,
    load_existing_fork_snapshot,
)
from core.project_root_import import (
    apply_project_root_import,
    build_project_root_import_preview,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _line(line_id, line_type=None, image_path="", label=""):
    return {
        "id": line_id,
        "original_file_name": f"{line_id}.txt",
        "original_index": 0,
        "current_index": 0,
        "original_text": label or line_id,
        "current_text": label or line_id,
        "tokens": [line_id],
        "line_type": line_type,
        "separator_label": label if line_type == "separator" else None,
        "image_path": image_path or None,
    }


class ProjectRootImportForkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "old" / "OldProject"
        self.root = self.base / "projects"
        self.source.mkdir(parents=True)
        source_image = self.source / "images" / "001.png"
        source_image.parent.mkdir()
        source_image.write_bytes(b"source-image")
        self.primary = self.source / "project.json"
        _write_json(
            self.primary,
            {
                "source_directory": str(self.source),
                "prompt_lines": [
                    _line("route-1", line_type="separator", label="Route 1"),
                    _line("line-1", image_path="images/001.png", label="prompt"),
                ],
                "nodes": {},
                "edges": [],
            },
        )
        self.fork = self.source / "forks" / "beach"
        (self.fork / "images").mkdir(parents=True)
        _write_json(
            self.fork / "project.json",
            {
                "source_directory": "",
                "prompt_lines": [],
                "nodes": {},
                "edges": [],
                "future_fork_project_field": {"keep": True},
            },
        )
        self.manifest = {
            "manifest_version": 1,
            "operation": "lightweight_fork_final_sequence",
            "fork_name": "beach",
            "source_project_path": str(self.primary),
            "destination_project_path": str(self.fork / "project.json"),
            "destination_manifest_path": str(self.fork / "manifest.json"),
            "selected_route_ids": [],
            "selected_route_labels": [],
            "source_route_blocks": [],
            "materialized_entries": [],
            "structure_entries": [],
            "skipped_entries": [],
            "append_history": [
                {
                    "source_project_path": str(self.primary),
                    "selected_route_ids": [],
                    "materialized_entries": [],
                    "structure_entries": [],
                }
            ],
            "future_manifest_field": {"keep": True},
        }
        _write_json(self.fork / "manifest.json", self.manifest)

    def _add_alternate_project_and_fork(self, fork_name="alternate-fork"):
        alternate = self.source / "alternate.json"
        _write_json(
            alternate,
            {
                "source_directory": str(self.source),
                "prompt_lines": [
                    _line("route-alt", line_type="separator", label="Alternate Route"),
                    _line("line-alt", image_path="images/001.png", label="alternate prompt"),
                ],
                "nodes": {},
                "edges": [],
            },
        )
        fork = self.source / "forks" / fork_name
        (fork / "images").mkdir(parents=True)
        _write_json(
            fork / "project.json",
            {
                "source_directory": "",
                "prompt_lines": [],
                "nodes": {},
                "edges": [],
            },
        )
        manifest = json.loads(json.dumps(self.manifest))
        manifest.update(
            {
                "fork_name": fork_name,
                "source_project_path": str(alternate),
                "destination_project_path": str(fork / "project.json"),
                "destination_manifest_path": str(fork / "manifest.json"),
            }
        )
        manifest["append_history"][0]["source_project_path"] = str(alternate)
        _write_json(fork / "manifest.json", manifest)
        return alternate, fork

    def tearDown(self):
        self.temp.cleanup()

    def test_preview_counts_fork_and_plans_supported_manifest(self):
        preview = build_project_root_import_preview(
            str(self.primary), str(self.root), "OldProject"
        )
        self.assertTrue(preview["valid"], preview["blockers"])
        self.assertEqual(1, preview["counts"]["fork_count"])
        self.assertEqual(1, len(preview["fork_manifest_plans"]))
        self.assertGreaterEqual(preview["counts"]["fork_manifest_rewrite_count"], 4)
        plan = preview["fork_manifest_plans"][0]
        destination = self.root / "OldProject"
        self.assertTrue(plan["relation_valid"])
        self.assertEqual(str(self.primary), plan["source_manifest_source_project_path"])
        self.assertEqual(
            str(destination / "project.json"),
            plan["expected_destination_source_project_path"],
        )
        self.assertEqual(
            str(destination / "forks" / "beach" / "project.json"),
            plan["expected_destination_fork_project_path"],
        )
        self.assertEqual(
            str(destination / "forks" / "beach" / "manifest.json"),
            plan["expected_destination_manifest_path"],
        )
        signature_relation = preview["signature"]["fork_manifests"][0]
        self.assertEqual(str(destination / "project.json"), signature_relation[3])

    def test_imported_fork_manifest_preserves_same_source_append_contract(self):
        preview = build_project_root_import_preview(
            str(self.primary), str(self.root), "OldProject"
        )
        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            retry_delays=(0.0,),
        )
        self.assertTrue(result["success"], result)
        destination = self.root / "OldProject"
        imported_primary = destination / "project.json"
        imported_fork = destination / "forks" / "beach" / "project.json"
        imported_manifest_path = destination / "forks" / "beach" / "manifest.json"
        manifest = json.loads(imported_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(str(imported_primary), manifest["source_project_path"])
        self.assertEqual(str(imported_fork), manifest["destination_project_path"])
        self.assertEqual(str(imported_manifest_path), manifest["destination_manifest_path"])
        self.assertEqual(str(imported_primary), manifest["append_history"][0]["source_project_path"])
        self.assertEqual({"keep": True}, manifest["future_manifest_field"])
        self.assertTrue(load_existing_fork_snapshot(str(imported_fork))["valid"])

        source_project = load_project_from_json(str(imported_primary))
        append_preview = build_lightweight_fork_append_preview(
            source_project,
            source_project_path=str(imported_primary),
            selected_route_ids=["route-1"],
            existing_fork_project_path=str(imported_fork),
        )
        self.assertTrue(append_preview["source_match"])
        self.assertTrue(append_preview["valid"], append_preview["fatal_diagnostics"])
        self.assertEqual(["route-1"], append_preview["appendable_route_ids"])

    def test_sibling_project_fork_uses_its_own_source_mapping_and_remains_appendable(self):
        alternate, source_fork = self._add_alternate_project_and_fork()
        preview = build_project_root_import_preview(
            str(self.primary), str(self.root), "OldProject"
        )
        self.assertTrue(preview["valid"], preview["blockers"])
        self.assertEqual(2, preview["counts"]["project_json_count"])
        plans = {
            plan["relative_path"]: plan for plan in preview["fork_manifest_plans"]
        }
        alternate_plan = plans["forks/alternate-fork/manifest.json"]
        destination = self.root / "OldProject"
        imported_alternate = destination / "alternate.json"
        self.assertEqual(str(alternate), alternate_plan["source_manifest_source_project_path"])
        self.assertEqual(
            str(imported_alternate),
            alternate_plan["expected_destination_source_project_path"],
        )

        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            retry_delays=(0.0,),
        )
        self.assertTrue(result["success"], result)
        imported_fork = destination / "forks" / source_fork.name / "project.json"
        imported_manifest_path = imported_fork.parent / "manifest.json"
        imported_manifest = json.loads(imported_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(str(imported_alternate), imported_manifest["source_project_path"])
        self.assertTrue(load_existing_fork_snapshot(str(imported_fork))["valid"])

        alternate_project = load_project_from_json(str(imported_alternate))
        append_preview = build_lightweight_fork_append_preview(
            alternate_project,
            source_project_path=str(imported_alternate),
            selected_route_ids=["route-alt"],
            existing_fork_project_path=str(imported_fork),
        )
        self.assertTrue(append_preview["source_match"])
        self.assertTrue(append_preview["valid"], append_preview["fatal_diagnostics"])
        self.assertEqual(["route-alt"], append_preview["appendable_route_ids"])

    def test_multiple_forks_keep_distinct_source_project_mappings(self):
        self._add_alternate_project_and_fork()
        preview = build_project_root_import_preview(
            str(self.primary), str(self.root), "OldProject"
        )
        self.assertTrue(preview["valid"], preview["blockers"])
        plans = {
            plan["relative_path"]: plan for plan in preview["fork_manifest_plans"]
        }
        destination = self.root / "OldProject"
        self.assertEqual(2, preview["counts"]["fork_count"])
        self.assertEqual(2, len(plans))
        self.assertEqual(
            str(destination / "project.json"),
            plans["forks/beach/manifest.json"]["expected_destination_source_project_path"],
        )
        self.assertEqual(
            str(destination / "alternate.json"),
            plans["forks/alternate-fork/manifest.json"]["expected_destination_source_project_path"],
        )

    def test_supported_manifest_with_unmapped_source_is_preview_blocker(self):
        external = self.base / "other-project" / "project.json"
        _write_json(
            external,
            {
                "source_directory": str(external.parent),
                "prompt_lines": [],
                "nodes": {},
                "edges": [],
            },
        )
        manifest = json.loads(json.dumps(self.manifest))
        manifest["source_project_path"] = str(external)
        _write_json(self.fork / "manifest.json", manifest)

        preview = build_project_root_import_preview(
            str(self.primary), str(self.root), "OldProject"
        )
        self.assertFalse(preview["valid"])
        self.assertEqual([], preview["fork_manifest_plans"])
        self.assertTrue(
            any("not one of the valid Project JSONs" in item for item in preview["blockers"]),
            preview["blockers"],
        )

    def test_supported_manifest_with_stale_destination_relation_is_preview_blocker(self):
        stale_values = {
            "destination_project_path": self.source / "forks" / "other" / "project.json",
            "destination_manifest_path": self.source / "forks" / "other" / "manifest.json",
        }
        for field, stale_path in stale_values.items():
            with self.subTest(field=field):
                manifest = json.loads(json.dumps(self.manifest))
                manifest[field] = str(stale_path)
                _write_json(self.fork / "manifest.json", manifest)
                preview = build_project_root_import_preview(
                    str(self.primary), str(self.root), "OldProject"
                )
                self.assertFalse(preview["valid"])
                self.assertEqual([], preview["fork_manifest_plans"])
                self.assertTrue(
                    any("does not match its actual" in item for item in preview["blockers"]),
                    preview["blockers"],
                )

    def test_malformed_manifest_is_copied_unchanged_with_warning(self):
        malformed_bytes = b"{ invalid manifest"
        (self.fork / "manifest.json").write_bytes(malformed_bytes)
        preview = build_project_root_import_preview(
            str(self.primary), str(self.root), "OldProject"
        )
        self.assertTrue(preview["valid"], preview["blockers"])
        self.assertEqual(0, len(preview["fork_manifest_plans"]))
        self.assertTrue(any("copied unchanged" in item for item in preview["warnings"]))
        result = apply_project_root_import(
            preview,
            expected_signature=preview["signature_digest"],
            retry_delays=(0.0,),
        )
        self.assertTrue(result["success"], result)
        imported_manifest = self.root / "OldProject" / "forks" / "beach" / "manifest.json"
        self.assertEqual(malformed_bytes, imported_manifest.read_bytes())

    def test_unsupported_manifest_is_copied_unchanged(self):
        unsupported = dict(self.manifest)
        unsupported["manifest_version"] = 999
        _write_json(self.fork / "manifest.json", unsupported)
        preview = build_project_root_import_preview(
            str(self.primary), str(self.root), "OldProject"
        )
        self.assertTrue(preview["valid"], preview["blockers"])
        self.assertTrue(any("unsupported" in item for item in preview["warnings"]))
        self.assertEqual(0, preview["counts"]["fork_manifest_rewrite_count"])


if __name__ == "__main__":
    unittest.main()
