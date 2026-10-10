"""C2A host-only authorization seam. No production executor or visible Start.

The current safe Review does not certify prompt bindings or finalized seeds.
Production therefore fails closed. A deliberately named characterization path
models certified human review and bounded executor acceptance without I/O.
"""
from dataclasses import dataclass, field, replace
import hashlib
import json
import secrets
from core import agent_facade
from ui.agent_generation_job import JobRequest
from ui.agent_generation_review_lifecycle import build_generation_review
from ui.project_agent_session_pump import ProjectAgentSessionRuntime

MAX_WORKFLOW_BYTES = 1_000_000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_FIELD_CHARS = 4096


def _encode(value):
    detached = agent_facade._json_copy(value, node_limit=200000, text_limit=MAX_MANIFEST_BYTES)
    stack = [detached]
    while stack:
        item = stack.pop()
        if type(item) is str and len(item) > MAX_FIELD_CHARS:
            raise ValueError("field limit")
        if type(item) is dict:
            stack.extend(item.keys())
            stack.extend(item.values())
        elif type(item) is list:
            stack.extend(item)
    encoded = json.dumps(detached, sort_keys=True, ensure_ascii=False,
                         allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest limit")
    return encoded


def _fingerprint(value):
    return hashlib.sha256(_encode(value)).hexdigest()


@dataclass(frozen=True)
class HumanStartAction:
    """Private callback carrier bound to this runtime, not an MCP approval flag."""
    session_incarnation: str = field(repr=False)
    proposal_id: str
    plan_id: str
    nonce: str = field(repr=False)


@dataclass(frozen=True)
class ReviewedExecutionCertificate:
    """Characterization-only evidence of separate complete executable review."""
    review_identity: str
    executable_identity: str
    destination: str = field(repr=False)
    output_location: str = field(repr=False)
    seed_policy: str


@dataclass(frozen=True)
class ExecutionRequest:
    request_id: str
    illustration_id: str
    run_index: int
    workflow_json: bytes = field(repr=False)
    workflow_identity: str


@dataclass(frozen=True)
class ExecutionManifest:
    """Immutable private bytes/scalars; no live Project, widgets or callbacks."""
    proposal_id: str
    plan_id: str
    requests: tuple
    parameters_json: bytes = field(repr=False)
    destination: str = field(repr=False)
    output_location: str = field(repr=False)
    seed_policy: str
    manifest_identity: str
    job_id: str | None = None
    claim_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class StartDecision:
    status: str
    job_id: str | None = None
    claim_id: str | None = field(default=None, repr=False)
    manifest: ExecutionManifest | None = field(default=None, repr=False)


def capture_human_start_action(runtime, proposal_id, plan_id):
    """Future direct human callback only; constructing this never starts work."""
    if type(runtime) is not ProjectAgentSessionRuntime or runtime._closed:
        return None
    record = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)
    if record.get("state") != "pending" or record.get("proposal_id") != proposal_id or record.get("plan_id") != plan_id:
        return None
    return HumanStartAction(runtime.generation_jobs._session_incarnation, proposal_id, plan_id, secrets.token_hex(16))


def certificate_for_characterization(preview, preflight, *, destination, output_location, seed_policy):
    """Test fixture only. C2B must replace with real host-reviewed certification."""
    return ReviewedExecutionCertificate(_fingerprint(preview), _fingerprint(preflight),
                                        destination, output_location, seed_policy)


def _manifest(action, preview, preflight, certificate):
    if (type(certificate) is not ReviewedExecutionCertificate or
            certificate.review_identity != _fingerprint(preview) or
            certificate.executable_identity != _fingerprint(preflight)):
        raise ValueError("uncertified workflow")
    if any(type(value) is not str or not 0 < len(value) <= MAX_FIELD_CHARS for value in
           (certificate.destination, certificate.output_location, certificate.seed_policy)):
        raise ValueError("invalid host destinations")
    if (certificate.destination != preflight["generation_options"].get("comfyui_endpoint") or
            certificate.output_location != preflight["generation_options"].get("output_directory")):
        raise ValueError("host destination mismatch")
    requests = preflight["request_plan"]
    if type(requests) is not list or not 1 <= len(requests) <= 100 or len(requests) != preview["request_count"]:
        raise ValueError("request limit")
    frozen = []
    total = 0
    for item in requests:
        workflow = preflight["workflow_plan"][item["workflow_key"]]["workflow_json"]
        encoded = _encode(workflow)
        if len(encoded) > MAX_WORKFLOW_BYTES:
            raise ValueError("workflow limit")
        total += len(encoded)
        if total > MAX_MANIFEST_BYTES:
            raise ValueError("aggregate limit")
        frozen.append(ExecutionRequest(item["request_id"], item["source_line_id"], item["run_index"],
                                       encoded, hashlib.sha256(encoded).hexdigest()))
    parameters = _encode(preflight["generation_options"])
    if total + len(parameters) > MAX_MANIFEST_BYTES:
        raise ValueError("aggregate limit")
    identity = _fingerprint([certificate.review_identity, certificate.executable_identity,
                            certificate.destination, certificate.output_location, certificate.seed_policy])
    return ExecutionManifest(action.proposal_id, action.plan_id, tuple(frozen), parameters,
                             certificate.destination, certificate.output_location, certificate.seed_policy, identity)


def authorize_generation_start(session_state, runtime, host_context_provider, action, *,
                               certificate=None, acceptance_for_characterization=None):
    """Revalidate outside locks; atomic custody/claim; fake bounded handoff only.

    No current production caller or UI invokes this. C2B must provide a bounded
    worker inbox reservation plus fully certified reviewed workflow/seed policy.
    """
    if (type(runtime) is not ProjectAgentSessionRuntime or type(action) is not HumanStartAction or
            action.session_incarnation != runtime.generation_jobs._session_incarnation):
        return StartDecision("invalid_human_action")
    review = build_generation_review(session_state, runtime, host_context_provider)
    if review.get("state") != "pending_current":
        return StartDecision(review.get("state", "validation_failure"))
    if (review["proposal_id"], review["plan_id"]) != (action.proposal_id, action.plan_id):
        return StartDecision("identity_mismatch")
    record = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)
    if (record.get("state") != "pending" or
            (record.get("proposal_id"), record.get("plan_id")) != (action.proposal_id, action.plan_id)):
        return StartDecision("stale_authorization")
    project, path = session_state.get("project"), session_state.get("current_project_path", "")
    registration = runtime._registration
    if registration is None:
        return StartDecision("session_unavailable")
    binding_values = [agent_facade.candidate_observation_handles.project_identity(project),
                      registration.route_id, path, record["pairing_generation"], review["target_epoch"]]
    preflight = {}
    fresh = agent_facade.preview_generation(project, record["intent"]["scene_id"],
                    run_count=record["intent"]["run_count"], host_context_provider=host_context_provider,
                    observation_binding=binding_values, _host_preflight=preflight)
    if type(fresh) is not dict or fresh.get("ok") is not True:
        return StartDecision("preparation_failed")
    if fresh != record["preview"]:
        runtime.mailbox.mark_review_proposal_stale(runtime.generation_review_custodian, action.proposal_id)
        return StartDecision("stale")
    # Existing Review explicitly says bindings/seeds are not certified. Do not
    # promote it to executable merely because its plan digest matches.
    if not runtime.generation_jobs._characterization:
        return StartDecision("executable_review_required")
    if not callable(acceptance_for_characterization):
        return StartDecision("executor_unavailable")
    try:
        manifest = _manifest(action, fresh, preflight, certificate)
    except Exception:
        return StartDecision("preparation_failed")
    custodian = runtime.generation_review_custodian
    with runtime._publication_gate:
        if runtime._closed or runtime._synchronize_target_locked(session_state.get("project"),
                           session_state.get("current_project_path", "")) != review["target_epoch"]:
            return StartDecision("stale_target")
        if session_state.get("project") is not project or session_state.get("current_project_path", "") != path:
            return StartDecision("stale_target")
        available, generation = runtime._registration.inspect_pairing_generation()
        if not available or (generation is not None and generation != record["pairing_generation"]):
            return StartDecision("session_unavailable")
        # The supported host full-run ownership excludes concurrent content
        # writers. Project/config mutations must use the same publication gate.
        with runtime.mailbox._lock:
            with custodian._lock:
                current = custodian._inspect_for_human_review_locked(custodian._clock())
                if current.get("state") != "pending" or any(current.get(key) != record.get(key) for key in
                     ("proposal_id", "plan_id", "preview", "intent", "target_epoch", "pairing_generation")):
                    return StartDecision("stale_authorization")
                binding = runtime.generation_jobs.host_binding(pairing_generation=current["pairing_generation"],
                                                             plan_identity=manifest.manifest_identity)
                requests = tuple(JobRequest(r.request_id, r.illustration_id, r.run_index, r.workflow_identity)
                                 for r in manifest.requests)
                receipt = runtime.generation_jobs.claim_authorized_for_characterization(binding, requests, action.nonce)
                if receipt.status != "claimed":
                    return StartDecision(receipt.status)
                manifest = replace(manifest, job_id=receipt.job_id, claim_id=receipt.claim_id)
                custodian._remember_record_locked(custodian._record, "proposal_cancelled")
                custodian._record = None
                custodian._revision += 1
                custodian._human_review_state = "authorization_consumed"
                runtime.mailbox._discard_review_ack_locked(action.proposal_id, "review_cancelled")
    # No host/mailbox/custodian/job lock spans executor acceptance. The test
    # callback must act like a nonblocking bounded inbox, not external execution.
    try:
        outcome = acceptance_for_characterization(receipt, manifest)
    except Exception:
        outcome = "unknown"
    if outcome != "accepted":
        outcome = "rejected" if outcome == "rejected" else "unknown"
        runtime.generation_jobs.settle_handoff_for_characterization(receipt.job_id, receipt.claim_id, outcome)
        return StartDecision("handoff_rejected" if outcome == "rejected" else "handoff_unknown", receipt.job_id)
    if runtime.generation_jobs.snapshot(receipt.job_id).get("state") != "claimed":
        return StartDecision("handoff_invalidated", receipt.job_id)
    return StartDecision("characterized_acceptance", receipt.job_id, receipt.claim_id, manifest)
