"""Independent Generation review custody. No Apply or generation authority.

The prepare/pending/retry protocol follows Scene Module Swap custody, using
shared immutable carriers and bounded JSON helpers only; no shared state.
"""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import threading
import time
import secrets
from ui.agent_scene_module_swap_approval_lifecycle import (
    PreparedProposalToken, PendingReviewRetryToken, ReviewRequestDecision,
    _Tombstone, _bounded_canonical_identity, _intent_digest,
    DEFAULT_PROPOSAL_TTL_SECONDS, MAX_PREPARED_LIFETIME_SECONDS, MAX_TOMBSTONES,
    _MAX_REQUEST_ID_LENGTH, _REASONS,
)
PROPOSAL_CONTRACT_VERSION = "promptgraph.agent-generation-review.v1"
REVIEW_REQUEST_CONTRACT_VERSION = "promptgraph.agent-generation-review-request.v1"


@dataclass
class _ProposalRecord:
    state: str
    token: str
    proposal_id: str
    request_id: str
    pairing_generation: int
    target_epoch: str
    intent: dict
    intent_digest: str
    plan_id: str
    content_identity: str
    encoded_size_bytes: int
    preview: dict
    ack: dict
    acknowledgment_identity: str
    prepared_at: float
    prepared_expires_at: float
    expires_at: float | None = None


def _valid_preview_envelope(preview):
    from core.agent_facade import CONTRACT_VERSION
    keys = {"contract_version", "ok", "reason", "diagnostics", "valid", "scene_id", "scene_label", "run_count",
            "target_count", "request_count", "expected_image_count", "output_count_is_estimate",
            "illustrations", "expected_output_node_count", "skipped_count", "blocked_count", "skipped",
            "skipped_truncated", "plan_id", "workflow_summary", "warnings", "blockers",
            "review_requested", "job_submitted"}
    if (type(preview) is not dict or preview.get('contract_version') != CONTRACT_VERSION
            or set(preview) != keys or preview.get('reason') != "" or preview.get("diagnostics") != []
            or preview.get('ok') is not True or preview.get('valid') is not True
            or preview.get('job_submitted') is not False or preview.get('review_requested') is not False
            or type(preview.get('plan_id')) is not str or len(preview['plan_id']) != 64
            or type(preview.get('run_count')) is not int or not 1 <= preview['run_count'] <= 5
            or type(preview.get('target_count')) is not int or not 1 <= preview['target_count'] <= 100
            or type(preview.get('illustrations')) is not list
            or len(preview['illustrations']) != preview['target_count']
            or preview.get('blocked_count') != 0
            or preview.get('request_count') != preview['target_count'] * preview['run_count']):
        return False
    ids = [row.get('illustration_id') for row in preview['illustrations'] if type(row) is dict]
    row_keys = {"illustration_id", "project_order", "authored_positive_prompt", "authored_negative_prompt",
                "eligible", "blocker", "positive_prompt", "negative_prompt", "prompt_summary_kind",
                "workflow_binding_verified", "workflow_node_count", "image_output_node_count",
                "save_image_node_count", "warnings"}
    def text(value):
        return (type(value) is dict and set(value) == {"text", "truncated", "length"}
                and type(value["text"]) is str and len(value["text"]) <= 4000
                and type(value["length"]) is int and value["length"] >= len(value["text"])
                and type(value["truncated"]) is bool)
    counts = ("expected_image_count", "expected_output_node_count", "skipped_count", "blocked_count")
    if (any(type(preview[key]) is not int or preview[key] < 0 for key in counts)
            or type(preview["scene_id"]) is not str or not 0 < len(preview["scene_id"]) <= 200
            or preview["output_count_is_estimate"] is not True
            or type(preview["skipped_truncated"]) is not bool
            or type(preview["skipped"]) is not list or len(preview["skipped"]) > 100
            or any(type(item) is not dict or set(item) != {"illustration_id", "reason"}
                   or type(item["illustration_id"]) is not str or len(item["illustration_id"]) > 200
                   or item["reason"] not in {"workbench", "deleted"} for item in preview["skipped"])):
        return False
    return (len(ids) == preview['target_count'] and all(type(i) is str and 0 < len(i) <= 200 for i in ids)
            and len(set(ids)) == len(ids)
            and text(preview["scene_label"])
            and preview["blockers"] == []
            and preview["warnings"] == ["preview_only_no_job_submitted", "image_count_is_estimate",
                                        "execution_seeds_not_committed", "workflow_bindings_not_certified"]
            and preview["workflow_summary"] == {"source": "host_configured", "endpoint": "host_configured"}
            and all(set(row) == row_keys and row.get('eligible') is True
                    and row["blocker"] == "" and row["workflow_binding_verified"] is False
                    and row["prompt_summary_kind"] == "active_illustration_inputs"
                    and all(type(row[key]) is int and row[key] >= 0 for key in
                            ("project_order", "workflow_node_count", "image_output_node_count", "save_image_node_count"))
                    and all(text(row[key]) for key in ("authored_positive_prompt", "authored_negative_prompt",
                                                      "positive_prompt", "negative_prompt"))
                    and row["warnings"] in ([], ["prompt_binding_requires_review"])
                    for row in preview['illustrations']))

class AgentGenerationReviewCustodian:
    def __init__(self, *, clock=time.monotonic):
        if not callable(clock):
            raise ValueError("invalid proposal clock")
        self._clock = clock
        self._lock = threading.RLock()
        self._closed = False
        self._target_epoch = None
        self._revision = 0
        self._record = None
        self._tombstones = OrderedDict()
        self._human_review_state = "absent"
        self._human_review_result = None

    def check_request(self, request_id, pairing_generation, target_epoch, intent):
        """Resolve same-generation retries and conflicts before Project capture."""

        digest = _intent_digest(intent)
        if (type(request_id) is not str or not 0 < len(request_id) <= _MAX_REQUEST_ID_LENGTH
                or type(pairing_generation) is not int or pairing_generation <= 0
                or type(target_epoch) is not str or not target_epoch or digest is None):
            return ReviewRequestDecision("review_unavailable")

        now = self._clock()
        with self._lock:
            self._expire_locked(now)
            if self._closed:
                return ReviewRequestDecision("session_closed")
            if target_epoch != self._target_epoch:
                return ReviewRequestDecision("stale_target")

            if self._record is not None and self._record.pairing_generation != pairing_generation:
                self._remember_record_locked(self._record, "stale_target")
                self._record = None
                self._revision += 1
                self._human_review_state = "stale"

            tombstone = self._tombstones.get(request_id)
            if tombstone is not None:
                if tombstone.pairing_generation != pairing_generation:
                    return ReviewRequestDecision("replay_not_accepted")
                if tombstone.intent_digest != digest:
                    return ReviewRequestDecision("request_id_conflict")
                return ReviewRequestDecision(tombstone.reason)

            record = self._record
            if record is not None:
                if record.request_id == request_id:
                    if record.pairing_generation != pairing_generation:
                        return ReviewRequestDecision("replay_not_accepted")
                    if record.intent_digest != digest:
                        return ReviewRequestDecision("request_id_conflict")
                    if record.state == "pending":
                        return self._retry_pending_locked(record)
                    return ReviewRequestDecision("review_already_pending")
                if record.state in ("prepared", "pending"):
                    return ReviewRequestDecision("review_already_pending")
            return ReviewRequestDecision("new", revision=self._revision)

    def prepare(self, request_id, pairing_generation, target_epoch, intent,
                expected_revision, preview):
        """Detach and size-check a fresh host-computed envelope before reserving."""

        digest = _intent_digest(intent)
        if (digest is None or type(request_id) is not str
                or not 0 < len(request_id) <= _MAX_REQUEST_ID_LENGTH
                or type(pairing_generation) is not int or pairing_generation <= 0
                or type(target_epoch) is not str or not target_epoch):
            return ReviewRequestDecision("review_unavailable")

        content_identity, encoded_size, encoding_reason = _bounded_canonical_identity(preview)
        if encoding_reason:
            size_reason = encoding_reason
            detached = None
        elif (not _valid_preview_envelope(preview) or type(intent) is not dict
              or set(intent) != {"scene_id", "run_count", "expected_plan_id"}
              or intent["scene_id"] != preview["scene_id"] or intent["run_count"] != preview["run_count"]
              or intent["expected_plan_id"] != preview["plan_id"]):
            size_reason = "invalid_preview"
            detached = None
            content_identity = None
            encoded_size = None
        else:
            try:
                detached = deepcopy(preview)
            except Exception:
                detached = None
            size_reason = "" if type(detached) is dict else "invalid_preview"

        now = self._clock()
        with self._lock:
            self._expire_locked(now)
            if self._closed:
                return ReviewRequestDecision("session_closed")
            if target_epoch != self._target_epoch:
                self._remember_locked(request_id, pairing_generation, digest, "stale_target")
                return ReviewRequestDecision("stale_target")
            if expected_revision != self._revision:
                self._remember_locked(request_id, pairing_generation, digest, "review_unavailable")
                return ReviewRequestDecision("review_unavailable")

            prior = self._tombstones.get(request_id)
            if prior is not None:
                if prior.pairing_generation != pairing_generation:
                    return ReviewRequestDecision("replay_not_accepted")
                if prior.intent_digest != digest:
                    return ReviewRequestDecision("request_id_conflict")
                return ReviewRequestDecision(prior.reason)

            record = self._record
            if record is not None:
                if record.request_id == request_id:
                    if record.pairing_generation != pairing_generation:
                        return ReviewRequestDecision("replay_not_accepted")
                    if record.intent_digest != digest:
                        return ReviewRequestDecision("request_id_conflict")
                    if record.state == "pending":
                        return self._retry_pending_locked(record)
                return ReviewRequestDecision("review_already_pending")

            if size_reason:
                self._remember_locked(request_id, pairing_generation, digest, size_reason)
                return ReviewRequestDecision(size_reason)

            token_value = secrets.token_urlsafe(32)
            proposal_id = secrets.token_urlsafe(24)
            plan_id = detached["plan_id"]
            ack = {
                "review_request_contract_version": REVIEW_REQUEST_CONTRACT_VERSION,
                "ok": True,
                "status": "queued_for_review",
                "proposal_id": proposal_id,
                "plan_id": plan_id,
                "content_identity": content_identity,
                "expires_in_seconds": DEFAULT_PROPOSAL_TTL_SECONDS,
            }
            acknowledgment_identity = secrets.token_urlsafe(24)
            self._record = _ProposalRecord(
                state="prepared",
                token=token_value,
                proposal_id=proposal_id,
                request_id=request_id,
                pairing_generation=pairing_generation,
                target_epoch=target_epoch,
                intent=deepcopy(intent),
                intent_digest=digest,
                plan_id=plan_id,
                content_identity=content_identity,
                encoded_size_bytes=encoded_size,
                preview=detached,
                ack=ack,
                acknowledgment_identity=acknowledgment_identity,
                prepared_at=now,
                prepared_expires_at=now + MAX_PREPARED_LIFETIME_SECONDS,
            )
            self._human_review_state = "prepared"
            self._human_review_result = None
            return ReviewRequestDecision(
                "prepared",
                result=deepcopy(ack),
                token=PreparedProposalToken(token_value, expected_revision),
                revision=expected_revision,
            )

    def _retry_pending_locked(self, record):
        """Return the exact ack plus identity needed for coordinated publish."""

        return ReviewRequestDecision(
            "retry_pending",
            result=deepcopy(record.ack),
            retry_token=PendingReviewRetryToken(
                request_id=record.request_id,
                pairing_generation=record.pairing_generation,
                target_epoch=record.target_epoch,
                intent=deepcopy(record.intent),
                intent_digest=record.intent_digest,
                proposal_id=record.proposal_id,
                acknowledgment_identity=record.acknowledgment_identity,
                acknowledgment=deepcopy(record.ack),
            ),
        )

    def remember_failure(self, request_id, pairing_generation, target_epoch, intent,
                         expected_revision, reason):
        """Boundedly remember a failed normalized correlation without a proposal."""

        digest = _intent_digest(intent)
        if (digest is None or reason not in _REASONS
                or type(request_id) is not str
                or type(pairing_generation) is not int):
            return False
        with self._lock:
            self._expire_locked(self._clock())
            if (self._closed or expected_revision != self._revision
                    or target_epoch != self._target_epoch or self._record is not None):
                return False
            self._remember_locked(request_id, pairing_generation, digest, reason)
            return True

    def inspect(self):
        """Return a detached host-only snapshot for tests and later UI wiring."""

        with self._lock:
            self._expire_locked(self._clock())
            record = self._record
            if record is None:
                return {"contract_version": PROPOSAL_CONTRACT_VERSION, "state": "absent"}
            return {
                "contract_version": PROPOSAL_CONTRACT_VERSION,
                "state": record.state,
                "proposal_id": record.proposal_id,
                "request_id": record.request_id,
                "pairing_generation": record.pairing_generation,
                "target_epoch": record.target_epoch,
                "intent": deepcopy(record.intent),
                "plan_id": record.plan_id,
                "content_identity": record.content_identity,
                "encoded_size_bytes": record.encoded_size_bytes,
                "expires_at": record.expires_at,
                "preview": deepcopy(record.preview),
            }

    def inspect_for_human_review(self):
        """Return only the current proposal needed by the session's human UI."""

        with self._lock:
            return self._inspect_for_human_review_locked(self._clock())

    def _inspect_for_human_review_locked(self, now):
        """Build a human-review snapshot with the custodian lock already held."""

        self._expire_locked(now)
        record = self._record
        if self._closed:
            return {
                "contract_version": PROPOSAL_CONTRACT_VERSION,
                "state": "session_unavailable",
            }
        if record is None:
            result = {
                "contract_version": PROPOSAL_CONTRACT_VERSION,
                "state": self._human_review_state,
            }
            if self._human_review_result is not None:
                result["result"] = dict(self._human_review_result)
            return result
        if record.state == "prepared":
            # Prepared custody is deliberately invisible until the mailbox
            # reply and proposal commit complete together.
            return {
                "contract_version": PROPOSAL_CONTRACT_VERSION,
                "state": "prepared",
            }
        return {
            "contract_version": PROPOSAL_CONTRACT_VERSION,
            "state": "pending",
            "proposal_id": record.proposal_id,
            "target_epoch": record.target_epoch,
            "intent": deepcopy(record.intent),
            "plan_id": record.plan_id,
            "preview": deepcopy(record.preview),
            "expires_in_seconds": max(0, int(record.expires_at - self._clock())),
        }

    def resolve_pending(self, proposal_id, action):
        """Consume one exact pending proposal as rejected or dismissed."""

        if action not in {"reject", "dismiss"}:
            return "invalid_action"
        with self._lock:
            return self._resolve_pending_locked(proposal_id, action, self._clock())

    def _resolve_pending_locked(self, proposal_id, action, now):
        """Resolve a pending proposal with the custodian lock already held."""

        self._expire_locked(now)
        if self._closed:
            return "session_unavailable"
        record = self._record
        if (record is None or record.state != "pending"
                or type(proposal_id) is not str
                or record.proposal_id != proposal_id):
            return self._human_review_state
        if action not in {"reject", "dismiss"}:
            return "invalid_action"
        state = "rejected" if action == "reject" else "dismissed"
        self._remember_record_locked(record, "proposal_cancelled")
        self._record = None
        self._revision += 1
        self._human_review_state = state
        return state

    def mark_pending_stale(self, proposal_id):
        """Consume a proposal whose fresh content no longer matches custody."""

        with self._lock:
            return self._mark_pending_stale_locked(proposal_id, self._clock())

    def _mark_pending_stale_locked(self, proposal_id, now):
        """Mark one pending proposal stale with the custodian lock already held."""

        self._expire_locked(now)
        if self._closed:
            return "session_unavailable"
        record = self._record
        if (record is None or record.state != "pending"
                or type(proposal_id) is not str
                or record.proposal_id != proposal_id):
            return self._human_review_state
        self._remember_record_locked(record, "stale_target")
        self._record = None
        self._revision += 1
        self._human_review_state = "stale"
        self._human_review_result = None
        return "stale"

    def cancel_pending(self):
        """Cancel host custody explicitly; ordinary pipe release never calls this."""

        with self._lock:
            self._cancel_locked("proposal_cancelled")

    def _fail_publication_locked(self, carrier, now):
        """Stale only the exact prepared/pending carrier; never a human action."""
        from ui.agent_scene_module_swap_approval_lifecycle import PreparedReviewReply, DuplicateReviewReply
        self._expire_locked(now)
        record = self._record
        if self._closed or record is None:
            return False
        if type(carrier) is PreparedReviewReply:
            token = carrier.token
            matches = (type(token) is PreparedProposalToken and record.state == "prepared"
                       and token._value == record.token and token._revision == self._revision)
        elif type(carrier) is DuplicateReviewReply:
            token = carrier.token
            matches = (type(token) is PendingReviewRetryToken and record.state == "pending"
                       and token.proposal_id == record.proposal_id
                       and token.request_id == record.request_id
                       and token.pairing_generation == record.pairing_generation
                       and token.target_epoch == record.target_epoch
                       and token.intent_digest == record.intent_digest
                       and token.acknowledgment_identity == record.acknowledgment_identity)
        else:
            matches = False
        if not matches:
            return False
        self._remember_record_locked(record, "stale_preview")
        self._record = None
        self._revision += 1
        self._human_review_state = "stale"
        self._human_review_result = None
        return True

    def close(self):
        """Drop every proposal and prevent later preparation or commitment."""

        with self._lock:
            self._close_locked()

    def synchronize_target_epoch(self, target_epoch):
        """Invalidate host custody when the session activates another target.

        The mailbox calls the private locked form while it already owns the
        mailbox lock, preserving the global mailbox-then-custodian order.
        """

        with self._lock:
            return self._synchronize_target_epoch_locked(target_epoch)

    def _synchronize_target_epoch_locked(self, target_epoch):
        if type(target_epoch) is not str or not target_epoch or self._closed:
            return False
        if target_epoch == self._target_epoch:
            return False
        self._target_epoch = target_epoch
        self._revision += 1
        if self._record is not None:
            self._remember_record_locked(self._record, "stale_target")
            self._record = None
            self._human_review_state = "stale"
            self._human_review_result = None
        return True

    def _commit_prepared_locked(self, token, *, request_id, pairing_generation,
                                target_epoch, reply, now):
        """Commit prepared custody while caller holds mailbox then this lock."""

        self._expire_locked(now)
        record = self._record
        if (self._closed or type(token) is not PreparedProposalToken
                or record is None or record.state != "prepared"
                or token._revision != self._revision
                or token._value != record.token
                or record.request_id != request_id
                or record.pairing_generation != pairing_generation
                or record.target_epoch != target_epoch
                or self._target_epoch != target_epoch
                or now >= record.prepared_expires_at
                or type(reply) is not dict
                or set(reply) != {
                    "bridge_contract_version", "request_id", "status", "result",
                }
                or reply.get("bridge_contract_version") != (
                    "promptgraph.app-agent-request-bridge.v1"
                )
                or reply.get("request_id") != request_id
                or reply.get("status") != "completed"
                or type(reply.get("result")) is not dict
                or reply["result"] != record.ack):
            return False

        # This single state transition is the custody acceptance linearization
        # point. Mailbox consume_reply remains excluded by its outer lock.
        record.state = "pending"
        record.expires_at = now + DEFAULT_PROPOSAL_TTL_SECONDS
        self._human_review_state = "pending"
        return True

    def _rollback_prepared_locked(self, token):
        """Remove a token if a coordinated mailbox publication fails."""

        record = self._record
        if (type(token) is not PreparedProposalToken or record is None
                or token._value != record.token):
            return False
        self._remember_record_locked(record, "review_unavailable")
        self._record = None
        self._revision += 1
        self._human_review_state = "computation_failure"
        return True

    def _abort_prepared_locked(self, token, reason="review_unavailable"):
        record = self._record
        if (type(token) is not PreparedProposalToken or record is None
                or token._value != record.token or record.state != "prepared"):
            return False
        if reason not in _REASONS:
            reason = "review_unavailable"
        self._remember_record_locked(record, reason)
        self._record = None
        self._revision += 1
        self._human_review_state = "computation_failure"
        return True

    def _abort_prepared_for_claim_locked(self, request_id, pairing_generation,
                                         target_epoch, reason="review_unavailable"):
        """Discard an uncommitted record owned by this exact mailbox claim."""

        record = self._record
        if (record is None or record.state != "prepared"
                or record.request_id != request_id
                or record.pairing_generation != pairing_generation
                or record.target_epoch != target_epoch):
            return False
        if reason not in _REASONS:
            reason = "review_unavailable"
        self._remember_record_locked(record, reason)
        self._record = None
        self._revision += 1
        self._human_review_state = "computation_failure"
        return True

    def _cancel_locked(self, reason):
        self._revision += 1
        if self._record is not None:
            self._remember_record_locked(self._record, reason)
            self._record = None
            self._human_review_state = "dismissed"
            self._human_review_result = None

    def _close_locked(self):
        self._closed = True
        self._revision += 1
        self._record = None
        self._tombstones.clear()
        self._human_review_state = "session_unavailable"
        self._human_review_result = None

    def _expire_locked(self, now):
        record = self._record
        if record is None:
            return
        if record.state == "prepared" and now >= record.prepared_expires_at:
            self._remember_record_locked(record, "review_unavailable")
            self._record = None
            self._revision += 1
            self._human_review_state = "computation_failure"
        elif record.state == "pending" and record.expires_at is not None and now >= record.expires_at:
            self._remember_record_locked(record, "proposal_expired")
            self._record = None
            self._revision += 1
            self._human_review_state = "expired"

    def _remember_record_locked(self, record, reason):
        self._remember_locked(
            record.request_id,
            record.pairing_generation,
            record.intent_digest,
            reason,
        )

    def _remember_locked(self, request_id, pairing_generation, digest, reason):
        if (type(request_id) is not str or not request_id
                or type(pairing_generation) is not int or type(digest) is not str):
            return
        tombstone = _Tombstone(pairing_generation, digest, reason)
        self._tombstones.pop(request_id, None)
        self._tombstones[request_id] = tombstone
        while len(self._tombstones) > MAX_TOMBSTONES:
            self._tombstones.popitem(last=False)
