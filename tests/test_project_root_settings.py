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
    get_projects_root_directory,
    load_settings,
    normalize_projects_root_directory,
    remember_project,
    save_settings,
)
from core.new_project_workspace import create_new_workspace_files


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class ProjectRootSettingsHelperTests(unittest.TestCase):
    def test_old_settings_file_loads_with_empty_portable_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = os.path.join(temp_dir, "settings.json")
            Path(settings_path).write_text(
                json.dumps({"unknown_setting": "preserved"}),
                encoding="utf-8",
            )
            with mock.patch.object(settings_module, "SETTINGS_FILE", settings_path):
                loaded = load_settings()

        self.assertEqual("", loaded["projects_root_directory"])
        self.assertEqual("preserved", loaded["unknown_setting"])

    def test_empty_and_malformed_values_use_supplied_fallback(self):
        fallback = os.path.join("portable", "projects")
        expected = os.path.abspath(fallback)
        for settings in (
            {},
            {"projects_root_directory": ""},
            {"projects_root_directory": "   "},
            {"projects_root_directory": 123},
            {"projects_root_directory": {"path": "invalid"}},
            None,
        ):
            with self.subTest(settings=settings):
                self.assertEqual(
                    expected,
                    get_projects_root_directory(settings, fallback),
                )
        self.assertEqual("", normalize_projects_root_directory("bad\x00path"))
        if os.name == "nt":
            self.assertEqual("", normalize_projects_root_directory("C:/bad<path>"))
            self.assertEqual(
                "",
                normalize_projects_root_directory(r"C:\valid-drive\bad:name"),
            )

    def test_absolute_relative_and_pathlike_roots_normalize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            absolute = os.path.join(temp_dir, "custom")
            self.assertEqual(
                os.path.abspath(absolute),
                normalize_projects_root_directory(f"  {absolute}  "),
            )
            self.assertEqual(
                os.path.abspath("relative-projects"),
                normalize_projects_root_directory("relative-projects"),
            )
            self.assertEqual(
                os.path.abspath(absolute),
                normalize_projects_root_directory(Path(absolute)),
            )

    def test_home_directory_is_expanded(self):
        with mock.patch.object(settings_module.os.path, "expanduser") as expanduser:
            expanduser.return_value = os.path.join("expanded", "projects")
            normalized = normalize_projects_root_directory("~/projects")

        expanduser.assert_called_once_with("~/projects")
        self.assertEqual(os.path.abspath(os.path.join("expanded", "projects")), normalized)

    def test_save_load_round_trip_preserves_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = os.path.join(temp_dir, "settings.json")
            custom_root = os.path.join(temp_dir, "custom-root")
            original = {
                "projects_root_directory": custom_root,
                "unknown_setting": {"keep": True},
            }
            with mock.patch.object(settings_module, "SETTINGS_FILE", settings_path):
                save_settings(original)
                loaded = load_settings()

        self.assertEqual(custom_root, loaded["projects_root_directory"])
        self.assertEqual({"keep": True}, loaded["unknown_setting"])

    def test_helpers_do_not_create_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_root = os.path.join(temp_dir, "missing", "projects")
            resolved = get_projects_root_directory(
                {"projects_root_directory": missing_root},
                os.path.join(temp_dir, "fallback"),
            )

            self.assertEqual(os.path.abspath(missing_root), resolved)
            self.assertFalse(os.path.exists(missing_root))

    def test_successful_project_creation_does_not_rewrite_configured_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured_root = os.path.join(temp_dir, "configured-root")
            settings = {
                "projects_root_directory": configured_root,
                "last_project": "",
                "recent_projects": [],
            }
            project_path, error = create_new_workspace_files(
                os.path.join(configured_root, "CreatedProject"),
                "project.json",
            )
            remember_project(settings, project_path)

            self.assertIsNone(error)
            self.assertTrue(os.path.isfile(project_path))
            self.assertEqual(configured_root, settings["projects_root_directory"])


class ProjectRootSettingsAppTests(unittest.TestCase):
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
            "default_projects_dir",
            "validate_projects_root_directory",
            "_new_workspace_parent_matches_default",
            "_update_new_workspace_parent_after_default_change",
            "save_projects_root_directory_setting",
            "reset_projects_root_directory_setting",
            namespace={
                "os": os,
                "st": types.SimpleNamespace(session_state=session_state),
                "APP_ROOT": os.path.join("C:\\", "PromptGraph"),
                "DEFAULT_PROJECTS_DIR_NAME": "projects",
                "get_projects_root_directory": get_projects_root_directory,
                "normalize_projects_root_directory": normalize_projects_root_directory,
                "save_settings": lambda value: saved.append(dict(value)),
            },
        )

    def test_default_projects_dir_uses_setting_then_portable_fallback(self):
        session_state = _SessionState(settings={"projects_root_directory": ""})
        namespace = self._load_functions(
            "default_projects_dir",
            namespace={
                "os": os,
                "st": types.SimpleNamespace(session_state=session_state),
                "APP_ROOT": os.path.join("C:\\", "PromptGraph"),
                "DEFAULT_PROJECTS_DIR_NAME": "projects",
                "get_projects_root_directory": get_projects_root_directory,
            },
        )
        fallback = os.path.abspath(os.path.join("C:\\", "PromptGraph", "projects"))
        self.assertEqual(fallback, namespace["default_projects_dir"]())

        configured = os.path.abspath(os.path.join("D:\\", "Projects"))
        session_state.settings["projects_root_directory"] = configured
        self.assertEqual(configured, namespace["default_projects_dir"]())

    def test_save_writes_once_without_creating_missing_root_or_mutating_project_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_root = os.path.join(temp_dir, "previous")
            missing_root = os.path.join(temp_dir, "missing", "projects")
            project = object()
            session_state = _SessionState(
                settings={
                    "projects_root_directory": previous_root,
                    "last_project": "external/project.json",
                    "recent_projects": [{"path": "external/project.json"}],
                    "unrelated": "keep",
                },
                _projects_root_directory_widget=missing_root,
                new_workspace_parent_dir=previous_root,
                active_management_workspace="project_management",
                project=project,
                current_project_path="external/project.json",
                history=["keep-history"],
                gallery_state={"keep": True},
                selected_node_ids=["line-1"],
                focused_line_id="line-1",
            )
            saved = []
            namespace = self._callback_namespace(session_state, saved)

            namespace["save_projects_root_directory_setting"]()

            self.assertEqual(1, len(saved))
            self.assertEqual(os.path.abspath(missing_root), saved[0]["projects_root_directory"])
            self.assertFalse(os.path.exists(missing_root))
            self.assertIs(project, session_state.project)
            self.assertEqual("external/project.json", session_state.current_project_path)
            self.assertEqual(["keep-history"], session_state.history)
            self.assertEqual([{"path": "external/project.json"}], session_state.settings["recent_projects"])
            self.assertEqual("external/project.json", session_state.settings["last_project"])
            self.assertEqual("project_management", session_state.active_management_workspace)
            self.assertEqual(os.path.abspath(missing_root), session_state.new_workspace_parent_dir)

    def test_save_preserves_manual_new_project_parent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_root = os.path.join(temp_dir, "previous")
            next_root = os.path.join(temp_dir, "next")
            manual_parent = os.path.join(temp_dir, "manual")
            session_state = _SessionState(
                settings={"projects_root_directory": previous_root},
                _projects_root_directory_widget=next_root,
                new_workspace_parent_dir=manual_parent,
                active_management_workspace="project_management",
            )
            saved = []
            namespace = self._callback_namespace(session_state, saved)

            namespace["save_projects_root_directory_setting"]()

            self.assertEqual(1, len(saved))
            self.assertEqual(manual_parent, session_state.new_workspace_parent_dir)

    def test_invalid_empty_file_and_dangling_link_targets_are_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_state = _SessionState(
                settings={"projects_root_directory": ""},
                _projects_root_directory_widget="   ",
                active_management_workspace="project_management",
            )
            saved = []
            namespace = self._callback_namespace(session_state, saved)
            namespace["save_projects_root_directory_setting"]()
            self.assertEqual([], saved)

            if os.name == "nt":
                session_state._projects_root_directory_widget = (
                    r"C:\valid-drive\bad:name"
                )
                namespace["save_projects_root_directory_setting"]()
                self.assertEqual([], saved)

            file_path = os.path.join(temp_dir, "regular-file")
            Path(file_path).write_text("not a directory", encoding="utf-8")
            self.assertTrue(namespace["validate_projects_root_directory"](file_path)[1])

            link_path = os.path.join(temp_dir, "dangling-link")
            missing_target = os.path.join(temp_dir, "missing-target")
            try:
                os.symlink(missing_target, link_path, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            self.assertTrue(namespace["validate_projects_root_directory"](link_path)[1])

    def test_reset_writes_empty_value_once_and_does_not_create_builtin_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = os.path.join(temp_dir, "portable-install")
            configured_root = os.path.join(temp_dir, "configured")
            session_state = _SessionState(
                settings={
                    "projects_root_directory": configured_root,
                    "last_project": "external/project.json",
                    "recent_projects": [{"path": "external/project.json"}],
                },
                _projects_root_directory_widget=configured_root,
                new_workspace_parent_dir=configured_root,
                active_management_workspace="project_management",
                project=object(),
                history=["keep"],
            )
            saved = []
            namespace = self._callback_namespace(session_state, saved)
            namespace["APP_ROOT"] = app_root

            namespace["reset_projects_root_directory_setting"]()

            built_in_root = os.path.abspath(os.path.join(app_root, "projects"))
            self.assertEqual(1, len(saved))
            self.assertEqual("", saved[0]["projects_root_directory"])
            self.assertEqual(built_in_root, session_state._projects_root_directory_widget)
            self.assertEqual(built_in_root, session_state.new_workspace_parent_dir)
            self.assertFalse(os.path.exists(built_in_root))
            self.assertEqual("external/project.json", session_state.settings["last_project"])
            self.assertEqual([{"path": "external/project.json"}], session_state.settings["recent_projects"])
            self.assertEqual(["keep"], session_state.history)
            self.assertEqual("project_management", session_state.active_management_workspace)

    def test_new_project_parent_initializes_once_and_restore_is_explicit(self):
        session_state = _SessionState(
            settings={"projects_root_directory": os.path.abspath("configured-root")}
        )
        namespace = self._load_functions(
            "default_projects_dir",
            "restore_new_workspace_parent_to_default",
            "ensure_new_workspace_parent_directory",
            namespace={
                "os": os,
                "st": types.SimpleNamespace(session_state=session_state),
                "APP_ROOT": os.path.abspath("."),
                "DEFAULT_PROJECTS_DIR_NAME": "projects",
                "get_projects_root_directory": get_projects_root_directory,
            },
        )

        configured = namespace["ensure_new_workspace_parent_directory"]()
        self.assertEqual(os.path.abspath("configured-root"), configured)
        session_state.new_workspace_parent_dir = os.path.abspath("manual-parent")
        self.assertEqual(
            os.path.abspath("manual-parent"),
            namespace["ensure_new_workspace_parent_directory"](),
        )
        namespace["restore_new_workspace_parent_to_default"]()
        self.assertEqual(os.path.abspath("configured-root"), session_state.new_workspace_parent_dir)

    def test_project_defaults_has_one_workspace_owner_and_renders_first(self):
        workspace = self._function_source("render_project_management_workspace")
        defaults_call = workspace.index("render_project_defaults_management_section()")
        new_call = workspace.index("render_new_project_management_section()")
        duplicate_call = workspace.index("render_duplicate_project_management_section()")
        self.assertLess(defaults_call, new_call)
        self.assertLess(new_call, duplicate_call)
        self.assertEqual(
            self.app_source.count("render_project_defaults_management_section()"),
            2,
        )
        defaults = self._function_source("render_project_defaults_management_section")
        self.assertIn('st.expander("Project Defaults"', defaults)
        self.assertNotIn("st.sidebar", defaults)

    def test_rendering_does_not_write_settings_or_rerun(self):
        defaults = self._function_source("render_project_defaults_management_section")
        self.assertNotIn("save_settings(", defaults)
        self.assertNotIn("st.rerun(", defaults)
        self.assertNotIn("os.makedirs(", defaults)
        self.assertNotIn("os.mkdir(", defaults)

    def test_new_project_widget_avoids_conflicting_explicit_default(self):
        new_project = self._function_source("render_new_project_management_section")
        self.assertIn("ensure_new_workspace_parent_directory()", new_project)
        text_input_start = new_project.index('st.text_input(\n            "保存先親フォルダ"')
        text_input_end = new_project.index(")", text_input_start)
        self.assertNotIn("default_projects_dir()", new_project[text_input_start:text_input_end])
        self.assertIn('key="new_workspace_parent_dir"', new_project)
        self.assertIn('"Use default Project root"', new_project)

    def test_metadata_includes_default_project_root(self):
        targets_start = self.app_source.index("MANAGEMENT_WORKSPACE_TARGETS = {")
        targets_end = self.app_source.index("_APP_RERUN_STARTED_AT", targets_start)
        targets = self.app_source[targets_start:targets_end]
        self.assertIn('"Default Project root"', targets)


if __name__ == "__main__":
    unittest.main()
