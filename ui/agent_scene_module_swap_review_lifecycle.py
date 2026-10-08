"""Fresh, host-only display projection for pending Scene Module Swap reviews."""

from core.agent_facade import (
    MAX_TARGETS,
    _preview_scene_module_swap_for_host_review,
)
from ui.agent_scene_module_swap_approval_lifecycle import (
    AgentSceneModuleSwapApprovalCustodian,
)


_INTENT_FIELDS = (
    "scene_id",
    "source_module_name",
    "target_module_name",
    "match_mode",
)
_EXPECTED_INTENT_FIELDS = frozenset((*_INTENT_FIELDS, "expected_plan_id"))
_DRIFT_LABELS = {
    "no prompt change": "No prompt change",
    "image reference unavailable": "Image reference unavailable",
    "prompt changed, no representative image": "Prompt changed; no representative image",
    "positive and negative changed while main image remains unchanged": (
        "Positive and negative prompts changed while the main image remains unchanged"
    ),
    "prompt changed while main image remains unchanged": (
        "Prompt changed while the main image remains unchanged"
    ),
}
_SWAP_KIND_LABELS = {
    "body_tokens": "Module body tokens",
    "reference": "Module reference",
}


def _count(value):
    return type(value) is int and 0 <= value <= MAX_TARGETS


def _pending_record_is_well_formed(record):
    intent = record.get("intent")
    preview = record.get("preview")
    return (
        type(record.get("proposal_id")) is str
        and bool(record["proposal_id"])
        and type(record.get("target_epoch")) is str
        and bool(record["target_epoch"])
        and type(record.get("plan_id")) is str
        and bool(record["plan_id"])
        and type(intent) is dict
        and set(intent) == _EXPECTED_INTENT_FIELDS
        and all(type(intent.get(field)) is str and intent[field] for field in _INTENT_FIELDS)
        and intent.get("match_mode") in {"strict", "loose"}
        and intent.get("expected_plan_id") == record.get("plan_id")
        and type(preview) is dict
        and preview.get("plan_id") == record.get("plan_id")
    )


def _validated_display_projection(record, fresh, plan):
    """Allowlist every human-visible value from one fresh facade/planner run."""

    intent = record["intent"]
    preview = record["preview"]
    scene_label = fresh.get("scene_label")
    target_ids = fresh.get("target_ids")
    entries = plan.get("entries") if type(plan) is dict else None
    counts = {
        key: fresh.get(key)
        for key in (
            "target_count", "changed_count", "no_op_count", "skipped_count",
            "blocked_count", "drift_count",
        )
    }
    if (
        fresh != preview
        or fresh.get("valid") is not True
        or type(fresh.get("prompt_only")) is not bool
        or fresh.get("prompt_only") is not True
        or fresh.get("negative_prompt_semantics") != "unchanged_by_module_swap"
        or type(scene_label) is not dict
        or type(scene_label.get("text")) is not str
        or type(target_ids) is not list
        or not 0 < len(target_ids) <= MAX_TARGETS
        or any(type(item) is not str or not item for item in target_ids)
        or any(not _count(value) for value in counts.values())
        or counts["target_count"] != len(target_ids)
        or type(plan) is not dict
        or plan.get("valid") is not True
        or plan.get("prompt_only") is not True
        or plan.get("signature") != fresh.get("source_fingerprint")
        or plan.get("source_fingerprint") != fresh.get("source_fingerprint")
        or plan.get("selected_route_ids") != [intent["scene_id"]]
        or plan.get("selected_route_count") != 1
        or plan.get("source_module_name") != intent["source_module_name"]
        or plan.get("target_module_name") != intent["target_module_name"]
        or plan.get("match_mode") != intent["match_mode"]
        or plan.get("target_line_ids") != target_ids
        or plan.get("target_line_count") != counts["target_count"]
        or plan.get("changed_line_count") != counts["changed_count"]
        or plan.get("no_op_count") != counts["no_op_count"]
        or plan.get("skipped_count") != counts["skipped_count"]
        or plan.get("blocked_count") != counts["blocked_count"]
        or plan.get("drift_count") != counts["drift_count"]
        or type(entries) is not list
        or len(entries) != len(target_ids)
    ):
        return None

    display_rows = []
    changed_count = 0
    no_op_count = 0
    skipped_count = 0
    drift_count = 0
    for order, (illustration_id, entry) in enumerate(zip(target_ids, entries, strict=True)):
        if type(entry) is not dict:
            return None
        before = entry.get("before_positive_prompt")
        after = entry.get("after_positive_prompt")
        before_negative = entry.get("before_negative_prompt")
        after_negative = entry.get("after_negative_prompt")
        added = entry.get("positive_added_tokens")
        removed = entry.get("positive_removed_tokens")
        positive_changed = entry.get("positive_changed")
        negative_changed = entry.get("negative_changed")
        no_op = entry.get("no_op")
        match_count = entry.get("match_count")
        swap_kind = entry.get("swap_kind", "")
        drift_risk = entry.get("drift_risk", "")
        skip_reason = entry.get("skip_reason", "")
        changed = positive_changed or negative_changed
        if (
            entry.get("line_id") != illustration_id
            or type(before) is not str
            or type(after) is not str
            or type(before_negative) is not str
            or type(after_negative) is not str
            or before_negative != after_negative
            or type(positive_changed) is not bool
            or type(negative_changed) is not bool
            or negative_changed
            or type(no_op) is not bool
            or no_op is changed
            or type(added) is not list
            or any(type(token) is not str for token in added)
            or type(removed) is not list
            or any(type(token) is not str for token in removed)
            or type(match_count) is not int
            or match_count < 0
            or type(swap_kind) is not str
            or swap_kind not in {"", "body_tokens", "reference"}
            or type(drift_risk) is not str
            or drift_risk not in _DRIFT_LABELS
            or type(skip_reason) is not str
        ):
            return None

        is_skipped = bool(skip_reason)
        changed_count += int(changed)
        no_op_count += int(no_op)
        skipped_count += int(is_skipped)
        drift_count += int(drift_risk not in {"no prompt change", "prompt changed, no representative image"})
        display_rows.append({
            "illustration_id": illustration_id,
            "scene_order": order,
            "status": "changed" if changed else "skipped" if is_skipped else "no_op",
            "before_positive_prompt": before,
            "after_positive_prompt": after,
            "token_delta": {
                "added": list(added),
                "removed": list(removed),
            },
            "match_count": match_count,
            "swap_kind": _SWAP_KIND_LABELS.get(swap_kind, "No token match"),
            "drift_risk": _DRIFT_LABELS[drift_risk],
            "negative_prompt_unchanged": before_negative == after_negative,
        })

    if (
        changed_count != counts["changed_count"]
        or no_op_count != counts["no_op_count"]
        or skipped_count != counts["skipped_count"]
        or drift_count != counts["drift_count"]
    ):
        return None

    return {
        "state": "pending_fresh",
        "proposal_id": record["proposal_id"],
        "plan_id": record["plan_id"],
        "expires_in_seconds": record.get("expires_in_seconds", 0),
        "scene_id": intent["scene_id"],
        "scene_label": scene_label["text"],
        "source_module_name": intent["source_module_name"],
        "target_module_name": intent["target_module_name"],
        "match_mode": intent["match_mode"],
        **counts,
        "rows": display_rows,
    }


def build_agent_scene_module_swap_review(project, runtime, project_path=""):
    """Freshly validate and project this session's pending host proposal."""

    if runtime is None:
        return {"state": "session_unavailable"}
    custodian = getattr(runtime, "review_custodian", None)
    if (type(custodian) is not AgentSceneModuleSwapApprovalCustodian
            or not callable(getattr(runtime, "inspect_review_custody", None))
            or not callable(getattr(runtime, "mark_review_proposal_stale", None))):
        return {"state": "session_unavailable"}
    try:
        current_epoch = runtime.synchronize_target(project, project_path)
    except Exception:
        return {"state": "computation_failure"}
    try:
        record = runtime.inspect_review_custody()
    except Exception:
        return {"state": "computation_failure"}
    state = record.get("state") if type(record) is dict else None
    if project is None:
        return {"state": "project_unavailable"}
    if state != "pending":
        return {"state": state if state in {
            "absent", "prepared", "expired", "stale", "rejected", "dismissed",
            "computation_failure", "session_unavailable",
        } else "computation_failure"}
    if not _pending_record_is_well_formed(record):
        return {"state": "validation_failure"}

    if current_epoch != record.get("target_epoch"):
        try:
            state = runtime.mark_review_proposal_stale(record["proposal_id"])
        except Exception:
            state = "computation_failure"
        return {"state": "stale" if state == "stale" else "validation_failure"}

    intent = record["intent"]
    request = {field: intent[field] for field in _INTENT_FIELDS}
    try:
        fresh, plan = _preview_scene_module_swap_for_host_review(project, request)
    except Exception:
        return {"state": "computation_failure"}
    if type(fresh) is not dict or fresh != record["preview"]:
        try:
            state = runtime.mark_review_proposal_stale(record["proposal_id"])
        except Exception:
            state = "computation_failure"
        return {"state": "stale" if state == "stale" else "validation_failure"}
    if (fresh.get("valid") is not True
            or type(fresh.get("changed_count")) is not int
            or fresh["changed_count"] <= 0):
        try:
            state = runtime.mark_review_proposal_stale(record["proposal_id"])
        except Exception:
            state = "computation_failure"
        return {"state": "stale" if state == "stale" else "validation_failure"}

    try:
        projection = _validated_display_projection(record, fresh, plan)
    except Exception:
        projection = None
    if projection is None:
        return {"state": "validation_failure"}

    # Recheck the custodian and target after the planner computation. A
    # confirmation control is rendered only while the exact same pending
    # proposal and target epoch remain current.
    try:
        final_epoch = runtime.synchronize_target(project, project_path)
        final_record = runtime.inspect_review_custody()
    except Exception:
        return {"state": "computation_failure"}
    final_state = final_record.get("state") if type(final_record) is dict else None
    if final_state != "pending":
        return {"state": final_state if final_state in {
            "absent", "prepared", "expired", "stale", "rejected", "dismissed",
            "computation_failure", "session_unavailable",
        } else "validation_failure"}
    if final_epoch != record["target_epoch"]:
        try:
            stale_state = runtime.mark_review_proposal_stale(record["proposal_id"])
        except Exception:
            stale_state = "computation_failure"
        return {"state": "stale" if stale_state == "stale" else "validation_failure"}
    if (
        final_record.get("proposal_id") != record["proposal_id"]
        or final_record.get("target_epoch") != record["target_epoch"]
        or final_record.get("plan_id") != record["plan_id"]
        or final_record.get("intent") != record["intent"]
        or final_record.get("preview") != record["preview"]
    ):
        return {"state": "validation_failure"}
    projection["expires_in_seconds"] = final_record.get("expires_in_seconds", 0)
    return projection
