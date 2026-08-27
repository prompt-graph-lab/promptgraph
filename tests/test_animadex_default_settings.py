import ast
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import core.settings as settings_module
from core.settings import (
    get_animadex_local_path,
    load_settings,
    normalize_animadex_local_path,
    save_settings,
)


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class AnimaDexSettingsHelperTests(unittest.TestCase):
    def test_old_settings_file_loads_with_empty_default_and_preserves_unknown_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = os.path.join(temp_dir, "settings.json")
            Path(settings_path).write_text(
                json.dumps(
                    {
                        "unknown_setting": {"keep": True},
                        "projects_root_directory": "existing-root",
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(settings_module, "SETTINGS_FILE", settings_path):
                loaded = load_settings()

        self.assertEqual("", loaded["animadex_local_path"])
        self.assertEqual({"keep": True}, loaded["unknown_setting"])
        self.assertEqual("existing-root", loaded["projects_root_directory"])

    def test_blank_malformed_and_invalid_types_normalize_to_empty(self):
        for value in ("", "   ", "bad\x00path", "bad\npath", 123, {}, None):
            with self.subTest(value=value):
                self.assertEqual("", normalize_animadex_local_path(value))
        self.assertEqual("", get_animadex_local_path(None))
        self.assertEqual("", get_animadex_local_path({"animadex_local_path": 123}))

    def test_relative_absolute_pathlike_and_nonexistent_paths_normalize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            existing_file = os.path.join(temp_dir, "animadex.db")
            Path(existing_file).write_text("fixture", encoding="utf-8")
            existing_directory = os.path.join(temp_dir, "data")
            os.mkdir(existing_directory)
            missing_path = os.path.join(temp_dir, "later-mounted", "animadex.db")

            for value in (
                existing_file,
                existing_directory,
                missing_path,
                Path(existing_file),
            ):
                with self.subTest(value=value):
                    self.assertEqual(
                        os.path.abspath(os.fspath(value)),
                        normalize_animadex_local_path(value),
                    )

        self.assertEqual(
            os.path.abspath("relative-animadex.db"),
            normalize_animadex_local_path("relative-animadex.db"),
        )

    def test_whitespace_is_trimmed_and_home_is_expanded(self):
        with mock.patch.object(settings_module.os.path, "expanduser") as expanduser:
            expanduser.return_value = os.path.join("expanded", "animadex.db")
            normalized = normalize_animadex_local_path("  ~/animadex.db  ")

        expanduser.assert_called_once_with("~/animadex.db")
        self.assertEqual(
            os.path.abspath(os.path.join("expanded", "animadex.db")),
            normalized,
        )

    def test_windows_forbidden_characters_are_checked_after_drive_prefix(self):
        with mock.patch.object(settings_module.os, "name", "nt"), mock.patch.object(
            settings_module.os.path,
            "splitdrive",
            side_effect=lambda value: ("C:", value[2:]) if value.startswith("C:") else ("", value),
        ):
            self.assertEqual(
                "",
                normalize_animadex_local_path(r"C:\valid-drive\bad:name.db"),
            )
            self.assertEqual(
                "",
                normalize_animadex_local_path(r"C:\valid-drive\bad?.db"),
            )
            self.assertEqual(
                os.path.abspath(r"C:\valid-drive\animadex.db"),
                normalize_animadex_local_path(r"C:\valid-drive\animadex.db"),
            )

    def test_save_settings_reports_success_and_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = os.path.join(temp_dir, "settings.json")
            with mock.patch.object(settings_module, "SETTINGS_FILE", settings_path):
                self.assertTrue(save_settings({"animadex_local_path": "fixture"}))
            self.assertTrue(os.path.isfile(settings_path))

        with mock.patch("builtins.open", side_effect=OSError("write failed")):
            self.assertFalse(save_settings({"animadex_local_path": "fixture"}))


class AnimaDexDefaultAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.app_source = (cls.root / "app.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.app_source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _function_source(self, name):
        return ast.get_source_segment(self.app_source, self.functions[name])

    def _load_functions(self, *names, namespace):
        module = ast.Module(
            body=[self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def _callback_namespace(self, session_state, saved):
        return self._load_functions(
            "initialize_animadex_browser_path",
            "sync_animadex_browser_path_draft",
            "_animadex_local_path_is_available",
            "save_animadex_local_path_default",
            "clear_animadex_local_path_default",
            namespace={
                "os": os,
                "st": types.SimpleNamespace(session_state=session_state),
                "get_animadex_local_path": get_animadex_local_path,
                "normalize_animadex_local_path": normalize_animadex_local_path,
                "save_settings": lambda settings: saved.append(dict(settings)) or True,
            },
        )

    def test_initialization_uses_saved_default_only_when_widget_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            saved_path = os.path.join(temp_dir, "saved", "animadex.db")
            session_state = _SessionState(
                settings={"animadex_local_path": f"  {saved_path}  "}
            )
            namespace = self._callback_namespace(session_state, [])

            self.assertEqual(
                os.path.abspath(saved_path),
                namespace["initialize_animadex_browser_path"](),
            )
            session_state.animadex_browser_path = "unsaved-session-path"
            namespace["sync_animadex_browser_path_draft"]()
            self.assertEqual(
                "unsaved-session-path",
                namespace["initialize_animadex_browser_path"](),
            )
            session_state.pop("animadex_browser_path")
            self.assertEqual(
                "unsaved-session-path",
                namespace["initialize_animadex_browser_path"](),
            )

    def test_initialization_uses_empty_value_when_no_default_is_saved(self):
        session_state = _SessionState(settings={"animadex_local_path": ""})
        namespace = self._callback_namespace(session_state, [])

        self.assertEqual("", namespace["initialize_animadex_browser_path"]())
        self.assertIn("animadex_browser_path", session_state)

    def test_save_default_normalizes_and_changes_only_editor_and_widget_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            current_path = os.path.join(temp_dir, "data")
            os.mkdir(current_path)
            project = object()
            global_library = {"Character": {"extension": {"keep": True}}}
            summary = {"character_records": [{"name": "keep"}]}
            session_state = _SessionState(
                settings={
                    "animadex_local_path": "",
                    "last_project": "project.json",
                    "unrelated": "keep",
                },
                animadex_browser_path=f"  {current_path}  ",
                animadex_discovery_summary=summary,
                project=project,
                history=["keep-history"],
                global_module_library=global_library,
            )
            saved = []
            namespace = self._callback_namespace(session_state, saved)

            self.assertTrue(namespace["save_animadex_local_path_default"]())

            normalized = os.path.abspath(current_path)
            self.assertEqual(1, len(saved))
            self.assertEqual(normalized, saved[0]["animadex_local_path"])
            self.assertEqual(normalized, session_state.animadex_browser_path)
            self.assertEqual(normalized, session_state.animadex_browser_path_draft)
            self.assertIs(project, session_state.project)
            self.assertEqual(["keep-history"], session_state.history)
            self.assertIs(summary, session_state.animadex_discovery_summary)
            self.assertIs(global_library, session_state.global_module_library)
            self.assertEqual("project.json", session_state.settings["last_project"])
            self.assertEqual("keep", session_state.settings["unrelated"])
            self.assertEqual(
                ("success", "AnimaDex local path saved as the default."),
                session_state.animadex_local_path_feedback,
            )

    def test_nonexistent_path_can_be_saved_and_is_reported_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = os.path.join(temp_dir, "later-mounted", "animadex.db")
            session_state = _SessionState(
                settings={"animadex_local_path": ""},
                animadex_browser_path=missing_path,
            )
            saved = []
            namespace = self._callback_namespace(session_state, saved)

            self.assertTrue(namespace["save_animadex_local_path_default"]())

            normalized = os.path.abspath(missing_path)
            self.assertEqual(normalized, saved[0]["animadex_local_path"])
            self.assertFalse(
                namespace["_animadex_local_path_is_available"](normalized)
            )
            self.assertEqual(
                (
                    "warning",
                    "Saved as default, but the path is not currently available.",
                ),
                session_state.animadex_local_path_feedback,
            )

    def test_invalid_path_keeps_existing_default_and_current_input(self):
        session_state = _SessionState(
            settings={"animadex_local_path": "existing-default"},
            animadex_browser_path="bad\x00path",
            animadex_discovery_summary={"keep": True},
        )
        saved = []
        namespace = self._callback_namespace(session_state, saved)

        self.assertFalse(namespace["save_animadex_local_path_default"]())

        self.assertEqual([], saved)
        self.assertEqual("existing-default", session_state.settings["animadex_local_path"])
        self.assertEqual("bad\x00path", session_state.animadex_browser_path)
        self.assertEqual({"keep": True}, session_state.animadex_discovery_summary)

    def test_save_failure_rolls_back_setting_and_does_not_claim_success(self):
        session_state = _SessionState(
            settings={"animadex_local_path": "existing-default"},
            animadex_browser_path="next-default",
        )
        namespace = self._callback_namespace(session_state, [])
        namespace["save_settings"] = lambda _settings: False

        self.assertFalse(namespace["save_animadex_local_path_default"]())

        self.assertEqual("existing-default", session_state.settings["animadex_local_path"])
        self.assertEqual("next-default", session_state.animadex_browser_path)
        self.assertEqual("error", session_state.animadex_local_path_feedback[0])

    def test_clear_default_preserves_current_path_and_nonsettings_state(self):
        project = object()
        summary = {"character_records": [{"name": "keep"}]}
        global_library = {"Character": {"body": "keep"}}
        session_state = _SessionState(
            settings={
                "animadex_local_path": os.path.abspath("saved-default"),
                "last_project": "project.json",
            },
            animadex_browser_path="current-session-path",
            animadex_discovery_summary=summary,
            project=project,
            history=["keep-history"],
            global_module_library=global_library,
        )
        saved = []
        namespace = self._callback_namespace(session_state, saved)

        self.assertTrue(namespace["clear_animadex_local_path_default"]())

        self.assertEqual(1, len(saved))
        self.assertEqual("", saved[0]["animadex_local_path"])
        self.assertEqual("current-session-path", session_state.animadex_browser_path)
        self.assertIs(summary, session_state.animadex_discovery_summary)
        self.assertIs(project, session_state.project)
        self.assertEqual(["keep-history"], session_state.history)
        self.assertIs(global_library, session_state.global_module_library)
        self.assertEqual("project.json", session_state.settings["last_project"])

    def test_clear_failure_restores_saved_default_and_keeps_current_path(self):
        session_state = _SessionState(
            settings={"animadex_local_path": "existing-default"},
            animadex_browser_path="current-session-path",
        )
        namespace = self._callback_namespace(session_state, [])
        namespace["save_settings"] = lambda _settings: False

        self.assertFalse(namespace["clear_animadex_local_path_default"]())

        self.assertEqual("existing-default", session_state.settings["animadex_local_path"])
        self.assertEqual("current-session-path", session_state.animadex_browser_path)
        self.assertEqual("error", session_state.animadex_local_path_feedback[0])

    def test_renderer_has_one_owner_and_default_controls_are_authoring_only(self):
        renderer = self._function_source("render_animadex_browser_section")
        owner = self._function_source("render_create_module_from_scratch_section")
        self.assertEqual(
            self.app_source.count("render_animadex_browser_section("),
            2,
        )
        self.assertEqual(owner.count("render_animadex_browser_section("), 1)
        self.assertIn("initialize_animadex_browser_path()", renderer)
        self.assertEqual(renderer.count('"animadex_save_local_path_default"'), 1)
        self.assertEqual(renderer.count('"animadex_clear_local_path_default"'), 1)
        self.assertNotIn("global_module_library_search_query", renderer)
        self.assertIn(
            "save_and_cache_global_module_library(",
            renderer,
        )
        self.assertIn(
            "project, global_library, global_module_names",
            owner,
        )
        self.assertNotIn("st.sidebar", renderer)
        self.assertNotIn("save_settings(", renderer)
        for workspace_name in (
            "render_project_management_workspace",
            "render_comfyui_settings_workspace",
        ):
            self.assertNotIn("animadex_", self._function_source(workspace_name))

    def test_limit_defaults_to_500_and_current_selection_drives_discovery_and_search(self):
        renderer = self._function_source("render_animadex_browser_section")
        self.assertIn("options=[100, 500, 1000]", renderer)
        self.assertIn("index=1", renderer)
        self.assertIn('key="animadex_browser_sample_limit"', renderer)
        self.assertIn("sample_limit=int(result_limit)", renderer)
        self.assertIn("limit=int(result_limit)", renderer)
        self.assertEqual(renderer.count("animadex_browser_sample_limit"), 1)

    def test_save_and_clear_callbacks_do_not_scan_or_mutate_project_data(self):
        for function_name in (
            "save_animadex_local_path_default",
            "clear_animadex_local_path_default",
        ):
            source = self._function_source(function_name)
            for forbidden in (
                "discover_animadex_local_data",
                "search_animadex_records",
                "save_project_to_json",
                "save_global_module_library",
                "history",
                "project",
            ):
                self.assertNotIn(forbidden, source)

    def test_project_and_workspace_resets_preserve_animadex_session_state(self):
        current_path = "current-session-path"
        summary = {"character_records": [{"name": "keep"}]}
        session_state = _SessionState(
            settings={"animadex_local_path": "saved-default"},
            animadex_browser_path=current_path,
            animadex_browser_path_draft=current_path,
            animadex_browser_sample_limit=100,
            animadex_discovery_summary=summary,
            animadex_discovery_query="reimu",
            global_module_library_search_query="rainbow",
            global_module_library_session_cache={
                "path": "fixture/global_modules.json",
                "library": {"milku": {"body": "rainbow"}},
            },
            active_management_workspace="module_attribute_authoring",
        )
        namespace = self._load_functions(
            "reset_management_workspace_session_state",
            "reset_module_attribute_authoring_project_session_state",
            namespace={
                "st": types.SimpleNamespace(session_state=session_state),
                "ACTIVE_MANAGEMENT_WORKSPACE_KEY": "active_management_workspace",
            },
        )

        namespace["reset_management_workspace_session_state"]()
        namespace["reset_module_attribute_authoring_project_session_state"]()

        self.assertEqual(current_path, session_state.animadex_browser_path)
        self.assertEqual(current_path, session_state.animadex_browser_path_draft)
        self.assertEqual(100, session_state.animadex_browser_sample_limit)
        self.assertIs(summary, session_state.animadex_discovery_summary)
        self.assertEqual("reimu", session_state.animadex_discovery_query)
        self.assertEqual(
            "rainbow",
            session_state.global_module_library_search_query,
        )
        self.assertIn(
            "milku",
            session_state.global_module_library_session_cache["library"],
        )
        self.assertEqual("saved-default", session_state.settings["animadex_local_path"])

    def test_failed_project_load_returns_before_project_bound_resets(self):
        source = self._function_source("load_project_json_into_session")
        missing_guard = source.index("if not os.path.exists(project_path):")
        failed_return = source.index("return False", missing_guard)
        first_reset = source.index("reset_lightweight_fork_session_state()")
        self.assertLess(missing_guard, failed_return)
        self.assertLess(failed_return, first_reset)
        self.assertNotIn("animadex_local_path", source)
        self.assertNotIn("animadex_browser_path", source)


if __name__ == "__main__":
    unittest.main()
