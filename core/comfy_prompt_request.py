"""Build a ComfyUI prompt request without submitting it.

Accepts an already prepared API workflow and endpoint. Seed mutation is
intentional and preserves the generation helper's existing cache-bypass policy.
No workflow selection, prompt expansion, UI, output capture or persistence.
"""

import json
import random
import urllib.request
import uuid
from dataclasses import dataclass, field
import hashlib
from urllib.parse import urlsplit

from core.generation_executable_manifest import (
    FinalizedManifest, FinalizedRequest, MAX_WORKFLOW_BYTES, MAX_AGGREGATE_BYTES, encode, fingerprint,
)
from core.comfy_workflow_outputs import _workflow_output_nodes


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


@dataclass(frozen=True)
class FrozenPromptRequest:
    """Private offline HTTP material; not a submission or mutable workflow."""
    request_id: str
    request_index: int
    workflow_identity: str
    client_id: str
    prompt_url: str = field(repr=False)
    body_json: bytes = field(repr=False)
    output_nodes: tuple  # (node identity, expected remote bucket)


def prepare_frozen_prompt_request(manifest, request, *, client_id):
    """Prepare exactly one reviewed request without the legacy seed randomizer.

    The private executor supplies the accepted manifest's exact request object
    and correlated client UUID. Endpoint comes solely from frozen host options;
    no caller workflow, destination or output-directory argument is accepted.
    This function performs no HTTP, workflow injection, expansion or file I/O.
    """
    if (type(manifest) is not FinalizedManifest or type(manifest.requests) is not tuple
            or type(request) is not FinalizedRequest or type(request.request_index) is not int
            or not 0 <= request.request_index < len(manifest.requests)
            or manifest.requests[request.request_index] is not request
            or type(request.workflow_json) is not bytes
            or not 0 < len(request.workflow_json) <= MAX_WORKFLOW_BYTES
            or type(manifest.host_config_json) is not bytes
            or not 0 < len(manifest.host_config_json) <= MAX_AGGREGATE_BYTES
            or hashlib.sha256(request.workflow_json).hexdigest() != request.workflow_identity):
        raise ValueError("invalid_frozen_request")
    if type(client_id) is not str or str(uuid.UUID(client_id)) != client_id:
        raise ValueError("invalid_client_correlation")
    # Recompute the finalizer's content identity, not a workflow plan. This also
    # binds frozen destination, physical order, request identity and seed policy.
    if not 1 <= len(manifest.requests) <= 100:
        raise ValueError("invalid_frozen_manifest")
    size, ids, rows = len(manifest.host_config_json), set(), []
    for index, item in enumerate(manifest.requests):
        if (type(item) is not FinalizedRequest or item.request_index != index
                or type(item.request_id) is not str or not 0 < len(item.request_id) <= 160
                or item.request_id in ids or type(item.workflow_json) is not bytes
                or not 0 < len(item.workflow_json) <= MAX_WORKFLOW_BYTES
                or type(item.seed_provenance_json) is not bytes
                or not 0 < len(item.seed_provenance_json) <= MAX_AGGREGATE_BYTES
                or hashlib.sha256(item.workflow_json).hexdigest() != item.workflow_identity):
            raise ValueError("invalid_frozen_manifest")
        ids.add(item.request_id)
        size += len(item.workflow_json) + len(item.seed_provenance_json)
        if size > MAX_AGGREGATE_BYTES:
            raise ValueError("frozen_payload_limit")
        rows.append({"request_id": item.request_id, "illustration_id": item.illustration_id,
                     "request_index": item.request_index, "run_index": item.run_index,
                     "workflow_identity": item.workflow_identity,
                     "seed_provenance": json.loads(item.seed_provenance_json)})
    if fingerprint([manifest.proposal_id, manifest.plan_id, manifest.scene_id, manifest.source_identity,
                    manifest.seed_policy, rows, json.loads(manifest.host_config_json)]) != manifest.manifest_identity:
        raise ValueError("frozen_identity_mismatch")
    workflow = json.loads(request.workflow_json)
    if type(workflow) is not dict or encode(workflow) != request.workflow_json:
        raise ValueError("invalid_frozen_workflow")
    options = json.loads(manifest.host_config_json)
    endpoint = options.get("comfyui_endpoint") if type(options) is dict else None
    if (type(endpoint) is not str or not 0 < len(endpoint) <= 4096
            or any(ord(c) <= 32 or ord(c) == 127 for c in endpoint)):
        raise ValueError("invalid_host_endpoint")
    url = endpoint if "://" in endpoint else "http://" + endpoint
    parts = urlsplit(url)
    if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment or parts.path not in {"", "/"}):
        raise ValueError("invalid_host_endpoint")
    parts.port  # Validate the frozen port without resolving or connecting.
    outputs = _workflow_output_nodes(workflow)
    if not 1 <= len(outputs) <= 100 or any(len(node) > 160 for node in outputs):
        raise ValueError("invalid_output_provenance")
    nodes = []
    for node in outputs:
        kind = workflow[node].get("class_type")
        if kind not in {"SaveImage", "PreviewImage"}:
            raise ValueError("invalid_output_provenance")
        nodes.append((node, "temp" if kind == "PreviewImage" else "output"))
    # Embed the exact reviewed bytes rather than decoding and rewriting seeds.
    body = b'{"prompt":' + request.workflow_json + b',"client_id":' + json.dumps(client_id).encode("ascii") + b'}'
    return FrozenPromptRequest(request.request_id, request.request_index, request.workflow_identity,
                               client_id, url.rstrip("/") + "/prompt", body, tuple(nodes))
