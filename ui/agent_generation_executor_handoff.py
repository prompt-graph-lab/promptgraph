"""C2B-3 private host/fake-worker boundary. Production execution stays disabled.

This does not call C2A's acceptance callback or accept its test certificate.
Only the actual server-held finalized review and exact human acknowledgment
can supply data, and even those cannot start a production inbox/job registry.
"""
from dataclasses import dataclass, field
import secrets

from ui.agent_generation_executable_confirmation import (
    _confirmation, _record_locked, _same, inspect_session_executable_review,
)
from ui.agent_generation_executor_inbox import ExecutionEnvelope, HandoffReceipt
from core.comfy_remote_output_receipts import RemoteOutputReceipt
from core.comfy_output_containment import LocalOutputReceipt
from ui.agent_generation_job import JobRequest, _PROCESS_INCARNATION
from ui.project_agent_session_pump import ProjectAgentSessionRuntime


@dataclass(frozen=True)
class ExecutorHumanStartAction:
    """Private simulated callback; bound to the confirmed review, never IDs alone."""
    session_incarnation: str = field(repr=False)
    proposal_id: str
    plan_id: str
    origin_identity: str = field(repr=False)
    manifest_identity: str = field(repr=False)
    review_revision: int
    nonce: str = field(repr=False)


def capture_executor_human_start_for_characterization(runtime):
    """New simulated human action after confirmation; no production authority."""
    if type(runtime) is not ProjectAgentSessionRuntime:
        return None
    with runtime._publication_gate:
        held = runtime._executable_review
        if (runtime._closed or not runtime.generation_jobs._characterization
                or not runtime._generation_executor_inbox._characterization
                or held is None or held.review.manifest is None
                or runtime._executable_confirmation != _confirmation(held)):
            return None
        manifest = held.review.manifest
        return ExecutorHumanStartAction(held.session_incarnation, manifest.proposal_id, manifest.plan_id,
            held.review.origin_identity, manifest.manifest_identity, held.revision, secrets.token_hex(16))


def handoff_generation_for_characterization(state, runtime, provider, action, *, fake_worker):
    """Fresh exact confirmation + distinct simulated human Start + bounded take.

    No production caller or UI is wired. Callback runs after all owner locks;
    it receives only an offer receipt and must take the inbox before progress.
    It never grants authority by merely returning the string 'accepted'.
    """
    if type(runtime) is not ProjectAgentSessionRuntime:
        return HandoffReceipt("invalid_human_action")
    inbox, jobs = runtime._generation_executor_inbox, runtime.generation_jobs
    if not inbox._characterization or not jobs._characterization:
        return HandoffReceipt("execution_unavailable")
    if (type(action) is not ExecutorHumanStartAction
            or action.session_incarnation != jobs._session_incarnation):
        return HandoffReceipt("invalid_human_action")
    if not callable(fake_worker):
        return HandoffReceipt("executor_unavailable")
    view, held = inspect_session_executable_review(state, runtime, provider)
    if held is None or view.get("state") != "certified":
        return HandoffReceipt(view.get("state", "verification_unavailable"))
    if not view.get("human_confirmed"):
        return HandoffReceipt("human_confirmation_required")
    manifest = held.review.manifest
    if (manifest.proposal_id, manifest.plan_id) != (action.proposal_id, action.plan_id):
        return HandoffReceipt("identity_mismatch")
    if (held.review.origin_identity, manifest.manifest_identity, held.revision) != (
            action.origin_identity, action.manifest_identity, action.review_revision):
        return HandoffReceipt("stale_human_action")
    project, path = state.get("project"), state.get("current_project_path", "")
    # Encoding/reconstruction/bounds work runs before bounded atomic markers.
    reservation = inbox.reserve_for_characterization(manifest)
    if reservation.status != "reserved":
        return HandoffReceipt(reservation.status)
    transferred = False
    try:
        with runtime._publication_gate:
            if runtime._closed or runtime._registration is None:
                return HandoffReceipt("session_unavailable")
            route = runtime._registry._record_for_registration(runtime._registration)
            if route is None:
                return HandoffReceipt("session_unavailable")
            # Pairing replacement uses the same operation lock. No registry
            # lock is acquired under mailbox/custodian/job/inbox locks.
            with route.operation_lock:
                status, record = _record_locked(runtime, state)
                if record is None:
                    return HandoffReceipt(status)
                if (runtime._executable_review is not held or not _same(held.custody, record)
                        or runtime._executable_confirmation != _confirmation(held)
                        or state.get("project") is not project or state.get("current_project_path", "") != path):
                    return HandoffReceipt("stale_authorization")
                custodian = runtime.generation_review_custodian
                with runtime.mailbox._lock:
                    with custodian._lock:
                        current = custodian._inspect_for_human_review_locked(custodian._clock())
                        if current.get("state") != "pending" or not _same(current, held.custody):
                            return HandoffReceipt("stale_authorization")
                        binding = jobs.host_binding(pairing_generation=current["pairing_generation"],
                                                    plan_identity=manifest.manifest_identity)
                        requests = tuple(JobRequest(r.request_id, r.illustration_id, r.run_index, r.workflow_identity)
                                         for r in manifest.requests)
                        with jobs._lock:
                            with inbox._lock:
                                # Capacity may expire during fresh validation.
                                if (inbox._closed or inbox._state != "reserved"
                                        or inbox._reservation != reservation.reservation_id
                                        or inbox._clock() >= inbox._deadline):
                                    return HandoffReceipt("reservation_unavailable")
                                claim = jobs.claim_authorized_for_characterization(binding, requests, action.nonce)
                                if claim.status != "claimed":
                                    return HandoffReceipt(claim.status)
                                envelope = ExecutionEnvelope(binding, held.review.origin_identity, manifest,
                                                             claim.job_id, claim.claim_id)
                                # Durable here means stored in the session job
                                # owner before take, not disk/restart durability.
                                committed = inbox._commit_locked(reservation, envelope)
                                custodian._remember_record_locked(custodian._record, "proposal_cancelled")
                                custodian._record = None
                                custodian._revision += 1
                                custodian._human_review_state = "authorization_consumed"
                                runtime.mailbox._discard_review_ack_locked(action.proposal_id, "review_cancelled")
                                runtime._clear_executable_review_locked()
                                # Linearization: committed offer + consumed
                                # custody become observable when owner locks
                                # release; no worker can take before this point.
                                transferred = True
                                offer = HandoffReceipt("offered", claim.job_id, claim.claim_id,
                                                       manifest.manifest_identity)
                                if not committed:
                                    # An internal post-claim failure still
                                    # consumes custody and pins the slot. Never
                                    # expose a recoverable proposal after claim.
                                    inbox._envelope = envelope
                                    inbox._state = "offered"
                                    return inbox.settle_for_characterization(jobs, offer, "unknown")
        try:
            response = fake_worker(offer)
        except Exception:
            response = None
        if type(response) is HandoffReceipt and response == HandoffReceipt(
                "accepted", offer.job_id, offer.claim_id, offer.manifest_identity):
            if not _handoff_target_current(state, runtime, offer):
                return HandoffReceipt("handoff_invalidated", offer.job_id)
            accepted = inbox.accepted_receipt(jobs, offer)
            if accepted.status != "handoff_unknown":
                return accepted
        outcome = ("rejected" if type(response) is HandoffReceipt and response == HandoffReceipt(
            "rejected", offer.job_id, offer.claim_id, offer.manifest_identity) else "unknown")
        return inbox.settle_for_characterization(jobs, offer, outcome)
    finally:
        if not transferred:
            inbox.release_reservation(reservation)


def _handoff_target_current(state, runtime, offer):
    with runtime._publication_gate:
        if runtime._closed or runtime._registration is None:
            return False
        route = runtime._registry._record_for_registration(runtime._registration)
        if route is None:
            return False
        with route.operation_lock:
            epoch = runtime._synchronize_target_locked(state.get("project"), state.get("current_project_path", ""))
            available, pairing = runtime._registration.inspect_pairing_generation()
            jobs = runtime.generation_jobs
            with jobs._lock:
                job = jobs._authorized_locked(offer.job_id, offer.claim_id)
                current = (available and job is not None and job.binding.target_epoch == epoch
                           and (pairing is None or job.binding.pairing_generation == pairing))
                if not current and job is not None:
                    jobs.invalidate_execution_custody()
                return bool(current)


def deliver_executor_event_for_characterization(state, runtime, event):
    """Original host fences activation and pairing before recording fake events.

    Outputs only record count/opaque receipt evidence. Host publication and save
    remain separate registry contracts, with no Candidate/history/file writes.
    """
    if type(runtime) is not ProjectAgentSessionRuntime:
        return "session_unavailable"
    jobs, inbox = runtime.generation_jobs, runtime._generation_executor_inbox
    with runtime._publication_gate:
        if runtime._closed or runtime._registration is None:
            return inbox.event_for_characterization(jobs, event, target_current=False)
        route = runtime._registry._record_for_registration(runtime._registration)
        if route is None:
            return inbox.event_for_characterization(jobs, event, target_current=False)
        with route.operation_lock:
            epoch = runtime._synchronize_target_locked(state.get("project"), state.get("current_project_path", ""))
            available, pairing = runtime._registration.inspect_pairing_generation()
            with jobs._lock:
                job = jobs._authorized_locked(getattr(event, "job_id", None), getattr(event, "claim_id", None))
                current = (available and job is not None and job.binding.target_epoch == epoch
                           and job.binding.session_id == jobs._session_incarnation
                           and job.binding.process_incarnation == _PROCESS_INCARNATION
                           and (job.binding.target_epoch, job.binding.activation_id) == jobs._target
                           and type(pairing) is int and job.binding.pairing_generation == pairing)
                return inbox.event_for_characterization(jobs, event, target_current=bool(current))


def local_output_custody_current_for_characterization(state, runtime, envelope, remote, local=None):
    """Original host checks before/after unlocked download/decode. No disk I/O.

    Publication remains a later separate contract. Exact activation fencing
    prevents old receipts entering a Project even after switching back.
    """
    if (type(runtime) is not ProjectAgentSessionRuntime or type(envelope) is not ExecutionEnvelope
            or type(remote) is not RemoteOutputReceipt):
        return False
    correlation = (envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity)
    if (remote.job_id, remote.claim_id, remote.manifest_identity) != correlation:
        return False
    index = remote.request_index
    if type(index) is not int or not 0 <= index < len(envelope.manifest.requests):
        return False
    request = envelope.manifest.requests[index]
    if (remote.request_id, remote.workflow_identity) != (request.request_id, request.workflow_identity):
        return False
    if local is not None and (type(local) is not LocalOutputReceipt or local.state != "verified"
            or (local.job_id, local.claim_id, local.manifest_identity) != correlation
            or (local.request_id, local.request_index, local.workflow_identity, local.prompt_id,
                local.remote_receipt_identity) != (remote.request_id, index, remote.workflow_identity,
                                                   remote.prompt_id, remote.identity)
            or local.verified_count != len(remote.images) or local.downloaded_count != len(remote.images)
            or tuple(image.descriptor_identity for image in local.images) != tuple(image.identity for image in remote.images)
            or not remote.execution_succeeded):
        return False
    jobs, inbox = runtime.generation_jobs, runtime._generation_executor_inbox
    if not jobs._characterization or not inbox._characterization:
        return False
    with runtime._publication_gate:
        if runtime._closed or runtime._registration is None:
            return False
        route = runtime._registry._record_for_registration(runtime._registration)
        if route is None:
            return False
        with route.operation_lock:
            epoch = runtime._synchronize_target_locked(state.get("project"), state.get("current_project_path", ""))
            available, pairing = runtime._registration.inspect_pairing_generation()
            with jobs._lock:
                jobs._cleanup_locked(jobs._clock())
                job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                with inbox._lock:
                    return bool(available and job is not None and job.binding == envelope.binding
                        and job.binding.session_id == jobs._session_incarnation
                        and job.binding.process_incarnation == _PROCESS_INCARNATION
                        and job.binding.target_epoch == epoch
                        and (job.binding.target_epoch, job.binding.activation_id) == jobs._target
                        and type(pairing) is int and job.binding.pairing_generation == pairing
                        and inbox._envelope is envelope and inbox._state == "accepted" and not inbox._closed
                        and job.request_states[index] == "awaiting_download"
                        and job.requests[index] == JobRequest(request.request_id, request.illustration_id,
                                                             request.run_index, request.workflow_identity))
