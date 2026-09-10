"""Read-only visible-neighbor selection for cross-line Candidate browsing."""


def _get_nearby_lines(project, line, radius=1):
    if not project or not line:
        return []
    visible_lines = [
        candidate_line
        for candidate_line in getattr(project, "prompt_lines", [])
        if not getattr(candidate_line, "deleted", False)
    ]
    visible_lines.sort(
        key=lambda candidate_line: (
            getattr(candidate_line, "current_index", None) is None,
            getattr(candidate_line, "current_index", 0) or 0,
        )
    )
    line_ids = [getattr(candidate_line, "id", None) for candidate_line in visible_lines]
    line_id = getattr(line, "id", None)
    if line_id not in line_ids:
        return []

    index = line_ids.index(line_id)
    start = max(0, index - radius)
    end = min(len(visible_lines), index + radius + 1)
    return [
        candidate_line
        for candidate_line in visible_lines[start:end]
        if getattr(candidate_line, "id", None) != line_id
    ]
