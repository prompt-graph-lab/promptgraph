import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class ProjectAssetsCleanupUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_path = Path(__file__).resolve().parents[1] / "app.py"
        cls.source = cls.app_path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, ast.FunctionDef)
        }

    def _source(self, function_name):
        return ast.get_source_segment(
            self.source,
            self.functions[function_name],
        )

    def _renderer_harness(self):
        class FakeColumn:
            def metric(self, *args, **kwargs):
                return None

        class FakeStreamlit:
            def __init__(self):
                self.session_state = {}
                self.clicked_keys = set()
                self.rerun_called = False

            def divider(self):
                return None

            def markdown(self, *args, **kwargs):
                return None

            def caption(self, *args, **kwargs):
                return None

            def warning(self, *args, **kwargs):
                return None

            def success(self, *args, **kwargs):
                return None

            def error(self, *args, **kwargs):
                return None

            def info(self, *args, **kwargs):
                return None

            def metric(self, *args, **kwargs):
                return None

            def dataframe(self, *args, **kwargs):
                return None

            def columns(self, count):
                return [FakeColumn() for _ in range(count)]

            def button(self, *args, disabled=False, key=None, **kwargs):
                clicked = key in self.clicked_keys and not disabled
                self.clicked_keys.discard(key)
                return clicked

            def checkbox(self, *args, key=None, **kwargs):
                return bool(self.session_state.get(key, False))

            def text_input(self, *args, key=None, **kwargs):
                return str(self.session_state.get(key, ""))

            def rerun(self):
                self.rerun_called = True

        fake_st = FakeStreamlit()
        preview_helper = mock.Mock()
        delete_helper = mock.Mock()
        stale_error = type(
            "ProjectAssetsPreviewStaleError",
            (Exception,),
            {},
        )
        constants = {
            node.targets[0].id: node.value.value
            for node in self.tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.startswith(
                "PROJECT_ASSETS_CLEANUP_"
            )
            and isinstance(node.value, ast.Constant)
        }
        namespace = {
            "st": fake_st,
            "os": os,
            "preview_verified_project_asset_duplicate_cleanup": (
                preview_helper
            ),
            "delete_verified_project_asset_source_duplicates": (
                delete_helper
            ),
            "ProjectAssetsPreviewStaleError": stale_error,
            "_format_project_assets_bytes": lambda value: f"{value} B",
            "_project_assets_cleanup_preview_rows": lambda preview: [],
            **constants,
        }
        exec(
            self._source(
                "reset_project_assets_cleanup_operation_state"
            ),
            namespace,
        )
        exec(
            self._source(
                "render_verified_project_asset_duplicate_cleanup"
            ),
            namespace,
        )
        return (
            namespace[
                "render_verified_project_asset_duplicate_cleanup"
            ],
            fake_st,
            preview_helper,
            delete_helper,
            stale_error,
            constants,
        )

    def test_cleanup_renderer_has_one_sidebar_owner(self):
        calls = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id
            == "render_verified_project_asset_duplicate_cleanup"
        ]
        self.assertEqual(len(calls), 1)
        sidebar = self._source("render_project_assets_sidebar_section")
        workspace = self._source("render_project_management_workspace")
        self.assertIn(
            "render_verified_project_asset_duplicate_cleanup(",
            sidebar,
        )
        self.assertNotIn(
            "render_verified_project_asset_duplicate_cleanup(",
            workspace,
        )

    def test_cleanup_ui_is_independent_from_existing_copy_controls(self):
        sidebar = self._source("render_project_assets_sidebar_section")
        cleanup_call = sidebar.index(
            "render_verified_project_asset_duplicate_cleanup("
        )
        copy_button = sidebar.index('"確認してProjectへ取り込む"')
        self.assertLess(copy_button, cleanup_call)
        self.assertEqual(
            sidebar.count("_copy_project_assets_and_save_with_session_rollback("),
            1,
        )
        self.assertEqual(
            sidebar.count(
                "render_verified_project_asset_duplicate_cleanup("
            ),
            1,
        )

    def test_cleanup_labels_and_safety_contract_are_explicit(self):
        renderer = self._source(
            "render_verified_project_asset_duplicate_cleanup"
        )
        for expected in (
            "Verified Duplicate Cleanup / 検証済み重複整理",
            "一般的な未参照ファイル削除ではありません",
            "candidates/側の保全コピーは削除しません",
            "Scan duplicate cleanup candidates",
            "Reclaimable size",
            "DELETE VERIFIED DUPLICATES",
            "Delete verified source duplicates",
            "PromptGraphから復元できません",
            "Project JSON unchanged / candidates/ unchanged",
        ):
            self.assertIn(expected, renderer)

    def test_preview_runs_only_in_explicit_scan_branch(self):
        renderer = self._source(
            "render_verified_project_asset_duplicate_cleanup"
        )
        self.assertEqual(
            renderer.count(
                "delete_verified_project_asset_source_duplicates("
            ),
            1,
        )
        self.assertEqual(
            renderer.count(
                "preview_verified_project_asset_duplicate_cleanup("
            ),
            1,
        )
        scan_branch = renderer[
            renderer.index('if st.button(\n        "Scan duplicate'):
            renderer.index(
                "preview = st.session_state.get("
                "PROJECT_ASSETS_CLEANUP_PREVIEW_KEY"
            )
        ]
        passive_render = renderer[
            renderer.index(
                "preview = st.session_state.get("
                "PROJECT_ASSETS_CLEANUP_PREVIEW_KEY"
            ):
            renderer.index('if st.button(\n        "Delete verified')
        ]
        apply_branch = renderer[
            renderer.index('if st.button(\n        "Delete verified'):
        ]
        self.assertEqual(
            scan_branch.count(
                "preview_verified_project_asset_duplicate_cleanup("
            ),
            1,
        )
        self.assertNotIn(
            "preview_verified_project_asset_duplicate_cleanup(",
            passive_render,
        )
        self.assertNotIn(
            "preview_verified_project_asset_duplicate_cleanup(",
            apply_branch,
        )
        self.assertIn(
            "delete_verified_project_asset_source_duplicates(",
            apply_branch,
        )
        for forbidden in (
            "os.remove(",
            "os.walk(",
            "_enumerate_cleanup_images(",
            "_cleanup_file_snapshot(",
            "hashlib.sha256(",
            "save_project_to_json(",
            "push_history(",
            "project.__dict__",
        ):
            self.assertNotIn(forbidden, renderer)

    def test_apply_requires_eligible_checkbox_and_exact_phrase(self):
        renderer = self._source(
            "render_verified_project_asset_duplicate_cleanup"
        )
        apply_disabled = renderer[
            renderer.index("apply_disabled = ("):
            renderer.index('if st.button(\n        "Delete verified')
        ]
        for required in (
            "cleanup_disabled",
            'preview.get("eligible_count")',
            "confirmed",
            'phrase != "DELETE VERIFIED DUPLICATES"',
        ):
            self.assertIn(required, apply_disabled)
        self.assertNotIn("preview_stale", apply_disabled)

    def test_explicit_scan_calls_preview_once_without_passive_rescan(self):
        (
            render,
            fake_st,
            preview_helper,
            _delete_helper,
            _stale_error,
            constants,
        ) = self._renderer_harness()
        stored_preview = {
            "valid": True,
            "signature": "scan-signature",
            "eligible_count": 1,
            "eligible_bytes": 10,
        }
        preview_helper.return_value = stored_preview
        fake_st.clicked_keys.add("project_assets_cleanup_scan")

        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "project.json"
            project_path.write_text("{}", encoding="utf-8")
            render(object(), str(project_path))

        preview_helper.assert_called_once()
        self.assertIs(
            fake_st.session_state[
                constants["PROJECT_ASSETS_CLEANUP_PREVIEW_KEY"]
            ],
            stored_preview,
        )

    def test_passive_confirmation_renders_are_lightweight_and_stale_apply_clears_preview(
        self,
    ):
        (
            render,
            fake_st,
            preview_helper,
            delete_helper,
            stale_error,
            constants,
        ) = self._renderer_harness()
        preview_key = constants["PROJECT_ASSETS_CLEANUP_PREVIEW_KEY"]
        confirm_key = constants["PROJECT_ASSETS_CLEANUP_CONFIRM_KEY"]
        phrase_key = constants["PROJECT_ASSETS_CLEANUP_PHRASE_KEY"]
        result_key = constants["PROJECT_ASSETS_CLEANUP_RESULT_KEY"]
        fake_st.session_state[preview_key] = {
            "valid": True,
            "signature": "stored-signature",
            "eligible_count": 1,
            "eligible_bytes": 10,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "project.json"
            project_path.write_text("{}", encoding="utf-8")
            project = object()

            render(project, str(project_path))
            preview_helper.assert_not_called()
            delete_helper.assert_not_called()

            fake_st.session_state[confirm_key] = True
            render(project, str(project_path))
            preview_helper.assert_not_called()
            delete_helper.assert_not_called()

            fake_st.session_state[phrase_key] = (
                "DELETE VERIFIED DUPLICATES"
            )
            render(project, str(project_path))
            preview_helper.assert_not_called()
            delete_helper.assert_not_called()

            delete_helper.side_effect = stale_error("stale preview")
            fake_st.clicked_keys.add("project_assets_cleanup_apply")
            render(project, str(project_path))

        preview_helper.assert_not_called()
        delete_helper.assert_called_once()
        self.assertNotIn(preview_key, fake_st.session_state)
        self.assertEqual(
            fake_st.session_state[result_key]["status"],
            "stale",
        )
        self.assertEqual(
            fake_st.session_state[result_key]["deleted_count"],
            0,
        )
        self.assertTrue(fake_st.rerun_called)

    def test_cleanup_widget_keys_are_unique_and_separate(self):
        expected_keys = (
            "project_assets_cleanup_preview",
            "project_assets_cleanup_confirm",
            "project_assets_cleanup_phrase",
            "project_assets_cleanup_result",
            "project_assets_cleanup_scan_running",
            "project_assets_cleanup_apply_running",
        )
        for key in expected_keys:
            self.assertEqual(
                self.source.count(f'"{key}"'),
                1,
                key,
            )
        self.assertNotEqual(
            "project_assets_cleanup_confirm",
            "project_assets_confirm",
        )

    def test_project_transitions_and_copy_apply_clear_cleanup_preview(self):
        reset_all = self._source("reset_project_assets_operation_state")
        reset_cleanup = self._source(
            "reset_project_assets_cleanup_operation_state"
        )
        sidebar = self._source("render_project_assets_sidebar_section")
        self.assertIn(
            "reset_project_assets_cleanup_operation_state()",
            reset_all,
        )
        self.assertIn(
            "PROJECT_ASSETS_CLEANUP_PREVIEW_KEY",
            reset_cleanup,
        )
        self.assertIn(
            "reset_project_assets_cleanup_operation_state()",
            sidebar,
        )
        for project_transition in (
            "load_project_json_into_session",
            "set_new_workspace_project",
            "render_prompt_import_export_panel",
        ):
            self.assertIn(
                "reset_project_assets_operation_state()",
                self._source(project_transition),
            )

    def test_mode_routing_does_not_reset_cleanup_state(self):
        mode_routing = self.source[
            self.source.index(
                "production_mode_context = get_production_mode_context"
            ):
        ]
        self.assertNotIn(
            "reset_project_assets_cleanup_operation_state()",
            mode_routing,
        )


if __name__ == "__main__":
    unittest.main()
