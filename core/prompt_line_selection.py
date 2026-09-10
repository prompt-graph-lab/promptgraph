"""Read-only Illustration ordering, adjacency and operation eligibility."""

WORKBENCH_LINE_TYPE = "workbench"


def get_visible_prompt_lines(project):
    if not project:
        return []
    visible_lines = [
        line
        for line in project.prompt_lines
        if not getattr(line, "deleted", False)
    ]
    return sorted(
        visible_lines,
        key=lambda line: (
            getattr(line, "current_index", None) is None,
            getattr(line, "current_index", 0) or 0,
        )
    )


def get_adjacent_focus_line_ids(project, focused_line_id):
    visible_lines = get_visible_prompt_lines(project)
    visible_line_ids = [line.id for line in visible_lines]
    if focused_line_id not in visible_line_ids:
        return None, None

    index = visible_line_ids.index(focused_line_id)
    previous_line_id = visible_line_ids[index - 1] if index > 0 else None
    next_line_id = visible_line_ids[index + 1] if index < len(visible_line_ids) - 1 else None
    return previous_line_id, next_line_id


def is_route_separator(line) -> bool:
    return getattr(line, "line_type", None) == "separator"


def is_workbench_line(line) -> bool:
    return getattr(line, "line_type", None) == WORKBENCH_LINE_TYPE


def is_gallery_operation_prompt_line(line) -> bool:
    return (
        line is not None
        and not getattr(line, "deleted", False)
        and not is_route_separator(line)
        and not is_workbench_line(line)
    )
