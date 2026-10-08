"""Persistent human review surface for agent-created Scene Module Swap proposals."""

import math

import streamlit as st

from ui.agent_scene_module_swap_review_lifecycle import (
    build_agent_scene_module_swap_review,
)


AGENT_REVIEW_ACTIVE_KEY = "agent_scene_module_swap_review_workspace_active"
_ACK_IDENTITY_KEY = "agent_scene_module_swap_review_ack_identity"
_PAGE_STATE_KEY = "agent_scene_module_swap_review_page_state"
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


def _resolve_proposal(custodian, proposal_id, action, identity):
    """Streamlit callback consumes one exact proposal and its staged checkbox."""

    try:
        custodian.resolve_pending(proposal_id, action)
    except Exception:
        pass
    if st.session_state.get(_ACK_IDENTITY_KEY) == identity:
        _clear_acknowledgment(st.session_state)


def _set_page(identity, page_index):
    st.session_state[_PAGE_STATE_KEY] = {
        "identity": identity,
        "page": max(0, int(page_index)),
    }


def render_agent_review_navigation(runtime):
    """Expose a normal-run navigation entry independent of Gallery controls."""

    state = "unavailable"
    custodian = getattr(runtime, "review_custodian", None)
    try:
        if custodian is not None:
            state = custodian.inspect_for_human_review().get("state", "unavailable")
    except Exception:
        state = "unavailable"
    label = "Agent Review · waiting" if state in {"pending", "prepared"} else "Agent Review"
    if st.sidebar.button(label, key="agent_scene_module_swap_review_navigation", width="stretch"):
        _set_workspace_active(True)
        st.rerun()


def render_agent_scene_module_swap_review_panel(project, runtime, project_path=""):
    """Render the session's fresh proposal for human inspection; never Apply."""

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
        if state in {"stale", "expired", "rejected", "dismissed"}:
            st.warning(message[0])
        elif state in {"computation_failure", "validation_failure", "session_unavailable"}:
            st.error(message[0])
        else:
            st.info(message[0])
        st.caption(message[1])
        return

    identity = (review["proposal_id"], review["plan_id"])
    prior_identity = st.session_state.get(_ACK_IDENTITY_KEY)
    if prior_identity != identity:
        _clear_acknowledgment(st.session_state)
        st.session_state[_ACK_IDENTITY_KEY] = identity

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
    page_count = max(1, math.ceil(len(rows) / _PAGE_SIZE))
    page_state = st.session_state.get(_PAGE_STATE_KEY)
    if type(page_state) is not dict or page_state.get("identity") != identity:
        page_index = 0
    else:
        page_index = min(max(0, page_state.get("page", 0)), page_count - 1)
    start = page_index * _PAGE_SIZE
    stop = min(len(rows), start + _PAGE_SIZE)
    st.subheader(f"Affected Illustrations {start + 1}–{stop} of {len(rows)}")

    for row in rows[start:stop]:
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

    custodian = getattr(runtime, "review_custodian", None)
    if custodian is not None:
        action_cols = st.columns(2)
        with action_cols[0]:
            st.button(
                "Reject proposal",
                key=f"agent_scene_swap_review_reject_{identity[0]}_{identity[1]}",
                on_click=_resolve_proposal,
                args=(custodian, identity[0], "reject", identity),
            )
        with action_cols[1]:
            st.button(
                "Dismiss proposal",
                key=f"agent_scene_swap_review_dismiss_{identity[0]}_{identity[1]}",
                on_click=_resolve_proposal,
                args=(custodian, identity[0], "dismiss", identity),
            )
