"""Read-only Candidate Route preview planning over caller-resolved targets.

The application retains scope/session resolution and runtime asset/candidate
lookups. This planner neither applies routes nor updates Project or UI state.
"""

from core.candidate_inspection import _candidate_path, _candidate_metadata_caption
from core.candidate_record_normalization import _normalize_candidate_path


def build_candidate_route_creation_preview(
    project, scope, target_resolution, *, active_candidates, resolve_asset_path,
    path_exists, duplicate_exists, build_route_label, line_base_label, example_limit=8,
) -> dict:
    """Preserve target order, lookup timing, counts and resolution value identity."""
    target_lines = target_resolution["target_lines"]
    examples = []
    candidate_line_count = 0
    route_count = 0
    add_line_count = 0
    skip_count = 0
    missing_count = 0
    duplicate_count = 0
    no_candidate_count = 0
    reserved_labels = set()
    route_plans = []

    for line in target_lines:
        candidates = list(active_candidates(line))
        route_candidates = []
        if not candidates:
            no_candidate_count += 1
            skip_count += 1
            continue
        for candidate_index, candidate in enumerate(candidates):
            candidate_path = _normalize_candidate_path(_candidate_path(candidate))
            resolved_candidate_path = resolve_asset_path(candidate_path)
            if not candidate_path or not resolved_candidate_path or not path_exists(resolved_candidate_path):
                missing_count += 1
                skip_count += 1
                continue
            if duplicate_exists(project, getattr(line, "id", ""), candidate_path):
                duplicate_count += 1
                skip_count += 1
                continue
            route_candidates.append({
                "candidate_index": candidate_index,
                "candidate_path": candidate_path,
                "candidate_metadata": _candidate_metadata_caption(candidate),
                "candidate": candidate,
            })

        if not route_candidates:
            continue

        candidate_line_count += 1
        route_count += 1
        add_line_count += len(route_candidates)
        route_label = build_route_label(project, line, reserved_labels)
        route_plans.append({"line": line, "route_label": route_label, "candidates": route_candidates})
        if len(examples) < example_limit:
            examples.append({
                "line_id": getattr(line, "id", ""),
                "display_id": line_base_label(line),
                "line_index": getattr(line, "current_index", getattr(line, "original_index", 0)),
                "route_label": route_label,
                "candidate_count": len(route_candidates),
                "candidate_paths": [item["candidate_path"] for item in route_candidates[:4]],
            })

    return {
        "scope": scope,
        "target_line_count": len(target_lines),
        "candidate_line_count": candidate_line_count,
        "route_count": route_count,
        "add_line_count": add_line_count,
        "skip_count": skip_count,
        "missing_count": missing_count,
        "duplicate_count": duplicate_count,
        "no_candidate_count": no_candidate_count,
        "warnings": target_resolution["warnings"],
        "route_resolution": target_resolution.get("route_resolution"),
        "examples": examples,
        "route_plans": route_plans,
    }
