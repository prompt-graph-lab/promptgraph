import json
import os
import tempfile
import unittest
from unittest import mock

from core.lightweight_fork_discovery import (
    discover_lightweight_forks_for_source,
    resolve_cached_lightweight_fork_discovery,
)


class LightweightForkDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = self.temp_dir.name
        self.source_path = os.path.join(self.root, "source.json")
        with open(self.source_path, "w", encoding="utf-8") as handle:
            json.dump({"prompt_lines": []}, handle)
        self.forks_dir = os.path.join(self.root, "forks")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _make_fork(self, name, *, manifest=None, project=True, images=True):
        fork_dir = os.path.join(self.forks_dir, name)
        os.makedirs(fork_dir, exist_ok=True)
        default_manifest = {
            "manifest_version": 1,
            "operation": "lightweight_fork_final_sequence",
            "fork_name": name,
            "source_project_path": self.source_path,
            "created_at": "2026-07-15T10:00:00+00:00",
            "selected_route_count": 2,
            "selected_route_ids": ["route_a", "route_b"],
            "materialized_line_count": 18,
            "skipped_line_count": 1,
            "materialized_entries": [{"route_id": "route_a", "source_line_id": "line_a"}],
            "structure_entries": [{"kind": "route_separator", "source_line_id": "route_b"}],
            "append_history": [],
        }
        if manifest is not None:
            default_manifest.update(manifest)
        with open(os.path.join(fork_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump(default_manifest, handle)
        if project:
            with open(os.path.join(fork_dir, "project.json"), "w", encoding="utf-8") as handle:
                json.dump({"prompt_lines": []}, handle)
        if images:
            os.makedirs(os.path.join(fork_dir, "images"), exist_ok=True)
        return fork_dir

    def test_missing_forks_directory_is_valid_empty_snapshot(self):
        snapshot = discover_lightweight_forks_for_source(self.source_path)
        self.assertTrue(snapshot["valid"])
        self.assertEqual([], snapshot["candidates"])
        self.assertEqual(os.path.realpath(self.forks_dir).lower(), snapshot["search_root"].lower())

    def test_valid_fork_summary_uses_manifest_without_loading_project_or_images(self):
        fork_dir = self._make_fork(
            "milku_final",
            manifest={
                "updated_at": "2026-07-17T03:00:00+00:00",
                "append_history": [{"id": 1}, {"id": 2}],
                "unknown_future_field": {"keep": True},
            },
        )
        loaded_paths = []

        def load_manifest(path):
            loaded_paths.append(path)
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)

        before = sorted(os.listdir(fork_dir))
        snapshot = discover_lightweight_forks_for_source(
            self.source_path,
            json_loader=load_manifest,
        )
        candidate = snapshot["candidates"][0]
        self.assertEqual([os.path.join(fork_dir, "manifest.json").lower()], [path.lower() for path in loaded_paths])
        self.assertEqual("milku_final", candidate["fork_name"])
        self.assertEqual(2, candidate["selected_route_count"])
        self.assertEqual(2, candidate["materialized_route_count"])
        self.assertEqual(18, candidate["materialized_line_count"])
        self.assertEqual(2, candidate["append_history_count"])
        self.assertIn("2 Scenes / 18 Illustrations / updated 2026-07-17", candidate["display_label"])
        self.assertEqual(before, sorted(os.listdir(fork_dir)))

    def test_route_label_counts_materialized_routes_not_selection_history(self):
        self._make_fork(
            "partially_materialized",
            manifest={
                "selected_route_count": 3,
                "selected_route_ids": ["route_a", "route_b", "route_missing"],
                "materialized_entries": [
                    {"route_id": "route_a", "source_line_id": "line_a"},
                    {"route_id": "route_b", "source_line_id": "line_b"},
                ],
                "structure_entries": [
                    {"kind": "route_separator", "source_line_id": "route_a"},
                    {"kind": "route_separator", "source_line_id": "route_b"},
                ],
            },
        )
        candidate = discover_lightweight_forks_for_source(self.source_path)["candidates"][0]
        self.assertEqual(3, candidate["selected_route_count"])
        self.assertEqual(2, candidate["materialized_route_count"])
        self.assertIn("2 Scenes / 18 Illustrations", candidate["display_label"])
        self.assertNotIn("3 Routes", candidate["display_label"])

    def test_materialized_route_count_includes_append_history_evidence(self):
        self._make_fork(
            "appended",
            manifest={
                "selected_route_count": 3,
                "selected_route_ids": ["route_a", "route_b", "route_c"],
                "append_history": [
                    {
                        "selected_route_ids": ["route_c"],
                        "materialized_entries": [{"route_id": "route_c", "source_line_id": "line_c"}],
                        "structure_entries": [{"kind": "route_separator", "source_line_id": "route_c"}],
                    }
                ],
            },
        )
        candidate = discover_lightweight_forks_for_source(self.source_path)["candidates"][0]
        self.assertEqual(3, candidate["materialized_route_count"])

    def test_invalid_candidates_are_rejected_without_hiding_valid_fork(self):
        self._make_fork("valid")
        self._make_fork("wrong_source", manifest={"source_project_path": os.path.join(self.root, "other.json")})
        self._make_fork("wrong_operation", manifest={"operation": "other"})
        self._make_fork("wrong_version", manifest={"manifest_version": 99})
        self._make_fork("missing_project", project=False)
        self._make_fork("missing_images", images=False)
        malformed_dir = os.path.join(self.forks_dir, "malformed")
        os.makedirs(malformed_dir, exist_ok=True)
        with open(os.path.join(malformed_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            handle.write("{")
        with open(os.path.join(malformed_dir, "project.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        os.makedirs(os.path.join(malformed_dir, "images"), exist_ok=True)

        snapshot = discover_lightweight_forks_for_source(self.source_path)
        self.assertEqual(["valid"], [candidate["fork_name"] for candidate in snapshot["candidates"]])
        reasons = "\n".join(entry["reason"] for entry in snapshot["rejected"])
        for expected in (
            "does not match",
            "unsupported manifest operation",
            "unsupported manifest version",
            "project.json is missing",
            "images directory is missing",
            "manifest.json is unreadable",
        ):
            self.assertIn(expected, reasons)

    def test_non_object_manifest_is_rejected(self):
        fork_dir = self._make_fork("list_manifest")
        with open(os.path.join(fork_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump([], handle)
        snapshot = discover_lightweight_forks_for_source(self.source_path)
        self.assertEqual([], snapshot["candidates"])
        self.assertIn("not an object", snapshot["rejected"][0]["reason"])

    def test_sort_prefers_updated_then_created_then_manifest_mtime(self):
        updated = self._make_fork(
            "updated",
            manifest={"updated_at": "2026-07-19T00:00:00+00:00", "created_at": "2026-07-01T00:00:00+00:00"},
        )
        self._make_fork("created", manifest={"created_at": "2026-07-18T00:00:00+00:00"})
        mtime = self._make_fork("mtime", manifest={"created_at": "invalid"})
        os.utime(os.path.join(mtime, "manifest.json"), (1781654400, 1781654400))  # 2026-06-17 UTC
        snapshot = discover_lightweight_forks_for_source(self.source_path)
        self.assertEqual(["updated", "created", "mtime"], [item["fork_name"] for item in snapshot["candidates"]])
        self.assertEqual("updated", os.path.basename(updated))

    def test_equal_dates_have_stable_name_order_and_empty_name_falls_back_to_directory(self):
        self._make_fork("zeta", manifest={"fork_name": "", "updated_at": "2026-07-17T00:00:00+00:00"})
        self._make_fork("alpha", manifest={"updated_at": "2026-07-17T00:00:00+00:00"})
        snapshot = discover_lightweight_forks_for_source(self.source_path)
        self.assertEqual(["alpha", "zeta"], [item["fork_name"] for item in snapshot["candidates"]])

    def test_normalized_source_path_matches_and_current_open_is_marked(self):
        fork_dir = self._make_fork(
            "normalized",
            manifest={"source_project_path": os.path.join(self.root, ".", "source.json")},
        )
        project_path = os.path.join(fork_dir, "project.json")
        snapshot = discover_lightweight_forks_for_source(
            os.path.join(self.root, ".", "source.json"),
            current_open_project_path=project_path,
        )
        self.assertTrue(snapshot["candidates"][0]["source_match"])
        self.assertTrue(snapshot["candidates"][0]["currently_open"])

    def test_duplicate_directory_entry_is_rejected_once(self):
        self._make_fork("duplicate")
        snapshot = discover_lightweight_forks_for_source(
            self.source_path,
            list_directory=lambda _path: ["duplicate", "duplicate"],
        )
        self.assertEqual(1, len(snapshot["candidates"]))
        self.assertIn("duplicate Fork directory", snapshot["rejected"][0]["reason"])

    def test_path_escape_from_injected_child_name_is_rejected(self):
        os.makedirs(self.forks_dir, exist_ok=True)
        snapshot = discover_lightweight_forks_for_source(
            self.source_path,
            list_directory=lambda _path: ["..\\escape"],
        )
        self.assertEqual([], snapshot["candidates"])
        self.assertIn("not a direct child", snapshot["rejected"][0]["reason"])

    def test_symlink_or_realpath_escape_is_rejected(self):
        os.makedirs(self.forks_dir, exist_ok=True)
        outside = os.path.join(self.root, "outside")
        os.makedirs(outside, exist_ok=True)
        original = os.path.realpath

        def escaping_realpath(path):
            if os.path.basename(str(path)) == "escaped":
                return outside
            return original(path)

        with mock.patch("core.lightweight_fork_append.os.path.realpath", side_effect=escaping_realpath):
            snapshot = discover_lightweight_forks_for_source(
                self.source_path,
                list_directory=lambda _path: ["escaped"],
            )
        self.assertEqual([], snapshot["candidates"])
        self.assertIn("escapes Fork discovery root", snapshot["rejected"][0]["reason"])

    def test_custom_search_root_outside_source_directory_fails_before_scan(self):
        outside_root = os.path.join(os.path.dirname(self.root), "outside-forks")
        list_directory = mock.Mock(return_value=[])
        json_loader = mock.Mock(return_value={})
        snapshot = discover_lightweight_forks_for_source(
            self.source_path,
            search_root=outside_root,
            list_directory=list_directory,
            json_loader=json_loader,
        )
        self.assertFalse(snapshot["valid"])
        self.assertIn("escapes the source Project directory", snapshot["reason"])
        list_directory.assert_not_called()
        json_loader.assert_not_called()

    def test_forks_root_realpath_escape_fails_before_scan(self):
        outside_root = os.path.join(os.path.dirname(self.root), "linked-forks-target")
        original = os.path.realpath
        expected_forks = os.path.normcase(os.path.abspath(self.forks_dir))
        list_directory = mock.Mock(return_value=[])
        json_loader = mock.Mock(return_value={})

        def linked_root_realpath(path):
            if os.path.normcase(os.path.abspath(str(path))) == expected_forks:
                return outside_root
            return original(path)

        with mock.patch("core.lightweight_fork_append.os.path.realpath", side_effect=linked_root_realpath):
            snapshot = discover_lightweight_forks_for_source(
                self.source_path,
                list_directory=list_directory,
                json_loader=json_loader,
            )
        self.assertFalse(snapshot["valid"])
        self.assertIn("escapes the source Project directory", snapshot["reason"])
        list_directory.assert_not_called()
        json_loader.assert_not_called()

    def test_cache_reuses_snapshot_and_refresh_or_source_change_rescans(self):
        calls = []

        def discoverer(source_project_path, **kwargs):
            calls.append((source_project_path, kwargs["search_root"]))
            return {"valid": True, "candidates": [{"call": len(calls)}]}

        snapshot, cache, hit = resolve_cached_lightweight_fork_discovery(
            None,
            source_project_path=self.source_path,
            search_root=self.forks_dir,
            refresh_generation=0,
            discoverer=discoverer,
        )
        self.assertFalse(hit)
        same_snapshot, same_cache, hit = resolve_cached_lightweight_fork_discovery(
            cache,
            source_project_path=self.source_path,
            search_root=self.forks_dir,
            refresh_generation=0,
            discoverer=discoverer,
        )
        self.assertTrue(hit)
        self.assertIs(snapshot, same_snapshot)
        self.assertIs(cache, same_cache)

        _, refreshed_cache, hit = resolve_cached_lightweight_fork_discovery(
            cache,
            source_project_path=self.source_path,
            search_root=self.forks_dir,
            refresh_generation=1,
            discoverer=discoverer,
        )
        self.assertFalse(hit)
        other_source = os.path.join(self.root, "other.json")
        _, _, hit = resolve_cached_lightweight_fork_discovery(
            refreshed_cache,
            source_project_path=other_source,
            search_root=self.forks_dir,
            refresh_generation=1,
            discoverer=discoverer,
        )
        self.assertFalse(hit)
        self.assertEqual(3, len(calls))


if __name__ == "__main__":
    unittest.main()
