import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from core import settings as settings_module
from core.settings import get_recent_projects, load_settings, remember_project, save_settings


class LightweightForkRecentProjectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        with open(app_path, encoding="utf-8") as handle:
            cls.app_source = handle.read()
        register_start = cls.app_source.index("def _remember_materialized_fork_project")
        register_end = cls.app_source.index("def reset_lightweight_fork_session_state", register_start)
        cls.register_source = cls.app_source[register_start:register_end]
        create_start = cls.app_source.index("def render_lightweight_fork_preview_section")
        create_end = cls.app_source.index("def render_gallery_operations_launcher", create_start)
        cls.create_source = cls.app_source[create_start:create_end]
        append_start = cls.app_source.index("def _render_lightweight_fork_append_section")
        append_end = cls.app_source.index("def render_lightweight_fork_preview_section", append_start)
        cls.append_source = cls.app_source[append_start:append_end]

    def test_registering_fork_in_recent_does_not_replace_last_source_project(self):
        settings = {"last_project": "C:/projects/source.json", "recent_projects": []}
        remember_project(settings, "C:/projects/forks/fork_a/project.json", update_last_project=False)
        self.assertEqual(os.path.abspath("C:/projects/source.json"), os.path.abspath(settings["last_project"]))
        self.assertEqual(
            os.path.abspath("C:/projects/forks/fork_a/project.json"),
            get_recent_projects(settings)[0]["path"],
        )

    def test_duplicate_fork_is_promoted_without_duplicate_entry(self):
        settings = {"last_project": "source.json", "recent_projects": []}
        remember_project(settings, "fork_a/project.json", update_last_project=False)
        remember_project(settings, "other/project.json", update_last_project=False)
        remember_project(settings, "fork_a/project.json", update_last_project=False)
        paths = [item["path"] for item in get_recent_projects(settings)]
        self.assertEqual(os.path.abspath("fork_a/project.json"), paths[0])
        self.assertEqual(1, sum(path == os.path.abspath("fork_a/project.json") for path in paths))

    def test_fork_registration_reuses_recent_project_limit(self):
        settings = {"last_project": "source.json", "recent_projects": []}
        for index in range(settings_module.MAX_RECENT_PROJECTS + 3):
            remember_project(settings, f"fork_{index}/project.json", update_last_project=False)
        self.assertEqual(settings_module.MAX_RECENT_PROJECTS, len(get_recent_projects(settings)))
        self.assertEqual(os.path.abspath("fork_12/project.json"), get_recent_projects(settings)[0]["path"])

    def test_recent_fork_persists_through_settings_reload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = os.path.join(temp_dir, "settings.json")
            settings = {"last_project": "source.json", "recent_projects": []}
            remember_project(settings, os.path.join(temp_dir, "fork", "project.json"), update_last_project=False)
            with mock.patch.object(settings_module, "SETTINGS_FILE", settings_path):
                save_settings(settings)
                loaded = load_settings()
            self.assertEqual(get_recent_projects(settings), get_recent_projects(loaded))

    def test_registration_wiring_checks_file_and_preserves_current_project_state(self):
        self.assertIn("os.path.isfile(normalized_path)", self.register_source)
        self.assertIn("remember_project(", self.register_source)
        self.assertIn("update_last_project=False", self.register_source)
        self.assertIn("save_settings", self.register_source)
        for forbidden in ("push_history", "autosave", "current_project_path =", "load_project_json_into_session"):
            self.assertNotIn(forbidden, self.register_source)

    def test_create_registers_only_after_success_and_keeps_explicit_open_action(self):
        success_index = self.create_source.index('if result.get("success"):')
        register_index = self.create_source.index("_remember_materialized_fork_project", success_index)
        invalidate_index = self.create_source.index("_invalidate_lightweight_fork_discovery_cache", register_index)
        self.assertLess(success_index, register_index)
        self.assertLess(register_index, invalidate_index)
        self.assertIn("作成した派生Projectを開く", self.app_source)
        self.assertNotIn("push_history", self.create_source)
        self.assertNotIn("save_current_project_if_possible", self.create_source)

    def test_append_success_promotes_recent_and_failure_path_has_no_registration(self):
        success_index = self.append_source.index('if result.get("success"):')
        register_index = self.append_source.index("_remember_materialized_fork_project", success_index)
        invalidate_index = self.append_source.index("_invalidate_lightweight_fork_discovery_cache", register_index)
        self.assertLess(success_index, register_index)
        self.assertLess(register_index, invalidate_index)
        before_success = self.append_source[:success_index]
        self.assertNotIn("_remember_materialized_fork_project", before_success)
        self.assertNotIn("push_history", self.append_source)
        self.assertNotIn("save_current_project_if_possible", self.append_source)

    def test_recent_registration_does_not_mutate_source_settings_input_copy_unexpectedly(self):
        settings = {
            "last_project": os.path.abspath("source.json"),
            "recent_projects": [{"name": "source", "path": os.path.abspath("source.json"), "last_opened": "old"}],
            "unknown": {"keep": True},
        }
        before_unknown = copy.deepcopy(settings["unknown"])
        remember_project(settings, "fork/project.json", update_last_project=False)
        self.assertEqual(before_unknown, settings["unknown"])
        self.assertEqual(os.path.abspath("source.json"), settings["last_project"])


if __name__ == "__main__":
    unittest.main()
