"""Process-local registration and one-use pairing for session mailboxes.

The registry only addresses weakly held session mailboxes. It does not own a
Project or Streamlit state, and a paired route exposes only target lookup,
request submission, reply consumption, and release.
"""

from dataclasses import dataclass, field
import hashlib
import hmac
import math
import secrets
import threading
import time
import weakref

from ui.project_agent_session_mailbox import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    MailboxOutcome,
    ProjectAgentSessionMailbox,
)


PAIRING_BOOTSTRAP_CONTRACT = "promptgraph.session-pairing-bootstrap.v1"
DEFAULT_PAIRING_LIFETIME_SECONDS = 60.0
MAX_PAIRING_LIFETIME_SECONDS = 300.0
_MAX_PAIRING_FIELD_CHARS = 512


def _digest_secret(secret):
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _valid_pairing_field(value):
    return (
        type(value) is str
        and 0 < len(value) <= _MAX_PAIRING_FIELD_CHARS
        and value.isascii()
    )


class PairingBootstrap:
    """Session-side offer; the capability is intentionally absent from repr."""

    __slots__ = (
        "contract_version", "process_incarnation", "route_id",
        "_capability", "expires_in_seconds",
    )

    def __init__(
        self,
        *,
        contract_version,
        process_incarnation,
        route_id,
        capability,
        expires_in_seconds,
    ):
        object.__setattr__(self, "contract_version", contract_version)
        object.__setattr__(self, "process_incarnation", process_incarnation)
        object.__setattr__(self, "route_id", route_id)
        object.__setattr__(self, "_capability", capability)
        object.__setattr__(self, "expires_in_seconds", expires_in_seconds)

    def __setattr__(self, name, value):
        raise AttributeError("pairing bootstrap is immutable")

    @property
    def capability(self):
        """The plaintext offer secret, exposed only to its session owner."""

        return self._capability

    def __repr__(self):
        return (
            "PairingBootstrap("
            f"contract_version={self.contract_version!r}, "
            f"process_incarnation={self.process_incarnation!r}, "
            f"route_id={self.route_id!r}, capability=<redacted>, "
            f"expires_in_seconds={self.expires_in_seconds!r})"
        )


@dataclass(frozen=True)
class PairingOperation:
    """Bounded result of a registration or pairing lifecycle operation."""

    status: str
    bootstrap: PairingBootstrap | None = None
    paired_route: object = None


@dataclass
class _RouteRecord:
    route_id: str
    registration_verifier: bytes = field(repr=False)
    mailbox_ref: object = field(repr=False)
    operation_lock: object = field(default_factory=threading.RLock, repr=False)
    bootstrap_verifier: bytes | None = field(default=None, repr=False)
    bootstrap_expires_at: float | None = None
    pairing_generation: int | None = None
    next_pairing_generation: int = 0


class ProjectAgentSessionRegistration:
    """Session-owner authority for arming and unregistering exactly one route."""

    __slots__ = ("_registry", "route_id", "_authority", "_closed")

    def __init__(self, registry, route_id, authority):
        self._registry = registry
        self.route_id = route_id
        self._authority = authority
        self._closed = False

    def __repr__(self):
        return f"ProjectAgentSessionRegistration(route_id={self.route_id!r})"

    def arm_pairing(self):
        if self._closed:
            return PairingOperation("session_unavailable")
        return self._registry.arm_pairing(self)

    def unregister(self):
        if self._closed:
            return False
        removed = self._registry.unregister_session(self)
        self._authority = None
        self._closed = True
        return removed


class ProjectAgentPairedRoute:
    """Narrow producer/consumer handle; never exposes the underlying mailbox."""

    __slots__ = (
        "_registry", "_process_incarnation", "_route_id", "_pairing_generation",
    )

    def __init__(self, registry, process_incarnation, route_id, pairing_generation):
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_process_incarnation", process_incarnation)
        object.__setattr__(self, "_route_id", route_id)
        object.__setattr__(self, "_pairing_generation", pairing_generation)

    def __setattr__(self, name, value):
        raise AttributeError("paired route is immutable")

    def __repr__(self):
        return "ProjectAgentPairedRoute(<paired route>)"

    @property
    def current_target_epoch(self):
        return self._registry._paired_target_epoch(self)

    def submit(
        self,
        target_epoch,
        request,
        *,
        timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ):
        return self._registry._paired_submit(
            self,
            target_epoch,
            request,
            timeout_seconds=timeout_seconds,
        )

    def consume_reply(self, target_epoch):
        return self._registry._paired_consume_reply(self, target_epoch)

    def release(self):
        return self._registry.release_pairing(self)


class ProjectAgentSessionRegistry:
    """One process-local registry for explicitly selected session routes."""

    def __init__(
        self,
        *,
        clock=time.monotonic,
        pairing_lifetime_seconds=DEFAULT_PAIRING_LIFETIME_SECONDS,
    ):
        try:
            pairing_lifetime = float(pairing_lifetime_seconds)
        except (OverflowError, TypeError, ValueError):
            pairing_lifetime = math.nan
        if (type(pairing_lifetime_seconds) not in (int, float)
                or not math.isfinite(pairing_lifetime)
                or pairing_lifetime <= 0
                or pairing_lifetime > MAX_PAIRING_LIFETIME_SECONDS):
            raise ValueError("invalid pairing lifetime")
        if not callable(clock):
            raise ValueError("invalid pairing clock")

        self._clock = clock
        self._pairing_lifetime_seconds = pairing_lifetime
        self._process_incarnation = secrets.token_urlsafe(32)
        self._lock = threading.RLock()
        self._routes = {}
        self._closed = False

    @property
    def process_incarnation(self):
        """Opaque process-lifetime identity; it is not a secret."""

        return self._process_incarnation

    def register_session(self, mailbox):
        """Register one weakly held mailbox and return its owner authority."""

        if type(mailbox) is not ProjectAgentSessionMailbox:
            return None

        route_id = secrets.token_urlsafe(32)
        authority = secrets.token_urlsafe(32)
        authority_verifier = _digest_secret(authority)
        registry_ref = weakref.ref(self)

        def on_mailbox_collected(_mailbox_ref):
            registry = registry_ref()
            if registry is not None:
                registry._forget_dead_route(route_id, authority_verifier)

        mailbox_ref = weakref.ref(mailbox, on_mailbox_collected)
        with self._lock:
            if self._closed:
                return None
            while route_id in self._routes:
                route_id = secrets.token_urlsafe(32)
            record = _RouteRecord(
                route_id=route_id,
                registration_verifier=authority_verifier,
                mailbox_ref=mailbox_ref,
            )
            self._routes[route_id] = record
        return ProjectAgentSessionRegistration(self, route_id, authority)

    def arm_pairing(self, registration):
        """Issue or replace one short-lived capability for the owner route."""

        record = self._record_for_registration(registration)
        if record is None:
            return PairingOperation("session_unavailable")

        with record.operation_lock:
            with self._lock:
                if not self._registration_matches_locked(registration, record):
                    return PairingOperation("session_unavailable")
                if self._closed:
                    return PairingOperation("session_unavailable")
                mailbox = record.mailbox_ref()
                if mailbox is None or mailbox.state == "closed":
                    self._routes.pop(record.route_id, None)
                    return PairingOperation("session_unavailable")
                if record.pairing_generation is not None:
                    return PairingOperation("already_paired")

                now = self._clock()
                if (record.bootstrap_expires_at is not None
                        and now >= record.bootstrap_expires_at):
                    self._clear_bootstrap_locked(record)

                capability = secrets.token_urlsafe(32)
                record.bootstrap_verifier = _digest_secret(capability)
                record.bootstrap_expires_at = now + self._pairing_lifetime_seconds
                bootstrap = PairingBootstrap(
                    contract_version=PAIRING_BOOTSTRAP_CONTRACT,
                    process_incarnation=self._process_incarnation,
                    route_id=record.route_id,
                    capability=capability,
                    expires_in_seconds=self._pairing_lifetime_seconds,
                )
                return PairingOperation("armed", bootstrap=bootstrap)

    def claim_pairing(self, process_incarnation, route_id, capability):
        """Atomically consume an offer and return one restricted route handle."""

        if (not _valid_pairing_field(process_incarnation)
                or not _valid_pairing_field(route_id)
                or not _valid_pairing_field(capability)):
            return PairingOperation("invalid_pairing")

        with self._lock:
            if self._closed or process_incarnation != self._process_incarnation:
                return PairingOperation("invalid_pairing")
            record = self._routes.get(route_id)
            if record is None:
                return PairingOperation("invalid_pairing")

        with record.operation_lock:
            with self._lock:
                if (self._closed or self._routes.get(route_id) is not record
                        or process_incarnation != self._process_incarnation):
                    return PairingOperation("invalid_pairing")
                mailbox = record.mailbox_ref()
                if mailbox is None or mailbox.state == "closed":
                    self._routes.pop(route_id, None)
                    return PairingOperation("session_unavailable")
                if record.pairing_generation is not None:
                    return PairingOperation("invalid_pairing")
                if (record.bootstrap_verifier is None
                        or record.bootstrap_expires_at is None):
                    return PairingOperation("invalid_pairing")

                now = self._clock()
                supplied_verifier = _digest_secret(capability)
                capability_matches = hmac.compare_digest(
                    supplied_verifier, record.bootstrap_verifier
                )
                if now >= record.bootstrap_expires_at:
                    self._clear_bootstrap_locked(record)
                    return PairingOperation(
                        "expired_pairing" if capability_matches else "invalid_pairing"
                    )
                if not capability_matches:
                    return PairingOperation("invalid_pairing")

                self._clear_bootstrap_locked(record)
                record.next_pairing_generation += 1
                record.pairing_generation = record.next_pairing_generation
                paired_route = ProjectAgentPairedRoute(
                    self,
                    self._process_incarnation,
                    record.route_id,
                    record.pairing_generation,
                )
                return PairingOperation("paired", paired_route=paired_route)

    def unregister_session(self, registration):
        """Remove a session route and invalidate offers and paired handles."""

        record = self._record_for_registration(registration)
        if record is None:
            return False
        with record.operation_lock:
            with self._lock:
                if not self._registration_matches_locked(registration, record):
                    return False
                self._clear_bootstrap_locked(record)
                self._routes.pop(record.route_id, None)
                return True

    def release_pairing(self, paired_route):
        """Invalidate one paired generation while leaving registration alive."""

        record = self._record_for_paired_route(paired_route)
        if record is None:
            return PairingOperation("already_released")
        with record.operation_lock:
            with self._lock:
                if not self._paired_route_matches_locked(paired_route, record):
                    return PairingOperation("already_released")
                record.pairing_generation = None
                return PairingOperation("released")

    def close(self):
        """Invalidate this registry for deterministic process-restart tests."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            records = list(self._routes.values())
        for record in records:
            with record.operation_lock:
                with self._lock:
                    if self._routes.get(record.route_id) is record:
                        self._clear_bootstrap_locked(record)
                        self._routes.pop(record.route_id, None)

    def _paired_target_epoch(self, paired_route):
        return self._with_paired_mailbox(
            paired_route,
            lambda mailbox: mailbox.target_epoch,
            unavailable=None,
        )

    def _paired_submit(
        self,
        paired_route,
        target_epoch,
        request,
        *,
        timeout_seconds,
    ):
        return self._with_paired_mailbox(
            paired_route,
            lambda mailbox: mailbox.submit(
                target_epoch,
                request,
                timeout_seconds=timeout_seconds,
            ),
            unavailable=MailboxOutcome("session_unavailable"),
        )

    def _paired_consume_reply(self, paired_route, target_epoch):
        return self._with_paired_mailbox(
            paired_route,
            lambda mailbox: mailbox.consume_reply(target_epoch),
            unavailable=MailboxOutcome("session_unavailable"),
        )

    def _with_paired_mailbox(self, paired_route, operation, *, unavailable):
        record = self._record_for_paired_route(paired_route)
        if record is None:
            return unavailable
        with record.operation_lock:
            with self._lock:
                if (self._closed
                        or not self._paired_route_matches_locked(paired_route, record)):
                    return unavailable
                mailbox = record.mailbox_ref()
                if mailbox is None or mailbox.state == "closed":
                    self._clear_bootstrap_locked(record)
                    self._routes.pop(record.route_id, None)
                    return unavailable
            return operation(mailbox)

    def _record_for_registration(self, registration):
        if (type(registration) is not ProjectAgentSessionRegistration
                or registration._registry is not self
                or not _valid_pairing_field(registration.route_id)
                or not _valid_pairing_field(registration._authority)):
            return None
        with self._lock:
            record = self._routes.get(registration.route_id)
            if record is None:
                return None
            if not hmac.compare_digest(
                _digest_secret(registration._authority),
                record.registration_verifier,
            ):
                return None
            return record

    def _registration_matches_locked(self, registration, record):
        return (
            not self._closed
            and type(registration) is ProjectAgentSessionRegistration
            and registration._registry is self
            and self._routes.get(record.route_id) is record
            and registration.route_id == record.route_id
            and _valid_pairing_field(registration._authority)
            and hmac.compare_digest(
                _digest_secret(registration._authority),
                record.registration_verifier,
            )
        )

    def _record_for_paired_route(self, paired_route):
        if (type(paired_route) is not ProjectAgentPairedRoute
                or paired_route._registry is not self
                or paired_route._process_incarnation != self._process_incarnation
                or not _valid_pairing_field(paired_route._route_id)):
            return None
        with self._lock:
            return self._routes.get(paired_route._route_id)

    def _paired_route_matches_locked(self, paired_route, record):
        return (
            not self._closed
            and type(paired_route) is ProjectAgentPairedRoute
            and paired_route._registry is self
            and paired_route._process_incarnation == self._process_incarnation
            and paired_route._route_id == record.route_id
            and paired_route._pairing_generation is not None
            and paired_route._pairing_generation == record.pairing_generation
            and self._routes.get(record.route_id) is record
        )

    def _forget_dead_route(self, route_id, registration_verifier):
        with self._lock:
            record = self._routes.get(route_id)
            if (record is not None and hmac.compare_digest(
                record.registration_verifier, registration_verifier
            )):
                self._clear_bootstrap_locked(record)
                self._routes.pop(route_id, None)

    @staticmethod
    def _clear_bootstrap_locked(record):
        record.bootstrap_verifier = None
        record.bootstrap_expires_at = None


_PROCESS_PROJECT_AGENT_SESSION_REGISTRY = ProjectAgentSessionRegistry()


def get_process_project_agent_session_registry():
    """Return the one module-owned registry for this PromptGraph process."""

    return _PROCESS_PROJECT_AGENT_SESSION_REGISTRY
