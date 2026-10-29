"""Read-only Public UI export for the canonical Scene Module Swap H1 envelope."""

from __future__ import annotations

import json

import streamlit as st

from core.agent_facade import (
    CONTRACT_VERSION,
    SCENE_MODULE_SWAP_OPERATION,
    preview_scene_module_swap,
)
from core.module_swap_selected_routes import build_selected_routes_module_swap_signature
from core.operations import get_module_swap_route_options


SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY = "_scene_module_swap_h1_export_snapshot"
SCENE_MODULE_SWAP_H1_MAX_ROWS = 100
SCENE_MODULE_SWAP_H1_D1_REQUEST_LIMIT_BYTES = 4 * 1024 * 1024
# D1 receives the observation inside a request object with a 64-character
# workingRevision. This exceeds the measured JSON wrapper overhead so the
# complete Desktop request stays below D1's body limit.
SCENE_MODULE_SWAP_H1_D1_WRAPPER_HEADROOM_BYTES = 256
SCENE_MODULE_SWAP_H1_MAX_BYTES = (
    SCENE_MODULE_SWAP_H1_D1_REQUEST_LIMIT_BYTES
    - SCENE_MODULE_SWAP_H1_D1_WRAPPER_HEADROOM_BYTES
)
_REQUEST_KEYS = {
    "scene_id",
    "source_module_name",
    "target_module_name",
    "match_mode",
}
_DIGEST_KEYS = ("source_fingerprint", "projection_digest", "plan_id")


def _complete_text(value: object) -> bool:
    return (
        type(value) is dict
        and type(value.get("text")) is str
        and type(value.get("truncated")) is bool
        and value["truncated"] is False
        and type(value.get("length")) is int
        and value["length"] == len(value["text"])
    )


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _complete_observation(observation: object, request: dict) -> bool:
    """Check that the untouched Facade envelope is complete for Desktop intake."""

    if type(observation) is not dict or type(request) is not dict:
        return False
    if set(request) != _REQUEST_KEYS or observation.get("request") != request:
        return False
    if (
        any(type(request.get(key)) is not str or not request[key] for key in _REQUEST_KEYS)
        or request.get("match_mode") not in {"strict", "loose"}
    ):
        return False
    if (
        observation.get("contract_version") != CONTRACT_VERSION
        or observation.get("operation") != SCENE_MODULE_SWAP_OPERATION
        or observation.get("valid") is not True
        or observation.get("reason") != ""
        or observation.get("prompt_only") is not True
        or observation.get("negative_prompt_semantics") != "unchanged_by_module_swap"
        or type(observation.get("diagnostics")) is not list
        or observation["diagnostics"]
    ):
        return False
    if any(not _is_digest(observation.get(key)) for key in _DIGEST_KEYS):
        return False
    if observation.get("scene_id") != request["scene_id"]:
        return False
    if not _complete_text(observation.get("scene_label")):
        return False

    target_ids = observation.get("target_ids")
    rows = observation.get("review_rows")
    target_count = observation.get("target_count")
    if (
        type(target_ids) is not list
        or not 1 <= len(target_ids) <= SCENE_MODULE_SWAP_H1_MAX_ROWS
        or any(type(value) is not str or not value for value in target_ids)
        or len(set(target_ids)) != len(target_ids)
        or type(target_count) is not int
        or target_count != len(target_ids)
        or type(rows) is not list
        or len(rows) != target_count
        or observation.get("review_rows_truncated") is not False
        or type(observation.get("review_rows_omitted")) is not int
        or observation["review_rows_omitted"] != 0
    ):
        return False

    count_keys = (
        "changed_count",
        "no_op_count",
        "skipped_count",
        "blocked_count",
        "drift_count",
    )
    counts = {key: observation.get(key) for key in count_keys}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        return False
    if (
        counts["blocked_count"] != 0
        or counts["changed_count"] + counts["no_op_count"] != target_count
        or counts["skipped_count"] > target_count
        or counts["drift_count"] > target_count
    ):
        return False

    changed_rows = 0
    no_op_rows = 0
    for order, (target_id, row) in enumerate(zip(target_ids, rows, strict=True)):
        if (
            type(row) is not dict
            or row.get("illustration_id") != target_id
            or type(row.get("scene_order")) is not int
            or row["scene_order"] != order
            or type(row.get("changed")) is not bool
            or type(row.get("no_op")) is not bool
            or row["changed"] == row["no_op"]
            or not _complete_text(row.get("before_positive_prompt"))
            or not _complete_text(row.get("after_positive_prompt"))
        ):
            return False
        changed_rows += int(row["changed"])
        no_op_rows += int(row["no_op"])

        delta = row.get("token_delta")
        if type(delta) is not dict:
            return False
        for side in ("added", "removed"):
            examples = delta.get(side)
            count = delta.get(f"{side}_count")
            if (
                type(examples) is not list
                or any(not _complete_text(example) for example in examples)
                or type(count) is not int
                or count != len(examples)
                or delta.get(f"{side}_truncated") is not False
            ):
                return False
        if type(row.get("match_count")) is not int or row["match_count"] < 0:
            return False

    return (
        changed_rows == counts["changed_count"]
        and no_op_rows == counts["no_op_count"]
    )


def _serialize_complete_observation(observation: dict, request: dict) -> tuple[str, bytes | None]:
    if not _complete_observation(observation, request):
        return "incomplete", None
    try:
        encoded = json.dumps(
            observation,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except Exception:
        return "incomplete", None
    if len(encoded) > SCENE_MODULE_SWAP_H1_MAX_BYTES:
        return "oversized", None
    if observation["changed_count"] == 0:
        return "zero_change", encoded
    return "ready", encoded


def _selection_signature(project, request: dict, project_path: str) -> str | None:
    try:
        return build_selected_routes_module_swap_signature(
            project,
            [request["scene_id"]],
            source_module_name=request["source_module_name"],
            target_module_name=request["target_module_name"],
            match_mode=request["match_mode"],
            project_path=project_path,
            disabled_modules=None,
        )
    except Exception:
        return None


def _render_status(status: str) -> None:
    if status == "incomplete":
        st.warning(
            "このPreviewはDesktop D1の受け入れ条件を満たさないため、H1 JSONを出力しません。"
            "SceneやPromptを調整して再生成してください。"
        )
    elif status == "oversized":
        st.warning(
            "このJSONはDesktopのサイズ上限を超えています。分割や一部省略は行わず、"
            "ダウンロードしません。対象やPromptを調整して再生成してください。"
        )
    elif status == "zero_change":
        st.info(
            "変更されるIllustrationがありません。Desktop D2では人が確認する変更案が必要なため、"
            "JSONダウンロードはありません。"
        )
    elif status == "invalid":
        st.info("Scene Module Swap Previewを作成できませんでした。選択を確認して再試行してください。")


def render_scene_module_swap_h1_export(project, *, is_free) -> None:
    """Offer the exact Public Facade H1 observation as a user-initiated download."""

    with st.expander("Scene Module Swap H1 JSON export", expanded=False):
        state = st.session_state
        if is_free():
            state.pop(SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY, None)
            st.info("H1 JSON exportはProで利用できます。")
            return
        if project is None:
            state.pop(SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY, None)
            st.info("現在開いているProjectを利用できません。")
            return

        try:
            routes = get_module_swap_route_options(project)
            library = getattr(project, "module_library", None)
            if type(library) is not dict:
                raise ValueError("invalid module library")
            route_by_id = {
                item["route_id"]: item
                for item in routes
                if type(item) is dict and type(item.get("route_id")) is str and item["route_id"]
            }
            module_names = sorted(name for name in library if type(name) is str and name)
        except Exception:
            state.pop(SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY, None)
            st.info("現在のProjectからSceneとModuleの選択肢を読み込めません。")
            return

        if not route_by_id:
            state.pop(SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY, None)
            st.info("現在のProjectに選べるSceneがありません。")
            return
        if len(module_names) < 2:
            state.pop(SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY, None)
            st.info("Scene Module Swapには異なるProject Moduleが2つ以上必要です。")
            return
        if len(route_by_id) != len(routes):
            state.pop(SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY, None)
            st.info("Scene IDを一意に選択できないため、H1 JSONは出力できません。")
            return

        scene_ids = list(route_by_id)
        scene_id = st.selectbox(
            "Scene",
            options=scene_ids,
            format_func=lambda value: (
                f"{route_by_id[value].get('route_label') or 'Scene'} "
                f"({route_by_id[value].get('line_count', 0)} Illustrations)"
            ),
            key="scene_module_swap_h1_scene_id",
        )
        source_module = st.selectbox(
            "Source Module",
            options=module_names,
            key="scene_module_swap_h1_source_module",
        )
        target_default = 1 if len(module_names) > 1 else 0
        target_module = st.selectbox(
            "Target Module",
            options=module_names,
            index=target_default,
            key="scene_module_swap_h1_target_module",
        )
        match_mode = st.radio(
            "Match mode",
            options=["strict", "loose"],
            horizontal=True,
            key="scene_module_swap_h1_match_mode",
        )
        request = {
            "scene_id": scene_id,
            "source_module_name": source_module,
            "target_module_name": target_module,
            "match_mode": match_mode,
        }
        project_path = state.get("current_project_path", "")
        project_path = project_path if type(project_path) is str else ""
        signature = _selection_signature(project, request, project_path)

        snapshot = state.get(SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY)
        snapshot_current = (
            type(snapshot) is dict
            and snapshot.get("project") is project
            and snapshot.get("project_path") == project_path
            and snapshot.get("request") == request
            and signature is not None
            and snapshot.get("signature") == signature
        )
        stale_snapshot_cleared = snapshot is not None and not snapshot_current
        if stale_snapshot_cleared:
            state.pop(SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY, None)
            snapshot = None

        st.caption(
            "現在のProjectの1 Sceneについて、Facadeが返すcanonical H1 JSONをそのまま出力します。"
            "この操作は読み取り専用です。"
        )
        if stale_snapshot_cleared:
            st.info("Projectまたは選択が変わったため、前のJSONを無効にしました。もう一度生成してください。")

        if signature is None:
            state.pop(SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY, None)
            st.info("現在の選択を確認できないため、H1 JSONを生成できません。")
            return

        if st.button("Generate H1 JSON", key="scene_module_swap_h1_generate"):
            try:
                observation = preview_scene_module_swap(project, request)
            except Exception:
                observation = None
            if type(observation) is not dict or observation.get("valid") is not True:
                state.pop(SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY, None)
                st.info("Scene Module Swap Previewを作成できませんでした。選択を確認して再試行してください。")
                return
            status, payload = _serialize_complete_observation(observation, request)
            state[SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY] = {
                "project": project,
                "project_path": project_path,
                "request": request.copy(),
                "signature": signature,
                "observation": observation,
                "payload": payload,
                "status": status,
            }
            snapshot = state[SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY]
            snapshot_current = True

        if not snapshot_current:
            return
        if type(snapshot) is not dict or snapshot.get("project") is not project:
            return

        status = snapshot.get("status")
        if status != "ready":
            _render_status(status if type(status) is str else "invalid")
            return
        payload = snapshot.get("payload")
        if type(payload) is not bytes:
            _render_status("invalid")
            return
        st.caption("Desktopの「Import Public Scene Swap proposal…」へ、JSON全文を変更せず貼り付けてください。")
        st.download_button(
            "Download H1 JSON",
            data=payload,
            file_name="scene-module-swap-h1.json",
            mime="application/json",
            key="scene_module_swap_h1_download",
        )
