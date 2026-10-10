"""Host-only fresh Generation review and exact human terminal actions."""
from core import agent_facade
from agent_adapters.mcp_adapter import validate_generation_review_arguments
from ui.agent_generation_review_custody import AgentGenerationReviewCustodian, _valid_preview_envelope
from ui.project_agent_session_pump import ProjectAgentSessionRuntime


def _inspect(runtime):
    return runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)


def build_generation_review(session_state, runtime, host_context_provider):
    if (type(runtime) is not ProjectAgentSessionRuntime
            or type(runtime.generation_review_custodian) is not AgentGenerationReviewCustodian):
        return {"state": "session_unavailable"}
    try:
        project, path = session_state.get("project"), session_state.get("current_project_path", "")
        epoch = runtime.synchronize_target(project, path)
        record = _inspect(runtime)
        state = record.get("state")
        if state != "pending":
            return {"state": state if state in {"absent", "prepared", "expired", "stale", "rejected",
                    "dismissed", "session_unavailable", "computation_failure"} else "validation_failure"}
        if project is None:
            return {"state": "project_unavailable"}
        if runtime._registration is None:
            return {"state": "session_unavailable"}
        available, generation = runtime._registration.inspect_pairing_generation()
        if not available:
            return {"state": "session_unavailable"}
        if generation is not None and generation != record.get("pairing_generation"):
            state = runtime.mailbox.mark_review_proposal_stale(runtime.generation_review_custodian, record["proposal_id"])
            return {"state": "stale" if state == "stale" else "validation_failure"}
        intent = validate_generation_review_arguments(record.get("intent"))
        preview = record.get("preview")
        if (intent is None or not _valid_preview_envelope(preview)
                or record.get("plan_id") != intent["expected_plan_id"]
                or preview["plan_id"] != record["plan_id"]
                or type(record.get("proposal_id")) is not str or not 0 < len(record["proposal_id"]) <= 128
                or type(record.get("pairing_generation")) is not int or record["pairing_generation"] <= 0
                or type(record.get("expires_in_seconds")) is not int or not 0 <= record["expires_in_seconds"] <= 900
                or epoch != record.get("target_epoch")
                or runtime._registration is None):
            return {"state": "validation_failure"}
        binding = [agent_facade.candidate_observation_handles.project_identity(project),
                   runtime._registration.route_id, path, record["pairing_generation"], epoch]
        fresh = agent_facade.preview_generation(project, intent["scene_id"], run_count=intent["run_count"],
                    host_context_provider=host_context_provider, observation_binding=binding)
        # Temporary read/preflight failure does not claim that content is current
        # or that the human dismissed it. Custody remains available for recovery.
        final_epoch = runtime.synchronize_target(session_state.get("project"),
                                                session_state.get("current_project_path", ""))
        final = _inspect(runtime)
        if final.get("state") != "pending":
            return {"state": final.get("state", "validation_failure")}
        available, generation = runtime._registration.inspect_pairing_generation()
        if not available:
            return {"state": "session_unavailable"}
        if generation is not None and generation != record["pairing_generation"]:
            state = runtime.mailbox.mark_review_proposal_stale(runtime.generation_review_custodian, record["proposal_id"])
            return {"state": "stale" if state == "stale" else "validation_failure"}
        identity_keys = ("proposal_id", "target_epoch", "pairing_generation", "plan_id", "intent", "preview")
        if final_epoch != epoch or any(final.get(key) != record.get(key) for key in identity_keys):
            return {"state": "validation_failure"}
        if type(fresh) is not dict or fresh.get("ok") is not True:
            return {"state": "computation_failure"}
        if fresh != preview:
            state = runtime.mailbox.mark_review_proposal_stale(runtime.generation_review_custodian, record["proposal_id"])
            return {"state": "stale" if state == "stale" else "validation_failure"}
        if not _valid_preview_envelope(fresh):
            return {"state": "validation_failure"}
        # All fields come from the existing safe, bounded Facade projection.
        return {"state": "pending_current", "proposal_id": record["proposal_id"], "plan_id": record["plan_id"],
                "target_epoch": epoch,
                "expires_in_seconds": final["expires_in_seconds"],
                **{key: fresh[key] for key in ("scene_id", "scene_label", "run_count", "target_count",
                    "request_count", "expected_image_count", "expected_output_node_count", "illustrations",
                    "skipped_count", "blocked_count", "skipped", "skipped_truncated", "warnings", "workflow_summary")}}
    except Exception:
        return {"state": "computation_failure"}


def resolve_generation_review(session_state, runtime, host_context_provider, proposal_id, plan_id, action):
    """Direct human callback: revalidate current identity/content before resolve."""
    if action not in {"reject", "dismiss"} or type(runtime) is not ProjectAgentSessionRuntime:
        return "invalid_action"
    try:
        record = _inspect(runtime)
        if record.get("proposal_id") != proposal_id or record.get("plan_id") != plan_id:
            return "identity_mismatch"
        review = build_generation_review(session_state, runtime, host_context_provider)
        if (review.get("state") != "pending_current" or review.get("proposal_id") != proposal_id
                or review.get("plan_id") != plan_id):
            return review.get("state", "validation_failure")
        with runtime._publication_gate:
            epoch = runtime._synchronize_target_locked(session_state.get("project"),
                                                      session_state.get("current_project_path", ""))
            record = _inspect(runtime)
            if (record.get("state") != "pending" or record.get("proposal_id") != proposal_id
                    or record.get("plan_id") != plan_id or epoch != review["target_epoch"]):
                return "identity_mismatch"
            available, generation = runtime._registration.inspect_pairing_generation()
            if not available:
                return "session_unavailable"
            if generation is not None and generation != record["pairing_generation"]:
                return runtime.mailbox.mark_review_proposal_stale(runtime.generation_review_custodian, proposal_id)
            status = runtime.mailbox.resolve_review_proposal(runtime.generation_review_custodian, proposal_id, action)
            if status in {"rejected", "dismissed"}:
                runtime._clear_executable_review_locked()
            return status
    except Exception:
        return "computation_failure"
