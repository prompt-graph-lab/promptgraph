import json
import os
import tempfile
import unittest
from pathlib import Path

from core.project_discovery import (
    discover_project_root_projects,
    inspect_promptgraph_project_json,
    is_promptgraph_project_json_payload,
    normalize_project_discovery_path,
    path_is_within,
    validate_project_discovery_open_path,
)


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _project_payload(**extra) -> dict:
    return {"source_directory": "", "prompt_lines": [], **extra}


class ProjectDirectoryDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "projects"
        self.root.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _project(self, directory: str, file_name: str = "project.json", payload=None) -> Path:
        return _write_json(
            self.root / directory / file_name,
            _project_payload() if payload is None else payload,
        )

    def _fork(self, project: str, fork: str, *, manifest=None, images=True) -> Path:
        project_path = self._project(project)
        fork_dir = self.root / project / "forks" / fork
        fork_path = _write_json(fork_dir / "project.json", _project_payload())
        if images:
            (fork_dir / "images").mkdir()
        if manifest is not False:
            payload = {
                "manifest_version": 1,
                "operation": "lightweight_fork_final_sequence",
                "fork_name": fork,
                "source_project_name": project_path.name,
                "source_project_path": str(project_path),
                "selected_route_count": 3,
                "selected_route_ids": ["route-1", "route-2", "route-3"],
                "materialized_line_count": 12,
                "created_at": "2026-08-01T00:00:00Z",
            }
            if isinstance(manifest, dict):
                payload.update(manifest)
            _write_json(fork_dir / "manifest.json", payload)
        return fork_path

    def test_minimum_project_payload_matches_existing_loader_contract(self):
        self.assertTrue(is_promptgraph_project_json_payload({"prompt_lines": []}))
        self.assertTrue(
            is_promptgraph_project_json_payload(
                {"prompt_lines": [], "nodes": {}, "edges": []}
            )
        )
        for rejected in (
            None,
            [],
            {},
            {"prompt_lines": {}},
            {"workflow": {"1": {"class_type": "KSampler"}}},
        ):
            self.assertFalse(is_promptgraph_project_json_payload(rejected))

    def test_inspection_accepts_empty_and_older_minimal_projects(self):
        empty_path = self._project("empty")
        older_path = self._project(
            "older",
            payload={"prompt_lines": [], "nodes": {}, "edges": []},
        )
        self.assertTrue(inspect_promptgraph_project_json(str(empty_path))["valid"])
        self.assertTrue(inspect_promptgraph_project_json(str(older_path))["valid"])

    def test_missing_root_and_regular_file_fail_closed(self):
        missing = discover_project_root_projects(self.root / "missing")
        self.assertFalse(missing["valid"])
        self.assertEqual("missing", missing["status"])
        self.assertEqual([], missing["projects"])

        regular_file = self.root / "not-a-root"
        regular_file.write_text("file", encoding="utf-8")
        file_result = discover_project_root_projects(regular_file)
        self.assertFalse(file_result["valid"])
        self.assertEqual("not_directory", file_result["status"])

    def test_normal_custom_and_multiple_project_jsons_are_discovered(self):
        first = self._project("ProjectA")
        second = self._project("ProjectA", "illustration-set.json")
        custom = self._project("ProjectB", "custom-name.json")

        result = discover_project_root_projects(self.root)

        self.assertTrue(result["valid"])
        self.assertEqual(3, result["counts"]["normal_projects"])
        self.assertEqual(
            {str(path.resolve()) for path in (first, second, custom)},
            {entry["project_path"] for entry in result["projects"]},
        )
        self.assertTrue(
            any(entry["display_label"] == "Project · ProjectB · custom-name.json" for entry in result["projects"])
        )

    def test_non_project_workflow_settings_manifests_and_malformed_json_are_rejected(self):
        project_dir = self.root / "mixed"
        _write_json(project_dir / "workflow.json", {"1": {"class_type": "KSampler"}})
        _write_json(project_dir / ".editor_settings.json", {"last_project": "x"})
        _write_json(project_dir / "manifest.json", {"manifest_version": 1})
        _write_json(project_dir / "export_manifest.json", {"files": []})
        _write_json(project_dir / "partial.tmp.json", _project_payload())
        (project_dir / "broken.json").write_text("{broken", encoding="utf-8")

        result = discover_project_root_projects(self.root)

        self.assertEqual([], result["projects"])
        reasons = "\n".join(entry["reason"] for entry in result["rejected"])
        self.assertIn("prompt_lines", reasons)
        self.assertIn("reserved non-Project", reasons)
        self.assertIn("temporary JSON", reasons)
        self.assertIn("unreadable", reasons)

    def test_only_direct_project_and_known_fork_depths_are_scanned(self):
        self._project("alpha")
        self._project("alpha/nested/deeper")
        self._project("alpha/generated/not-a-project")
        self._project("alpha/candidates/not-a-project")
        self._project("alpha/exports/not-a-project")

        result = discover_project_root_projects(self.root)

        self.assertEqual(1, result["counts"]["normal_projects"])
        self.assertEqual(0, result["counts"]["fork_projects"])
        self.assertEqual(
            os.path.join("alpha", "project.json"),
            result["projects"][0]["relative_path"],
        )

    def test_valid_fork_uses_manifest_metadata(self):
        fork_path = self._fork("ProjectA", "beach-variation")

        result = discover_project_root_projects(self.root)

        fork = next(entry for entry in result["projects"] if entry["kind"] == "fork")
        self.assertEqual(str(fork_path.resolve()), fork["project_path"])
        self.assertTrue(fork["manifest_available"])
        self.assertEqual(3, fork["fork_metadata"]["selected_route_count"])
        self.assertEqual(0, fork["fork_metadata"]["materialized_route_count"])
        self.assertEqual(12, fork["fork_metadata"]["materialized_line_count"])
        self.assertIn("updated 2026-08-01", fork["display_label"])

    def test_missing_malformed_unsupported_and_mismatched_manifests_keep_forks_openable(self):
        missing_path = self._fork("alpha", "missing", manifest=False)
        malformed_path = self._fork("beta", "malformed", manifest=False)
        (malformed_path.parent / "manifest.json").write_text("{broken", encoding="utf-8")
        unsupported_path = self._fork(
            "gamma",
            "unsupported",
            manifest={"manifest_version": 99},
        )
        mismatch_path = self._fork(
            "delta",
            "mismatch",
            manifest={"source_project_path": str(self.root / "elsewhere" / "project.json")},
        )

        result = discover_project_root_projects(self.root)

        forks = {entry["project_path"]: entry for entry in result["projects"] if entry["kind"] == "fork"}
        for path in (missing_path, malformed_path, unsupported_path, mismatch_path):
            self.assertIn(str(path.resolve()), forks)
            self.assertFalse(forks[str(path.resolve())]["manifest_available"])
        self.assertEqual(4, result["counts"]["fork_projects"])
        self.assertGreaterEqual(len(result["diagnostics"]), 4)

    def test_missing_fork_images_directory_is_diagnostic_not_a_load_blocker(self):
        fork_path = self._fork("alpha", "no-images", images=False)

        result = discover_project_root_projects(self.root)

        self.assertIn(
            str(fork_path.resolve()),
            [entry["project_path"] for entry in result["projects"]],
        )
        self.assertTrue(any("images directory is missing" in item for item in result["diagnostics"]))

    def test_duplicate_directory_and_project_paths_are_deduplicated(self):
        project_path = self._project("alpha")

        def duplicate_list(path):
            names = os.listdir(path)
            if normalize_project_discovery_path(path) == normalize_project_discovery_path(self.root):
                return names + ["alpha"]
            return names

        result = discover_project_root_projects(self.root, list_directory=duplicate_list)

        self.assertEqual([str(project_path.resolve())], [entry["project_path"] for entry in result["projects"]])
        self.assertTrue(any("duplicate resolved Project directory" in entry["reason"] for entry in result["rejected"]))

    def test_order_is_stable_and_natural_with_forks_after_parent_projects(self):
        self._project("Project10")
        self._fork("Project2", "fork10")
        self._fork("Project2", "fork2")
        self._project("Project1")

        first = discover_project_root_projects(self.root)
        second = discover_project_root_projects(self.root)

        first_labels = [entry["display_label"] for entry in first["projects"]]
        self.assertEqual(first_labels, [entry["display_label"] for entry in second["projects"]])
        self.assertEqual("Project · Project1 · project.json", first_labels[0])
        self.assertEqual("Project · Project2 · project.json", first_labels[1])
        self.assertIn("Project2 / fork2", first_labels[2])
        self.assertIn("Project2 / fork10", first_labels[3])
        self.assertEqual("Project · Project10 · project.json", first_labels[4])

    def test_unreadable_root_json_and_stat_failures_do_not_escape(self):
        project_path = self._project("alpha")
        unreadable_root = discover_project_root_projects(
            self.root,
            list_directory=lambda _path: (_ for _ in ()).throw(PermissionError("denied")),
        )
        self.assertFalse(unreadable_root["valid"])
        self.assertEqual("unreadable", unreadable_root["status"])

        unreadable_json = discover_project_root_projects(
            self.root,
            json_loader=lambda _path: (_ for _ in ()).throw(PermissionError("denied")),
        )
        self.assertEqual([], unreadable_json["projects"])

        stat_failure = discover_project_root_projects(
            self.root,
            path_mtime=lambda _path: (_ for _ in ()).throw(OSError("stat failed")),
        )
        self.assertEqual(str(project_path.resolve()), stat_failure["projects"][0]["project_path"])
        self.assertTrue(any("modified time is unavailable" in item for item in stat_failure["diagnostics"]))

    def test_path_helpers_reject_invalid_and_outside_paths(self):
        inside = self._project("alpha")
        outside = Path(self.temp_dir.name) / "outside" / "project.json"
        _write_json(outside, _project_payload())

        self.assertEqual("", normalize_project_discovery_path("bad\x00path"))
        self.assertTrue(path_is_within(inside, self.root))
        self.assertFalse(path_is_within(outside, self.root))
        self.assertFalse(path_is_within("Z:\\other-drive\\project.json", self.root))

        normalized, error = validate_project_discovery_open_path(inside, self.root)
        self.assertEqual(str(inside.resolve()), normalized)
        self.assertEqual("", error)
        self.assertTrue(validate_project_discovery_open_path(outside, self.root)[1])
        inside.unlink()
        self.assertIn("missing", validate_project_discovery_open_path(inside, self.root)[1])

    def test_symlink_project_and_outside_directory_are_rejected_when_supported(self):
        target = self._project("target")
        link_project_dir = self.root / "linked-file"
        link_project_dir.mkdir()
        link_project = link_project_dir / "project.json"
        outside_dir = Path(self.temp_dir.name) / "outside-project"
        _write_json(outside_dir / "project.json", _project_payload())
        outside_link = self.root / "outside-link"
        try:
            os.symlink(target, link_project)
            os.symlink(outside_dir, outside_link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation is unavailable: {exc}")

        result = discover_project_root_projects(self.root)

        paths = [entry["project_path"] for entry in result["projects"]]
        self.assertNotIn(str(link_project.resolve()), paths)
        self.assertNotIn(str((outside_dir / "project.json").resolve()), paths)
        reasons = "\n".join(entry["reason"] for entry in result["rejected"])
        self.assertIn("symlinks are not allowed", reasons)
        self.assertIn("escapes Project root", reasons)


if __name__ == "__main__":
    unittest.main()
