"""Human-facing Gallery panel for cross-Project Scene Import."""

from __future__ import annotations

from typing import Any

import streamlit as st

from core.operations import get_gallery_route_options
from ui.scene_import_lifecycle import (
    SCENE_IMPORT_APPLY_RESULT_KEY,
    SCENE_IMPORT_FEEDBACK_KEY,
    SCENE_IMPORT_PREVIEW_KEY,
    SCENE_IMPORT_SOURCE_PATH_KEY,
    SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY,
    apply_and_publish_scene_import,
    build_scene_import_preview_from_source,
    reset_scene_import_operation_state,
    set_scene_import_source_path,
    set_scene_import_source_separator_id,
)


SCENE_IMPORT_SOURCE_PATH_WIDGET_KEY = "_scene_import_source_path_widget"
SCENE_IMPORT_SOURCE_SEPARATOR_WIDGET_KEY = "_scene_import_source_separator_widget"
SCENE_IMPORT_CONFIRM_WIDGET_KEY = "_scene_import_confirm_widget"

SCENE_IMPORT_OPERATION_KEY = "scene_import"
SCENE_IMPORT_OPERATION_LABEL = "Scene Import / シーンを取り込む"
SCENE_IMPORT_OPERATION_ACTION = (
    SCENE_IMPORT_OPERATION_KEY,
    SCENE_IMPORT_OPERATION_LABEL,
    "別のPromptGraph ProjectからSceneを1つ取り込みます。Promptと構造のみを移し、Source画像・Candidates・Variantsはコピーせず、現在のProject末尾へ追加します。",
)

_FEEDBACK_MESSAGES = {
    "preview_ready": "Fresh Previewを作成しました。内容を確認してください。",
    "preview_ineligible": "Previewに確認が必要です。Blockerを確認してください。",
    "source_selection_changed": "Sourceの選択が変わりました。Fresh Previewを作成してください。",
    "invalid_source_path": "Project JSONのパスを確認してください。",
    "target_project_unavailable": "現在のProjectを利用できません。",
    "same_project_path": "現在開いているProjectとは別のProjectを選択してください。",
    "source_load_failed": "Source Projectを読み込めませんでした。パスとJSONを確認してください。",
    "source_project_unavailable": "Source Projectを利用できません。",
    "preview_failed": "Scene Import Previewを作成できませんでした。入力を確認して再試行してください。",
    "preview_result_unavailable": "Scene Import Previewを利用できません。再試行してください。",
    "scene_import_applied": "Sceneを現在のProject末尾へ追加しました。",
    "reviewed_preview_missing": "確認済みPreviewがありません。Fresh Previewを作成してください。",
    "reviewed_preview_session_mismatch": "Previewの選択状態が変わりました。Fresh Previewを作成してください。",
    "source_now_invalid": "Source Sceneが変わりました。Fresh Previewを作成してください。",
    "target_now_invalid": "現在のProjectが変わりました。Fresh Previewを作成してください。",
    "reviewed_preview_stale": "Preview作成後にProjectの状態が変わりました。Fresh Previewを作成してください。",
    "core_apply_rejected": "Applyできませんでした。Fresh Previewを作成して確認し直してください。",
    "core_apply_failed": "Apply中にエラーが発生しました。Previewを作成し直してください。",
    "undo_snapshot_failed": "Undo用の状態を作成できませんでした。Applyは行われていません。",
    "undo_history_unavailable": "Undo履歴を利用できません。Applyは行われていません。",
}

_BLOCKER_MESSAGES = {
    "module_conflict": "同名のModule定義が異なります。Conflictはこの操作では適用できません。",
    "same_name_definition_differs": "同名Moduleのportable定義が異なります。",
    "malformed_target_module": "現在のProjectにある同名Module定義を読み取れません。",
    "stale_target_current_index": "現在のProjectの行順情報が一致しません。Projectを確認してPreviewを作り直してください。",
    "same_project": "同じProjectから同じProjectへのImportはできません。",
    "source_projection_invalid": "Source Sceneを安全に読み取れません。SceneとModule参照を確認してください。",
    "malformed_target_module_library": "現在のProjectのModule情報を読み取れません。",
    "target_id_allocation_failed": "新しいScene IDを安全に作成できませんでした。",
}


def reset_scene_import_panel_state(session_state) -> None:
    """Clear this operation's lifecycle and temporary widget state only."""

    reset_scene_import_operation_state(session_state)
    for key in (
        SCENE_IMPORT_SOURCE_PATH_WIDGET_KEY,
        SCENE_IMPORT_SOURCE_SEPARATOR_WIDGET_KEY,
        SCENE_IMPORT_CONFIRM_WIDGET_KEY,
    ):
        session_state.pop(key, None)


def _bounded_code(value: Any, *, fallback: str) -> str:
    if (
        type(value) is str
        and 0 < len(value) <= 80
        and all(char.isalnum() or char in "_-" for char in value)
    ):
        return value
    return fallback


def _bounded_name_list(value: Any) -> list[str] | None:
    if type(value) is not list:
        return None
    names = [
        name if len(name) <= 160 else name[:157] + "..."
        for name in value[:256]
        if type(name) is str
    ]
    if len(value) > 256:
        names.append(f"… ({len(value) - 256} more)")
    return names


def _sync_source_inputs(session_state, source_path: str, separator_id: str) -> bool:
    """Synchronize widget mirrors through the lifecycle invalidation owner."""

    path_changed = set_scene_import_source_path(session_state, source_path)
    if path_changed:
        # A Scene id is scoped to its source Project selection. Do not carry the
        # previous Project's separator into a newly selected JSON file.
        set_scene_import_source_separator_id(session_state, "")
        session_state[SCENE_IMPORT_SOURCE_SEPARATOR_WIDGET_KEY] = ""
        separator_id = ""
    separator_changed = set_scene_import_source_separator_id(
        session_state,
        separator_id,
    )
    if path_changed or separator_changed:
        session_state[SCENE_IMPORT_CONFIRM_WIDGET_KEY] = False
    return path_changed or separator_changed


def _discover_source_routes(
    source_path: str,
    *,
    load_project_from_json,
) -> tuple[list[dict[str, Any]], str | None]:
    """Load a transient Project only to build the active Scene selector."""

    if not source_path.strip():
        return [], None
    try:
        source_project = load_project_from_json(source_path)
        raw_routes = get_gallery_route_options(source_project)
    except Exception:
        return [], "source_load_failed"

    routes: list[dict[str, Any]] = []
    if type(raw_routes) is not list:
        return [], "source_load_failed"
    for route in raw_routes:
        if type(route) is not dict:
            continue
        route_id = route.get("route_id")
        count = route.get("line_count")
        if type(route_id) is not str or not route_id or type(count) is not int or count < 0:
            continue
        label = route.get("route_label")
        routes.append(
            {
                "separator_id": route_id,
                "label": label if type(label) is str and label else "Scene",
                "illustration_count": count,
            }
        )
    return routes, None


def _render_lifecycle_feedback(session_state) -> None:
    if type(session_state.get(SCENE_IMPORT_APPLY_RESULT_KEY)) is dict:
        return
    feedback = session_state.get(SCENE_IMPORT_FEEDBACK_KEY)
    if type(feedback) is not dict:
        return
    code = _bounded_code(feedback.get("code"), fallback="operation_failed")
    message = _FEEDBACK_MESSAGES.get(code)
    if message is None:
        message = "Scene Importを続行できません。入力を確認してFresh Previewからやり直してください。"
    kind = feedback.get("kind")
    if kind == "success":
        st.success(message)
    elif kind == "error":
        st.error(message)
    else:
        st.info(message)


def _render_apply_result(session_state) -> None:
    result = session_state.get(SCENE_IMPORT_APPLY_RESULT_KEY)
    if type(result) is not dict:
        return
    if result.get("applied") is True:
        target_separator = result.get("target_separator_id")
        illustration_ids = result.get("imported_illustration_ids")
        imported_modules = _bounded_name_list(result.get("imported_module_names"))
        reused_modules = _bounded_name_list(result.get("reused_module_names"))
        st.success("Sceneを現在のProject末尾へ追加しました。")
        if type(target_separator) is str:
            st.caption(f"追加したScene ID: {target_separator}")
        count = len(illustration_ids) if type(illustration_ids) is list else 0
        st.write(f"追加したIllustration: {count}")
        if imported_modules is not None:
            st.write("追加したModule: " + (", ".join(str(name) for name in imported_modules) or "なし"))
        if reused_modules is not None:
            st.write("再利用したModule: " + (", ".join(str(name) for name in reused_modules) or "なし"))
        st.caption("適用は現在のセッション内で完了し、通常の自動保存処理も呼び出しました。保存結果はPromptGraphの既存自動保存表示を確認してください。")
        return

    code = _bounded_code(result.get("reason"), fallback="core_apply_rejected")
    message = _FEEDBACK_MESSAGES.get(
        code,
        "Scene Importを適用できませんでした。Fresh Previewを作成して確認し直してください。",
    )
    st.error(message)
    st.caption("このPreviewは消費されました。条件を確認してFresh Previewを作成してください。")


def _render_preview_blockers(preview: dict[str, Any]) -> None:
    blockers = preview.get("blockers")
    if type(blockers) is not list or not blockers:
        st.warning("Previewを適用できません。Blockerを確認してください。")
        return
    st.warning("このPreviewはApplyできません。Blockerを解消してFresh Previewを作成してください。")
    for raw_code in blockers[:16]:
        code = _bounded_code(raw_code, fallback="invalid_preview")
        st.write("• " + _BLOCKER_MESSAGES.get(code, "確認が必要な状態: " + code))


def _render_preview_review(preview: dict[str, Any]) -> None:
    st.markdown("#### Preview内容")
    receipt = preview.get("planned_receipt")
    scene_label = receipt.get("source_scene_label") if type(receipt) is dict else None
    scene_label = scene_label if type(scene_label) is str and scene_label else "Scene"
    illustrations = preview.get("planned_illustrations")
    illustrations = illustrations if type(illustrations) is list else []
    separator = preview.get("planned_separator")
    separator_id = separator.get("id") if type(separator) is dict else None
    st.write(f"Source Scene: **{scene_label}**")
    st.write(f"ImportするIllustration: **{len(illustrations)}**")
    target_line_count = preview.get("target_line_count")
    insertion_index = preview.get("insertion_index")
    if type(target_line_count) is int and type(insertion_index) is int:
        st.write(
            f"追加先: 現在のProjectの物理末尾（現在 {target_line_count} 行目の後、挿入位置 {insertion_index}）"
        )
    if type(separator_id) is str:
        st.caption(f"追加予定のScene ID: {separator_id}")
    st.caption(
        "構造とPromptのみをImportします。Source画像、Candidates、Gallery Variants、Workbench、生成状態はコピーしません。"
    )

    actions = preview.get("module_actions")
    actions = actions if type(actions) is list else []
    st.markdown("##### Module actions")
    module_rows = []
    for action in actions:
        if type(action) is not dict:
            continue
        name = action.get("name")
        status = action.get("action")
        if type(name) is not str or type(status) is not str or status not in {"reuse", "import", "conflict"}:
            continue
        reason = _bounded_code(action.get("reason"), fallback="")
        descriptions = {
            "reuse": "同等のportable定義を再利用",
            "import": "portable定義を追加",
            "conflict": "同名Moduleの定義が異なるためApply不可",
        }
        module_rows.append(
            {
                "Module": name,
                "Action": descriptions[status],
                "理由": _BLOCKER_MESSAGES.get(reason, reason or "") if status == "conflict" else "",
            }
        )
    if module_rows:
        st.dataframe(module_rows, hide_index=True, width="stretch")
    else:
        st.caption("参照Moduleはありません。")

    st.markdown("##### ImportするIllustrations")
    illustration_rows = []
    for order, row in enumerate(illustrations, start=1):
        if type(row) is not dict:
            continue
        illustration_rows.append(
            {
                "順番": order,
                "Positive Prompt": row.get("current_text", ""),
                "Negative Prompt": row.get("negative_prompt", ""),
                "予定ID": row.get("id", ""),
            }
        )
    if illustration_rows:
        st.dataframe(illustration_rows, hide_index=True, width="stretch")
    elif (
        preview.get("valid") is True
        and type(separator) is dict
        and type(separator_id) is str
        and bool(separator_id.strip())
    ):
        st.caption("Source Sceneは空です。Separatorのみ追加されます。")
    else:
        st.info("Illustration planを作成できませんでした。Blockerを確認してください。")

    if preview.get("valid") is not True or preview.get("eligible") is not True:
        _render_preview_blockers(preview)

    with st.expander("Technical Preview identity", expanded=False):
        for key, label in (
            ("plan_id", "Plan ID"),
            ("projection_digest", "Projection digest"),
            ("source_scene_fingerprint", "Source Scene fingerprint"),
            ("target_freshness_fingerprint", "Target freshness fingerprint"),
        ):
            value = preview.get(key)
            if type(value) is str:
                st.caption(f"{label}: {value}")


def render_scene_import_panel(
    project,
    *,
    load_project_from_json,
    synchronize_selected_routes,
    restore_focus_after_graph_update,
    save_current_project_if_possible,
) -> None:
    """Render Scene Import controls and dispatch only through its lifecycle."""

    session_state = st.session_state
    session_state.setdefault(
        SCENE_IMPORT_SOURCE_PATH_WIDGET_KEY,
        session_state.get(SCENE_IMPORT_SOURCE_PATH_KEY, ""),
    )
    session_state.setdefault(
        SCENE_IMPORT_SOURCE_SEPARATOR_WIDGET_KEY,
        session_state.get(SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY, ""),
    )
    session_state.setdefault(SCENE_IMPORT_CONFIRM_WIDGET_KEY, False)

    st.markdown("#### Project間のScene Import")
    source_path = st.text_input(
        "Source Project JSON path",
        key=SCENE_IMPORT_SOURCE_PATH_WIDGET_KEY,
        help="別のPromptGraph ProjectのJSONファイルを指定します。",
    )
    _sync_source_inputs(
        session_state,
        source_path if type(source_path) is str else "",
        session_state.get(SCENE_IMPORT_SOURCE_SEPARATOR_WIDGET_KEY, ""),
    )

    routes, discovery_error = _discover_source_routes(
        source_path if type(source_path) is str else "",
        load_project_from_json=load_project_from_json,
    )
    route_ids = [route["separator_id"] for route in routes]
    current_widget_separator = session_state.get(
        SCENE_IMPORT_SOURCE_SEPARATOR_WIDGET_KEY,
        "",
    )
    if type(current_widget_separator) is not str or current_widget_separator not in route_ids:
        if current_widget_separator:
            set_scene_import_source_separator_id(session_state, "")
            session_state[SCENE_IMPORT_CONFIRM_WIDGET_KEY] = False
        current_widget_separator = ""
        session_state[SCENE_IMPORT_SOURCE_SEPARATOR_WIDGET_KEY] = ""

    route_by_id = {route["separator_id"]: route for route in routes}
    selector_options = ["", *route_ids]

    def _route_label(separator_id: str) -> str:
        if not separator_id:
            return "Sceneを選択してください"
        route = route_by_id.get(separator_id, {})
        return f"{route.get('label', 'Scene')} — {route.get('illustration_count', 0)} illustrations"

    selected_separator_id = st.selectbox(
        "Source Scene",
        options=selector_options,
        index=selector_options.index(current_widget_separator),
        format_func=_route_label,
        key=SCENE_IMPORT_SOURCE_SEPARATOR_WIDGET_KEY,
        disabled=not routes,
    )
    _sync_source_inputs(
        session_state,
        source_path if type(source_path) is str else "",
        selected_separator_id if type(selected_separator_id) is str else "",
    )
    if selected_separator_id:
        st.caption(f"Source Scene ID: {selected_separator_id}")

    if discovery_error:
        st.info("Source Projectを読み込めませんでした。ファイルのパスとJSONを確認してください。")
    elif source_path and not routes:
        st.info("Source Projectに選択できるactive Sceneがありません。")

    preview_disabled = not bool(source_path and selected_separator_id and routes and not discovery_error)
    if st.button("Fresh Preview", key="scene_import_fresh_preview", disabled=preview_disabled):
        build_scene_import_preview_from_source(
            source_path,
            selected_separator_id,
            session_state=session_state,
            load_project_from_json=load_project_from_json,
        )
        session_state[SCENE_IMPORT_CONFIRM_WIDGET_KEY] = False

    _render_lifecycle_feedback(session_state)
    _render_apply_result(session_state)

    preview = session_state.get(SCENE_IMPORT_PREVIEW_KEY)
    if type(preview) is not dict:
        session_state[SCENE_IMPORT_CONFIRM_WIDGET_KEY] = False
        return

    _render_preview_review(preview)
    confirmable = preview.get("valid") is True and preview.get("eligible") is True
    if not confirmable:
        session_state[SCENE_IMPORT_CONFIRM_WIDGET_KEY] = False
        return

    confirmed = st.checkbox(
        "このSceneを現在のProject末尾へ追加することを確認しました",
        key=SCENE_IMPORT_CONFIRM_WIDGET_KEY,
    )
    if st.button(
        "SceneをImport",
        key="scene_import_apply",
        disabled=not confirmed,
    ):
        apply_and_publish_scene_import(
            source_path,
            selected_separator_id,
            preview,
            session_state=session_state,
            load_project_from_json=load_project_from_json,
            synchronize_selected_routes=synchronize_selected_routes,
            restore_focus_after_graph_update=restore_focus_after_graph_update,
            save_current_project_if_possible=save_current_project_if_possible,
        )
        st.rerun()
