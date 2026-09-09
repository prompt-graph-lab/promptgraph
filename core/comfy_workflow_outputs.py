"""Classify workflow output nodes using existing class-name rules."""

def _workflow_output_nodes(workflow_json):
    node_ids = []
    if not isinstance(workflow_json, dict):
        return node_ids
    target_nodes = workflow_json.get("nodes", workflow_json)
    if not isinstance(target_nodes, dict):
        return node_ids
    for node_id, node_data in target_nodes.items():
        if not isinstance(node_data, dict):
            continue
        class_type = str(node_data.get("class_type") or node_data.get("type") or "")
        if class_type in {"SaveImage", "PreviewImage"} or class_type.endswith(".SaveImage") or class_type.endswith(".PreviewImage"):
            node_ids.append(str(node_id))
    return node_ids

def _workflow_save_image_nodes(workflow_json):
    node_ids = []
    if not isinstance(workflow_json, dict):
        return node_ids
    target_nodes = workflow_json.get("nodes", workflow_json)
    if not isinstance(target_nodes, dict):
        return node_ids
    for node_id, node_data in target_nodes.items():
        if not isinstance(node_data, dict):
            continue
        class_type = str(node_data.get("class_type") or node_data.get("type") or "")
        if class_type == "SaveImage" or class_type.endswith(".SaveImage"):
            node_ids.append(str(node_id))
    return node_ids
