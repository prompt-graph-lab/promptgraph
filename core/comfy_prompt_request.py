"""Build a ComfyUI prompt request without submitting it.

Accepts an already prepared API workflow and endpoint. Seed mutation is
intentional and preserves the generation helper's existing cache-bypass policy.
No workflow selection, prompt expansion, UI, output capture or persistence.
"""

import json
import random
import urllib.request
import uuid


def prepare_prompt_request(workflow_json, server_address):
    server_address = server_address.replace("http://", "").replace("https://", "").strip("/")
    client_id = str(uuid.uuid4())
    
    # シード値をランダム化してComfyUIのキャッシュを回避する
    for node_id, node_data in workflow_json.items():
        if isinstance(node_data, dict) and "inputs" in node_data:
            inputs = node_data["inputs"]
            for seed_key in ["seed", "noise_seed"]:
                if seed_key in inputs and isinstance(inputs[seed_key], (int, float)):
                    # 一般的な最大値 (2^64 - 1) までの範囲で乱数を生成
                    inputs[seed_key] = random.randint(0, 0xffffffffffffffff)
                    
    p = {"prompt": workflow_json, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data)
    return server_address, client_id, req
