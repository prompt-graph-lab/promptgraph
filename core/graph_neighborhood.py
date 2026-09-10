"""Read-only undirected neighborhood traversal over existing graph edges."""


def get_neighborhood_node_ids(project, selected_node_ids, steps):
    if not project or not selected_node_ids or steps is None:
        return None

    valid_selected = [
        nid for nid in selected_node_ids
        if nid in getattr(project, "nodes", {})
    ]

    if not valid_selected:
        return set()

    forward = {}
    backward = {}

    for source, target in getattr(project, "edges", []):
        forward.setdefault(source, set()).add(target)
        backward.setdefault(target, set()).add(source)

    result = set(valid_selected)
    frontier = set(valid_selected)

    for _ in range(steps):
        next_frontier = set()
        for nid in frontier:
            next_frontier.update(forward.get(nid, set()))
            next_frontier.update(backward.get(nid, set()))
        next_frontier -= result
        result.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break

    return result
