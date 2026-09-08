"""Read-only interpretation of one received ComfyUI payload.

Returns (completed, event): ignored payloads return (False, None).
Exceptions propagate to the generator's existing receive-loop handler.
"""

import json


def interpret_progress_message(out, prompt_id):
    if isinstance(out, str):
        message = json.loads(out)
        msg_type = message.get("type")
        data = message.get("data", {})

        if msg_type == "execution_start":
            return False, {"type": "status", "text": "Execution started", "value": 0.05}
        elif msg_type == "executing":
            node = data.get("node")
            if node is None and data.get("prompt_id") == prompt_id:
                # 完了
                return True, None
        elif msg_type == "progress":
            value = data.get("value", 0)
            max_val = data.get("max", 1)
            if max_val > 0:
                progress = value / max_val
                # 10% ~ 90% の範囲にスケーリング
                scaled_progress = 0.1 + (progress * 0.8)
                return False, {"type": "progress", "text": f"Sampling... {value}/{max_val}", "value": scaled_progress}
        elif msg_type == "execution_success" and data.get("prompt_id") == prompt_id:
            return True, None
        elif msg_type == "execution_error":
            error_msg = data.get("exception_message", "Unknown error")
            node_id = data.get("node_id", "")
            node_type = data.get("node_type", "")
            raise Exception(f"ComfyUI Execution Error in node {node_id} ({node_type}): {error_msg}")
    return False, None
