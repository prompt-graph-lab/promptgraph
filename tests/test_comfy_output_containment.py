"""C2B-5 fake streams + temporary files; never network, workers or publication."""
import copy
from dataclasses import FrozenInstanceError, replace
import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageFile
import pytest

from core import comfy_output_containment as owner
from core.comfy_output_containment import ContainedOutputStore, ContainmentLimits, DownloadStream
from core.comfy_remote_output_receipts import validate_remote_outputs
from ui.agent_generation_executor_handoff import local_output_custody_current_for_characterization as current
from test_agent_generation_comfy_executor import harness, metadata, result, raw
from test_agent_generation_executor_handoff import start


def image_bytes(fmt="PNG", size=(17, 23)):
    output = io.BytesIO()
    Image.new("RGB", size, "red").save(output, format=fmt)
    return output.getvalue()


def successful_metadata(prompt, images=None, *, success=True):
    history = json.loads(metadata(prompt, images=images))
    if success:
        history[prompt]["status"] = {"completed": True, "status_str": "success"}
    return raw(history)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(owner.tempfile, "tempdir", str(tmp_path))
    return ContainedOutputStore.create_for_characterization(characterization=True)


def running(*, images=None, success=True):
    values, adapter, sent = harness(provider=lambda p, prompt: result(p, prompt,
        history_json=successful_metadata(prompt, images, success=success)))
    runtime, _, state, *_ = values
    adapter._local_gate = lambda envelope, remote, local: current(state, runtime, envelope, remote, local)
    accepted = start(values, adapter.accept_and_run_for_characterization)
    return values, adapter, sent, accepted


def stream_provider(data, calls=None, *, declared=None, read_hook=None):
    def provider(lookup):
        if calls is not None:
            calls.append(lookup)
        source = io.BytesIO(data(lookup) if callable(data) else data)
        length = len(source.getvalue()) if declared is None else declared
        def read(limit):
            assert 0 < limit <= owner.CHUNK_BYTES
            if read_hook:
                read_hook(limit)
            return source.read(limit)
        return DownloadStream(length, read, source.close)
    return provider


def contain(adapter, store, provider):
    return adapter.contain_local_outputs_for_characterization(store, fake_stream_provider=provider)


@pytest.mark.parametrize("fmt,extension", [("PNG", "png"), ("JPEG", "jpg"), ("JPEG", "jpeg"),
                                           ("WEBP", "webp"), ("BMP", "bmp")])
def test_verified_image_hash_dimensions_private_names_and_no_mutation(store, fmt, extension):
    data, calls = image_bytes(fmt), []
    images = [{"filename": f"PRIVATE_REMOTE.{extension}", "subfolder": "PRIVATE/subfolder", "type": "output"}]
    values, adapter, sent, accepted = running(images=images)
    runtime, _, state, *_ = values
    before = copy.deepcopy(state)
    bomb_limit, truncation = Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES
    locks = [runtime._publication_gate, runtime.mailbox._lock, runtime.generation_review_custodian._lock,
             runtime.generation_jobs._lock, runtime._generation_executor_inbox._lock]
    def unlocked(limit):
        assert not any(lock._is_owned() if hasattr(lock, "_is_owned") else lock.locked() for lock in locks)
    original_verify = store._verify
    def verify(*args):
        unlocked(1)
        return original_verify(*args)
    with patch.object(store, "_verify", side_effect=verify), \
         patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
         patch("threading.Thread.start", side_effect=AssertionError("worker")), \
         patch("core.gallery_generation.ingest_gallery_generation_outputs", side_effect=AssertionError("publication")):
        outcome = contain(adapter, store, stream_provider(data, calls, read_hook=unlocked))
    assert outcome.status == "local_outputs_ready"
    local = adapter.local_receipts()[0]
    assert local.state == "verified" and local.verified_count == local.downloaded_count == 1
    image = local.images[0]
    assert (image.width, image.height, image.image_format) == (17, 23, fmt)
    assert image.content_sha256 == hashlib.sha256(data).hexdigest() and image.byte_count == len(data)
    assert len(calls) == 1 and calls[0].endpoint_origin == "http://PRIVATE_ENDPOINT"
    assert calls[0].filename == images[0]["filename"] and calls[0].bucket == "output"
    assert not hasattr(calls[0], "destination") and not hasattr(local, "path")
    path = store._storage[image.storage_identity][0]
    assert path.read_bytes() == data and path.parent.parent == store._root
    assert "PRIVATE" not in str(path) and path.name == image.storage_identity
    snapshot = runtime.generation_jobs.snapshot(accepted.job_id)
    assert snapshot["requests"][0]["state"] == "awaiting_host_registration"
    assert snapshot["output_count"] == 1 and snapshot["registered_count"] == 0
    assert snapshot["save_state"] == "not_attempted" and state == before
    assert not adapter.execution_available and not store.execution_available
    assert not any(private in repr(snapshot) for private in (str(store._root), "PRIVATE", image.content_sha256))
    assert Image.MAX_IMAGE_PIXELS == bomb_limit and ImageFile.LOAD_TRUNCATED_IMAGES == truncation
    assert len(sent) == 1
    with pytest.raises(FrozenInstanceError): image.width = 2
    with pytest.raises(FrozenInstanceError): local.state = "published"
    runtime.close()
    assert path.exists()  # no scope/session finalizer removes remote evidence


def test_statusless_remote_metadata_alone_never_downloads_or_advances(store):
    values, adapter, sent, accepted = running(success=False)
    assert adapter.remote_receipts()[0].execution_succeeded is False
    calls = []
    assert contain(adapter, store, stream_provider(image_bytes(), calls)).status == "local_outputs_quarantined"
    local = adapter.local_receipts()[0]
    assert local.failure_code == "execution_success_unproven" and not local.images
    assert not calls and not list(store._root.iterdir())
    assert values[0].generation_jobs.snapshot(accepted.job_id)["requests"][0]["state"] == "awaiting_download"
    assert values[0].generation_jobs.snapshot(accepted.job_id)["output_count"] == 0
    adapter.advance_for_characterization()
    assert len(sent) == 1
    values[0].close()


def test_multi_image_atomic_receipt_multi_run_correlation_no_second_download(store):
    images = [{"filename": f"remote{i}.png", "subfolder": "", "type": "output"} for i in range(3)]
    values, adapter, sent, accepted = running(images=images)
    runtime, _, state, *_ = values
    calls, locals = [], []
    for index in range(4):
        provider = stream_provider(lambda lookup: image_bytes(size=(18 + index, 24)), calls)
        assert contain(adapter, store, provider).status == "local_outputs_ready"
        local = adapter.local_receipts()[-1]
        locals.append(local)
        assert local.request_index == index and local.request_id == sent[index].request_id
        assert local.workflow_identity == sent[index].workflow_identity
        assert local.remote_receipt_identity == adapter.remote_receipts()[-1].identity
        assert local.verified_count == 3 and len(set(i.storage_identity for i in local.images)) == 3
        snapshot = runtime.generation_jobs.snapshot(accepted.job_id)
        assert snapshot["output_count"] == 3 * (index + 1)
        assert contain(adapter, store, provider).status == "duplicate_local_receipt"
        assert len(calls) == 3 * (index + 1)
        adapter.advance_for_characterization()
        assert len(sent) == index + 1  # local verification alone cannot publish/advance
        assert runtime.generation_jobs.publication_for_characterization(accepted.job_id, accepted.claim_id,
            binding=adapter._envelope.binding, request_index=index, registered_count=3) == "accepted"
        adapter.advance_for_characterization()  # registry counts only, no Candidate writes
    assert len(set(r.identity for r in locals)) == 4
    assert len(set(r.prompt_id for r in locals)) == 4
    assert len(set(i.storage_identity for r in locals for i in r.images)) == 12
    runtime.close()


@pytest.mark.parametrize("case", ["empty", "truncated", "corrupt", "mismatch", "oversized", "short", "overrun",
                                 "animated", "gif", "dimension", "pixels", "bomb", "relaxed_truncation"])
def test_invalid_bytes_never_become_local_success(store, case, monkeypatch):
    extension, data, declared = "png", image_bytes(), None
    if case == "empty": data = b""
    elif case == "truncated": data = data[:40]
    elif case == "corrupt": data = b"corrupt image"
    elif case == "mismatch": data = image_bytes("JPEG")
    elif case == "oversized": declared = store._limits.image_bytes + 1
    elif case == "short": declared = len(data) + 1
    elif case == "overrun": declared = len(data) - 1
    elif case == "gif": extension, data = "gif", image_bytes("GIF")
    elif case == "animated":
        source = io.BytesIO()
        Image.new("RGB", (20, 20), "red").save(source, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (20, 20), "blue")])
        data = source.getvalue()
    elif case == "dimension": store._limits = replace(store._limits, dimension=16)
    elif case == "pixels": store._limits = replace(store._limits, pixels=17 * 23 - 1)
    elif case == "bomb":
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    else: monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    images = [{"filename": f"remote.{extension}", "subfolder": "", "type": "output"}]
    values, adapter, sent, accepted = running(images=images)
    assert contain(adapter, store, stream_provider(data, declared=declared)).status in {
        "local_outputs_incomplete", "local_outputs_quarantined"}
    local = adapter.local_receipts()[0]
    assert local.state != "verified" and local.verified_count == 0
    assert values[0].generation_jobs.snapshot(accepted.job_id)["output_count"] == 0
    assert len(sent) == 1
    values[0].close()


def test_interruption_cleans_only_partial_bytes_and_pins_attempt(store):
    values, adapter, _, accepted = running()
    calls, closes = [], []
    def provider(lookup):
        calls.append(lookup)
        reads = []
        def read(limit):
            if reads: raise OSError("PRIVATE_PATH_URL")
            reads.append(limit)
            return b"partial"
        return DownloadStream(100, read, lambda: closes.append(True))
    assert contain(adapter, store, provider).status == "local_outputs_incomplete"
    local = adapter.local_receipts()[0]
    assert local.failure_code == "download_interrupted" and not local.retained_storage_identities
    assert not any(p.is_file() for p in store._root.rglob("*")) and store._used_bytes == 0
    assert contain(adapter, store, provider).status == "duplicate_local_receipt"
    assert len(calls) == len(closes) == 1
    assert "PRIVATE" not in repr(local)
    values[0].close()


def test_partial_batch_is_quarantined_atomic_and_retains_complete_evidence(store):
    images = [{"filename": f"remote{i}.png", "subfolder": "", "type": "output"} for i in range(2)]
    values, adapter, _, accepted = running(images=images)
    calls = []
    def data(lookup):
        return image_bytes() if len(calls) == 1 else b"broken"
    assert contain(adapter, store, stream_provider(data, calls)).status == "local_outputs_quarantined"
    local = adapter.local_receipts()[0]
    assert local.downloaded_count == 2 and local.verified_count == 1 and local.state == "quarantined"
    assert len(local.retained_storage_identities) == 2
    assert len([p for p in store._root.rglob("*") if p.is_file()]) == 2
    assert values[0].generation_jobs.snapshot(accepted.job_id)["output_count"] == 0
    values[0].close()


@pytest.mark.parametrize("invalidation", ["switch", "save_as", "pairing", "disarm", "close", "expiry", "session"])
def test_invalidated_during_io_keeps_verified_evidence_quarantined_no_authority(store, invalidation):
    values, adapter, sent, accepted = running()
    runtime, route, state, *_ = values
    original_project, original_path = state["project"], state["current_project_path"]
    changed = []
    def invalidate(limit):
        if changed: return
        changed.append(True)
        if invalidation == "switch": state["project"] = copy.deepcopy(state["project"])
        elif invalidation == "save_as": state["current_project_path"] = "SAVE_AS"
        elif invalidation == "pairing":
            route.release()
            bootstrap = runtime.arm_local_pairing().bootstrap
            assert runtime._registry.claim_pairing(bootstrap.process_incarnation, bootstrap.route_id,
                bootstrap.capability).status == "paired"
        elif invalidation == "disarm": runtime.disarm_launcher_rendezvous()
        elif invalidation == "close": runtime.close()
        elif invalidation == "expiry": runtime.generation_jobs._clock = lambda: 10**12
        else: runtime.generation_jobs._session_incarnation = "0" * 32
    assert contain(adapter, store, stream_provider(image_bytes(), read_hook=invalidate)).status == "local_outputs_quarantined"
    local = adapter.local_receipts()[0]
    assert local.state == "quarantined" and local.verified_count == 1
    path = store._storage[local.images[0].storage_identity][0]
    assert path.exists() and path.read_bytes() == image_bytes()
    snapshot = runtime.generation_jobs.snapshot(accepted.job_id)
    assert snapshot.get("output_count", 0) == snapshot.get("registered_count", 0) == 0
    state["project"], state["current_project_path"] = original_project, original_path
    runtime.synchronize_target(original_project, original_path)
    assert not current(state, runtime, adapter._envelope, adapter.remote_receipts()[0], local)
    adapter.advance_for_characterization()
    contain(adapter, store, stream_provider(b"new content"))
    assert len(sent) == 1 and path.exists()
    runtime.close()


def test_stale_before_download_blocks_provider(store):
    values, adapter, _, accepted = running()
    values[2]["current_project_path"] = "SAVE_AS"
    calls = []
    assert contain(adapter, store, stream_provider(image_bytes(), calls)).status == "host_invalidated"
    assert not calls and not list(store._root.iterdir())
    values[0].close()


def test_preexisting_generated_destination_never_overwrites(store, monkeypatch):
    values, adapter, _, _ = running()
    class Fixed:
        hex = "a" * 32
    monkeypatch.setattr(owner.uuid, "uuid4", lambda: Fixed())
    existing = store._root / Fixed.hex
    existing.mkdir()
    sentinel = existing / "sentinel"
    sentinel.write_bytes(b"preserve")
    calls = []
    assert contain(adapter, store, stream_provider(image_bytes(), calls)).status == "local_outputs_incomplete"
    assert sentinel.read_bytes() == b"preserve" and not calls
    values[0].close()


def test_preexisting_file_exclusive_creation(store, monkeypatch):
    values, adapter, _, _ = running()
    original = owner.os.open
    paths = []
    def preexisting(path, flags, mode):
        Path(path).write_bytes(b"preserve")
        paths.append(path)
        return original(path, flags, mode)
    monkeypatch.setattr(owner.os, "open", preexisting)
    assert contain(adapter, store, stream_provider(image_bytes())).status == "local_outputs_incomplete"
    assert Path(paths[0]).read_bytes() == b"preserve"
    values[0].close()


def test_reparse_root_and_postwrite_escape_fenced_without_unsafe_cleanup(store, monkeypatch):
    values, adapter, _, _ = running()
    original = owner._ordinary
    def reparse(path, *, directory):
        if Path(path) == store._root:
            raise owner._ContainmentFailure("unsafe_storage")
        return original(path, directory=directory)
    monkeypatch.setattr(owner, "_ordinary", reparse)
    calls = []
    assert contain(adapter, store, stream_provider(image_bytes(), calls)).status == "local_outputs_incomplete"
    assert not calls
    values[0].close()


def test_root_identity_replacement_and_symlink_parent_rejected(store, tmp_path):
    values, adapter, _, _ = running()
    original_root = store._root
    original_root.rename(original_root.with_name(original_root.name + "-original"))
    original_root.mkdir()
    calls = []
    assert contain(adapter, store, stream_provider(image_bytes(), calls)).status == "local_outputs_incomplete"
    assert not calls
    link = tmp_path / "link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        values[0].close()
        return  # Windows without symlink privilege; reparse lstat test below covers it
    with pytest.raises(owner._ContainmentFailure): owner._ordinary(link / "child", directory=True)
    values[0].close()


def test_actual_reparse_attribute_is_rejected(tmp_path, monkeypatch):
    original = Path.lstat
    def reparse(path):
        result = original(path)
        if path == tmp_path:
            class Info:
                st_mode = result.st_mode
                st_file_attributes = 0x400
            return Info()
        return result
    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(owner._ContainmentFailure): owner._ordinary(tmp_path, directory=True)


@pytest.mark.parametrize("field,value", [("job_id", "different"), ("claim_id", "different"),
    ("manifest_identity", "0" * 64), ("request_id", "different"), ("workflow_identity", "0" * 64),
    ("prompt_id", "different"), ("identity", "0" * 64)])
def test_forged_receipt_correlation_rejected_before_io(store, field, value):
    values, adapter, sent, _ = running()
    remote = adapter.remote_receipts()[0]
    with pytest.raises(ValueError, match="remote_correlation_mismatch"):
        store.stage_for_characterization(adapter._envelope, sent[0], replace(remote, **{field: value}),
            fake_stream_provider=stream_provider(image_bytes()))
    assert not list(store._root.iterdir())
    values[0].close()


def test_conflicting_descriptor_or_content_cannot_overwrite_committed_identity(store):
    values, adapter, sent, _ = running()
    contain(adapter, store, stream_provider(image_bytes()))
    remote, local = adapter.remote_receipts()[0], adapter.local_receipts()[0]
    assert store.stage_for_characterization(adapter._envelope, sent[0], remote,
        fake_stream_provider=lambda lookup: (_ for _ in ()).throw(AssertionError("redownload"))) is local
    alternate = validate_remote_outputs(adapter._envelope, sent[0], remote.prompt_id,
        successful_metadata(remote.prompt_id, [{"filename": "another.png", "subfolder": "", "type": "output"}]))
    with pytest.raises(ValueError, match="local_receipt_conflict"):
        store.stage_for_characterization(adapter._envelope, sent[0], alternate,
            fake_stream_provider=stream_provider(image_bytes(size=(33, 22))))
    assert store._storage[local.images[0].storage_identity][0].read_bytes() == image_bytes()
    values[0].close()


def test_provider_reentry_no_duplicate_download_or_submission(store):
    values, adapter, sent, _ = running()
    calls = []
    def provider(lookup):
        calls.append(lookup)
        assert contain(adapter, store, provider).status == "local_outputs_fenced"
        adapter.advance_for_characterization()
        source = io.BytesIO(image_bytes())
        return DownloadStream(len(source.getvalue()), source.read, source.close)
    assert contain(adapter, store, provider).status == "local_outputs_ready"
    assert len(calls) == len(sent) == 1
    values[0].close()


def test_request_and_aggregate_byte_limits_are_enforced(store):
    values, adapter, sent, _ = running()
    data = image_bytes()
    store._limits = ContainmentLimits(image_bytes=len(data), request_bytes=len(data), aggregate_bytes=len(data))
    assert contain(adapter, store, stream_provider(data)).status == "local_outputs_ready"
    values[0].generation_jobs.publication_for_characterization(adapter._envelope.job_id, adapter._envelope.claim_id,
        binding=adapter._envelope.binding, request_index=0, registered_count=1)
    adapter.advance_for_characterization()
    assert contain(adapter, store, stream_provider(data)).status == "local_outputs_incomplete"
    assert adapter.local_receipts()[1].failure_code == "download_size_limit"
    assert store._used_bytes == len(data)
    values[0].close()


def test_store_factory_cannot_accept_arbitrary_directory_and_disabled_defaults():
    with pytest.raises(ValueError, match="execution_unavailable"): ContainedOutputStore.create_for_characterization()
    with pytest.raises(ValueError, match="host_storage_required"): ContainedOutputStore(Path("Project"), (), ContainmentLimits())
    with pytest.raises(TypeError): ContainedOutputStore.create_for_characterization(characterization=True, root="Project")
    with pytest.raises(ValueError): ContainedOutputStore.create_for_characterization(characterization=True,
        limits=ContainmentLimits(image_bytes=0))


def test_current_host_rejects_wrong_local_receipt_exact_correlation(store):
    values, adapter, _, _ = running()
    remote = adapter.remote_receipts()[0]
    local = store.stage_for_characterization(adapter._envelope, adapter._active_prepared, remote,
        fake_stream_provider=stream_provider(image_bytes()))
    runtime, _, state, *_ = values
    assert current(state, runtime, adapter._envelope, remote, local)
    for field, value in [("request_id", "wrong"), ("remote_receipt_identity", "0" * 64),
                         ("prompt_id", "wrong"), ("claim_id", "wrong"), ("state", "quarantined")]:
        assert not current(state, runtime, adapter._envelope, remote, replace(local, **{field: value}))
    runtime.close()


def test_committed_content_change_is_conflict_without_download_or_overwrite(store):
    values, adapter, _, _ = running()
    calls = []
    contain(adapter, store, stream_provider(image_bytes(), calls))
    local = adapter.local_receipts()[0]
    path = store._storage[local.images[0].storage_identity][0]
    path.write_bytes(image_bytes(size=(18, 24)))
    changed = path.read_bytes()
    assert contain(adapter, store, stream_provider(image_bytes(), calls)).status == "local_receipt_conflict"
    assert adapter.local_receipts()[0].state == "quarantined"
    assert path.read_bytes() == changed and len(calls) == 1
    values[0].close()


def test_post_download_root_reparse_keeps_uncertain_evidence_isolated(store, monkeypatch):
    values, adapter, _, accepted = running()
    original = owner._ordinary
    calls = []
    def data(lookup):
        def unsafe(path, *, directory):
            if Path(path) == store._root:
                raise owner._ContainmentFailure("unsafe_storage")
            return original(path, directory=directory)
        monkeypatch.setattr(owner, "_ordinary", unsafe)
        return image_bytes()
    assert contain(adapter, store, stream_provider(data, calls)).status == "local_outputs_quarantined"
    local = adapter.local_receipts()[0]
    assert local.failure_code == "unsafe_storage" and local.downloaded_count == 1
    assert len(local.retained_storage_identities) == 1 and len(calls) == 1
    assert len([p for p in store._root.rglob("*") if p.is_file()]) == 1
    assert values[0].generation_jobs.snapshot(accepted.job_id)["output_count"] == 0
    values[0].close()


@pytest.mark.parametrize("bad", ["chunk_type", "chunk_oversize", "length_type", "close_failure"])
def test_bounded_stream_contract_failure_is_safe_and_pinned(store, bad):
    values, adapter, _, accepted = running()
    data, calls = image_bytes(), []
    def provider(lookup):
        calls.append(lookup)
        source = io.BytesIO(data)
        length = "unknown" if bad == "length_type" else len(data)
        def read(limit):
            if bad == "chunk_type": return "not bytes"
            if bad == "chunk_oversize": return b"x" * (limit + 1)
            return source.read(limit)
        def close():
            source.close()
            if bad == "close_failure": raise OSError("PRIVATE")
        return DownloadStream(length, read, close)
    assert contain(adapter, store, provider).status in {"local_outputs_incomplete", "local_outputs_quarantined"}
    local = adapter.local_receipts()[0]
    assert local.failure_code in {"download_contract_invalid", "download_interrupted"}
    if bad == "close_failure":
        assert local.downloaded_count == 1 and len(local.retained_storage_identities) == 1
    assert values[0].generation_jobs.snapshot(accepted.job_id)["output_count"] == 0
    assert contain(adapter, store, provider).status == "duplicate_local_receipt" and len(calls) == 1
    values[0].close()


def test_per_request_limit_quarantines_atomic_batch(store):
    images = [{"filename": f"remote{i}.png", "subfolder": "", "type": "output"} for i in range(2)]
    values, adapter, _, accepted = running(images=images)
    data = image_bytes()
    store._limits = ContainmentLimits(image_bytes=len(data), request_bytes=len(data), aggregate_bytes=2 * len(data))
    assert contain(adapter, store, stream_provider(data)).status == "local_outputs_quarantined"
    local = adapter.local_receipts()[0]
    assert local.failure_code == "download_size_limit" and local.verified_count == 1
    assert store._used_bytes == len(data)
    assert values[0].generation_jobs.snapshot(accepted.job_id)["output_count"] == 0
    values[0].close()


def test_late_remote_receipt_is_retained_without_downloading_in_new_target(store):
    values, adapter, sent = harness(provider=lambda p, prompt: result(p, prompt, "pending"))
    runtime, _, state, *_ = values
    adapter._local_gate = lambda envelope, remote, local: current(state, runtime, envelope, remote, local)
    accepted = start(values, adapter.accept_and_run_for_characterization)
    state["current_project_path"] = "SAVE_AS"
    good = result(sent[0], adapter._active_prompt,
        history_json=successful_metadata(adapter._active_prompt))
    assert adapter.receive_result_for_characterization(good).status == "late_remote_receipt"
    calls = []
    assert contain(adapter, store, stream_provider(image_bytes(), calls)).status == "remote_receipt_required"
    assert len(adapter.late_receipts()) == 1 and not calls
    assert runtime.generation_jobs.snapshot(accepted.job_id)["output_count"] == 0
    runtime.close()


def test_atomic_batch_never_exposes_first_verified_image_as_complete(store):
    images = [{"filename": f"remote{i}.png", "subfolder": "", "type": "output"} for i in range(2)]
    values, adapter, _, accepted = running(images=images)
    seen = []
    def data(lookup):
        seen.append(lookup)
        assert store.receipts_for_characterization() == ()
        assert adapter.local_receipts() == ()
        assert values[0].generation_jobs.snapshot(accepted.job_id)["output_count"] == 0
        return image_bytes()
    assert contain(adapter, store, stream_provider(data)).status == "local_outputs_ready"
    assert len(seen) == 2
    values[0].close()


def test_missing_live_pairing_never_authorizes_old_job_download(store):
    values, adapter, _, _ = running()
    runtime = values[0]
    calls = []
    with patch.object(type(runtime._registration), "inspect_pairing_generation", return_value=(True, None)):
        assert contain(adapter, store, stream_provider(image_bytes(), calls)).status == "host_invalidated"
    assert not calls
    runtime.close()


def test_disarm_and_repair_never_restore_old_output_authority(store):
    values, adapter, _, _ = running()
    runtime, route, state, *_ = values
    old_remote = adapter.remote_receipts()[0]
    runtime.disarm_launcher_rendezvous()
    route.release()
    bootstrap = runtime.arm_local_pairing().bootstrap
    assert runtime._registry.claim_pairing(bootstrap.process_incarnation, bootstrap.route_id,
        bootstrap.capability).status == "paired"
    assert not current(state, runtime, adapter._envelope, old_remote)
    calls = []
    assert contain(adapter, store, stream_provider(image_bytes(), calls)).status == "host_invalidated"
    assert not calls
    runtime.close()


def test_pairing_release_between_post_io_gate_and_event_delivery_quarantines(store):
    values, adapter, _, accepted = running()
    runtime, route, state, *_ = values
    def release_at_seam(envelope, remote, local):
        valid = current(state, runtime, envelope, remote, local)
        if local is not None:
            assert valid
            route.release()
        return valid
    adapter._local_gate = release_at_seam
    assert contain(adapter, store, stream_provider(image_bytes())).status == "local_outputs_quarantined"
    local = adapter.local_receipts()[0]
    assert local.state == "quarantined" and local.verified_count == 1
    assert store._storage[local.images[0].storage_identity][0].exists()
    snapshot = runtime.generation_jobs.snapshot(accepted.job_id)
    assert snapshot["output_count"] == snapshot["registered_count"] == 0
    runtime.close()
