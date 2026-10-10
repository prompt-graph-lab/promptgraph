"""Generation Preview and executable details; human acknowledgment, no Start."""
import math
import streamlit as st
from ui.agent_generation_review_lifecycle import build_generation_review, resolve_generation_review
from ui.agent_generation_executable_confirmation import (
    prepare_session_executable_review, inspect_session_executable_review, confirm_session_execution_details,
)

GENERATION_REVIEW_ACTIVE_KEY = "agent_generation_review_workspace_active"
_PAGE_KEY = "agent_generation_review_page"
_FEEDBACK_KEY = "agent_generation_review_feedback"
_EXEC_PAGE_KEY = "agent_generation_executable_page"
_EXEC_FEEDBACK_KEY = "agent_generation_executable_feedback"
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


def _prepare_executable(runtime, provider, identity, held=None):
    st.session_state[_EXEC_FEEDBACK_KEY] = prepare_session_executable_review(
        st.session_state, runtime, provider, *identity, refresh=held is not None, expected_review=held)


def _confirm_executable(runtime, provider, held):
    st.session_state[_EXEC_FEEDBACK_KEY] = confirm_session_execution_details(st.session_state, runtime, provider, held)


def _set_executable_page(identity, index):
    st.session_state[_EXEC_PAGE_KEY] = {"identity": identity, "page": max(0, index)}


def _render_executable_review(runtime, provider, identity):
    st.subheader("Executable Review")
    st.info("Confirmation does not start generation. ComfyUI execution is not available yet.")
    st.caption("Execution unavailable: no worker or Start capability exists. Offline certification does not guarantee runtime success.")
    feedback = st.session_state.pop(_EXEC_FEEDBACK_KEY, None)
    if feedback not in {None, "certified", "uncertifiable", "confirmed", "already_confirmed", "already_prepared"}:
        st.warning("The executable review action could not be verified. No new human confirmation was recorded.")
    view, held = inspect_session_executable_review(st.session_state, runtime, provider)
    state = view["state"]
    if state == "unprepared":
        st.caption("Prepare executable review to freeze exact workflows and seeds for this proposal.")
        st.button("Prepare executable review", key=f"agent_generation_executable_prepare_{identity[0]}",
                  on_click=_prepare_executable, args=(runtime, provider, identity))
        return
    if held is None:
        st.warning("Stale / unavailable: executable details cannot be confirmed. Retry verification in a normal app run.")
        return
    if view.get("human_confirmed"):
        st.success("Confirmed: human acknowledged the exact displayed execution details.")
    elif state == "certified":
        st.success("Prepared / certified: executable details verified offline.")
    else:
        st.warning("Uncertifiable: blockers prevent confirmation of this complete review.")
    st.text(f"Executable Scene: {view['scene_label']['text']}")
    st.text(f"Executable Scene identity: {view['scene_id']}")
    st.caption(f"Targets: {view['target_count']}; requests: {view['request_count']}; runs: {view['run_count']}; seed policy: {view['seed_policy']}.")
    st.caption("Certification warnings: " + ", ".join(view["warnings"]))
    st.caption("Certification blockers: " + (", ".join(view["blockers"]) or "none"))
    page_identity = (identity, held.revision)
    page = st.session_state.get(_EXEC_PAGE_KEY, {})
    index = page.get("page", 0) if type(page) is dict and page.get("identity") == page_identity else 0
    if type(index) is not int:
        index = 0
    rows = view["requests"]
    index, pages, start, page_rows = _page_rows(rows, index)
    targets = {row["illustration_id"]: row for row in view["targets"]}
    st.subheader(f"Executable requests {start + 1}–{start + len(page_rows)} of {len(rows)}")
    for row in page_rows:
        target = targets[row["illustration_id"]]
        with st.expander(f"Executable request {row['request_index'] + 1} · {row['illustration_id']} · run {row['run_index']}"):
            st.caption(f"Physical Illustration order: {target['project_order']}; request order: {row['request_index'] + 1}; run order: {row['run_index']}.")
            st.caption(f"Target certification: {'certified' if target['certified'] else 'uncertifiable'}; request certification: {'certified' if row['certified'] else 'uncertifiable'}.")
            st.caption("Target blockers: " + (", ".join(target["blockers"]) or "none"))
            st.caption("Request blockers: " + (", ".join(row["blockers"]) or "none"))
            for prompt in row["prompts"]:
                st.caption(f"Verified {prompt['role']} prompt · binding {prompt['binding_index'] + 1} · {prompt['semantics']}")
                st.code(prompt["text"], language="text")
            for seed in row["seeds"]:
                st.text(f"Final {seed['input_key']} · slot {seed['seed_index'] + 1}: {seed['value']} ({seed['policy']})")
            for parameter in row["parameters"]:
                st.text(f"Parameter {parameter['parameter']}: {parameter['value']}")
            st.text("Workflow fingerprint: " + (row["workflow_identity"] or "unavailable"))
    columns = st.columns(2)
    columns[0].button("Previous executable requests", key=f"agent_generation_executable_previous_{identity[0]}_{held.revision}",
        disabled=index <= 0, on_click=_set_executable_page, args=(page_identity, index - 1))
    columns[1].button("Next executable requests", key=f"agent_generation_executable_next_{identity[0]}_{held.revision}",
        disabled=index >= pages - 1, on_click=_set_executable_page, args=(page_identity, index + 1))
    st.caption(f"Executable page {index + 1} of {pages}. Every request and affected target is inspectable.")
    st.button("Confirm reviewed execution details", key=f"agent_generation_executable_confirm_{identity[0]}_{held.revision}",
        disabled=state != "certified" or view.get("human_confirmed", False),
        on_click=_confirm_executable, args=(runtime, provider, held))
    st.button("Refresh executable review", key=f"agent_generation_executable_refresh_{identity[0]}_{held.revision}",
        on_click=_prepare_executable, args=(runtime, provider, identity, held),
        help="Invalidates the old executable review and human confirmation before finalizing new seeds.")


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
    _render_executable_review(runtime, host_context_provider, identity)
    columns = st.columns(2)
    for column, label, action in zip(columns, ("Reject proposal", "Dismiss proposal"), ("reject", "dismiss"), strict=True):
        column.button(label, key=f"agent_generation_{action}_{identity[0]}", on_click=_resolve,
                      args=(runtime, host_context_provider, identity, action))
