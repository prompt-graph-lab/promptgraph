"""Interpret history records without normalizing or copying their contents."""

def _history_outputs(history, prompt_id):
    if not isinstance(history, dict):
        return {}
    prompt_history = history.get(prompt_id)
    if not isinstance(prompt_history, dict) and len(history) == 1:
        prompt_history = next(iter(history.values()))
    if not isinstance(prompt_history, dict):
        return {}
    outputs = prompt_history.get("outputs", {})
    return outputs if isinstance(outputs, dict) else {}

def _history_prompt_record(history, prompt_id):
    if not isinstance(history, dict):
        return {}
    prompt_history = history.get(prompt_id)
    if not isinstance(prompt_history, dict) and len(history) == 1:
        prompt_history = next(iter(history.values()))
    return prompt_history if isinstance(prompt_history, dict) else {}

def _history_prompt_ids_sample(history, limit=8):
    if not isinstance(history, dict):
        return []
    return [str(prompt_id) for prompt_id in list(history.keys())[:limit]]
