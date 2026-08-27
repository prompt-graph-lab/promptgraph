import json
import os
import tempfile
import unittest
from pathlib import Path

from core.project_root_import import (
    FORK_MANIFEST_PATH_REGISTRY,
    PROJECT_JSON_PATH_REGISTRY,
    rebase_fork_manifest_paths,
    rebase_project_json_paths,
    sanitize_project_import_name,
)


def _line(**updates):
    data = {
        "id": "line-1",
        "original_file_name": "001.png",
        "original_index": 0,
        "current_index": 0,
        "original_text": "old root must remain in prompt",
        "current_text": "old root must remain in prompt",
        "tokens": ["test"],
        "negative_prompt": "old root must remain in negative",
    }
    data.update(updates)
    return data


class ProjectRootImportPathRebaseTests(unittest.TestCase):
    def test_sanitize_blocks_windows_reserved_and_nested_names(self):
        self.assertEqual("Old_Project", sanitize_project_import_name("Old/Project"))
        self.assertEqual("CON_", sanitize_project_import_name("CON"))
        self.assertEqual("ImportedProject", sanitize_project_import_name(" .. "))

    def test_explicit_registry_covers_current_runtime_path_fields(self):
        for expected in (
            "source_directory",
            "prompt_lines[].image_path",
            "prompt_lines[].generated_candidates[].path",
            "prompt_lines[].gallery_variants[].path",
            "prompt_lines[].source_generation_info.source_image_path",
            "route_snapshots[].items[].reference_image_path",
        ):
            self.assertIn(expected, PROJECT_JSON_PATH_REGISTRY)
        for expected in (
            "source_project_path",
            "destination_project_path",
            "destination_manifest_path",
            "append_history[].source_project_path",
        ):
            self.assertIn(expected, FORK_MANIFEST_PATH_REGISTRY)

    def test_project_rebase_changes_only_known_paths_and_preserves_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "old"
            destination_root = Path(temp_dir) / "projects" / "OldProject"
            source_root.mkdir()
            (source_root / "images").mkdir()
            (source_root / "candidates").mkdir()
            (source_root / "images" / "001.png").write_bytes(b"image")
            (source_root / "candidates" / "a.png").write_bytes(b"candidate")
            external = Path(temp_dir) / "external.png"
            external.write_bytes(b"external")
            source_project = source_root / "project.json"
            destination_project = destination_root / "project.json"
            internal_image = str(source_root / "images" / "001.png")
            internal_candidate = str(source_root / "candidates" / "a.png")
            raw = {
                "source_directory": str(source_root),
                "future_top_level": {"keep": True, "mystery_path": internal_image},
                "project_metadata": {
                    "image_imports": [
                        {
                            "source_directory": str(source_root / "images"),
                            "images": [{"path": internal_image, "future": "keep"}],
                        }
                    ],
                    "future_metadata": {"path": internal_image},
                },
                "prompt_lines": [
                    _line(
                        image_path=internal_image,
                        generated_image_path=internal_candidate,
                        selected_candidate_path=internal_candidate,
                        generated_candidates=[
                            {
                                "path": internal_candidate,
                                "previous_main_image_path": internal_image,
                                "workflow_path": internal_image,
                            }
                        ],
                        gallery_variants=[
                            {
                                "id": "variant-1",
                                "path": internal_candidate,
                                "lineage_info": {
                                    "candidate_image_path": internal_candidate,
                                    "parent_image_path": internal_image,
                                },
                                "source_generation_info": {
                                    "source_image_path": internal_candidate,
                                    "source_prompt": "keep",
                                },
                                "candidate_metadata": {"path": internal_image},
                            }
                        ],
                        lineage_info={
                            "candidate_image_path": internal_candidate,
                            "parent_image_path": internal_image,
                            "candidate_image_swap": {
                                "new_main_image_path": internal_candidate,
                                "previous_main_image_path": internal_image,
                            },
                        },
                        source_generation_info={"source_image_path": str(external)},
                        future_line_field={"path": internal_image},
                    )
                ],
                "route_snapshots": [
                    {
                        "items": [
                            {
                                "selected_candidate_path": internal_candidate,
                                "generated_image_path": internal_candidate,
                                "reference_image_path": internal_image,
                                "prompt_text": str(source_root),
                            }
                        ]
                    }
                ],
            }

            rewritten, analysis = rebase_project_json_paths(
                raw,
                source_root=str(source_root),
                destination_root=str(destination_root),
                source_project_path=str(source_project),
                destination_project_path=str(destination_project),
            )

            line = rewritten["prompt_lines"][0]
            self.assertEqual("images/001.png", line["image_path"])
            self.assertEqual("candidates/a.png", line["selected_candidate_path"])
            self.assertEqual(str(destination_root), rewritten["source_directory"])
            self.assertEqual(
                str(destination_root / "images"),
                rewritten["project_metadata"]["image_imports"][0]["source_directory"],
            )
            self.assertEqual(str(external), line["source_generation_info"]["source_image_path"])
            self.assertEqual(internal_image, raw["prompt_lines"][0]["image_path"])
            self.assertEqual(
                internal_image,
                rewritten["future_top_level"]["mystery_path"],
            )
            self.assertEqual(
                internal_image,
                line["future_line_field"]["path"],
            )
            self.assertEqual(
                internal_image,
                line["generated_candidates"][0]["workflow_path"],
            )
            self.assertEqual(
                internal_image,
                line["gallery_variants"][0]["candidate_metadata"]["path"],
            )
            self.assertIn("old root must remain", line["current_text"])
            self.assertIn("old root must remain", line["negative_prompt"])
            self.assertGreaterEqual(len(analysis["rewrites"]), 12)
            self.assertEqual(1, len(analysis["external_paths"]))
            self.assertFalse(analysis["blockers"])

    def test_relative_paths_are_kept_and_missing_main_path_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "old"
            destination_root = Path(temp_dir) / "projects" / "Old"
            source_root.mkdir()
            raw = {"prompt_lines": [_line(image_path="images/missing.png")]}
            rewritten, analysis = rebase_project_json_paths(
                raw,
                source_root=str(source_root),
                destination_root=str(destination_root),
                source_project_path=str(source_root / "project.json"),
                destination_project_path=str(destination_root / "project.json"),
            )
            self.assertEqual("images/missing.png", rewritten["prompt_lines"][0]["image_path"])
            self.assertTrue(any("Missing Project-local reference" in item for item in analysis["blockers"]))

    def test_fork_manifest_rewrites_only_supported_path_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "old"
            destination_root = Path(temp_dir) / "projects" / "Old"
            fork_dir = source_root / "forks" / "beach"
            fork_dir.mkdir(parents=True)
            source_project = source_root / "project.json"
            fork_project = fork_dir / "project.json"
            manifest_path = fork_dir / "manifest.json"
            for path in (source_project, fork_project, manifest_path):
                path.write_text("{}", encoding="utf-8")
            image = fork_dir / "images" / "001.png"
            image.parent.mkdir()
            image.write_bytes(b"image")
            manifest = {
                "manifest_version": 1,
                "operation": "lightweight_fork_final_sequence",
                "source_project_path": str(source_project),
                "destination_project_path": str(fork_project),
                "destination_manifest_path": str(manifest_path),
                "materialized_entries": [{"source_image_path": str(image), "copied_image_path": "images/001.png"}],
                "append_history": [
                    {
                        "source_project_path": str(source_project),
                        "materialized_entries": [{"source_image_path": str(image)}],
                    }
                ],
                "future": {"path": str(source_project)},
            }
            rewritten, analysis = rebase_fork_manifest_paths(
                manifest,
                source_root=str(source_root),
                destination_root=str(destination_root),
                source_manifest_path=str(manifest_path),
                destination_manifest_path=str(destination_root / "forks" / "beach" / "manifest.json"),
            )
            self.assertEqual(str(destination_root / "project.json"), rewritten["source_project_path"])
            self.assertEqual(
                str(destination_root / "forks" / "beach" / "project.json"),
                rewritten["destination_project_path"],
            )
            self.assertEqual(
                str(destination_root / "forks" / "beach" / "images" / "001.png"),
                rewritten["materialized_entries"][0]["source_image_path"],
            )
            self.assertEqual(str(source_project), rewritten["future"]["path"])
            self.assertFalse(analysis["blockers"])


if __name__ == "__main__":
    unittest.main()
