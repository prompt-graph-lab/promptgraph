import json
from copy import deepcopy


EDITABLE_FIELD_NAMES = (
    "text",
    "ckpt_name",
    "lora_name",
    "strength_model",
    "strength_clip",
    "seed",
    "noise_seed",
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "denoise",
    "vae_name",
    "filename_prefix",
)
LORA_LOADER_FIELDS = ("lora_name", "strength_model", "strength_clip")


def parse_workflow_json(raw_text: str):
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("Workflow JSON is empty.")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}.") from exc


def _api_nodes(data):
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("prompt"), dict):
        return data["prompt"]
    if isinstance(data.get("nodes"), dict):
        return data["nodes"]
    return data


def _looks_like_api_nodes(nodes) -> bool:
    if not isinstance(nodes, dict) or not nodes:
        return False
    return any(
        isinstance(node, dict)
        and ("class_type" in node or "inputs" in node)
        and isinstance(node.get("inputs", {}), dict)
        for node in nodes.values()
    )


def detect_workflow_shape(data) -> str:
    if _looks_like_api_nodes(_api_nodes(data)):
        return "api"
    if isinstance(data, dict) and isinstance(data.get("nodes"), list):
        return "ui"
    return "unknown"


def _link_node_id(value):
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, dict) and value.get("node_id") is not None:
        return str(value.get("node_id"))
    return None


def _infer_prompt_roles_from_api_nodes(nodes) -> dict[str, str]:
    roles = {}
    if not isinstance(nodes, dict):
        return roles
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        if "ksampler" not in class_type.lower():
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        positive_id = _link_node_id(inputs.get("positive"))
        negative_id = _link_node_id(inputs.get("negative"))
        if positive_id:
            roles[positive_id] = "Positive prompt candidate"
        if negative_id:
            roles[negative_id] = "Negative prompt candidate"
    return roles


def _is_text_encode_like(class_type: str) -> bool:
    lowered = str(class_type or "").lower()
    return "cliptextencode" in lowered or ("textencode" in lowered and "text" in lowered)


def _is_lora_loader_like(class_type: str) -> bool:
    lowered = str(class_type or "").lower()
    return "loraloader" in lowered or ("lora" in lowered and "loader" in lowered)


def _extract_api_nodes(data) -> list[dict]:
    nodes = _api_nodes(data)
    prompt_roles = _infer_prompt_roles_from_api_nodes(nodes)
    extracted = []
    for node_id, node in sorted(nodes.items(), key=lambda item: str(item[0])):
        if not isinstance(node, dict):
            continue
        node_copy = deepcopy(node)
        extracted.append({
            "id": str(node_id),
            "class_type": str(node.get("class_type") or node.get("type") or ""),
            "inputs": dict(node.get("inputs", {})) if isinstance(node.get("inputs"), dict) else {},
            "shape": "api",
            "prompt_role": prompt_roles.get(str(node_id), ""),
            "raw": node_copy,
        })
    return extracted


def get_text_encode_candidates(data) -> list[dict]:
    if detect_workflow_shape(data) != "api":
        return []

    candidates = []
    for node in extract_workflow_nodes(data):
        role = infer_node_role(node)
        inputs = node.get("inputs", {})
        class_type = node.get("class_type", "")
        if "text" not in inputs:
            continue
        candidates.append({
            "node_id": node["id"],
            "class_type": class_type,
            "role": role,
            "has_text_input": "text" in inputs,
            "text_preview": str(inputs.get("text", ""))[:120] if isinstance(inputs.get("text"), str) else "",
        })
    return candidates


def get_lora_loader_candidates(data) -> list[dict]:
    if detect_workflow_shape(data) != "api":
        return []

    candidates = []
    for node in extract_workflow_nodes(data):
        class_type = node.get("class_type", "")
        if not _is_lora_loader_like(class_type):
            continue
        inputs = node.get("inputs", {})
        inputs = inputs if isinstance(inputs, dict) else {}
        missing_fields = [field for field in LORA_LOADER_FIELDS if field not in inputs]
        candidates.append({
            "node_id": node["id"],
            "class_type": class_type,
            "lora_name": inputs.get("lora_name", ""),
            "strength_model": inputs.get("strength_model", ""),
            "strength_clip": inputs.get("strength_clip", ""),
            "missing_fields": missing_fields,
            "can_inject": not missing_fields,
        })
    return candidates


def _api_node_map(data):
    copied = deepcopy(data)
    nodes = _api_nodes(copied)
    if not isinstance(nodes, dict):
        return copied, None
    return copied, nodes


def _validate_text_injection_target(nodes: dict, node_id: str):
    clean_node_id = str(node_id)
    if clean_node_id not in nodes:
        raise ValueError(f"Node {clean_node_id} was not found in the workflow.")

    node = nodes[clean_node_id]
    if not isinstance(node, dict):
        raise ValueError(f"Node {clean_node_id} is not a valid workflow node.")

    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(f"Node {clean_node_id} does not have editable inputs.")

    if "text" not in inputs:
        raise ValueError(f"Node {clean_node_id} does not have an inputs['text'] field.")
    return inputs


def _parse_strength(value, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid number.") from exc


def _validate_lora_injection_target(nodes: dict, node_id: str):
    clean_node_id = str(node_id)
    if clean_node_id not in nodes:
        raise ValueError(f"Node {clean_node_id} was not found in the workflow.")

    node = nodes[clean_node_id]
    if not isinstance(node, dict):
        raise ValueError(f"Node {clean_node_id} is not a valid workflow node.")

    class_type = str(node.get("class_type") or node.get("type") or "")
    if not _is_lora_loader_like(class_type):
        raise ValueError(f"Node {clean_node_id} is not a LoraLoader-like node.")

    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(f"Node {clean_node_id} does not have editable inputs.")

    missing_fields = [field for field in LORA_LOADER_FIELDS if field not in inputs]
    if missing_fields:
        raise ValueError(f"Node {clean_node_id} is missing required LoRA fields: {', '.join(missing_fields)}.")
    return inputs


def inject_lora_into_api_workflow(data, node_id, lora_name: str, strength_model, strength_clip) -> dict:
    if detect_workflow_shape(data) != "api":
        raise ValueError("LoRA loader injection export currently supports API-style workflows only.")
    clean_lora_name = str(lora_name or "").strip()
    if not clean_lora_name:
        raise ValueError("LoRA name is required.")

    copied, nodes = _api_node_map(data)
    if nodes is None:
        raise ValueError("Workflow nodes could not be resolved.")

    parsed_strength_model = _parse_strength(strength_model, "strength_model")
    parsed_strength_clip = _parse_strength(strength_clip, "strength_clip")
    inputs = _validate_lora_injection_target(nodes, str(node_id))
    inputs["lora_name"] = clean_lora_name
    inputs["strength_model"] = parsed_strength_model
    inputs["strength_clip"] = parsed_strength_clip
    return copied


def inject_text_into_api_workflow(data, node_id, text: str) -> dict:
    if detect_workflow_shape(data) != "api":
        raise ValueError("Prompt injection export currently supports API-style workflows only.")

    copied, nodes = _api_node_map(data)
    if nodes is None:
        raise ValueError("Workflow nodes could not be resolved.")

    inputs = _validate_text_injection_target(nodes, str(node_id))
    inputs["text"] = str(text or "")
    return copied


def inject_prompts_into_api_workflow(
    data,
    positive_node_id,
    positive_text: str,
    negative_node_id=None,
    negative_text: str | None = None,
) -> dict:
    injected = inject_text_into_api_workflow(data, positive_node_id, positive_text)
    if negative_node_id and negative_text:
        injected = inject_text_into_api_workflow(injected, negative_node_id, negative_text)
    return injected


def workflow_to_json_text(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _extract_ui_nodes(data) -> list[dict]:
    extracted = []
    for index, node in enumerate(data.get("nodes", [])):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", index)
        class_type = node.get("type") or node.get("class_type") or ""
        extracted.append({
            "id": str(node_id),
            "class_type": str(class_type),
            "inputs": {},
            "shape": "ui",
            "widgets_values": deepcopy(node.get("widgets_values", [])),
            "raw": deepcopy(node),
        })
    return extracted


def extract_workflow_nodes(data) -> list[dict]:
    shape = detect_workflow_shape(data)
    if shape == "api":
        return _extract_api_nodes(data)
    if shape == "ui":
        return _extract_ui_nodes(data)
    return []


def infer_node_role(node: dict) -> str:
    class_type = str(node.get("class_type") or "")
    lowered = class_type.lower()
    if node.get("prompt_role"):
        return node["prompt_role"]
    if "cliptextencode" in lowered or ("textencode" in lowered and "text" in lowered):
        return "Text encode candidate"
    if "checkpointloadersimple" in lowered or ("checkpoint" in lowered and "loader" in lowered):
        return "Checkpoint candidate"
    if "loraloader" in lowered or ("lora" in lowered and "loader" in lowered):
        return "LoRA candidate"
    if "ksampler" in lowered or "sampler" in lowered:
        return "Sampler candidate"
    if "vaeloader" in lowered or "vae" in lowered:
        return "VAE candidate"
    if "saveimage" in lowered or ("save" in lowered and "image" in lowered):
        return "Save image candidate"
    if not class_type:
        return "Unknown"
    return "Unknown"


def summarize_editable_fields(node: dict) -> dict:
    inputs = node.get("inputs", {})
    fields = {}
    if isinstance(inputs, dict):
        for key in EDITABLE_FIELD_NAMES:
            if key in inputs:
                fields[key] = inputs[key]

    widgets_values = node.get("widgets_values")
    if widgets_values:
        fields["widgets_values"] = widgets_values
    return fields


def summarize_workflow_nodes(data) -> list[dict]:
    rows = []
    for node in extract_workflow_nodes(data):
        fields = summarize_editable_fields(node)
        rows.append({
            "node_id": node["id"],
            "class_type": node["class_type"],
            "role": infer_node_role(node),
            "editable_fields": fields,
        })
    return rows
