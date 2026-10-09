"""Dedicated normal-run Generation Review surface. Reject/Dismiss only."""
import math
import streamlit as st
from ui.agent_generation_review_lifecycle import build_generation_review, resolve_generation_review

GENERATION_REVIEW_ACTIVE_KEY = "agent_generation_review_workspace_active"
_PAGE_KEY = "agent_generation_review_page"
_FEEDBACK_KEY = "agent_generation_review_feedback"
_MESSAGES = {
    "absent": "No Generation proposal is waiting for review.",
    "prepared": "Generation proposal preparation is pending; review is unavailable until custody commits.",
    "expired": "This Generation proposal expired. Request a fresh Preview and review.",
    "stale": "This Generation proposal is stale. Request a fresh Preview and review.",
    "rejected": "This Generation proposal was rejected.",
    "dismissed": "This Generation proposal was dismissed.",
    "session_unavailable": "Generation Review is unavailable for this session.",
    "project_unavailable": "The active Project is unavailable.",
    "computation_failure": "Verification failed temporarily. No review action is available; retry in a normal app run.",
    "validation_failure": "Generation proposal validation failed. No review action is available.",
}


def _active(value):
    st.session_state[GENERATION_REVIEW_ACTIVE_KEY] = value


def render_generation_review_navigation(runtime, *, on_activate=None):
    try:
        state = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian).get("state")
    except Exception:
        state = "unavailable"
    label = "Generation Review · waiting" if state in {"pending", "prepared"} else "Generation Review"
    if st.sidebar.button(label, key="agent_generation_review_navigation", width="stretch"):
        _active(True)
        if on_activate is not None:
            on_activate()
        st.rerun()


def _set_page(identity, index):
    st.session_state[_PAGE_KEY] = {"identity": identity, "page": max(0, index)}


def _page_rows(rows, index):
    pages = max(1, math.ceil(len(rows) / 20))
    index = min(max(0, index), pages - 1)
    start = index * 20
    return index, pages, start, rows[start:start + 20]


def _resolve(runtime, provider, identity, action):
    status = resolve_generation_review(st.session_state, runtime, provider, *identity, action)
    st.session_state[_FEEDBACK_KEY] = status


def _prompt(label, value):
    st.caption(label)
    st.code(value["text"], language="text")
    if value["truncated"]:
        st.caption(f"Bounded prompt summary; original length {value['length']} characters.")


def render_generation_review_panel(runtime, host_context_provider):
    st.title("Generation Review")
    st.info("No generation has started; review only.")
    st.button("Return to Project", key="agent_generation_review_return", on_click=_active, args=(False,))
    review = build_generation_review(st.session_state, runtime, host_context_provider)
    state = review["state"]
    feedback = st.session_state.pop(_FEEDBACK_KEY, None)
    if feedback in {"computation_failure", "identity_mismatch", "validation_failure"}:
        st.warning("The action could not be verified for the current proposal. No human resolution was recorded.")
    if state != "pending_current":
        st.warning(_MESSAGES.get(state, _MESSAGES["validation_failure"]))
        return
    identity = (review["proposal_id"], review["plan_id"])
    st.success("Pending · current after fresh verification")
    st.text(f"Scene: {review['scene_label']['text']}")
    st.text(f"Scene identity: {review['scene_id']}")
    st.text(f"Proposal: {review['proposal_id']}")
    st.caption(f"Expires in approximately {review['expires_in_seconds']} seconds.")
    columns = st.columns(4)
    for column, label, key in zip(columns, ("Runs", "Targets", "Requests", "Estimated images"),
            ("run_count", "target_count", "request_count", "expected_image_count"), strict=True):
        column.metric(label, review[key])
    st.caption(f"Estimated output-node executions: {review['expected_output_node_count']}; skipped: {review['skipped_count']}; blocked: {review['blocked_count']}.")
    summary = review["workflow_summary"]
    safe_labels = {"host_configured": "Host-configured"}
    st.text(f"Workflow source: {safe_labels[summary['source']]} shared workflow")
    st.text(f"Endpoint policy: {safe_labels[summary['endpoint']]} (address hidden)")
    st.caption("Output configuration remains host-controlled; supported output-node counts are shown for every target below.")
    st.warning("Image and output counts are estimates, not file-count promises. Offline preflight does not guarantee ComfyUI runtime success.")
    st.warning("Active prompt summaries do not certify every workflow prompt binding. Execution seeds are not committed by Preview.")
    st.caption("Warnings: " + ", ".join(review["warnings"]))
    for item in review["skipped"]:
        st.text(f"Skipped {item['illustration_id']}: {item['reason']}")
    if review["skipped_truncated"]:
        st.caption("Skipped detail is bounded; total skipped count is shown above.")
    rows = review["illustrations"]
    page = st.session_state.get(_PAGE_KEY, {})
    index = page.get("page", 0) if type(page) is dict and page.get("identity") == identity else 0
    if type(index) is not int:
        index = 0
    index, pages, start, page_rows = _page_rows(rows, index)
    st.subheader(f"Illustrations {start + 1}–{start + len(page_rows)} of {len(rows)}")
    for offset, row in enumerate(page_rows, start + 1):
        with st.expander(f"Illustration {offset} · {row['illustration_id']}"):
            st.caption(f"Project order: {row['project_order']}; eligible; blocker: {row['blocker'] or 'none'}")
            for label, key in (("Authored positive", "authored_positive_prompt"), ("Authored negative", "authored_negative_prompt"),
                               ("Resolved active positive", "positive_prompt"), ("Resolved active negative", "negative_prompt")):
                _prompt(label, row[key])
            st.caption(f"Workflow nodes: {row['workflow_node_count']}; image-output nodes: {row['image_output_node_count']}; SaveImage-only nodes: {row['save_image_node_count']}.")
            st.caption("Prompt binding: uncertified; " + (", ".join(row["warnings"]) or "no additional warnings"))
    columns = st.columns(2)
    columns[0].button("Previous Illustrations", key=f"agent_generation_previous_{identity[0]}", disabled=index <= 0,
                      on_click=_set_page, args=(identity, index - 1))
    columns[1].button("Next Illustrations", key=f"agent_generation_next_{identity[0]}", disabled=index >= pages - 1,
                      on_click=_set_page, args=(identity, index + 1))
    st.caption(f"Page {index + 1} of {pages}. Every target is available for inspection.")
    columns = st.columns(2)
    for column, label, action in zip(columns, ("Reject proposal", "Dismiss proposal"), ("reject", "dismiss"), strict=True):
        column.button(label, key=f"agent_generation_{action}_{identity[0]}", on_click=_resolve,
                      args=(runtime, host_context_provider, identity, action))
