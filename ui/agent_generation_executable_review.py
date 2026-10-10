"""C2B-1 host-only observation. No human approval, custody consume or job claim.

The returned private carrier can be retained by a future human UI. Inspection
recomputes host inputs and rejects drift without rerolling its finalized seeds.
Neither the carrier nor its public projection is an execution certificate.
"""
from dataclasses import dataclass, field
import json

from core import agent_facade
from core.generation_executable_manifest import (
    FinalizedManifest, encode, fingerprint, finalize_generation_manifest,
)
from ui.agent_generation_review_lifecycle import build_generation_review
from ui.project_agent_session_pump import ProjectAgentSessionRuntime


@dataclass(frozen=True)
class ExecutableReview:
    manifest: FinalizedManifest | None = field(repr=False)
    projection_json: bytes
    origin_identity: str = field(repr=False)
    source_identity: str = field(repr=False)


@dataclass(frozen=True)
class ExecutableReviewDecision:
    status: str
    review: ExecutableReview | None = field(default=None, repr=False)


def _inputs(session_state, runtime, provider):
    if type(runtime) is not ProjectAgentSessionRuntime or runtime._closed:
        return "session_unavailable", None
    review = build_generation_review(session_state, runtime, provider)
    if review.get("state") != "pending_current":
        return review.get("state", "validation_failure"), None
    record = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)
    project, path = session_state.get("project"), session_state.get("current_project_path", "")
    registration = runtime._registration
    if registration is None or record.get("state") != "pending":
        return "session_unavailable", None
    binding = [agent_facade.candidate_observation_handles.project_identity(project), registration.route_id,
               path, record["pairing_generation"], review["target_epoch"]]
    preflight = {}
    fresh = agent_facade.preview_generation(project, record["intent"]["scene_id"],
                run_count=record["intent"]["run_count"], host_context_provider=provider,
                observation_binding=binding, _host_preflight=preflight)
    if fresh.get("ok") is not True:
        return "computation_failure", None
    if fresh != record["preview"]:
        runtime.mailbox.mark_review_proposal_stale(runtime.generation_review_custodian, record["proposal_id"])
        return "stale", None
    # Final revalidation also covers activation/pairing/custody changes during
    # preparation. This uses the existing full-run host writer contract.
    final = build_generation_review(session_state, runtime, provider)
    if final.get("state") != "pending_current":
        return final.get("state", "validation_failure"), None
    comparable = lambda value: {key: item for key, item in value.items() if key != "expires_in_seconds"}
    if (comparable(final) != comparable(review) or session_state.get("project") is not project
            or session_state.get("current_project_path", "") != path):
        return "stale", None
    origin = fingerprint([runtime.generation_jobs._session_incarnation, binding,
                          record["proposal_id"], record["plan_id"], record["intent"], record["preview"]])
    return "pending_current", (origin, fresh, preflight, record["proposal_id"])


def build_executable_generation_review(session_state, runtime, host_context_provider, *, random_u64=None):
    """Finalize once for future human inspection, preserving pending custody."""
    try:
        status, inputs = _inputs(session_state, runtime, host_context_provider)
        if inputs is None:
            return ExecutableReviewDecision(status)
        origin, preview, preflight, proposal_id = inputs
        finalized = finalize_generation_manifest(proposal_id, preview, preflight, random_u64=random_u64)
        # Finalization calls no host I/O; reject any reentrant random-source or
        # in-run Project/config changes before returning the review carrier.
        status, final = _inputs(session_state, runtime, host_context_provider)
        if final is None:
            return ExecutableReviewDecision(status)
        if final[0] != origin or fingerprint(final[2]) != fingerprint(preflight):
            return ExecutableReviewDecision("stale")
        carrier = ExecutableReview(finalized.manifest, finalized.projection_json, origin, fingerprint(preflight))
        return ExecutableReviewDecision("certified" if finalized.manifest else "uncertifiable", carrier)
    except Exception:
        # Raw host workflow/config/errors never cross the projection boundary.
        return ExecutableReviewDecision("preparation_failed")


def inspect_executable_generation_review(session_state, runtime, host_context_provider, review):
    """Return detached allowlisted view only while the exact proposal is current.

    Caller data cannot certify human confirmation: production C2A continues to
    return executable_review_required even when this observation is certified.
    """
    if type(review) is not ExecutableReview:
        return {"state": "invalid_review"}
    try:
        status, inputs = _inputs(session_state, runtime, host_context_provider)
        if inputs is None:
            return {"state": status}
        if inputs[0] != review.origin_identity or fingerprint(inputs[2]) != review.source_identity:
            return {"state": "stale"}
        seed_values = iter([seed["final_value"] for request in review.manifest.requests
                           for seed in json.loads(request.seed_provenance_json)] if review.manifest else [])
        rebuilt = finalize_generation_manifest(inputs[3], inputs[1], inputs[2],
                         random_u64=(lambda: next(seed_values)) if review.manifest else (lambda: 0))
        if rebuilt.manifest != review.manifest or rebuilt.projection_json != review.projection_json:
            return {"state": "invalid_review"}
        # Immutable bytes, detached view. No widget/session/Project is retained.
        projection = json.loads(review.projection_json)
        if encode(projection) != review.projection_json:
            return {"state": "invalid_review"}
        return projection
    except Exception:
        return {"state": "computation_failure"}
