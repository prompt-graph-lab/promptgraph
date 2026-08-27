import os
import unittest

from core.project_discovery import (
    build_project_discovery_cache_key,
    resolve_cached_project_discovery,
)


class ProjectDirectoryDiscoveryCacheTests(unittest.TestCase):
    def _discoverer(self, calls):
        def discover(root):
            normalized_root = os.path.realpath(os.path.abspath(root))
            calls.append(normalized_root)
            return {
                "valid": True,
                "status": "ready",
                "root": normalized_root,
                "projects": [
                    {
                        "kind": "project",
                        "project_path": os.path.join(normalized_root, "alpha", "project.json"),
                        "currently_open": False,
                    }
                ],
                "rejected": [],
                "diagnostics": [],
                "counts": {"normal_projects": 1, "fork_projects": 0, "rejected": 0},
            }

        return discover

    def test_initial_discovery_runs_once_and_ordinary_reruns_hit_cache(self):
        calls = []
        discoverer = self._discoverer(calls)
        root = os.path.abspath("projects")

        first, cache_entry, first_hit = resolve_cached_project_discovery(
            None,
            root=root,
            refresh_generation=0,
            discoverer=discoverer,
        )
        second, same_entry, second_hit = resolve_cached_project_discovery(
            cache_entry,
            root=root,
            refresh_generation=0,
            discoverer=discoverer,
        )

        self.assertFalse(first_hit)
        self.assertTrue(second_hit)
        self.assertEqual(1, len(calls))
        self.assertEqual(first["projects"], second["projects"])
        self.assertIs(cache_entry, same_entry)

    def test_refresh_generation_causes_exactly_one_new_discovery(self):
        calls = []
        discoverer = self._discoverer(calls)
        root = os.path.abspath("projects")
        _snapshot, cache_entry, _hit = resolve_cached_project_discovery(
            None,
            root=root,
            refresh_generation=0,
            discoverer=discoverer,
        )

        _refreshed, refreshed_entry, refreshed_hit = resolve_cached_project_discovery(
            cache_entry,
            root=root,
            refresh_generation=1,
            discoverer=discoverer,
        )
        _again, _same_entry, again_hit = resolve_cached_project_discovery(
            refreshed_entry,
            root=root,
            refresh_generation=1,
            discoverer=discoverer,
        )

        self.assertFalse(refreshed_hit)
        self.assertTrue(again_hit)
        self.assertEqual(2, len(calls))

    def test_root_change_invalidates_without_reusing_old_snapshot(self):
        calls = []
        discoverer = self._discoverer(calls)
        root_a = os.path.abspath("projects-a")
        root_b = os.path.abspath("projects-b")
        _snapshot, cache_entry, _hit = resolve_cached_project_discovery(
            None,
            root=root_a,
            refresh_generation=0,
            discoverer=discoverer,
        )

        changed, _changed_entry, changed_hit = resolve_cached_project_discovery(
            cache_entry,
            root=root_b,
            refresh_generation=0,
            discoverer=discoverer,
        )

        self.assertFalse(changed_hit)
        self.assertEqual(2, len(calls))
        self.assertEqual(os.path.realpath(root_b), changed["root"])

    def test_current_project_change_only_decorates_cached_snapshot(self):
        calls = []
        discoverer = self._discoverer(calls)
        root = os.path.abspath("projects")
        project_path = os.path.join(root, "alpha", "project.json")
        _snapshot, cache_entry, _hit = resolve_cached_project_discovery(
            None,
            root=root,
            refresh_generation=0,
            discoverer=discoverer,
        )

        current, _same_entry, cache_hit = resolve_cached_project_discovery(
            cache_entry,
            root=root,
            refresh_generation=0,
            current_open_project_path=project_path,
            discoverer=discoverer,
        )

        self.assertTrue(cache_hit)
        self.assertEqual(1, len(calls))
        self.assertTrue(current["projects"][0]["currently_open"])
        self.assertFalse(cache_entry["snapshot"]["projects"][0]["currently_open"])

    def test_cache_key_is_only_effective_root_and_refresh_generation(self):
        root = os.path.abspath("projects")
        self.assertEqual(
            (os.path.realpath(root), 4),
            build_project_discovery_cache_key(root, 4),
        )


if __name__ == "__main__":
    unittest.main()
