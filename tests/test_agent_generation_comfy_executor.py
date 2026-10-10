"""C2B-4 frozen submission and remote receipts, deterministic fakes only."""
import copy
from dataclasses import replace, FrozenInstanceError
import json
from unittest.mock import patch
import uuid

import pytest

from core.comfy_prompt_request import prepare_frozen_prompt_request
from core.comfy_remote_output_receipts import validate_remote_outputs, MAX_REMOTE_BYTES, MAX_REMOTE_IMAGES
from ui import agent_generation_comfy_executor as owner
from ui.agent_generation_comfy_executor import ComfyExecutorAdapter, SubmissionResult, ExecutionResult, ComfyProgress
from ui.agent_generation_executor_inbox import GenerationExecutorInbox
from ui.agent_generation_job import GenerationJobRegistry
from test_agent_generation_executor_handoff import ready, start, deliver, event, safe_capture
from test_agent_generation_executable_review_ui import queued, prepare, confirm, identity
from ui.agent_generation_executor_handoff import capture_executor_human_start_for_characterization as capture_start
from test_agent_generation_executable_manifest import host_for


def raw(value):
    return json.dumps(value).encode()


def metadata(prompt, *, images=None, node="out"):
    return raw({prompt: {"outputs": {node: {"images": images if images is not None else [
        {"filename": "private_image.png", "subfolder": "private/folder", "type": "output"}]}}}})


def result(prepared, prompt, status="ready", **kwargs):
    return ExecutionResult(prepared.request_id, prompt, status,
        kwargs.pop("history_json", metadata(prompt) if status == "ready" else b""), **kwargs)


def harness(values=None, transport=None, provider=None, *, characterization=True):
    values = values or ready()
    runtime, _, state, *_ = values
    sent = []
    def send(prepared):
        sent.append(prepared)
        return transport(prepared) if transport else SubmissionResult("accepted", raw({"prompt_id": str(uuid.uuid4())}))
    adapter = ComfyExecutorAdapter(runtime.generation_jobs, runtime._generation_executor_inbox,
        fake_transport=send, fake_result_provider=provider or result,
        host_event_sink=lambda value: deliver(state, runtime, value), characterization=characterization)
    return values, adapter, sent


def settle(values, adapter):
    runtime, _, state, *_ = values
    envelope = adapter._envelope
    snapshot = runtime.generation_jobs.snapshot(envelope.job_id)
    index = adapter._index
    count = snapshot["requests"][index]["remote_output_count"]
    assert deliver(state, runtime, event(adapter._acceptance, snapshot["event_count"] + 1,
        "outputs_ready", index=index, count=count)) == "accepted"
    assert runtime.generation_jobs.publication_for_characterization(envelope.job_id, envelope.claim_id,
        binding=envelope.binding, request_index=index, registered_count=count) == "accepted"


def test_frozen_order_and_remote_receipts_are_distinct_from_local_publication():
    values, adapter, sent = harness()
    runtime, _, state, _, held, _ = values
    before, swap = copy.deepcopy(state), runtime.inspect_review_custody()
    with patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
         patch("threading.Thread.start", side_effect=AssertionError("worker")), \
         patch("builtins.open", side_effect=AssertionError("output")), \
         patch("core.comfy_prompt_request.prepare_prompt_request", side_effect=AssertionError("randomizer")), \
         patch("core.comfy_prompt_request.random.randint", side_effect=AssertionError("randomizer")):
        accepted = start(values, adapter.accept_and_run_for_characterization)
        assert accepted.status == "characterized_acceptance"
        for index in range(4):
            snapshot = runtime.generation_jobs.snapshot(accepted.job_id)
            assert snapshot["requests"][index]["state"] == "awaiting_download"
            assert snapshot["requests"][index]["output_count"] == 0
            assert snapshot["requests"][index]["registered_count"] == 0
            assert runtime.generation_jobs.publication_for_characterization(accepted.job_id, accepted.claim_id,
                binding=adapter._envelope.binding, request_index=index, registered_count=1) == "invalid_transition"
            assert snapshot["remote_output_count"] == index + 1
            assert len(sent) == index + 1
            adapter.advance_for_characterization()
            assert len(sent) == index + 1
            settle(values, adapter)  # fake registry counts only, never Project
            adapter.advance_for_characterization()
    assert [item.request_index for item in sent] == [0, 1, 2, 3]
    for prepared, request in zip(sent, held.review.manifest.requests):
        assert prepared.request_id == request.request_id
        assert json.loads(prepared.body_json)["prompt"] == json.loads(request.workflow_json)
        assert request.workflow_json in prepared.body_json
        assert prepared.prompt_url == "http://PRIVATE_ENDPOINT/prompt"
        assert json.loads(prepared.body_json)["client_id"] == prepared.client_id
    receipts = adapter.remote_receipts()
    assert len(receipts) == 4 and len({r.identity for r in receipts}) == 4
    assert all(r.job_id == accepted.job_id and r.prompt_id and r.images[0].node_id == "out" for r in receipts)
    assert state == before and runtime.inspect_review_custody() == swap
    snapshot = runtime.generation_jobs.snapshot(accepted.job_id)
    assert snapshot["state"] == "completed" and snapshot["save_state"] == "not_attempted"
    assert "private_image" not in repr(snapshot) and "PRIVATE_ENDPOINT" not in repr(snapshot)
    assert not adapter.execution_available and not runtime.generation_jobs.execution_available
    assert runtime._generation_executor_inbox.accept_for_characterization(runtime.generation_jobs, accepted)[1] is None
    assert start(values, adapter.accept_and_run_for_characterization).status != "characterized_acceptance"
    with pytest.raises(FrozenInstanceError): receipts[0].images = ()
    runtime.close()


def test_zero_seed_and_noise_seed_frozen_without_randomization():
    provider = host_for({"agent_generation_seed_policy": "preserve_u64"},
                        lambda workflow: workflow["noise"]["inputs"].update(noise_seed=0))
    runtime, route, _, state, _, provider = queued(runs=2, provider=provider)
    runtime.generation_jobs = GenerationJobRegistry(characterization=True)
    runtime._generation_executor_inbox = GenerationExecutorInbox(characterization=True)
    runtime.synchronize_target(state["project"], state["current_project_path"])
    assert prepare(state, runtime, provider, *identity(runtime)) == "certified"
    held = runtime._executable_review
    assert confirm(state, runtime, provider, held) == "confirmed"
    values, adapter, sent = harness((runtime, route, state, provider, held, capture_start(runtime)))
    assert start(values, adapter.accept_and_run_for_characterization).status == "characterized_acceptance"
    workflow = json.loads(sent[0].body_json)["prompt"]
    assert workflow["s"]["inputs"]["seed"] == workflow["noise"]["inputs"]["noise_seed"] == 0
    runtime.close()


@pytest.mark.parametrize("change", ["digest", "request_identity", "order", "destination", "duplicate", "oversized"])
def test_frozen_preparation_rejects_changed_identity_digest_and_bounds(change):
    values = ready()
    manifest = values[4].review.manifest
    request = manifest.requests[0]
    if change == "digest": request = replace(request, workflow_identity="0" * 64)
    elif change == "request_identity": request = replace(request, request_id="different")
    elif change == "order": request = replace(request, request_index=1)
    elif change == "destination": manifest = replace(manifest, host_config_json=raw({"comfyui_endpoint": "other"}))
    elif change == "duplicate": manifest = replace(manifest, requests=(request, request))
    elif change == "oversized": request = replace(request, workflow_json=b" " * 1_000_001)
    if change in {"digest", "request_identity", "oversized"}:
        manifest = replace(manifest, requests=(request,) + manifest.requests[1:])
    with pytest.raises(ValueError): prepare_frozen_prompt_request(manifest, request, client_id=str(uuid.uuid4()))
    values[0].close()


@pytest.mark.parametrize("status", ["rejected_before_submission", "execution_failed"])
def test_immediate_definitive_failures_settle_every_request_before_handoff_returns(status):
    transport = (lambda prepared: SubmissionResult(status)) if status == "rejected_before_submission" else None
    values, adapter, sent = harness(transport=transport, provider=lambda p, prompt: result(p, prompt, "execution_failed"))
    accepted = start(values, adapter.accept_and_run_for_characterization)
    jobs = values[0].generation_jobs
    assert accepted.status == "characterized_acceptance" and len(sent) == 4
    assert jobs.snapshot(accepted.job_id)["state"] == "failed"
    assert values[0]._generation_executor_inbox.accepted_receipt(jobs, accepted).status == "characterized_acceptance"
    adapter.advance_for_characterization()
    assert len(sent) == 4 and not adapter.remote_receipts()
    values[0].close()


@pytest.mark.parametrize("response", [None, b"{}", b"not json", raw({"prompt_id": "bad"}),
    raw({"prompt_id": 1}), b'{"prompt_id":"a","prompt_id":"b"}', b" " * (MAX_REMOTE_BYTES + 1)],
    ids=["timeout", "missing", "malformed", "invalid_uuid", "wrong_type", "duplicate_key", "oversized"])
def test_ambiguous_submission_never_retries_or_starts_next_request(response):
    def transport(prepared):
        if response is None: raise TimeoutError("PRIVATE_URL_AND_ERROR")
        return SubmissionResult("accepted", response)
    values, adapter, sent = harness(transport=transport)
    accepted = start(values, adapter.accept_and_run_for_characterization)
    assert len(sent) == 1 and adapter.observation().status == "submission_outcome_unknown"
    jobs = values[0].generation_jobs
    assert jobs.snapshot(accepted.job_id)["state"] == "submission_outcome_unknown"
    for _ in range(3): adapter.advance_for_characterization()
    assert len(sent) == 1 and "PRIVATE" not in repr(jobs.snapshot(accepted.job_id))
    assert jobs.claim_for_characterization(accepted.job_id, binding=adapter._envelope.binding,
        claim_key=values[-1].nonce).status == "terminal"
    values[0].close()


def test_duplicate_prompt_id_is_unknown_and_stops_second_request():
    prompt = str(uuid.uuid4())
    values, adapter, sent = harness(transport=lambda p: SubmissionResult("accepted", raw({"prompt_id": prompt})),
        provider=lambda p, prompt: result(p, prompt, "execution_failed"))
    accepted = start(values, adapter.accept_and_run_for_characterization)
    assert len(sent) == 2 and values[0].generation_jobs.snapshot(accepted.job_id)["state"] == "submission_outcome_unknown"
    adapter.advance_for_characterization()
    assert len(sent) == 2
    values[0].close()


@pytest.mark.parametrize("status", ["pending", "timeout", "unknown"])
def test_execution_timeout_progress_and_correlated_later_result_without_resubmission(status):
    values, adapter, sent = harness(provider=lambda p, prompt: result(p, prompt, status,
        progress=(ComfyProgress(1, 20), ComfyProgress(2, 20))))
    accepted = start(values, adapter.accept_and_run_for_characterization)
    jobs = values[0].generation_jobs
    assert accepted.status == "characterized_acceptance" and jobs.snapshot(accepted.job_id)["state"] == "awaiting_result"
    for _ in range(3): adapter.advance_for_characterization()
    snapshot = jobs.snapshot(accepted.job_id)
    assert len(sent) == 1 and snapshot["event_count"] == (5 if status == "timeout" else 4)
    assert adapter.observation().status == {"pending": "awaiting_remote_result", "timeout": "execution_timeout",
        "unknown": "execution_outcome_unknown"}[status]
    assert sum(e["kind"] == "execution_timeout" for e in snapshot["events"]) == (1 if status == "timeout" else 0)
    if status == "timeout":
        deadline = jobs._jobs[accepted.job_id].deadline
        adapter.receive_result_for_characterization(result(sent[0], adapter._active_prompt, "timeout"))
        assert jobs.snapshot(accepted.job_id) == snapshot and jobs._jobs[accepted.job_id].deadline == deadline
        assert len(sent) == 1
    good = result(sent[0], adapter._active_prompt)
    assert adapter.receive_result_for_characterization(replace(good, request_id="wrong")).status == "result_correlation_mismatch"
    assert adapter.receive_result_for_characterization(replace(good, prompt_id=str(uuid.uuid4()))).status == "result_correlation_mismatch"
    assert adapter.receive_result_for_characterization(good).status == "awaiting_download"
    snapshot = jobs.snapshot(accepted.job_id)
    assert adapter.receive_result_for_characterization(good).status == "duplicate_remote_receipt"
    assert adapter.receive_result_for_characterization(replace(good, status="execution_failed")).status == "result_fenced"
    assert jobs.snapshot(accepted.job_id) == snapshot and len(sent) == 1
    settle(values, adapter)
    adapter.advance_for_characterization()
    assert len(sent) == 2
    assert adapter.receive_result_for_characterization(good).status == "result_correlation_mismatch"
    values[0].close()


@pytest.mark.parametrize("bad", ["missing", "empty", "duplicate", "extra_node", "malformed", "oversized", "count",
    "duplicate_keys", "wrong_prompt", "status_failed", "status_pending"])
def test_untrusted_metadata_is_quarantined_and_blocks_next_request(bad):
    def provider(p, prompt):
        record = {"filename": "image.png", "subfolder": "", "type": "output"}
        data = metadata(prompt)
        if bad == "missing": data = raw({prompt: {}})
        elif bad == "empty": data = metadata(prompt, images=[])
        elif bad == "duplicate": data = metadata(prompt, images=[record, record])
        elif bad == "extra_node": data = metadata(prompt, node="unknown")
        elif bad == "malformed": data = metadata(prompt, images=[{"filename": "image.png"}])
        elif bad == "oversized": data = b" " * (MAX_REMOTE_BYTES + 1)
        elif bad == "count": data = metadata(prompt, images=[dict(record, filename=f"{i}.png") for i in range(MAX_REMOTE_IMAGES + 1)])
        elif bad == "duplicate_keys": data = ('{"' + prompt + '":{"outputs":{},"outputs":{}}}').encode()
        elif bad == "wrong_prompt": data = metadata(str(uuid.uuid4()))
        else: data = raw({prompt: {"outputs": {"out": {"images": [record]}},
            "status": {"status_str": "error" if bad == "status_failed" else "success", "completed": bad == "status_failed"}}})
        return result(p, prompt, history_json=data)
    values, adapter, sent = harness(provider=provider)
    accepted = start(values, adapter.accept_and_run_for_characterization)
    assert adapter.observation().status == "remote_metadata_quarantined"
    assert values[0].generation_jobs.snapshot(accepted.job_id)["state"] == "awaiting_result"
    adapter.advance_for_characterization()
    assert len(sent) == 1 and not adapter.remote_receipts() and not adapter.late_receipts()
    values[0].close()


@pytest.mark.parametrize("key,value", [("filename", s) for s in (
    "../image.png", "C:\\image.png", "https://host/image.png", "NUL.png", "image.png.", "image%2f.png",
    "image\x00.png", "image.txt", "a" * 256 + ".png")] + [("subfolder", s) for s in (
    "../x", "/absolute", "C:\\x", "a//b", "a/..", "a/CON", "a" * 1025)],
    ids=[f"unsafe-{i}" for i in range(16)])
def test_unsafe_remote_components_never_become_local_destinations(key, value):
    values, adapter, _ = harness(provider=lambda p, prompt: result(p, prompt,
        history_json=metadata(prompt, images=[dict(filename="safe.png", subfolder="", type="output") | {key: value}])))
    start(values, adapter.accept_and_run_for_characterization)
    assert adapter.observation().status == "remote_metadata_quarantined" and not adapter.remote_receipts()
    values[0].close()


@pytest.mark.parametrize("invalidation", ["switch", "save_as", "pairing", "disarm", "close"])
def test_late_outputs_after_host_invalidation_are_private_and_cannot_advance(invalidation):
    values, adapter, sent = harness(provider=lambda p, prompt: result(p, prompt, "pending"))
    runtime, route, state, *_ = values
    accepted = start(values, adapter.accept_and_run_for_characterization)
    pending = result(sent[0], adapter._active_prompt)
    if invalidation == "switch": state["project"] = copy.deepcopy(state["project"])
    elif invalidation == "save_as": state["current_project_path"] = "SAVE_AS"
    elif invalidation == "pairing":
        route.release()
        bootstrap = runtime.arm_local_pairing().bootstrap
        assert runtime._registry.claim_pairing(bootstrap.process_incarnation, bootstrap.route_id,
            bootstrap.capability).status == "paired"
    elif invalidation == "disarm": runtime.disarm_launcher_rendezvous()
    else: runtime.close()
    assert adapter.receive_result_for_characterization(pending).status == "late_remote_receipt"
    assert not adapter.remote_receipts() and len(adapter.late_receipts()) == 1
    adapter.advance_for_characterization()
    assert len(sent) == 1
    snapshot = runtime.generation_jobs.snapshot(accepted.job_id)
    assert snapshot.get("remote_output_count", 0) == snapshot.get("registered_count", 0) == 0
    runtime.close()


def test_receipt_memory_and_total_progress_are_bounded(monkeypatch):
    monkeypatch.setattr(owner, "MAX_RECEIPT_BYTES", 1)
    values, adapter, sent = harness()
    start(values, adapter.accept_and_run_for_characterization)
    assert adapter.observation().status == "receipt_capacity_unavailable"
    assert not adapter.remote_receipts() and adapter._receipt_bytes == 0
    adapter.advance_for_characterization()
    assert len(sent) == 1
    monkeypatch.setattr(owner, "MAX_RECEIPT_BYTES", 512 * 1024)
    pending = result(sent[0], adapter._active_prompt, "pending", progress=(ComfyProgress(1, 20),) * 4)
    adapter.receive_result_for_characterization(pending)
    count = values[0].generation_jobs.snapshot(adapter._envelope.job_id)["event_count"]
    adapter.receive_result_for_characterization(pending)
    assert values[0].generation_jobs.snapshot(adapter._envelope.job_id)["event_count"] == count
    assert adapter._progress_count == 4
    values[0].close()


def test_default_adapter_disabled():
    values, disabled, sent = harness(characterization=False)
    assert start(values, disabled.accept_and_run_for_characterization).status != "characterized_acceptance"
    assert not sent
    values[0].close()


@pytest.mark.parametrize("field,value", [("request_id", "wrong"), ("request_index", -1),
    ("output_nodes", (("unknown", "output"),)), ("body_json", b"{}"), ("prompt_url", "http://other/prompt")])
def test_receipt_cannot_replace_frozen_request_correlation_or_node_provenance(field, value):
    values, adapter, sent = harness()
    start(values, adapter.accept_and_run_for_characterization)
    with pytest.raises(ValueError):
        validate_remote_outputs(adapter._envelope, replace(sent[0], **{field: value}),
                                adapter._active_prompt, metadata(adapter._active_prompt))
    values[0].close()


def test_unknown_deadline_does_not_free_consumed_claim_or_restart_adapter():
    values, adapter, sent = harness(transport=lambda p: SubmissionResult("unknown"))
    accepted = start(values, adapter.accept_and_run_for_characterization)
    jobs, inbox = values[0].generation_jobs, values[0]._generation_executor_inbox
    jobs._clock = lambda: 10**12
    jobs.snapshot(accepted.job_id)  # cleanup is not evidence of remote rejection
    adapter.advance_for_characterization()
    assert len(sent) == 1
    assert inbox.accept_for_characterization(jobs, accepted)[1] is None
    assert inbox.retire_settled_for_characterization(jobs, accepted) != "retired"
    values[0].close()


def test_accumulated_receipt_capacity_never_discards_authoritative_batch(monkeypatch):
    values, adapter, sent = harness()
    start(values, adapter.accept_and_run_for_characterization)
    first = adapter.remote_receipts()[0]
    monkeypatch.setattr(owner, "MAX_RECEIPT_BYTES", first.encoded_size)
    settle(values, adapter)
    adapter.advance_for_characterization()
    assert len(sent) == 2 and adapter.observation().status == "receipt_capacity_unavailable"
    assert adapter.remote_receipts() == (first,) and adapter._receipt_bytes == first.encoded_size
    adapter.advance_for_characterization()
    assert len(sent) == 2
    values[0].close()


def test_transport_reentry_cannot_submit_twice():
    holder = []
    def transport(p):
        holder[0].advance_for_characterization()
        return SubmissionResult("accepted", raw({"prompt_id": str(uuid.uuid4())}))
    values, adapter, sent = harness(transport=transport)
    holder.append(adapter)
    start(values, adapter.accept_and_run_for_characterization)
    assert len(sent) == 1
    values[0].close()


def test_fake_progress_and_successful_terminalization_before_handoff_returns():
    values, adapter, sent = harness(provider=lambda p, prompt: result(p, prompt,
        progress=(ComfyProgress(20, 20),)))
    before = copy.deepcopy(values[2])
    def worker(offer):
        receipt = adapter.accept_and_run_for_characterization(offer)
        for _ in range(4):
            settle(values, adapter)
            adapter.advance_for_characterization()
        assert values[0].generation_jobs.snapshot(offer.job_id)["state"] == "completed"
        return receipt
    accepted = start(values, worker)
    assert accepted.status == "characterized_acceptance" and len(sent) == 4
    assert values[2] == before
    assert values[0]._generation_executor_inbox.accept_for_characterization(values[0].generation_jobs, accepted)[1] is None
    values[0].close()


def test_remote_descriptor_identity_is_stable_across_json_and_image_order():
    values, adapter, sent = harness()
    start(values, adapter.accept_and_run_for_characterization)
    images = [{"filename": f"image{i}.png", "subfolder": "", "type": "output"} for i in range(2)]
    first = validate_remote_outputs(adapter._envelope, sent[0], adapter._active_prompt,
        metadata(adapter._active_prompt, images=images))
    second = validate_remote_outputs(adapter._envelope, sent[0], adapter._active_prompt,
        metadata(adapter._active_prompt, images=list(reversed(images))))
    assert first.identity == second.identity and first.images == second.images
    assert first.request_id == sent[0].request_id and first.workflow_identity == sent[0].workflow_identity
    assert first.claim_id == adapter._envelope.claim_id and first.manifest_identity == adapter._envelope.manifest.manifest_identity
    values[0].close()
