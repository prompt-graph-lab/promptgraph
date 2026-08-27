"""Pure planning for the session-only Graph Edit Illustration Browser.

The planner limits only the records rendered by the existing Graph Edit list.
It never mutates Project data, session state, Gallery state, or operation scope.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


FILTER_ALL = "all"
FILTER_OUTSIDE_SCENES = "outside_scenes"
FILTER_SCENE_PREFIX = "scene:"
PAGE_SIZE_OPTIONS = (12, 24, 48)
DEFAULT_PAGE_SIZE = 12


def _safe_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        return list(value or [])
    except (TypeError, ValueError):
        return []


def _clean_id(value: Any) -> str:
    return str(value or "").strip()


def _is_separator(line: Any) -> bool:
    return getattr(line, "line_type", None) == "separator"


def _scene_label(line: Any) -> str:
    return str(
        getattr(line, "separator_label", "")
        or getattr(line, "current_text", "")
        or getattr(line, "original_file_name", "")
        or getattr(line, "id", "")
        or "Scene"
    )


def normalize_graph_edit_browser_page_size(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_PAGE_SIZE
    return normalized if normalized in PAGE_SIZE_OPTIONS else DEFAULT_PAGE_SIZE


def normalize_graph_edit_browser_page(value: Any, page_count: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError):
        normalized = 1
    return max(1, min(max(1, int(page_count or 1)), normalized))


def _normalized_collapsed_group_keys(
    value: Any,
    valid_group_keys: set[str],
) -> set[str]:
    if isinstance(value, dict):
        raw_values: Iterable[Any] = (
            group_key for group_key, collapsed in value.items() if collapsed
        )
    elif isinstance(value, (set, list, tuple)):
        raw_values = value
    else:
        raw_values = ()
    allowed = set(valid_group_keys) | {FILTER_OUTSIDE_SCENES}
    return {
        clean
        for item in raw_values
        if (clean := _clean_id(item)) in allowed
    }


def _entry_group_filter(entry: dict[str, Any]) -> str:
    return str(entry.get("group_key") or FILTER_OUTSIDE_SCENES)


def _entries_for_filter(entries: list[dict[str, Any]], filter_value: str) -> list[dict[str, Any]]:
    if filter_value == FILTER_ALL:
        return list(entries)
    return [entry for entry in entries if _entry_group_filter(entry) == filter_value]


def build_graph_edit_illustration_browser_plan(
    project: Any,
    illustration_lines: Any,
    *,
    filter_value: Any = FILTER_ALL,
    collapsed_group_keys: Any = None,
    page: Any = 1,
    page_size: Any = DEFAULT_PAGE_SIZE,
    current_illustration_id: Any = "",
) -> dict[str, Any]:
    """Return a non-mutating render plan for the existing Graph Edit list."""

    diagnostics: list[str] = []
    project_lines = _safe_list(getattr(project, "prompt_lines", []))
    browser_lines = _safe_list(illustration_lines)
    line_id_counts = Counter(
        _clean_id(getattr(line, "id", ""))
        for line in project_lines
        if _clean_id(getattr(line, "id", ""))
    )

    scene_by_object: dict[int, dict[str, Any] | None] = {}
    scene_definitions: list[dict[str, Any]] = []
    scene_definition_by_handle: dict[str, dict[str, Any]] = {}
    current_scene: dict[str, Any] | None = None
    project_order_by_object: dict[int, int] = {}

    for project_order, line in enumerate(project_lines):
        project_order_by_object[id(line)] = project_order
        if _is_separator(line):
            handle = _clean_id(getattr(line, "id", ""))
            if getattr(line, "deleted", False):
                current_scene = None
            elif not handle:
                diagnostics.append("Graph Edit Scene separator has no id")
                current_scene = None
            elif line_id_counts.get(handle, 0) != 1:
                diagnostics.append(f"Graph Edit Scene handle is ambiguous: {handle}")
                current_scene = None
            else:
                current_scene = {
                    "handle": handle,
                    "group_key": f"{FILTER_SCENE_PREFIX}{handle}",
                    "filter_value": f"{FILTER_SCENE_PREFIX}{handle}",
                    "label": _scene_label(line),
                    "project_order": project_order,
                    "separator": line,
                }
                scene_definitions.append(current_scene)
                scene_definition_by_handle[handle] = current_scene
        scene_by_object[id(line)] = current_scene

    label_counts = Counter(scene["label"] for scene in scene_definitions)
    label_seen: Counter[str] = Counter()
    for scene in scene_definitions:
        label_seen[scene["label"]] += 1
        occurrence = label_seen[scene["label"]]
        scene["display_label"] = (
            f"{scene['label']} [{occurrence}]"
            if label_counts[scene["label"]] > 1 and occurrence > 1
            else scene["label"]
        )

    all_entries: list[dict[str, Any]] = []
    for browser_order, line in enumerate(browser_lines):
        scene = scene_by_object.get(id(line))
        if id(line) not in project_order_by_object:
            diagnostics.append(
                "Graph Edit Illustration Browser input contains a record outside project.prompt_lines"
            )
        all_entries.append(
            {
                "line": line,
                "line_id": _clean_id(getattr(line, "id", "")),
                "line_type": getattr(line, "line_type", None),
                "browser_order": browser_order,
                "project_order": project_order_by_object.get(id(line), browser_order),
                "scene_handle": scene.get("handle") if scene else "",
                "scene_label": scene.get("display_label") if scene else "Scene外のイラスト",
                "group_key": (
                    scene.get("group_key") if scene else FILTER_OUTSIDE_SCENES
                ),
                "group_filter_value": (
                    scene.get("filter_value") if scene else FILTER_OUTSIDE_SCENES
                ),
            }
        )

    valid_group_keys = {
        scene["group_key"] for scene in scene_definition_by_handle.values()
    }
    normalized_collapsed_group_keys = _normalized_collapsed_group_keys(
        collapsed_group_keys,
        valid_group_keys,
    )
    counts_by_handle = Counter(entry["scene_handle"] for entry in all_entries)
    outside_count = counts_by_handle.get("", 0)

    scene_summaries = [
        {
            **scene,
            "count": counts_by_handle.get(scene["handle"], 0),
            "collapsed": scene["group_key"] in normalized_collapsed_group_keys,
        }
        for scene in scene_definitions
    ]
    outside_summary = {
        "handle": "",
        "group_key": FILTER_OUTSIDE_SCENES,
        "filter_value": FILTER_OUTSIDE_SCENES,
        "label": "Scene外のイラスト",
        "display_label": "Scene外のイラスト",
        "count": outside_count,
        "collapsed": FILTER_OUTSIDE_SCENES in normalized_collapsed_group_keys,
    }

    filter_options = [
        {
            "value": FILTER_ALL,
            "label": f"すべてのイラスト — {len(all_entries)}",
            "count": len(all_entries),
        },
        {
            "value": FILTER_OUTSIDE_SCENES,
            "label": f"Scene外のイラスト — {outside_count}",
            "count": outside_count,
        },
    ] + [
        {
            "value": summary["filter_value"],
            "label": f"{summary['display_label']} — {summary['count']}",
            "count": summary["count"],
            "scene_handle": summary["handle"],
        }
        for summary in scene_summaries
    ]
    valid_filters = {option["value"] for option in filter_options}
    requested_filter = _clean_id(filter_value) or FILTER_ALL
    filter_fallback = requested_filter not in valid_filters
    normalized_filter = FILTER_ALL if filter_fallback else requested_filter
    if filter_fallback:
        diagnostics.append(
            f"Graph Edit Illustration Browser filter is unavailable: {requested_filter}"
        )

    filtered_entries = _entries_for_filter(all_entries, normalized_filter)
    if normalized_filter == FILTER_ALL:
        visible_entries = [
            entry
            for entry in filtered_entries
            if entry["group_key"] not in normalized_collapsed_group_keys
        ]
    else:
        visible_entries = filtered_entries

    normalized_page_size = normalize_graph_edit_browser_page_size(page_size)
    page_count = max(
        1,
        (len(visible_entries) + normalized_page_size - 1) // normalized_page_size,
    )
    normalized_page = normalize_graph_edit_browser_page(
        1 if filter_fallback else page,
        page_count,
    )
    start_index = (normalized_page - 1) * normalized_page_size
    end_index = min(len(visible_entries), start_index + normalized_page_size)
    page_entries = visible_entries[start_index:end_index]

    nonempty_groups = {
        entry["group_key"]
        for entry in all_entries
    }
    all_groups_collapsed = bool(
        normalized_filter == FILTER_ALL
        and all_entries
        and nonempty_groups
        and nonempty_groups.issubset(normalized_collapsed_group_keys)
    )

    current_id = _clean_id(current_illustration_id)
    current_matches = [
        entry
        for entry in all_entries
        if current_id and entry["line_id"] == current_id
    ]
    current_entry = current_matches[0] if len(current_matches) == 1 else None
    current_reveal_available = bool(
        current_entry
        and current_entry["line_type"] not in {"separator", "workbench"}
        and not getattr(current_entry["line"], "deleted", False)
    )
    reveal_filter_value = (
        current_entry["group_filter_value"] if current_reveal_available else ""
    )
    reveal_page = 1
    if current_reveal_available:
        reveal_entries = _entries_for_filter(all_entries, reveal_filter_value)
        reveal_index = next(
            (
                index
                for index, entry in enumerate(reveal_entries)
                if entry["line"] is current_entry["line"]
            ),
            0,
        )
        reveal_page = reveal_index // normalized_page_size + 1

    current_on_page = bool(
        current_entry
        and any(entry["line"] is current_entry["line"] for entry in page_entries)
    )

    return {
        "valid": True,
        "filter_value": normalized_filter,
        "requested_filter_value": requested_filter,
        "filter_fallback": filter_fallback,
        "filter_options": filter_options,
        "scene_summaries": scene_summaries,
        "outside_summary": outside_summary,
        "collapsed_group_keys": sorted(normalized_collapsed_group_keys),
        "all_entries": all_entries,
        "filtered_entries": filtered_entries,
        "visible_entries": visible_entries,
        "page_entries": page_entries,
        "total_count": len(all_entries),
        "filtered_count": len(filtered_entries),
        "visible_count": len(visible_entries),
        "hidden_by_filter_count": len(all_entries) - len(filtered_entries),
        "hidden_by_collapse_count": len(filtered_entries) - len(visible_entries),
        "all_groups_collapsed": all_groups_collapsed,
        "page": normalized_page,
        "page_size": normalized_page_size,
        "page_count": page_count,
        "page_start": 0 if not visible_entries else start_index + 1,
        "page_end": end_index,
        "current_illustration_id": current_id,
        "current_entry": current_entry,
        "current_on_page": current_on_page,
        "current_reveal_available": current_reveal_available,
        "reveal_filter_value": reveal_filter_value,
        "reveal_page": reveal_page,
        "diagnostics": diagnostics,
    }
