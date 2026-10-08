"""Host-only approval, Apply and Project publication for agent Scene Swap."""

from copy import deepcopy
from threading import Barrier, Event, Lock, Thread, current_thread
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from core.agent_facade import preview_scene_module_swap
from core.graph_builder import build_graph
from core import module_swap_selected_routes as core_module_swap
from core.io import load_project_from_json, save_project_to_json
from core.parser import parse_prompt
from core.project import Project, PromptLine
from ui.agent_scene_module_swap_approval_lifecycle import (
    AgentSceneModuleSwapApprovalCustodian,
    PreparedReviewReply,
)
from ui.agent_scene_module_swap_apply_lifecycle import (
    apply_agent_scene_module_swap_approval,
)
from ui.agent_scene_module_swap_review_panel import _ack_widget_key
from ui.project_agent_request_bridge import BRIDGE_CONTRACT_VERSION
from ui.project_agent_session_mailbox import ProjectAgentSessionMailbox
from ui.project_agent_session_pump import ProjectAgentSessionRuntime
from ui.project_agent_session_registry import ProjectAgentSessionRegistry


ACK_IDENTITY_KEY = "review_ack_identity"
ACK_WIDGET_KEY = "review_ack_checked"
ACTIVE_PATH = "active.json"


class _ObservedGate:
    """Lock wrapper exposing a deterministic contender-arrival event."""

    def __init__(self, observed_thread_name):
        self._lock = Lock()
        self._observed_thread_name = observed_thread_name
        self.observed_attempt = Event()

    def __enter__(self):
        if current_thread().name == self._observed_thread_name:
            self.observed_attempt.set()
        self._lock.acquire()
        return self

    def __exit__(self, *_exc_info):
        self._lock.release()


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _project():
    lines = [
        PromptLine(
            id="scene-a", original_file_name="Scene A", original_index=0,
            current_index=0, original_text="Scene A", current_text="Scene A",
            tokens=[], line_type="separator", separator_label="Scene A",
        ),
        PromptLine(
            id="line-a", original_file_name="line-a.png", original_index=1,
            current_index=1, original_text="red, blue", current_text="red, blue",
            tokens=parse_prompt("red, blue"), negative_prompt="keep negative",
            image_path="keep.png", generated_candidates=[{"path": "candidate.png"}],
            gallery_variants=[{"path": "variant.png"}],
        ),
        PromptLine(
            id="scene-b", original_file_name="Scene B", original_index=2,
            current_index=2, original_text="Scene B", current_text="Scene B",
            tokens=[], line_type="separator", separator_label="Scene B",
        ),
    ]
    return build_graph(Project(
        source_directory="project-source",
        prompt_lines=lines,
        module_library={
            "source": {"body": "red, blue", "core_tokens": ["red", "blue"]},
            "target": {"body": "gold, green", "core_tokens": ["gold", "green"]},
        },
        attribute_groups={},
    ))


def _intent():
    return {
        "scene_id": "scene-a",
        "source_module_name": "source",
        "target_module_name": "target",
        "match_mode": "strict",
    }


def _runtime_with_pending(
    project,
    *,
    clock=None,
    include_unconsumed_ack=False,
    project_path=ACTIVE_PATH,
):
    mailbox_kwargs = {} if clock is None else {"clock": clock}
    custodian_kwargs = {} if clock is None else {"clock": clock}
    runtime = ProjectAgentSessionRuntime(
        mailbox=ProjectAgentSessionMailbox(**mailbox_kwargs),
        review_custodian=AgentSceneModuleSwapApprovalCustodian(**custodian_kwargs),
        _registry=ProjectAgentSessionRegistry(),
    )
    epoch = runtime.synchronize_target(project, project_path)
    preview = preview_scene_module_swap(project, _intent())
    assert preview["valid"] is True
    assert preview["changed_count"] == 1
    intent = {**_intent(), "expected_plan_id": preview["plan_id"]}

    if include_unconsumed_ack:
        request = {
            "request_id": "request-a",
            "tool": "promptgraph_request_scene_module_swap_review",
            "arguments": intent,
        }
        assert runtime.mailbox.submit(
            epoch, request, _pairing_generation=1,
        ).status == "accepted"
        runtime.mailbox.begin_full_app_run(epoch)
        mailbox_claim = runtime.mailbox._claim_for_service(epoch)
        assert mailbox_claim is not None

    custodian = runtime.review_custodian
    decision = custodian.check_request("request-a", 1, epoch, intent)
    assert decision.status == "new"
    prepared = custodian.prepare(
        "request-a", 1, epoch, intent, decision.revision, preview,
    )
    assert prepared.status == "prepared"
    reply = {
        "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
        "request_id": "request-a",
        "status": "completed",
        "result": prepared.result,
    }

    if include_unconsumed_ack:
        outcome = runtime.mailbox.complete_with_review(
            mailbox_claim,
            PreparedReviewReply(reply, prepared.token),
            epoch,
            custodian,
        )
        assert outcome.status == "completed"
        assert runtime.mailbox.state == "reply_ready"
    else:
        with custodian._lock:
            assert custodian._commit_prepared_locked(
                prepared.token,
                request_id="request-a",
                pairing_generation=1,
                target_epoch=epoch,
                reply=reply,
                now=custodian._clock(),
            )
    review = runtime.inspect_review_custody()
    assert review["state"] == "pending"
    return runtime, epoch, review


def _state(project, review, *, checked=True, project_path=ACTIVE_PATH):
    state = {
        "project": project,
        "current_project_path": project_path,
        "history": [],
        "focused_line_id": "line-a",
        "selected_node_ids": ["stale-node"],
        "gallery_selected_route_ids": ["scene-a"],
        "module_swap_preview": {"stale": True},
        "module_swap_selected_routes_confirm": True,
        ACK_IDENTITY_KEY: (review["proposal_id"], review["plan_id"]),
        ACK_WIDGET_KEY: checked,
    }
    return state


def _apply(runtime, state, review, project, *, callbacks=None):
    callbacks = callbacks or {}
    return apply_agent_scene_module_swap_approval(
        state,
        runtime,
        project=project,
        project_path=state.get("current_project_path", ACTIVE_PATH),
        proposal_id=review["proposal_id"],
        plan_id=review["plan_id"],
        acknowledgment_identity_key=ACK_IDENTITY_KEY,
        acknowledgment_identity=(review["proposal_id"], review["plan_id"]),
        acknowledgment_widget_key=ACK_WIDGET_KEY,
        synchronize_gallery_selection=callbacks.get("selection"),
        restore_focus=callbacks.get("focus"),
        sync_text_areas=callbacks.get("text"),
        save_project=callbacks.get("save", lambda _project, _path, _reason: True),
    )


def test_success_revalidates_applies_one_scene_and_publishes_in_order():
    project = _project()
    runtime, epoch, review = _runtime_with_pending(
        project, include_unconsumed_ack=True,
    )
    events = []
    state = _state(project, review)

    def selection(updated):
        assert state["project"] is updated
        # Selection publication runs only after the pre-Apply snapshot has
        # entered history and the Project replacement has been installed.
        assert len(state["history"]) == 1
        events.append(("history", project, state["history"][0]))
        events.append(("selection", updated))

    def focus(previous):
        assert previous == "line-a"
        assert state["project"] is not project
        events.append(("focus", state["project"]))

    def text_sync():
        events.append(("text", state["project"]))

    def save(saved_project, destination, reason):
        assert reason == "Agent Scene Module Swap applied"
        assert saved_project is state["project"]
        assert destination == ACTIVE_PATH
        assert state["project"] is not project
        assert runtime.inspect_review_custody()["state"] == "applying"
        events.append(("save", saved_project, destination))
        return True

    before = deepcopy(project)
    with patch(
        "ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
        wraps=core_module_swap.apply_selected_routes_module_swap,
    ) as core_apply:
        result = _apply(
            runtime, state, review, project,
            callbacks={"selection": selection, "focus": focus, "text": text_sync, "save": save},
        )

    assert result == {
        "status": "applied",
        "applied_count": 1,
        "save_succeeded": True,
        "sync_warning": False,
    }
    assert [event[0] for event in events] == ["history", "selection", "focus", "text", "save"]
    assert events[0][1] is project
    assert events[0][2] == before
    assert state["project"] is not project
    assert state["project"].prompt_lines[1].current_text == "gold, green"
    assert state["project"].prompt_lines[1].negative_prompt == "keep negative"
    assert state["project"].prompt_lines[1].image_path == "keep.png"
    assert state["project"].module_library == project.module_library
    assert core_apply.call_count == 1
    assert core_apply.call_args.args[1] == ["scene-a"]
    assert core_apply.call_args.kwargs["expected_signature"] == (
        review["preview"]["source_fingerprint"]
    )
    assert core_apply.call_args.kwargs["source_module_name"] == "source"
    assert core_apply.call_args.kwargs["target_module_name"] == "target"
    assert core_apply.call_args.kwargs["match_mode"] == "strict"
    assert core_apply.call_args.kwargs["project_path"] == ""
    assert core_apply.call_args.kwargs["disabled_modules"] is None
    assert runtime.synchronize_target(state["project"], ACTIVE_PATH) != epoch
    assert state["selected_node_ids"] == []
    assert state["gallery_selected_route_ids"] == ["scene-a"]
    assert "module_swap_preview" not in state
    assert "module_swap_selected_routes_confirm" not in state
    assert runtime.inspect_review_custody()["state"] == "applied"
    assert runtime.inspect_review_custody()["result"] == {
        "applied_count": 1,
        "save_succeeded": True,
        "scene_label": "Scene A",
        "source_module_name": "source",
        "target_module_name": "target",
    }

    # The undelivered MCP result remains a queue-only cancellation; it cannot
    # contain the later human Apply result.
    mailbox_outcome = runtime.mailbox.consume_reply(epoch)
    assert mailbox_outcome.status == "review_cancelled"
    assert mailbox_outcome.reply is None

    repeated = _apply(runtime, state, review, project)
    assert repeated["status"] == "applied"
    assert len(state["history"]) == 1
    runtime.close()


def test_autosave_failure_keeps_project_and_history_and_consumes_approval():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    result = _apply(runtime, state, review, project, callbacks={"save": lambda *_args: False})

    assert result["status"] == "applied_save_failed"
    assert result["save_succeeded"] is False
    assert state["project"] is not project
    assert len(state["history"]) == 1
    assert runtime.inspect_review_custody()["state"] == "applied_save_failed"
    assert _apply(runtime, state, review, project)["status"] == "applied_save_failed"
    assert len(state["history"]) == 1
    runtime.close()


def test_persistence_owner_receives_exact_applied_project_and_original_path(tmp_path):
    project = _project()
    destination = str(tmp_path / "approved-project.json")
    runtime, _epoch, review = _runtime_with_pending(
        project,
        project_path=destination,
    )
    state = _state(project, review, project_path=destination)
    observed = []

    def persist(saved_project, saved_path, reason):
        observed.append((saved_project, saved_path, reason))
        assert saved_project is state["project"]
        assert saved_path == destination
        save_project_to_json(saved_project, saved_path)
        return True

    result = _apply(
        runtime,
        state,
        review,
        project,
        callbacks={"save": persist},
    )

    assert result["status"] == "applied"
    assert observed == [(
        state["project"],
        destination,
        "Agent Scene Module Swap applied",
    )]
    assert observed[0][0] is state["project"]
    assert observed[0][0] is not project
    persisted = load_project_from_json(destination)
    assert persisted.prompt_lines[1].current_text == "gold, green"
    runtime.close()


def test_late_unrelated_source_edit_after_post_apply_preview_blocks_publication():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    saved = []
    real_publish = runtime.publish_review_apply
    real_preview = preview_scene_module_swap
    preview_count = 0

    def count_preview(*args, **kwargs):
        nonlocal preview_count
        preview_count += 1
        return real_preview(*args, **kwargs)

    def late_edit_then_publish(*args, **kwargs):
        # Both pre-Apply and post-core facade previews have passed by the time
        # the lifecycle reaches its final publication decision.
        assert preview_count == 2
        project.project_metadata["edited_after_final_preview"] = True
        return real_publish(*args, **kwargs)

    runtime.publish_review_apply = late_edit_then_publish
    with patch(
        "ui.agent_scene_module_swap_apply_lifecycle.preview_scene_module_swap",
        side_effect=count_preview,
    ) as facade_preview:
        with patch(
            "ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
            wraps=core_module_swap.apply_selected_routes_module_swap,
        ) as core_apply:
            result = _apply(
                runtime,
                state,
                review,
                project,
                callbacks={
                    "save": lambda _project, _path, reason: saved.append(reason) or True,
                },
            )

    assert facade_preview.call_count == 2
    assert core_apply.call_count == 1
    assert result["status"] == "stale"
    assert state["project"] is project
    assert state["history"] == []
    assert saved == []
    assert project.project_metadata["edited_after_final_preview"] is True
    assert project.prompt_lines[1].current_text == "red, blue"
    assert runtime.inspect_review_custody()["state"] == "stale"
    runtime.close()


def test_core_failure_consumes_claim_without_host_publication():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    saved = []
    failed_core = {
        "applied": False,
        "stale_preview": False,
        "applied_count": 0,
        "error": "ignored by host",
        "updated_project": None,
    }
    with patch(
        "ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
        return_value=failed_core,
    ) as core_apply:
        result = _apply(
            runtime,
            state,
            review,
            project,
            callbacks={"save": lambda _project, _path, reason: saved.append(reason) or True},
        )

    assert core_apply.call_count == 1
    assert result["status"] == "apply_failed"
    assert state["project"] is project
    assert state["history"] == []
    assert saved == []
    assert runtime.inspect_review_custody()["state"] == "apply_failed"
    assert _apply(runtime, state, review, project)["status"] == "apply_failed"
    assert core_apply.call_count == 1
    runtime.close()


@pytest.mark.parametrize("stale_kind", ["prompt", "module", "project"])
def test_stale_prompt_or_target_change_has_no_publication(stale_kind):
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    saved = []
    if stale_kind == "prompt":
        line = project.prompt_lines[1]
        line.current_text = "red, blue, edited"
        line.tokens = parse_prompt(line.current_text)
    elif stale_kind == "module":
        project.module_library["target"]["body"] = "silver, violet"
    else:
        replacement = _project()
        state["project"] = replacement
        state["current_project_path"] = "replacement.json"

    result = _apply(runtime, state, review, project, callbacks={"save": lambda _project, _path, reason: saved.append(reason)})

    assert result["status"] == "stale"
    assert state["history"] == []
    assert saved == []
    assert runtime.inspect_review_custody()["state"] == "stale"
    runtime.close()


@pytest.mark.parametrize("stale_kind", ["prompt", "module"])
def test_in_place_edit_during_real_core_apply_survives_without_host_publication(stale_kind):
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    saved = []
    real_core_apply = core_module_swap.apply_selected_routes_module_swap

    def edit_source_after_clone_is_built(*args, **kwargs):
        result = real_core_apply(*args, **kwargs)
        if stale_kind == "prompt":
            line = project.prompt_lines[1]
            line.current_text = "red, blue, edit made during Apply"
            line.tokens = parse_prompt(line.current_text)
        else:
            project.module_library["source"]["body"] = "red, blue, edit during Apply"
        return result

    with patch(
        "ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
        side_effect=edit_source_after_clone_is_built,
    ) as core_apply:
        result = _apply(
            runtime,
            state,
            review,
            project,
            callbacks={"save": lambda _project, _path, reason: saved.append(reason) or True},
        )

    assert core_apply.call_count == 1
    assert result["status"] == "stale"
    assert state["project"] is project
    assert state["history"] == []
    assert saved == []
    if stale_kind == "prompt":
        assert project.prompt_lines[1].current_text == "red, blue, edit made during Apply"
    else:
        assert project.module_library["source"]["body"] == "red, blue, edit during Apply"
    assert runtime.inspect_review_custody()["state"] == "stale"
    runtime.close()


def test_project_replacement_failure_rolls_back_the_staged_undo_entry():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)

    class RejectReplacement(dict):
        def __setitem__(self, key, value):
            if key == "project" and value is not project:
                raise OSError("simulated session publication failure")
            return super().__setitem__(key, value)

    state = RejectReplacement(_state(project, review))
    saved = []
    result = _apply(
        runtime,
        state,
        review,
        project,
        callbacks={"save": lambda _project, _path, reason: saved.append(reason) or True},
    )

    assert result["status"] == "apply_failed"
    assert state["project"] is project
    assert state["history"] == []
    assert saved == []
    assert runtime.inspect_review_custody()["state"] == "apply_failed"
    runtime.close()


@pytest.mark.parametrize("winner", ["disarm", "close", "target_switch"])
def test_revocation_or_target_switch_winning_before_publication_prevents_commit(winner):
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    saved = []
    replacement = _project()
    publication_ready = Event()
    allow_publication = Event()
    real_publish = runtime.publish_review_apply

    def pause_before_publication_gate(*args, **kwargs):
        publication_ready.set()
        assert allow_publication.wait(timeout=5)
        return real_publish(*args, **kwargs)

    runtime.publish_review_apply = pause_before_publication_gate
    with ThreadPoolExecutor(max_workers=1) as pool:
        attempt = pool.submit(
            _apply,
            runtime,
            state,
            review,
            project,
            callbacks={"save": lambda _project, _path, reason: saved.append(reason) or True},
        )
        assert publication_ready.wait(timeout=5)
        if winner == "disarm":
            class FakeBroker:
                def disarm_launcher_rendezvous(self, _registration):
                    return type("Operation", (), {"status": "disarmed"})()

                def close_session_route(self, _route_id):
                    return None

                def forget_launcher_rendezvous(self, _registration):
                    return None

            runtime._named_pipe_broker = FakeBroker()
            assert runtime.disarm_launcher_rendezvous().status == "disarmed"
        elif winner == "close":
            runtime.close()
        else:
            state["project"] = replacement
            state["current_project_path"] = "replacement.json"
            runtime.synchronize_target(replacement, "replacement.json")
        allow_publication.set()
        result = attempt.result(timeout=10)

    expected_status = {
        "disarm": "dismissed",
        "close": "session_unavailable",
        "target_switch": "stale",
    }[winner]
    assert result["status"] == expected_status
    assert state["project"] is (replacement if winner == "target_switch" else project)
    assert state["history"] == []
    assert saved == []
    if winner != "close":
        assert runtime.inspect_review_custody()["state"] == expected_status
        runtime.close()


@pytest.mark.parametrize("winner", ["disarm", "close"])
def test_publication_gate_winning_before_revocation_keeps_apply_success(winner):
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    gate = _ObservedGate(f"{winner}-racer")
    runtime._publication_gate = gate
    entered_public_assignment = Event()
    racer_done = Event()
    saved = []

    class CompetingState(dict):
        def __setitem__(self, key, value):
            if key == "project" and value is not project:
                def revoke():
                    try:
                        if winner == "disarm":
                            class FakeBroker:
                                def disarm_launcher_rendezvous(self, _registration):
                                    return type("Operation", (), {"status": "disarmed"})()

                                def close_session_route(self, _route_id):
                                    return None

                                def forget_launcher_rendezvous(self, _registration):
                                    return None

                            runtime._named_pipe_broker = FakeBroker()
                            runtime.disarm_launcher_rendezvous()
                        else:
                            runtime.close()
                    finally:
                        racer_done.set()

                Thread(target=revoke, name=f"{winner}-racer").start()
                assert gate.observed_attempt.wait(timeout=5)
                entered_public_assignment.set()
            return super().__setitem__(key, value)

    state = CompetingState(_state(project, review))
    result = _apply(
        runtime,
        state,
        review,
        project,
        callbacks={"save": lambda _project, _path, reason: saved.append(reason) or True},
    )
    assert entered_public_assignment.is_set()
    assert racer_done.wait(timeout=5)
    assert result["status"] in {"applied", "applied_save_failed"}
    assert state["project"] is not project
    assert len(state["history"]) == 1
    if winner == "disarm":
        assert result["status"] == "applied"
        assert saved == ["Agent Scene Module Swap applied"]
        assert runtime.inspect_review_custody()["state"] == "applied"
    elif result["status"] == "applied":
        assert saved == ["Agent Scene Module Swap applied"]
    else:
        assert result["save_succeeded"] is False
        assert saved == []


def test_session_close_after_publication_reports_unsaved_apply_without_rollback():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    saved = []
    real_publish = runtime.publish_review_apply

    def publish_then_close(*args, **kwargs):
        status = real_publish(*args, **kwargs)
        assert status == "published"
        runtime.close()
        return status

    runtime.publish_review_apply = publish_then_close
    result = _apply(
        runtime,
        state,
        review,
        project,
        callbacks={
            "save": lambda _project, _path, reason: saved.append(reason) or True,
        },
    )

    assert result == {
        "status": "applied_save_failed",
        "applied_count": 1,
        "save_succeeded": False,
        "sync_warning": False,
    }
    assert state["project"] is not project
    assert state["project"].prompt_lines[1].current_text == "gold, green"
    assert len(state["history"]) == 1
    assert saved == []


@pytest.mark.parametrize("switch_kind", ["project", "path"])
def test_target_identity_or_path_change_after_publication_skips_reconciliation_and_save(
    switch_kind,
):
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    newer_project = _project()
    state = _state(project, review)
    state["autosave_feedback"] = "B was already saved"
    state["last_saved_at"] = "B saved timestamp"
    state["selected_node_ids"] = ["B selected node"]
    state["gallery_selected_route_ids"] = ["B selected scene"]
    state["focused_line_id"] = "B focused line"
    state["module_swap_preview"] = {"belongs_to": "B"}
    state["module_swap_selected_routes_confirm"] = "B widget state"
    callbacks_called = []
    saved = []
    real_publish = runtime.publish_review_apply

    def publish_then_switch_target(*args, **kwargs):
        status = real_publish(*args, **kwargs)
        assert status == "published"
        with runtime._publication_gate:
            if switch_kind == "project":
                state["project"] = newer_project
                # Same path makes the object-identity part of the guard
                # observable independently from destination validation.
                runtime._synchronize_target_locked(newer_project, ACTIVE_PATH)
            else:
                # A same-object Save As changes the validated destination.
                state["current_project_path"] = "newer.json"
                runtime._synchronize_target_locked(
                    state["project"],
                    "newer.json",
                )
        return status

    runtime.publish_review_apply = publish_then_switch_target

    result = _apply(
        runtime,
        state,
        review,
        project,
        callbacks={
            "selection": lambda *_args: callbacks_called.append("selection"),
            "focus": lambda *_args: callbacks_called.append("focus"),
            "text": lambda *_args: callbacks_called.append("text"),
            "save": lambda *_args: saved.append("save") or True,
        },
    )

    assert result == {
        "status": "applied_save_failed",
        "applied_count": 1,
        "save_succeeded": False,
        "sync_warning": False,
    }
    if switch_kind == "project":
        assert state["project"] is newer_project
        assert state["current_project_path"] == ACTIVE_PATH
    else:
        assert state["project"] is not project
        assert state["current_project_path"] == "newer.json"
    assert len(state["history"]) == 1
    assert saved == []
    assert callbacks_called == []
    assert state["autosave_feedback"] == "B was already saved"
    assert state["last_saved_at"] == "B saved timestamp"
    assert state["selected_node_ids"] == ["B selected node"]
    assert state["gallery_selected_route_ids"] == ["B selected scene"]
    assert state["focused_line_id"] == "B focused line"
    assert state["module_swap_preview"] == {"belongs_to": "B"}
    assert state["module_swap_selected_routes_confirm"] == "B widget state"
    assert runtime.inspect_review_custody()["state"] == "applied_save_failed"
    assert runtime.inspect_review_custody()["result"]["save_succeeded"] is False
    runtime.close()


def test_duplicate_approval_callback_waiting_during_publication_cannot_apply_twice():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    gate = _ObservedGate("duplicate-racer_1")
    runtime._publication_gate = gate
    publication_entered = Event()
    allow_project_assignment = Event()

    class PausingState(dict):
        def __setitem__(self, key, value):
            if key == "project" and value is not project:
                publication_entered.set()
                assert allow_project_assignment.wait(timeout=5)
            return super().__setitem__(key, value)

    state = PausingState(state)
    with patch(
        "ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
        wraps=core_module_swap.apply_selected_routes_module_swap,
    ) as core_apply:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="duplicate-racer") as pool:
            first = pool.submit(_apply, runtime, state, review, project)
            assert publication_entered.wait(timeout=5)
            second = pool.submit(_apply, runtime, state, review, project)
            assert gate.observed_attempt.wait(timeout=5)
            allow_project_assignment.set()
            first_result = first.result(timeout=10)
            second_result = second.result(timeout=10)

    assert first_result["status"] == "applied"
    assert second_result["status"] in {"applying", "applied"}
    assert core_apply.call_count == 1
    assert len(state["history"]) == 1
    assert runtime.inspect_review_custody()["state"] == "applied"
    runtime.close()


def test_target_switch_during_core_apply_blocks_replacement_publication():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    replacement = _project()
    saved = []
    real_core_apply = core_module_swap.apply_selected_routes_module_swap

    def switch_target_during_core(*args, **kwargs):
        result = real_core_apply(*args, **kwargs)
        state["project"] = replacement
        state["current_project_path"] = "replacement.json"
        runtime.synchronize_target(replacement, "replacement.json")
        return result

    with patch(
        "ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
        side_effect=switch_target_during_core,
    ):
        result = _apply(
            runtime,
            state,
            review,
            project,
            callbacks={"save": lambda _project, _path, reason: saved.append(reason) or True},
        )

    assert result["status"] == "stale"
    assert state["project"] is replacement
    assert state["history"] == []
    assert saved == []
    assert runtime.inspect_review_custody()["state"] == "stale"
    runtime.close()


def test_session_close_during_core_apply_blocks_replacement_publication():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    saved = []
    real_core_apply = core_module_swap.apply_selected_routes_module_swap

    def close_session_during_core(*args, **kwargs):
        result = real_core_apply(*args, **kwargs)
        runtime.close()
        return result

    with patch(
        "ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
        side_effect=close_session_during_core,
    ):
        result = _apply(
            runtime,
            state,
            review,
            project,
            callbacks={"save": lambda _project, _path, reason: saved.append(reason) or True},
        )

    assert result["status"] == "session_unavailable"
    assert state["project"] is project
    assert state["history"] == []
    assert saved == []


def test_explicit_disarm_during_core_apply_revokes_claim_before_publication():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    saved = []
    real_core_apply = core_module_swap.apply_selected_routes_module_swap

    class FakeBroker:
        def disarm_launcher_rendezvous(self, _registration):
            return type("Operation", (), {"status": "disarmed"})()

    runtime._named_pipe_broker = FakeBroker()

    def disarm_during_core(*args, **kwargs):
        result = real_core_apply(*args, **kwargs)
        assert runtime.disarm_launcher_rendezvous().status == "disarmed"
        return result

    with patch(
        "ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
        side_effect=disarm_during_core,
    ):
        result = _apply(
            runtime,
            state,
            review,
            project,
            callbacks={"save": lambda _project, _path, reason: saved.append(reason) or True},
        )

    assert result["status"] == "dismissed"
    assert state["project"] is project
    assert state["history"] == []
    assert saved == []
    assert runtime.inspect_review_custody()["state"] == "dismissed"
    runtime._named_pipe_broker = None
    runtime.close()


def test_missing_human_acknowledgment_cannot_claim_or_apply():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review, checked=False)
    with patch(
        "ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
    ) as core_apply:
        result = _apply(runtime, state, review, project)
    assert result == {"status": "acknowledgment_required"}
    assert core_apply.call_count == 0
    assert runtime.inspect_review_custody()["state"] == "pending"
    assert state["history"] == []
    runtime.close()


def test_review_panel_requires_staged_ack_then_dispatches_direct_host_apply():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    identity = (review["proposal_id"], review["plan_id"])
    ack_key = _ack_widget_key(identity)
    apply_key = f"agent_scene_swap_review_apply_{identity[0]}_{identity[1]}"
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui.agent_scene_module_swap_apply_lifecycle import apply_agent_scene_module_swap_approval\n"
        "from ui.agent_scene_module_swap_review_panel import render_agent_scene_module_swap_review_panel\n"
        "def _apply_handler(**approval):\n"
        "    return apply_agent_scene_module_swap_approval(\n"
        "        **approval,\n"
        "        synchronize_gallery_selection=lambda project: None,\n"
        "        restore_focus=lambda focus: None,\n"
        "        sync_text_areas=lambda: None,\n"
        "        save_project=lambda _project, _path, reason: True,\n"
        "    )\n"
        "render_agent_scene_module_swap_review_panel(\n"
        "    st.session_state['project'],\n"
        "    st.session_state['review_runtime'],\n"
        "    st.session_state['current_project_path'],\n"
        "    apply_handler=_apply_handler,\n"
        ")\n",
        default_timeout=30,
    )
    app.session_state["project"] = project
    app.session_state["current_project_path"] = ACTIVE_PATH
    app.session_state["history"] = []
    app.session_state["focused_line_id"] = "line-a"
    app.session_state["selected_node_ids"] = []
    app.session_state["review_runtime"] = runtime
    app.run(timeout=30)

    assert not app.exception
    assert app.button(key=apply_key).disabled is True
    app.checkbox(key=ack_key).check().run(timeout=30)
    assert not app.exception
    assert app.button(key=apply_key).disabled is False
    app.button(key=apply_key).click().run(timeout=30)

    assert not app.exception
    assert app.session_state["project"] is not project
    assert app.session_state["project"].prompt_lines[1].current_text == "gold, green"
    assert len(app.session_state["history"]) == 1
    assert runtime.inspect_review_custody()["state"] == "applied"
    assert any(element.value == "Scene: Scene A" for element in app.text)
    assert any(
        element.value == "Module swap: source → target"
        for element in app.text
    )
    assert any(
        "Undo: the pre-Apply Project is available in history." in element.value
        for element in app.caption
    )
    runtime.close()


def test_duplicate_approval_callbacks_claim_once_and_apply_at_most_once():
    project = _project()
    runtime, _epoch, review = _runtime_with_pending(project)
    state = _state(project, review)
    original_claim = runtime.claim_review_proposal_for_apply
    barrier = Barrier(2)

    def synchronized_claim(*args):
        barrier.wait(timeout=5)
        return original_claim(*args)

    runtime.claim_review_proposal_for_apply = synchronized_claim
    with patch(
        "ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
        wraps=__import__("core.module_swap_selected_routes", fromlist=[
            "apply_selected_routes_module_swap",
        ]).apply_selected_routes_module_swap,
    ) as core_apply:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_apply, runtime, state, review, project) for _ in range(2)]
            outcomes = [future.result(timeout=10) for future in futures]

    assert core_apply.call_count == 1
    assert any(outcome["status"] == "applied" for outcome in outcomes)
    assert len(state["history"]) == 1
    assert runtime.inspect_review_custody()["state"] == "applied"
    runtime.close()


def test_expired_or_rejected_proposal_cannot_publish():
    for action in ("expire", "reject"):
        clock = FakeClock()
        project = _project()
        runtime, _epoch, review = _runtime_with_pending(project, clock=clock)
        state = _state(project, review)
        if action == "expire":
            clock.advance(15 * 60)
        else:
            assert runtime.resolve_review_proposal(review["proposal_id"], "reject") == "rejected"
        result = _apply(runtime, state, review, project)
        assert result["status"] == ("expired" if action == "expire" else "rejected")
        assert state["history"] == []
        assert state["project"] is project
        runtime.close()
