"""Application session lifecycle for verified Project Asset duplicate cleanup."""

from core.io import (
    ProjectAssetsPreviewStaleError,
    delete_verified_project_asset_source_duplicates,
    preview_verified_project_asset_duplicate_cleanup,
)


PROJECT_ASSETS_CLEANUP_PREVIEW_KEY = "project_assets_cleanup_preview"
PROJECT_ASSETS_CLEANUP_CONFIRM_KEY = "project_assets_cleanup_confirm"
PROJECT_ASSETS_CLEANUP_PHRASE_KEY = "project_assets_cleanup_phrase"
PROJECT_ASSETS_CLEANUP_RESULT_KEY = "project_assets_cleanup_result"
PROJECT_ASSETS_CLEANUP_SCAN_RUNNING_KEY = "project_assets_cleanup_scan_running"
PROJECT_ASSETS_CLEANUP_APPLY_RUNNING_KEY = "project_assets_cleanup_apply_running"
PROJECT_ASSETS_CLEANUP_RESET_PENDING_KEY = "project_assets_cleanup_reset_pending"


def reset_project_assets_cleanup_operation_state(
    session_state, *, keep_result: bool = False
) -> None:
    """Clear Project-bound cleanup state and defer widget confirmation reset."""

    session_state.pop(PROJECT_ASSETS_CLEANUP_PREVIEW_KEY, None)
    if not keep_result:
        session_state.pop(PROJECT_ASSETS_CLEANUP_RESULT_KEY, None)
    session_state[PROJECT_ASSETS_CLEANUP_SCAN_RUNNING_KEY] = False
    session_state[PROJECT_ASSETS_CLEANUP_APPLY_RUNNING_KEY] = False
    session_state[PROJECT_ASSETS_CLEANUP_RESET_PENDING_KEY] = True


def consume_project_assets_cleanup_confirmation_reset(session_state) -> None:
    if session_state.pop(PROJECT_ASSETS_CLEANUP_RESET_PENDING_KEY, False):
        session_state[PROJECT_ASSETS_CLEANUP_CONFIRM_KEY] = False
        session_state[PROJECT_ASSETS_CLEANUP_PHRASE_KEY] = ""


def scan_project_assets_cleanup(session_state, project, project_path) -> None:
    """Store only an explicitly requested core Preview."""

    session_state[PROJECT_ASSETS_CLEANUP_SCAN_RUNNING_KEY] = True
    try:
        preview = preview_verified_project_asset_duplicate_cleanup(
            project, project_path
        )
        session_state[PROJECT_ASSETS_CLEANUP_PREVIEW_KEY] = preview
        session_state.pop(PROJECT_ASSETS_CLEANUP_RESULT_KEY, None)
        session_state[PROJECT_ASSETS_CLEANUP_CONFIRM_KEY] = False
        session_state[PROJECT_ASSETS_CLEANUP_PHRASE_KEY] = ""
    finally:
        session_state[PROJECT_ASSETS_CLEANUP_SCAN_RUNNING_KEY] = False


def apply_project_assets_cleanup(
    session_state, project, project_path, preview
) -> None:
    """Dispatch one core deletion and preserve its result for the next render."""

    session_state[PROJECT_ASSETS_CLEANUP_APPLY_RUNNING_KEY] = True
    try:
        cleanup_result = delete_verified_project_asset_source_duplicates(
            project, project_path, preview
        )
    except ProjectAssetsPreviewStaleError as exc:
        cleanup_result = {
            "status": "stale",
            "deleted_count": 0,
            "deleted_bytes": 0,
            "error": str(exc),
            "remaining_eligible_files": [],
        }
    except Exception as exc:
        cleanup_result = {
            "status": "validation_failure",
            "deleted_count": 0,
            "deleted_bytes": 0,
            "error": str(exc),
            "remaining_eligible_files": [],
        }
    finally:
        session_state[PROJECT_ASSETS_CLEANUP_APPLY_RUNNING_KEY] = False

    session_state[PROJECT_ASSETS_CLEANUP_RESULT_KEY] = cleanup_result
    reset_project_assets_cleanup_operation_state(session_state, keep_result=True)
