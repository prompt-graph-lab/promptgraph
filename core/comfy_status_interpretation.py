"""Interpret Comfy status and failure markers without mutation."""

def _comfy_status_summary(prompt_history):
    status = prompt_history.get("status", {}) if isinstance(prompt_history, dict) else {}
    if isinstance(status, dict):
        status_value = status.get("status_str")
        if status_value is None and "completed" in status:
            status_value = "completed" if status.get("completed") else "not_completed"
        messages = status.get("messages", [])
        return str(status_value or "unknown"), messages if isinstance(messages, list) else []
    if status:
        return str(status), []
    return "unknown", []

def _comfy_status_is_failure(prompt_history):
    status_value, messages = _comfy_status_summary(prompt_history)
    lowered = status_value.lower()
    if lowered in {"error", "failed", "failure"}:
        return True
    for message in messages:
        if not isinstance(message, (list, tuple)) or not message:
            continue
        if str(message[0]).lower() in {"execution_error", "error", "failed"}:
            return True
    return False
