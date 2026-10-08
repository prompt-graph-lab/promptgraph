"""PR-A tests for session-local, host-computed Scene Module Swap review custody."""

from copy import deepcopy
import queue
import threading

import pytest

from agent_adapters import mcp_adapter
from core import agent_facade
from core.agent_facade import preview_scene_module_swap
from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine
from ui import project_agent_request_bridge as bridge
from ui import project_capture_safety as capture_safety
from ui.agent_scene_module_swap_approval_lifecycle import (
    DEFAULT_PROPOSAL_TTL_SECONDS,
    MAX_PROPOSAL_ENCODED_BYTES,
    AgentSceneModuleSwapApprovalCustodian,
    DuplicateReviewReply,
    PreparedProposalToken,
    PreparedReviewReply,
    _bounded_canonical_identity,
    _valid_preview_envelope,
)
from ui.project_agent_request_bridge import BRIDGE_CONTRACT_VERSION
from ui.project_agent_session_mailbox import MailboxClaim, ProjectAgentSessionMailbox
from ui.project_agent_session_pump import (
    ProjectAgentSessionRuntime,
    service_project_agent_session_request,
)
from ui import project_agent_session_pump as session_pump
from ui.project_agent_session_registry import ProjectAgentSessionRegistry


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ObservedRLock:
    """Signal when a second thread attempts to enter an owned RLock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.contended = threading.Event()

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.contended.set()
            self.lock.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.lock.release()


def _line(line_id, text, index, *, line_type=None):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.png",
        original_index=index,
        current_index=index,
        original_text=text,
        current_text=text,
        tokens=parse_prompt(text) if line_type is None else [],
        line_type=line_type,
    )


def _project():
    return build_graph(Project(
        prompt_lines=[
            _line("scene-1", "First Scene", 0, line_type="separator"),
            _line("illustration-1", "red, blue", 1),
            _line("scene-2", "Empty", 2, line_type="separator"),
        ],
        module_library={
            "source": {"body": "red, blue", "core_tokens": ["red", "blue"]},
            "target": {"body": "gold, green"},
        },
        attribute_groups={},
    ))


def _intent():
    return {
        "scene_id": "scene-1",
        "source_module_name": "source",
        "target_module_name": "target",
        "match_mode": "strict",
    }


def _request(request_id, arguments):
    return {
        "request_id": request_id,
        "tool": "promptgraph_request_scene_module_swap_review",
        "arguments": arguments,
    }


def _expected_arguments(project):
    intent = _intent()
    preview = preview_scene_module_swap(project, intent)
    assert preview["valid"] is True
    return {**intent, "expected_plan_id": preview["plan_id"]}, preview


def _arm_route(runtime, registry):
    armed = runtime.arm_local_pairing()
    assert armed.status == "armed"
    bootstrap = armed.bootstrap
    paired = registry.claim_pairing(
        bootstrap.process_incarnation,
        bootstrap.route_id,
        bootstrap.capability,
    )
    assert paired.status == "paired"
    return paired.paired_route


def _make_staged_review(*, clock=None, preview=None):
    clock = clock or FakeClock()
    preview = preview or preview_scene_module_swap(_project(), _intent())
    custodian = AgentSceneModuleSwapApprovalCustodian(clock=clock)
    mailbox = ProjectAgentSessionMailbox(clock=clock)
    custodian.synchronize_target_epoch("epoch-a")
    mailbox.synchronize_target_epoch("epoch-a", review_custodian=custodian)
    request = _request("request-a", {
        **_intent(), "expected_plan_id": preview["plan_id"],
    })
    assert mailbox.submit(
        "epoch-a", request, _pairing_generation=1,
    ).status == "accepted"
    mailbox.begin_full_app_run("epoch-a")
    claim = mailbox._claim_for_service("epoch-a")
    decision = custodian.check_request(
        "request-a", 1, "epoch-a", {
            **_intent(), "expected_plan_id": preview["plan_id"],
        },
    )
    assert decision.status == "new"
    prepared = custodian.prepare(
        "request-a", 1, "epoch-a",
        {**_intent(), "expected_plan_id": preview["plan_id"]},
        decision.revision,
        preview,
    )
    assert prepared.status == "prepared"
    carrier = PreparedReviewReply({
        "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
        "request_id": "request-a",
        "status": "completed",
        "result": prepared.result,
    }, prepared.token)
    return clock, custodian, mailbox, claim, carrier


def _make_live_pending_review(monkeypatch, *, clock=None):
    monkeypatch.setattr(
        capture_safety._streamlit_config,
        "get_option",
        lambda key: False if key == "runner.fastReruns" else None,
    )
    project = _project()
    arguments, preview = _expected_arguments(project)
    session = {"project": project, "current_project_path": r"C:\Projects\active.json"}
    run_token = capture_safety.begin_project_capture_run(session)
    registry = ProjectAgentSessionRegistry()
    mailbox_kwargs = {} if clock is None else {"clock": clock}
    custodian_kwargs = {} if clock is None else {"clock": clock}
    runtime = ProjectAgentSessionRuntime(
        mailbox=ProjectAgentSessionMailbox(**mailbox_kwargs),
        review_custodian=AgentSceneModuleSwapApprovalCustodian(**custodian_kwargs),
        _registry=registry,
    )
    epoch = runtime.synchronize_target(project, session["current_project_path"])
    route = _arm_route(runtime, registry)
    request = _request("request-a", arguments)
    assert route.submit(epoch, request).status == "accepted"
    assert service_project_agent_session_request(runtime, session, run_token) == "completed"
    initial = route.consume_reply(epoch)
    assert initial.status == "completed"
    assert initial.reply["result"]["status"] == "queued_for_review"
    assert runtime.review_custodian.inspect()["state"] == "pending"
    return runtime, route, registry, session, run_token, epoch, request, preview


def _expanded_preview(preview, *, token_count):
    expanded = deepcopy(preview)
    target_count = 100
    expanded["target_count"] = target_count
    expanded["target_ids"] = [f"illustration-{index}" for index in range(target_count)]
    expanded["changed_count"] = 1
    expanded["no_op_count"] = target_count - 1
    expanded["review_rows_truncated"] = False
    expanded["review_rows_omitted"] = 0
    template = deepcopy(preview["review_rows"][0])
    expanded["review_rows"] = []
    token_text = "x" * 4000
    for index, illustration_id in enumerate(expanded["target_ids"]):
        row = deepcopy(template)
        row["illustration_id"] = illustration_id
        row["scene_order"] = index
        row["changed"] = index == 0
        row["no_op"] = index != 0
        tokens = [{"text": token_text, "truncated": False, "length": 4000}
                  for _ in range(token_count)]
        row["token_delta"] = {
            "added": tokens,
            "removed": [],
            "added_count": len(tokens),
            "removed_count": 0,
            "added_truncated": False,
            "removed_truncated": False,
        }
        expanded["review_rows"].append(row)
    return expanded


def _maximal_facade_preview(preview):
    maximal = _expanded_preview(preview, token_count=100)
    control_text = "\x01" * 4000
    maximal["target_count"] = 1000
    maximal["no_op_count"] = 999
    maximal["review_rows_truncated"] = True
    maximal["review_rows_omitted"] = 900
    maximal["scene_label"] = {
        "text": control_text, "truncated": False, "length": 4000,
    }
    maximal["target_ids"] = [
        f"{index:04}" + "a" * 196 for index in range(1000)
    ]
    for index, row in enumerate(maximal["review_rows"]):
        row["illustration_id"] = maximal["target_ids"][index]
        row["before_positive_prompt"] = {
            "text": control_text, "truncated": False, "length": 4000,
        }
        row["after_positive_prompt"] = {
            "text": control_text, "truncated": False, "length": 4000,
        }
        row["token_delta"]["added"] = [
            {"text": control_text, "truncated": False, "length": 4000}
            for _ in range(100)
        ]
        row["token_delta"]["removed"] = [
            {"text": control_text, "truncated": False, "length": 4000}
            for _ in range(100)
        ]
        row["token_delta"]["added_count"] = 100
        row["token_delta"]["removed_count"] = 100
    return maximal


def test_review_tool_round_trip_is_pair_generation_scoped_and_disconnect_safe(monkeypatch):
    monkeypatch.setattr(
        capture_safety._streamlit_config,
        "get_option",
        lambda key: False if key == "runner.fastReruns" else None,
    )
    project = _project()
    before_project = deepcopy(project)
    arguments, expected_preview = _expected_arguments(project)
    session = {"project": project, "current_project_path": r"C:\Projects\active.json"}
    run_token = capture_safety.begin_project_capture_run(session)
    capture_calls = []
    original_capture = bridge.capture_active_project

    def count_capture(*args):
        capture_calls.append(True)
        return original_capture(*args)

    monkeypatch.setattr(bridge, "capture_active_project", count_capture)
    registry = ProjectAgentSessionRegistry()
    runtime = ProjectAgentSessionRuntime(_registry=registry)
    target_epoch = runtime.synchronize_target(project, session["current_project_path"])
    first_route = _arm_route(runtime, registry)
    try:
        request = _request("review-request-1", arguments)
        assert first_route.submit(target_epoch, request).status == "accepted"
        assert service_project_agent_session_request(runtime, session, run_token) == "completed"
        assert len(capture_calls) == 1
        assert runtime.review_custodian.inspect()["state"] == "pending"
        assert runtime.review_custodian.inspect()["preview"] == expected_preview
        assert project == before_project

        delivered = first_route.consume_reply(target_epoch)
        assert delivered.status == "completed"
        ack = delivered.reply["result"]
        assert ack["ok"] is True
        assert ack["status"] == "queued_for_review"
        assert ack["plan_id"] == expected_preview["plan_id"]
        assert "preview" not in ack and "Project" not in str(ack)

        # An exact retry in this pairing generation returns the same bounded
        # acknowledgement without recapturing the Project or extending TTL.
        before_retry = runtime.review_custodian.inspect()
        expires_at = before_retry["expires_at"]
        assert first_route.submit(target_epoch, request).status == "accepted"
        assert service_project_agent_session_request(runtime, session, run_token) == "completed"
        duplicate = first_route.consume_reply(target_epoch)
        assert duplicate.reply["result"] == ack
        assert len(capture_calls) == 1
        after_retry = runtime.review_custodian.inspect()
        assert after_retry["expires_at"] == expires_at
        assert after_retry["proposal_id"] == before_retry["proposal_id"]
        assert after_retry["preview"] == before_retry["preview"]

        # Reusing the same correlation ID for a different normalized intent
        # is rejected before capture and cannot replace the pending proposal.
        conflicting = _request("review-request-1", {
            **arguments, "target_module_name": "different-target",
        })
        assert first_route.submit(target_epoch, conflicting).status == "accepted"
        assert service_project_agent_session_request(runtime, session, run_token) == "completed"
        conflict_reply = first_route.consume_reply(target_epoch)
        assert conflict_reply.reply["result"]["reason"] == "request_id_conflict"
        assert len(capture_calls) == 1
        assert runtime.review_custodian.inspect()["proposal_id"] == ack["proposal_id"]

        # Ordinary paired-route release leaves committed review custody intact.
        assert first_route.release().status == "released"
        assert runtime.review_custodian.inspect()["state"] == "pending"

        next_route = _arm_route(runtime, registry)
        assert next_route.submit(target_epoch, request).status == "accepted"
        assert service_project_agent_session_request(runtime, session, run_token) == "completed"
        replay = next_route.consume_reply(target_epoch)
        assert replay.reply["result"]["reason"] == "replay_not_accepted"
        assert "proposal_id" not in replay.reply["result"]
        assert len(capture_calls) == 1

        other_request = _request("review-request-2", arguments)
        assert next_route.submit(target_epoch, other_request).status == "accepted"
        assert service_project_agent_session_request(runtime, session, run_token) == "completed"
        busy = next_route.consume_reply(target_epoch)
        assert busy.reply["result"]["reason"] == "review_already_pending"
        assert len(capture_calls) == 1

        class Broker:
            def disarm_launcher_rendezvous(self, _registration):
                return type("Operation", (), {"status": "disarmed"})()

        runtime._named_pipe_broker = Broker()
        assert runtime.disarm_launcher_rendezvous().status == "disarmed"
        assert runtime.review_custodian.inspect()["state"] == "absent"
        next_route.release()
    finally:
        runtime._named_pipe_broker = None
        runtime.close()


@pytest.mark.parametrize(
    "transition",
    ("disarm", "proposal_expiry", "target_switch", "session_close"),
)
def test_duplicate_review_ack_rechecks_live_custody_before_publish(
        monkeypatch, transition):
    clock = FakeClock() if transition == "proposal_expiry" else None
    runtime, route, registry, session, run_token, epoch, request, _preview = (
        _make_live_pending_review(monkeypatch, clock=clock)
    )
    if clock is not None:
        # Leave more than the mailbox request timeout but less than the
        # proposal TTL, so only proposal expiry changes before completion.
        clock.advance(DEFAULT_PROPOSAL_TTL_SECONDS - 30)

    assert route.submit(epoch, request).status == "accepted"

    original_dispatch = session_pump.dispatch_project_agent_request
    retry_preflight_complete = threading.Event()
    allow_publication = threading.Event()

    def pause_after_retry_preflight(*args, **kwargs):
        reply = original_dispatch(*args, **kwargs)
        assert type(reply) is DuplicateReviewReply
        retry_preflight_complete.set()
        if not allow_publication.wait(5):
            raise TimeoutError("test did not resume duplicate completion")
        return reply

    monkeypatch.setattr(
        session_pump,
        "dispatch_project_agent_request",
        pause_after_retry_preflight,
    )
    results = queue.Queue()
    worker = threading.Thread(target=lambda: results.put(
        service_project_agent_session_request(runtime, session, run_token)
    ))
    worker.start()
    assert retry_preflight_complete.wait(5)

    try:
        if transition == "disarm":
            class Broker:
                def disarm_launcher_rendezvous(self, _registration):
                    return type("Operation", (), {"status": "disarmed"})()

            runtime._named_pipe_broker = Broker()
            assert runtime.disarm_launcher_rendezvous().status == "disarmed"
        elif transition == "proposal_expiry":
            clock.advance(31)
        elif transition == "target_switch":
            session["project"] = _project()
            session["current_project_path"] = r"C:\Projects\replacement.json"
            runtime.synchronize_target(
                session["project"],
                session["current_project_path"],
            )
        elif transition == "session_close":
            runtime.close()
    finally:
        allow_publication.set()
        worker.join(5)

    assert not worker.is_alive()
    service_status = results.get_nowait()
    assert service_status != "completed"
    consumed = route.consume_reply(epoch)
    assert not (
        consumed.status == "completed"
        and type(consumed.reply) is dict
        and consumed.reply.get("result", {}).get("status") == "queued_for_review"
    )

    after = runtime.review_custodian.inspect()
    assert after["state"] == "absent"
    if transition == "disarm":
        assert consumed.status == "review_cancelled"
        assert "proposal_id" not in after
    elif transition == "proposal_expiry":
        assert consumed.status == "expired"
    elif transition == "target_switch":
        assert consumed.status == "stale_target"
    else:
        assert consumed.status in ("session_closed", "session_unavailable")

    if transition == "disarm":
        # A new pairing generation cannot retrieve the cancelled proposal's
        # positive acknowledgement from its bounded tombstone.
        assert route.release().status == "released"
        replacement_route = _arm_route(runtime, registry)
        assert replacement_route.submit(epoch, request).status == "accepted"
        monkeypatch.setattr(
            session_pump,
            "dispatch_project_agent_request",
            original_dispatch,
        )
        assert service_project_agent_session_request(
            runtime, session, run_token,
        ) == "completed"
        replay = replacement_route.consume_reply(epoch)
        assert replay.status == "completed"
        assert replay.reply["result"]["reason"] == "replay_not_accepted"
        assert "proposal_id" not in replay.reply["result"]
        replacement_route.release()

    runtime._named_pipe_broker = None
    runtime.close()


def test_observation_and_preview_completions_remain_ordinary_with_pending_review(
        monkeypatch):
    runtime, route, _registry, session, run_token, epoch, _review_request, _preview = (
        _make_live_pending_review(monkeypatch)
    )
    before = runtime.review_custodian.inspect()

    for request_id, tool, arguments in (
        ("ordinary-summary", "promptgraph_project_summary", {}),
        ("ordinary-preview", "promptgraph_preview_scene_module_swap", _intent()),
    ):
        request = _request(request_id, {**arguments})
        request["tool"] = tool
        assert route.submit(epoch, request).status == "accepted"
        assert service_project_agent_session_request(runtime, session, run_token) == "completed"
        delivered = route.consume_reply(epoch)
        assert delivered.status == "completed"
        assert type(delivered.reply["result"]) is dict
        if tool == "promptgraph_preview_scene_module_swap":
            assert delivered.reply["result"]["valid"] is True

    after = runtime.review_custodian.inspect()
    assert after["state"] == "pending"
    assert after["proposal_id"] == before["proposal_id"]
    assert after["expires_at"] == before["expires_at"]
    route.release()
    runtime.close()


def test_review_bridge_without_trusted_session_custody_fails_before_capture(monkeypatch):
    project = _project()
    arguments, _ = _expected_arguments(project)
    session = {"project": project}
    run_token = capture_safety.begin_project_capture_run(session)
    captured = []
    monkeypatch.setattr(bridge, "capture_active_project", lambda *args: captured.append(args))

    reply = bridge.dispatch_project_agent_request(
        session,
        run_token,
        _request("not-hosted", arguments),
    )

    assert reply["status"] == "completed"
    assert reply["result"]["reason"] == "host_review_unavailable"
    assert captured == []


def test_expected_plan_mismatch_and_capture_invalidation_do_not_prepare(monkeypatch):
    monkeypatch.setattr(
        capture_safety._streamlit_config,
        "get_option",
        lambda key: False if key == "runner.fastReruns" else None,
    )
    project = _project()
    arguments, _ = _expected_arguments(project)
    custodian = AgentSceneModuleSwapApprovalCustodian()
    custodian.synchronize_target_epoch("epoch-a")
    session = {"project": project}
    run_token = capture_safety.begin_project_capture_run(session)

    stale = bridge.dispatch_project_agent_request(
        session,
        run_token,
        _request("stale-plan", {**arguments, "expected_plan_id": "0" * 64}),
        review_custodian=custodian,
        pairing_generation=1,
        target_epoch="epoch-a",
    )
    assert stale["result"]["reason"] == "stale_preview"
    assert custodian.inspect()["state"] == "absent"

    custodian = AgentSceneModuleSwapApprovalCustodian()
    custodian.synchronize_target_epoch("epoch-a")
    monkeypatch.setattr(bridge, "is_capture_current", lambda *args: False)
    invalidated = bridge.dispatch_project_agent_request(
        session,
        run_token,
        _request("invalidated-capture", arguments),
        review_custodian=custodian,
        pairing_generation=1,
        target_epoch="epoch-a",
    )
    assert invalidated["result"]["reason"] == "stale_target"
    assert custodian.inspect()["state"] == "absent"


def test_no_op_and_over_limit_facade_previews_never_prepare(monkeypatch):
    monkeypatch.setattr(
        capture_safety._streamlit_config,
        "get_option",
        lambda key: False if key == "runner.fastReruns" else None,
    )
    project = _project()
    arguments, real_preview = _expected_arguments(project)
    session = {"project": project}
    run_token = capture_safety.begin_project_capture_run(session)

    for request_id, reason, updates in (
        ("no-op", "no_op_preview", {"changed_count": 0}),
        ("too-many", "target_limit_exceeded", {"target_count": 1001}),
    ):
        custodian = AgentSceneModuleSwapApprovalCustodian()
        custodian.synchronize_target_epoch("epoch-a")
        preview = deepcopy(real_preview)
        preview.update(updates)
        monkeypatch.setattr(
            agent_facade,
            "preview_scene_module_swap",
            lambda *_args, preview=preview: deepcopy(preview),
        )
        reply = bridge.dispatch_project_agent_request(
            session,
            run_token,
            _request(request_id, arguments),
            review_custodian=custodian,
            pairing_generation=1,
            target_epoch="epoch-a",
        )
        assert reply["status"] == "completed"
        assert reply["result"]["reason"] == reason
        assert custodian.inspect()["state"] == "absent"


def test_complete_with_review_publishes_ack_only_after_pending_commit(monkeypatch):
    _clock, custodian, mailbox, claim, carrier = _make_staged_review()
    observed_lock = ObservedRLock()
    mailbox._lock = observed_lock
    commit_entered = threading.Event()
    allow_commit_return = threading.Event()
    results = queue.Queue()
    original_commit = custodian._commit_prepared_locked

    def pause_after_commit(token, **kwargs):
        committed = original_commit(token, **kwargs)
        commit_entered.set()
        if not allow_commit_return.wait(5):
            raise TimeoutError("test did not release committed review")
        return committed

    custodian._commit_prepared_locked = pause_after_commit

    def complete():
        results.put(("completion", mailbox.complete_with_review(
            claim, carrier, "epoch-a", custodian,
        )))

    def consume():
        results.put(("consumer-started", None))
        outcome = mailbox.consume_reply("epoch-a")
        state = custodian.inspect()["state"]
        results.put(("consumer", state, outcome))

    completion_thread = threading.Thread(target=complete)
    consumer_thread = threading.Thread(target=consume)
    completion_thread.start()
    assert commit_entered.wait(5)
    consumer_thread.start()
    assert observed_lock.contended.wait(5)
    allow_commit_return.set()
    completion_thread.join(5)
    consumer_thread.join(5)

    assert not completion_thread.is_alive() and not consumer_thread.is_alive()
    events = [results.get_nowait() for _ in range(3)]
    outcome = next(item[1] for item in events if item[0] == "completion")
    assert outcome.status == "completed"
    assert ("consumer-started", None) in events
    _tag, state, consumed = next(item for item in events if item[0] == "consumer")
    assert state == "pending"
    assert consumed.status == "completed"
    assert consumed.reply["result"]["status"] == "queued_for_review"
    assert custodian.inspect()["state"] == "pending"


def test_review_completion_failure_rolls_back_prepared_custody():
    cases = (
        "lost_token", "commit_raises", "deadline", "target_switch",
        "session_close", "claim_mismatch", "reply_invalid",
    )
    for case in cases:
        clock, custodian, mailbox, claim, carrier = _make_staged_review()
        if case == "lost_token":
            carrier = PreparedReviewReply(
                carrier.reply,
                PreparedProposalToken("lost-token", carrier.token._revision),
            )
        elif case == "commit_raises":
            original_commit = custodian._commit_prepared_locked

            def raise_after_commit(token, **kwargs):
                original_commit(token, **kwargs)
                raise RuntimeError("private test fault")

            custodian._commit_prepared_locked = raise_after_commit
        elif case == "deadline":
            clock.advance(121)
        elif case == "target_switch":
            mailbox.synchronize_target_epoch("epoch-b", review_custodian=custodian)
        elif case == "session_close":
            mailbox.close(review_custodian=custodian)
        elif case == "claim_mismatch":
            claim = MailboxClaim(
                "wrong-claim", claim.target_epoch, claim.request, claim.pairing_generation,
            )
        elif case == "reply_invalid":
            carrier = PreparedReviewReply(
                {**carrier.reply, "unexpected": True}, carrier.token,
            )

        outcome = mailbox.complete_with_review(claim, carrier, mailbox.target_epoch, custodian)
        assert outcome.status != "completed"
        inspected = custodian.inspect()
        assert inspected["state"] == "absent"
        if mailbox.state == "reply_ready":
            delivered = mailbox.consume_reply("epoch-a")
            assert delivered.status != "completed"
        assert custodian.inspect()["state"] == "absent"


def test_prepared_proposal_is_invisible_until_the_coordinated_mailbox_commit():
    _clock, custodian, mailbox, _claim, _carrier = _make_staged_review()
    assert custodian.inspect()["state"] == "prepared"
    assert mailbox.state == "executing"
    assert mailbox.consume_reply("epoch-a").status == "busy"

    unstarted = AgentSceneModuleSwapApprovalCustodian()
    unstarted.synchronize_target_epoch("epoch-a")
    decision = unstarted.check_request("not-staged", 1, "epoch-a", {
        **_intent(), "expected_plan_id": "0" * 64,
    })
    assert decision.status == "new"
    assert unstarted.inspect()["state"] == "absent"


def test_proposal_size_is_bounded_without_truncating_the_safe_preview(monkeypatch):
    import ui.agent_scene_module_swap_approval_lifecycle as lifecycle

    preview = preview_scene_module_swap(_project(), _intent())
    accepted_preview = _expanded_preview(preview, token_count=8)
    accepted_digest, accepted_size, reason = _bounded_canonical_identity(accepted_preview)
    assert reason == "" and accepted_size < MAX_PROPOSAL_ENCODED_BYTES
    assert len(accepted_digest) == 64

    # The configured operational limit accepts a complete ordinary
    # 100-row review, retaining every visible row without truncation.
    custodian = AgentSceneModuleSwapApprovalCustodian()
    custodian.synchronize_target_epoch("epoch-a")
    intent = {**_intent(), "expected_plan_id": accepted_preview["plan_id"]}
    decision = custodian.check_request("normal", 1, "epoch-a", intent)
    prepared = custodian.prepare(
        "normal", 1, "epoch-a", intent, decision.revision, accepted_preview,
    )
    assert prepared.status == "prepared"
    stored = custodian.inspect()
    assert stored["encoded_size_bytes"] == accepted_size
    assert stored["preview"] == accepted_preview
    assert stored["preview"] is not accepted_preview
    assert stored["preview"]["review_rows_truncated"] is False
    assert len(stored["preview"]["review_rows"]) == 100

    # Equality with the measured canonical byte count is accepted; one byte
    # less rejects the complete envelope instead of truncating it.
    monkeypatch.setattr(lifecycle, "MAX_PROPOSAL_ENCODED_BYTES", accepted_size)
    at_boundary = AgentSceneModuleSwapApprovalCustodian()
    at_boundary.synchronize_target_epoch("epoch-a")
    decision = at_boundary.check_request("boundary", 1, "epoch-a", intent)
    prepared = at_boundary.prepare(
        "boundary", 1, "epoch-a", intent, decision.revision, accepted_preview,
    )
    assert prepared.status == "prepared"
    stored = at_boundary.inspect()
    assert stored["encoded_size_bytes"] == accepted_size
    assert stored["preview"] == accepted_preview
    assert stored["preview"] is not accepted_preview

    monkeypatch.setattr(lifecycle, "MAX_PROPOSAL_ENCODED_BYTES", accepted_size - 1)
    above_boundary = AgentSceneModuleSwapApprovalCustodian()
    above_boundary.synchronize_target_epoch("epoch-a")
    decision = above_boundary.check_request("one-byte-over", 1, "epoch-a", intent)
    rejected = above_boundary.prepare(
        "one-byte-over", 1, "epoch-a", intent, decision.revision, accepted_preview,
    )
    assert rejected.status == "proposal_too_large"
    assert rejected.result is None
    assert above_boundary.inspect()["state"] == "absent"

    monkeypatch.setattr(
        lifecycle, "MAX_PROPOSAL_ENCODED_BYTES", MAX_PROPOSAL_ENCODED_BYTES,
    )
    maximal = _maximal_facade_preview(preview)
    assert _valid_preview_envelope(maximal)
    maximal_digest, maximal_size, reason = _bounded_canonical_identity(maximal)
    assert maximal_digest is None
    assert reason == "proposal_too_large"
    assert maximal_size > MAX_PROPOSAL_ENCODED_BYTES

    # A valid but oversized proposal is rejected before deepcopy, receives no
    # positive acknowledgment, and leaves no partial/prepared/pending record.
    other = AgentSceneModuleSwapApprovalCustodian()
    other.synchronize_target_epoch("epoch-a")
    large_intent = {**_intent(), "expected_plan_id": maximal["plan_id"]}
    large_decision = other.check_request("maximal", 1, "epoch-a", large_intent)
    monkeypatch.setattr(
        lifecycle, "deepcopy",
        lambda *_args, **_kwargs: pytest.fail("oversized proposal must not be copied"),
    )
    rejected = other.prepare(
        "maximal", 1, "epoch-a", large_intent,
        large_decision.revision, maximal,
    )
    assert rejected.status == "proposal_too_large"
    assert rejected.result is None
    assert other.inspect()["state"] == "absent"

    # The same maximal valid envelope is rejected as a whole; it remains
    # intact and is never retained as a truncated review.
    maximal_decision = other.check_request(
        "maximal-valid", 1, "epoch-a",
        {**_intent(), "expected_plan_id": maximal["plan_id"]},
    )
    maximal_rejected = other.prepare(
        "maximal-valid", 1, "epoch-a",
        {**_intent(), "expected_plan_id": maximal["plan_id"]},
        maximal_decision.revision, maximal,
    )
    assert maximal_rejected.status == "proposal_too_large"
    assert maximal_rejected.result is None
    assert other.inspect()["state"] == "absent"
    assert maximal["review_rows_truncated"] is True
    assert len(maximal["review_rows"]) == 100


@pytest.mark.parametrize(
    "arguments",
    [
        {"scene_id": "scene-1", "source_module_name": "source",
         "target_module_name": "target"},
        {"scene_id": "scene-1", "source_module_name": "source",
         "target_module_name": "target", "expected_plan_id": 7},
        {"scene_id": "scene-1", "source_module_name": "source",
         "target_module_name": "target", "expected_plan_id": "0" * 63},
        {"scene_id": "scene-1", "source_module_name": "source",
         "target_module_name": "target", "expected_plan_id": "0" * 64,
         "unexpected": True},
        {"scene_id": "\ud800", "source_module_name": "source",
         "target_module_name": "target", "expected_plan_id": "0" * 64},
    ],
    ids=("missing-plan-id", "wrong-plan-id-type", "wrong-plan-id-length",
         "unknown-key", "invalid-unicode"),
)
def test_invalid_review_arguments_through_mailbox_pump_do_not_capture_or_create_custody(
        monkeypatch, arguments):
    project = _project()
    session = {
        "project": project,
        "current_project_path": r"C:\Projects\active.json",
    }
    run_token = capture_safety.begin_project_capture_run(session)
    registry = ProjectAgentSessionRegistry()
    runtime = ProjectAgentSessionRuntime(_registry=registry)
    epoch = runtime.synchronize_target(project, session["current_project_path"])
    route = _arm_route(runtime, registry)
    monkeypatch.setattr(
        bridge,
        "capture_active_project",
        lambda *_args: pytest.fail("invalid review arguments must not capture"),
    )
    try:
        assert route.submit(
            epoch,
            _request("invalid-through-pump", arguments),
        ).status == "accepted"
        assert service_project_agent_session_request(runtime, session, run_token) == "completed"
        consumed = route.consume_reply(epoch)

        assert consumed.status == "completed"
        assert consumed.reply["result"]["reason"] == "invalid_arguments"
        assert "proposal_id" not in consumed.reply["result"]
        assert runtime.review_custodian.inspect()["state"] == "absent"
        assert route.release().status == "released"
    finally:
        runtime.close()


@pytest.mark.parametrize("commit_first", [False, True], ids=("close-first", "commit-first"))
def test_session_close_racing_review_commit_never_leaves_deliverable_ack_or_custody(
        commit_first):
    _clock, custodian, mailbox, claim, carrier = _make_staged_review()
    runtime = ProjectAgentSessionRuntime(
        mailbox=mailbox,
        review_custodian=custodian,
        _registry=ProjectAgentSessionRegistry(),
    )
    observed_lock = ObservedRLock()
    mailbox._lock = observed_lock
    results = queue.Queue()

    if commit_first:
        commit_entered = threading.Event()
        allow_commit_return = threading.Event()
        original_commit = custodian._commit_prepared_locked

        def pause_after_commit(token, **kwargs):
            committed = original_commit(token, **kwargs)
            commit_entered.set()
            if not allow_commit_return.wait(5):
                raise TimeoutError("test did not release committed review")
            return committed

        custodian._commit_prepared_locked = pause_after_commit

        def complete():
            results.put(mailbox.complete_with_review(
                claim, carrier, "epoch-a", custodian,
            ))

        completion_thread = threading.Thread(target=complete)
        completion_thread.start()
        assert commit_entered.wait(5)
        close_thread = threading.Thread(target=runtime.close)
        close_thread.start()
        assert observed_lock.contended.wait(5)
        allow_commit_return.set()
        completion_thread.join(5)
        close_thread.join(5)
        assert not completion_thread.is_alive()
        assert not close_thread.is_alive()
        assert results.get_nowait().status == "completed"
    else:
        observed_lock.lock.acquire()
        close_thread = threading.Thread(target=runtime.close)
        close_thread.start()
        assert observed_lock.contended.wait(5)
        observed_lock.lock.release()
        close_thread.join(5)
        assert not close_thread.is_alive()
        assert mailbox.complete_with_review(
            claim, carrier, "epoch-a", custodian,
        ).status == "session_closed"

    assert mailbox.state == "closed"
    assert custodian.inspect()["state"] == "absent"
    assert mailbox.consume_reply("epoch-a").status == "session_closed"
    runtime.close()


def test_target_epoch_and_proposal_ttl_invalidate_only_the_session_record():
    clock = FakeClock()
    preview = preview_scene_module_swap(_project(), _intent())
    _clock, custodian, mailbox, claim, carrier = _make_staged_review(
        clock=clock, preview=preview,
    )
    assert mailbox.complete_with_review(claim, carrier, "epoch-a", custodian).status == "completed"
    assert mailbox.consume_reply("epoch-a").status == "completed"
    assert custodian.inspect()["state"] == "pending"

    sibling = AgentSceneModuleSwapApprovalCustodian(clock=clock)
    sibling.synchronize_target_epoch("epoch-a")
    assert sibling.inspect()["state"] == "absent"
    assert sibling.check_request(
        "independent", 8, "epoch-a",
        {**_intent(), "expected_plan_id": preview["plan_id"]},
    ).status == "new"

    custodian.synchronize_target_epoch("epoch-b")
    assert custodian.inspect()["state"] == "absent"
    new_intent = {**_intent(), "expected_plan_id": preview["plan_id"]}
    assert custodian.check_request("new", 2, "epoch-b", new_intent).status == "new"

    # A fresh record has an independent bounded TTL; mailbox reply expiry or
    # consumption does not control its lifetime.
    next_custodian = AgentSceneModuleSwapApprovalCustodian(clock=clock)
    next_custodian.synchronize_target_epoch("epoch-a")
    decision = next_custodian.check_request("ttl", 3, "epoch-a", new_intent)
    prepared = next_custodian.prepare(
        "ttl", 3, "epoch-a", new_intent, decision.revision, preview,
    )
    assert prepared.status == "prepared"
    with next_custodian._lock:
        assert next_custodian._commit_prepared_locked(
            prepared.token,
            request_id="ttl",
            pairing_generation=3,
            target_epoch="epoch-a",
            reply={
                "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
                "request_id": "ttl",
                "status": "completed",
                "result": prepared.result,
            },
            now=clock(),
        )
    clock.advance(15 * 60)
    assert next_custodian.inspect()["state"] == "absent"


def test_request_tombstones_remain_bounded():
    custodian = AgentSceneModuleSwapApprovalCustodian()
    custodian.synchronize_target_epoch("epoch-a")
    with custodian._lock:
        for index in range(100):
            custodian._remember_locked(
                f"request-{index}", 1, f"{index:064x}", "review_unavailable",
            )

    assert len(custodian._tombstones) == 64
    assert "request-0" not in custodian._tombstones
    assert "request-99" in custodian._tombstones


def test_mailbox_reply_expiry_does_not_expire_committed_proposal():
    clock = FakeClock()
    preview = preview_scene_module_swap(_project(), _intent())
    _clock, custodian, mailbox, claim, carrier = _make_staged_review(
        clock=clock, preview=preview,
    )
    assert mailbox.complete_with_review(claim, carrier, "epoch-a", custodian).status == "completed"
    clock.advance(61)

    expired_reply = mailbox.consume_reply("epoch-a")

    assert expired_reply.status == "expired"
    assert custodian.inspect()["state"] == "pending"
