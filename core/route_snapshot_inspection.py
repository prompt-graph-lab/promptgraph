"""Read-only snapshot presentation and comparison, including shared preview formatting.

Snapshot creation, mutation, persistence and rendering remain with their callers.
"""


def _short_preview(value: str, limit: int = 120) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _route_snapshot_label(index, snapshot):
    name = snapshot.get("name", "Untitled sequence") if isinstance(snapshot, dict) else "Untitled sequence"
    created_at = snapshot.get("created_at", "") if isinstance(snapshot, dict) else ""
    favorite_prefix = "★ " if isinstance(snapshot, dict) and snapshot.get("favorite") else ""
    return f"{index + 1}. {favorite_prefix}{name} {created_at}".strip()


def _ensure_route_snapshot_metadata(snapshot):
    if not isinstance(snapshot, dict):
        return {}
    metadata = {
        "favorite": bool(snapshot.get("favorite", False)),
        "notes": snapshot.get("notes") if isinstance(snapshot.get("notes"), str) else "",
        "tags": snapshot.get("tags") if isinstance(snapshot.get("tags"), str) else "",
    }
    score = snapshot.get("score")
    if score in ("", None):
        metadata["score"] = None
    elif isinstance(score, (int, float)):
        metadata["score"] = max(0.0, min(10.0, float(score)))
    else:
        try:
            metadata["score"] = max(0.0, min(10.0, float(score)))
        except (TypeError, ValueError):
            metadata["score"] = None
    return metadata


def _route_snapshot_image_path(item):
    if not isinstance(item, dict):
        return ""
    return item.get("selected_candidate_path") or item.get("generated_image_path") or ""


def _route_compare_line_label(item):
    line_index = item.get("line_index") if isinstance(item, dict) else None
    prompt_text = item.get("prompt_text", "") if isinstance(item, dict) else ""
    prompt_preview = _short_preview(prompt_text, 80) if prompt_text else "Untitled illustration"
    if not isinstance(line_index, int):
        return prompt_preview
    return f"Illustration {line_index + 1}: {prompt_preview}"


def _compare_route_snapshots(snapshot_a, snapshot_b):
    items_a = {
        item.get("line_id"): item
        for item in snapshot_a.get("items", []) if isinstance(item, dict) and item.get("line_id")
    } if isinstance(snapshot_a, dict) else {}
    items_b = {
        item.get("line_id"): item
        for item in snapshot_b.get("items", []) if isinstance(item, dict) and item.get("line_id")
    } if isinstance(snapshot_b, dict) else {}

    rows = []
    for line_id in items_a:
        if line_id not in items_b:
            continue
        item_a = items_a[line_id]
        item_b = items_b[line_id]
        path_a = _route_snapshot_image_path(item_a)
        path_b = _route_snapshot_image_path(item_b)
        if path_a == path_b:
            continue
        rows.append({
            "line_id": line_id,
            "label": _route_compare_line_label(item_a),
            "path_a": path_a,
            "path_b": path_b,
        })
    return rows


def _sorted_route_snapshot_items(snapshot):
    if not isinstance(snapshot, dict):
        return []
    indexed_items = [
        (index, item)
        for index, item in enumerate(snapshot.get("items", []) or [])
        if isinstance(item, dict)
    ]
    indexed_items.sort(
        key=lambda indexed_item: (
            not isinstance(indexed_item[1].get("line_index"), int),
            indexed_item[1].get("line_index") if isinstance(indexed_item[1].get("line_index"), int) else indexed_item[0],
            indexed_item[0],
        )
    )
    return [item for _index, item in indexed_items]
