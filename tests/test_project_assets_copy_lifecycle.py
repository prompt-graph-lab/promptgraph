import unittest
from unittest import mock

from core.io import ProjectAssetsPreviewStaleError
from core.project import Project, PromptLine
from ui import project_assets_copy_lifecycle as lifecycle


class _SessionState(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


def _line(line_id, *, candidates=None, variants=None, line_type="normal"):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.txt",
        original_index=0,
        current_index=0,
        original_text="prompt",
        current_text="prompt",
        tokens=["prompt"],
        line_type=line_type,
        generated_candidates=list(candidates or []),
        gallery_variants=list(variants or []),
    )


class ProjectAssetsCopyLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.project = Project(
            prompt_lines=[
                _line("candidate", candidates=[{"path": "old.png"}]),
                _line("variant-only", variants=[{"path": "variant.png"}]),
                _line(
                    "separator",
                    candidates=[{"path": "separator.png"}],
                    line_type="separator",
                ),
            ]
        )
        self.preview = {"signature": "confirmed", "planned_copy_count": 1}
        self.session = _SessionState(
            project=self.project,
            line_generated_candidates={"old": [{"path": "old.png"}]},
            project_assets_preview=self.preview,
            project_assets_confirm=True,
        )
        self.cleanup = mock.Mock()

    def _apply(self, *, candidate_getter=None):
        return lifecycle.apply_project_assets_copy(
            self.session,
            self.project,
            "project.json",
            self.preview,
            line_candidate_key=lambda line: str(line.id),
            get_persistent_line_candidates=(
                candidate_getter or (lambda line: line.generated_candidates)
            ),
            reset_project_assets_cleanup_operation_state=self.cleanup,
        )

    def test_success_uses_one_core_transaction_then_syncs_candidates_and_resets(self):
        events = []

        def preview(*_args):
            events.append("preview")
            return {"signature": "confirmed"}

        def transaction(project, _path, *, expected_signature):
            events.append("transaction")
            self.assertEqual(expected_signature, "confirmed")
            project.prompt_lines[0].generated_candidates = [{"path": "candidates/local.png"}]
            return {"copied": 1}

        def cleanup():
            events.append("cleanup")
            self.assertEqual(
                self.session.line_generated_candidates,
                {"candidate": [{"path": "candidates/local.png"}]},
            )
            self.assertIn("last_saved_at", self.session)
            self.assertEqual(self.session.autosave_feedback, "candidate assets copied")
            self.assertNotIn(lifecycle.PROJECT_ASSETS_PREVIEW_KEY, self.session)
            self.assertTrue(
                self.session[lifecycle.PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY]
            )

        def candidates(line):
            events.append("candidate")
            return line.generated_candidates

        self.cleanup.side_effect = cleanup
        with mock.patch.object(lifecycle, "preview_copy_candidates_to_project", side_effect=preview), mock.patch.object(
            lifecycle, "copy_candidates_to_project_and_save_atomically", side_effect=transaction
        ) as core_transaction:
            result = self._apply(candidate_getter=candidates)

        self.assertEqual(result, {"status": "success", "summary": {"copied": 1}})
        core_transaction.assert_called_once()
        self.assertEqual(
            events,
            ["preview", "transaction", "candidate", "candidate", "candidate", "cleanup"],
        )
        self.assertEqual(
            self.session.line_generated_candidates,
            {"candidate": [{"path": "candidates/local.png"}]},
        )
        self.assertIn("last_saved_at", self.session)
        self.assertEqual(self.session.autosave_feedback, "candidate assets copied")
        self.assertNotIn(lifecycle.PROJECT_ASSETS_PREVIEW_KEY, self.session)
        self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY])
        self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CONFIRM_KEY])

    def test_render_time_stale_refreshes_preview_without_core_or_project_mutation(self):
        fresh = {"signature": "changed"}
        with mock.patch.object(lifecycle, "preview_copy_candidates_to_project", return_value=fresh), mock.patch.object(
            lifecycle, "copy_candidates_to_project_and_save_atomically"
        ) as core_transaction:
            result = self._apply()

        self.assertEqual(result, {"status": "stale"})
        core_transaction.assert_not_called()
        self.assertIs(self.session.project, self.project)
        self.assertIs(self.session[lifecycle.PROJECT_ASSETS_PREVIEW_KEY], fresh)
        self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY])
        self.assertEqual(self.session[lifecycle.PROJECT_ASSETS_FEEDBACK_KEY]["kind"], "warning")
        self.assertNotIn("last_saved_at", self.session)
        self.cleanup.assert_not_called()

    def test_core_stale_refreshes_preview_without_session_rollback(self):
        fresh = {"signature": "changed-at-commit"}
        with mock.patch.object(
            lifecycle,
            "preview_copy_candidates_to_project",
            side_effect=[{"signature": "confirmed"}, fresh],
        ) as preview, mock.patch.object(
            lifecycle,
            "copy_candidates_to_project_and_save_atomically",
            side_effect=ProjectAssetsPreviewStaleError("changed"),
        ) as core_transaction:
            result = self._apply()

        self.assertEqual(result, {"status": "stale"})
        self.assertEqual(preview.call_count, 2)
        core_transaction.assert_called_once()
        self.assertIs(self.session.project, self.project)
        self.assertIs(self.session[lifecycle.PROJECT_ASSETS_PREVIEW_KEY], fresh)
        self.assertTrue(self.session[lifecycle.PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY])
        self.assertIn("Previewが古くなりました", self.session[lifecycle.PROJECT_ASSETS_FEEDBACK_KEY]["message"])
        self.cleanup.assert_not_called()

    def test_ordinary_transaction_exception_restores_session_without_success(self):
        old_candidates = self.session.line_generated_candidates

        def fail(_project, _path, *, expected_signature):
            self.assertEqual(expected_signature, "confirmed")
            self.session.project = object()
            self.session.line_generated_candidates = {"changed": True}
            raise OSError("save failed")

        with mock.patch.object(lifecycle, "preview_copy_candidates_to_project", return_value={"signature": "confirmed"}), mock.patch.object(
            lifecycle, "copy_candidates_to_project_and_save_atomically", side_effect=fail
        ):
            result = self._apply()

        self.assertEqual(result["status"], "error")
        self.assertIsInstance(result["error"], OSError)
        self.assertIsNot(self.session.project, self.project)
        self.assertEqual(self.session.project, self.project)
        self.assertEqual(self.session.line_generated_candidates, old_candidates)
        self.assertIsNot(self.session.line_generated_candidates, old_candidates)
        self.assertIs(self.session[lifecycle.PROJECT_ASSETS_PREVIEW_KEY], self.preview)
        self.assertNotIn("last_saved_at", self.session)
        self.assertNotIn("autosave_feedback", self.session)
        self.cleanup.assert_not_called()

    def test_publication_exception_keeps_core_success_and_partial_effects(self):
        def transaction(project, _path, *, expected_signature):
            self.assertEqual(expected_signature, "confirmed")
            project.prompt_lines[0].generated_candidates = [
                {"path": "candidates/local.png"}
            ]
            return {"copied": 1}

        def fail_sync(_line):
            raise RuntimeError("candidate sync failed")

        with mock.patch.object(
            lifecycle,
            "preview_copy_candidates_to_project",
            return_value={"signature": "confirmed"},
        ), mock.patch.object(
            lifecycle,
            "copy_candidates_to_project_and_save_atomically",
            side_effect=transaction,
        ):
            with self.assertRaisesRegex(RuntimeError, "candidate sync failed"):
                self._apply(candidate_getter=fail_sync)

        self.assertIs(self.session.project, self.project)
        self.assertEqual(
            self.project.prompt_lines[0].generated_candidates,
            [{"path": "candidates/local.png"}],
        )
        self.assertIs(self.session[lifecycle.PROJECT_ASSETS_PREVIEW_KEY], self.preview)
        self.assertNotIn("last_saved_at", self.session)
        self.cleanup.assert_not_called()

    def test_copy_preview_and_deferred_confirmation_reset(self):
        fresh = {"signature": "new"}
        with mock.patch.object(lifecycle, "preview_copy_candidates_to_project", return_value=fresh):
            lifecycle.store_project_assets_copy_preview(
                self.session, self.project, "project.json"
            )
        self.assertIs(self.session[lifecycle.PROJECT_ASSETS_PREVIEW_KEY], fresh)
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CONFIRM_KEY])

        self.session[lifecycle.PROJECT_ASSETS_CONFIRM_KEY] = True
        self.session[lifecycle.PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY] = True
        lifecycle.consume_project_assets_copy_confirmation_reset(self.session)
        self.assertFalse(self.session[lifecycle.PROJECT_ASSETS_CONFIRM_KEY])
        self.assertNotIn(lifecycle.PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY, self.session)
