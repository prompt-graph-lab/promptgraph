"""Advanced Project Save As confirmation and successful transition lifecycle."""

from datetime import datetime

import streamlit as st

from core.io import save_project_to_json
from core.project_discovery import path_is_within as project_discovery_path_is_within
from core.project_save_as_safety import (
    build_project_save_as_pending_overwrite,
    inspect_project_save_as_destination,
    project_save_as_confirmation_is_fresh,
)
from core.settings import remember_project, save_settings


PROJECT_SAVE_AS_PENDING_OVERWRITE_KEY = "project_save_as_pending_overwrite"
PROJECT_SAVE_AS_OVERWRITE_ACK_KEY = "project_save_as_overwrite_acknowledged"
PROJECT_SAVE_AS_OVERWRITE_ACK_WIDGET_KEY = (
    "_project_save_as_overwrite_acknowledged_widget"
)
PROJECT_SAVE_AS_OVERWRITE_ACK_RESET_PENDING_KEY = (
    "project_save_as_overwrite_ack_reset_pending"
)
PROJECT_SAVE_AS_FEEDBACK_KEY = "project_save_as_feedback"


def arm_project_save_as_overwrite(target_snapshot: dict) -> None:
    """Store one occupied target snapshot for a separate confirmation action."""

    st.session_state[PROJECT_SAVE_AS_PENDING_OVERWRITE_KEY] = (
        build_project_save_as_pending_overwrite(
            target_snapshot,
            st.session_state.get("current_project_path", ""),
            st.session_state.get("project"),
        )
    )
    st.session_state[PROJECT_SAVE_AS_OVERWRITE_ACK_KEY] = False
    st.session_state[PROJECT_SAVE_AS_OVERWRITE_ACK_RESET_PENDING_KEY] = True
    st.session_state.pop(PROJECT_SAVE_AS_FEEDBACK_KEY, None)


def clear_project_save_as_confirmation(*, clear_feedback: bool = False) -> None:
    """Clear durable confirmation and schedule safe widget reconstruction."""

    st.session_state.pop(PROJECT_SAVE_AS_PENDING_OVERWRITE_KEY, None)
    st.session_state.pop(PROJECT_SAVE_AS_OVERWRITE_ACK_KEY, None)
    st.session_state[PROJECT_SAVE_AS_OVERWRITE_ACK_RESET_PENDING_KEY] = True
    if clear_feedback:
        st.session_state.pop(PROJECT_SAVE_AS_FEEDBACK_KEY, None)


def reset_project_save_as_confirmation_state() -> None:
    """Clear Save As confirmation after a successful Project transition."""

    clear_project_save_as_confirmation(clear_feedback=True)


def invalidate_project_save_as_confirmation_for_path_change() -> None:
    """Invalidate an armed target without mutating the path widget itself."""

    if st.session_state.get(PROJECT_SAVE_AS_PENDING_OVERWRITE_KEY):
        clear_project_save_as_confirmation(clear_feedback=False)
        st.session_state[PROJECT_SAVE_AS_FEEDBACK_KEY] = (
            "warning",
            "上書き対象が確認後に変更されました。保存先を再確認してください。",
        )


def sync_project_save_as_overwrite_acknowledgment() -> None:
    st.session_state[PROJECT_SAVE_AS_OVERWRITE_ACK_KEY] = bool(
        st.session_state.get(
            PROJECT_SAVE_AS_OVERWRITE_ACK_WIDGET_KEY,
            False,
        )
    )


def _commit_project_save_as(
    normalized_path: str,
    *,
    target_existed: bool,
    ensure_current_project_folder_layout,
    reset_project_assets_operation_state,
    default_projects_dir,
    request_project_directory_discovery_refresh,
) -> None:
    """Publish the existing Save As transition after the atomic writer returns."""

    save_project_to_json(st.session_state.project, normalized_path)
    st.session_state.current_project_path = normalized_path
    ensure_current_project_folder_layout(normalized_path)
    st.session_state.last_saved_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    st.session_state.autosave_feedback = "manual save"
    st.session_state.settings = remember_project(
        st.session_state.settings,
        normalized_path,
    )
    save_settings(st.session_state.settings)
    reset_project_assets_operation_state()
    if (
        not target_existed
        and project_discovery_path_is_within(
            normalized_path,
            default_projects_dir(),
        )
    ):
        request_project_directory_discovery_refresh()
    clear_project_save_as_confirmation(clear_feedback=False)
    st.session_state[PROJECT_SAVE_AS_FEEDBACK_KEY] = (
        "success",
        "プロジェクトを保存しました。",
    )


def save_project_as_requested(
    json_path,
    *,
    ensure_current_project_folder_layout,
    reset_project_assets_operation_state,
    default_projects_dir,
    request_project_directory_discovery_refresh,
) -> None:
    """Inspect the destination again before a one-click save or confirmation."""

    try:
        target_snapshot = inspect_project_save_as_destination(json_path)
    except (OSError, TypeError, ValueError) as exc:
        clear_project_save_as_confirmation(clear_feedback=False)
        st.session_state[PROJECT_SAVE_AS_FEEDBACK_KEY] = (
            "error",
            str(exc),
        )
    else:
        if target_snapshot.get("kind") == "file":
            arm_project_save_as_overwrite(target_snapshot)
        elif target_snapshot.get("kind") == "missing":
            try:
                fresh_snapshot = inspect_project_save_as_destination(
                    target_snapshot["normalized_path"]
                )
                if fresh_snapshot.get("kind") == "file":
                    arm_project_save_as_overwrite(fresh_snapshot)
                elif fresh_snapshot.get("kind") != "missing":
                    raise ValueError(
                        "Project JSONの保存先は通常ファイルではありません。"
                    )
                else:
                    _commit_project_save_as(
                        fresh_snapshot["normalized_path"],
                        target_existed=False,
                        ensure_current_project_folder_layout=ensure_current_project_folder_layout,
                        reset_project_assets_operation_state=reset_project_assets_operation_state,
                        default_projects_dir=default_projects_dir,
                        request_project_directory_discovery_refresh=request_project_directory_discovery_refresh,
                    )
            except Exception as exc:
                clear_project_save_as_confirmation(clear_feedback=False)
                st.session_state[PROJECT_SAVE_AS_FEEDBACK_KEY] = (
                    "error",
                    f"Project JSONを保存できませんでした: {exc}",
                )
        else:
            clear_project_save_as_confirmation(clear_feedback=False)
            st.session_state[PROJECT_SAVE_AS_FEEDBACK_KEY] = (
                "error",
                "Project JSONの保存先は通常ファイルではありません。",
            )


def confirm_project_save_as_overwrite(
    *,
    ensure_current_project_folder_layout,
    reset_project_assets_operation_state,
    default_projects_dir,
    request_project_directory_discovery_refresh,
) -> None:
    """Freshly validate and execute the armed destructive Save As action."""

    pending = st.session_state.get(PROJECT_SAVE_AS_PENDING_OVERWRITE_KEY)
    acknowledged = bool(
        st.session_state.get(PROJECT_SAVE_AS_OVERWRITE_ACK_KEY, False)
    )
    fresh, current_snapshot = project_save_as_confirmation_is_fresh(
        pending,
        st.session_state.get("save_project_json_path", ""),
        st.session_state.get("current_project_path", ""),
        st.session_state.get("project"),
    )
    if not acknowledged or not fresh:
        clear_project_save_as_confirmation(clear_feedback=False)
        st.session_state[PROJECT_SAVE_AS_FEEDBACK_KEY] = (
            "warning",
            "上書き対象が確認後に変更されました。保存先を再確認してください。",
        )
        return

    normalized_path = str(current_snapshot.get("normalized_path") or "")
    try:
        _commit_project_save_as(
            normalized_path,
            target_existed=True,
            ensure_current_project_folder_layout=ensure_current_project_folder_layout,
            reset_project_assets_operation_state=reset_project_assets_operation_state,
            default_projects_dir=default_projects_dir,
            request_project_directory_discovery_refresh=request_project_directory_discovery_refresh,
        )
    except Exception as exc:
        st.session_state.pop(PROJECT_SAVE_AS_OVERWRITE_ACK_KEY, None)
        st.session_state[
            PROJECT_SAVE_AS_OVERWRITE_ACK_RESET_PENDING_KEY
        ] = True
        st.session_state[PROJECT_SAVE_AS_FEEDBACK_KEY] = (
            "error",
            f"Project JSONを保存できませんでした: {exc}",
        )
