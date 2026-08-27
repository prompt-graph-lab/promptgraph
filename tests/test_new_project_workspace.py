import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from core.io import load_project_from_json
from core.new_project_workspace import (
    create_new_workspace_files,
    normalize_new_workspace_project_file_name,
    resolve_new_workspace_destination,
)


class NewProjectDestinationResolverTests(unittest.TestCase):
    def test_default_parent_and_project_name_resolve_to_project_json(self):
        parent = os.path.abspath(os.path.join("projects"))
        result = resolve_new_workspace_destination(parent, "MyProject", "project.json")

        self.assertTrue(result["valid"])
        self.assertEqual(parent, result["parent_dir"])
        self.assertEqual(os.path.join(parent, "MyProject"), result["project_dir"])
        self.assertEqual(os.path.join(parent, "MyProject", "project.json"), result["project_path"])

    def test_custom_absolute_parent_and_relative_parent_are_normalized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            absolute_result = resolve_new_workspace_destination(temp_dir, "MilkBook", "book")
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                relative_result = resolve_new_workspace_destination("relative-parent", "MilkBook", "book")
            finally:
                os.chdir(previous_cwd)

        self.assertTrue(absolute_result["valid"])
        self.assertEqual(os.path.abspath(temp_dir), absolute_result["parent_dir"])
        self.assertEqual("book.json", absolute_result["project_file_name"])
        self.assertTrue(os.path.isabs(relative_result["parent_dir"]))

    def test_parent_expands_user_without_creating_directories(self):
        expanded_parent = os.path.join(os.path.expanduser("~"), "promptgraph-new-project-preview")
        result = resolve_new_workspace_destination(
            "~/promptgraph-new-project-preview",
            "PreviewOnly",
            "project.json",
            path_exists=lambda _path: False,
            path_is_file=lambda _path: False,
        )

        self.assertTrue(result["valid"])
        self.assertEqual(os.path.abspath(expanded_parent), result["parent_dir"])

    def test_invalid_parent_and_project_names_are_rejected(self):
        invalid_names = ["", ".", "..", "../escape", "A/B", "A\\B", "C:\\Absolute", "A:B", "A*B", "Tail. "]
        for project_name in invalid_names:
            with self.subTest(project_name=project_name):
                result = resolve_new_workspace_destination("parent", project_name, "project.json")
                self.assertFalse(result["valid"])

        self.assertFalse(resolve_new_workspace_destination("", "Valid", "project.json")["valid"])

    def test_parent_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent_file = os.path.join(temp_dir, "not-a-folder")
            Path(parent_file).write_text("file", encoding="utf-8")
            result = resolve_new_workspace_destination(parent_file, "Project", "project.json")

        self.assertFalse(result["valid"])
        self.assertIn("folder", result["error"])

    def test_json_filename_is_normalized_without_directory_escape(self):
        default_name, default_error = normalize_new_workspace_project_file_name("")
        self.assertEqual("project.json", default_name)
        self.assertEqual("", default_error)

        normalized, error = normalize_new_workspace_project_file_name("../nested/book")
        self.assertEqual("book.json", normalized)
        self.assertEqual("", error)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = resolve_new_workspace_destination(temp_dir, "MilkBook", "../nested/book")

        self.assertTrue(result["valid"])
        self.assertEqual("book.json", result["project_file_name"])
        self.assertEqual(os.path.join(result["project_dir"], "book.json"), result["project_path"])

    def test_preview_reports_collision_suffix_without_filesystem_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, "MilkBook"))
            os.makedirs(os.path.join(temp_dir, "MilkBook-1"))
            result = resolve_new_workspace_destination(temp_dir, "MilkBook", "project.json")

        self.assertTrue(result["valid"])
        self.assertEqual(2, result["collision_index"])
        self.assertTrue(result["project_dir"].endswith("MilkBook-2"))

    def test_dangling_symlink_is_a_preview_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            link_path = os.path.join(temp_dir, "Project")
            missing_target = os.path.join(temp_dir, "missing-target")
            try:
                os.symlink(missing_target, link_path, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            self.assertFalse(os.path.exists(link_path))
            self.assertTrue(os.path.lexists(link_path))
            result = resolve_new_workspace_destination(temp_dir, "Project", "project.json")

            self.assertTrue(result["valid"])
            self.assertEqual(1, result["collision_index"])
            self.assertEqual(f"{link_path}-1", result["project_dir"])
            self.assertTrue(os.path.islink(link_path))

    def test_preview_does_not_create_missing_parent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_parent = os.path.join(temp_dir, "missing", "parent")
            result = resolve_new_workspace_destination(missing_parent, "PreviewOnly", "project.json")
            self.assertTrue(result["valid"])
            self.assertFalse(os.path.exists(missing_parent))


class NewProjectWorkspaceCreationTests(unittest.TestCase):
    def test_creates_under_default_style_projects_parent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            projects_parent = os.path.join(temp_dir, "projects")
            project_path, error = create_new_workspace_files(
                os.path.join(projects_parent, "MyProject"),
                "project.json",
            )

            self.assertIsNone(error)
            self.assertEqual(
                os.path.join(projects_parent, "MyProject", "project.json"),
                project_path,
            )
            self.assertTrue(os.path.isfile(project_path))

    def test_creates_project_json_and_folder_layout_under_custom_parent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path, error = create_new_workspace_files(
                os.path.join(temp_dir, "custom", "MilkBook"),
                "book",
            )
            loaded = load_project_from_json(project_path)

            self.assertIsNone(error)
            self.assertTrue(os.path.isfile(project_path))
            self.assertEqual([], loaded.prompt_lines)
            for folder_name in ("refs", "candidates", "routes", "exports", "workflows"):
                self.assertTrue(os.path.isdir(os.path.join(os.path.dirname(project_path), folder_name)))

    def test_collision_suffixes_do_not_overwrite_existing_projects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = os.path.join(temp_dir, "MilkBook")
            os.makedirs(base_dir)
            existing_path = os.path.join(base_dir, "project.json")
            Path(existing_path).write_text('{"keep": true}', encoding="utf-8")
            os.makedirs(f"{base_dir}-1")

            project_path, error = create_new_workspace_files(base_dir, "project.json")

            self.assertIsNone(error)
            self.assertTrue(project_path.startswith(f"{base_dir}-2"))
            self.assertEqual('{"keep": true}', Path(existing_path).read_text(encoding="utf-8"))

    def test_dangling_symlink_is_preserved_and_creation_uses_suffix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            link_path = os.path.join(temp_dir, "Project")
            missing_target = os.path.join(temp_dir, "missing-target")
            try:
                os.symlink(missing_target, link_path, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            project_path, error = create_new_workspace_files(link_path, "project.json")

            self.assertIsNone(error)
            self.assertEqual(os.path.join(f"{link_path}-1", "project.json"), project_path)
            self.assertTrue(os.path.isfile(project_path))
            self.assertTrue(os.path.islink(link_path))
            self.assertEqual(missing_target, os.readlink(link_path))

    def test_file_exists_race_advances_suffix_before_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = os.path.join(temp_dir, "Project")
            real_makedirs = os.makedirs
            attempted_dirs = []

            def race_once(path, *, exist_ok):
                attempted_dirs.append(path)
                if len(attempted_dirs) == 1:
                    raise FileExistsError(path)
                real_makedirs(path, exist_ok=exist_ok)

            with mock.patch("core.new_project_workspace.os.makedirs", side_effect=race_once):
                project_path, error = create_new_workspace_files(
                    base_dir,
                    "project.json",
                    path_exists=lambda _path: False,
                )

            self.assertIsNone(error)
            self.assertEqual([base_dir, f"{base_dir}-1"], attempted_dirs[:2])
            self.assertEqual(os.path.join(f"{base_dir}-1", "project.json"), project_path)

    def test_custom_parent_does_not_create_unrelated_default_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_dir = os.path.join(temp_dir, "custom", "Project")
            unrelated_default = os.path.join(temp_dir, "projects")
            project_path, error = create_new_workspace_files(custom_dir, "project.json")

            self.assertIsNone(error)
            self.assertTrue(os.path.isfile(project_path))
            self.assertFalse(os.path.exists(unrelated_default))

    def test_parent_file_and_permission_failure_do_not_call_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent_file = os.path.join(temp_dir, "parent-file")
            Path(parent_file).write_text("file", encoding="utf-8")
            save_calls = []
            with self.assertRaises(OSError):
                create_new_workspace_files(
                    os.path.join(parent_file, "Project"),
                    "project.json",
                    save_project=lambda project, path: save_calls.append((project, path)),
                )
            self.assertEqual([], save_calls)

            with mock.patch("core.new_project_workspace.os.makedirs", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    create_new_workspace_files(
                        os.path.join(temp_dir, "Denied"),
                        "project.json",
                        save_project=lambda project, path: save_calls.append((project, path)),
                    )
            self.assertEqual([], save_calls)

    def test_save_failure_does_not_run_folder_layout(self):
        layout_calls = []

        def fail_save(_project, _path):
            raise OSError("save failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(OSError):
                create_new_workspace_files(
                    os.path.join(temp_dir, "Project"),
                    "project.json",
                    save_project=fail_save,
                    ensure_folder_layout=lambda path: layout_calls.append(path),
                )

        self.assertEqual([], layout_calls)


class NewProjectWorkspaceUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        cls.section_start = cls.app_source.index(
            "def render_new_project_management_section()"
        )
        cls.section_end = cls.app_source.index(
            "def render_duplicate_project_management_section()",
            cls.section_start,
        )
        cls.section_source = cls.app_source[cls.section_start:cls.section_end]

    def test_workspace_separates_parent_name_and_file_inputs(self):
        self.assertIn('"保存先親フォルダ"', self.section_source)
        self.assertIn('key="new_workspace_parent_dir"', self.section_source)
        self.assertIn('"プロジェクト名"', self.section_source)
        self.assertIn('key="new_workspace_project_name"', self.section_source)
        self.assertIn('key="new_workspace_project_file"', self.section_source)
        self.assertNotIn("プロジェクト名 / フォルダ名", self.section_source)
        self.assertNotIn('key="new_project_dir"', self.section_source)

    def test_workspace_uses_default_parent_and_previews_resolved_path(self):
        self.assertIn("ensure_new_workspace_parent_directory()", self.section_source)
        self.assertIn("default_projects_dir()", self.app_source)
        self.assertIn("resolve_new_workspace_destination(", self.section_source)
        self.assertIn('st.caption("作成先")', self.section_source)
        self.assertIn('st.code(destination["project_path"], language="text")', self.section_source)
        self.assertIn('destination["collision_index"]', self.section_source)

    def test_invalid_destination_disables_create_without_mutation(self):
        self.assertIn('disabled=not destination["valid"]', self.section_source)
        resolver_call = self.section_source.index("resolve_new_workspace_destination(")
        create_button = self.section_source.index("if st.button(", resolver_call)
        self.assertIn('"作成"', self.section_source[create_button:])
        create_call = self.section_source.index("create_new_workspace(", create_button)
        session_switch = self.section_source.index("set_new_workspace_project(project_path)", create_call)
        self.assertLess(resolver_call, create_button)
        self.assertLess(create_button, create_call)
        self.assertLess(create_call, session_switch)

    def test_ui_keeps_existing_create_flow_and_no_persistent_root_setting(self):
        self.assertIn('key="create_new_workspace"', self.section_source)
        self.assertIn('st.success("プロジェクトを作成しました。")', self.section_source)
        self.assertNotIn("last_new_project_parent", self.app_source)
        self.assertNotIn("default_project_root", self.app_source)
        self.assertNotIn("folder_picker", self.app_source)

    def test_other_project_management_flows_remain_available(self):
        for expected in (
            'key="quick_save_project"',
            'st.button("最近のプロジェクトを開く")',
            'st.button("JSONファイルを開く")',
            '"別名で保存して切り替える"',
            '"プロジェクトディレクトリを複製して開く"',
        ):
            self.assertIn(expected, self.app_source)

    def test_legacy_create_wrapper_keeps_relative_and_absolute_resolution(self):
        wrapper_start = self.app_source.index("def create_new_workspace(")
        wrapper_end = self.app_source.index("def set_new_workspace_project", wrapper_start)
        wrapper_source = self.app_source[wrapper_start:wrapper_end]
        self.assertIn("clean_project_dir = default_new_project_dir(clean_project_dir_raw)", wrapper_source)
        self.assertIn("return create_new_workspace_files(clean_project_dir, project_file_name)", wrapper_source)
        self.assertNotIn("os.makedirs(default_projects_dir()", wrapper_source)

    def test_successful_session_switch_clears_startup_warning(self):
        setter_start = self.app_source.index("def set_new_workspace_project")
        setter_end = self.app_source.index("def _sanitize_duplicate_project_dir_name", setter_start)
        setter_source = self.app_source[setter_start:setter_end]
        for expected in (
            "st.session_state.history = []",
            "reset_lightweight_fork_session_state()",
            "reset_gallery_route_action_session_state()",
            "reset_gallery_selected_route_session_state()",
            "st.session_state.current_project_path = os.path.abspath(project_path)",
            "st.session_state.settings = remember_project(",
            "save_settings(st.session_state.settings)",
        ):
            self.assertIn(expected, setter_source)
        self.assertIn('st.session_state.pop("startup_project_auto_open_error", None)', setter_source)

    def test_creation_failure_does_not_switch_the_current_session(self):
        error_branch = self.section_source.index("if error:")
        warning = self.section_source.index("st.warning(error)", error_branch)
        success_branch = self.section_source.index("else:", warning)
        session_switch = self.section_source.index("set_new_workspace_project(project_path)", success_branch)
        self.assertLess(error_branch, warning)
        self.assertLess(warning, success_branch)
        self.assertLess(success_branch, session_switch)


if __name__ == "__main__":
    unittest.main()
