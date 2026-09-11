"""Graph Edit Browser draft protection, navigation callbacks and Project reset.

Rendering, planner reconciliation and completed-page registration stay in app.
The lookup below intentionally retains the app lookup semantics for this owner.
"""

import streamlit as st

from core.graph_edit_illustration_browser import (
    DEFAULT_PAGE_SIZE as GRAPH_EDIT_BROWSER_DEFAULT_PAGE_SIZE,
    FILTER_ALL as GRAPH_EDIT_BROWSER_FILTER_ALL,
    PAGE_SIZE_OPTIONS as GRAPH_EDIT_BROWSER_PAGE_SIZE_OPTIONS,
)

GRAPH_EDIT_BROWSER_FILTER_KEY = "graph_edit_illustration_filter"
GRAPH_EDIT_BROWSER_PAGE_KEY = "graph_edit_illustration_page"
GRAPH_EDIT_BROWSER_PAGE_SIZE_KEY = "graph_edit_illustration_page_size"
GRAPH_EDIT_BROWSER_COLLAPSED_KEY = "graph_edit_collapsed_group_keys"
GRAPH_EDIT_BROWSER_NOTICE_KEY = "graph_edit_illustration_browser_notice"
GRAPH_EDIT_BROWSER_PAGE_LINE_IDS_KEY = "graph_edit_illustration_browser_page_line_ids"
GRAPH_EDIT_BROWSER_FILTER_WIDGET_KEY = "_graph_edit_illustration_filter_widget"
GRAPH_EDIT_BROWSER_PAGE_SIZE_WIDGET_KEY = "_graph_edit_illustration_page_size_widget"
GRAPH_EDIT_BROWSER_PAGE_TOP_WIDGET_KEY = "_graph_edit_illustration_page_top"
GRAPH_EDIT_BROWSER_UNSAVED_WARNING = (
    "このpageに未保存の編集があります。\n\n"
    "各イラストの「Save Changes」で保存するか、変更を破棄してから表示を切り替えてください。"
)


def get_line_by_id(project, line_id):
    if not project or not line_id:
        return None
    return next(
        (line for line in project.prompt_lines if line.id == line_id and not getattr(line, "deleted", False)),
        None
    )


def reset_graph_edit_illustration_browser_state() -> None:
    """Reset session-only Graph Edit Browser state after Project replacement."""

    st.session_state[GRAPH_EDIT_BROWSER_FILTER_KEY] = GRAPH_EDIT_BROWSER_FILTER_ALL
    st.session_state[GRAPH_EDIT_BROWSER_PAGE_KEY] = 1
    st.session_state[GRAPH_EDIT_BROWSER_PAGE_SIZE_KEY] = (
        GRAPH_EDIT_BROWSER_DEFAULT_PAGE_SIZE
    )
    st.session_state[GRAPH_EDIT_BROWSER_COLLAPSED_KEY] = set()
    st.session_state[GRAPH_EDIT_BROWSER_NOTICE_KEY] = ""
    st.session_state[GRAPH_EDIT_BROWSER_PAGE_LINE_IDS_KEY] = []
    st.session_state.pop(GRAPH_EDIT_BROWSER_FILTER_WIDGET_KEY, None)
    st.session_state.pop(GRAPH_EDIT_BROWSER_PAGE_SIZE_WIDGET_KEY, None)
    st.session_state.pop(GRAPH_EDIT_BROWSER_PAGE_TOP_WIDGET_KEY, None)


def get_graph_edit_browser_unsaved_line_ids(project) -> list[str]:
    """Return current-page IDs whose existing editor widgets differ from Project."""

    if not project:
        return []
    page_line_ids = st.session_state.get(
        GRAPH_EDIT_BROWSER_PAGE_LINE_IDS_KEY,
        [],
    )
    if not isinstance(page_line_ids, (list, tuple)):
        return []

    unsaved_line_ids = []
    seen = set()
    for raw_line_id in page_line_ids:
        line_id = str(raw_line_id or "")
        if not line_id or line_id in seen:
            continue
        seen.add(line_id)
        line = get_line_by_id(project, line_id)
        if not line or getattr(line, "deleted", False):
            continue
        stored_text = getattr(line, "current_text", "") or ""
        stored_negative = getattr(line, "negative_prompt", "") or ""
        draft_text = st.session_state.get(f"text_{line_id}", stored_text)
        draft_negative = st.session_state.get(
            f"negative_text_{line_id}",
            stored_negative,
        )
        if draft_text != stored_text or draft_negative != stored_negative:
            unsaved_line_ids.append(line_id)
    return unsaved_line_ids


def block_graph_edit_browser_navigation_if_unsaved(project) -> bool:
    """Block Browser-only navigation while current-page editor drafts exist."""

    if not get_graph_edit_browser_unsaved_line_ids(project):
        return False
    st.session_state[GRAPH_EDIT_BROWSER_NOTICE_KEY] = (
        GRAPH_EDIT_BROWSER_UNSAVED_WARNING
    )
    return True


def discard_graph_edit_browser_current_page_drafts(project) -> list[str]:
    """Restore current-page editor widgets from Project without mutating Project."""

    discarded_line_ids = []
    for line_id in get_graph_edit_browser_unsaved_line_ids(project):
        line = get_line_by_id(project, line_id)
        if not line or getattr(line, "deleted", False):
            continue
        st.session_state[f"text_{line_id}"] = (
            getattr(line, "current_text", "") or ""
        )
        st.session_state[f"negative_text_{line_id}"] = (
            getattr(line, "negative_prompt", "") or ""
        )
        discarded_line_ids.append(line_id)
    st.session_state[GRAPH_EDIT_BROWSER_NOTICE_KEY] = ""
    return discarded_line_ids


def _reset_graph_edit_browser_page() -> None:
    st.session_state[GRAPH_EDIT_BROWSER_PAGE_KEY] = 1
    st.session_state.pop(GRAPH_EDIT_BROWSER_PAGE_TOP_WIDGET_KEY, None)


def _on_graph_edit_browser_filter_changed() -> None:
    if block_graph_edit_browser_navigation_if_unsaved(
        st.session_state.get("project")
    ):
        st.session_state[GRAPH_EDIT_BROWSER_FILTER_WIDGET_KEY] = (
            st.session_state.get(
                GRAPH_EDIT_BROWSER_FILTER_KEY,
                GRAPH_EDIT_BROWSER_FILTER_ALL,
            )
        )
        return
    st.session_state[GRAPH_EDIT_BROWSER_FILTER_KEY] = st.session_state.get(
        GRAPH_EDIT_BROWSER_FILTER_WIDGET_KEY,
        GRAPH_EDIT_BROWSER_FILTER_ALL,
    )
    _reset_graph_edit_browser_page()
    st.session_state[GRAPH_EDIT_BROWSER_NOTICE_KEY] = ""


def _on_graph_edit_browser_page_size_changed() -> None:
    if block_graph_edit_browser_navigation_if_unsaved(
        st.session_state.get("project")
    ):
        st.session_state[GRAPH_EDIT_BROWSER_PAGE_SIZE_WIDGET_KEY] = (
            st.session_state.get(
                GRAPH_EDIT_BROWSER_PAGE_SIZE_KEY,
                GRAPH_EDIT_BROWSER_DEFAULT_PAGE_SIZE,
            )
        )
        return
    page_size = st.session_state.get(
        GRAPH_EDIT_BROWSER_PAGE_SIZE_WIDGET_KEY,
        GRAPH_EDIT_BROWSER_DEFAULT_PAGE_SIZE,
    )
    st.session_state[GRAPH_EDIT_BROWSER_PAGE_SIZE_KEY] = (
        page_size
        if page_size in GRAPH_EDIT_BROWSER_PAGE_SIZE_OPTIONS
        else GRAPH_EDIT_BROWSER_DEFAULT_PAGE_SIZE
    )
    _reset_graph_edit_browser_page()


def _on_graph_edit_browser_page_input_changed(widget_key: str) -> None:
    if block_graph_edit_browser_navigation_if_unsaved(
        st.session_state.get("project")
    ):
        st.session_state[widget_key] = st.session_state.get(
            GRAPH_EDIT_BROWSER_PAGE_KEY,
            1,
        )
        return
    try:
        page = int(st.session_state.get(widget_key, 1))
    except (TypeError, ValueError, OverflowError):
        page = 1
    st.session_state[GRAPH_EDIT_BROWSER_PAGE_KEY] = max(1, page)


def _set_graph_edit_browser_page(page: int, page_count: int) -> bool:
    if block_graph_edit_browser_navigation_if_unsaved(
        st.session_state.get("project")
    ):
        return False
    st.session_state[GRAPH_EDIT_BROWSER_PAGE_KEY] = max(
        1,
        min(max(1, int(page_count or 1)), int(page or 1)),
    )
    st.session_state.pop(GRAPH_EDIT_BROWSER_PAGE_TOP_WIDGET_KEY, None)
    return True


def _set_graph_edit_browser_collapsed_group_keys(group_keys) -> bool:
    """Apply one typed collapse set unless current-page drafts block navigation."""

    if block_graph_edit_browser_navigation_if_unsaved(
        st.session_state.get("project")
    ):
        return False
    st.session_state[GRAPH_EDIT_BROWSER_COLLAPSED_KEY] = {
        str(group_key)
        for group_key in (group_keys or set())
        if str(group_key or "")
    }
    _reset_graph_edit_browser_page()
    return True


def _reveal_graph_edit_browser_current(filter_value: str, page: int) -> None:
    """Apply an explicit reveal before the next widget-rendering pass."""

    if block_graph_edit_browser_navigation_if_unsaved(
        st.session_state.get("project")
    ):
        return
    st.session_state[GRAPH_EDIT_BROWSER_FILTER_KEY] = str(filter_value or "")
    st.session_state[GRAPH_EDIT_BROWSER_PAGE_KEY] = max(1, int(page or 1))
    st.session_state[GRAPH_EDIT_BROWSER_NOTICE_KEY] = (
        "現在のイラストを含むSceneとpageを表示しました。"
    )
    st.session_state.pop(GRAPH_EDIT_BROWSER_FILTER_WIDGET_KEY, None)
    st.session_state.pop(GRAPH_EDIT_BROWSER_PAGE_TOP_WIDGET_KEY, None)
