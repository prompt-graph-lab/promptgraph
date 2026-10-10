"""Disposable Projects/JSON and fake outputs only; no active user publication."""
import ast
import copy
from dataclasses import replace, FrozenInstanceError
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

from core.candidate_inspection import _candidate_path
from core.candidate_record_normalization import (
    _normalize_candidate_path, _normalize_candidate_record, _normalize_candidate_records,
)
from core.comfy_output_containment import ContainedOutputStore
from core.generation_output_promotion import DurableGenerationAssets
from core.io import load_project_from_json, save_project_to_json
from ui.agent_generation_candidate_publication import GenerationCandidatePublication
from ui.agent_generation_executor_handoff import (
    capture_executor_human_start_for_characterization as capture_start,
    local_output_custody_current_for_characterization as local_current,
)
from ui.agent_generation_executor_inbox import GenerationExecutorInbox
from ui.agent_generation_job import GenerationJobRegistry, ACTIVE_TTL
from test_agent_generation_executable_manifest import host_for
from test_agent_generation_executable_review_ui import queued, prepare, confirm, identity
from test_agent_generation_comfy_executor import harness, result
from test_agent_generation_executor_handoff import start
from test_comfy_output_containment import image_bytes, successful_metadata, stream_provider, contain
from ui import project_capture_safety as capture
from functools import lru_cache


class State(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


@lru_cache(maxsize=1)
def app_nodes():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    names = {"_make_generated_candidate_record", "_append_line_generated_candidates",
             "_get_persistent_line_candidates", "_append_persistent_line_candidates",
             "_sync_line_generated_candidates_to_session", "_line_candidate_key",
             "save_agent_scene_module_swap_project"}
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names)
    return nodes


def app_owners(state):
    """Compile the actual existing app owners, without running its UI."""
    namespace = dict(st=SimpleNamespace(session_state=state), datetime=datetime, timezone=timezone,
        _normalize_candidate_path=_normalize_candidate_path, _normalize_candidate_record=_normalize_candidate_record,
        _normalize_candidate_records=_normalize_candidate_records, _candidate_path=_candidate_path,
        save_project_to_json=save_project_to_json, ensure_project_folder_layout=lambda path: None)
    exec(compile(ast.Module(body=app_nodes(), type_ignores=[]), "app.py", "exec"), namespace)
    return namespace


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(capture._streamlit_config, "get_option", lambda key: False)
    import test_agent_generation_executable_review_ui as review_test
    original_setup = review_test.setup
    json_path = str(tmp_path / "project.json")
    def setup():
        runtime, route, _, state, args = original_setup()
        state["current_project_path"] = json_path
        epoch = runtime.synchronize_target(state["project"], json_path)
        return runtime, route, epoch, State(state), args
    monkeypatch.setattr(review_test, "setup", setup)
    output = tmp_path / "durable"
    output.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    import core.comfy_output_containment as containment
    monkeypatch.setattr(containment.tempfile, "tempdir", str(staging))
    base_provider = host_for()
    def provider(p, runs):
        host = base_provider(p, runs)
        host["generation_options"]["output_directory"] = str(output)
        return host
    runtime, route, _, state, _, provider = queued(count=2, runs=2, provider=provider, with_swap=True)
    state["history"] = []
    runtime.generation_jobs = GenerationJobRegistry(characterization=True)
    runtime._generation_executor_inbox = GenerationExecutorInbox(characterization=True)
    runtime.synchronize_target(state["project"], state["current_project_path"])
    assert prepare(state, runtime, provider, *identity(runtime), random_u64=lambda: 0) == "certified"
    held = runtime._executable_review
    assert confirm(state, runtime, provider, held) == "confirmed"
    values = (runtime, route, state, provider, held, capture_start(runtime))
    images = [{"filename": f"REMOTE-{i}.png", "subfolder": "REMOTE/FOLDER", "type": "output"} for i in range(2)]
    values, adapter, sent = harness(values, provider=lambda p, prompt: result(p, prompt,
        history_json=successful_metadata(prompt, images)))
    adapter._local_gate = lambda e, r, l: local_current(state, runtime, e, r, l)
    accepted = start(values, adapter.accept_and_run_for_characterization)
    store = ContainedOutputStore.create_for_characterization(characterization=True)
    assert contain(adapter, store, stream_provider(image_bytes())).status == "local_outputs_ready"
    owners = app_owners(state)
    publisher = GenerationCandidatePublication.create_for_characterization(state, runtime, adapter._envelope,
        approved_directory=str(output), candidate_factory=owners["_make_generated_candidate_record"],
        candidate_appender=owners["_append_line_generated_candidates"],
        save_project=owners["save_agent_scene_module_swap_project"], characterization=True)
    value = SimpleNamespace(runtime=runtime, route=route, state=state, adapter=adapter, sent=sent,
        store=store, publisher=publisher, accepted=accepted, owners=owners, output=output, tmp=tmp_path)
    with patch("urllib.request.urlopen", side_effect=AssertionError("real network")), \
         patch("core.comfyui.generate_image_with_progress", side_effect=AssertionError("real generation")):
        yield value
    runtime.close()


def publish(rig, index=None):
    index = rig.adapter._index if index is None else index
    remote = next(r for r in rig.adapter.remote_receipts() if r.request_index == index)
    local = next(r for r in rig.adapter.local_receipts() if r.request_index == index)
    return rig.publisher.publish_for_characterization(rig.store, remote, local)


def finish(rig):
    receipts = []
    for index in range(4):
        receipts.append(publish(rig))
        assert receipts[-1].registration_state == "registered"
        rig.adapter.advance_for_characterization()
        if index < 3:
            assert contain(rig.adapter, rig.store, stream_provider(image_bytes())).status == "local_outputs_ready"
    return receipts


def test_multi_image_multi_run_order_metadata_persistence_and_undo(rig):
    original = copy.deepcopy(rig.state["project"])
    swap = rig.runtime.inspect_review_custody()
    seed_policy = rig.adapter._envelope.manifest.seed_policy
    assert seed_policy == "random_u64"
    receipts = finish(rig)
    assert rig.publisher._origin.source_snapshot == original
    assert [r.registered_count for r in receipts] == [2, 2, 2, 2]
    assert rig.runtime.inspect_review_custody() == swap
    assert rig.runtime.generation_review_custodian.inspect()["state"] != "pending"
    assert rig.runtime.mailbox.state != "reply_ready"
    project = rig.state["project"]
    assert [l.id for l in project.prompt_lines] == [l.id for l in original.prompt_lines]
    for line, before in zip(project.prompt_lines[1:], original.prompt_lines[1:]):
        assert line.current_text == before.current_text and line.negative_prompt == before.negative_prompt
        assert line.image_path == before.image_path
        records = line.generated_candidates
        assert [r["run_index"] for r in records] == [1, 1, 2, 2]
        assert [r["generation_provenance"]["output_index"] for r in records] == [1, 2, 1, 2]
        assert all(r["prompt_text"] == "red" and r["seed_mode"] == "frozen_execution" for r in records)
        assert all(r["candidate_prompt_source"] == "frozen_execution" for r in records)
        assert all(Path(r["path"]).is_relative_to(rig.output) for r in records)
        assert all(not Path(r["path"]).is_relative_to(rig.store._root) for r in records)
        assert all("REMOTE" not in r["path"] and Path(r["path"]).read_bytes() == image_bytes() for r in records)
        assert rig.state["line_generated_candidates"][line.id] == records
    assert [r["seed"] for r in project.prompt_lines[1].generated_candidates] == [0, 0, 2, 2]
    assert len(rig.state["history"]) == 4 and rig.state["history"][0] == original
    assert rig.publisher.save_for_characterization() == "saved"
    reopened = load_project_from_json(rig.state["current_project_path"])
    for restored, active in zip(reopened.prompt_lines, project.prompt_lines):
        for persisted, record in zip(restored.generated_candidates, active.generated_candidates):
            assert Path(rig.state["current_project_path"]).parent.joinpath(persisted["path"]) == Path(record["path"])
            assert {k: v for k, v in persisted.items() if k != "path"} == {k: v for k, v in record.items() if k != "path"}
    assert reopened.module_library == project.module_library
    assert rig.runtime.generation_jobs.snapshot(rig.accepted.job_id)["save_state"] == "saved"
    assert publish(rig, 0) == receipts[0]  # does not replay after terminal/save
    assert rig.publisher.save_for_characterization() == "saved"
    assert len(rig.sent) == 4 and not rig.publisher.execution_available
    with pytest.raises(FrozenInstanceError): receipts[0].registered_count = 0


def test_duplicate_concurrent_publication_and_exact_receipt_identity(rig):
    entered, release = Event(), Event()
    original = rig.publisher._assets.promote_for_characterization
    def blocked(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    with patch.object(rig.publisher._assets, "promote_for_characterization", side_effect=blocked):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(publish, rig)
            assert entered.wait(10)
            second = pool.submit(publish, rig).result(10)
            assert second.registration_state == "publication_in_progress"
            assert rig.publisher.save_for_characterization() == "publication_busy"
            release.set()
            receipt = first.result(10)
    assert receipt.registration_state == "registered"
    assert publish(rig) == receipt and len(rig.publisher._assets._retained) == 2
    remote, local = rig.adapter.remote_receipts()[0], rig.adapter.local_receipts()[0]
    assert rig.publisher.publish_for_characterization(rig.store, remote, replace(local)).registration_state == "receipt_conflict"


@pytest.mark.parametrize("when", ["before", "during_promotion", "factory", "before_commit"])
@pytest.mark.parametrize("drift", ["path", "project", "switch_back", "pairing", "prompt", "module", "route", "image", "disarm", "close", "expiry", "session", "process"])
def test_original_host_and_source_drift_at_boundaries_never_appends(rig, when, drift, monkeypatch):
    source = rig.state["project"]
    changed = False
    def change():
        nonlocal changed
        if changed:
            return
        changed = True
        if drift == "path": rig.state["current_project_path"] += ".other"
        elif drift == "project": rig.state["project"] = copy.deepcopy(source)
        elif drift == "switch_back":
            rig.runtime.synchronize_target(copy.deepcopy(source), "other")
            rig.runtime.synchronize_target(source, rig.state["current_project_path"])
        elif drift == "pairing":
            rig.route.release()
            offer = rig.runtime.arm_local_pairing().bootstrap
            assert rig.runtime._registry.claim_pairing(offer.process_incarnation,
                offer.route_id, offer.capability).status == "paired"
        elif drift == "prompt": source.prompt_lines[1].current_text += " changed"
        elif drift == "module": source.module_library["source"]["body"] = "changed"
        elif drift == "route": source.prompt_lines.reverse()
        elif drift == "image": source.prompt_lines[1].image_path = "changed.png"
        elif drift == "disarm": rig.runtime.disarm_launcher_rendezvous()
        elif drift == "expiry": rig.runtime.generation_jobs._clock = lambda: 10**12
        elif drift == "session": rig.runtime.generation_jobs._session_incarnation = "0" * 32
        elif drift == "process":
            import ui.agent_generation_candidate_publication as publication
            monkeypatch.setattr(publication, "_PROCESS_INCARNATION", "changed-process")
        else: rig.runtime.close()
    if when == "before":
        change()
        receipt = publish(rig)
    else:
        method = ("promote_for_characterization" if when == "during_promotion" else
                  "revalidate_for_characterization" if when == "before_commit" else None)
        if method:
            original = getattr(rig.publisher._assets, method)
            def hook(*args):
                result = original(*args)
                change()
                return result
            with patch.object(rig.publisher._assets, method, side_effect=hook): receipt = publish(rig)
        else:
            factory = rig.publisher._factory
            def hook(*args):
                record = factory(*args)
                change()
                return record
            rig.publisher._factory = hook
            receipt = publish(rig)
    assert receipt.registration_state in {"stale_original_host", "registration_failed"}
    assert all(not line.generated_candidates for line in source.prompt_lines)
    assert not rig.state["history"] and rig.publisher.save_for_characterization() == "registration_incomplete"
    assert len(rig.sent) == 1


@pytest.mark.parametrize("damage", ["local_bytes", "local_identity", "promoted_bytes", "root_identity", "partial_copy"])
def test_corrupt_unsafe_or_partial_promotion_is_pinned_and_retained(rig, damage):
    local = rig.adapter.local_receipts()[0]
    source = rig.store._storage[local.images[0].storage_identity][0]
    if damage == "local_bytes": source.write_bytes(b"changed")
    elif damage == "local_identity":
        data = source.read_bytes()
        source.unlink()
        source.write_bytes(data)
    elif damage == "root_identity":
        root = rig.publisher._assets._root
        root.rename(root.with_name(root.name + "-retained"))
        root.mkdir()
    if damage in {"promoted_bytes", "partial_copy"}:
        original = rig.publisher._assets.revalidate_for_characterization
        def corrupt(images):
            Path(images[0].path).write_bytes(b"changed")
            return original(images)
        target = (patch.object(rig.publisher._assets, "revalidate_for_characterization", side_effect=corrupt)
                  if damage == "promoted_bytes" else
                  patch("core.generation_output_promotion.os.fsync", side_effect=OSError("PRIVATE_EXCEPTION")))
        with target: receipt = publish(rig)
    else: receipt = publish(rig)
    assert receipt.registration_state == "registration_failed" and receipt.promotion_state == "promotion_failed"
    assert publish(rig) == receipt
    assert all(not line.generated_candidates for line in rig.state["project"].prompt_lines)
    assert source.exists() and not rig.state["history"]
    assert "PRIVATE_EXCEPTION" not in repr(receipt)
    if damage in {"promoted_bytes", "partial_copy"}: assert rig.publisher._assets._retained


@pytest.mark.parametrize("count", [0, 1, 2])
def test_appender_exception_reports_observed_partial_registration_without_replay(rig, count):
    original = rig.publisher._appender
    def fail(line, records):
        original(line, records[:count])
        raise RuntimeError("private exception after append")
    rig.publisher._appender = fail
    receipt = publish(rig)
    assert receipt.registration_state == "registration_uncertain" and receipt.registered_count == count
    assert len(rig.state["project"].prompt_lines[1].generated_candidates) == count
    assert len(rig.state["history"]) == bool(count)
    assert rig.runtime.generation_jobs.snapshot(rig.accepted.job_id)["registered_count"] == count
    assert publish(rig) == receipt and len(rig.publisher._assets._retained) == 2
    assert rig.publisher.save_for_characterization() in {"registration_incomplete", "registration_uncertain"}


@pytest.mark.parametrize("outcome", ["saved", "save_failed", "save_uncertain", "switch", "source_drift", "close", "layout_failure"])
def test_exact_save_outcomes_concurrency_and_no_retry(rig, outcome):
    finish(rig)
    calls = []
    source, path = rig.state["project"], rig.state["current_project_path"]
    original = rig.publisher._save
    entered, release = Event(), Event()
    def save(project, project_path, reason):
        assert project is source and project_path == path
        calls.append((project, project_path))
        entered.set()
        assert release.wait(10)
        if outcome == "save_failed": return False
        if outcome == "save_uncertain":
            original(project, project_path, reason)
            raise RuntimeError("after replace uncertainty")
        result = original(project, project_path, reason)
        if outcome == "switch": rig.state["project"] = copy.deepcopy(source)
        if outcome == "source_drift": source.prompt_lines[1].current_text = "after save"
        if outcome == "close": rig.runtime.close()
        return result
    if outcome == "layout_failure":
        rig.owners["ensure_project_folder_layout"] = lambda p: (_ for _ in ()).throw(OSError("layout"))
        rig.owners["st"].warning = lambda text: None
    rig.publisher._save = save
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(rig.publisher.save_for_characterization)
        assert entered.wait(10)
        assert pool.submit(rig.publisher.save_for_characterization).result(10) == "saving"
        release.set()
        actual = first.result(10)
    expected = "save_uncertain" if outcome in {"switch", "close", "source_drift", "save_uncertain"} else (
        "save_failed" if outcome == "save_failed" else "saved")
    assert actual == expected and rig.publisher.save_for_characterization() == expected and len(calls) == 1
    assert len(source.prompt_lines[1].generated_candidates) == 4
    if outcome != "save_failed": assert Path(path).exists()


def test_io_callbacks_and_hashing_are_outside_owner_locks(rig):
    runtime = rig.runtime
    route = runtime._registry._record_for_registration(runtime._registration)
    locks = [runtime._publication_gate, route.operation_lock, runtime.generation_jobs._lock,
             runtime._generation_executor_inbox._lock, runtime.mailbox._lock]
    def unlocked(*args):
        assert all(not (lock._is_owned() if hasattr(lock, "_is_owned") else lock.locked()) for lock in locks)
    original = rig.publisher._assets.promote_for_characterization
    def promote(*args):
        unlocked()
        return original(*args)
    with patch.object(rig.publisher._assets, "promote_for_characterization", side_effect=promote): finish(rig)
    original_save = rig.publisher._save
    def save(*args):
        unlocked()
        return original_save(*args)
    rig.publisher._save = save
    assert rig.publisher.save_for_characterization() == "saved"


def test_factory_changes_source_image_then_appender_never_runs(rig):
    factory = rig.publisher._factory
    def mutate(*args):
        record = factory(*args)
        rig.state["project"].prompt_lines[1].image_path = "changed"
        return record
    rig.publisher._factory = mutate
    with patch.object(rig.publisher, "_appender") as append:
        assert publish(rig).registration_state == "stale_original_host"
        append.assert_not_called()


def test_factory_frozen_prompt_unavailable_never_uses_current_text(rig):
    # Multi-binding text cannot be flattened without changing its meaning.
    review = json.loads(rig.publisher._origin.review_json)
    review["requests"][0]["prompts"] = [{"role": "positive", "text": "first"}, {"role": "positive", "text": "second"}]
    # This is private fixture evidence, not authority forged by a public caller.
    object.__setattr__(rig.publisher._origin, "review_json", json.dumps(review).encode())
    assert publish(rig).registration_state == "registered"
    records = rig.state["project"].prompt_lines[1].generated_candidates
    assert all(r["prompt_text"] is None and r["negative_prompt"] is None for r in records)
    assert all(r["generation_provenance"]["prompt_available"] is False for r in records)


def test_production_gate_and_wrong_destination_owner_are_unavailable(rig):
    with pytest.raises(ValueError, match="execution_unavailable"):
        DurableGenerationAssets.create_for_characterization(str(rig.output))
    with pytest.raises(ValueError, match="execution_unavailable"):
        GenerationCandidatePublication.create_for_characterization(rig.state, rig.runtime, rig.adapter._envelope,
            approved_directory=str(rig.output), candidate_factory=lambda: None, candidate_appender=lambda: None,
            save_project=lambda: None)
    with pytest.raises(ValueError, match="destination_not_approved"):
        GenerationCandidatePublication.create_for_characterization(rig.state, rig.runtime, rig.adapter._envelope,
            approved_directory=str(rig.tmp), candidate_factory=lambda: None, candidate_appender=lambda: None,
            save_project=lambda: None, characterization=True)
    with pytest.raises(ValueError, match="publication_owner_exists"):
        GenerationCandidatePublication.create_for_characterization(rig.state, rig.runtime, rig.adapter._envelope,
            approved_directory=str(rig.output), candidate_factory=lambda: None, candidate_appender=lambda: None,
            save_project=lambda: None, characterization=True)
    assert rig.publisher.save_for_characterization() == "registration_incomplete"


def test_private_origin_never_leaves_host_in_worker_or_job(rig):
    envelope = rig.adapter._envelope
    assert rig.runtime._generation_publication_origin.envelope is envelope
    assert not any(hasattr(envelope, name) for name in ("original_project", "project", "original_path",
                                                      "source_snapshot", "review_json"))
    snapshot = rig.runtime.generation_jobs.snapshot(rig.accepted.job_id)
    assert rig.state["current_project_path"] not in repr(snapshot)
    assert str(rig.output) not in repr(snapshot)


def test_publication_preserves_pending_scene_swap_and_its_ack(rig):
    from core import agent_facade
    from ui.project_agent_session_pump import service_project_agent_session_request
    runtime, state = rig.runtime, rig.state
    intent = {"scene_id": "scene", "source_module_name": "source", "target_module_name": "target", "match_mode": "strict"}
    preview = agent_facade.preview_scene_module_swap(state["project"], intent)
    epoch = runtime.synchronize_target(state["project"], state["current_project_path"])
    assert rig.route.submit(epoch, {"request_id": "swap", "tool": "promptgraph_request_scene_module_swap_review",
        "arguments": {**intent, "expected_plan_id": preview["plan_id"]}}).status == "accepted"
    token = capture.begin_project_capture_run(state)
    assert service_project_agent_session_request(runtime, state, token) == "completed"
    before = runtime.inspect_review_custody()
    assert before["state"] == "pending" and runtime.mailbox.state == "reply_ready"
    assert publish(rig).registration_state == "registered"
    assert runtime.inspect_review_custody() == before and runtime.mailbox.state == "reply_ready"
    assert rig.route.consume_reply(epoch).reply["result"]["status"] == "queued_for_review"


def test_exclusive_destination_never_overwrites_existing_file(rig):
    existing = rig.publisher._assets._root / ("f" * 32 + ".png")
    existing.write_bytes(b"existing asset")
    with patch("core.generation_output_promotion.uuid.uuid4", return_value=SimpleNamespace(hex="f" * 32)):
        receipt = publish(rig)
    assert receipt.promotion_state == "promotion_failed" and existing.read_bytes() == b"existing asset"
    assert not rig.state["project"].prompt_lines[1].generated_candidates


def test_symlink_approved_directory_is_refused(rig):
    link = rig.tmp / "linked-output"
    try:
        os.symlink(rig.output, link, target_is_directory=True)
    except OSError:
        pytest.skip("Windows host does not permit disposable symlink creation")
    with pytest.raises(ValueError, match="unsafe_destination"):
        DurableGenerationAssets.create_for_characterization(str(link), characterization=True)


def test_asset_corruption_before_save_prevents_json_write(rig):
    finish(rig)
    candidate = rig.state["project"].prompt_lines[1].generated_candidates[0]
    Path(candidate["path"]).write_bytes(b"corrupt after registration")
    with patch.object(rig.publisher, "_save") as save:
        assert rig.publisher.save_for_characterization() == "save_not_authorized"
        save.assert_not_called()
    assert not Path(rig.state["current_project_path"]).exists()
    assert rig.runtime.generation_jobs.snapshot(rig.accepted.job_id)["registered_count"] == 8


def test_source_drift_during_appender_keeps_observed_count_uncertain(rig):
    appender = rig.publisher._appender
    def drift(line, records):
        appender(line, records)
        line.current_text = "unexpected mutation"
    rig.publisher._appender = drift
    receipt = publish(rig)
    assert receipt.registration_state == "registration_uncertain" and receipt.registered_count == 2
    assert len(rig.state["history"]) == 1 and publish(rig) == receipt


def test_pairing_inspection_failure_after_append_preserves_truthful_observed_count(rig):
    appender = rig.publisher._appender
    registration = type(rig.runtime._registration)
    with patch.object(registration, "inspect_pairing_generation", wraps=rig.runtime._registration.inspect_pairing_generation) as inspect:
        def append(line, records):
            appender(line, records)
            inspect.side_effect = OSError("pairing read unavailable")
        rig.publisher._appender = append
        receipt = publish(rig)
    assert receipt.registration_state == "registration_uncertain" and receipt.registered_count == 2
    assert len(rig.state["project"].prompt_lines[1].generated_candidates) == 2
    assert publish(rig) == receipt and len(rig.state["history"]) == 1


def test_pairing_inspection_failure_after_save_is_uncertain_with_callback_evidence(rig):
    finish(rig)
    save = rig.publisher._save
    registration = type(rig.runtime._registration)
    with patch.object(registration, "inspect_pairing_generation", wraps=rig.runtime._registration.inspect_pairing_generation) as inspect:
        def callback(*args):
            result = save(*args)
            inspect.side_effect = OSError("pairing read unavailable")
            return result
        rig.publisher._save = callback
        assert rig.publisher.save_for_characterization() == "save_uncertain"
    assert rig.publisher._save_callback_outcome == "saved"
    assert Path(rig.state["current_project_path"]).exists()
    assert rig.publisher.save_for_characterization() == "save_uncertain"


def test_nested_registered_provenance_drift_cannot_modify_expected_source(rig):
    assert publish(rig).registration_state == "registered"
    candidate = rig.state["project"].prompt_lines[1].generated_candidates[0]
    candidate["generation_provenance"]["prompts"][0]["text"] = "edited provenance"
    rig.adapter.advance_for_characterization()
    assert contain(rig.adapter, rig.store, stream_provider(image_bytes())).status == "local_outputs_ready"
    assert publish(rig).registration_state == "stale_original_host"
    assert len(rig.state["project"].prompt_lines[1].generated_candidates) == 2
