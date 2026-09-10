"""Pure JSON parsing and executable ComfyUI metadata shape inspection."""

import json


def _load_json_from_text(value: str):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _is_executable_comfy_workflow(value) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        isinstance(node, dict) and isinstance(node.get("inputs"), dict)
        for node in value.values()
    )
