import copy
import os
from pathlib import Path
import tempfile
import unittest

from core.settings import get_last_project_path
from core.startup import STARTUP_AUTO_OPEN_ATTEMPTED_KEY, attempt_startup_project_auto_open


class StartupProjectAutoOpenTests(unittest.TestCase):
    def test_opens_existing_last_project_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = os.path.join(temp_dir, "project.json")
            Path(project_path).write_text("{}", encoding="utf-8")
            state = {"project": None, "settings": {"last_project": project_path}}
            opened_paths = []

            def open_project(path):
                opened_paths.append(path)
                state["project"] = object()
                state["current_project_path"] = path
                return True

            first = attempt_startup_project_auto_open(
                state,
                resolve_last_project_path=lambda: project_path,
                open_project=open_project,
            )
            second = attempt_startup_project_auto_open(
                state,
                resolve_last_project_path=lambda: project_path,
                open_project=open_project,
            )

        self.assertTrue(first["attempted"])
        self.assertTrue(first["opened"])
        self.assertEqual("opened", first["reason"])
        self.assertFalse(second["attempted"])
        self.assertEqual("already_attempted", second["reason"])
        self.assertEqual([project_path], opened_paths)

    def test_existing_session_project_prevents_auto_open(self):
        existing_project = object()
        state = {"project": existing_project}
        resolver_calls = []

        result = attempt_startup_project_auto_open(
            state,
            resolve_last_project_path=lambda: resolver_calls.append(True),
            open_project=lambda _path: self.fail("open_project must not be called"),
        )

        self.assertEqual("project_already_loaded", result["reason"])
        self.assertIs(existing_project, state["project"])
        self.assertEqual([], resolver_calls)
        self.assertTrue(state[STARTUP_AUTO_OPEN_ATTEMPTED_KEY])

    def test_empty_last_project_does_not_open(self):
        state = {"project": None}
        result = attempt_startup_project_auto_open(
            state,
            resolve_last_project_path=lambda: "",
            open_project=lambda _path: self.fail("open_project must not be called"),
        )

        self.assertEqual("last_project_not_configured", result["reason"])
        self.assertEqual("", result["error"])

    def test_missing_last_project_fails_open_without_retry(self):
        state = {"project": None, "settings": {"last_project": "missing.json"}}
        settings_before = copy.deepcopy(state["settings"])
        open_calls = []

        first = attempt_startup_project_auto_open(
            state,
            resolve_last_project_path=lambda: "missing.json",
            path_is_file=lambda _path: False,
            open_project=lambda path: open_calls.append(path),
        )
        second = attempt_startup_project_auto_open(
            state,
            resolve_last_project_path=lambda: "missing.json",
            path_is_file=lambda _path: True,
            open_project=lambda path: open_calls.append(path),
        )

        self.assertEqual("last_project_file_not_found", first["reason"])
        self.assertIn("missing.json", first["error"])
        self.assertEqual("already_attempted", second["reason"])
        self.assertEqual([], open_calls)
        self.assertIsNone(state["project"])
        self.assertEqual(settings_before, state["settings"])

    def test_invalid_project_is_caught_and_manual_open_remains_possible(self):
        state = {"project": None}

        def fail_to_open(_path):
            raise ValueError("invalid project JSON")

        result = attempt_startup_project_auto_open(
            state,
            resolve_last_project_path=lambda: "broken.json",
            path_is_file=lambda _path: True,
            open_project=fail_to_open,
        )

        self.assertEqual("last_project_open_failed", result["reason"])
        self.assertIn("invalid project JSON", result["error"])
        self.assertIsNone(state["project"])
        self.assertTrue(state[STARTUP_AUTO_OPEN_ATTEMPTED_KEY])

    def test_malformed_last_project_setting_is_caught(self):
        state = {"project": None}
        result = attempt_startup_project_auto_open(
            state,
            resolve_last_project_path=lambda: {"not": "a path"},
            open_project=lambda _path: self.fail("open_project must not be called"),
        )

        self.assertEqual("invalid_last_project_path", result["reason"])
        self.assertTrue(result["error"])

    def test_settings_path_normalization_rejects_malformed_values(self):
        self.assertEqual("", get_last_project_path({"last_project": {"not": "a path"}}))
        self.assertEqual("", get_last_project_path({"last_project": 123}))


class StartupProjectAutoOpenUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    def test_startup_auto_open_runs_after_page_config_before_sidebar(self):
        page_config = self.app_source.index("st.set_page_config(")
        startup_call = self.app_source.index("auto_open_last_project_on_startup()", page_config)
        sidebar = self.app_source.index("st.sidebar.title(", startup_call)

        self.assertLess(page_config, startup_call)
        self.assertLess(startup_call, sidebar)

    def test_session_does_not_claim_last_path_before_project_load(self):
        self.assertIn('st.session_state.current_project_path = ""', self.app_source)

    def test_last_project_button_is_removed_but_manual_open_is_preserved(self):
        self.assertNotIn("最後のプロジェクトを開く", self.app_source)
        self.assertNotIn('key="open_last_project"', self.app_source)
        self.assertIn("**最近のプロジェクト**", self.app_source)
        self.assertIn("**JSONファイルを直接指定して開く**", self.app_source)
        self.assertIn('key="quick_save_project"', self.app_source)

    def test_startup_failure_warning_and_success_cleanup_are_wired(self):
        self.assertIn("startup_project_auto_open_error", self.app_source)
        self.assertIn("前回のProjectを自動で開けませんでした。", self.app_source)
        self.assertIn("if startup_auto_open_error and st.session_state.project is None:", self.app_source)
        loader_start = self.app_source.index("def load_project_json_into_session")
        loader_end = self.app_source.index("def _unique_project_dir", loader_start)
        self.assertIn(
            'st.session_state.pop("startup_project_auto_open_error", None)',
            self.app_source[loader_start:loader_end],
        )


if __name__ == "__main__":
    unittest.main()
