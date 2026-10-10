"""C2B-1 deterministic offline workflow and complete review characterization."""
import copy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import time
from unittest.mock import patch

import pytest

from core import agent_facade
from core import generation_executable_manifest as owner
from core.comfy_workflow_preparation import _build_line_workflow_from_text
from ui.agent_generation_executable_review import (
    build_executable_generation_review, inspect_executable_generation_review,
)
from ui.agent_generation_start_lifecycle import authorize_generation_start, capture_human_start_action
from test_agent_generation_preview import project, line, safe_capture, app_host
from test_agent_generation_review_custody import setup, send


def workflow():
    return {"p": {"class_type": "CLIPTextEncode", "inputs": {"text": "original positive"}},
            "n": {"class_type": "CLIPTextEncode", "inputs": {"text": "original negative"}},
            "s": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 20, "cfg": 7.0,
                  "sampler_name": "euler", "scheduler": "normal", "positive": ["p", 0], "negative": ["n", 0]}},
            "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": owner.MAX_SEED}},
            "latent": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
            "out": {"class_type": "SaveImage", "inputs": {"filename_prefix": "PRIVATE_PATH"}}}


def host_for(settings=None, change=None):
    settings = settings or {}
    def provider(p, runs):
        source = workflow()
        if change:
            change(source)
        def build(item, index):
            context = {}
            result, warning = _build_line_workflow_from_text(json.dumps(source), item, settings,
                                                            project=p, _binding_context=context)
            return {"workflow_json": result, "warning": warning, "binding_context": context,
                    "resolved_positive_prompt": item.current_text, "resolved_negative_prompt": item.negative_prompt}
        return {"generation_options": {"run_count": runs, "settings": copy.deepcopy(settings),
                    "comfyui_endpoint": "PRIVATE_ENDPOINT", "output_directory": "PRIVATE_OUTPUT",
                    "workflow_file_signature": {"sha256": owner.fingerprint(source)}},
                "request_builder": build, "project_path": "PRIVATE_PROJECT_PATH"}
    return provider


def inputs(runs=3, provider=None, value=None):
    p = value or project()
    preflight = {}
    preview = agent_facade.preview_generation(p, "scene", run_count=runs,
                  host_context_provider=provider or host_for(), _host_preflight=preflight)
    assert preview["valid"]
    return preview, preflight


def finalize(runs=3, provider=None, random_u64=lambda: 0):
    preview, preflight = inputs(runs, provider)
    return owner.finalize_generation_manifest("proposal", preview, preflight, random_u64=random_u64)


def queued(runs=3, provider=None):
    runtime, route, epoch, state, args = setup()
    state["project"].prompt_lines = project().prompt_lines
    provider = provider or host_for()
    binding = [agent_facade.candidate_observation_handles.project_identity(state["project"]),
               runtime._registration.route_id, state["current_project_path"], route._pairing_generation, epoch]
    args["run_count"] = runs
    args["expected_plan_id"] = agent_facade.preview_generation(state["project"], "scene", run_count=runs,
                     host_context_provider=provider, observation_binding=binding)["plan_id"]
    assert send(runtime, route, epoch, state, args, provider=provider) == "completed"
    return runtime, state, provider


def test_multiple_runs_frozen_order_deterministic_fingerprints_and_seed_provenance():
    preview, preflight = inputs()
    before = copy.deepcopy(preflight)
    first = owner.finalize_generation_manifest("proposal", preview, preflight, random_u64=lambda: 0)
    second = owner.finalize_generation_manifest("proposal", preview, preflight, random_u64=lambda: 0)
    assert first == second and preflight == before
    requests = first.manifest.requests
    assert [(r.illustration_id, r.run_index) for r in requests] == [(i, run) for i in ("two", "one") for run in (1, 2, 3)]
    assert [r.request_index for r in requests] == list(range(6))
    seeds = []
    for request in requests:
        payload = json.loads(request.workflow_json)
        assert hashlib.sha256(request.workflow_json).hexdigest() == request.workflow_identity
        seeds += [payload["s"]["inputs"]["seed"], payload["noise"]["inputs"]["noise_seed"]]
        provenance = json.loads(request.seed_provenance_json)
        assert [s["original_value"] for s in provenance] == [0, owner.MAX_SEED]
        assert [s["final_value"] for s in provenance] == seeds[-2:]
        payload["s"]["inputs"]["seed"] = 123
        assert owner.encode(payload) != request.workflow_json
    assert seeds == list(range(12))  # Constant RNG exercises deterministic collision resolution.
    with pytest.raises(FrozenInstanceError):
        requests[0].workflow_json = b"changed"
    preflight["workflow_plan"].clear()
    assert requests[0].workflow_json == second.manifest.requests[0].workflow_json


def test_preserve_zero_and_u64_boundary_and_no_second_randomization():
    finalized = finalize(provider=host_for({"agent_generation_seed_policy": "preserve_u64"}),
                         random_u64=lambda: pytest.fail("fixed policy cannot randomize"))
    assert all(json.loads(r.workflow_json)["s"]["inputs"]["seed"] == 0 for r in finalized.manifest.requests)
    assert all(json.loads(r.workflow_json)["noise"]["inputs"]["noise_seed"] == owner.MAX_SEED
               for r in finalized.manifest.requests)
    assert len({r.workflow_identity for r in finalized.manifest.requests[:3]}) == 1


@pytest.mark.parametrize("seed", [-1, 2**64, True, 1.5, "0", ["noise", 0]])
def test_unsupported_seed_values_block_complete_target(seed):
    result = finalize(provider=host_for(change=lambda w: w["s"]["inputs"].update(seed=seed)))
    view = json.loads(result.projection_json)
    assert result.manifest is None and view["state"] == "uncertifiable"
    assert len(view["requests"]) == 6 and not any(row["certified"] for row in view["targets"])
    assert all(row["blockers"] == ["unsupported_seed_value"] for row in view["requests"])


def test_random_bounds_and_wraparound_are_deterministic():
    result = finalize(random_u64=lambda: owner.MAX_SEED)
    values = [s["value"] for row in json.loads(result.projection_json)["requests"] for s in row["seeds"]]
    assert values == [owner.MAX_SEED] + list(range(11))
    assert finalize(random_u64=lambda: 2**64).manifest is None


def test_binding_verifies_positive_negative_injected_values_not_return_success():
    preview, preflight = inputs(1)
    assert [b["text"] for b in json.loads(owner.finalize_generation_manifest("proposal", preview, preflight,
                               random_u64=lambda: 0).projection_json)["requests"][0]["prompts"]] == ["red", "blur"]
    preflight["workflow_plan"]["one"]["workflow_json"]["n"]["inputs"]["text"] = "silently unchanged"
    result = owner.finalize_generation_manifest("proposal", preview, preflight, random_u64=lambda: 0)
    view = json.loads(result.projection_json)
    assert result.manifest is None
    assert [r["certified"] for r in view["targets"]] == [True, False]
    assert view["requests"][1]["blockers"] == ["prompt_text_mismatch"]
    assert view["request_count"] == 2 and len(view["requests"]) == 2


@pytest.mark.parametrize("change,reason", [
    (lambda w: w.pop("n"), "prompt_node_missing"),
    (lambda w: w["n"]["inputs"].pop("text"), "prompt_input_missing"),
    (lambda w: w["p"].update(class_type="CustomCLIPTextEncode"), "unsupported_prompt_binding"),
    (lambda w: w["s"]["inputs"].update(negative=["p", 0]), "ambiguous_prompt_binding"),
    (lambda w: w["s"]["inputs"].update(positive=["out", 0]), "unsupported_prompt_binding"),
    (lambda w: w["s"].update(class_type="CustomKSampler"), "unsupported_prompt_binding"),
    (lambda w: w.pop("s"), "prompt_mapping_missing"),
])
def test_missing_ambiguous_unsupported_bindings_fail_closed(change, reason):
    result = finalize(provider=host_for(change=change))
    assert result.manifest is None
    assert json.loads(result.projection_json)["requests"][0]["blockers"] == [reason]


@pytest.mark.parametrize("mode,expected", [("overwrite", "first, second"), ("merge", "original positive, first, second")])
def test_grouped_order_dedup_and_negative_semantics_use_existing_owner(mode, expected):
    settings = {"comfy_mapping": {"group_map": {"a": "positive", "b": "positive", "bad": "negative"},
                  "group_order": ["b", "a", "bad"], "merge_mode": mode,
                  "positive": {"node_id": "p", "input_key": "text"},
                  "negative": {"node_id": "n", "input_key": "text"}}}
    with patch("core.comfyui.build_prompt_by_group", return_value={"a": ["second", "first"], "b": ["first"], "bad": ["ugly"]}):
        result = finalize(provider=host_for(settings))
    assert result.manifest
    prompts = json.loads(result.projection_json)["requests"][0]["prompts"]
    assert prompts[0]["text"] == expected
    assert prompts[1]["text"] == ("ugly" if mode == "overwrite" else "original negative, ugly")
    assert all(row["semantics"] == "group_mapping" for row in prompts)


@pytest.mark.parametrize("change,reason", [
    (lambda m: m["group_map"].clear(), "prompt_group_unmapped"),
    (lambda m: m["group_map"].update(a="missing"), "prompt_destination_missing"),
    (lambda m: m["positive"].update(node_id="missing"), "prompt_node_missing"),
    (lambda m: m["positive"].update(input_key="unknown"), "unsupported_prompt_binding"),
    (lambda m: m["negative"].update(node_id="p"), "ambiguous_prompt_binding"),
    (lambda m: m.pop("negative"), "prompt_mapping_incomplete"),
])
def test_group_mapping_silent_skip_cannot_certify(change, reason):
    mapping = {"group_map": {"a": "positive"}, "merge_mode": "overwrite",
               "positive": {"node_id": "p", "input_key": "text"}, "negative": {"node_id": "n", "input_key": "text"}}
    change(mapping)
    with patch("core.comfyui.build_prompt_by_group", return_value={"a": ["red"]}):
        result = finalize(provider=host_for({"comfy_mapping": mapping}))
    assert result.manifest is None
    assert json.loads(result.projection_json)["requests"][0]["blockers"] == [reason]


def test_projection_allowlist_complete_and_host_identity_comparison_no_io_or_authority():
    runtime, state, provider = queued()
    before = copy.deepcopy(state)
    swap = runtime.inspect_review_custody()
    pending = runtime.generation_review_custodian.inspect()
    with patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
         patch("threading.Thread.start", side_effect=AssertionError("worker")), \
         patch("builtins.open", side_effect=AssertionError("filesystem output")), \
         patch("core.comfy_prompt_request.prepare_prompt_request", side_effect=AssertionError("rerandomization")):
        decision = build_executable_generation_review(state, runtime, provider, random_u64=lambda: 0)
        assert decision.status == "certified"
        view = inspect_executable_generation_review(state, runtime, provider, decision.review)
        assert view["state"] == "certified"
        assert view == inspect_executable_generation_review(state, runtime, provider, decision.review)
        action = capture_human_start_action(runtime, pending["proposal_id"], pending["plan_id"])
        assert authorize_generation_start(state, runtime, provider, action,
                          certificate=decision.review).status == "executable_review_required"
    assert state == before and runtime.inspect_review_custody() == swap
    assert runtime.generation_review_custodian.inspect() == pending and not runtime.generation_jobs._jobs
    assert not view["execution_available"] and not view["job_submitted"]
    assert len(view["requests"]) == 6 and len(view["targets"]) == 2
    assert all(s not in json.dumps(view) for s in ("PRIVATE", "workflow_json", "node_id", "request_id", "settings"))
    tampered = json.loads(decision.review.projection_json)
    tampered["raw_workflow"] = "private"
    bad = replace(decision.review, projection_json=owner.encode(tampered))
    assert inspect_executable_generation_review(state, runtime, provider, bad) == {"state": "invalid_review"}
    assert inspect_executable_generation_review(state, runtime, provider, replace(decision.review,
                            source_identity="0" * 64)) == {"state": "stale"}
    runtime.close()


@pytest.mark.parametrize("drift", ["prompt", "module", "workflow", "config", "save_as", "switch", "pairing", "close", "expiry"])
def test_review_drift_refuses_without_consuming_or_claiming(drift):
    runtime, state, provider = queued()
    carrier = build_executable_generation_review(state, runtime, provider, random_u64=lambda: 0).review
    assert carrier
    if drift == "prompt": state["project"].prompt_lines[1].current_text = "changed"
    elif drift == "module": state["project"].module_library["new"] = {"body": "changed"}
    elif drift == "workflow": provider = host_for(change=lambda w: w["s"]["inputs"].update(steps=25))
    elif drift == "config": provider = host_for({"agent_generation_seed_policy": "preserve_u64"})
    elif drift == "save_as": state["current_project_path"] = "new"
    elif drift == "switch": state["project"] = copy.deepcopy(state["project"])
    elif drift == "pairing": runtime.generation_review_custodian._record.pairing_generation += 1
    elif drift == "expiry": runtime.generation_review_custodian._record.expires_at = 0
    else: runtime.close()
    assert inspect_executable_generation_review(state, runtime, provider, carrier)["state"] != "certified"
    assert not runtime.generation_jobs._jobs
    runtime.close()


def test_reentrant_activation_change_during_seed_finalization_refuses():
    runtime, state, provider = queued()
    def random():
        state["project"] = copy.deepcopy(state["project"])
        return 0
    decision = build_executable_generation_review(state, runtime, provider, random_u64=random)
    assert decision.review is None and not runtime.generation_jobs._jobs
    runtime.close()


@pytest.mark.parametrize("boundary", ["workflow", "aggregate", "binding", "seed", "parameter", "prompt"])
def test_bounded_projection_and_workflow_limits(boundary, monkeypatch):
    if boundary == "aggregate":
        monkeypatch.setattr(owner, "MAX_AGGREGATE_BYTES", 1)
        result = finalize()
    else:
        monkeypatch.setattr(owner, {"workflow": "MAX_WORKFLOW_BYTES", "binding": "MAX_BINDINGS", "seed": "MAX_SEEDS",
                                  "parameter": "MAX_PARAMETERS", "prompt": "MAX_REVIEW_TEXT"}[boundary], 1)
        result = finalize()
    assert result.manifest is None
    assert len(json.loads(result.projection_json)["requests"]) >= 6


def test_missing_request_coverage_rejects_instead_of_partial_review():
    preview, preflight = inputs()
    preflight["request_plan"].pop()
    with pytest.raises(ValueError):
        owner.finalize_generation_manifest("proposal", preview, preflight)


def test_real_serialized_workflow_and_repeated_aggregate_size_limits():
    provider = host_for(change=lambda w: w["out"]["inputs"].update(filename_prefix="青" * 350000))
    result = finalize(1, provider)
    assert result.manifest is None
    assert json.loads(result.projection_json)["requests"][0]["blockers"] == ["workflow_limit"]
    provider = host_for(change=lambda w: w["out"]["inputs"].update(filename_prefix="x" * 899000))
    result = finalize(5, provider)
    view = json.loads(result.projection_json)
    assert result.manifest is None and len(view["requests"]) == 10
    assert any(row["blockers"] == ["aggregate_limit"] for row in view["requests"])
    assert "x" * 100 not in result.projection_json.decode()


def test_actual_configured_host_file_binding_and_drift(tmp_path):
    provider, settings_state, path = app_host(tmp_path)
    path.write_text(json.dumps(workflow()), encoding="utf-8")
    before_file, before_settings = path.read_bytes(), copy.deepcopy(settings_state)
    runtime, state, provider = queued(provider=provider)
    before_project = copy.deepcopy(state["project"])
    decision = build_executable_generation_review(state, runtime, provider, random_u64=lambda: 0)
    assert decision.status == "certified"
    assert path.read_bytes() == before_file and settings_state == before_settings
    assert state["project"] == before_project
    assert str(path) not in decision.review.projection_json.decode()
    changed = workflow()
    changed["out"]["inputs"]["filename_prefix"] = "changed file"
    path.write_text(json.dumps(changed), encoding="utf-8")
    assert inspect_executable_generation_review(state, runtime, provider, decision.review)["state"] == "stale"
    assert not runtime.generation_jobs._jobs
    runtime.close()


def test_placeholder_does_not_silently_certify_uninjected_negative():
    preview, preflight = inputs(1)
    source = workflow()
    source["p"]["inputs"]["text"] = "__PROMPT__"
    binding = {}
    injected, _ = _build_line_workflow_from_text(json.dumps(source), project().prompt_lines[1], {},
                                                _binding_context=binding)
    preflight["workflow_plan"]["two"]["workflow_json"] = injected
    preflight["binding_contexts"]["two"] = binding
    result = owner.finalize_generation_manifest("proposal", preview, preflight, random_u64=lambda: 0)
    assert result.manifest is None
    assert json.loads(result.projection_json)["requests"][0]["blockers"] == ["prompt_text_mismatch"]


def test_missing_private_evidence_and_incomplete_review_remain_non_authoritative():
    preview, preflight = inputs(1)
    preflight["binding_contexts"]["two"] = None
    result = owner.finalize_generation_manifest("proposal", preview, preflight, random_u64=lambda: 0)
    assert result.manifest is None
    assert json.loads(result.projection_json)["targets"][0]["unsupported_bindings"] == ["prompt_evidence_unavailable"]
    runtime, state, provider = queued(provider=host_for(change=lambda w: w["s"]["inputs"].update(seed=-1)))
    decision = build_executable_generation_review(state, runtime, provider, random_u64=lambda: 0)
    assert decision.status == "uncertifiable"
    view = inspect_executable_generation_review(state, runtime, provider, decision.review)
    assert view["state"] == "uncertifiable" and len(view["requests"]) == 6
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    assert not runtime.generation_jobs._jobs
    runtime.close()


def test_private_random_source_failure_is_a_bounded_code():
    def broken():
        raise ValueError("PRIVATE_PATH_AND_CREDENTIAL")
    result = finalize(random_u64=broken)
    assert result.manifest is None and b"PRIVATE" not in result.projection_json
    assert json.loads(result.projection_json)["requests"][0]["blockers"] == ["workflow_preparation_failed"]


def test_expiry_countdown_during_recomputation_is_not_content_drift():
    runtime, state, provider = queued()
    base, ticks = time.monotonic(), iter(range(100))
    runtime.generation_review_custodian._clock = lambda: base + next(ticks) * 0.25
    decision = build_executable_generation_review(state, runtime, provider, random_u64=lambda: 0)
    assert decision.status == "certified"
    assert inspect_executable_generation_review(state, runtime, provider, decision.review)["state"] == "certified"
    assert not runtime.generation_jobs._jobs
    runtime.close()
