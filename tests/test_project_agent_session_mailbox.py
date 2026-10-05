import gc
import threading
import weakref

from ui.project_agent_session_mailbox import (
    ProjectAgentSessionMailbox,
    ProjectTargetTracker,
)


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class Target:
    pass


def make_mailbox(clock=None, epoch="target-a"):
    mailbox = ProjectAgentSessionMailbox(clock=clock or FakeClock())
    mailbox.synchronize_target_epoch(epoch)
    return mailbox


def test_target_tracker_changes_only_for_object_or_path_activation():
    tracker = ProjectTargetTracker()
    first = Target()
    initial = tracker.observe(first, r"C:\Projects\one\project.json")

    assert tracker.observe(first, r"C:\Projects\one\.\project.json") == initial
    first.revision = "in-place edit"
    assert tracker.observe(first, r"C:\Projects\one\project.json") == initial

    replacement = Target()
    replaced = tracker.observe(replacement, r"C:\Projects\one\project.json")
    assert replaced != initial
    path_changed = tracker.observe(replacement, r"C:\Projects\two\project.json")
    assert path_changed != replaced
    no_project = tracker.observe(None, "")
    assert no_project != path_changed
    restored = tracker.observe(Target(), "")
    assert restored != no_project


def test_target_tracker_holds_no_strong_project_reference():
    tracker = ProjectTargetTracker()
    project = Target()
    project_ref = weakref.ref(project)
    tracker.observe(project, "")
    del project
    gc.collect()

    assert project_ref() is None


def test_submit_detaches_json_and_capacity_remains_taken_through_reply():
    clock = FakeClock()
    mailbox = make_mailbox(clock)
    request = {"request_id": "req-1", "tool": "promptgraph_project_summary", "arguments": {}}

    assert mailbox.submit("target-a", request).status == "accepted"
    request["tool"] = "tampered-after-submit"
    assert mailbox.submit("target-a", {}).status == "busy"
    assert mailbox.state == "pending"

    assert mailbox.state == "pending"
    mailbox.begin_full_app_run("target-a")
    claim = mailbox._claim_for_service("target-a")
    assert claim.request["tool"] == "promptgraph_project_summary"
    assert mailbox.complete(claim, {"status": "completed", "result": {"ok": True}}, "target-a").status == "completed"

    assert mailbox.state == "reply_ready"
    assert mailbox.submit("target-a", {}).status == "busy"
    reply = mailbox.consume_reply("target-a")
    assert reply.status == "completed"
    assert reply.reply == {"status": "completed", "result": {"ok": True}}
    assert mailbox.consume_reply("target-a").status == "idle"
    assert mailbox.submit("target-a", {}).status == "accepted"


def test_second_request_is_busy_while_first_is_executing_and_wrong_epoch_is_stale():
    mailbox = make_mailbox()
    request = {"request_id": "req", "tool": "x", "arguments": {}}
    assert mailbox.submit("other-target", request).status == "stale_target"
    assert mailbox.submit("target-a", request).status == "accepted"
    mailbox.begin_full_app_run("target-a")
    claim = mailbox._claim_for_service("target-a")
    assert claim is not None
    assert mailbox.submit("target-a", request).status == "busy"


def test_reply_copy_preserves_large_and_deep_json_without_new_output_limit():
    mailbox = make_mailbox()
    mailbox.submit("target-a", {"request_id": "req", "tool": "x", "arguments": {}})
    mailbox.begin_full_app_run("target-a")
    claim = mailbox._claim_for_service("target-a")
    deep = leaf = {}
    for _ in range(1200):
        child = {}
        leaf["child"] = child
        leaf = child
    large_reply = {"payload": "x" * 2_500_000, "deep": deep}

    assert mailbox.complete(claim, large_reply, "target-a").status == "completed"
    outcome = mailbox.consume_reply("target-a")
    assert outcome.status == "completed"
    assert len(outcome.reply["payload"]) == 2_500_000
    node = outcome.reply["deep"]
    for _ in range(1200):
        node = node["child"]
    assert node == {}


def test_invalid_custom_cyclic_non_json_requests_are_rejected_without_hooks():
    mailbox = make_mailbox()

    class Hostile:
        def __str__(self):
            raise AssertionError("must not coerce")

    assert mailbox.submit("target-a", {"x": Hostile()}).status == "invalid_request"
    cyclic = []
    cyclic.append(cyclic)
    assert mailbox.submit("target-a", {"x": cyclic}).status == "invalid_request"
    assert mailbox.submit("target-a", {1: "non-string key"}).status == "invalid_request"
    assert mailbox.submit("target-a", {"x": float("nan")}).status == "invalid_request"
    assert mailbox.state == "idle"


def test_target_change_invalidates_pending_wake_due_and_unconsumed_reply():
    for prepare in ("pending", "wake_requested", "service_due"):
        mailbox = make_mailbox()
        mailbox.submit("target-a", {"request_id": "req", "tool": "x", "arguments": {}})
        if prepare == "wake_requested":
            assert mailbox.fragment_tick() is True
        elif prepare == "service_due":
            mailbox.begin_full_app_run("target-a")
        mailbox.synchronize_target_epoch("target-b")
        assert mailbox.consume_reply("target-b").status == "stale_target"
        assert mailbox.state == "reply_ready"
        assert mailbox.consume_reply("target-a").status == "stale_target"
        assert mailbox.state == "idle"
        assert mailbox.submit("target-b", {}).status == "accepted"

    mailbox = make_mailbox()
    mailbox.submit("target-a", {"request_id": "req", "tool": "x", "arguments": {}})
    mailbox.begin_full_app_run("target-a")
    claim = mailbox._claim_for_service("target-a")
    mailbox.complete(claim, {"ok": True}, "target-a")
    mailbox.synchronize_target_epoch("target-b")
    assert mailbox.consume_reply("target-b").status == "stale_target"
    assert mailbox.state == "reply_ready"
    assert mailbox.consume_reply("target-a").status == "stale_target"
    assert mailbox.state == "idle"
    assert mailbox.submit("target-b", {}).status == "accepted"


def test_target_change_while_executing_discards_reply_after_dispatch():
    mailbox = make_mailbox()
    mailbox.submit("target-a", {"request_id": "req", "tool": "x", "arguments": {}})
    mailbox.begin_full_app_run("target-a")
    claim = mailbox._claim_for_service("target-a")
    mailbox.synchronize_target_epoch("target-b")

    assert mailbox.complete(claim, {"ok": True}, "target-b").status == "stale_target"
    assert mailbox.consume_reply("target-b").status == "stale_target"
    assert mailbox.state == "reply_ready"
    assert mailbox.consume_reply("target-a").status == "stale_target"
    assert mailbox.state == "idle"
    assert mailbox.submit("target-b", {}).status == "accepted"


def test_original_consumer_clears_stale_outcome_without_rolling_back_epoch():
    mailbox = make_mailbox()
    mailbox.submit("target-a", {"request_id": "req", "tool": "x", "arguments": {}})
    mailbox.begin_full_app_run("target-a")
    claim = mailbox._claim_for_service("target-a")
    mailbox.complete(claim, {"ok": True}, "target-a")
    mailbox.synchronize_target_epoch("target-b")

    # The unrelated new-target consumer cannot release the old request.
    assert mailbox.consume_reply("target-b").status == "stale_target"
    assert mailbox.state == "reply_ready"

    # The original producer can consume its stale terminal result.
    assert mailbox.consume_reply("target-a").status == "stale_target"
    assert mailbox.target_epoch == "target-b"
    assert mailbox.state == "idle"
    assert mailbox.submit(
        "target-b",
        {"request_id": "new-target", "tool": "x", "arguments": {}},
    ).status == "accepted"


def test_expired_or_internal_error_outcome_remains_consumable_by_original_epoch():
    for outcome_kind in ("expired", "internal_error"):
        clock = FakeClock()
        mailbox = make_mailbox(clock)
        mailbox.submit(
            "target-a",
            {"request_id": "req", "tool": "x", "arguments": {}},
            timeout_seconds=1,
        )
        if outcome_kind == "expired":
            clock.advance(1)
            mailbox.begin_full_app_run("target-a")
        else:
            mailbox.begin_full_app_run("target-a")
            claim = mailbox._claim_for_service("target-a")
            assert mailbox.complete(claim, object(), "target-a").status == "internal_error"

        mailbox.synchronize_target_epoch("target-b")
        assert mailbox.consume_reply("target-b").status == "stale_target"
        assert mailbox.state == "reply_ready"
        assert mailbox.consume_reply("target-a").status == outcome_kind
        assert mailbox.target_epoch == "target-b"
        assert mailbox.state == "idle"
        assert mailbox.submit("target-b", {}).status == "accepted"


def test_deadline_rejects_before_service_during_execution_and_before_consumption():
    clock = FakeClock()
    mailbox = make_mailbox(clock)
    mailbox.submit("target-a", {"request_id": "before", "tool": "x", "arguments": {}}, timeout_seconds=2)
    clock.advance(2)
    mailbox.begin_full_app_run("target-a")
    assert mailbox.consume_reply("target-a").status == "expired"

    mailbox.submit("target-a", {"request_id": "during", "tool": "x", "arguments": {}}, timeout_seconds=2)
    mailbox.begin_full_app_run("target-a")
    claim = mailbox._claim_for_service("target-a")
    clock.advance(2)
    assert mailbox.complete(claim, {"ok": True}, "target-a").status == "expired"
    assert mailbox.consume_reply("target-a").status == "expired"

    mailbox.submit("target-a", {"request_id": "reply", "tool": "x", "arguments": {}}, timeout_seconds=2)
    mailbox.begin_full_app_run("target-a")
    claim = mailbox._claim_for_service("target-a")
    mailbox.complete(claim, {"ok": True}, "target-a")
    clock.advance(2)
    assert mailbox.consume_reply("target-a").status == "expired"


def test_fragment_requests_one_wake_and_retries_only_unclaimed_work():
    clock = FakeClock()
    mailbox = make_mailbox(clock)
    mailbox.submit("target-a", {"request_id": "req", "tool": "x", "arguments": {}})
    assert mailbox.fragment_tick() is True
    assert mailbox.fragment_tick() is False
    clock.advance(1)
    assert mailbox.fragment_tick() is True

    mailbox.begin_full_app_run("target-a")
    assert mailbox.fragment_tick() is False
    claim = mailbox._claim_for_service("target-a")
    assert claim is not None
    assert mailbox.fragment_tick() is False


def test_close_is_terminal_and_drops_pending_or_reply_state():
    mailbox = make_mailbox()
    mailbox.submit("target-a", {"request_id": "req", "tool": "x", "arguments": {}})
    mailbox.close()

    assert mailbox.state == "closed"
    assert mailbox.submit("target-a", {}).status == "session_closed"
    assert mailbox.consume_reply("target-a").status == "session_closed"


def test_concurrent_submit_is_capacity_one():
    mailbox = make_mailbox()
    start = threading.Barrier(3)
    results = []

    def submit(request_id):
        start.wait()
        results.append(mailbox.submit("target-a", {
            "request_id": request_id,
            "tool": "promptgraph_project_summary",
            "arguments": {},
        }).status)

    threads = [threading.Thread(target=submit, args=(f"req-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert sorted(results) == ["accepted", "busy"]
    assert all(not thread.is_alive() for thread in threads)
