import unittest
from pathlib import Path


class ManagementWorkspaceShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.app_source = (cls.root / "app.py").read_text(encoding="utf-8")

    def _function_source(self, name, next_name):
        start = self.app_source.index(f"def {name}")
        end = self.app_source.index(f"def {next_name}", start)
        return self.app_source[start:end]

    def test_session_key_and_allowed_targets_are_explicit(self):
        self.assertIn(
            'ACTIVE_MANAGEMENT_WORKSPACE_KEY = "active_management_workspace"',
            self.app_source,
        )
        targets = self.app_source.split(
            "MANAGEMENT_WORKSPACE_TARGETS = {", maxsplit=1
        )[1].split("_APP_RERUN_STARTED_AT", maxsplit=1)[0]
        for target in (
            "project_management",
            "module_attribute_authoring",
            "module_attribute_apply",
            "comfyui_settings",
        ):
            self.assertEqual(targets.count(f'"{target}": {{'), 1)
        self.assertIn(
            "if ACTIVE_MANAGEMENT_WORKSPACE_KEY not in st.session_state:",
            self.app_source,
        )

    def test_invalid_targets_normalize_to_inactive(self):
        normalize = self._function_source(
            "normalize_management_workspace_target",
            "reset_management_workspace_session_state",
        )
        self.assertIn("if clean_target in MANAGEMENT_WORKSPACE_TARGETS:", normalize)
        self.assertTrue(normalize.rstrip().endswith('return ""'))

        active = self._function_source(
            "get_active_management_workspace",
            "render_management_workspace_launchers",
        )
        self.assertIn(
            "clean_target = normalize_management_workspace_target(stored_target)",
            active,
        )
        self.assertIn(
            "st.session_state[ACTIVE_MANAGEMENT_WORKSPACE_KEY] = clean_target",
            active,
        )

    def test_open_and_close_only_change_workspace_state(self):
        open_source = self._function_source(
            "open_management_workspace",
            "get_active_management_workspace",
        )
        close_source = self._function_source(
            "reset_management_workspace_session_state",
            "reset_module_attribute_authoring_project_session_state",
        )
        for forbidden in (
            "gallery_main_mode_enabled",
            "trash_view_mode_enabled",
            "focused_line_id",
            "selected_node_ids",
            "gallery_selected_route_ids",
            "history",
            "save_",
        ):
            self.assertNotIn(forbidden, open_source)
            self.assertNotIn(forbidden, close_source)

    def test_launchers_route_to_unique_targets_and_keys(self):
        launchers = self._function_source(
            "render_management_workspace_launchers",
            "render_management_workspace_shell",
        )
        expected = {
            "project_management": "open_project_management_workspace",
            "module_attribute_authoring": (
                "open_module_attribute_authoring_workspace"
            ),
            "comfyui_settings": "open_comfyui_settings_workspace",
        }
        for target, key in expected.items():
            self.assertEqual(launchers.count(f'"{target}"'), 1)
            self.assertEqual(launchers.count(f'"{key}"'), 1)
        self.assertNotIn('"module_attribute_apply"', launchers)
        self.assertNotIn("Open Apply Workspace", launchers)
        self.assertIn("open_management_workspace(target)", launchers)
        self.assertIn("st.rerun()", launchers)

    def test_workspace_router_is_exclusive_and_precedes_production_modes(self):
        router = self.app_source.index(
            "active_management_workspace = get_active_management_workspace()"
        )
        no_project = self.app_source.index("if not st.session_state.project:", router)
        mode_controls = self.app_source.index("mode_cols = st.columns([1, 1, 3])")
        self.assertLess(router, no_project)
        self.assertLess(router, mode_controls)

        router_source = self.app_source[router:no_project]
        self.assertIn(
            "render_management_workspace_shell(active_management_workspace)",
            router_source,
        )
        self.assertIn("st.stop()", router_source)

        shell = self._function_source(
            "render_management_workspace_shell",
            "_invalidate_lightweight_fork_discovery_cache",
        )
        self.assertIn('key="close_active_management_workspace"', shell)
        self.assertIn("reset_management_workspace_session_state()", shell)
        self.assertIn('if target == "comfyui_settings":', shell)
        self.assertIn("render_comfyui_settings_workspace()", shell)
        self.assertIn('if target == "module_attribute_authoring":', shell)
        self.assertIn("render_module_attribute_authoring_workspace()", shell)
        self.assertIn('if target == "module_attribute_apply":', shell)
        self.assertIn("render_module_attribute_apply_workspace()", shell)
        for forbidden in (
            "render_pro_gallery_mode",
            "render_pro_trash_view_mode",
            "render_comfy_workflow_inspector",
            "render_attribute_group_sidebar_manager",
            "save_project_to_json",
            "save_settings",
            "build_graph",
        ):
            self.assertNotIn(forbidden, shell)

    def test_project_transition_success_paths_reset_workspace(self):
        loader = self._function_source(
            "load_project_json_into_session",
            "auto_open_last_project_on_startup",
        )
        self.assertLess(
            loader.index("project = load_project_from_json(project_path)"),
            loader.index("reset_management_workspace_session_state()"),
        )
        self.assertLess(
            loader.index("reset_management_workspace_session_state()"),
            loader.index("st.session_state.project = project"),
        )

        startup = self._function_source(
            "auto_open_last_project_on_startup",
            "_unique_project_dir",
        )
        self.assertIn("open_project=load_project_json_into_session", startup)

        new_project = self._function_source(
            "set_new_workspace_project",
            "_sanitize_duplicate_project_dir_name",
        )
        self.assertIn("reset_management_workspace_session_state()", new_project)

        duplicate = self._function_source(
            "duplicate_current_project_directory",
            "is_valid_new_module_name",
        )
        self.assertIn(
            "load_project_json_into_session(destination_project_path)",
            duplicate,
        )

        prompt_import = self._function_source(
            "render_prompt_import_export_panel",
            "render_gallery_import_export_section",
        )
        self.assertEqual(
            prompt_import.count("reset_management_workspace_session_state()"),
            2,
        )

    def test_workspace_shell_does_not_add_persistent_state(self):
        for forbidden in (
            '"previous_production_mode"',
            '"management_workspace" =',
            "Project.management_workspace",
            "settings[ACTIVE_MANAGEMENT_WORKSPACE_KEY]",
        ):
            self.assertNotIn(forbidden, self.app_source)


if __name__ == "__main__":
    unittest.main()
