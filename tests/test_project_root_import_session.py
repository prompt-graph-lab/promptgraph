"""Characterize import drafts independently of rendering and disk operations."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ui import project_root_import_session as session


class ImportSessionTests(unittest.TestCase):
    def setUp(self):
        self.preview = {}
        self.result = {}
        self.state = {
            session.PROJECT_ROOT_IMPORT_PREVIEW_KEY: self.preview,
            session.PROJECT_ROOT_IMPORT_RESULT_KEY: self.result,
            session.PROJECT_ROOT_IMPORT_SOURCE_KEY: "original.json",
            session.PROJECT_ROOT_IMPORT_NAME_KEY: "old name",
            session.PROJECT_ROOT_IMPORT_CONFIRM_KEY: True,
            session.PROJECT_ROOT_IMPORT_PHRASE_KEY: "COPY PROJECT",
            "unrelated": self.preview,
        }
        replacement = patch.object(session, "st", SimpleNamespace(session_state=self.state))
        replacement.start()
        self.addCleanup(replacement.stop)

    def test_reset_defers_widget_changes_and_retains_result_identity(self):
        session.reset_project_root_import_operation_state(keep_result=True)
        self.assertNotIn(session.PROJECT_ROOT_IMPORT_PREVIEW_KEY, self.state)
        self.assertIs(self.state[session.PROJECT_ROOT_IMPORT_RESULT_KEY], self.result)
        self.assertTrue(self.state[session.PROJECT_ROOT_IMPORT_CONFIRM_KEY])
        session.consume_project_root_import_confirmation_reset()
        self.assertNotIn(session.PROJECT_ROOT_IMPORT_CONFIRM_KEY, self.state)
        self.assertNotIn(session.PROJECT_ROOT_IMPORT_PHRASE_KEY, self.state)
        self.assertNotIn(session.PROJECT_ROOT_IMPORT_CONFIRM_RESET_PENDING_KEY, self.state)
        self.assertEqual(self.state[session.PROJECT_ROOT_IMPORT_SOURCE_KEY], "original.json")
        self.assertEqual(self.state[session.PROJECT_ROOT_IMPORT_NAME_KEY], "old name")
        self.assertIs(self.state["unrelated"], self.preview)
        session.consume_project_root_import_confirmation_reset()

    def test_falsey_pending_is_consumed_without_clearing_widgets(self):
        self.state[session.PROJECT_ROOT_IMPORT_CONFIRM_RESET_PENDING_KEY] = ""
        session.consume_project_root_import_confirmation_reset()
        self.assertNotIn(session.PROJECT_ROOT_IMPORT_CONFIRM_RESET_PENDING_KEY, self.state)
        self.assertTrue(self.state[session.PROJECT_ROOT_IMPORT_CONFIRM_KEY])

    def test_confirmation_request_preserves_preview_and_result(self):
        session._reset_project_root_import_confirmation()
        self.assertIs(self.state[session.PROJECT_ROOT_IMPORT_PREVIEW_KEY], self.preview)
        self.assertIs(self.state[session.PROJECT_ROOT_IMPORT_RESULT_KEY], self.result)
        session._invalidate_project_root_import_preview()
        self.assertNotIn(session.PROJECT_ROOT_IMPORT_RESULT_KEY, self.state)
        self.assertNotIn(session.PROJECT_ROOT_IMPORT_PREVIEW_KEY, self.state)

    def test_source_selection_normalizes_before_naming_and_invalidation(self):
        with patch.object(session, "normalize_project_import_path", return_value="parent/project.json") as normalize:
            with patch.object(session, "sanitize_project_import_name", return_value="new name") as sanitize:
                session._select_project_root_import_source(" raw ")
        normalize.assert_called_once_with(" raw ")
        sanitize.assert_called_once_with("parent")
        self.assertEqual(self.state[session.PROJECT_ROOT_IMPORT_SOURCE_KEY], "parent/project.json")
        self.assertEqual(self.state[session.PROJECT_ROOT_IMPORT_NAME_KEY], "new name")
        self.assertNotIn(session.PROJECT_ROOT_IMPORT_PREVIEW_KEY, self.state)
        self.assertTrue(self.state[session.PROJECT_ROOT_IMPORT_CONFIRM_KEY])

    def test_empty_selected_name_preserves_old_draft(self):
        with patch.object(session, "normalize_project_import_path", return_value=""):
            with patch.object(session, "sanitize_project_import_name", return_value=""):
                session._select_project_root_import_source("")
        self.assertEqual(self.state[session.PROJECT_ROOT_IMPORT_SOURCE_KEY], "")
        self.assertEqual(self.state[session.PROJECT_ROOT_IMPORT_NAME_KEY], "old name")

    def test_naming_failure_leaves_source_written_and_preview_intact(self):
        with patch.object(session, "normalize_project_import_path", return_value="new.json"):
            with patch.object(session, "sanitize_project_import_name", side_effect=ValueError("name")):
                with self.assertRaisesRegex(ValueError, "name"):
                    session._select_project_root_import_source("raw")
        self.assertEqual(self.state[session.PROJECT_ROOT_IMPORT_SOURCE_KEY], "new.json")
        self.assertIs(self.state[session.PROJECT_ROOT_IMPORT_PREVIEW_KEY], self.preview)
        self.assertNotIn(session.PROJECT_ROOT_IMPORT_CONFIRM_RESET_PENDING_KEY, self.state)

    def test_name_initialization_is_missing_only_and_lazy(self):
        for existing in ("", None, False, "draft"):
            self.state[session.PROJECT_ROOT_IMPORT_NAME_KEY] = existing
            with patch.object(session, "sanitize_project_import_name", side_effect=AssertionError):
                session.initialize_project_root_import_name(None)
            self.assertIs(self.state[session.PROJECT_ROOT_IMPORT_NAME_KEY], existing)
        self.state.pop(session.PROJECT_ROOT_IMPORT_NAME_KEY)
        with patch.object(session, "sanitize_project_import_name", return_value="") as sanitize:
            session.initialize_project_root_import_name("raw/project.json")
        sanitize.assert_called_once_with("raw")
        self.assertEqual(self.state[session.PROJECT_ROOT_IMPORT_NAME_KEY], "")
