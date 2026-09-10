"""Read-only matching of selected graph nodes to a prompt line node path."""

def get_node_match_terms(project, node_id):
    node = getattr(project, "nodes", {}).get(node_id)
    if not node:
        return set()

    from core.parser import extract_node_metadata
    terms = {
        getattr(node, "display", ""),
        getattr(node, "word", ""),
        getattr(node, "original", ""),
    }
    for value in list(terms):
        if value:
            terms.add(extract_node_metadata(value)["base_word"])
    return {term.strip().lower() for term in terms if term and term.strip()}

def remap_selected_nodes_for_line(project, line, selected_node_ids):
    if not project or not line or not selected_node_ids:
        return []

    line_node_ids = [
        node_id
        for node_id in getattr(line, "node_path", [])
        if node_id in getattr(project, "nodes", {})
    ]
    exact_matches = [
        node_id
        for node_id in selected_node_ids
        if node_id in line_node_ids
    ]
    if exact_matches:
        return exact_matches

    selected_terms = set()
    for node_id in selected_node_ids:
        selected_terms.update(get_node_match_terms(project, node_id))
    if not selected_terms:
        return []

    remapped_node_ids = []
    for node_id in line_node_ids:
        if node_id in remapped_node_ids:
            continue
        if get_node_match_terms(project, node_id) & selected_terms:
            remapped_node_ids.append(node_id)

    return remapped_node_ids
