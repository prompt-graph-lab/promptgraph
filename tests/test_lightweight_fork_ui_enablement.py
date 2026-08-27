import os
import unittest

from core.lightweight_fork import (
    ALL_SCOPE_CONFIRM_PHRASE,
    get_lightweight_fork_create_blockers,
)


def _preview(*, scope="selected_lines", materializable_count=1, signature="same"):
    return {
        "scope": scope,
        "materializable_count": materializable_count,
        "signature": {"value": signature},
    }


class LightweightForkUiEnablementTests(unittest.TestCase):
    def _blockers(self, **overrides):
        preview = _preview()
        values = {
            "fork_name": "reviewed_fork",
            "source_project_saved": True,
            "stored_preview": preview,
            "current_preview": preview,
            "preview_project_path": "C:/projects/source/project.json",
            "current_project_path": "C:/projects/source/project.json",
            "confirmation_checked": True,
            "all_scope_phrase": "",
            "destination_conflict": False,
            "validation": {"valid": True},
            "materialization_running": False,
        }
        values.update(overrides)
        return get_lightweight_fork_create_blockers(**values)

    def test_preview_and_confirmation_are_required(self):
        blockers = self._blockers(stored_preview=None, current_preview=None, confirmation_checked=False)
        self.assertIn("no preview", blockers)
        self.assertIn("confirmation required", blockers)

    def test_stale_preview_is_disabled(self):
        current = _preview(signature="changed")
        blockers = self._blockers(current_preview=current)
        self.assertIn("preview is stale", blockers)

    def test_materializable_targets_are_required(self):
        preview = _preview(materializable_count=0)
        blockers = self._blockers(stored_preview=preview, current_preview=preview)
        self.assertIn("no materializable lines", blockers)

    def test_saved_source_and_destination_are_required(self):
        blockers = self._blockers(source_project_saved=False, destination_conflict=True)
        self.assertIn("source project is not saved", blockers)
        self.assertIn("destination already exists", blockers)

    def test_fork_name_is_required(self):
        blockers = self._blockers(fork_name="")
        self.assertIn("fork name is required", blockers)

    def test_selected_scopes_do_not_require_phrase(self):
        for scope in ("selected_lines", "current_route", "selected_route", "selected_routes"):
            preview = _preview(scope=scope)
            blockers = self._blockers(stored_preview=preview, current_preview=preview)
            self.assertNotIn("FORK FINAL phrase mismatch", blockers)
            self.assertEqual([], blockers)

    def test_all_scope_requires_exact_phrase(self):
        preview = _preview(scope="all_lines")
        for phrase in ("", "fork final", "FORK  FINAL", "FORK FINAL ", "FORK-FINAL"):
            blockers = self._blockers(
                stored_preview=preview,
                current_preview=preview,
                all_scope_phrase=phrase,
            )
            self.assertIn("FORK FINAL phrase mismatch", blockers)

        blockers = self._blockers(
            stored_preview=preview,
            current_preview=preview,
            all_scope_phrase=ALL_SCOPE_CONFIRM_PHRASE,
        )
        self.assertEqual([], blockers)

    def test_running_materialization_is_disabled(self):
        blockers = self._blockers(materialization_running=True)
        self.assertIn("materialization running", blockers)

    def test_validation_failure_is_disabled(self):
        blockers = self._blockers(validation={"valid": False, "error": "source image missing"})
        self.assertIn("core validation failed", blockers)

    def test_app_uses_gated_apply_and_explicit_open_action(self):
        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        with open(app_path, "r", encoding="utf-8") as handle:
            app_source = handle.read()
        self.assertIn('"派生Projectを作成"', app_source)
        self.assertIn("disabled=bool(blockers)", app_source)
        self.assertIn("stored_preview=preview", app_source)
        self.assertIn("current_preview=current_preview", app_source)
        self.assertIn("I reviewed the final image sequence", app_source)
        self.assertIn("FORK FINAL", app_source)
        self.assertIn("作成した派生Projectを開く", app_source)
        self.assertNotIn("派生Projectを作成 (future)", app_source)

    def test_selected_routes_uses_gallery_session_selection(self):
        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        with open(app_path, "r", encoding="utf-8") as handle:
            app_source = handle.read()
        self.assertIn('"selected_routes"', app_source)
        self.assertIn("resolve_selected_routes_fork_plan", app_source)
        self.assertIn('st.session_state.get("gallery_selected_route_ids", [])', app_source)
        self.assertIn('selected_route_ids=selected_route_ids', app_source)


if __name__ == "__main__":
    unittest.main()
