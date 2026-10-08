"""Human review-surface tests for the session-local Scene Swap proposal."""

import json
from copy import deepcopy

from streamlit.testing.v1 import AppTest

from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine
from core.agent_facade import preview_scene_module_swap
from ui.agent_scene_module_swap_approval_lifecycle import (
    AgentSceneModuleSwapApprovalCustodian,
)
from ui import agent_scene_module_swap_review_lifecycle as review_lifecycle
from ui.agent_scene_module_swap_review_lifecycle import (
    build_agent_scene_module_swap_review,
)
from ui.agent_scene_module_swap_review_panel import _ack_widget_key


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class _Runtime:
    def __init__(self, custodian, epoch="epoch-a"):
        self.review_custodian = custodian
        self.epoch = epoch

    def synchronize_target(self, project, project_path):
        if project is None:
            self.epoch = "epoch-no-project"
            self.review_custodian.synchronize_target_epoch(self.epoch)
        return self.epoch


def _project(illustration_count=101):
    lines = [PromptLine(
        id="scene-main",
        original_file_name="Scene Main",
        original_index=0,
        current_index=0,
        original_text="Scene Main",
        current_text="Scene Main",
        tokens=[],
        line_type="separator",
    )]
    for index in range(illustration_count):
        text = f"red, blue, illustration {index}"
        lines.append(PromptLine(
            id=f"illustration-{index:03}",
            original_file_name=r"C:\private\source-image.png",
            original_index=index,
            current_index=index + 1,
            original_text=text,
            current_text=text,
            tokens=parse_prompt(text),
            negative_prompt="unchanged negative prompt",
            image_path=r"C:\private\source-image.png",
        ))
    lines.append(PromptLine(
        id="scene-after",
        original_file_name="Scene After",
        original_index=illustration_count + 1,
        current_index=illustration_count + 1,
        original_text="Scene After",
        current_text="Scene After",
        tokens=[],
        line_type="separator",
    ))
    return build_graph(Project(
        prompt_lines=lines,
        module_library={
            "source": {
                "body": "red, blue",
                "core_tokens": ["red", "blue"],
                "reference_assets": [r"C:\private\module-asset.png"],
                "private_metadata": "DO_NOT_RENDER_MODULE_BODY_OR_METADATA",
            },
            "target": {
                "body": "gold, green",
                "reference_assets": [r"C:\private\target-module.png"],
            },
        },
        attribute_groups={},
    ))


def _intent():
    return {
        "scene_id": "scene-main",
        "source_module_name": "source",
        "target_module_name": "target",
        "match_mode": "strict",
    }


def _pending_review(project, clock=None):
    clock = clock or _Clock()
    custodian = AgentSceneModuleSwapApprovalCustodian(clock=clock)
    custodian.synchronize_target_epoch("epoch-a")
    preview = preview_scene_module_swap(project, _intent())
    assert preview["valid"] is True
    intent = {**_intent(), "expected_plan_id": preview["plan_id"]}
    decision = custodian.check_request("request-a", 1, "epoch-a", intent)
    assert decision.status == "new"
    prepared = custodian.prepare(
        "request-a", 1, "epoch-a", intent, decision.revision, preview,
    )
    assert prepared.status == "prepared"
    reply = {
        "bridge_contract_version": "promptgraph.app-agent-request-bridge.v1",
        "request_id": "request-a",
        "status": "completed",
        "result": prepared.result,
    }
    with custodian._lock:
        assert custodian._commit_prepared_locked(
            prepared.token,
            request_id="request-a",
            pairing_generation=1,
            target_epoch="epoch-a",
            reply=reply,
            now=clock(),
        )
    return custodian, _Runtime(custodian), preview


def _visible_text(app):
    collections = (
        app.title,
        app.header,
        app.subheader,
        app.markdown,
        app.text,
        app.caption,
        app.info,
        app.success,
        app.warning,
        app.error,
        app.code,
    )
    return "\n".join(
        str(element.value)
        for collection in collections
        for element in collection
    )


def test_review_projection_freshly_validates_and_includes_every_target_without_paths():
    project = _project(101)
    custodian, runtime, _preview = _pending_review(project)
    before_lines = list(project.prompt_lines)
    before_line_values = [
        (line.current_text, list(line.tokens), line.negative_prompt)
        for line in project.prompt_lines
    ]
    before_modules = deepcopy(project.module_library)

    review = build_agent_scene_module_swap_review(project, runtime, r"C:\private\active.json")

    assert review["state"] == "pending_fresh"
    assert review["scene_label"] == "Scene Main"
    assert review["scene_id"] == "scene-main"
    assert review["target_count"] == 101
    assert len(review["rows"]) == 101
    assert review["rows"][0]["illustration_id"] == "illustration-000"
    assert review["rows"][-1]["illustration_id"] == "illustration-100"
    assert review["rows"][0]["before_positive_prompt"] == "red, blue, illustration 0"
    assert review["rows"][0]["after_positive_prompt"] == "gold, green, illustration 0"
    assert review["rows"][0]["negative_prompt_unchanged"] is True
    serialized = json.dumps(review, ensure_ascii=False)
    for forbidden in (
        r"C:\private",
        "DO_NOT_RENDER_MODULE_BODY_OR_METADATA",
        "source_module_snapshot",
        "main_image_path",
        "reference_assets",
        "unchanged negative prompt",
    ):
        assert forbidden not in serialized
    assert custodian.inspect_for_human_review()["state"] == "pending"
    assert len(project.prompt_lines) == len(before_lines)
    assert all(current is before for current, before in zip(project.prompt_lines, before_lines, strict=True))
    assert [
        (line.current_text, list(line.tokens), line.negative_prompt)
        for line in project.prompt_lines
    ] == before_line_values
    assert project.module_library == before_modules


def test_freshness_mismatch_consumes_confirmation_eligible_proposal_as_stale():
    project = _project(1)
    custodian, runtime, _preview = _pending_review(project)
    project.prompt_lines[1].current_text += ", edited while pending"
    project.prompt_lines[1].tokens = parse_prompt(project.prompt_lines[1].current_text)

    review = build_agent_scene_module_swap_review(project, runtime)

    assert review == {"state": "stale"}
    assert custodian.inspect_for_human_review()["state"] == "stale"


def test_prepared_proposal_has_no_review_content_until_commit():
    project = _project(1)
    clock = _Clock()
    custodian = AgentSceneModuleSwapApprovalCustodian(clock=clock)
    custodian.synchronize_target_epoch("epoch-a")
    preview = preview_scene_module_swap(project, _intent())
    intent = {**_intent(), "expected_plan_id": preview["plan_id"]}
    decision = custodian.check_request("request-a", 1, "epoch-a", intent)
    prepared = custodian.prepare(
        "request-a", 1, "epoch-a", intent, decision.revision, preview,
    )
    assert prepared.status == "prepared"

    review = build_agent_scene_module_swap_review(project, _Runtime(custodian))

    assert review == {"state": "prepared"}
    assert custodian.inspect_for_human_review() == {
        "contract_version": "promptgraph.agent-scene-module-swap-review.v1",
        "state": "prepared",
    }


def test_expired_proposal_is_reported_without_rendering_its_review_content():
    project = _project(1)
    clock = _Clock()
    custodian, runtime, _preview = _pending_review(project, clock=clock)
    clock.now += 15 * 60

    review = build_agent_scene_module_swap_review(project, runtime)

    assert review == {"state": "expired"}
    assert custodian.inspect_for_human_review()["state"] == "expired"


def test_same_pending_proposal_is_rechecked_after_fresh_preview_before_display(monkeypatch):
    project = _project(1)
    custodian, runtime, _preview = _pending_review(project)
    original_preview = review_lifecycle._preview_scene_module_swap_for_host_review

    def preview_then_dismiss(project_value, request):
        result = original_preview(project_value, request)
        proposal_id = custodian.inspect_for_human_review()["proposal_id"]
        custodian.resolve_pending(proposal_id, "dismiss")
        return result

    monkeypatch.setattr(
        review_lifecycle,
        "_preview_scene_module_swap_for_host_review",
        preview_then_dismiss,
    )

    review = build_agent_scene_module_swap_review(project, runtime)

    assert review == {"state": "dismissed"}


def test_project_unavailability_is_a_bounded_state_without_proposal_details():
    project = _project(1)
    custodian, runtime, _preview = _pending_review(project)

    review = build_agent_scene_module_swap_review(None, runtime)

    assert review == {"state": "project_unavailable"}
    assert custodian.inspect_for_human_review()["state"] == "stale"


def test_review_panel_paginates_all_targets_stages_ack_only_and_rejects_without_mutation():
    project = _project(101)
    custodian, runtime, preview = _pending_review(project)
    first_prompt = project.prompt_lines[1].current_text
    record = custodian.inspect_for_human_review()
    identity = (record["proposal_id"], record["plan_id"])
    ack_key = _ack_widget_key(identity)
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui.agent_scene_module_swap_review_panel import render_agent_scene_module_swap_review_panel\n"
        "render_agent_scene_module_swap_review_panel(st.session_state['review_project'], st.session_state['review_runtime'], r'C:\\private\\active.json')\n",
        default_timeout=30,
    )
    app.session_state["review_project"] = project
    app.session_state["review_runtime"] = runtime
    app.run(timeout=30)

    assert not app.exception
    assert "Awaiting human review" in _visible_text(app)
    assert "Negative Prompts, images, Candidates, Variants, and generation state remain unchanged" in _visible_text(app)
    assert "C:\\private" not in _visible_text(app)
    assert "DO_NOT_RENDER_MODULE_BODY_OR_METADATA" not in _visible_text(app)
    assert "Apply" not in [button.label for button in app.button]
    assert len(app.expander) == 20

    next_key = f"agent_scene_swap_review_next_{identity[0]}_{identity[1]}"
    for _ in range(5):
        app.button(key=next_key).click().run(timeout=30)
        assert not app.exception
    assert "illustration-100" in {str(element.value) for element in app.code}

    app.checkbox(key=ack_key).check().run(timeout=30)
    assert not app.exception
    assert "Review acknowledgment staged" in _visible_text(app)
    assert project.prompt_lines[1].current_text == first_prompt
    assert "Apply" not in [button.label for button in app.button]

    reject_key = f"agent_scene_swap_review_reject_{identity[0]}_{identity[1]}"
    app.button(key=reject_key).click().run(timeout=30)

    assert not app.exception
    assert custodian.inspect_for_human_review()["state"] == "rejected"
    assert "This proposal was rejected." in _visible_text(app)
    assert project.prompt_lines[1].current_text == first_prompt
    assert ack_key not in app.session_state
    assert "Apply" not in [button.label for button in app.button]


def test_stale_content_clears_a_previously_staged_review_acknowledgment():
    project = _project(1)
    custodian, runtime, _preview = _pending_review(project)
    record = custodian.inspect_for_human_review()
    identity = (record["proposal_id"], record["plan_id"])
    ack_key = _ack_widget_key(identity)
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui.agent_scene_module_swap_review_panel import render_agent_scene_module_swap_review_panel\n"
        "render_agent_scene_module_swap_review_panel(st.session_state['review_project'], st.session_state['review_runtime'])\n",
        default_timeout=30,
    )
    app.session_state["review_project"] = project
    app.session_state["review_runtime"] = runtime
    app.run(timeout=30)
    app.checkbox(key=ack_key).check().run(timeout=30)
    assert app.session_state[ack_key] is True

    project.prompt_lines[1].current_text += ", changed after review"
    project.prompt_lines[1].tokens = parse_prompt(project.prompt_lines[1].current_text)
    app.run(timeout=30)

    assert not app.exception
    assert "This proposal is stale." in _visible_text(app)
    assert ack_key not in app.session_state
    assert "Apply" not in [button.label for button in app.button]
    assert custodian.inspect_for_human_review()["state"] == "stale"


def test_reject_and_dismiss_are_one_shot_terminal_custodian_actions():
    for action, expected in (("reject", "rejected"), ("dismiss", "dismissed")):
        project = _project(1)
        custodian, _runtime, _preview = _pending_review(project)
        proposal_id = custodian.inspect_for_human_review()["proposal_id"]

        assert custodian.resolve_pending(proposal_id, action) == expected
        assert custodian.inspect_for_human_review()["state"] == expected
        assert custodian.resolve_pending(proposal_id, action) == expected


def test_app_has_global_agent_review_navigation_and_services_review_before_workspace_stops():
    from pathlib import Path

    source = Path("app.py").read_text(encoding="utf-8")
    assert source.index("render_agent_review_navigation(_PROJECT_AGENT_SESSION_RUNTIME)") < source.index(
        "if (is_free() and st.session_state.show_tutorial"
    )
    assert source.index("if st.session_state.get(AGENT_REVIEW_ACTIVE_KEY, False):") < source.index(
        "    render_management_workspace_shell(active_management_workspace)"
    )
    assert source.count("render_agent_scene_module_swap_review_panel(") == 3
    assert "and not st.session_state.get(AGENT_REVIEW_ACTIVE_KEY, False)" in source
