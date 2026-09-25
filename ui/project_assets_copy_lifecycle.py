"""Application session lifecycle for Project Assets Candidate/Variant copying."""

import copy
from datetime import datetime

from core.io import (
    ProjectAssetsPreviewStaleError,
    copy_candidates_to_project_and_save_atomically,
    preview_copy_candidates_to_project,
)


PROJECT_ASSETS_PREVIEW_KEY = "project_assets_preview"
PROJECT_ASSETS_CONFIRM_KEY = "project_assets_confirm"
PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY = "project_assets_confirm_reset_pending"
PROJECT_ASSETS_FEEDBACK_KEY = "project_assets_feedback"


def reset_project_assets_copy_operation_state(session_state) -> None:
    """Clear copy state when the active Project is replaced."""

    session_state.pop(PROJECT_ASSETS_PREVIEW_KEY, None)
    session_state.pop(PROJECT_ASSETS_FEEDBACK_KEY, None)
    session_state[PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY] = True


def consume_project_assets_copy_confirmation_reset(session_state) -> None:
    if session_state.pop(PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY, False):
        session_state[PROJECT_ASSETS_CONFIRM_KEY] = False


def store_project_assets_copy_preview(session_state, project, project_path) -> None:
    preview = preview_copy_candidates_to_project(project, project_path)
    session_state[PROJECT_ASSETS_PREVIEW_KEY] = preview
    session_state[PROJECT_ASSETS_CONFIRM_KEY] = False


def _sync_project_assets_candidate_session_state(
    session_state, project, line_candidate_key, get_persistent_line_candidates
) -> None:
    session_state.line_generated_candidates = {
        line_candidate_key(line): list(get_persistent_line_candidates(line))
        for line in getattr(project, "prompt_lines", [])
        if (
            getattr(line, "line_type", None) != "separator"
            and get_persistent_line_candidates(line)
        )
    }


def apply_project_assets_copy(
    session_state,
    project,
    project_path,
    preview,
    *,
    line_candidate_key,
    get_persistent_line_candidates,
    reset_project_assets_cleanup_operation_state,
):
    """Apply a confirmed copy, preserving both stale gates and publication order."""

    fresh_preview = preview_copy_candidates_to_project(project, project_path)
    if fresh_preview.get("signature") != preview.get("signature"):
        session_state[PROJECT_ASSETS_PREVIEW_KEY] = fresh_preview
        session_state[PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY] = True
        session_state[PROJECT_ASSETS_FEEDBACK_KEY] = {
            "kind": "warning",
            "message": (
                "対象参照またはfilesystemがPreview後に変わりました。"
                "Previewを更新したので、内容を確認して"
                "もう一度実行してください。"
            ),
        }
        return {"status": "stale"}

    previous_project = project.clone()
    previous_candidate_state = copy.deepcopy(
        session_state.get("line_generated_candidates", {})
    )
    try:
        summary = copy_candidates_to_project_and_save_atomically(
            project,
            project_path,
            expected_signature=preview.get("signature", ""),
        )
    except ProjectAssetsPreviewStaleError:
        session_state[PROJECT_ASSETS_PREVIEW_KEY] = (
            preview_copy_candidates_to_project(project, project_path)
        )
        session_state[PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY] = True
        session_state[PROJECT_ASSETS_FEEDBACK_KEY] = {
            "kind": "warning",
            "message": (
                "Previewが古くなりました。更新後の内容を確認して"
                "もう一度実行してください。"
            ),
        }
        return {"status": "stale"}
    except Exception as exc:
        session_state.project = previous_project
        session_state.line_generated_candidates = previous_candidate_state
        return {"status": "error", "error": exc}

    _sync_project_assets_candidate_session_state(
        session_state,
        project,
        line_candidate_key,
        get_persistent_line_candidates,
    )
    session_state.last_saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_state.autosave_feedback = "candidate assets copied"
    session_state.pop(PROJECT_ASSETS_PREVIEW_KEY, None)
    session_state[PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY] = True
    reset_project_assets_cleanup_operation_state()
    return {"status": "success", "summary": summary}
