import unittest
from pathlib import Path


class ProjectManagementWorkspaceRelocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )

    def _function_source(self, name, next_name):
        start = self.app_source.index(f"def {name}")
        end = self.app_source.index(f"def {next_name}", start)
        return self.app_source[start:end]

    def test_project_workspace_dispatches_real_forms_only_for_project_target(self):
        shell = self._function_source(
            "render_management_workspace_shell",
            "_invalidate_lightweight_fork_discovery_cache",
        )
        self.assertIn('if target == "project_management":', shell)
        self.assertIn("render_project_management_workspace()", shell)
        self.assertLess(
            shell.index("render_project_management_workspace()"),
            shell.index("render_module_attribute_authoring_workspace()"),
        )
        self.assertIn("return", shell)

        workspace = self._function_source(
            "render_project_management_workspace",
            "is_valid_new_module_name",
        )
        self.assertIn("render_project_defaults_management_section()", workspace)
        self.assertIn("render_new_project_management_section()", workspace)
        self.assertIn("render_duplicate_project_management_section()", workspace)
        self.assertIn("render_existing_project_import_section()", workspace)
        self.assertLess(
            workspace.index("render_project_defaults_management_section()"),
            workspace.index("render_new_project_management_section()"),
        )
        self.assertLess(
            workspace.index("render_new_project_management_section()"),
            workspace.index("render_duplicate_project_management_section()"),
        )
        self.assertLess(
            workspace.index("render_duplicate_project_management_section()"),
            workspace.index("render_existing_project_import_section()"),
        )
        self.assertIn("Advanced direct JSON", workspace)
        self.assertIn("Project Assets remain in the Sidebar for Pro v1", workspace)

    def test_relocated_forms_have_one_render_owner_and_keep_widget_keys(self):
        self.assertNotIn(
            'with st.sidebar.expander("新規プロジェクト", expanded=False):',
            self.app_source,
        )
        self.assertNotIn(
            'with st.sidebar.expander("プロジェクトを複製", expanded=False):',
            self.app_source,
        )

        for key in (
            "new_workspace_parent_dir",
            "_projects_root_directory_widget",
            "save_projects_root_directory",
            "reset_projects_root_directory",
            "use_default_projects_root",
            "new_workspace_project_name",
            "new_workspace_project_file",
            "create_new_workspace",
            "duplicate_project_dir_name",
            "duplicate_project_confirm",
            "duplicate_project_as_button",
        ):
            self.assertEqual(self.app_source.count(f'key="{key}"'), 1)

    def test_create_and_duplicate_keep_existing_helpers_and_close_after_success(self):
        create = self._function_source(
            "render_new_project_management_section",
            "render_duplicate_project_management_section",
        )
        self.assertIn("resolve_new_workspace_destination(", create)
        self.assertIn("create_new_workspace(", create)
        self.assertIn("set_new_workspace_project(project_path)", create)
        self.assertLess(
            create.index("set_new_workspace_project(project_path)"),
            create.index("st.rerun()"),
        )

        duplicate = self._function_source(
            "render_duplicate_project_management_section",
            "_project_root_import_external_source",
        )
        self.assertIn(
            "duplicate_current_project_directory(",
            duplicate,
        )
        self.assertIn("st.rerun()", duplicate)

    def test_daily_advanced_and_project_assets_entries_remain_in_sidebar(self):
        sidebar_start = self.app_source.index('st.sidebar.subheader("プロジェクト")')
        router = self.app_source.index(
            "active_management_workspace = get_active_management_workspace()",
            sidebar_start,
        )
        sidebar = self.app_source[sidebar_start:router]
        for expected in (
            'key="quick_save_project"',
            'with st.sidebar.expander("プロジェクトを開く"',
            'with st.sidebar.expander("Advanced"',
            'key="open_project_path"',
            'key="save_project_as_json_button"',
            "render_project_assets_sidebar_section()",
        ):
            self.assertIn(expected, sidebar)
        project_assets = self._function_source(
            "render_project_assets_sidebar_section",
            "is_valid_new_module_name",
        )
        self.assertIn(
            '"Candidate / Variant画像をProjectへ取り込む"',
            project_assets,
        )
        self.assertIn('key="copy_candidates_to_project"', project_assets)

    def test_new_and_duplicate_do_not_own_root_settings_persistence(self):
        create = self._function_source(
            "render_new_project_management_section",
            "render_duplicate_project_management_section",
        )
        duplicate = self._function_source(
            "render_duplicate_project_management_section",
            "_project_root_import_external_source",
        )
        workspace = "\n".join((create, duplicate))
        for forbidden in (
            "save_project_to_json",
            "save_settings",
            "remember_project",
            "Project.management_workspace",
            "settings[ACTIVE_MANAGEMENT_WORKSPACE_KEY]",
        ):
            self.assertNotIn(forbidden, workspace)


if __name__ == "__main__":
    unittest.main()
