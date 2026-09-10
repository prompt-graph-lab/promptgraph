"""Read-only positional projection of focused prompt tokens onto graph nodes."""


def get_focus_token_node_pairs(project, target_line):
    pairs = []
    node_path = list(getattr(target_line, "node_path", []) or [])
    for index, token in enumerate(getattr(target_line, "tokens", []) or []):
        node_id = node_path[index] if index < len(node_path) else None
        selectable = (
            bool(node_id)
            and node_id in getattr(project, "nodes", {})
            and not token.startswith("<mod:")
            and not token.startswith("</mod:")
        )
        pairs.append({
            "index": index,
            "token": token,
            "node_id": node_id,
            "selectable": selectable,
        })
    return pairs
