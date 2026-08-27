from pathlib import Path
import unittest


class SidebarProjectOpenUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        cls.project_open_start = cls.app_source.index(
            'with st.sidebar.expander("プロジェクトを開く", expanded=False):'
        )
        cls.advanced_start = cls.app_source.index(
            'with st.sidebar.expander("Advanced", expanded=False):',
            cls.project_open_start,
        )
        cls.next_section = cls.app_source.index(
            "render_project_assets_sidebar_section()",
            cls.advanced_start,
        )
        cls.recent_source = cls.app_source[cls.project_open_start:cls.advanced_start]
        cls.advanced_source = cls.app_source[cls.advanced_start:cls.next_section]

    def test_directory_browser_and_recent_projects_are_normal_open_paths(self):
        self.assertIn("render_project_directory_browser()", self.recent_source)
        self.assertIn("**最近のプロジェクト**", self.recent_source)
        self.assertIn('st.selectbox(\n            "最近のプロジェクト"', self.recent_source)
        self.assertIn('st.button("最近のプロジェクトを開く")', self.recent_source)
        self.assertIn("load_project_json_into_session(recent_project_path)", self.recent_source)
        self.assertLess(
            self.recent_source.index("render_project_directory_browser()"),
            self.recent_source.index("**最近のプロジェクト**"),
        )
        self.assertNotIn("open_project_path", self.recent_source)
        self.assertNotIn("プロジェクトJSON", self.recent_source)

    def test_direct_json_open_is_in_a_closed_advanced_sibling(self):
        self.assertLess(self.project_open_start, self.advanced_start)
        self.assertIn("**JSONファイルを直接指定して開く**", self.advanced_source)
        self.assertIn(
            'st.text_input("プロジェクトJSON", project_file_default, key="open_project_path")',
            self.advanced_source,
        )
        self.assertIn('st.button("JSONファイルを開く")', self.advanced_source)
        self.assertIn("load_project_json_into_session(open_project_path)", self.advanced_source)

    def test_save_as_is_inside_the_same_closed_advanced_section(self):
        self.assertIn("**Project JSONを別名で保存**", self.advanced_source)
        self.assertIn(
            '"現在のProjectを別のJSONへ保存し、"',
            self.advanced_source,
        )
        self.assertIn(
            '"そのJSONを以後の保存先として使用します。"',
            self.advanced_source,
        )
        self.assertIn(
            '"Projectディレクトリ全体を複製する場合は"',
            self.advanced_source,
        )
        self.assertIn(
            '"「プロジェクトを複製」を使用してください。"',
            self.advanced_source,
        )
        self.assertIn(
            'key="save_project_json_path",',
            self.advanced_source,
        )
        self.assertIn(
            "on_change=invalidate_project_save_as_confirmation_for_path_change",
            self.advanced_source,
        )
        self.assertIn('"別名で保存して切り替える"', self.advanced_source)
        self.assertIn('key="save_project_as_json_button"', self.advanced_source)
        self.assertIn("disabled=not bool(st.session_state.project)", self.advanced_source)
        self.assertNotIn(
            'with st.sidebar.expander("名前を付けて保存", expanded=False):',
            self.app_source,
        )
        self.assertLess(
            self.advanced_source.index("**JSONファイルを直接指定して開く**"),
            self.advanced_source.index("**Project JSONを別名で保存**"),
        )

    def test_save_as_state_contract_is_preserved(self):
        commit_start = self.app_source.index("def _commit_project_save_as(")
        commit_end = self.app_source.index(
            "def confirm_project_save_as_overwrite(",
            commit_start,
        )
        save_as_source = self.app_source[commit_start:commit_end]
        for expected in (
            "save_project_to_json(st.session_state.project, normalized_path)",
            "st.session_state.current_project_path = normalized_path",
            "ensure_current_project_folder_layout(normalized_path)",
            'st.session_state.autosave_feedback = "manual save"',
            "st.session_state.settings = remember_project(",
            "save_settings(st.session_state.settings)",
        ):
            self.assertIn(expected, save_as_source)
        self.assertEqual(1, self.app_source.count('key="save_project_json_path"'))
        self.assertEqual(1, self.app_source.count('key="save_project_as_json_button"'))
        self.assertEqual(
            1,
            self.app_source.count(
                'key="project_save_as_confirm_overwrite_button"'
            ),
        )

    def test_existing_recent_and_json_open_state_contracts_are_preserved(self):
        self.assertIn("recent_projects = get_recent_projects(st.session_state.settings)", self.app_source)
        self.assertIn(
            "project_file_default = current_project_path or last_project_path or \"project.json\"",
            self.app_source,
        )
        self.assertEqual(1, self.app_source.count('key="open_project_path"'))

    def test_effective_project_root_browser_does_not_add_native_picker(self):
        combined_source = self.app_source[self.project_open_start:self.next_section]
        self.assertIn("render_project_directory_browser()", combined_source)
        self.assertNotIn("folder_picker", combined_source)
        self.assertNotIn("directory_picker", combined_source)


if __name__ == "__main__":
    unittest.main()
