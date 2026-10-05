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
        self._deadline = None
        self._claim_id = None
        self._invalidated_while_executing = False
        self._reply_status = None
        self._reply = None
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

    def submit(self, target_epoch, request, *, timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS):
        """Accept one detached request explicitly bound to a target epoch."""

        if (type(target_epoch) is not str or not target_epoch
                or type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0
                or timeout_seconds > MAX_REQUEST_TIMEOUT_SECONDS):
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
            self._deadline = now + float(timeout_seconds)
            self._claim_id = None
            self._invalidated_while_executing = False
            self._reply = None
            self._reply_status = None
            self._reply_generation += 1
            self._wake_retry_count = 0
            self._wake_retry_at = None
            self._state = _PENDING
            return MailboxOutcome("accepted")

    def synchronize_target_epoch(self, target_epoch):
        """Invalidate old-target work while retaining the session mailbox."""

        if type(target_epoch) is not str or not target_epoch:
            return False

        with self._lock:
            if self._closed or target_epoch == self._target_epoch:
                return False
            self._target_epoch = target_epoch

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
            return MailboxClaim(claim_id, target_epoch, detached)

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
                self._state = _REPLY_READY
                self._reply_generation += 1
                # Keep target epoch and deadline until the producer consumes
                # this reply. A Project switch or timeout during that interval
                # must invalidate a result that has not left the mailbox.
                self._clear_request_payload_locked()
            return MailboxOutcome(self._reply_status or "unavailable")

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
                    "stale_target", "expired", "internal_error",
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

    def close(self):
        """Close this session route and reject any outstanding work."""

        with self._lock:
            self._closed = True
            self._state = _CLOSED
            self._target_epoch = None
            self._request = None
            self._request_epoch = None
            self._deadline = None
            self._claim_id = None
            self._invalidated_while_executing = False
            self._reply_status = None
            self._reply = None
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
        self._clear_request_payload_locked()
        self._reply_generation += 1

    def _clear_request_payload_locked(self):
        self._request = None
        self._claim_id = None
        self._invalidated_while_executing = False
        self._wake_retry_count = 0
        self._wake_retry_at = None

    def _clear_outcome_locked(self):
        self._state = _IDLE
        self._reply_status = None
        self._reply = None
        self._request_epoch = None
        self._deadline = None
        self._claim_id = None
        self._invalidated_while_executing = False
        self._reply_generation += 1
        self._wake_retry_count = 0
        self._wake_retry_at = None
