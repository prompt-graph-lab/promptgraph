"""Host publication lifecycle for cross-Project Scene Import."""

import os

from core.project import Project
from core.project_save_as_safety import normalize_project_save_as_path
from core.route_operations import get_route_move_ui_state
from core.scene_import import (
    SCENE_IMPORT_APPLY_CONTRACT_VERSION,
    SCENE_IMPORT_PREVIEW_CONTRACT_VERSION,
    SCENE_IMPORT_PREVIEW_OPERATION,
    apply_scene_import,
    preview_scene_import,
)


SCENE_IMPORT_SOURCE_PATH_KEY = "scene_import_source_path"
SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY = "scene_import_source_separator_id"
SCENE_IMPORT_PREVIEW_KEY = "scene_import_preview"
SCENE_IMPORT_APPLY_RESULT_KEY = "scene_import_apply_result"
SCENE_IMPORT_FEEDBACK_KEY = "scene_import_feedback"
UNDO_HISTORY_LIMIT = 20


def _raw_path(path) -> str:
    try:
        value = os.fspath(path)
    except (TypeError, ValueError):
        return ""
    return value.strip() if type(value) is str else ""


def _stored_path(path) -> str:
    raw_path = _raw_path(path)
    return normalize_project_save_as_path(raw_path) or raw_path


def _paths_match(path_a, path_b) -> bool:
    normalized_a = normalize_project_save_as_path(path_a)
    normalized_b = normalize_project_save_as_path(path_b)
    if normalized_a and normalized_b:
        return os.path.normcase(normalized_a) == os.path.normcase(normalized_b)
    return _raw_path(path_a) == _raw_path(path_b)


def invalidate_scene_import_preview(
    session_state,
    *,
    feedback_code: str | None = None,
    clear_apply_result: bool = False,
) -> None:
    """Disarm the one-shot Preview without disturbing unrelated session state."""

    session_state.pop(SCENE_IMPORT_PREVIEW_KEY, None)
    if clear_apply_result:
        session_state.pop(SCENE_IMPORT_APPLY_RESULT_KEY, None)
    if feedback_code:
        session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
            "kind": "warning",
            "code": feedback_code,
        }
    else:
        session_state.pop(SCENE_IMPORT_FEEDBACK_KEY, None)


def reset_scene_import_operation_state(session_state) -> None:
    """Clear Scene Import inputs and outcomes when the host resets the panel."""

    for key in (
        SCENE_IMPORT_SOURCE_PATH_KEY,
        SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY,
        SCENE_IMPORT_PREVIEW_KEY,
        SCENE_IMPORT_APPLY_RESULT_KEY,
        SCENE_IMPORT_FEEDBACK_KEY,
    ):
        session_state.pop(key, None)


def set_scene_import_source_path(session_state, source_path) -> bool:
    """Set the selected source path and invalidate Preview when it changes."""

    next_path = _stored_path(source_path)
    previous_path = session_state.get(SCENE_IMPORT_SOURCE_PATH_KEY, "")
    changed = not _paths_match(previous_path, next_path)
    if changed:
        invalidate_scene_import_preview(
            session_state,
            feedback_code="source_selection_changed",
            clear_apply_result=True,
        )
    session_state[SCENE_IMPORT_SOURCE_PATH_KEY] = next_path
    return changed


def set_scene_import_source_separator_id(session_state, separator_id) -> bool:
    """Set the explicit source Scene handle and invalidate its old Preview."""

    next_separator_id = separator_id.strip() if type(separator_id) is str else ""
    previous = session_state.get(SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY, "")
    previous_separator_id = previous.strip() if type(previous) is str else ""
    changed = previous_separator_id != next_separator_id
    if changed:
        invalidate_scene_import_preview(
            session_state,
            feedback_code="source_selection_changed",
            clear_apply_result=True,
        )
    session_state[SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY] = next_separator_id
    return changed


def _preview_failure(reason: str) -> dict:
    return {
        "contract_version": SCENE_IMPORT_PREVIEW_CONTRACT_VERSION,
        "operation": SCENE_IMPORT_PREVIEW_OPERATION,
        "valid": False,
        "eligible": False,
        "reason": reason,
        "blockers": [reason],
        "diagnostics": [{"code": reason}],
    }


def _set_preview_feedback(session_state, preview: dict) -> None:
    valid = type(preview.get("valid")) is bool and preview["valid"]
    eligible = type(preview.get("eligible")) is bool and preview["eligible"]
    session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
        "kind": "success" if valid and eligible else "warning",
        "code": "preview_ready" if valid and eligible else "preview_ineligible",
    }


def build_scene_import_preview_from_source(
    source_path,
    separator_id,
    *,
    session_state,
    load_project_from_json,
) -> dict:
    """Reload a source Project and store one complete, read-only Preview."""

    set_scene_import_source_path(session_state, source_path)
    set_scene_import_source_separator_id(session_state, separator_id)
    invalidate_scene_import_preview(session_state, clear_apply_result=True)

    normalized_source_path = normalize_project_save_as_path(source_path)
    if not normalized_source_path:
        result = _preview_failure("invalid_source_path")
        session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
            "kind": "error",
            "code": result["reason"],
        }
        return result

    target_project = session_state.get("project")
    if type(target_project) is not Project:
        result = _preview_failure("target_project_unavailable")
        session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
            "kind": "error",
            "code": result["reason"],
        }
        return result

    if _paths_match(normalized_source_path, session_state.get("current_project_path", "")):
        result = _preview_failure("same_project_path")
        session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
            "kind": "error",
            "code": result["reason"],
        }
        return result

    try:
        source_project = load_project_from_json(normalized_source_path)
    except Exception:
        result = _preview_failure("source_load_failed")
        session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
            "kind": "error",
            "code": result["reason"],
        }
        return result

    if type(source_project) is not Project:
        result = _preview_failure("source_project_unavailable")
        session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
            "kind": "error",
            "code": result["reason"],
        }
        return result

    try:
        preview = preview_scene_import(
            source_project,
            session_state.get(SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY, ""),
            target_project,
        )
    except Exception:
        result = _preview_failure("preview_failed")
        session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
            "kind": "error",
            "code": result["reason"],
        }
        return result

    if type(preview) is not dict:
        result = _preview_failure("preview_result_unavailable")
        session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
            "kind": "error",
            "code": result["reason"],
        }
        return result

    # Core Preview results, including ineligible conflicts, are retained intact
    # so a later UI can render the full review evidence.
    session_state[SCENE_IMPORT_PREVIEW_KEY] = preview
    _set_preview_feedback(session_state, preview)
    return preview


def _bounded_reason(value, fallback: str) -> str:
    if (
        type(value) is str
        and 0 < len(value) <= 80
        and all(char.isalnum() or char in "_-" for char in value)
    ):
        return value
    return fallback


def _host_apply_failure(reason: str, reviewed_preview=None) -> dict:
    result = {
        "contract_version": SCENE_IMPORT_APPLY_CONTRACT_VERSION,
        "operation": SCENE_IMPORT_PREVIEW_OPERATION,
        "applied": False,
        "reason": reason,
        "blockers": [reason],
        "diagnostics": [{"code": reason}],
    }
    if type(reviewed_preview) is dict:
        for source_key, result_key in (
            ("plan_id", "reviewed_plan_id"),
            ("projection_digest", "projection_digest"),
            ("source_scene_fingerprint", "source_scene_fingerprint"),
            ("target_freshness_fingerprint", "target_freshness_fingerprint"),
        ):
            value = reviewed_preview.get(source_key)
            if (
                type(value) is str
                and len(value) == 71
                and value.startswith("sha256:")
                and all(char in "0123456789abcdef" for char in value[7:])
            ):
                result[result_key] = value
    return result


def _publish_host_apply_failure(session_state, reason: str, reviewed_preview=None) -> dict:
    result = _host_apply_failure(reason, reviewed_preview)
    session_state[SCENE_IMPORT_APPLY_RESULT_KEY] = result
    invalidate_scene_import_preview(session_state)
    session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
        "kind": "error",
        "code": reason,
    }
    return result


def _clear_consumed_preview(session_state) -> None:
    session_state.pop(SCENE_IMPORT_PREVIEW_KEY, None)


def apply_and_publish_scene_import(
    source_path,
    separator_id,
    reviewed_preview,
    *,
    session_state,
    load_project_from_json,
    synchronize_selected_routes,
    restore_focus_after_graph_update,
    save_current_project_if_possible,
):
    """Reload, apply, and publish a stored Scene Import Preview once."""

    preview_in_state = session_state.get(SCENE_IMPORT_PREVIEW_KEY)
    had_preview = preview_in_state is not None
    path_changed = set_scene_import_source_path(session_state, source_path)
    separator_changed = set_scene_import_source_separator_id(
        session_state,
        separator_id,
    )
    if had_preview and (path_changed or separator_changed):
        return _publish_host_apply_failure(
            session_state,
            "source_selection_changed",
            preview_in_state,
        )
    if type(preview_in_state) is not dict:
        return _publish_host_apply_failure(
            session_state,
            "reviewed_preview_missing",
        )
    if reviewed_preview is not preview_in_state:
        return _publish_host_apply_failure(
            session_state,
            "reviewed_preview_session_mismatch",
            preview_in_state,
        )

    normalized_source_path = normalize_project_save_as_path(source_path)
    if not normalized_source_path:
        return _publish_host_apply_failure(
            session_state,
            "invalid_source_path",
            preview_in_state,
        )

    target_project = session_state.get("project")
    if type(target_project) is not Project:
        return _publish_host_apply_failure(
            session_state,
            "target_project_unavailable",
            preview_in_state,
        )
    if _paths_match(normalized_source_path, session_state.get("current_project_path", "")):
        return _publish_host_apply_failure(
            session_state,
            "same_project_path",
            preview_in_state,
        )

    history = session_state.get("history")
    if not isinstance(history, list):
        return _publish_host_apply_failure(
            session_state,
            "undo_history_unavailable",
            preview_in_state,
        )

    # Capture focus and Undo custody before Apply. The snapshot is published
    # only after the core operation succeeds.
    previous_focus = session_state.get("focused_line_id")
    previous_highlight = session_state.get("highlighted_line_id")
    previous_expanded = session_state.get("gallery_expanded_line_id")
    previous_selected_route = session_state.get(
        "gallery_selected_route_separator_id",
        "",
    )
    try:
        history_snapshot = target_project.clone()
        if type(history_snapshot) is not Project or history_snapshot is target_project:
            raise ValueError("invalid undo snapshot")
    except Exception:
        return _publish_host_apply_failure(
            session_state,
            "undo_snapshot_failed",
            preview_in_state,
        )

    try:
        source_project = load_project_from_json(normalized_source_path)
    except Exception:
        return _publish_host_apply_failure(
            session_state,
            "source_load_failed",
            preview_in_state,
        )
    if type(source_project) is not Project:
        return _publish_host_apply_failure(
            session_state,
            "source_project_unavailable",
            preview_in_state,
        )

    try:
        result = apply_scene_import(
            source_project,
            session_state.get(SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY, ""),
            target_project,
            reviewed_preview,
        )
    except Exception:
        # The core Apply has an atomic mutation contract. Do not publish the
        # speculative Undo snapshot or leak exception details into session state.
        return _publish_host_apply_failure(
            session_state,
            "core_apply_failed",
            preview_in_state,
        )

    if type(result) is not dict or type(result.get("applied")) is not bool:
        return _publish_host_apply_failure(
            session_state,
            "core_apply_result_invalid",
            preview_in_state,
        )
    if not result["applied"]:
        session_state[SCENE_IMPORT_APPLY_RESULT_KEY] = result
        _clear_consumed_preview(session_state)
        session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
            "kind": "error",
            "code": _bounded_reason(result.get("reason"), "core_apply_rejected"),
        }
        return result

    # Core Apply mutates this existing Project in place. Publish its prior
    # snapshot only now, with the ordinary bounded app history capacity.
    history.append(history_snapshot)
    while len(history) > UNDO_HISTORY_LIMIT:
        history.pop(0)

    synchronize_selected_routes(target_project)
    route_state = get_route_move_ui_state(
        target_project,
        route_handle=str(previous_selected_route or ""),
        focused_line_id=previous_focus,
        highlighted_line_id=previous_highlight,
        expanded_line_id=previous_expanded,
    )
    session_state.gallery_selected_route_separator_id = route_state[
        "gallery_selected_route_separator_id"
    ]
    session_state.focused_line_id = route_state["focused_line_id"]
    session_state.highlighted_line_id = route_state["highlighted_line_id"]
    session_state.gallery_expanded_line_id = route_state["gallery_expanded_line_id"]
    restore_focus_after_graph_update(previous_focus)

    session_state[SCENE_IMPORT_APPLY_RESULT_KEY] = result
    session_state[SCENE_IMPORT_FEEDBACK_KEY] = {
        "kind": "success",
        "code": "scene_import_applied",
    }
    _clear_consumed_preview(session_state)
    save_current_project_if_possible("Scene Import applied")
    return result
