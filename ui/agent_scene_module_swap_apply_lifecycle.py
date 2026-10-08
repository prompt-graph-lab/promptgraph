"""One-shot human approval and host-only publication for Scene Module Swap."""

from core.agent_facade import preview_scene_module_swap
from core.module_swap_selected_routes import apply_selected_routes_module_swap


_INTENT_FIELDS = (
    "scene_id",
    "source_module_name",
    "target_module_name",
    "match_mode",
)
_INTENT_KEYS = frozenset((*_INTENT_FIELDS, "expected_plan_id"))


def _current_target_matches(session_state, project, project_path):
    current_path = session_state.get("current_project_path", "")
    return (
        session_state.get("project") is project
        and type(current_path) is str
        and type(project_path) is str
        and current_path == project_path
    )


def _terminal_review_state(runtime):
    try:
        record = runtime.inspect_review_custody()
    except Exception:
        return "session_unavailable"
    if type(record) is not dict:
        return "session_unavailable"
    state = record.get("state")
    return state if state in {
        "expired", "stale", "rejected", "dismissed", "applying",
        "applied", "applied_save_failed", "apply_failed", "session_unavailable",
    } else "stale"


def _mark_pending_stale(runtime, proposal_id):
    try:
        state = runtime.mark_review_proposal_stale(proposal_id)
    except Exception:
        return "computation_failure"
    if state == "stale":
        return "stale"
    return _terminal_review_state(runtime)


def _synchronize_session_target(runtime, session_state):
    try:
        runtime.synchronize_target(
            session_state.get("project"),
            session_state.get("current_project_path", ""),
        )
    except Exception:
        return "computation_failure"
    return _terminal_review_state(runtime)


def _finish_claim(runtime, claim, status, result=None):
    try:
        terminal = runtime.finish_review_proposal_apply(claim, status, result or {})
    except Exception:
        return "session_unavailable"
    if terminal == status:
        return status
    return _terminal_review_state(runtime)


def apply_agent_scene_module_swap_approval(
    session_state,
    runtime,
    *,
    project,
    project_path,
    proposal_id,
    plan_id,
    acknowledgment_identity_key,
    acknowledgment_identity,
    acknowledgment_widget_key,
    synchronize_gallery_selection,
    restore_focus,
    sync_text_areas,
    save_project,
):
    """Revalidate one staged human approval, Apply on a core clone, then publish.

    The checkbox values only establish that the exact current proposal was
    reviewed in this browser session. This function is called by the explicit
    host button callback, claims custody once after a fresh exact-envelope
    check, and never exposes the Apply result to the agent mailbox.
    """

    expected_identity = (proposal_id, plan_id)
    if (session_state.get(acknowledgment_identity_key) != expected_identity
            or session_state.get(acknowledgment_widget_key) is not True):
        return {"status": "acknowledgment_required"}
    if (runtime is None
            or not callable(getattr(runtime, "synchronize_target", None))
            or not callable(getattr(runtime, "inspect_review_custody", None))
            or not callable(getattr(runtime, "claim_review_proposal_for_apply", None))
            or not callable(getattr(runtime, "review_apply_claim_is_current", None))
            or not callable(getattr(runtime, "finish_review_proposal_apply", None))
            or not callable(getattr(runtime, "mark_review_proposal_stale", None))):
        return {"status": "session_unavailable"}
    if project is None:
        return {"status": _synchronize_session_target(runtime, session_state)}
    if not _current_target_matches(session_state, project, project_path):
        return {"status": _synchronize_session_target(runtime, session_state)}

    try:
        target_epoch = runtime.synchronize_target(project, project_path)
        record = runtime.inspect_review_custody()
    except Exception:
        return {"status": "computation_failure"}
    if type(record) is not dict:
        return {"status": "session_unavailable"}
    state = record.get("state")
    if state != "pending":
        return {"status": _terminal_review_state(runtime)}
    intent = record.get("intent")
    stored_preview = record.get("preview")
    if (
        record.get("proposal_id") != proposal_id
        or record.get("plan_id") != plan_id
        or record.get("target_epoch") != target_epoch
        or type(intent) is not dict
        or set(intent) != _INTENT_KEYS
        or any(type(intent.get(key)) is not str or not intent[key]
               for key in _INTENT_FIELDS)
        or intent.get("match_mode") not in {"strict", "loose"}
        or intent.get("expected_plan_id") != plan_id
        or type(stored_preview) is not dict
        or stored_preview.get("plan_id") != plan_id
    ):
        return {"status": _mark_pending_stale(runtime, proposal_id)}

    request = {key: intent[key] for key in _INTENT_FIELDS}
    try:
        fresh_preview = preview_scene_module_swap(project, request)
    except Exception:
        return {"status": "computation_failure"}
    if (
        type(fresh_preview) is not dict
        or fresh_preview != stored_preview
        or fresh_preview.get("valid") is not True
        or type(fresh_preview.get("changed_count")) is not int
        or fresh_preview["changed_count"] <= 0
        or fresh_preview.get("request") != request
        or fresh_preview.get("scene_id") != intent["scene_id"]
        or fresh_preview.get("plan_id") != plan_id
        or type(fresh_preview.get("source_fingerprint")) is not str
        or type(fresh_preview.get("projection_digest")) is not str
    ):
        return {"status": _mark_pending_stale(runtime, proposal_id)}

    # Recheck target identity, epoch, and complete custody after facade work.
    # No Project/custodian lock is held during Preview computation.
    try:
        current_epoch = runtime.synchronize_target(project, project_path)
        current_record = runtime.inspect_review_custody()
    except Exception:
        return {"status": "computation_failure"}
    if not _current_target_matches(session_state, project, project_path):
        return {"status": _synchronize_session_target(runtime, session_state)}
    if (current_epoch != target_epoch or type(current_record) is not dict
            or current_record.get("state") != "pending"
            or current_record.get("proposal_id") != proposal_id
            or current_record.get("target_epoch") != target_epoch
            or current_record.get("plan_id") != plan_id
            or current_record.get("intent") != intent
            or current_record.get("preview") != fresh_preview):
        return {"status": _terminal_review_state(runtime)}

    claim_status, claim = runtime.claim_review_proposal_for_apply(
        proposal_id,
        target_epoch,
        intent,
        fresh_preview,
    )
    if claim_status != "applying" or claim is None:
        return {"status": claim_status}

    try:
        history_snapshot = project.clone()
        if history_snapshot is None or history_snapshot is project:
            raise RuntimeError("invalid history snapshot")
    except Exception:
        return {"status": _finish_claim(runtime, claim, "apply_failed")}

    try:
        # The claim is a one-shot linearization point. Target changes and
        # session teardown revoke it through the mailbox/custodian lock pair.
        current_epoch = runtime.synchronize_target(
            session_state.get("project"),
            session_state.get("current_project_path", ""),
        )
    except Exception:
        return {"status": _finish_claim(runtime, claim, "apply_failed")}
    if (not _current_target_matches(session_state, project, project_path)
            or current_epoch != target_epoch
            or not runtime.review_apply_claim_is_current(claim)):
        return {"status": _terminal_review_state(runtime)}

    try:
        apply_result = apply_selected_routes_module_swap(
            project,
            [intent["scene_id"]],
            expected_signature=fresh_preview["source_fingerprint"],
            source_module_name=intent["source_module_name"],
            target_module_name=intent["target_module_name"],
            match_mode=intent["match_mode"],
            project_path="",
            disabled_modules=None,
        )
    except Exception:
        return {"status": _finish_claim(runtime, claim, "apply_failed")}

    if (type(apply_result) is not dict or apply_result.get("applied") is not True):
        if type(apply_result) is dict and apply_result.get("stale_preview") is True:
            return {"status": _finish_claim(runtime, claim, "stale")}
        return {"status": _finish_claim(runtime, claim, "apply_failed")}
    changed_count = fresh_preview["changed_count"]
    updated_project = apply_result.get("updated_project")
    if (type(apply_result.get("applied_count")) is not int
            or apply_result["applied_count"] != changed_count
            or apply_result.get("selected_route_ids") != [intent["scene_id"]]
            or updated_project is None or updated_project is project):
        return {"status": _finish_claim(runtime, claim, "apply_failed")}

    # Core Apply only returns a replacement clone. Verify the exact active
    # session/target and claim once more before publishing any host state.
    try:
        current_epoch = runtime.synchronize_target(
            session_state.get("project"),
            session_state.get("current_project_path", ""),
        )
        claim_current = runtime.review_apply_claim_is_current(claim)
    except Exception:
        return {"status": _terminal_review_state(runtime)}
    if (not _current_target_matches(session_state, project, project_path)
            or current_epoch != target_epoch or not claim_current):
        return {"status": _terminal_review_state(runtime)}

    history = session_state.get("history")
    if type(history) is not list:
        return {"status": _finish_claim(runtime, claim, "apply_failed")}
    try:
        history.append(history_snapshot)
        if len(history) > 20:
            history.pop(0)
        previous_focus = session_state.get("focused_line_id")
        session_state["project"] = updated_project
    except Exception:
        return {"status": _finish_claim(runtime, claim, "apply_failed")}

    # The Project replacement is now successful and must not be rolled back
    # if persistence fails. Each publication helper is host-local and bounded.
    session_state["selected_node_ids"] = []
    sync_warning = False
    for callback, arguments in (
        (synchronize_gallery_selection, (updated_project,)),
        (restore_focus, (previous_focus,)),
        (sync_text_areas, ()),
    ):
        try:
            if callable(callback):
                callback(*arguments)
        except Exception:
            sync_warning = True
    session_state.pop("module_swap_preview", None)
    session_state.pop("module_swap_selected_routes_confirm", None)

    try:
        save_succeeded = bool(save_project("Agent Scene Module Swap applied"))
    except Exception:
        save_succeeded = False
    terminal_status = "applied" if save_succeeded else "applied_save_failed"
    terminal_result = {
        "applied_count": changed_count,
        "save_succeeded": save_succeeded,
    }
    if sync_warning:
        terminal_result["sync_warning"] = True
    state = _finish_claim(runtime, claim, terminal_status, terminal_result)
    return {
        "status": state,
        "applied_count": changed_count,
        "save_succeeded": save_succeeded,
        "sync_warning": sync_warning,
    }
