"""Inject grouped tokens into the supplied workflow in place."""
import logging
logger = logging.getLogger("core.comfyui")

def inject_prompt_to_workflow(workflow_json, grouped_prompt, mapping, fallback_prompt=None):
    group_map = mapping.get("group_map", {})
    group_order = mapping.get("group_order")
    merge_mode = mapping.get("merge_mode", "merge")

    if group_order:
        ordered_groups = [(g, grouped_prompt[g]) for g in group_order if g in grouped_prompt]
        ordered_groups += [(g, grouped_prompt[g]) for g in grouped_prompt if g not in group_order]
    else:
        ordered_groups = list(grouped_prompt.items())

    dest_texts = {}
    for group, tokens in ordered_groups:
        if group not in group_map:
            logger.info(f"Unmapped group '{group}' -> defaulting to positive")
            dest_key = "positive"
        else:
            dest_key = group_map.get(group, "positive")

        if dest_key not in mapping:
            continue

        if dest_key not in dest_texts:
            dest_texts[dest_key] = []
        dest_texts[dest_key].extend(tokens)

    # Ensure all mapped targets exist even if empty
    for k in mapping.keys():
        if k not in ["group_map", "group_order", "merge_mode"] and k not in dest_texts:
            dest_texts[k] = []

    if fallback_prompt and "positive" in dest_texts and not dest_texts["positive"]:
        dest_texts["positive"] = [fallback_prompt]

    for dest_key, tokens in dest_texts.items():

        dest_config = mapping.get(dest_key)
        if not dest_config:
            continue

        node_id = str(dest_config.get("node_id"))
        input_key = dest_config.get("input_key")

        try:
            # Handle both raw API format and {"nodes": ...} format
            target_nodes = workflow_json.get("nodes", workflow_json) if isinstance(workflow_json, dict) else workflow_json

            if node_id not in target_nodes:
                logger.warning(f"Node {node_id} not found in workflow")
                continue

            inputs = target_nodes[node_id].get("inputs", {})
            if input_key not in inputs:
                logger.warning(f"input_key '{input_key}' not found in node {node_id}")
                continue

            tokens = list(dict.fromkeys(tokens))

            existing = target_nodes[node_id]["inputs"].get(input_key, "")
            if isinstance(existing, str):
                existing = existing.strip().rstrip(",")

            if merge_mode == "overwrite":
                merged = ", ".join(tokens)
            else:
                existing_tokens = [t.strip() for t in existing.split(",") if t.strip()] if isinstance(existing, str) else []
                for t in tokens:
                    if t not in existing_tokens:
                        existing_tokens.append(t)
                merged = ", ".join(existing_tokens)

            target_nodes[node_id]["inputs"][input_key] = merged
        except Exception as e:
            logger.warning(f"Failed to inject prompt to node {node_id}: {e}")
            pass

    return workflow_json
