"""Read-only node selection, layout and edge hints for the Graph display.

Rendering, graph construction and session selection stay with their callers.
"""


def get_graph_node_ids_for_line(project, line):
    if not project or not line:
        return set()
    return {
        node_id
        for node_id in getattr(line, "node_path", [])
        if node_id in getattr(project, "nodes", {})
    }


def sort_graph_node_ids_for_display(project, node_ids, focused_line=None):
    focused_order = {}
    if focused_line:
        for index, node_id in enumerate(getattr(focused_line, "node_path", [])):
            if node_id in getattr(project, "nodes", {}) and node_id not in focused_order:
                focused_order[node_id] = index

    def sort_key(node_id):
        node = project.nodes[node_id]
        if node_id in focused_order:
            return (0, focused_order[node_id], node.depth, node.display)
        return (1, node.depth, node.display)

    return sorted(
        [node_id for node_id in node_ids if node_id in getattr(project, "nodes", {})],
        key=sort_key,
    )


def get_wrapped_graph_positions(ordered_node_ids, row_size=6, x_gap=115, y_gap=90):
    positions = {}
    for index, node_id in enumerate(ordered_node_ids):
        row = index // row_size
        col = index % row_size
        row_count = min(row_size, len(ordered_node_ids) - row * row_size)
        x_offset = ((row_count - 1) * x_gap) / 2
        positions[node_id] = {
            "x": int(col * x_gap - x_offset),
            "y": int(row * y_gap),
        }
    return positions


def get_initial_graph_display_node_ids(project):
    if not project:
        return set()
    if getattr(project, "merge_by_word_only", False):
        # In merged-word mode depth is only the first observed token position.
        # Use count-ranked nodes so the meta-level repeated-word graph stays visible.
        node_counts = {
            node_id: getattr(node, "count", 0)
            for node_id, node in getattr(project, "nodes", {}).items()
        }
        return {
            node_id
            for node_id, _count in sorted(node_counts.items(), key=lambda item: item[1], reverse=True)[:80]
        }
    return {nid for nid, node in project.nodes.items() if node.depth <= 2}


def get_branch_visual_hints(project, displayed_node_ids):
    displayed_node_ids = {
        node_id
        for node_id in displayed_node_ids
        if node_id in getattr(project, "nodes", {})
    }
    if not project or not displayed_node_ids:
        return set(), set(), set()

    ranked_counts = sorted(
        (
            getattr(project.nodes[node_id], "count", 0)
            for node_id in displayed_node_ids
        ),
        reverse=True,
    )
    if not ranked_counts:
        return set(), set(), set()

    threshold_index = min(len(ranked_counts) - 1, max(0, len(ranked_counts) // 4))
    spine_threshold = max(2, ranked_counts[threshold_index])
    spine_node_ids = {
        node_id
        for node_id in displayed_node_ids
        if getattr(project.nodes[node_id], "count", 0) >= spine_threshold
        and (
            getattr(project.nodes[node_id], "prev_node_ids", set())
            or getattr(project.nodes[node_id], "next_node_ids", set())
        )
    }

    divergence_origin_node_ids = set()
    weaker_branch_edges = set()
    for node_id in displayed_node_ids:
        parent_node = project.nodes[node_id]
        parent_count = max(1, getattr(parent_node, "count", 0))
        displayed_children = [
            child_id
            for child_id in getattr(parent_node, "next_node_ids", set())
            if child_id in displayed_node_ids and child_id in project.nodes
        ]
        if len(displayed_children) < 2:
            continue

        weaker_children = [
            child_id
            for child_id in displayed_children
            if getattr(project.nodes[child_id], "count", 0) <= parent_count * 0.6
        ]
        if weaker_children:
            divergence_origin_node_ids.add(node_id)
            weaker_branch_edges.update((node_id, child_id) for child_id in weaker_children)

    return divergence_origin_node_ids, spine_node_ids, weaker_branch_edges


def get_cooccurrence_overlay_edges(
    project,
    ordered_display_node_ids,
    min_count=3,
    max_nodes_per_line=14,
    max_edges_per_node=1,
    max_edges=30,
):
    display_order = {
        node_id: index
        for index, node_id in enumerate(ordered_display_node_ids)
        if node_id in getattr(project, "nodes", {})
    }
    displayed_node_ids = set(display_order)
    if not project or len(displayed_node_ids) < 2:
        return []

    syntax_edges = set(getattr(project, "edges", []))
    pair_counts = {}
    for line in getattr(project, "prompt_lines", []):
        if getattr(line, "deleted", False):
            continue
        line_node_ids = []
        seen_in_line = set()
        for node_id in getattr(line, "node_path", []):
            if node_id in displayed_node_ids and node_id not in seen_in_line:
                seen_in_line.add(node_id)
                line_node_ids.append(node_id)
        if len(line_node_ids) < 2:
            continue
        line_node_ids = sorted(line_node_ids, key=lambda node_id: display_order[node_id])[:max_nodes_per_line]
        for index, source in enumerate(line_node_ids):
            for target in line_node_ids[index + 1:]:
                if (source, target) in syntax_edges or (target, source) in syntax_edges:
                    continue
                pair = tuple(sorted((source, target), key=lambda node_id: display_order[node_id]))
                pair_counts[pair] = pair_counts.get(pair, 0) + 1

    ranked_pairs = sorted(
        (
            (source, target, count)
            for (source, target), count in pair_counts.items()
            if count >= min_count
        ),
        key=lambda item: (-item[2], display_order[item[0]], display_order[item[1]]),
    )
    overlay_edges = []
    per_node_counts = {}
    for source, target, count in ranked_pairs:
        if per_node_counts.get(source, 0) >= max_edges_per_node:
            continue
        if per_node_counts.get(target, 0) >= max_edges_per_node:
            continue
        overlay_edges.append((source, target, count))
        per_node_counts[source] = per_node_counts.get(source, 0) + 1
        per_node_counts[target] = per_node_counts.get(target, 0) + 1
        if len(overlay_edges) >= max_edges:
            break
    return overlay_edges
