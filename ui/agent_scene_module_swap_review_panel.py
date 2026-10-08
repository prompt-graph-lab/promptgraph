"""Persistent human review surface for agent-created Scene Module Swap proposals."""

import math

import streamlit as st

from ui.agent_scene_module_swap_review_lifecycle import (
    build_agent_scene_module_swap_review,
)


AGENT_REVIEW_ACTIVE_KEY = "agent_scene_module_swap_review_workspace_active"
_ACK_IDENTITY_KEY = "agent_scene_module_swap_review_ack_identity"
_PAGE_STATE_KEY = "agent_scene_module_swap_review_page_state"
_RESULT_KEY = "agent_scene_module_swap_apply_result"
_PAGE_SIZE = 20

_STATE_MESSAGES = {
    "absent": (
        "No agent proposal is waiting for review.",
        "An agent must request human review for a fresh Preview before it appears here.",
    ),
    "prepared": (
        "A proposal is being prepared.",
        "Review content is unavailable until the request and mailbox acknowledgment commit together.",
    ),
    "expired": (
        "This proposal expired.",
        "Ask the agent to create a fresh Preview and submit a new review request.",
    ),
    "stale": (
        "This proposal is stale.",
        "The Project or its prompt/Module content changed. Ask the agent for a fresh Preview and review request.",
    ),
    "rejected": (
        "This proposal was rejected.",
        "The proposal was consumed. A new review request is required for another review.",
    ),
    "dismissed": (
        "This proposal was dismissed.",
        "The proposal was consumed. A new review request is required for another review.",
    ),
    "applying": (
        "This proposal is being applied.",
        "The one-time host approval is claimed. The review controls are unavailable until publication completes.",
    ),
    "applied": (
        "The approved Scene Module Swap was applied.",
        "The updated Project is in memory and autosave completed.",
    ),
    "applied_save_failed": (
        "The approved Scene Module Swap was applied, but autosave did not complete.",
        "Autosave was skipped or failed. Verify the active Project and destination before continuing.",
    ),
    "apply_failed": (
        "The approved Scene Module Swap could not be applied.",
        "The proposal was consumed. No automatic retry is available; request a fresh review.",
    ),
    "computation_failure": (
        "The proposal could not be verified right now.",
        "No review action is available. Retry in a normal app run or dismiss it after verification recovers.",
    ),
    "validation_failure": (
        "The proposal did not pass review validation.",
        "No review content is shown and no confirmation can be staged.",
    ),
    "project_unavailable": (
        "The active Project is unavailable.",
        "Open a Project in this browser session to inspect its pending proposal.",
    ),
    "session_unavailable": (
        "Agent Review is unavailable for this browser session.",
        "The session-owned proposal custodian could not be accessed.",
    ),
}


def _ack_widget_key(identity):
    proposal_id, plan_id = identity
    return f"agent_scene_module_swap_review_ack_{proposal_id}_{plan_id}"


def _clear_acknowledgment(session_state):
    identity = session_state.pop(_ACK_IDENTITY_KEY, None)
    if type(identity) is tuple and len(identity) == 2:
        session_state.pop(_ack_widget_key(identity), None)


def _set_workspace_active(active):
    st.session_state[AGENT_REVIEW_ACTIVE_KEY] = bool(active)


def _resolve_proposal(runtime, proposal_id, action, identity):
    """Streamlit callback consumes one exact proposal and its staged checkbox."""

    try:
        runtime.resolve_review_proposal(proposal_id, action)
    except Exception:
        pass
    if st.session_state.get(_ACK_IDENTITY_KEY) == identity:
        _clear_acknowledgment(st.session_state)


def _approve_and_apply(
    apply_handler,
    runtime,
    project,
    project_path,
    proposal_id,
    plan_id,
    identity,
    acknowledgment_widget_key,
):
    """Run the application-owned host lifecycle from the direct button action."""

    try:
        outcome = apply_handler(
            session_state=st.session_state,
            runtime=runtime,
            project=project,
            project_path=project_path,
            proposal_id=proposal_id,
            plan_id=plan_id,
            acknowledgment_identity_key=_ACK_IDENTITY_KEY,
            acknowledgment_identity=identity,
            acknowledgment_widget_key=acknowledgment_widget_key,
        )
    except Exception:
        outcome = {"status": "computation_failure"}
    if type(outcome) is not dict:
        outcome = {"status": "computation_failure"}
    status = outcome.get("status")
    if status not in {
        "acknowledgment_required", "computation_failure", "applying",
        "applied", "applied_save_failed", "apply_failed", "stale", "expired",
        "rejected", "dismissed", "session_unavailable",
    }:
        status = "computation_failure"
        outcome = {"status": status}
    if status in {"acknowledgment_required", "computation_failure"}:
        st.session_state[_RESULT_KEY] = {"identity": identity, "status": status}
    else:
        st.session_state.pop(_RESULT_KEY, None)
        if st.session_state.get(_ACK_IDENTITY_KEY) == identity:
            _clear_acknowledgment(st.session_state)
        st.session_state.pop(_PAGE_STATE_KEY, None)


def _set_page(identity, page_index):
    st.session_state[_PAGE_STATE_KEY] = {
        "identity": identity,
        "page": max(0, int(page_index)),
    }


def _page_rows(rows, page_index, page_size=_PAGE_SIZE):
    """Return one clamped page and its row offsets without dropping targets."""

    page_count = max(1, math.ceil(len(rows) / page_size))
    page_index = min(max(0, page_index), page_count - 1)
    start = page_index * page_size
    stop = min(len(rows), start + page_size)
    return page_index, page_count, start, stop, rows[start:stop]


def render_agent_review_navigation(runtime):
    """Expose a normal-run navigation entry independent of Gallery controls."""

    state = "unavailable"
    inspector = getattr(runtime, "inspect_review_custody", None)
    try:
        if callable(inspector):
            state = inspector().get("state", "unavailable")
    except Exception:
        state = "unavailable"
    label = "Agent Review · waiting" if state in {"pending", "prepared"} else "Agent Review"
    if st.sidebar.button(label, key="agent_scene_module_swap_review_navigation", width="stretch"):
        _set_workspace_active(True)
        st.rerun()


def render_agent_scene_module_swap_review_panel(
    project,
    runtime,
    project_path="",
    *,
    apply_handler=None,
):
    """Render the session's fresh proposal and optional host-only Apply action."""

    st.title("Agent Review")
    if st.button("Return to Project", key="agent_scene_module_swap_review_return"):
        _set_workspace_active(False)
        st.rerun()

    try:
        # This runs only in the normal full-app path. The lifecycle synchronizes
        # the target before and after fresh validation.
        review = build_agent_scene_module_swap_review(project, runtime, project_path)
    except Exception:
        review = {"state": "computation_failure"}

    state = review.get("state") if type(review) is dict else "computation_failure"
    if state != "pending_fresh":
        _clear_acknowledgment(st.session_state)
        message = _STATE_MESSAGES.get(state, _STATE_MESSAGES["computation_failure"])
        if state in {"applied"}:
            st.success(message[0])
        elif state in {"applied_save_failed", "stale", "expired", "rejected", "dismissed"}:
            st.warning(message[0])
        elif state in {"computation_failure", "validation_failure", "session_unavailable"}:
            st.error(message[0])
        elif state == "apply_failed":
            st.error(message[0])
        else:
            st.info(message[0])
        st.caption(message[1])
        terminal = review.get("result") if type(review) is dict else None
        if type(terminal) is dict and type(terminal.get("scene_label")) is str:
            st.text(f"Scene: {terminal['scene_label']}")
        if (type(terminal) is dict
                and type(terminal.get("source_module_name")) is str
                and type(terminal.get("target_module_name")) is str):
            st.text(
                "Module swap: "
                f"{terminal['source_module_name']} → {terminal['target_module_name']}"
            )
        if type(terminal) is dict and type(terminal.get("applied_count")) is int:
            st.metric("Applied Illustrations", terminal["applied_count"])
            st.caption("Apply: completed")
            save_result = (
                "saved" if terminal.get("save_succeeded") is True
                else "not saved; verify the active Project and destination"
            )
            st.caption(f"Save: {save_result}")
            history = st.session_state.get("history")
            if type(history) is list and history:
                st.caption("Undo: the pre-Apply Project is available in history.")
        if type(terminal) is dict and terminal.get("sync_warning") is True:
            st.warning("One or more local selection/editor views could not be refreshed.")
        return

    identity = (review["proposal_id"], review["plan_id"])
    prior_identity = st.session_state.get(_ACK_IDENTITY_KEY)
    if prior_identity != identity:
        _clear_acknowledgment(st.session_state)
        st.session_state[_ACK_IDENTITY_KEY] = identity
    attempt_feedback = st.session_state.pop(_RESULT_KEY, None)
    if (type(attempt_feedback) is dict
            and attempt_feedback.get("identity") == identity):
        if attempt_feedback.get("status") == "acknowledgment_required":
            st.info("Review acknowledgment is required before applying this proposal.")
        elif attempt_feedback.get("status") == "computation_failure":
            st.warning("The proposal could not be revalidated. It remains pending and may be reviewed again.")

    st.success("Awaiting human review")
    st.text(f"Scene: {review['scene_label']}")
    st.caption("Scene identity")
    st.code(review["scene_id"], language="text")
    st.text(f"Source Module: {review['source_module_name']}")
    st.text(f"Target Module: {review['target_module_name']}")
    st.text(f"Match mode: {review['match_mode']}")
    st.text(f"Proposal expires in approximately {review['expires_in_seconds']} seconds.")

    count_cols = st.columns(5)
    for container, label, key in zip(
        count_cols,
        ("Targets", "Changed", "No-op", "Skipped", "Blocked"),
        ("target_count", "changed_count", "no_op_count", "skipped_count", "blocked_count"),
        strict=True,
    ):
        container.metric(label, review[key])
    st.caption(f"Image/prompt drift-risk rows: {review['drift_count']}")
    st.info(
        "This proposal changes positive prompts only. Negative Prompts, images, "
        "Candidates, Variants, and generation state remain unchanged. Prompt "
        "changes can still drift from the image generated from the prior prompt."
    )

    rows = review["rows"]
    page_state = st.session_state.get(_PAGE_STATE_KEY)
    if type(page_state) is not dict or page_state.get("identity") != identity:
        page_index = 0
    else:
        page_index = page_state.get("page", 0)
    if type(page_index) is not int:
        page_index = 0
    page_index, page_count, start, stop, page_rows = _page_rows(rows, page_index)
    st.subheader(f"Affected Illustrations {start + 1}–{stop} of {len(rows)}")

    for row in page_rows:
        status = {
            "changed": "Changed",
            "no_op": "No change",
            "skipped": "Skipped",
        }.get(row["status"], "Review")
        with st.expander(f"Illustration {row['scene_order'] + 1} · {status}", expanded=False):
            st.caption("Illustration identity")
            st.code(row["illustration_id"], language="text")
            st.caption("Before · positive prompt")
            st.code(row["before_positive_prompt"], language="text")
            st.caption("After · positive prompt")
            st.code(row["after_positive_prompt"], language="text")
            st.caption(f"Token change: {row['swap_kind']}; matching token count: {row['match_count']}")
            st.caption("Added positive-prompt tokens")
            st.code(", ".join(row["token_delta"]["added"]) or "None", language="text")
            st.caption("Removed positive-prompt tokens")
            st.code(", ".join(row["token_delta"]["removed"]) or "None", language="text")
            st.caption(f"Drift risk: {row['drift_risk']}")
            st.caption("Negative Prompt unchanged.")

    page_cols = st.columns(2)
    with page_cols[0]:
        st.button(
            "Previous Illustrations",
            key=f"agent_scene_swap_review_previous_{identity[0]}_{identity[1]}",
            disabled=page_index <= 0,
            on_click=_set_page,
            args=(identity, page_index - 1),
        )
    with page_cols[1]:
        st.button(
            "Next Illustrations",
            key=f"agent_scene_swap_review_next_{identity[0]}_{identity[1]}",
            disabled=page_index >= page_count - 1,
            on_click=_set_page,
            args=(identity, page_index + 1),
        )
    st.caption(f"Page {page_index + 1} of {page_count}. Every target is available for inspection.")

    acknowledgment = st.checkbox(
        "I reviewed this proposal (stages review acknowledgment only; no changes are applied).",
        key=_ack_widget_key(identity),
    )
    if acknowledgment:
        st.info("Review acknowledgment staged for this proposal. The Project has not changed.")

    resolver = getattr(runtime, "resolve_review_proposal", None)
    action_count = 3 if callable(resolver) and callable(apply_handler) else 2
    action_cols = st.columns(action_count)
    action_index = 0
    if callable(apply_handler):
        ack_key = _ack_widget_key(identity)
        with action_cols[action_index]:
            st.button(
                "Approve and Apply",
                key=f"agent_scene_swap_review_apply_{identity[0]}_{identity[1]}",
                type="primary",
                disabled=not acknowledgment,
                on_click=_approve_and_apply,
                args=(
                    apply_handler, runtime, project, project_path,
                    identity[0], identity[1], identity, ack_key,
                ),
            )
        action_index += 1
    if callable(resolver):
        with action_cols[action_index]:
            st.button(
                "Reject proposal",
                key=f"agent_scene_swap_review_reject_{identity[0]}_{identity[1]}",
                on_click=_resolve_proposal,
                args=(runtime, identity[0], "reject", identity),
            )
        action_index += 1
        with action_cols[action_index]:
            st.button(
                "Dismiss proposal",
                key=f"agent_scene_swap_review_dismiss_{identity[0]}_{identity[1]}",
                on_click=_resolve_proposal,
                args=(runtime, identity[0], "dismiss", identity),
            )
