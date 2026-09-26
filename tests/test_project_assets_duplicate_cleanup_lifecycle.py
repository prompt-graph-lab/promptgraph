import unittest
from unittest import mock

from core.io import ProjectAssetsPreviewStaleError
from ui import project_assets_duplicate_cleanup_lifecycle as lifecycle


class ProjectAssetsDuplicateCleanupLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.project = object()
        self.project_path = "project.json"
        self.preview = {"valid": True, "signature": "stored", "eligible_count": 1}
        self.history = ["existing"]
        self.session = {
            "project": self.project,
            "history": self.history,
            "line_generated_candidates": {"candidate": "unchanged"},
            lifecycle.PROJECT_ASSETS_CLEANUP_PREVIEW_KEY: self.preview,
            lifecycle.PROJECT_ASSETS_CLEANUP_CONFIRM_KEY: True,
            lifecycle.PROJECT_ASSETS_CLEANUP_PHRASE_KEY: "DELETE VERIFIED DUPLICATES",
        }

    def _assert_non_cleanup_state_unchanged(self):
        self.assertIs(self.session["project"], self.project)
        self.assertIs(self.session["history"], self.history)
        self.assertEqual(self.history, ["existing"])
        self.assertEqual(
            self.session["line_generated_candidates"],
            {"candidate": "unchanged"},
        )
        self.assertEqual(
            {key for key in self.session if not key.startswith("project_assets_cleanup_")},
            {"project", "history", "line_generated_candidates"},
        )

    def test_explicit_scan_stores_core_preview_and_resets_confirmation(self):
        fresh = {"valid": True, "signature": "fresh", "eligible_count": 2}
        self.session[lifecycle.PROJECT_ASSETS_CLEANUP_RESULT_KEY] = {"status": "stale"}

        def scan(project, project_path):
            self.assertIs(project, self.project)
            self.assertEqual(project_path, self.project_path)
            self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_SCAN_RUNNING_KEY])
            return fresh

        with mock.patch.object(
            lifecycle, "preview_verified_project_asset_duplicate_cleanup", side_effect=scan
        ) as core_scan, mock.patch.object(
            lifecycle, "delete_verified_project_asset_source_duplicates"
        ) as core_delete:
            lifecycle.scan_project_assets_cleanup(
                self.session, self.project, self.project_path
            )

        core_scan.assert_called_once_with(self.project, self.project_path)
        core_delete.assert_not_called()
        self.assertIs(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_PREVIEW_KEY], fresh)
        self.assertNotIn(lifecycle.PROJECT_ASSETS_CLEANUP_RESULT_KEY, self.session)
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_CONFIRM_KEY])
        self.assertEqual(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_PHRASE_KEY], "")
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_SCAN_RUNNING_KEY])
        self._assert_non_cleanup_state_unchanged()

    def test_scan_error_resets_running_without_changing_prior_confirmation(self):
        with mock.patch.object(
            lifecycle,
            "preview_verified_project_asset_duplicate_cleanup",
            side_effect=RuntimeError("scan failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "scan failed"):
                lifecycle.scan_project_assets_cleanup(
                    self.session, self.project, self.project_path
                )

        self.assertIs(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_PREVIEW_KEY], self.preview)
        self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_CONFIRM_KEY])
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_SCAN_RUNNING_KEY])
        self._assert_non_cleanup_state_unchanged()

    def test_success_dispatches_once_preserves_result_and_defers_confirmation_reset(self):
        result = {
            "status": "success",
            "deleted_count": 1,
            "deleted_bytes": 8,
            "retained_copy_count": 1,
        }

        def delete(project, project_path, preview):
            self.assertIs(project, self.project)
            self.assertEqual(project_path, self.project_path)
            self.assertIs(preview, self.preview)
            self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_APPLY_RUNNING_KEY])
            return result

        with mock.patch.object(
            lifecycle, "delete_verified_project_asset_source_duplicates", side_effect=delete
        ) as core_delete:
            lifecycle.apply_project_assets_cleanup(
                self.session, self.project, self.project_path, self.preview
            )

        core_delete.assert_called_once_with(self.project, self.project_path, self.preview)
        self.assertIs(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_RESULT_KEY], result)
        self.assertNotIn(lifecycle.PROJECT_ASSETS_CLEANUP_PREVIEW_KEY, self.session)
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_APPLY_RUNNING_KEY])
        self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_RESET_PENDING_KEY])
        self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_CONFIRM_KEY])
        lifecycle.consume_project_assets_cleanup_confirmation_reset(self.session)
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_CONFIRM_KEY])
        self.assertEqual(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_PHRASE_KEY], "")
        self.assertNotIn(lifecycle.PROJECT_ASSETS_CLEANUP_RESET_PENDING_KEY, self.session)
        self._assert_non_cleanup_state_unchanged()

    def test_pre_delete_stale_arms_rescan_without_retry(self):
        with mock.patch.object(
            lifecycle,
            "delete_verified_project_asset_source_duplicates",
            side_effect=ProjectAssetsPreviewStaleError("saved JSON changed"),
        ) as core_delete:
            lifecycle.apply_project_assets_cleanup(
                self.session, self.project, self.project_path, self.preview
            )

        core_delete.assert_called_once()
        self.assertEqual(
            self.session[lifecycle.PROJECT_ASSETS_CLEANUP_RESULT_KEY],
            {
                "status": "stale",
                "deleted_count": 0,
                "deleted_bytes": 0,
                "error": "saved JSON changed",
                "remaining_eligible_files": [],
            },
        )
        self.assertNotIn(lifecycle.PROJECT_ASSETS_CLEANUP_PREVIEW_KEY, self.session)
        self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_RESET_PENDING_KEY])
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_APPLY_RUNNING_KEY])
        self._assert_non_cleanup_state_unchanged()

    def test_partial_results_keep_core_details_without_retry_or_rollback(self):
        for status in ("partial_stale", "partial_failure"):
            with self.subTest(status=status):
                self.session[lifecycle.PROJECT_ASSETS_CLEANUP_PREVIEW_KEY] = self.preview
                result = {
                    "status": status,
                    "deleted_count": 1,
                    "deleted_bytes": 8,
                    "failed_file": "generated/second.png",
                    "error": "changed",
                    "remaining_eligible_files": ["generated/second.png"],
                }
                with mock.patch.object(
                    lifecycle,
                    "delete_verified_project_asset_source_duplicates",
                    return_value=result,
                ) as core_delete:
                    lifecycle.apply_project_assets_cleanup(
                        self.session, self.project, self.project_path, self.preview
                    )
                core_delete.assert_called_once()
                self.assertIs(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_RESULT_KEY], result)
                self.assertNotIn(lifecycle.PROJECT_ASSETS_CLEANUP_PREVIEW_KEY, self.session)
                self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_APPLY_RUNNING_KEY])
                self._assert_non_cleanup_state_unchanged()

    def test_validation_error_clears_running_and_preserves_error(self):
        with mock.patch.object(
            lifecycle,
            "delete_verified_project_asset_source_duplicates",
            side_effect=ValueError("invalid preview"),
        ) as core_delete:
            lifecycle.apply_project_assets_cleanup(
                self.session, self.project, self.project_path, self.preview
            )

        core_delete.assert_called_once()
        self.assertEqual(
            self.session[lifecycle.PROJECT_ASSETS_CLEANUP_RESULT_KEY]["status"],
            "validation_failure",
        )
        self.assertEqual(
            self.session[lifecycle.PROJECT_ASSETS_CLEANUP_RESULT_KEY]["error"],
            "invalid preview",
        )
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_APPLY_RUNNING_KEY])
        self._assert_non_cleanup_state_unchanged()

    def test_project_replacement_reset_clears_result_and_defers_widgets(self):
        self.session[lifecycle.PROJECT_ASSETS_CLEANUP_RESULT_KEY] = {"status": "success"}
        lifecycle.reset_project_assets_cleanup_operation_state(self.session)

        self.assertNotIn(lifecycle.PROJECT_ASSETS_CLEANUP_PREVIEW_KEY, self.session)
        self.assertNotIn(lifecycle.PROJECT_ASSETS_CLEANUP_RESULT_KEY, self.session)
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_SCAN_RUNNING_KEY])
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_APPLY_RUNNING_KEY])
        self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_RESET_PENDING_KEY])
        lifecycle.consume_project_assets_cleanup_confirmation_reset(self.session)
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_CONFIRM_KEY])
        self.assertEqual(self.session[lifecycle.PROJECT_ASSETS_CLEANUP_PHRASE_KEY], "")
        self._assert_non_cleanup_state_unchanged()


if __name__ == "__main__":
    unittest.main()
