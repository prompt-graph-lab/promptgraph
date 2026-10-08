"""Session-local custody for host-computed Scene Module Swap review proposals.

This owner retains only the bounded safe Agent Facade envelope and opaque
request bookkeeping. It has no Streamlit, Project, mailbox, transport, Apply,
or persistence dependency. Mailbox completion coordinates the private
prepare-to-pending transition under the fixed mailbox-then-custodian lock
order.
"""

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import secrets
import threading
import time

from core.agent_facade import MAX_ITEMS, MAX_TARGETS, SCENE_MODULE_SWAP_OPERATION
from core.agent_facade import CONTRACT_VERSION as FACADE_CONTRACT_VERSION
from core.agent_facade import MAX_TEXT


PROPOSAL_CONTRACT_VERSION = "promptgraph.agent-scene-module-swap-review.v1"
REVIEW_REQUEST_CONTRACT_VERSION = "promptgraph.agent-scene-module-swap-review-request.v1"
DEFAULT_PROPOSAL_TTL_SECONDS = 15 * 60
# One session proposal is retained for host review. Eight MiB leaves room for
# a full 100-row review with ordinary prompts and token deltas while keeping
# canonicalization, retained data, and later inspection copies bounded. The
# facade's theoretical maximum can be much larger; oversized proposals fail
# whole instead of being truncated or partially retained.
MAX_PROPOSAL_ENCODED_BYTES = 8 * 1024 * 1024
MAX_PREPARED_LIFETIME_SECONDS = 120
MAX_TOMBSTONES = 64

_MAX_ENVELOPE_DEPTH = 32
_MAX_ENVELOPE_NODES = 100_000
_MAX_REQUEST_ID_LENGTH = 128
_REASONS = frozenset({
    "host_review_unavailable",
    "stale_preview",
    "invalid_preview",
    "no_op_preview",
    "target_limit_exceeded",
    "review_already_pending",
    "request_id_conflict",
    "replay_not_accepted",
    "proposal_too_large",
    "proposal_expired",
    "stale_target",
    "session_closed",
    "review_unavailable",
    "proposal_cancelled",
})


@dataclass(frozen=True)
class PreparedProposalToken:
    """Internal, non-JSON token linking one prepared record to one mailbox claim."""

    _value: str
    _revision: int


@dataclass(frozen=True)
class PreparedReviewReply:
    """Internal bridge carrier; never crosses the mailbox/pipe JSON boundary."""

    reply: dict
    token: PreparedProposalToken


@dataclass(frozen=True)
class PendingReviewRetryToken:
    """Internal identity snapshot for one same-generation pending retry."""

    request_id: str
    pairing_generation: int
    target_epoch: str
    intent: dict
    intent_digest: str
    proposal_id: str
    acknowledgment_identity: str
    acknowledgment: dict


@dataclass(frozen=True)
class DuplicateReviewReply:
    """Internal retry carrier; completion must revalidate live custody."""

    reply: dict
    token: PendingReviewRetryToken


@dataclass(frozen=True)
class ReviewRequestDecision:
    """Bounded result from proposal preflight or preparation."""

    status: str
    result: dict | None = None
    token: PreparedProposalToken | None = None
    revision: int = 0
    retry_token: PendingReviewRetryToken | None = None


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


@dataclass(frozen=True)
class _Tombstone:
    pairing_generation: int
    intent_digest: str
    reason: str


def _plain_json(value):
    """Accept exact JSON built-ins without conversion hooks or cycles."""

    pending = [(value, 0, False)]
    active = set()
    nodes = 0
    try:
        while pending:
            item, depth, leaving = pending.pop()
            if leaving:
                active.remove(id(item))
                continue
            nodes += 1
            if nodes > _MAX_ENVELOPE_NODES or depth > _MAX_ENVELOPE_DEPTH:
                return False
            kind = type(item)
            if kind is str:
                item.encode("utf-8")
                continue
            if kind in (type(None), bool, int):
                continue
            if kind is float:
                if not math.isfinite(item):
                    return False
                continue
            if kind is dict:
                identity = id(item)
                if identity in active:
                    return False
                active.add(identity)
                pending.append((item, depth, True))
                for key, child in item.items():
                    if type(key) is not str:
                        return False
                    key.encode("utf-8")
                    pending.append((child, depth + 1, False))
                continue
            if kind is list:
                identity = id(item)
                if identity in active:
                    return False
                active.add(identity)
                pending.append((item, depth, True))
                pending.extend((child, depth + 1, False) for child in item)
                continue
            return False
    except Exception:
        return False
    return True


def _bounded_canonical_identity(value):
    """Hash/count canonical JSON within the custody cap, without retaining it."""

    if not _plain_json(value):
        return None, 0, "invalid_preview"
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    digest = hashlib.sha256()
    encoded_size = 0
    try:
        for chunk in encoder.iterencode(value):
            raw = chunk.encode("utf-8")
            encoded_size += len(raw)
            if encoded_size > MAX_PROPOSAL_ENCODED_BYTES:
                return None, encoded_size, "proposal_too_large"
            digest.update(raw)
    except Exception:
        return None, 0, "invalid_preview"
    return digest.hexdigest(), encoded_size, ""


def _intent_digest(intent):
    try:
        encoded = json.dumps(
            intent,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except Exception:
        return None
    return hashlib.sha256(encoded).hexdigest()


def _valid_preview_envelope(preview):
    top_keys = {
        "contract_version", "operation", "valid", "reason", "diagnostics",
        "request", "source_fingerprint", "projection_digest", "plan_id",
        "scene_id", "scene_label", "target_ids", "target_count", "changed_count",
        "no_op_count", "skipped_count", "blocked_count", "drift_count",
        "prompt_only", "negative_prompt_semantics", "review_rows",
        "review_rows_truncated", "review_rows_omitted",
    }
    if (type(preview) is not dict or set(preview) != top_keys
            or preview.get("contract_version") != FACADE_CONTRACT_VERSION
            or preview.get("valid") is not True
            or preview.get("reason") != ""
            or preview.get("diagnostics") != []
            or preview.get("prompt_only") is not True
            or preview.get("negative_prompt_semantics") != "unchanged_by_module_swap"):
        return False
    if preview.get("operation") != SCENE_MODULE_SWAP_OPERATION:
        return False

    def digest(value):
        return (type(value) is str and len(value) == 64
                and all(char in "0123456789abcdef" for char in value))

    def text_value(value):
        return (
            type(value) is dict
            and set(value) == {"text", "truncated", "length"}
            and type(value["text"]) is str
            and len(value["text"]) <= MAX_TEXT
            and type(value["truncated"]) is bool
            and type(value["length"]) is int
            and value["length"] >= len(value["text"])
            and value["truncated"] is (value["length"] > len(value["text"]))
        )

    if not all(digest(preview.get(key)) for key in (
            "source_fingerprint", "projection_digest", "plan_id")):
        return False
    request = preview.get("request")
    if (type(request) is not dict
            or set(request) != {"scene_id", "source_module_name", "target_module_name", "match_mode"}
            or any(type(request[key]) is not str or not request[key]
                   for key in ("scene_id", "source_module_name", "target_module_name"))
            or request.get("match_mode") not in ("strict", "loose")):
        return False
    if (type(preview.get("scene_id")) is not str
            or preview["scene_id"] != request["scene_id"]
            or not text_value(preview.get("scene_label"))):
        return False
    target_count = preview.get("target_count")
    changed_count = preview.get("changed_count")
    target_ids = preview.get("target_ids")
    review_rows = preview.get("review_rows")
    counters = (changed_count, preview.get("no_op_count"), preview.get("skipped_count"),
                preview.get("blocked_count"), preview.get("drift_count"),
                preview.get("review_rows_omitted"))
    if (type(target_count) is not int or not 1 <= target_count <= MAX_TARGETS
            or any(type(item) is not int or item < 0 for item in counters)
            or changed_count <= 0 or changed_count + preview["no_op_count"] != target_count
            or type(preview.get("review_rows_truncated")) is not bool
            or preview["review_rows_truncated"] is not (target_count > MAX_ITEMS)
            or preview["review_rows_omitted"] != max(0, target_count - MAX_ITEMS)
            or type(target_ids) is not list or len(target_ids) != target_count
            or any(type(item) is not str or not item or len(item) > 200 for item in target_ids)
            or len(set(target_ids)) != target_count
            or type(review_rows) is not list
            or len(review_rows) != min(target_count, MAX_ITEMS)):
        return False

    row_keys = {
        "illustration_id", "scene_order", "before_positive_prompt",
        "after_positive_prompt", "changed", "no_op", "token_delta",
        "match_count", "swap_kind", "drift_risk",
    }
    token_delta_keys = {
        "added", "removed", "added_count", "removed_count",
        "added_truncated", "removed_truncated",
    }
    for index, row in enumerate(review_rows):
        if (type(row) is not dict or set(row) != row_keys
                or row.get("illustration_id") != target_ids[index]
                or type(row.get("scene_order")) is not int or row["scene_order"] != index
                or not text_value(row.get("before_positive_prompt"))
                or not text_value(row.get("after_positive_prompt"))
                or type(row.get("changed")) is not bool or type(row.get("no_op")) is not bool
                or type(row.get("match_count")) is not int or row["match_count"] < 0
                or type(row.get("swap_kind")) is not str
                or type(row.get("drift_risk")) is not str):
            return False
        token_delta = row.get("token_delta")
        if type(token_delta) is not dict or set(token_delta) != token_delta_keys:
            return False
        for name in ("added", "removed"):
            tokens = token_delta.get(name)
            count = token_delta.get(name + "_count")
            truncated = token_delta.get(name + "_truncated")
            if (type(tokens) is not list or len(tokens) > MAX_ITEMS
                    or any(not text_value(item) for item in tokens)
                    or type(count) is not int or count < len(tokens)
                    or type(truncated) is not bool or truncated is not (count > len(tokens))):
                return False
    return True


class AgentSceneModuleSwapApprovalCustodian:
    """One bounded proposal slot owned by exactly one browser-session runtime."""

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
        elif not _valid_preview_envelope(preview):
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
            return {
                "contract_version": PROPOSAL_CONTRACT_VERSION,
                "state": self._human_review_state,
            }
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
        return "stale"

    def cancel_pending(self):
        """Cancel host custody explicitly; ordinary pipe release never calls this."""

        with self._lock:
            self._cancel_locked("proposal_cancelled")

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

    def _close_locked(self):
        self._closed = True
        self._revision += 1
        self._record = None
        self._tombstones.clear()
        self._human_review_state = "session_unavailable"

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
