"""Normalize graph component return values into existing node IDs."""


def normalize_agraph_selection(return_value, project):
    if not return_value:
        return []

    raw_items = return_value if isinstance(return_value, list) else [return_value]
    ids = []

    for item in raw_items:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            if "id" in item:
                ids.append(item["id"])
            elif "node" in item:
                ids.append(item["node"])
        else:
            if hasattr(item, "id"):
                ids.append(item.id)

    valid_ids = []
    for nid in ids:
        if nid in project.nodes and nid not in valid_ids:
            valid_ids.append(nid)

    return valid_ids
