"""C2B-7 composed fake execution and evidence-retention characterization.

No active user Project, transport, recovery journal, restart reconstruction or
production worker. Reuse C2B-6's disposable fixture: real review/confirmation,
one-shot handoff, fake executor, real receipt validation and contained files.
"""
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.comfy_output_containment import ContainedOutputStore, DownloadStream
from core.io import load_project_from_json
from ui.agent_generation_candidate_publication import GenerationCandidatePublication
from ui.agent_generation_executor_handoff import (
    capture_executor_human_start_for_characterization as capture_start,
    local_output_custody_current_for_characterization as local_current,
)
from ui.agent_generation_executor_inbox import GenerationExecutorInbox
from ui.agent_generation_job import GenerationJobRegistry
from ui import project_capture_safety as capture
from test_agent_generation_candidate_publication import rig, finish, publish, app_owners, State
from test_agent_generation_comfy_executor import harness, result
from test_agent_generation_executable_manifest import host_for
from test_agent_generation_executable_review_ui import queued, prepare, confirm, identity
from test_agent_generation_executor_handoff import start
from test_comfy_output_containment import contain, image_bytes, successful_metadata, stream_provider


def retained(rig):
    return [Path(path) for path, _ in rig.publisher._assets._retained]


def test_complete_fake_path_reopen_binds_every_request_and_never_replays(rig):
    original = copy.deepcopy(rig.state["project"])
    swap = rig.runtime.inspect_review_custody()
    manifest = rig.adapter._envelope.manifest
    frozen_review = json.loads(rig.publisher._origin.review_json)
    appends, saves = [], []
    appender, saver = rig.publisher._appender, rig.publisher._save
    rig.publisher._appender = lambda line, records: (appends.append(line.id), appender(line, records))[1]
    rig.publisher._save = lambda *args: (saves.append(args[1]), saver(*args))[1]
    receipts = finish(rig)
    assert rig.runtime.generation_jobs.snapshot(rig.accepted.job_id)["save_state"] == "not_attempted"
    assert not Path(rig.state["current_project_path"]).exists()
    assert [r.request_index for r in receipts] == list(range(4))
    assert rig.publisher.save_for_characterization() == "saved"
    path = Path(rig.state["current_project_path"])
    reopened = load_project_from_json(str(path))
    records = [c for line in reopened.prompt_lines for c in line.generated_candidates]
    assert len(records) == 8
    for index, request in enumerate(manifest.requests):
        submitted = rig.sent[index]
        assert submitted.request_id == request.request_id
        assert json.loads(submitted.body_json)["prompt"] == json.loads(request.workflow_json)
        batch = [c for c in records if c["generation_provenance"]["request_index"] == index]
        assert len(batch) == 2
        for record in batch:
            provenance = record["generation_provenance"]
            assert provenance["workflow_identity"] == request.workflow_identity
            assert provenance["illustration_id"] == request.illustration_id
            assert provenance["run_index"] == request.run_index
            assert provenance["seeds"] == frozen_review["requests"][index]["seeds"]
            assert provenance["prompts"] == frozen_review["requests"][index]["prompts"]
            assert provenance["local_receipt_identity"] == rig.adapter.local_receipts()[index].identity
            assert provenance["remote_receipt_identity"] == rig.adapter.remote_receipts()[index].identity
            assert hashlib.sha256((path.parent / record["path"]).read_bytes()).hexdigest() == provenance["content_sha256"]
    assert records[0]["seed"] == 0 and records[0]["prompt_text"] == "red"
    for before, after in zip(original.prompt_lines, reopened.prompt_lines):
        assert (before.id, before.current_text, before.negative_prompt, before.image_path) == (
            after.id, after.current_text, after.negative_prompt, after.image_path)
    assert rig.runtime.inspect_review_custody() == swap
    assert rig.runtime._generation_executor_inbox.accept_for_characterization(
        rig.runtime.generation_jobs, rig.accepted)[1] is None
    for index, receipt in enumerate(receipts):
        assert publish(rig, index) == receipt
    assert rig.publisher.save_for_characterization() == "saved"
    rig.adapter.advance_for_characterization()
    assert len(rig.sent) == len(appends) == 4 and len(saves) == 1
    assert not any(owner.execution_available for owner in (rig.publisher, rig.adapter, rig.store,
        rig.runtime.generation_jobs, rig.runtime._generation_executor_inbox))


def test_failure_between_promotion_and_registration_retains_both_evidence_sets(rig):
    before = copy.deepcopy(rig.state["project"])
    calls = []
    def fail_factory(*args):
        calls.append(args)
        raise RuntimeError("after promotion, before registration")
    rig.publisher._factory = fail_factory
    receipt = publish(rig)
    assert (receipt.promotion_state, receipt.registration_state, receipt.registered_count) == (
        "promoted", "registration_failed", 0)
    assert len(retained(rig)) == 2 and all(p.read_bytes() == image_bytes() for p in retained(rig))
    assert rig.store.receipts_for_characterization()[0].state == "verified"
    assert rig.state["project"] == before and not rig.state["history"]
    assert publish(rig) == receipt and len(calls) == 1
    rig.adapter.advance_for_characterization()
    assert len(rig.sent) == 1 and rig.publisher.save_for_characterization() == "registration_incomplete"
    rig.runtime.generation_jobs._clock = lambda: 10**12
    rig.runtime.generation_jobs.cleanup()
    assert all(p.exists() for p in retained(rig))  # expiry is never asset cleanup


def test_partial_insertion_never_replays_and_uncertainty_blocks_final_save(rig):
    appender = rig.publisher._appender
    calls = []
    def append_one_then_fail(line, records):
        calls.append(line.id)
        appender(line, records[:1])
        raise RuntimeError("after one observed insertion")
    rig.publisher._appender = append_one_then_fail
    receipt = publish(rig)
    assert receipt.registration_state == "registration_uncertain" and receipt.registered_count == 1
    assert len(rig.state["project"].prompt_lines[1].generated_candidates) == 1
    assert len(rig.state["history"]) == 1 and len(retained(rig)) == 2
    assert publish(rig) == receipt and len(calls) == 1
    snapshot = rig.runtime.generation_jobs.snapshot(rig.accepted.job_id)
    assert snapshot["requests"][0]["state"] == "partially_failed"
    # A settled observed count permits a later distinct request. It never
    # repairs/replays the first insertion or erases its publication uncertainty.
    rig.publisher._appender = appender
    rig.adapter.advance_for_characterization()
    for index in range(1, 4):
        assert contain(rig.adapter, rig.store, stream_provider(image_bytes())).status == "local_outputs_ready"
        assert publish(rig).registration_state == "registered"
        rig.adapter.advance_for_characterization()
    assert len(rig.sent) == 4 and len(calls) == 1
    assert rig.runtime.generation_jobs.snapshot(rig.accepted.job_id)["state"] == "partially_failed"
    assert rig.publisher.save_for_characterization() == "registration_uncertain"
    assert not Path(rig.state["current_project_path"]).exists()


@pytest.mark.parametrize("outcome", ["failure", "replaced_then_unknown"])
def test_complete_registration_and_persistence_are_separate_durable_evidence(rig, outcome):
    finish(rig)
    calls = []
    real_save = rig.publisher._save
    def save(*args):
        calls.append(args[1])
        if outcome == "failure":
            return False
        real_save(*args)
        raise RuntimeError("reply lost after atomic replacement")
    rig.publisher._save = save
    expected = "save_failed" if outcome == "failure" else "save_uncertain"
    assert rig.publisher.save_for_characterization() == expected
    assert rig.publisher.save_for_characterization() == expected and len(calls) == 1
    snapshot = rig.runtime.generation_jobs.snapshot(rig.accepted.job_id)
    assert snapshot["state"] == "completed" and snapshot["registered_count"] == 8
    assert snapshot["save_state"] == expected
    assert len(retained(rig)) == 8 and all(p.exists() for p in retained(rig))
    assert sum(len(line.generated_candidates) for line in rig.state["project"].prompt_lines) == 8
    path = Path(rig.state["current_project_path"])
    assert path.exists() is (outcome != "failure")
    if path.exists():
        reopened = load_project_from_json(str(path))
        assert sum(len(line.generated_candidates) for line in reopened.prompt_lines) == 8
        # Reopening verifies disk contents, not the expired callback's authority.
        assert snapshot["save_state"] == "save_uncertain"


@pytest.mark.parametrize("invalidation", ["switch_back", "save_as", "pairing"])
def test_invalidation_wins_after_unlocked_promotion_before_registration(rig, invalidation):
    promoted, release = Event(), Event()
    original_project = rig.state["project"]
    original_path = rig.state["current_project_path"]
    original = rig.publisher._assets.promote_for_characterization
    def pause_after_copy(*args):
        value = original(*args)
        promoted.set()
        assert release.wait(10)
        return value
    with patch.object(rig.publisher._assets, "promote_for_characterization", side_effect=pause_after_copy):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(publish, rig)
            try:
                assert promoted.wait(10)
                if invalidation == "switch_back":
                    rig.runtime.synchronize_target(copy.deepcopy(original_project), "other.json")
                    rig.runtime.synchronize_target(original_project, original_path)
                elif invalidation == "save_as":
                    rig.state["current_project_path"] = str(rig.tmp / "save-as.json")
                    rig.runtime.synchronize_target(original_project, rig.state["current_project_path"])
                else:
                    assert rig.route.release().status == "released"
                release.set()
                receipt = pending.result(10)
            finally:
                release.set()
    assert receipt.promotion_state == "promoted" and receipt.registration_state == "stale_original_host"
    assert all(not line.generated_candidates for line in original_project.prompt_lines)
    assert not rig.state["history"] and len(retained(rig)) == 2
    assert all(p.exists() for p in retained(rig))
    assert publish(rig) == receipt and len(rig.sent) == 1
    assert rig.publisher.save_for_characterization() == "registration_incomplete"
    assert not Path(original_path).exists()


@pytest.fixture
def remote_only(tmp_path, monkeypatch):
    """The complete real review/claim path, paused at the remote boundary."""
    monkeypatch.setattr(capture._streamlit_config, "get_option", lambda key: False)
    import test_agent_generation_executable_review_ui as review_test
    base_setup = review_test.setup
    def setup():
        runtime, route, _, state, args = base_setup()
        state["current_project_path"] = str(tmp_path / "project.json")
        epoch = runtime.synchronize_target(state["project"], state["current_project_path"])
        return runtime, route, epoch, State(state), args
    monkeypatch.setattr(review_test, "setup", setup)
    output = tmp_path / "durable"
    output.mkdir()
    monkeypatch.setattr("core.comfy_output_containment.tempfile.tempdir", str(tmp_path))
    base_provider = host_for()
    def provider(p, runs):
        host = base_provider(p, runs)
        host["generation_options"]["output_directory"] = str(output)
        return host
    runtime, route, _, state, _, provider = queued(count=1, provider=provider)
    state["history"] = []
    runtime.generation_jobs = GenerationJobRegistry(characterization=True)
    runtime._generation_executor_inbox = GenerationExecutorInbox(characterization=True)
    runtime.synchronize_target(state["project"], state["current_project_path"])
    assert prepare(state, runtime, provider, *identity(runtime), random_u64=lambda: 0) == "certified"
    held = runtime._executable_review
    assert confirm(state, runtime, provider, held) == "confirmed"
    images = [{"filename": f"remote-{index}.png", "subfolder": "", "type": "output"} for index in range(2)]
    values, adapter, sent = harness((runtime, route, state, provider, held, capture_start(runtime)),
        provider=lambda p, prompt: result(p, prompt, history_json=successful_metadata(prompt, images)))
    adapter._local_gate = lambda e, r, l: local_current(state, runtime, e, r, l)
    accepted = start(values, adapter.accept_and_run_for_characterization)
    store = ContainedOutputStore.create_for_characterization(characterization=True)
    owners = app_owners(state)
    publisher = GenerationCandidatePublication.create_for_characterization(state, runtime, adapter._envelope,
        approved_directory=str(output), candidate_factory=owners["_make_generated_candidate_record"],
        candidate_appender=owners["_append_line_generated_candidates"],
        save_project=owners["save_agent_scene_module_swap_project"], characterization=True)
    with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")), \
         patch("core.comfyui.generate_image_with_progress", side_effect=AssertionError("generation forbidden")):
        yield SimpleNamespace(runtime=runtime, state=state, adapter=adapter, sent=sent,
            accepted=accepted, store=store, publisher=publisher)
    runtime.close()


@pytest.mark.parametrize("damage", ["incomplete", "quarantined"])
def test_failed_containment_cannot_cross_durable_or_candidate_boundary(remote_only, damage):
    value = remote_only
    before = copy.deepcopy(value.state["project"])
    calls = []
    if damage == "incomplete":
        def provider(lookup):
            calls.append(lookup)
            def read(limit):
                raise OSError("stream lost")
            return DownloadStream(100, read, lambda: None)
    else:
        provider = stream_provider(lambda lookup: image_bytes() if len(calls) == 1 else b"broken", calls)
    assert contain(value.adapter, value.store, provider).status == "local_outputs_" + damage
    local, remote = value.adapter.local_receipts()[0], value.adapter.remote_receipts()[0]
    assert local.state == damage
    receipt = value.publisher.publish_for_characterization(value.store, remote, local)
    assert receipt.registration_state == "stale_original_host" and receipt.promotion_state == "not_attempted"
    assert not value.publisher._assets._retained
    assert value.state["project"] == before and not value.state["history"]
    assert contain(value.adapter, value.store, provider).status == "duplicate_local_receipt"
    assert len(calls) == (1 if damage == "incomplete" else 2)
    value.adapter.advance_for_characterization()
    snapshot = value.runtime.generation_jobs.snapshot(value.accepted.job_id)
    assert snapshot["requests"][0]["state"] == "awaiting_download" and snapshot["output_count"] == 0
    assert value.publisher.save_for_characterization() == "registration_incomplete"
    assert not Path(value.state["current_project_path"]).exists()


def test_lost_runtime_memory_leaves_files_but_cannot_reconstruct_publication(rig):
    finish(rig)
    files = retained(rig)
    envelope = rig.adapter._envelope
    origin = rig.runtime._generation_publication_origin
    rig.runtime.close()
    assert all(p.exists() for p in files)
    # A fresh registry has no old claim. A receipt/IDs/file existence cannot
    # replace private live ownership. This is not an actual restart recovery.
    fresh_jobs = GenerationJobRegistry(characterization=True)
    assert fresh_jobs.snapshot(envelope.job_id)["state"] == "unavailable"
    rig.runtime._generation_publication_origin = None
    with pytest.raises(ValueError, match="original_host_required"):
        GenerationCandidatePublication.create_for_characterization(rig.state, rig.runtime, envelope,
            approved_directory=str(rig.output), candidate_factory=rig.publisher._factory,
            candidate_appender=rig.publisher._appender, save_project=rig.publisher._save,
            characterization=True)
    assert rig.publisher.save_for_characterization() == "registration_incomplete"
    assert not Path(origin.path).exists() and all(p.exists() for p in files)
