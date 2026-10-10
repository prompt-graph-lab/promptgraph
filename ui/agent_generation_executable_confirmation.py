"""Session-host executable observation and human acknowledgment; never Start.

Workflow reads/reconstruction happen outside custody locks. Publication uses
the runtime gate -> route operation -> mailbox -> Generation custodian order, without consuming
pending custody, claiming a job, or producing any execution certificate.
"""
from dataclasses import dataclass, field

from ui.agent_generation_executable_review import (
    ExecutableReview, build_executable_generation_review, inspect_executable_generation_review,
)
from ui.project_agent_session_pump import ProjectAgentSessionRuntime

_IDENTITY_KEYS = ("proposal_id", "plan_id", "preview", "intent", "target_epoch", "pairing_generation")
_INVALID = {"stale", "expired", "rejected", "dismissed", "absent", "invalid_review", "session_unavailable"}


@dataclass(frozen=True)
class SessionExecutableReview:
    review: ExecutableReview = field(repr=False)
    custody: dict = field(repr=False)
    session_incarnation: str = field(repr=False)
    revision: int


@dataclass(frozen=True)
class HumanExecutionDetailsConfirmation:
    """Acknowledgment only. Deliberately has no Start nonce, claim or receipt."""
    proposal_id: str = field(repr=False)
    origin_identity: str = field(repr=False)
    manifest_identity: str = field(repr=False)
    projection_json: bytes = field(repr=False)
    session_incarnation: str = field(repr=False)
    revision: int


def _record_locked(runtime, state):
    if runtime._closed or runtime._registration is None:
        return "session_unavailable", None
    try:
        epoch = runtime._synchronize_target_locked(state.get("project"), state.get("current_project_path", ""))
        available, pairing = runtime._registration.inspect_pairing_generation()
        if not available:
            return "verification_unavailable", None
        record = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)
    except Exception:
        return "verification_unavailable", None
    if record.get("state") != "pending":
        return record.get("state", "verification_unavailable"), None
    if (record.get("target_epoch") != epoch
            or (pairing is not None and pairing != record.get("pairing_generation"))):
        runtime._clear_executable_review_locked()
        return "stale", None
    return "pending", record


def _same(left, right):
    return all(left.get(key) == right.get(key) for key in _IDENTITY_KEYS)


def _confirmation(held):
    return HumanExecutionDetailsConfirmation(held.custody["proposal_id"], held.review.origin_identity,
        held.review.manifest.manifest_identity, held.review.projection_json, held.session_incarnation, held.revision)


def prepare_session_executable_review(state, runtime, provider, proposal_id, plan_id, *,
                                      refresh=False, expected_review=None, random_u64=None):
    """Direct Prepare/Refresh callback. Invalidate before drawing any new seed."""
    if type(runtime) is not ProjectAgentSessionRuntime:
        return "session_unavailable"
    with runtime._publication_gate:
        status, record = _record_locked(runtime, state)
        if record is None:
            return status
        if (record["proposal_id"], record["plan_id"]) != (proposal_id, plan_id):
            return "identity_mismatch"
        if refresh:
            if expected_review is None or runtime._executable_review is not expected_review:
                return "identity_mismatch"
        elif runtime._executable_target_epoch is not None:
            return "already_prepared" if runtime._executable_review is not None else "preparing"
        runtime._clear_executable_review_locked()
        revision = runtime._executable_revision
        runtime._executable_target_epoch = record["target_epoch"]
        runtime._executable_proposal_id = proposal_id
        project, path = state.get("project"), state.get("current_project_path", "")
    decision = build_executable_generation_review(state, runtime, provider, random_u64=random_u64)
    with runtime._publication_gate:
        status, current = _record_locked(runtime, state)
        if runtime._executable_revision != revision:
            return "stale"
        if (current is None or not _same(record, current) or state.get("project") is not project
                or state.get("current_project_path", "") != path):
            runtime._clear_executable_review_locked()
            return status if current is None else "stale"
        if decision.review is None:
            runtime._clear_executable_review_locked()
            return decision.status
        runtime._executable_review = SessionExecutableReview(decision.review, record,
            runtime.generation_jobs._session_incarnation, revision)
        return decision.status


def inspect_session_executable_review(state, runtime, provider):
    """Fresh safe view plus server callback carrier; navigation retains seeds."""
    if type(runtime) is not ProjectAgentSessionRuntime:
        return {"state": "session_unavailable"}, None
    with runtime._publication_gate:
        status, record = _record_locked(runtime, state)
        held = runtime._executable_review
        if record is None:
            return {"state": status}, None
        if held is None:
            return {"state": "unprepared"}, None
        if not _same(held.custody, record):
            runtime._clear_executable_review_locked()
            return {"state": "stale"}, None
    view = inspect_executable_generation_review(state, runtime, provider, held.review)
    with runtime._publication_gate:
        status, current = _record_locked(runtime, state)
        if runtime._executable_review is not held:
            return {"state": "stale"}, None
        if current is None or not _same(held.custody, current):
            if status != "verification_unavailable":
                runtime._clear_executable_review_locked()
            return {"state": status if current is None else "stale"}, None
        if view.get("state") in _INVALID:
            runtime._clear_executable_review_locked()
            return view, None
        if view.get("state") not in {"certified", "uncertifiable"}:
            return view, None  # A temporary failure neither confirms nor dismisses.
        view["human_confirmed"] = (held.review.manifest is not None
            and runtime._executable_confirmation == _confirmation(held))
        return view, held


def confirm_session_execution_details(state, runtime, provider, held):
    """Direct human callback bound to the server-held complete displayed bytes."""
    if type(runtime) is not ProjectAgentSessionRuntime or type(held) is not SessionExecutableReview:
        return "invalid_review"
    with runtime._publication_gate:
        if (runtime._closed or runtime._executable_review is not held
                or held.session_incarnation != runtime.generation_jobs._session_incarnation):
            return "identity_mismatch"
    view, current_held = inspect_session_executable_review(state, runtime, provider)
    if current_held is not held:
        return view.get("state", "identity_mismatch")
    if view.get("state") != "certified" or held.review.manifest is None:
        return view.get("state", "uncertifiable")
    # Reconstruction above compares every private workflow/seed and the exact
    # projection. Only bounded custody markers are checked under owner locks.
    with runtime._publication_gate:
        if runtime._closed:
            return "session_unavailable"
        route = runtime._registry._record_for_registration(runtime._registration)
        if route is None:
            return "session_unavailable"
        # Pairing replacement uses this same operation lock before registry /
        # mailbox access. Fence the final pairing check through acknowledgment;
        # never acquire a registry lock while holding mailbox/custodian locks.
        with route.operation_lock:
            status, record = _record_locked(runtime, state)
            if record is None:
                return status
            if runtime._executable_review is not held or not _same(held.custody, record):
                return "identity_mismatch"
            with runtime.mailbox._lock:
                with runtime.generation_review_custodian._lock:
                    try:
                        current = runtime.generation_review_custodian._inspect_for_human_review_locked(
                            runtime.generation_review_custodian._clock())
                    except Exception:
                        return "verification_unavailable"
                    if current.get("state") != "pending" or not _same(held.custody, current):
                        runtime._clear_executable_review_locked()
                        return "stale"
                    if runtime._executable_confirmation is not None:
                        return "already_confirmed" if runtime._executable_confirmation == _confirmation(held) else "conflicting_confirmation"
                    runtime._executable_confirmation = _confirmation(held)
                    return "confirmed"
