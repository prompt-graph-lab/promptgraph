"""Thread-safe, transport-neutral mailbox for one PromptGraph session.

This module intentionally has no Streamlit, Project, adapter, or persistence
dependency. A future process-level producer may retain a mailbox reference,
but it cannot use that reference to read a Project or Streamlit session.
"""

from dataclasses import dataclass
import math
import os
import threading
import time
import uuid
import weakref


DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0
MAX_REQUEST_TIMEOUT_SECONDS = 120.0
FRAGMENT_POLL_INTERVAL_SECONDS = 1.0
MAX_WAKE_RETRY_SECONDS = 5.0

# These are generic plain-JSON resource bounds. They match the existing app
# bridge's request boundary; the bridge remains the owner of the request and
# tool semantics.
_MAX_REQUEST_DEPTH = 64
_MAX_REQUEST_NODES = 20_000
_MAX_REQUEST_STRING_CHARS = 500_000
_MAX_INTEGER_BITS = 4096

_IDLE = "idle"
_PENDING = "pending"
_WAKE_REQUESTED = "wake_requested"
_SERVICE_DUE = "service_due"
_EXECUTING = "executing"
_REPLY_READY = "reply_ready"
_CLOSED = "closed"


@dataclass(frozen=True)
class MailboxOutcome:
    """Bounded result of a mailbox operation, separate from bridge replies."""

    status: str
    reply: object = None


@dataclass(frozen=True)
class MailboxClaim:
    """One claimed request for execution by the current full-app run."""

    _claim_id: str
    target_epoch: str
    request: dict
    pairing_generation: int | None = None


def _copy_plain_json(value, *, bounded: bool):
    """Return an isolated exact-built-in JSON value or None if invalid.

    Incoming requests use the same structural budgets as the existing bridge.
    Trusted bridge replies use the same JSON-shape rules without a second
    output-size limit. No conversion hooks, custom mappings, or serializers
    supplied by the producer are invoked.
    """

    remaining_nodes = _MAX_REQUEST_NODES
    total_string_chars = 0
    active_containers = set()

    def scalar(item):
        nonlocal remaining_nodes, total_string_chars
        remaining_nodes -= 1
        if bounded and remaining_nodes < 0:
            raise ValueError

        item_type = type(item)
        if item_type is type(None) or item_type is bool:
            return True, item
        if item_type is int:
            if bounded and item.bit_length() > _MAX_INTEGER_BITS:
                raise ValueError
            return True, item
        if item_type is float:
            if not math.isfinite(item):
                raise ValueError
            return True, item
        if item_type is str:
            if bounded:
                total_string_chars += len(item)
                if total_string_chars > _MAX_REQUEST_STRING_CHARS:
                    raise ValueError
            return True, item
        return False, None

    try:
        is_scalar, copied_root = scalar(value)
        if is_scalar:
            return copied_root
        if type(value) is dict:
            copied_root = {}
        elif type(value) is list:
            copied_root = []
        else:
            raise ValueError

        active_containers.add(id(value))
        # Each frame is an iterator over exact built-in container entries,
        # its output container, and its nesting depth. Iteration avoids adding
        # a new recursion limit to trusted facade replies.
        stack = [(value, iter(value.items()) if type(value) is dict else iter(value), copied_root, 0)]
        while stack:
            source, children, destination, depth = stack[-1]
            try:
                entry = next(children)
            except StopIteration:
                active_containers.remove(id(source))
                stack.pop()
                continue

            if type(source) is dict:
                key, child = entry
                if type(key) is not str:
                    raise ValueError
                if bounded:
                    total_string_chars += len(key)
                    if total_string_chars > _MAX_REQUEST_STRING_CHARS:
                        raise ValueError
                assign_key = key
            else:
                child = entry
                assign_key = None

            child_depth = depth + 1
            if bounded and child_depth > _MAX_REQUEST_DEPTH:
                raise ValueError
            child_is_scalar, child_value = scalar(child)
            if child_is_scalar:
                if type(destination) is dict:
                    destination[assign_key] = child_value
                else:
                    destination.append(child_value)
                continue

            if type(child) is dict:
                child_destination = {}
                child_iterator = iter(child.items())
            elif type(child) is list:
                child_destination = []
                child_iterator = iter(child)
            else:
                raise ValueError
            identity = id(child)
            if identity in active_containers:
                raise ValueError
            if type(destination) is dict:
                destination[assign_key] = child_destination
            else:
                destination.append(child_destination)
            active_containers.add(identity)
            stack.append((child, child_iterator, child_destination, child_depth))
        return copied_root
    except Exception:
        return None


def _normalize_target_path(path):
    """Make the session's Project path comparable without touching disk."""

    if type(path) is not str or not path:
        return ""
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(path)))
    except Exception:
        # The path is app-owned session state. Preserve a stable string
        # identity if platform path normalization is unavailable.
        return path


class ProjectTargetTracker:
    """Track Project object/path activation without owning the Project."""

    def __init__(self):
        self._lock = threading.Lock()
        self._initialized = False
        self._project_ref = None
        self._had_project = False
        self._project_path = ""
        self._epoch = None

    def observe(self, project, project_path):
        """Return an opaque epoch that changes only with target identity."""

        project_is_trackable = project is None
        try:
            if project is not None:
                # The tracker keeps identity without keeping the mutable
                # Project alive. It deliberately does not import the domain
                # model or retain the object strongly.
                project_ref = weakref.ref(project)
                project_is_trackable = True
            else:
                project_ref = None
        except TypeError:
            project_ref = None
            project_is_trackable = False

        had_project = project is not None
        normalized_path = _normalize_target_path(project_path)
        with self._lock:
            if not self._initialized:
                changed = True
            else:
                previous_project = (
                    self._project_ref() if self._project_ref is not None else None
                )
                same_project = (
                    not self._had_project and not had_project
                ) or (
                    self._had_project and had_project
                    and project_ref is not None
                    and previous_project is project
                )
                changed = (
                    not project_is_trackable
                    or not same_project
                    or normalized_path != self._project_path
                )

            if changed:
                self._epoch = uuid.uuid4().hex

            self._initialized = True
            self._project_ref = project_ref
            self._had_project = had_project
            self._project_path = normalized_path
            return self._epoch

    def close(self):
        with self._lock:
            self._project_ref = None
            self._had_project = False
            self._project_path = ""
            self._epoch = None
            self._initialized = False


class ProjectAgentSessionMailbox:
    """One capacity-one, thread-safe request/reply mailbox for one session."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._state = _IDLE
        self._closed = False
        self._target_epoch = None
        self._request = None
        self._request_epoch = None
        self._request_pairing_generation = None
        self._deadline = None
        self._claim_id = None
        self._invalidated_while_executing = False
        self._reply_status = None
        self._reply = None
        self._reply_is_review_request = False
        self._reply_review_identity = None
        self._reply_generation = 0
        self._first_fragment_tick_pending = False
        self._wake_retry_count = 0
        self._wake_retry_at = None

    @property
    def target_epoch(self):
        with self._lock:
            return self._target_epoch

    @property
    def state(self):
        """Expose a stable diagnostic state for tests and host coordination."""

        with self._lock:
            return self._state

    def submit(self, target_epoch, request, *, timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
               _pairing_generation=None):
        """Accept one detached request explicitly bound to a target epoch."""

        if (type(target_epoch) is not str or not target_epoch
                or type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0
                or timeout_seconds > MAX_REQUEST_TIMEOUT_SECONDS
                or (_pairing_generation is not None
                    and (type(_pairing_generation) is not int or _pairing_generation <= 0))):
            return MailboxOutcome("invalid_request")

        detached = _copy_plain_json(request, bounded=True)
        if type(detached) is not dict:
            return MailboxOutcome("invalid_request")

        now = self._clock()
        with self._lock:
            if self._closed:
                return MailboxOutcome("session_closed")
            if target_epoch != self._target_epoch:
                return MailboxOutcome("stale_target")
            if self._state != _IDLE:
                return MailboxOutcome("busy")

            self._request = detached
            self._request_epoch = target_epoch
            self._request_pairing_generation = _pairing_generation
            self._deadline = now + float(timeout_seconds)
            self._claim_id = None
            self._invalidated_while_executing = False
            self._reply = None
            self._reply_status = None
            self._reply_is_review_request = False
            self._reply_review_identity = None
            self._reply_generation += 1
            self._wake_retry_count = 0
            self._wake_retry_at = None
            self._state = _PENDING
            return MailboxOutcome("accepted")

    def synchronize_target_epoch(self, target_epoch, *, review_custodian=None):
        """Invalidate old-target work while retaining the session mailbox."""

        if type(target_epoch) is not str or not target_epoch:
            return False

        with self._lock:
            if self._closed:
                return False
            changed = target_epoch != self._target_epoch
            self._target_epoch = target_epoch
            if review_custodian is not None:
                with review_custodian._lock:
                    review_custodian._synchronize_target_epoch_locked(target_epoch)
                    if not changed:
                        return False
                    return self._invalidate_target_locked()
            if not changed:
                return False
            return self._invalidate_target_locked()

    def _invalidate_target_locked(self):
        """Apply mailbox invalidation while the mailbox lock is held."""

        if self._state == _EXECUTING:
            self._invalidated_while_executing = True
            return True
        if self._state in (_PENDING, _WAKE_REQUESTED, _SERVICE_DUE, _REPLY_READY):
            if self._state != _REPLY_READY or self._reply_status == "completed":
                self._set_terminal_locked("stale_target")
        return True

    def begin_full_app_run(self, target_epoch, *, now=None):
        """Synchronize target and mark a normal app run as the service context."""

        self.synchronize_target_epoch(target_epoch)
        if now is None:
            now = self._clock()
        with self._lock:
            if self._closed:
                return
            self._first_fragment_tick_pending = True
            if self._state in (_PENDING, _WAKE_REQUESTED):
                if self._is_expired_locked(now):
                    self._set_terminal_locked("expired")
                else:
                    self._state = _SERVICE_DUE
                    self._wake_retry_at = None

    def fragment_tick(self, *, now=None):
        """Return True once when this fragment must request a full-app rerun."""

        if now is None:
            now = self._clock()
        with self._lock:
            if self._closed:
                return False
            if self._state in (_PENDING, _WAKE_REQUESTED, _SERVICE_DUE) and self._is_expired_locked(now):
                self._set_terminal_locked("expired")
                return False

            if self._first_fragment_tick_pending:
                self._first_fragment_tick_pending = False
                return False

            if self._state == _PENDING:
                self._mark_wake_requested_locked(now)
                return True

            if self._state == _SERVICE_DUE:
                # A prior full run ended before reaching its service point.
                # Re-run only the unclaimed request; an executing request is
                # never retried.
                self._mark_wake_requested_locked(now)
                return True

            if self._state == _WAKE_REQUESTED:
                if self._wake_retry_at is not None and now >= self._wake_retry_at:
                    self._mark_wake_requested_locked(now)
                    return True
            return False

    def _claim_for_service(self, target_epoch, *, now=None):
        """Claim one request; the caller must be a current full-app run."""

        self.synchronize_target_epoch(target_epoch)
        if now is None:
            now = self._clock()
        with self._lock:
            if self._closed:
                return None
            if self._state not in (_PENDING, _WAKE_REQUESTED, _SERVICE_DUE):
                return None
            if self._is_expired_locked(now):
                self._set_terminal_locked("expired")
                return None
            if self._request_epoch != target_epoch or self._target_epoch != target_epoch:
                self._set_terminal_locked("stale_target")
                return None

            # A request can arrive after this full run's initial sync but
            # before its service point. Only the host's normal-run service
            # owner calls this private claim method, so it may service without
            # an unnecessary fragment-triggered rerun.
            self._state = _SERVICE_DUE

            stored_request = self._request
            pairing_generation = self._request_pairing_generation
            claim_id = uuid.uuid4().hex
            self._claim_id = claim_id
            self._state = _EXECUTING
            self._wake_retry_at = None

        # The request was already detached on submission. Clone it outside the
        # lock so future dispatch adapters cannot mutate the mailbox's copy.
        detached = _copy_plain_json(stored_request, bounded=True)
        with self._lock:
            if self._closed or self._state != _EXECUTING or self._claim_id != claim_id:
                return None
            if (self._invalidated_while_executing
                    or self._target_epoch != target_epoch
                    or self._request_epoch != target_epoch):
                self._set_terminal_locked("stale_target")
                return None
            if self._is_expired_locked(self._clock()):
                self._set_terminal_locked("expired")
                return None
            if type(detached) is not dict:
                self._set_terminal_locked("internal_error")
                return None
            return MailboxClaim(claim_id, target_epoch, detached, pairing_generation)

    def complete(self, claim, reply, target_epoch, *, now=None):
        """Publish the exact bridge reply, unless target/deadline went stale."""

        detached_reply = _copy_plain_json(reply, bounded=False)
        reply_is_valid = detached_reply is not None and type(detached_reply) is dict
        self.synchronize_target_epoch(target_epoch)
        if now is None:
            now = self._clock()

        with self._lock:
            if self._closed:
                return MailboxOutcome("session_closed")
            if (type(claim) is not MailboxClaim
                    or self._state != _EXECUTING
                    or self._claim_id != claim._claim_id):
                return MailboxOutcome("unavailable")

            if (self._invalidated_while_executing
                    or claim.target_epoch != target_epoch
                    or self._target_epoch != target_epoch):
                self._set_terminal_locked("stale_target")
            elif self._is_expired_locked(now):
                self._set_terminal_locked("expired")
            elif not reply_is_valid:
                self._set_terminal_locked("internal_error")
            else:
                self._reply_status = "completed"
                self._reply = detached_reply
                self._reply_is_review_request = False
                self._reply_review_identity = None
                self._state = _REPLY_READY
                self._reply_generation += 1
                # Keep target epoch and deadline until the producer consumes
                # this reply. A Project switch or timeout during that interval
                # must invalidate a result that has not left the mailbox.
                self._clear_request_payload_locked()
            return MailboxOutcome(self._reply_status or "unavailable")

    def complete_with_review(self, claim, prepared_review, target_epoch,
                             review_custodian, *, now=None):
        """Atomically publish a positive reply with its host proposal custody.

        Reply detachment occurs before locking. The only nested lock order is
        mailbox then custodian, and this critical section performs no Project,
        Streamlit, transport, or callback work.
        """

        from ui.agent_scene_module_swap_approval_lifecycle import (
            AgentSceneModuleSwapApprovalCustodian,
            PreparedReviewReply,
        )

        if (type(prepared_review) is not PreparedReviewReply
                or type(review_custodian) is not AgentSceneModuleSwapApprovalCustodian):
            return MailboxOutcome("invalid_review_carrier")
        detached_reply = _copy_plain_json(prepared_review.reply, bounded=False)
        reply_is_valid = detached_reply is not None and type(detached_reply) is dict
        if now is None:
            now = self._clock()

        with self._lock:
            with review_custodian._lock:
                if self._closed:
                    review_custodian._abort_prepared_locked(
                        prepared_review.token, "session_closed",
                    )
                    return MailboxOutcome("session_closed")

                claim_is_current = (
                    type(claim) is MailboxClaim
                    and self._state == _EXECUTING
                    and self._claim_id == claim._claim_id
                    and claim.pairing_generation == self._request_pairing_generation
                    and claim.pairing_generation is not None
                )
                if not claim_is_current:
                    review_custodian._abort_prepared_locked(prepared_review.token)
                    if self._state == _EXECUTING:
                        review_custodian._abort_prepared_for_claim_locked(
                            self._request.get("request_id") if type(self._request) is dict else None,
                            self._request_pairing_generation,
                            self._request_epoch,
                        )
                        self._set_terminal_locked("internal_error")
                    return MailboxOutcome("unavailable")

                if (self._invalidated_while_executing
                        or claim.target_epoch != target_epoch
                        or self._target_epoch != target_epoch):
                    review_custodian._abort_prepared_locked(
                        prepared_review.token, "stale_target",
                    )
                    self._set_terminal_locked("stale_target")
                    return MailboxOutcome("stale_target")
                if self._is_expired_locked(now):
                    review_custodian._abort_prepared_locked(
                        prepared_review.token, "proposal_expired",
                    )
                    self._set_terminal_locked("expired")
                    return MailboxOutcome("expired")
                if not reply_is_valid:
                    review_custodian._abort_prepared_locked(prepared_review.token)
                    self._set_terminal_locked("internal_error")
                    return MailboxOutcome("internal_error")

                try:
                    committed = review_custodian._commit_prepared_locked(
                        prepared_review.token,
                        request_id=claim.request.get("request_id"),
                        pairing_generation=claim.pairing_generation,
                        target_epoch=claim.target_epoch,
                        reply=detached_reply,
                        now=now,
                    )
                except Exception:
                    review_custodian._rollback_prepared_locked(prepared_review.token)
                    self._set_terminal_locked("internal_error")
                    return MailboxOutcome("internal_error")
                if not committed:
                    review_custodian._abort_prepared_locked(prepared_review.token)
                    review_custodian._abort_prepared_for_claim_locked(
                        claim.request.get("request_id"),
                        claim.pairing_generation,
                        claim.target_epoch,
                    )
                    self._set_terminal_locked("internal_error")
                    return MailboxOutcome("internal_error")

                try:
                    # Consumers cannot observe the acknowledgement until the
                    # mailbox lock is released, after custody is pending.
                    self._reply_status = "completed"
                    self._reply = detached_reply
                    self._reply_is_review_request = True
                    record = review_custodian._record
                    self._reply_review_identity = (
                        record.request_id,
                        record.pairing_generation,
                        record.target_epoch,
                        record.proposal_id,
                        record.acknowledgment_identity,
                    )
                    self._state = _REPLY_READY
                    self._reply_generation += 1
                    self._clear_request_payload_locked()
                except Exception:
                    review_custodian._rollback_prepared_locked(prepared_review.token)
                    self._set_terminal_locked("internal_error")
                    return MailboxOutcome("internal_error")

                return MailboxOutcome("completed")

    def complete_with_duplicate_review(self, claim, duplicate_review, target_epoch,
                                       review_custodian, *, now=None):
        """Publish a retry acknowledgement only while its exact proposal is pending.

        Unlike first-time review completion, this does not create or transition
        proposal custody. It revalidates the retry's original correlation,
        pairing, intent, proposal, and acknowledgement under the same fixed
        mailbox-then-custodian lock order before exposing the positive reply.
        """

        from ui.agent_scene_module_swap_approval_lifecycle import (
            AgentSceneModuleSwapApprovalCustodian,
            DuplicateReviewReply,
            PendingReviewRetryToken,
        )

        if (type(duplicate_review) is not DuplicateReviewReply
                or type(duplicate_review.token) is not PendingReviewRetryToken
                or type(review_custodian) is not AgentSceneModuleSwapApprovalCustodian):
            return MailboxOutcome("invalid_review_retry_carrier")

        detached_reply = _copy_plain_json(duplicate_review.reply, bounded=False)
        reply_is_valid = detached_reply is not None and type(detached_reply) is dict
        self.synchronize_target_epoch(
            target_epoch,
            review_custodian=review_custodian,
        )

        token = duplicate_review.token
        with self._lock:
            with review_custodian._lock:
                if self._closed or review_custodian._closed:
                    if self._state == _EXECUTING:
                        self._set_terminal_locked("session_closed")
                    return MailboxOutcome("session_closed")

                claim_is_current = (
                    type(claim) is MailboxClaim
                    and self._state == _EXECUTING
                    and self._claim_id == claim._claim_id
                    and claim.pairing_generation is not None
                    and claim.pairing_generation == self._request_pairing_generation
                    and claim.target_epoch == self._request_epoch
                    and type(self._request) is dict
                    and type(claim.request) is dict
                    and claim.request == self._request
                    and claim.request.get("request_id") == token.request_id
                    and self._request.get("request_id") == token.request_id
                )
                if not claim_is_current:
                    if self._state == _EXECUTING:
                        self._set_terminal_locked("internal_error")
                    return MailboxOutcome("unavailable")

                if (self._invalidated_while_executing
                        or claim.target_epoch != target_epoch
                        or self._target_epoch != target_epoch
                        or token.target_epoch != target_epoch
                        or review_custodian._target_epoch != target_epoch):
                    self._set_terminal_locked("stale_target")
                    return MailboxOutcome("stale_target")

                mailbox_now = self._clock() if now is None else now
                if self._is_expired_locked(mailbox_now):
                    self._set_terminal_locked("expired")
                    return MailboxOutcome("expired")
                if not reply_is_valid:
                    self._set_terminal_locked("internal_error")
                    return MailboxOutcome("internal_error")

                custody_now = review_custodian._clock() if now is None else now
                review_custodian._expire_locked(custody_now)
                record = review_custodian._record
                tombstone = review_custodian._tombstones.get(token.request_id)
                if record is None:
                    terminal_status = "review_cancelled"
                    if (tombstone is not None
                            and tombstone.pairing_generation == token.pairing_generation
                            and tombstone.intent_digest == token.intent_digest):
                        terminal_status = {
                            "proposal_expired": "expired",
                            "stale_target": "stale_target",
                            "session_closed": "session_closed",
                        }.get(tombstone.reason, "review_cancelled")
                    self._set_terminal_locked(terminal_status)
                    return MailboxOutcome(terminal_status)

                expected_reply = detached_reply
                identity_matches = (
                    record.state == "pending"
                    and record.expires_at is not None
                    and custody_now < record.expires_at
                    and record.request_id == token.request_id
                    and record.pairing_generation == token.pairing_generation
                    and record.pairing_generation == claim.pairing_generation
                    and record.target_epoch == token.target_epoch
                    and record.target_epoch == claim.target_epoch
                    and record.target_epoch == review_custodian._target_epoch
                    and record.intent == token.intent
                    and record.intent_digest == token.intent_digest
                    and record.proposal_id == token.proposal_id
                    and record.acknowledgment_identity == token.acknowledgment_identity
                    and record.ack == token.acknowledgment
                    and type(expected_reply) is dict
                    and set(expected_reply) == {
                        "bridge_contract_version", "request_id", "status", "result",
                    }
                    and expected_reply.get("bridge_contract_version") == (
                        "promptgraph.app-agent-request-bridge.v1"
                    )
                    and expected_reply.get("request_id") == token.request_id
                    and expected_reply.get("status") == "completed"
                    and expected_reply.get("result") == record.ack
                )
                if not identity_matches:
                    self._set_terminal_locked("review_cancelled")
                    return MailboxOutcome("review_cancelled")

                # Retry publication does not change custody state or expiry.
                self._reply_status = "completed"
                self._reply = detached_reply
                self._reply_is_review_request = True
                self._reply_review_identity = (
                    token.request_id,
                    token.pairing_generation,
                    token.target_epoch,
                    token.proposal_id,
                    token.acknowledgment_identity,
                )
                self._state = _REPLY_READY
                self._reply_generation += 1
                self._clear_request_payload_locked()
                return MailboxOutcome("completed")

    def inspect_review_custody(self, review_custodian):
        """Inspect host review while coordinating terminal state with its reply.

        Expiry, stale, Reject, and Dismiss transitions use the fixed mailbox-
        then-custodian lock order. Only the unconsumed acknowledgment for the
        exact proposal may be replaced with a terminal mailbox outcome.
        """

        from ui.agent_scene_module_swap_approval_lifecycle import (
            AgentSceneModuleSwapApprovalCustodian,
        )

        if type(review_custodian) is not AgentSceneModuleSwapApprovalCustodian:
            return {"state": "session_unavailable"}
        with self._lock:
            with review_custodian._lock:
                now = review_custodian._clock()
                review = review_custodian._inspect_for_human_review_locked(now)
                status = {
                    "expired": "expired",
                    "stale": "stale_target",
                    "rejected": "review_cancelled",
                    "dismissed": "review_cancelled",
                    "applied": "review_cancelled",
                    "applied_save_failed": "review_cancelled",
                    "apply_failed": "review_cancelled",
                }.get(review.get("state") if type(review) is dict else None)
                identity = self._reply_review_identity
                if status is not None and type(identity) is tuple and len(identity) == 5:
                    self._discard_review_ack_locked(identity[3], status)
                return review

    def resolve_review_proposal(self, review_custodian, proposal_id, action):
        """Resolve one human action and invalidate only its queued ACK atomically."""

        from ui.agent_scene_module_swap_approval_lifecycle import (
            AgentSceneModuleSwapApprovalCustodian,
        )

        if type(review_custodian) is not AgentSceneModuleSwapApprovalCustodian:
            return "session_unavailable"
        if action not in {"reject", "dismiss"}:
            return "invalid_action"
        with self._lock:
            with review_custodian._lock:
                state = review_custodian._resolve_pending_locked(
                    proposal_id, action, review_custodian._clock(),
                )
                identity = self._reply_review_identity
                if type(identity) is tuple and len(identity) == 5:
                    status = {
                        "rejected": "review_cancelled",
                        "dismissed": "review_cancelled",
                        "expired": "expired",
                        "stale": "stale_target",
                    }.get(state)
                    if status is not None:
                        self._discard_review_ack_locked(proposal_id, status)
                return state

    def mark_review_proposal_stale(self, review_custodian, proposal_id):
        """Mark a stale host proposal and its exact undelivered ACK together."""

        from ui.agent_scene_module_swap_approval_lifecycle import (
            AgentSceneModuleSwapApprovalCustodian,
        )

        if type(review_custodian) is not AgentSceneModuleSwapApprovalCustodian:
            return "session_unavailable"
        with self._lock:
            with review_custodian._lock:
                state = review_custodian._mark_pending_stale_locked(
                    proposal_id,
                    review_custodian._clock(),
                )
                identity = self._reply_review_identity
                if type(identity) is tuple and len(identity) == 5:
                    status = {
                        "stale": "stale_target",
                        "expired": "expired",
                    }.get(state)
                    if status is not None:
                        self._discard_review_ack_locked(proposal_id, status)
                return state

    def claim_review_proposal_for_apply(
        self,
        review_custodian,
        proposal_id,
        target_epoch,
        intent,
        preview,
    ):
        """Claim one freshly reviewed proposal under mailbox-then-custodian order."""

        from ui.agent_scene_module_swap_approval_lifecycle import (
            AgentSceneModuleSwapApprovalCustodian,
            _apply_claim_identities,
        )

        if type(review_custodian) is not AgentSceneModuleSwapApprovalCustodian:
            return "session_unavailable", None
        identities = _apply_claim_identities(intent, preview)
        if identities is None:
            return "stale", None
        intent_identity, content_identity = identities
        with self._lock:
            if self._closed:
                return "session_unavailable", None
            if type(target_epoch) is not str or target_epoch != self._target_epoch:
                return "stale", None
            with review_custodian._lock:
                return review_custodian._claim_pending_for_apply_locked(
                    proposal_id,
                    target_epoch,
                    intent_identity,
                    content_identity,
                    review_custodian._clock(),
                )

    def review_apply_claim_is_current(self, review_custodian, claim):
        """Check a claim without exposing Project or proposal internals."""

        from ui.agent_scene_module_swap_approval_lifecycle import (
            AgentSceneModuleSwapApprovalCustodian,
        )

        if type(review_custodian) is not AgentSceneModuleSwapApprovalCustodian:
            return False
        with self._lock:
            if self._closed or self._target_epoch != getattr(claim, "target_epoch", None):
                return False
            with review_custodian._lock:
                return review_custodian._apply_claim_is_current_locked(claim)

    def finish_review_proposal_apply(self, review_custodian, claim, status, result):
        """Terminalize one claimed Apply and suppress only its undelivered ACK."""

        from ui.agent_scene_module_swap_approval_lifecycle import (
            AgentSceneModuleSwapApprovalCustodian,
        )

        if type(review_custodian) is not AgentSceneModuleSwapApprovalCustodian:
            return "session_unavailable"
        with self._lock:
            if self._closed:
                return "session_unavailable"
            with review_custodian._lock:
                state = review_custodian._finish_apply_locked(claim, status, result)
                if state in {"applied", "applied_save_failed", "stale", "apply_failed"}:
                    # Never expose the human Apply result through the MCP queue ACK.
                    self._discard_review_ack_locked(claim.proposal_id, "review_cancelled")
                return state

    def _discard_review_ack_locked(self, proposal_id, status):
        """Replace an undelivered positive ACK only for its exact proposal."""

        identity = self._reply_review_identity
        if (
            type(identity) is not tuple
            or len(identity) != 5
            or type(proposal_id) is not str
            or identity[3] != proposal_id
            or self._state != _REPLY_READY
            or self._reply_status != "completed"
            or self._reply_is_review_request is not True
        ):
            return False
        reply = self._reply
        result = reply.get("result") if type(reply) is dict else None
        if (
            type(reply) is not dict
            or reply.get("request_id") != identity[0]
            or type(result) is not dict
            or result.get("proposal_id") != identity[3]
            or result.get("status") != "queued_for_review"
        ):
            return False
        self._set_terminal_locked(status)
        return True

    def cancel_review_custody(self, review_custodian):
        """Cancel custody and hide an unconsumed positive queue reply."""

        with self._lock:
            with review_custodian._lock:
                review_custodian._cancel_locked("proposal_cancelled")
                if (self._state == _REPLY_READY
                        and self._reply_status == "completed"
                        and self._reply_is_review_request):
                    self._set_terminal_locked("review_cancelled")

    def consume_reply(self, target_epoch, *, now=None):
        """Consume one outcome, detaching large replies without holding lock."""

        if now is None:
            now = self._clock()
        with self._lock:
            if self._closed:
                return MailboxOutcome("session_closed")
            if type(target_epoch) is not str or not target_epoch:
                return MailboxOutcome("stale_target")
            if self._state != _REPLY_READY:
                if self._state == _IDLE:
                    return MailboxOutcome(
                        "idle" if target_epoch == self._target_epoch else "stale_target"
                    )
                if target_epoch != self._target_epoch:
                    return MailboxOutcome("stale_target")
                return MailboxOutcome("busy")
            # An outcome belongs to the submitted request epoch, which may be
            # older than the current session target after invalidation. Only
            # that request's producer may consume it; consumption never
            # synchronizes or rewinds the session-owned target epoch.
            if target_epoch != self._request_epoch:
                return MailboxOutcome("stale_target")
            if self._is_expired_locked(now) and self._reply_status == "completed":
                self._set_terminal_locked("expired")
            generation = self._reply_generation
            status = self._reply_status or "internal_error"
            reply = self._reply

        detached_reply = (
            _copy_plain_json(reply, bounded=False)
            if status == "completed" else None
        )
        if status == "completed" and type(detached_reply) is not dict:
            status = "internal_error"
            detached_reply = None

        with self._lock:
            if self._closed:
                return MailboxOutcome("session_closed")
            if self._state != _REPLY_READY or generation != self._reply_generation:
                if self._state == _REPLY_READY and self._reply_status in (
                    "stale_target", "expired", "internal_error", "review_cancelled",
                ):
                    if target_epoch != self._request_epoch:
                        return MailboxOutcome("stale_target")
                    outcome = MailboxOutcome(self._reply_status)
                    self._clear_outcome_locked()
                    return outcome
                return MailboxOutcome("busy")
            if target_epoch != self._request_epoch:
                return MailboxOutcome("stale_target")
            if (status == "completed"
                    and self._request_epoch is not None
                    and self._target_epoch != self._request_epoch):
                self._set_terminal_locked("stale_target")
                status = "stale_target"
                detached_reply = None
            outcome = MailboxOutcome(status, detached_reply)
            self._clear_outcome_locked()
            return outcome

    def close(self, *, review_custodian=None):
        """Close this session route and reject any outstanding work."""

        with self._lock:
            if review_custodian is not None:
                with review_custodian._lock:
                    review_custodian._close_locked()
            self._closed = True
            self._state = _CLOSED
            self._target_epoch = None
            self._request = None
            self._request_epoch = None
            self._request_pairing_generation = None
            self._deadline = None
            self._claim_id = None
            self._invalidated_while_executing = False
            self._reply_status = None
            self._reply = None
            self._reply_is_review_request = False
            self._reply_review_identity = None
            self._reply_generation += 1
            self._first_fragment_tick_pending = False
            self._wake_retry_at = None

    def _is_expired_locked(self, now):
        return self._deadline is not None and now >= self._deadline

    def _mark_wake_requested_locked(self, now):
        self._state = _WAKE_REQUESTED
        self._wake_retry_count += 1
        delay = min(
            MAX_WAKE_RETRY_SECONDS,
            FRAGMENT_POLL_INTERVAL_SECONDS * (2 ** min(self._wake_retry_count - 1, 8)),
        )
        self._wake_retry_at = now + delay

    def _set_terminal_locked(self, status):
        self._state = _REPLY_READY
        self._reply_status = status
        self._reply = None
        self._reply_is_review_request = False
        self._reply_review_identity = None
        self._clear_request_payload_locked()
        self._reply_generation += 1

    def _clear_request_payload_locked(self):
        self._request = None
        self._request_pairing_generation = None
        self._claim_id = None
        self._invalidated_while_executing = False
        self._wake_retry_count = 0
        self._wake_retry_at = None

    def _clear_outcome_locked(self):
        self._state = _IDLE
        self._reply_status = None
        self._reply = None
        self._reply_is_review_request = False
        self._reply_review_identity = None
        self._request_epoch = None
        self._deadline = None
        self._claim_id = None
        self._invalidated_while_executing = False
        self._reply_generation += 1
        self._wake_retry_count = 0
        self._wake_retry_at = None
