"""Submit an already constructed prompt request and validate its response.

Status yields, request preparation, WebSocket lifecycle and output capture
remain with their existing owners.
"""

import json
import urllib.error
import urllib.request


def submit_prompt_request(req, server_address):
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read())
            prompt_id = result.get("prompt_id")
    except urllib.error.URLError as e:
        raise Exception(f"Failed to connect to ComfyUI at {server_address}. Is it running? Error: {e}")

    if not prompt_id:
        raise Exception("Failed to get prompt_id from ComfyUI.")
    return prompt_id
