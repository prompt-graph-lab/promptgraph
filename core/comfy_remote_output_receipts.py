"""Bounded untrusted ComfyUI history -> private remote descriptors, never files.

Strict standard image-node provenance is intentionally narrower than legacy
Gallery's fallback/dedup extraction. Rejected input is not retained or echoed.
"""
from dataclasses import dataclass, field
import hashlib
import json
import re
import uuid

from core.agent_facade import _json_copy
from core.comfy_image_outputs import _looks_like_comfy_image_record
from core.comfy_prompt_request import FrozenPromptRequest, prepare_frozen_prompt_request

MAX_REMOTE_BYTES = 64 * 1024
MAX_REMOTE_IMAGES = 16
MAX_DESCRIPTOR_NAME = 255
MAX_SUBFOLDER = 1024


def decode_remote_json(raw):
    """Bound bytes before parsing; reject duplicate keys and non-JSON numbers."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_REMOTE_BYTES:
        raise ValueError("remote_metadata_limit")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("ambiguous_remote_metadata")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError("invalid_remote_metadata")
    return _json_copy(json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant),
                      node_limit=2048, text_limit=MAX_REMOTE_BYTES)


def valid_prompt_id(value):
    if type(value) is not str or len(value) != 36:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _safe_component(value):
    if (type(value) is not str or not 0 < len(value) <= MAX_DESCRIPTOR_NAME
            or value in {".", ".."} or value[-1] in {" ", "."}
            or any(ord(c) < 32 or ord(c) == 127 or c in '/\\:<>"|?*%' for c in value)):
        return False
    stem = value.split(".", 1)[0].upper()
    return stem not in {"CON", "PRN", "AUX", "NUL"} and re.fullmatch(r"(?:COM|LPT)[1-9]", stem) is None


@dataclass(frozen=True)
class RemoteImageDescriptor:
    identity: str
    node_id: str
    filename: str = field(repr=False)
    subfolder: str = field(repr=False)
    bucket: str
    image_format: str


@dataclass(frozen=True)
class RemoteOutputReceipt:
    """Remote metadata only: no downloaded/validated/registered/saved claim."""
    job_id: str
    claim_id: str = field(repr=False)
    manifest_identity: str = field(repr=False)
    request_id: str = field(repr=False)
    request_index: int
    workflow_identity: str = field(repr=False)
    prompt_id: str = field(repr=False)
    identity: str
    images: tuple[RemoteImageDescriptor, ...] = field(repr=False)
    encoded_size: int


def validate_remote_outputs(envelope, prepared, prompt_id, history_json):
    """Validate one exact prompt's standard images; all-or-nothing quarantine.

    The envelope is an accepted private correlation carrier, not a Project.
    Paths are remote lookup components only. Future downloads must choose a
    separate contained local destination and validate actual image content.
    """
    if (type(prepared) is not FrozenPromptRequest or not valid_prompt_id(prompt_id)
            or type(history_json) is not bytes or not 0 < len(history_json) <= MAX_REMOTE_BYTES):
        raise ValueError("invalid_remote_metadata")
    if type(prepared.request_index) is not int or not 0 <= prepared.request_index < len(envelope.manifest.requests):
        raise ValueError("request_correlation_mismatch")
    request = envelope.manifest.requests[prepared.request_index]
    if prepared != prepare_frozen_prompt_request(envelope.manifest, request, client_id=prepared.client_id):
        raise ValueError("request_correlation_mismatch")
    history = decode_remote_json(history_json)
    if type(history) is not dict or set(history) != {prompt_id}:
        raise ValueError("prompt_correlation_mismatch")
    record = history[prompt_id]
    if type(record) is not dict or type(record.get("outputs")) is not dict:
        raise ValueError("missing_remote_outputs")
    if "status" in record and (type(record["status"]) is not dict
            or record["status"].get("completed") is not True
            or record["status"].get("status_str") != "success"):
        raise ValueError("unresolved_remote_execution")
    outputs = record["outputs"]
    expected = dict(prepared.output_nodes)
    if not outputs or set(outputs) != set(expected):
        raise ValueError("output_provenance_mismatch")
    images, seen = [], set()
    origin = [envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity,
              prepared.request_id, prepared.request_index, prepared.workflow_identity, prompt_id]
    for node in expected:
        payload = outputs[node]
        if type(payload) is not dict or set(payload) != {"images"} or type(payload["images"]) is not list:
            raise ValueError("invalid_remote_descriptor")
        if not payload["images"] or len(images) + len(payload["images"]) > MAX_REMOTE_IMAGES:
            raise ValueError("remote_count_limit")
        for descriptor in payload["images"]:
            if type(descriptor) is not dict or set(descriptor) != {"filename", "subfolder", "type"}:
                raise ValueError("invalid_remote_descriptor")
            filename, subfolder, bucket = descriptor["filename"], descriptor["subfolder"], descriptor["type"]
            if (not _safe_component(filename) or type(subfolder) is not str or len(subfolder) > MAX_SUBFOLDER
                    or (subfolder and not all(_safe_component(s) for s in subfolder.split("/")))
                    or bucket != expected[node] or not _looks_like_comfy_image_record(descriptor)):
                raise ValueError("unsafe_remote_descriptor")
            key = (filename, subfolder, bucket)
            if key in seen:
                raise ValueError("duplicate_remote_descriptor")
            seen.add(key)
            identity = hashlib.sha256(json.dumps(origin + [node, *key], ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            images.append(RemoteImageDescriptor(identity, node, filename, subfolder, bucket,
                                               filename.rsplit(".", 1)[1].lower()))
    images.sort(key=lambda image: image.identity)
    identity = hashlib.sha256(json.dumps(origin + [r.identity for r in images],
        separators=(",", ":")).encode("utf-8")).hexdigest()
    encoded_size = len(history_json)
    return RemoteOutputReceipt(envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity,
        prepared.request_id, prepared.request_index, prepared.workflow_identity, prompt_id,
        identity, tuple(images), encoded_size)
