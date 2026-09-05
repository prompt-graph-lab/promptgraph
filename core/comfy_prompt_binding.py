"""Bind current prompts to an already selected ComfyUI API workflow.

Replacement intentionally mutates the supplied workflow and returns the number
of assignments, including repeated assignments to a shared positive/negative
node. Callers own workflow loading/copying, module expansion, settings and
execution. Debug inspection only reads the workflow and line.

This preserves the generation path's upstream traversal and fallback rules;
it is separate from the explicit node-selection tools in core.comfy_workflow.
"""


def _replace_clip_text_prompts(workflow_json, line, image_metadata=None):
    if not isinstance(workflow_json, dict):
        return 0

    nodes = workflow_json.get("nodes", workflow_json)
    if not isinstance(nodes, dict):
        return 0

    current_positive = getattr(line, "current_text", "") or ""
    current_negative = getattr(line, "negative_prompt", "") or ""
    imported_positive = (image_metadata or {}).get("prompt_text") or ""
    imported_negative = (image_metadata or {}).get("negative_prompt") or ""
    replacements = 0
    clip_nodes = []
    prompt_roles = _infer_workflow_prompt_node_ids(nodes)
    resolved_positive = False
    resolved_negative = False

    for positive_node_id in prompt_roles.get("positive", []):
        inputs = nodes[positive_node_id].get("inputs", {})
        if isinstance(inputs, dict) and isinstance(inputs.get("text"), str):
            inputs["text"] = current_positive
            replacements += 1
            resolved_positive = True

    for negative_node_id in prompt_roles.get("negative", []):
        inputs = nodes[negative_node_id].get("inputs", {})
        if isinstance(inputs, dict) and isinstance(inputs.get("text"), str):
            inputs["text"] = current_negative
            replacements += 1
            resolved_negative = True

    if resolved_positive and resolved_negative:
        return replacements

    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        if "CLIPTextEncode" not in str(node.get("class_type", "")):
            continue
        inputs = node.get("inputs", {})
        if isinstance(inputs, dict) and isinstance(inputs.get("text"), str):
            clip_nodes.append(inputs)

    for inputs in clip_nodes:
        text = inputs.get("text", "")
        if not resolved_positive and imported_positive and text == imported_positive:
            inputs["text"] = current_positive
            replacements += 1
            resolved_positive = True
        elif not resolved_negative and imported_negative and text == imported_negative:
            inputs["text"] = current_negative
            replacements += 1
            resolved_negative = True

    if not resolved_positive and replacements == 0 and len(clip_nodes) == 1:
        clip_nodes[0]["text"] = current_positive
        replacements += 1

    return replacements


def _workflow_link_node_id(value):
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, dict) and value.get("node_id") is not None:
        return str(value.get("node_id"))
    return None


def _workflow_node_has_text_input(node) -> bool:
    inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
    return isinstance(inputs, dict) and isinstance(inputs.get("text"), str)


def _collect_upstream_text_node_ids(nodes: dict, start_node_id: str) -> list[str]:
    if not isinstance(nodes, dict) or not start_node_id:
        return []

    text_node_ids = []
    visited = set()
    stack = [str(start_node_id)]
    while stack:
        node_id = stack.pop()
        if node_id in visited:
            continue
        visited.add(node_id)

        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        if _workflow_node_has_text_input(node):
            text_node_ids.append(node_id)

        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for value in inputs.values():
            linked_node_id = _workflow_link_node_id(value)
            if linked_node_id and linked_node_id not in visited:
                stack.append(linked_node_id)
    return text_node_ids


def _infer_workflow_prompt_node_ids(nodes: dict) -> dict:
    prompt_roles = {"positive": [], "negative": []}
    if not isinstance(nodes, dict):
        return prompt_roles

    seen = {"positive": set(), "negative": set()}
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or node.get("type") or "")
        if "ksampler" not in class_type.lower():
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        positive_id = _workflow_link_node_id(inputs.get("positive"))
        negative_id = _workflow_link_node_id(inputs.get("negative"))
        for role, start_node_id in (("positive", positive_id), ("negative", negative_id)):
            if not start_node_id:
                continue
            for text_node_id in _collect_upstream_text_node_ids(nodes, start_node_id):
                if text_node_id in seen[role]:
                    continue
                prompt_roles[role].append(text_node_id)
                seen[role].add(text_node_id)
    return prompt_roles


def _workflow_submitted_prompt_debug(workflow_json, line) -> dict:
    nodes = workflow_json.get("nodes", workflow_json) if isinstance(workflow_json, dict) else {}
    roles = _infer_workflow_prompt_node_ids(nodes)

    def node_texts(role):
        texts = []
        for node_id in roles.get(role, []):
            node = nodes.get(node_id) if isinstance(nodes, dict) else None
            inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
            text = inputs.get("text", "") if isinstance(inputs, dict) else ""
            texts.append(text if isinstance(text, str) else "")
        return texts

    return {
        "expected_positive_prompt": getattr(line, "current_text", "") or "",
        "expected_negative_prompt": getattr(line, "negative_prompt", "") or "",
        "positive_node_ids": roles.get("positive", []),
        "negative_node_ids": roles.get("negative", []),
        "submitted_positive_prompts": node_texts("positive"),
        "submitted_negative_prompts": node_texts("negative"),
    }
