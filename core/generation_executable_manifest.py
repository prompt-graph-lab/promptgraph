"""Offline finalization for a future executor. No submission or authorization.

Only immutable serialized workflows leave this owner. A future executor must
submit these exact bytes without the legacy submission-time seed randomizer.
Binding certification supports direct standard sampler/CLIPTextEncode links
and host group mappings to those same text slots, with a proven standard
sampler -> VAEDecode -> image output path, not arbitrary custom nodes.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import math
import secrets
import re

from core.agent_facade import _json_copy
from core.comfy_workflow_injection import inject_prompt_to_workflow
from core.comfy_workflow_outputs import _workflow_output_nodes

MAX_WORKFLOW_BYTES = 1_000_000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_AGGREGATE_BYTES = MAX_MANIFEST_BYTES
MAX_REVIEW_TEXT = 4000
MAX_BINDINGS = 100
MAX_SEEDS = 100
MAX_PARAMETERS = 100
MAX_SEED = 2**64 - 1
SAMPLERS = {"KSampler", "KSamplerAdvanced"}
IMAGE_OUTPUTS = {"SaveImage", "PreviewImage"}
PARAMETERS = {"steps", "cfg", "sampler_name", "scheduler", "denoise",
              "width", "height", "batch_size", "start_at_step", "end_at_step",
              "add_noise", "return_with_leftover_noise"}
PARAMETER_NODES = SAMPLERS | {"EmptyLatentImage"}
BLOCKERS = {"prompt_node_missing", "unsupported_prompt_binding", "prompt_input_missing", "prompt_review_limit",
            "unsupported_workflow", "prompt_mapping_missing", "ambiguous_prompt_binding", "prompt_evidence_unavailable",
            "unsupported_prompt_mapping", "prompt_group_unmapped", "prompt_destination_missing", "prompt_source_mismatch",
            "prompt_mapping_incomplete", "prompt_binding_limit", "prompt_text_mismatch", "unsupported_seed_value",
            "seed_review_limit", "seed_binding_missing", "unsupported_generation_parameter", "parameter_review_limit",
            "workflow_limit", "aggregate_limit", "manifest_limit", "image_output_missing",
            "unsupported_output_binding", "unverifiable_output_binding", "ambiguous_output_binding"}


def _blocker(error):
    code = str(error)
    return code if code in BLOCKERS else "workflow_preparation_failed"


def encode(value):
    detached = _json_copy(value, node_limit=2000000, text_limit=MAX_MANIFEST_BYTES)
    result = json.dumps(detached, sort_keys=True, ensure_ascii=False,
                        allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(result) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest_limit")
    return result


def fingerprint(value):
    return hashlib.sha256(encode(value)).hexdigest()


@dataclass(frozen=True)
class FinalizedRequest:
    request_id: str
    illustration_id: str
    request_index: int
    run_index: int
    workflow_json: bytes = field(repr=False)
    workflow_identity: str
    seed_provenance_json: bytes = field(repr=False)


@dataclass(frozen=True)
class FinalizedManifest:
    proposal_id: str
    plan_id: str
    scene_id: str
    requests: tuple[FinalizedRequest, ...]
    host_config_json: bytes = field(repr=False)
    source_identity: str = field(repr=False)
    seed_policy: str
    manifest_identity: str


@dataclass(frozen=True)
class Finalization:
    manifest: FinalizedManifest | None = field(repr=False)
    projection_json: bytes


def _slot(nodes, node_id, key):
    node = nodes.get(node_id)
    if type(node) is not dict:
        raise ValueError("prompt_node_missing")
    if node.get("class_type") != "CLIPTextEncode" or key != "text":
        raise ValueError("unsupported_prompt_binding")
    inputs = node.get("inputs")
    if type(inputs) is not dict or key not in inputs:
        raise ValueError("prompt_input_missing")
    if type(inputs[key]) is not str:
        raise ValueError("unsupported_prompt_binding")
    if len(inputs[key]) > MAX_REVIEW_TEXT:
        raise ValueError("prompt_review_limit")
    return inputs[key]


def _output_link(nodes, node, key):
    """Only port zero links in the supported image/latent path are provable."""
    inputs = node.get("inputs")
    if type(inputs) is not dict:
        raise ValueError("unverifiable_output_binding")
    link = inputs.get(key)
    if (type(link) is not list or len(link) != 2 or type(link[0]) is not str
            or type(link[1]) is not int or link[1] != 0 or link[0] not in nodes):
        raise ValueError("unverifiable_output_binding")
    return link[0]


def _verify_output_paths(nodes, samplers):
    """Prove all recognized image outputs consume certified standard samplers.

    Preview's class-name discovery does not prove custom output semantics.
    Only the exact standard sink/decoder/sampler chain is supported here;
    unknown transforms are never followed by guessing from their inputs.
    """
    outputs = _workflow_output_nodes(nodes)
    if not outputs:
        raise ValueError("image_output_missing")
    reached = set()
    for node_id in outputs:
        output = nodes[node_id]
        if output.get("class_type") not in IMAGE_OUTPUTS:
            raise ValueError("unsupported_output_binding")
        decoder = nodes[_output_link(nodes, output, "images")]
        if decoder.get("class_type") != "VAEDecode":
            raise ValueError("unsupported_output_binding")
        sampler_id = _output_link(nodes, decoder, "samples")
        if nodes[sampler_id].get("class_type") not in SAMPLERS:
            raise ValueError("unsupported_output_binding")
        reached.add(sampler_id)
    # Certifying an unused sampler would attribute its prompts to images that
    # it does not produce. All standard samplers must have a proven output.
    if reached != samplers:
        raise ValueError("ambiguous_output_binding")


def _roles(nodes):
    roles = {"positive": [], "negative": []}
    samplers = set()
    for node_id, node in nodes.items():
        if type(node) is not dict:
            raise ValueError("unsupported_workflow")
        kind = node.get("class_type", "")
        if "ksampler" in kind.lower() and kind not in SAMPLERS:
            raise ValueError("unsupported_prompt_binding")
        if kind not in SAMPLERS:
            continue
        samplers.add(node_id)
        for role in roles:
            link = node.get("inputs", {}).get(role)
            if (type(link) is not list or len(link) != 2 or type(link[0]) is not str
                    or type(link[1]) is not int or link[1] != 0):
                raise ValueError("unsupported_prompt_binding")
            node_id = link[0]
            _slot(nodes, node_id, "text")
            if node_id not in roles[role]:
                roles[role].append(node_id)
    if not all(roles.values()):
        raise ValueError("prompt_mapping_missing")
    if set(roles["positive"]) & set(roles["negative"]):
        raise ValueError("ambiguous_prompt_binding")
    _verify_output_paths(nodes, samplers)
    # Extra encoders/custom text nodes could contain another active prompt.
    # Do not claim complete certification with unreviewed text slots.
    covered = set(roles["positive"] + roles["negative"])
    if any(("text" in node.get("inputs", {}) or "cliptextencode" in node.get("class_type", "").lower())
           and identity not in covered for identity, node in nodes.items()):
        raise ValueError("unsupported_prompt_binding")
    return roles


def verify_prompt_bindings(workflow, context, settings):
    """Verify final slots against independently retained host preparation inputs.

    Group injection may skip invalid entries, so validate every destination and
    group first, then use its existing merge/order/dedup owner on a source copy.
    Negative grouped text intentionally follows mapping semantics, including
    empty or merged source text; it is never relabeled as authored negative.
    """
    roles = _roles(workflow)
    if type(context) is not dict or type(context.get("source_workflow")) is not dict:
        raise ValueError("prompt_evidence_unavailable")
    expected = {}
    mapping = settings.get("comfy_mapping")
    if mapping and (type(mapping) is not dict or "group_map" not in mapping):
        raise ValueError("unsupported_prompt_mapping")
    if mapping and "group_map" in mapping:
        grouped = context.get("grouped_prompt")
        if (type(mapping) is not dict or type(mapping.get("group_map")) is not dict
                or type(grouped) is not dict or mapping.get("merge_mode", "merge") not in {"merge", "overwrite"}
                or type(mapping.get("group_order", [])) is not list):
            raise ValueError("unsupported_prompt_mapping")
        if any(type(group) is not str or type(tokens) is not list
               or any(type(token) is not str for token in tokens) for group, tokens in grouped.items()):
            raise ValueError("unsupported_prompt_mapping")
        if any(group not in mapping["group_map"] for group in grouped):
            raise ValueError("prompt_group_unmapped")
        destinations = {k: v for k, v in mapping.items() if k not in {"group_map", "group_order", "merge_mode"}}
        if any(type(dest) is not str or dest not in destinations for dest in mapping["group_map"].values()):
            raise ValueError("prompt_destination_missing")
        source = deepcopy(context["source_workflow"])
        if _roles(source) != roles:
            raise ValueError("prompt_source_mismatch")
        mapped = set()
        for dest, config in destinations.items():
            if type(config) is not dict or set(config) != {"node_id", "input_key"}:
                raise ValueError("unsupported_prompt_mapping")
            node_id, key = str(config["node_id"]), config["input_key"]
            _slot(source, node_id, key)
            if node_id in mapped:
                raise ValueError("ambiguous_prompt_binding")
            mapped.add(node_id)
        if mapped != set(roles["positive"] + roles["negative"]):
            raise ValueError("prompt_mapping_incomplete")
        injected = inject_prompt_to_workflow(source, grouped, mapping, fallback_prompt=context.get("positive_prompt"))
        expected = {node_id: _slot(injected, node_id, "text") for node_id in mapped}
    else:
        for role in roles:
            text = context.get(role + "_prompt")
            if type(text) is not str or len(text) > MAX_REVIEW_TEXT:
                raise ValueError("prompt_review_limit")
            for node_id in roles[role]:
                expected[node_id] = text
    if sum(map(len, roles.values())) > MAX_BINDINGS:
        raise ValueError("prompt_binding_limit")
    rows = []
    for role, ids in roles.items():
        for index, node_id in enumerate(ids):
            text = _slot(workflow, node_id, "text")
            if text != expected[node_id]:
                raise ValueError("prompt_text_mismatch")
            # Ordinals are safe presentation IDs; raw host node IDs stay private.
            rows.append({"role": role, "binding_index": index, "text": text,
                         "semantics": "group_mapping" if mapping and "group_map" in mapping else "active_illustration_inputs"})
    return rows


def _seed(value):
    if type(value) is int and 0 <= value <= MAX_SEED:
        return value
    if type(value) is float and math.isfinite(value) and value.is_integer() and 0 <= value <= MAX_SEED:
        return int(value)
    raise ValueError("unsupported_seed_value")


def _finalize_seeds(workflow, policy, random_u64, used):
    provenance, public = [], []
    for node_id, node in workflow.items():
        for key in ("seed", "noise_seed"):
            if key not in node["inputs"]:
                continue
            original = _seed(node["inputs"][key])
            value = original
            if policy == "random_u64":
                value = _seed(random_u64())
                # Finite deterministic collision resolution; no probabilistic
                # retry and no chance of duplicate random-policy manifest seeds.
                while value in used:
                    value = (value + 1) & MAX_SEED
                used.add(value)
            node["inputs"][key] = value
            provenance.append({"node_id": node_id, "input_key": key, "original_value": original,
                               "final_value": value, "policy": policy})
            public.append({"seed_index": len(public), "input_key": key, "value": value, "policy": policy})
            if len(public) > MAX_SEEDS:
                raise ValueError("seed_review_limit")
    if not public:
        raise ValueError("seed_binding_missing")
    return provenance, public


def _parameters(workflow):
    rows = []
    for index, node in enumerate(workflow.values()):
        if node["class_type"] not in PARAMETER_NODES:
            continue
        for key, value in node["inputs"].items():
            if key not in PARAMETERS:
                continue
            if type(value) not in (str, int, float, bool) or (type(value) is str and len(value) > 200):
                raise ValueError("unsupported_generation_parameter")
            if type(value) is str and not re.fullmatch(r"[a-zA-Z0-9_]+", value):
                raise ValueError("unsupported_generation_parameter")
            rows.append({"node_index": index, "parameter": key, "value": value})
            if len(rows) > MAX_PARAMETERS:
                raise ValueError("parameter_review_limit")
    return rows


def finalize_generation_manifest(proposal_id, preview, preflight, *, random_u64=None):
    """Private pure host operation; a digest or return value never proves review."""
    random_u64 = random_u64 or (lambda: secrets.randbits(64))
    requests = preflight["request_plan"]
    targets = preview["illustrations"]
    if (not preview.get("valid") or not 1 <= len(requests) <= 100
            or len(requests) != preview["request_count"]
            or len(targets) != preview["target_count"] or not 1 <= len(targets) <= 100
            or type(preview["run_count"]) is not int or not 1 <= preview["run_count"] <= 5
            or len({row["illustration_id"] for row in targets}) != len(targets)):
        raise ValueError("request_limit")
    expected_order = [(row["illustration_id"], run) for row in targets for run in range(1, preview["run_count"] + 1)]
    if [(r["source_line_id"], r["run_index"]) for r in requests] != expected_order:
        raise ValueError("incomplete_target_coverage")
    if len({r["request_id"] for r in requests}) != len(requests):
        raise ValueError("ambiguous_request_identity")
    options = preflight["generation_options"]
    settings = options.get("settings", {})
    policy = settings.get("agent_generation_seed_policy", "random_u64")
    if policy not in {"preserve_u64", "random_u64"}:
        raise ValueError("unsupported_seed_policy")
    host_config = encode(options)
    source_identity = fingerprint(preflight)
    frozen, review_requests, target_rows, used = [], [], [], set()
    total = len(host_config)
    bindings = {}
    failures = {}
    for row in targets:
        identity = row["illustration_id"]
        try:
            bindings[identity] = verify_prompt_bindings(preflight["workflow_plan"][identity]["workflow_json"],
                                    preflight["binding_contexts"].get(identity), settings)
        except ValueError as exc:
            failures[identity] = _blocker(exc)
    for index, item in enumerate(requests):
        identity = item["source_line_id"]
        request_row = {"request_index": index, "illustration_id": identity, "run_index": item["run_index"],
                       "certified": False, "workflow_identity": None, "prompts": [], "seeds": [],
                       "parameters": [], "blockers": []}
        if identity not in failures:
            try:
                workflow = _json_copy(preflight["workflow_plan"][item["workflow_key"]]["workflow_json"],
                                      node_limit=20000, text_limit=1000000)
                provenance, seeds = _finalize_seeds(workflow, policy, random_u64, used)
                parameters = _parameters(workflow)
                workflow_bytes = encode(workflow)
                if len(workflow_bytes) > MAX_WORKFLOW_BYTES:
                    raise ValueError("workflow_limit")
                provenance_bytes = encode(provenance)
                total += len(workflow_bytes) + len(provenance_bytes)
                if total > MAX_AGGREGATE_BYTES:
                    raise ValueError("aggregate_limit")
                digest = hashlib.sha256(workflow_bytes).hexdigest()
                frozen.append(FinalizedRequest(item["request_id"], identity, index, item["run_index"],
                                               workflow_bytes, digest, provenance_bytes))
                request_row.update(certified=True, workflow_identity=digest, prompts=bindings[identity],
                                   seeds=seeds, parameters=parameters)
            except ValueError as exc:
                failures[identity] = _blocker(exc)
        request_row["blockers"] = [failures[identity]] if identity in failures else []
        review_requests.append(request_row)
    # If any run fails, explicitly mark the whole target uncertifiable. Keep
    # every physical request visible and never deliver a partial manifest.
    for row in review_requests:
        if row["illustration_id"] in failures:
            row["certified"] = False
            row["blockers"] = [failures[row["illustration_id"]]]
        if failures:
            # No partial executable payload is retained. Verified prompt text
            # can still explain the target certification result to the human.
            row.update(workflow_identity=None, seeds=[], parameters=[])
    for row in targets:
        identity = row["illustration_id"]
        target_rows.append({"illustration_id": identity, "project_order": row["project_order"],
                            "certified": identity not in failures,
                            "unsupported_bindings": ([failures[identity]] if identity in failures and
                                                     "prompt" in failures[identity] else []),
                            "blockers": [failures[identity]] if identity in failures else []})
    manifest = None
    if not failures:
        payload = [proposal_id, preview["plan_id"], preview["scene_id"], source_identity, policy,
                   [{"request_id": r.request_id, "illustration_id": r.illustration_id,
                     "request_index": r.request_index, "run_index": r.run_index,
                     "workflow_identity": r.workflow_identity,
                     "seed_provenance": json.loads(r.seed_provenance_json)} for r in frozen],
                   json.loads(host_config)]
        manifest = FinalizedManifest(proposal_id, preview["plan_id"], preview["scene_id"], tuple(frozen),
                                     host_config, source_identity, policy, fingerprint(payload))
    projection = {"state": "certified" if manifest else "uncertifiable", "proposal_id": proposal_id,
                  "plan_id": preview["plan_id"], "scene_id": preview["scene_id"], "scene_label": preview["scene_label"],
                  "target_count": len(targets), "run_count": preview["run_count"], "request_count": len(requests),
                  "targets": target_rows, "requests": review_requests, "seed_policy": policy,
                  "manifest_identity": manifest.manifest_identity if manifest else None,
                  "warnings": ["offline_certification_only", "human_confirmation_required", "execution_unavailable"],
                  "blockers": ["uncertifiable_target"] if failures else [],
                  "execution_available": False, "job_submitted": False}
    return Finalization(manifest, encode(projection))
