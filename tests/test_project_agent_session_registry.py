import ast
import gc
import queue
import threading
import weakref
from pathlib import Path

import pytest

from ui.project_agent_session_mailbox import ProjectAgentSessionMailbox
from ui.project_agent_session_pump import ProjectAgentSessionRuntime
from ui.project_agent_session_registry import (
    DEFAULT_PAIRING_LIFETIME_SECONDS,
    PAIRING_BOOTSTRAP_CONTRACT,
    ProjectAgentPairedRoute,
    ProjectAgentSessionRegistry,
    get_process_project_agent_session_registry,
)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _arm_and_claim(registry, registration):
    armed = registration.arm_pairing()
    assert armed.status == "armed"
    bootstrap = armed.bootstrap
    claimed = registry.claim_pairing(
        bootstrap.process_incarnation,
        bootstrap.route_id,
        bootstrap.capability,
    )
    assert claimed.status == "paired"
    return bootstrap, claimed.paired_route


def test_registry_incarnation_and_routes_are_process_and_session_scoped():
    registry = ProjectAgentSessionRegistry()
    other_registry = ProjectAgentSessionRegistry()
    mailbox_a = ProjectAgentSessionMailbox()
    mailbox_b = ProjectAgentSessionMailbox()
    registration_a = registry.register_session(mailbox_a)
    registration_b = registry.register_session(mailbox_b)

    assert registry.process_incarnation
    assert registry.process_incarnation != other_registry.process_incarnation
    assert registration_a.route_id != registration_b.route_id
    assert registration_a is not registration_b
    assert get_process_project_agent_session_registry() is (
        get_process_project_agent_session_registry()
    )
    assert not hasattr(registry, "get_current_session")
    assert not hasattr(registry, "last_registered_session")
    assert not hasattr(registry, "current_session")


def test_registry_module_has_no_streamlit_project_or_transport_dependency():
    module_path = Path(__file__).resolve().parents[1] / "ui" / (
        "project_agent_session_registry.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module or "")

    forbidden = ("streamlit", "core.project", "socket", "multiprocessing", "mcp")
    assert not any(
        name == blocked or name.startswith(f"{blocked}.")
        for name in imported_modules
        for blocked in forbidden
    )


def test_session_runtime_owns_registration_and_arms_only_its_route():
    registry = ProjectAgentSessionRegistry()
    runtime_a = ProjectAgentSessionRuntime(_registry=registry)
    runtime_b = ProjectAgentSessionRuntime(_registry=registry)
    epoch_a = runtime_a.synchronize_target(None, "")
    epoch_b = runtime_b.synchronize_target(None, "")

    offer_a = runtime_a.arm_local_pairing()
    offer_b = runtime_b.arm_local_pairing()
    assert offer_a.status == "armed"
    assert offer_b.status == "armed"
    assert offer_a.bootstrap.contract_version == PAIRING_BOOTSTRAP_CONTRACT
    assert offer_a.bootstrap.process_incarnation == registry.process_incarnation
    assert offer_a.bootstrap.route_id != offer_b.bootstrap.route_id
    assert offer_a.bootstrap.capability
    assert len(offer_a.bootstrap.capability) >= 43
    assert offer_a.bootstrap.expires_in_seconds == DEFAULT_PAIRING_LIFETIME_SECONDS
    assert offer_a.bootstrap.capability not in repr(offer_a.bootstrap)
    with pytest.raises(AttributeError):
        offer_a.bootstrap.route_id = offer_b.bootstrap.route_id
    assert not hasattr(offer_a.bootstrap, "registration_authority")
    assert not hasattr(offer_a.bootstrap, "target_epoch")
    assert not hasattr(offer_a.bootstrap, "project_path")

    claimed_a = registry.claim_pairing(
        offer_a.bootstrap.process_incarnation,
        offer_a.bootstrap.route_id,
        offer_a.bootstrap.capability,
    )
    assert claimed_a.status == "paired"
    route_a = claimed_a.paired_route
    assert type(route_a) is ProjectAgentPairedRoute
    assert route_a.current_target_epoch == epoch_a
    assert route_a.current_target_epoch != epoch_b
    assert not hasattr(route_a, "mailbox")
    assert not hasattr(route_a, "target_tracker")
    assert not hasattr(route_a, "synchronize_target_epoch")
    assert not hasattr(route_a, "_claim_for_service")
    assert not hasattr(route_a, "complete")
    assert not hasattr(route_a, "close")
    with pytest.raises(AttributeError):
        route_a._route_id = offer_b.bootstrap.route_id

    runtime_a.close()
    runtime_b.close()


def test_default_session_runtimes_share_one_process_registry():
    runtime_a = ProjectAgentSessionRuntime()
    runtime_b = ProjectAgentSessionRuntime()

    assert runtime_a._registry is get_process_project_agent_session_registry()
    assert runtime_b._registry is runtime_a._registry
    offer_a = runtime_a.arm_local_pairing().bootstrap
    offer_b = runtime_b.arm_local_pairing().bootstrap
    assert offer_a.route_id != offer_b.route_id
    runtime_a.close()
    runtime_b.close()


def test_two_session_routes_isolate_submit_unpair_target_change_and_cleanup():
    registry = ProjectAgentSessionRegistry()
    runtime_a = ProjectAgentSessionRuntime(_registry=registry)
    runtime_b = ProjectAgentSessionRuntime(_registry=registry)
    epoch_a = runtime_a.synchronize_target(None, "")
    epoch_b = runtime_b.synchronize_target(None, "")
    offer_a = runtime_a.arm_local_pairing().bootstrap
    offer_b = runtime_b.arm_local_pairing().bootstrap
    route_a = registry.claim_pairing(
        offer_a.process_incarnation,
        offer_a.route_id,
        offer_a.capability,
    ).paired_route
    route_b = registry.claim_pairing(
        offer_b.process_incarnation,
        offer_b.route_id,
        offer_b.capability,
    ).paired_route

    assert route_a.submit(epoch_b, {"request_id": "wrong-route"}).status == (
        "stale_target"
    )
    assert runtime_a.mailbox.state == "idle"
    assert runtime_b.mailbox.state == "idle"
    assert route_a.submit(epoch_a, {"request_id": "a"}).status == "accepted"
    assert runtime_b.mailbox.state == "idle"
    runtime_a.synchronize_target(None, r"C:\Projects\changed-a\project.json")
    assert route_a.consume_reply(epoch_a).status == "stale_target"
    assert route_b.current_target_epoch == epoch_b
    assert runtime_b.mailbox.state == "idle"

    assert route_a.release().status == "released"
    assert route_a.current_target_epoch is None
    assert route_b.current_target_epoch == epoch_b
    runtime_a.close()
    assert route_a.submit(epoch_a, {"request_id": "after-cleanup"}).status == (
        "session_unavailable"
    )
    assert route_b.submit(epoch_b, {"request_id": "b"}).status == "accepted"
    runtime_b.close()


def test_route_id_alone_cannot_arm_pairing_and_stale_authority_fails():
    registry = ProjectAgentSessionRegistry()
    mailbox = ProjectAgentSessionMailbox()
    registration = registry.register_session(mailbox)

    assert registry.arm_pairing(registration.route_id).status == "session_unavailable"
    assert registration.arm_pairing().status == "armed"
    assert registration.unregister()
    assert not registration.unregister()
    assert registration.arm_pairing().status == "session_unavailable"
    assert registry.claim_pairing(
        registry.process_incarnation,
        registration.route_id,
        "arbitrary-capability",
    ).status == "invalid_pairing"
    mailbox.close()


def test_wrong_route_capability_and_process_incarnation_do_not_consume_offer():
    registry = ProjectAgentSessionRegistry()
    mailbox_a = ProjectAgentSessionMailbox()
    mailbox_b = ProjectAgentSessionMailbox()
    registration_a = registry.register_session(mailbox_a)
    registration_b = registry.register_session(mailbox_b)
    offer_a = registration_a.arm_pairing().bootstrap
    offer_b = registration_b.arm_pairing().bootstrap

    assert registry.claim_pairing(
        "wrong-process-incarnation",
        offer_a.route_id,
        offer_a.capability,
    ).status == "invalid_pairing"
    assert registry.claim_pairing(
        registry.process_incarnation,
        offer_b.route_id,
        offer_a.capability,
    ).status == "invalid_pairing"
    assert registry.claim_pairing(
        registry.process_incarnation,
        offer_a.route_id,
        "wrong-capability",
    ).status == "invalid_pairing"
    assert registry.claim_pairing(
        registry.process_incarnation,
        offer_a.route_id,
        "\ud800",
    ).status == "invalid_pairing"
    claim_a = registry.claim_pairing(
        registry.process_incarnation,
        offer_a.route_id,
        offer_a.capability,
    )
    assert claim_a.status == "paired"
    assert claim_a.paired_route.current_target_epoch is None
    assert registry.claim_pairing(
        registry.process_incarnation,
        offer_b.route_id,
        offer_b.capability,
    ).status == "paired"
    mailbox_a.close()
    mailbox_b.close()


def test_claim_is_one_use_and_two_simultaneous_claimants_have_one_winner():
    registry = ProjectAgentSessionRegistry()
    mailbox = ProjectAgentSessionMailbox()
    registration = registry.register_session(mailbox)
    bootstrap = registration.arm_pairing().bootstrap
    barrier = threading.Barrier(3)
    results = queue.Queue()

    def claimant():
        barrier.wait(timeout=5)
        results.put(registry.claim_pairing(
            bootstrap.process_incarnation,
            bootstrap.route_id,
            bootstrap.capability,
        ))

    threads = [threading.Thread(target=claimant) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    outcomes = [results.get_nowait(), results.get_nowait()]
    assert [outcome.status for outcome in outcomes].count("paired") == 1
    winner = next(outcome for outcome in outcomes if outcome.status == "paired")
    loser = next(outcome for outcome in outcomes if outcome.status != "paired")
    assert loser.status == "invalid_pairing"
    assert registration.arm_pairing().status == "already_paired"
    assert registry.claim_pairing(
        bootstrap.process_incarnation,
        bootstrap.route_id,
        bootstrap.capability,
    ).status == "invalid_pairing"
    winner.paired_route.release()
    mailbox.close()


def test_rearming_replaces_unclaimed_capability():
    registry = ProjectAgentSessionRegistry()
    mailbox = ProjectAgentSessionMailbox()
    registration = registry.register_session(mailbox)

    old_offer = registration.arm_pairing().bootstrap
    new_offer = registration.arm_pairing().bootstrap
    assert old_offer.capability != new_offer.capability
    assert registry.claim_pairing(
        registry.process_incarnation,
        old_offer.route_id,
        old_offer.capability,
    ).status == "invalid_pairing"
    assert registry.claim_pairing(
        registry.process_incarnation,
        new_offer.route_id,
        new_offer.capability,
    ).status == "paired"
    mailbox.close()


def test_pairing_expiry_is_monotonic_and_rearm_issues_a_fresh_capability():
    clock = FakeClock()
    registry = ProjectAgentSessionRegistry(
        clock=clock,
        pairing_lifetime_seconds=5,
    )
    mailbox = ProjectAgentSessionMailbox()
    registration = registry.register_session(mailbox)

    expires_offer = registration.arm_pairing().bootstrap
    clock.advance(5)
    assert registry.claim_pairing(
        registry.process_incarnation,
        expires_offer.route_id,
        expires_offer.capability,
    ).status == "expired_pairing"
    assert registry.claim_pairing(
        registry.process_incarnation,
        expires_offer.route_id,
        expires_offer.capability,
    ).status == "invalid_pairing"

    fresh_offer = registration.arm_pairing().bootstrap
    assert fresh_offer.capability != expires_offer.capability
    clock.advance(4.999)
    assert registry.claim_pairing(
        registry.process_incarnation,
        fresh_offer.route_id,
        fresh_offer.capability,
    ).status == "paired"
    mailbox.close()


def test_expired_pairing_reason_requires_the_correct_capability():
    clock = FakeClock()
    registry = ProjectAgentSessionRegistry(
        clock=clock,
        pairing_lifetime_seconds=1,
    )
    mailbox = ProjectAgentSessionMailbox()
    registration = registry.register_session(mailbox)
    wrong_offer = registration.arm_pairing().bootstrap
    clock.advance(1)

    assert registry.claim_pairing(
        registry.process_incarnation,
        wrong_offer.route_id,
        "wrong-capability",
    ).status == "invalid_pairing"

    valid_offer = registration.arm_pairing().bootstrap
    clock.advance(1)
    assert registry.claim_pairing(
        registry.process_incarnation,
        valid_offer.route_id,
        valid_offer.capability,
    ).status == "expired_pairing"
    mailbox.close()


def test_target_epoch_changes_do_not_destroy_paired_session_route():
    registry = ProjectAgentSessionRegistry()
    mailbox = ProjectAgentSessionMailbox()
    registration = registry.register_session(mailbox)
    mailbox.synchronize_target_epoch("target-a")
    _bootstrap, route = _arm_and_claim(registry, registration)

    assert route.current_target_epoch == "target-a"
    assert route.submit("target-a", {"request_id": "a"}).status == "accepted"
    mailbox.synchronize_target_epoch("target-b")
    assert route.consume_reply("target-a").status == "stale_target"
    assert route.current_target_epoch == "target-b"
    assert route.submit("target-b", {"request_id": "b"}).status == "accepted"
    assert route.release().status == "released"
    assert route.current_target_epoch is None
    assert registration.arm_pairing().status == "armed"
    mailbox.close()


def test_release_cleanup_and_registry_replacement_invalidate_old_handles():
    registry = ProjectAgentSessionRegistry()
    mailbox = ProjectAgentSessionMailbox()
    registration = registry.register_session(mailbox)
    mailbox.synchronize_target_epoch("target-a")
    bootstrap, old_route = _arm_and_claim(registry, registration)

    assert old_route.release().status == "released"
    assert old_route.submit("target-a", {"request_id": "old"}).status == (
        "session_unavailable"
    )
    assert registry.claim_pairing(
        bootstrap.process_incarnation,
        bootstrap.route_id,
        bootstrap.capability,
    ).status == "invalid_pairing"
    new_bootstrap = registration.arm_pairing().bootstrap
    new_route = registry.claim_pairing(
        new_bootstrap.process_incarnation,
        new_bootstrap.route_id,
        new_bootstrap.capability,
    ).paired_route
    assert old_route.release().status == "already_released"
    assert new_route.current_target_epoch == "target-a"

    registry.close()
    replacement = ProjectAgentSessionRegistry()
    assert replacement.process_incarnation != bootstrap.process_incarnation
    assert replacement.claim_pairing(
        bootstrap.process_incarnation,
        bootstrap.route_id,
        bootstrap.capability,
    ).status == "invalid_pairing"
    assert new_route.current_target_epoch is None
    assert new_route.submit("target-a", {"request_id": "stale"}).status == (
        "session_unavailable"
    )
    mailbox.close()


def test_session_runtime_close_unregisters_before_closing_mailbox_idempotently():
    registry = ProjectAgentSessionRegistry()
    runtime = ProjectAgentSessionRuntime(_registry=registry)
    runtime.synchronize_target(None, "")
    bootstrap = runtime.arm_local_pairing().bootstrap
    route = registry.claim_pairing(
        bootstrap.process_incarnation,
        bootstrap.route_id,
        bootstrap.capability,
    ).paired_route

    runtime.close()
    runtime.close()
    assert runtime.mailbox.state == "closed"
    assert route.current_target_epoch is None
    assert route.submit("target", {"request_id": "closed"}).status == (
        "session_unavailable"
    )
    assert registry.claim_pairing(
        bootstrap.process_incarnation,
        bootstrap.route_id,
        bootstrap.capability,
    ).status == "invalid_pairing"


def test_registry_holds_only_weak_mailbox_reference_and_dead_route_fails_closed():
    registry = ProjectAgentSessionRegistry()
    mailbox = ProjectAgentSessionMailbox()
    mailbox_ref = weakref.ref(mailbox)
    registration = registry.register_session(mailbox)
    bootstrap = registration.arm_pairing().bootstrap

    del mailbox
    gc.collect()

    assert mailbox_ref() is None
    assert registration.arm_pairing().status == "session_unavailable"
    assert registry.claim_pairing(
        bootstrap.process_incarnation,
        bootstrap.route_id,
        bootstrap.capability,
    ).status == "invalid_pairing"
