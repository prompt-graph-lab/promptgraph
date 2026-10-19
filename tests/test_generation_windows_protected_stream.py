"""Offline contracts + actual disposable native Windows staging, no network."""
import copy
from dataclasses import replace
import hashlib
import io
from pathlib import Path
import threading
import traceback
from unittest.mock import Mock, patch

import pytest

from core import generation_windows_protected_assets as a
from core import generation_windows_protected_storage as w
from core.comfy_http_view import PromptHTTPViewTransport
from core.comfy_output_containment import (
    AcceptedProtectedOutputBatch, CHUNK_BYTES, ContainmentLimits, DownloadStream,
    LocalOutputReceipt, ProtectedOutputAcceptanceCharacterization,
)
from core.generation_output_promotion import PromotedImage
from test_comfy_http_view import binding, Wire, Response
from test_comfy_output_containment import image_bytes
from test_generation_windows_protected_assets import admitted_owner, owner, assert_closed_gates
from test_generation_windows_protected_storage import native_scope, mutate_disposable_acl


def bound(extension="png", *, images=1, success=True):
    return binding(images=[{"filename": f"PRIVATE_{i}.{extension}", "subfolder": "PRIVATE/path", "type": "output"}
                           for i in range(images)], success=success)[:3]


def stage(store, values, provider, fresh=lambda envelope, remote: True, index=0):
    envelope, prepared, remote = values
    return store.stage_remote_image_for_characterization(envelope, prepared, remote, remote.images[index],
                                                        stream_provider=provider, host_freshness=fresh)


def stage_admitted(store, storage, values, provider, *, operation_id, fresh=lambda envelope, remote: True,
                   index=0, characterization=True, disposable_opt_in=True):
    envelope, prepared, remote = values
    return store.stage_remote_image_with_admission_for_characterization(
        envelope, prepared, remote, remote.images[index], admission_owner=storage,
        operation_id=operation_id, stream_provider=provider, host_freshness=fresh,
        characterization=characterization, disposable_opt_in=disposable_opt_in)


def acceptance(store, values, batch, fresh):
    return ProtectedOutputAcceptanceCharacterization.create_for_characterization(
        store, *values, batch, host_freshness=fresh,
        characterization=True, disposable_opt_in=True)


class Stream:
    def __init__(self, body, *, length=None, read=None, close=None):
        self.source = io.BytesIO(body)
        self.length = len(body) if length is None else length
        self.read_hook, self.close_hook = read, close
        self.reads, self.lookups, self.closes = [], [], 0

    def __call__(self, lookup):
        self.lookups.append(lookup)
        return DownloadStream(self.length, self.read, self.close)

    def read(self, limit):
        self.reads.append(limit)
        if self.read_hook:
            return self.read_hook(limit)
        return self.source.read(limit)

    def close(self):
        self.closes += 1
        if self.close_hook:
            self.close_hook()
        self.source.close()


@pytest.mark.parametrize("change", ["prepared_copy", "prepared_origin", "receipt", "history", "success",
                                    "descriptor_copy", "descriptor", "missing_success", "provider", "fresh"])
def test_portable_contract_rejects_before_native_or_callbacks(change):
    envelope, prepared, remote = bound(success=change != "missing_success")
    descriptor = remote.images[0]
    provider, fresh = Mock(), Mock(return_value=True)
    if change == "prepared_copy": prepared = replace(prepared)
    elif change == "prepared_origin": prepared = replace(prepared, prompt_url="http://other/prompt")
    elif change == "receipt": remote = replace(remote, claim_id="other")
    elif change == "history": remote = replace(remote, _validated_history_json=b"{}")
    elif change == "success": remote = replace(remote, execution_succeeded=False)
    elif change == "descriptor_copy": descriptor = replace(descriptor)
    elif change == "descriptor": descriptor = replace(descriptor, filename="other.png")
    elif change == "provider": provider = None
    elif change == "fresh": fresh = None
    store = object.__new__(a.WindowsProtectedAssetsCharacterization)
    with patch.object(w, "_api", side_effect=AssertionError("native IO")):
        with pytest.raises(ValueError, match="remote_correlation_mismatch"):
            store.stage_remote_image_for_characterization(envelope, prepared, remote, descriptor,
                                                          stream_provider=provider, host_freshness=fresh)
    if callable(provider): provider.assert_not_called()
    if callable(fresh): fresh.assert_not_called()


def test_portable_types_and_gates_do_not_gain_receipt_authority():
    assert not a.WindowsProtectedAssetsCharacterization.execution_available
    assert not a.WindowsProtectedAssetsCharacterization.protected_storage_available
    assert not issubclass(a.VerifiedProtectedImageObservation, (LocalOutputReceipt, PromotedImage))


def test_portable_batch_refuses_non_tuple_before_native_or_host_callback():
    values = bound()
    store = object.__new__(a.WindowsProtectedAssetsCharacterization)
    fresh = Mock(return_value=True)
    with patch.object(w, "_api", side_effect=AssertionError("native IO")):
        with pytest.raises(ValueError, match="remote_correlation_mismatch"):
            store.commit_verified_remote_image_batch_for_characterization(
                *values, [], host_freshness=fresh)
    fresh.assert_not_called()


@pytest.mark.parametrize("fmt,extension", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp"), ("BMP", "bmp")])
def test_real_native_success_exact_correlation_and_dacl_at_first_callback(owner, fmt, extension):
    store, scope, api = owner
    data, values = image_bytes(fmt), bound(extension)
    envelope, prepared, remote = values
    provider = Stream(data)
    def fault(point):
        if point == "after_file_create":
            path, handle, identity, acl = next(iter(store._files.values()))
            assert path.parent == store._roots["temporary_containment"]._path
            assert path.read_bytes() == b"" and "PRIVATE" not in path.name
            assert w._identity(handle) == identity == w._ordinary(path, directory=False)
            assert w._acl(handle, api, w._current_user(api)) == acl[0]
            assert len(acl[0]) == 1 and acl[0][0][1] == 3
            for target in (path, path.parent, scope):
                with pytest.raises(OSError):
                    target.rename(target.with_name(target.name + "-replaced"))
    store._fault = fault
    observed = stage(store, values, provider)
    image = observed.image
    assert type(observed) is a.VerifiedProtectedImageObservation
    assert (observed.job_id, observed.claim_id, observed.manifest_identity, observed.request_id,
            observed.request_index, observed.workflow_identity, observed.prompt_id,
            observed.remote_receipt_identity, observed.descriptor_identity) == (
        remote.job_id, remote.claim_id, remote.manifest_identity, prepared.request_id,
        prepared.request_index, prepared.workflow_identity, remote.prompt_id, remote.identity, remote.images[0].identity)
    assert image.purpose == "temporary_containment" and image.image_format == fmt
    assert image.content_sha256 == hashlib.sha256(data).hexdigest() and image.byte_count == len(data)
    assert store.inspect_verified_remote_image_for_characterization(observed) is observed
    assert provider.closes == 1 and all(0 < n <= CHUNK_BYTES for n in provider.reads)
    assert provider.lookups[0].descriptor_identity == observed.descriptor_identity
    assert not list(store._roots["promoted_assets"]._path.iterdir())
    assert_closed_gates(store.readiness())
    with pytest.raises(ValueError, match="already_attempted"):
        stage(store, values, provider)
    with pytest.raises(ValueError, match="image_owner_mismatch"):
        store.inspect_verified_remote_image_for_characterization(replace(observed))
    assert len(provider.lookups) == 1


def test_real_native_admitted_stream_reserves_policy_max_before_create_and_commits_actual_bytes(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    data, values = image_bytes(), bound()
    maximum = min(store._limits.image_bytes, store._limits.request_bytes,
                  store._limits.aggregate_bytes)
    snapshots = []

    def fault(boundary):
        if boundary == "after_file_create":
            assert not store._lock._is_owned() and not storage._lock._is_owned()
            row = next(item for item in storage._ledger.readiness()["roots"]
                       if item["purpose"] == "temporary_containment")
            snapshots.append((row["reserved_bytes"], row["reserved_entries"],
                              row["observed_used_bytes"], row["observed_used_entries"]))

    provider_source = io.BytesIO(data)
    def read(limit):
        assert not store._lock._is_owned() and not storage._lock._is_owned()
        return provider_source.read(limit)
    def close():
        assert not store._lock._is_owned() and not storage._lock._is_owned()
    provider = Stream(data, read=read, close=close)
    original_provider = provider.__call__

    def provide(lookup):
        assert not store._lock._is_owned() and not storage._lock._is_owned()
        row = next(item for item in storage._ledger.readiness()["roots"]
                   if item["purpose"] == "temporary_containment")
        assert (row["reserved_bytes"], row["reserved_entries"]) == (maximum, 1)
        return original_provider(lookup)

    store._fault = fault
    native_api = store._roots["temporary_containment"]._api[2]
    create_file = native_api.CreateFile
    before_create = []
    staging_root = store._roots["temporary_containment"]._path

    def create_after_reservation(*args, **kwargs):
        target = Path(str(args[0]))
        if target.parent == staging_root and not target.exists():
            row = next(item for item in storage._ledger.readiness()["roots"]
                       if item["purpose"] == "temporary_containment")
            before_create.append((row["reserved_bytes"], row["reserved_entries"],
                                  row["observed_used_bytes"], row["observed_used_entries"]))
        return create_file(*args, **kwargs)

    with patch.object(native_api, "CreateFile", side_effect=create_after_reservation):
        observed = stage_admitted(
            store, storage, values, provide, operation_id="stream-admitted-1",
            fresh=lambda envelope, remote: (
                not store._lock._is_owned() and not storage._lock._is_owned()))
    assert before_create == [(maximum, 1, 0, 0)]
    assert snapshots == [(maximum, 1, 0, 0)]
    assert type(observed) is a.VerifiedProtectedImageObservation
    assert store._stream_images[(observed.request_id, observed.descriptor_identity)] is observed
    path, handle, identity, acl = store._files[(observed.image.purpose, observed.image.storage_identity)]
    assert path.read_bytes() == data
    assert w._identity(handle) == identity == w._ordinary(path, directory=False)
    assert w._acl(handle, store._roots[observed.image.purpose]._api,
                  store._roots[observed.image.purpose]._user) == acl[0]
    row = next(item for item in storage.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["reserved_bytes"] == row["reserved_entries"] == 0
    assert row["observed_used_bytes"] == len(data)
    assert row["observed_used_entries"] == 1
    assert row["retained_uncertain_bytes"] == row["retained_uncertain_entries"] == 0
    storage_view = storage.readiness()
    assert storage_view["writer_integrated"] is True
    assert provider.closes == 1
    for key in ("execution_available", "protected_storage_available", "promotion_available",
                "candidate_publication_allowed", "disk_space_guaranteed", "cleanup_allowed"):
        assert storage_view[key] is False
    assert storage_view["authorship"] == "unverified"


def test_real_native_admitted_stream_supports_sequential_descriptors_and_refreshes_inventory(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    values, first_data, second_data = bound(images=2), image_bytes(), image_bytes("PNG", (3, 4))
    first = stage_admitted(store, storage, values, Stream(first_data),
                           operation_id="stream-admitted-descriptor-0", index=0)
    second = stage_admitted(store, storage, values, Stream(second_data),
                            operation_id="stream-admitted-descriptor-1", index=1)
    assert (first.descriptor_identity, second.descriptor_identity) == tuple(
        descriptor.identity for descriptor in values[2].images)
    row = next(item for item in storage.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["observed_used_bytes"] == len(first_data) + len(second_data)
    assert row["observed_used_entries"] == 2
    assert row["reserved_bytes"] == row["reserved_entries"] == 0
    assert store._stream_request_bytes[values[1].request_id] == len(first_data) + len(second_data)
    assert len(store._stream_images) == 2 and not store._uncertain


def test_real_native_admitted_stream_capacity_refusal_precedes_create_and_provider(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    limited = replace(storage._limits, shared_temporary_and_promoted_bytes=1)
    storage._limits = limited
    storage._ledger._limits = limited
    provider = Mock()
    with patch.object(store._roots["temporary_containment"]._api[2], "CreateFile",
                      side_effect=AssertionError("CREATE_NEW must not be reached")):
        with pytest.raises(ValueError, match="storage_capacity_exceeded"):
            stage_admitted(store, storage, bound(), provider, operation_id="stream-over-capacity")
    provider.assert_not_called()
    assert not store._files and not store._unobserved_files and not store._uncertain
    row = next(item for item in storage._ledger.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["reserved_bytes"] == row["reserved_entries"] == 0
    assert row["retained_uncertain_bytes"] == row["retained_uncertain_entries"] == 0


def test_real_native_admitted_stream_rejects_copied_descriptor_before_reservation(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    values, provider = bound(), Mock()
    descriptor = replace(values[2].images[0])
    with pytest.raises(ValueError, match="remote_correlation_mismatch"):
        store.stage_remote_image_with_admission_for_characterization(
            *values, descriptor, admission_owner=storage, operation_id="stream-copied-descriptor",
            stream_provider=provider, host_freshness=lambda envelope, remote: True,
            characterization=True, disposable_opt_in=True)
    provider.assert_not_called()
    assert not store._files and not store._stream_attempts
    assert not storage._ledger._reservations and not store._uncertain


def test_real_native_admitted_stream_rejects_reused_capacity_operation_id(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    values = bound(images=2)
    first = stage_admitted(store, storage, values, Stream(image_bytes()),
                           operation_id="stream-same-capacity-operation", index=0)
    provider = Mock()
    with pytest.raises(ValueError, match="operation_identity_reused"):
        stage_admitted(store, storage, values, provider,
                       operation_id="stream-same-capacity-operation", index=1)
    provider.assert_not_called()
    assert len(store._files) == 1
    assert store._stream_images[(first.request_id, first.descriptor_identity)] is first
    assert not store._uncertain


def test_real_native_admitted_stream_cancels_pre_admission_freshness_loss(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    provider = Mock()
    with pytest.raises(ValueError, match="host_freshness_lost"):
        stage_admitted(store, storage, bound(), provider, operation_id="stream-pre-admission-stale",
                       fresh=lambda envelope, remote: False)
    provider.assert_not_called()
    assert not store._files and not store._unobserved_files and not store._uncertain
    assert not storage._ledger._reservations
    assert not store._capacity_busy and store._capacity_idle.is_set()


@pytest.mark.parametrize("fault", ["provider", "read"])
def test_real_native_admitted_stream_retains_full_upper_bound_after_admission(admitted_owner, fault):
    store, storage, _, _, _ = admitted_owner
    provider = Stream(image_bytes())
    if fault == "provider":
        def fail_provider(lookup):
            provider(lookup)
            raise OSError("injected stream provider failure")
        callback = fail_provider
    else:
        provider.read_hook = lambda limit: (_ for _ in ()).throw(OSError("injected stream read failure"))
        callback = provider
    maximum = min(store._limits.image_bytes, store._limits.request_bytes,
                  store._limits.aggregate_bytes)
    with pytest.raises(ValueError, match="download_interrupted"):
        stage_admitted(store, storage, bound(), callback,
                       operation_id="stream-admitted-failure-" + fault)
    assert store._uncertain and not store._stream_images and not store._images
    assert len(store._files) == 1
    assert next(iter(store._files.values()))[0].exists()
    row = next(item for item in storage._ledger.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["reserved_bytes"] == row["reserved_entries"] == 0
    assert row["retained_uncertain_bytes"] == maximum
    assert row["retained_uncertain_entries"] == 1
    assert not store._capacity_busy and store._capacity_idle.is_set()


def test_real_native_admitted_stream_close_waits_for_blocked_provider_and_retains_uncertainty(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    stream = Stream(image_bytes())
    errors, close_errors = [], []

    def provider(lookup):
        entered.set()
        assert release.wait(5)
        return stream(lookup)

    def run_stream():
        try:
            stage_admitted(store, storage, bound(), provider,
                           operation_id="stream-close-race")
        except BaseException as exc:
            errors.append(exc)

    def run_close():
        try:
            store.close()
        except BaseException as exc:
            close_errors.append(exc)
        finally:
            closed.set()

    worker = threading.Thread(target=run_stream)
    closer = threading.Thread(target=run_close)
    try:
        worker.start()
        assert entered.wait(5)
        closer.start()
        assert store._revoking_event.wait(5)
        assert not closed.is_set()
        release.set()
        worker.join(10)
        closer.join(10)
    finally:
        release.set()
        if worker.ident is not None:
            worker.join(5)
        if closer.ident is not None:
            closer.join(5)
    assert not worker.is_alive() and not closer.is_alive()
    assert not close_errors and closed.is_set()
    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    assert stream.closes == 1
    assert store._closed and store._uncertain and not store._stream_images
    assert len(store._files) == 1 and next(iter(store._files.values()))[0].exists()
    row = next(item for item in storage._ledger.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["retained_uncertain_bytes"] == min(
        store._limits.image_bytes, store._limits.request_bytes, store._limits.aggregate_bytes)
    assert row["retained_uncertain_entries"] == 1


def test_real_native_admitted_stream_reentrant_close_fails_fast(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    values, stream = bound(), Stream(image_bytes())

    def provider(lookup):
        with pytest.raises(ValueError, match="storage_busy"):
            store.close()
        return stream(lookup)

    observed = stage_admitted(store, storage, values, provider,
                              operation_id="stream-reentrant-close")
    assert observed.image.byte_count == len(image_bytes())
    assert not store._revoking and not store._uncertain
    row = next(item for item in storage.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["reserved_bytes"] == 0


def test_real_native_admitted_stream_duplicate_attempt_does_not_reserve_or_retry(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    values, data = bound(), image_bytes()
    first = stage_admitted(store, storage, values, Stream(data), operation_id="stream-duplicate-first")
    provider = Mock()
    with pytest.raises(ValueError, match="already_attempted"):
        stage_admitted(store, storage, values, provider, operation_id="stream-duplicate-second")
    provider.assert_not_called()
    assert len(store._files) == 1 and store._stream_images[(first.request_id, first.descriptor_identity)] is first
    row = next(item for item in storage._ledger.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["reserved_bytes"] == row["reserved_entries"] == 0
    assert row["observed_used_bytes"] == len(data) and row["observed_used_entries"] == 1


def test_real_native_admitted_stream_requires_disposable_scope_and_exact_root_owners(admitted_owner, owner):
    store, storage, _, _, _ = admitted_owner
    foreign_store = owner[0]
    provider = Mock()
    values = bound()
    with pytest.raises(ValueError, match="storage_root_owner_mismatch"):
        stage_admitted(foreign_store, storage, values, provider,
                       operation_id="stream-cross-owner")
    with pytest.raises(ValueError, match="execution_unavailable"):
        stage_admitted(store, storage, values, provider, operation_id="stream-no-opt-in",
                       characterization=False)
    provider.assert_not_called()
    assert not store._files and not foreign_store._files
    assert not storage._ledger._reservations


@pytest.mark.parametrize("drift", ["content", "acl"])
def test_real_native_admitted_stream_drift_retains_maximum_reservation(admitted_owner, drift):
    store, storage, _, api, _ = admitted_owner
    data, values = image_bytes(), bound()

    def fault(boundary):
        if boundary != "after_file_write":
            return
        path = next(iter(store._files.values()))[0]
        if drift == "content":
            path.write_bytes(b"changed while disposable stream was active")
        else:
            mutate_disposable_acl(path, api, "changed_owner_only")

    store._fault = fault
    maximum = min(store._limits.image_bytes, store._limits.request_bytes,
                  store._limits.aggregate_bytes)
    with pytest.raises(Exception):
        stage_admitted(store, storage, values, Stream(data),
                       operation_id="stream-drift-" + drift)
    assert store._uncertain and not store._stream_images and not store._images
    assert len(store._files) == 1 and next(iter(store._files.values()))[0].exists()
    row = next(item for item in storage._ledger.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["reserved_bytes"] == 0
    assert row["retained_uncertain_bytes"] == maximum
    assert row["retained_uncertain_entries"] == 1
    if drift == "acl":
        path = next(iter(store._files.values()))[0]
        mutate_disposable_acl(path, api, "original")


def test_real_native_admitted_stream_host_freshness_loss_after_provider_retains_maximum(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    values, stream, current = bound(), Stream(image_bytes()), [True]

    def provider(lookup):
        result = stream(lookup)
        current[0] = False
        return result

    with pytest.raises(ValueError, match="host_freshness_lost"):
        stage_admitted(store, storage, values, provider,
                       operation_id="stream-stale-after-provider",
                       fresh=lambda envelope, remote: current[0])
    assert stream.closes == 1 and not store._stream_images and not store._images
    assert store._uncertain and len(store._files) == 1
    row = next(item for item in storage._ledger.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["retained_uncertain_bytes"] == min(
        store._limits.image_bytes, store._limits.request_bytes, store._limits.aggregate_bytes)
    assert row["retained_uncertain_entries"] == 1


def test_real_native_admitted_stream_rechecks_freshness_at_final_native_commit(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    values, current, calls = bound(), [True], [0]
    observe = store._observe

    def drift_after_final_native_observation(name, purpose, extension):
        result = observe(name, purpose, extension)
        calls[0] += 1
        if calls[0] == 3:
            current[0] = False
        return result

    store._observe = drift_after_final_native_observation
    with pytest.raises(ValueError, match="host_freshness_lost"):
        stage_admitted(store, storage, values, Stream(image_bytes()),
                       operation_id="stream-stale-before-final-commit",
                       fresh=lambda envelope, remote: current[0])
    assert calls[0] == 3 and store._uncertain
    assert not store._images and not store._stream_images and not store._stream_pending_images
    row = next(item for item in storage._ledger.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["retained_uncertain_bytes"] == min(
        store._limits.image_bytes, store._limits.request_bytes, store._limits.aggregate_bytes)
    assert row["retained_uncertain_entries"] == 1


def test_real_native_admission_close_during_provider_retains_admitted_stream(admitted_owner):
    store, storage, _, _, _ = admitted_owner
    stream, provider_called = Stream(image_bytes()), []

    def provider(lookup):
        result = stream(lookup)
        provider_called.append(True)
        storage.close()
        return result

    with pytest.raises(ValueError, match="storage_owner_unavailable"):
        stage_admitted(store, storage, bound(), provider,
                       operation_id="stream-admission-close-race")
    assert provider_called == [True] and stream.closes == 1
    assert not store._stream_images and not store._images and store._uncertain
    assert len(store._files) == 1 and next(iter(store._files.values()))[0].exists()
    row = next(item for item in storage._ledger.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["retained_uncertain_bytes"] == min(
        store._limits.image_bytes, store._limits.request_bytes, store._limits.aggregate_bytes)
    assert row["retained_uncertain_entries"] == 1


def test_real_native_incremental_write_before_next_read_and_no_prebuffer(owner):
    store, _, _ = owner
    data = image_bytes("BMP", (257, 200))
    values, consumed = bound("bmp"), 0
    def read(limit):
        nonlocal consumed
        path = next(iter(store._files.values()))[0]
        assert path.stat().st_size == consumed
        chunk = data[consumed:consumed + limit]
        consumed += len(chunk)
        return chunk
    provider = Stream(data, read=read)
    observed = stage(store, values, provider)
    assert consumed == observed.image.byte_count == len(data)
    assert len(provider.reads) >= 4
    assert store.readiness()["retained_byte_reservation"] == len(data)


def test_real_native_close_contending_with_allocation_tracks_handle_and_fences_stream(owner):
    store, _, api = owner
    values, provider = bound(), Mock()
    create_returned = threading.Event()
    close_contending = threading.Event()
    allow_create_return = threading.Event()
    close_finished = threading.Event()
    close_thread_id = [None]
    stage_errors, close_errors = [], []

    class CloseObservedRLock:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            if threading.get_ident() == close_thread_id[0]:
                close_contending.set()
            self.inner.acquire()
            return self

        def __exit__(self, *_):
            self.inner.release()

        def _is_owned(self):
            return self.inner._is_owned()

    store._lock = CloseObservedRLock(store._lock)
    original_create = api[2].CreateFile

    def create_then_pause(*args):
        handle = original_create(*args)
        create_returned.set()
        assert close_contending.wait(5)
        assert allow_create_return.wait(5)
        return handle

    def fault(point):
        if point == "after_file_create":
            assert not store._lock._is_owned()
            assert close_finished.wait(5)

    store._fault = fault

    def stage_worker():
        try:
            stage(store, values, provider)
        except BaseException as exc:
            stage_errors.append(exc)

    def close_worker():
        close_thread_id[0] = threading.get_ident()
        try:
            store.close()
        except BaseException as exc:
            close_errors.append(exc)
        finally:
            close_finished.set()

    stage_thread = threading.Thread(target=stage_worker)
    close_thread = threading.Thread(target=close_worker)
    try:
        with patch.object(api[2], "CreateFile", side_effect=create_then_pause):
            stage_thread.start()
            assert create_returned.wait(5)
            close_thread.start()
            assert close_contending.wait(5)
            allow_create_return.set()
            stage_thread.join(10)
            close_thread.join(10)
    finally:
        allow_create_return.set()
        close_finished.set()
        if stage_thread.ident is not None:
            stage_thread.join(5)
        if close_thread.ident is not None:
            close_thread.join(5)

    assert not stage_thread.is_alive() and not close_thread.is_alive()
    assert not close_errors and len(stage_errors) == 1
    assert store._closed and store._uncertain and not store._stream_busy
    assert store._stream_attempts and not store._images and not store._stream_images
    provider.assert_not_called()

    tracked = ([(path, handle) for path, handle in store._unobserved_files]
               + [(record[0], record[1]) for record in store._files.values()])
    assert len(tracked) == 1
    path, handle = tracked[0]
    assert path.exists() and path.parent == store._roots["temporary_containment"]._path
    with pytest.raises(ValueError, match="native_identity_unavailable"):
        w._identity(handle)
    with pytest.raises(ValueError):
        stage(store, values, provider)
    provider.assert_not_called()


@pytest.mark.parametrize("failure", ["short", "extra", "oversized", "zero", "bool_length", "nonbyte", "overread",
                                     "malformed", "timeout", "interrupt", "close", "wrong_format"])
def test_real_native_failed_stream_retains_all_evidence_fences_retry(owner, failure):
    store, _, _ = owner
    data = image_bytes()
    provider = Stream(data)
    if failure == "short": provider.length += 1
    elif failure == "extra": provider.length -= 1
    elif failure == "oversized": provider.length = store._limits.image_bytes + 1
    elif failure == "zero": provider.length = 0
    elif failure == "bool_length": provider.length = True
    elif failure == "nonbyte": provider.read_hook = lambda limit: "secret invalid chunk"
    elif failure == "overread": provider.read_hook = lambda limit: b"x" * (limit + 1)
    elif failure in {"malformed", "wrong_format"}:
        provider = Stream(b"bad" if failure == "malformed" else image_bytes("JPEG"))
    elif failure in {"timeout", "interrupt"}:
        def broken(limit): raise TimeoutError() if failure == "timeout" else OSError("interrupted")
        provider.read_hook = broken
    elif failure == "close":
        def close(): raise OSError("close failed")
        provider.close_hook = close
    values = bound()
    with pytest.raises(Exception): stage(store, values, provider)
    assert provider.closes == 1 and len(provider.lookups) == 1
    assert len(store._files) == 1 and not store._images and not store._stream_images
    path = next(iter(store._files.values()))[0]
    assert path.exists() and store.readiness()["asset_observation"] == "retained_uncertain"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="inspect_only_or_uncertain"):
        stage(store, values, provider)
    store.close()
    assert path.read_bytes() == before


@pytest.mark.parametrize("boundary", ["provider", "read", "close", "before"])
def test_real_native_host_freshness_loss_around_callbacks_retains_no_success(owner, boundary):
    store, _, _ = owner
    data, values, current = image_bytes(), bound(), boundary != "before"
    provider = Stream(data)
    def lose():
        nonlocal current
        current = False
    if boundary == "read":
        def read(limit):
            lose()
            return data[:limit]
        provider.read_hook = read
    if boundary == "close": provider.close_hook = lose
    def provide(lookup):
        stream = provider(lookup)
        if boundary == "provider": lose()
        return stream
    with pytest.raises(ValueError, match="host_freshness_lost"):
        stage(store, values, provide, lambda envelope, remote: current)
    assert not store._images and not store._stream_images
    assert len(provider.lookups) == (0 if boundary == "before" else 1)
    assert provider.closes == (0 if boundary == "before" else 1)
    assert all(record[0].exists() for record in store._files.values())
    assert not store._stream_busy and store._uncertain


@pytest.mark.parametrize("point", ["after_file_create", "after_file_write", "after_file_sync", "provider", "read", "close"])
@pytest.mark.parametrize("target", ["file", "root"])
def test_real_native_acl_change_permanently_invalidates_even_after_restore(owner, point, target):
    store, _, api = owner
    values, changed = bound(), []
    def mutate():
        path = next(iter(store._files.values()))[0]
        path = path if target == "file" else path.parent
        mutate_disposable_acl(path, api, "changed_owner_only")
        changed.append(path)
    def fault(boundary):
        if boundary == point: mutate()
    store._fault = fault
    provider = Stream(image_bytes())
    if point == "read":
        def read(limit):
            mutate()
            return b""
        provider.read_hook = read
    if point == "close": provider.close_hook = mutate
    def provide(lookup):
        result = provider(lookup)
        if point == "provider": mutate()
        return result
    with pytest.raises(ValueError): stage(store, values, provide)
    assert changed and not store._images and store._invalid
    for path in changed: mutate_disposable_acl(path, api, "original")
    with pytest.raises(ValueError, match="invalidated_observation"): store._check()
    assert all(r[0].exists() for r in store._files.values())
    assert provider.closes == (0 if point == "after_file_create" else 1)


@pytest.mark.parametrize("native", ["WriteFile", "FlushFileBuffers"])
def test_real_native_io_failures_reserve_bytes_and_retain(owner, native):
    store, _, api = owner
    data, values = image_bytes(), bound()
    with patch.object(api[2], native, side_effect=OSError("native IO failed")):
        with pytest.raises(OSError): stage(store, values, Stream(data))
    assert store.readiness()["retained_byte_reservation"] == len(data)
    assert len(store._files) == 1 and not store._images and store._uncertain


def test_real_native_short_write_retains_actual_partial_bytes_and_full_reservation(owner):
    store, _, api = owner
    data, write = image_bytes(), api[2].WriteFile
    def partial(handle, chunk): return write(handle, chunk[:len(chunk) // 2])
    with patch.object(api[2], "WriteFile", side_effect=partial):
        with pytest.raises(ValueError, match="incomplete_write"):
            stage(store, bound(), Stream(data))
    assert next(iter(store._files.values()))[0].read_bytes() == data[:len(data) // 2]
    assert store.readiness()["retained_byte_reservation"] == len(data)
    assert store._uncertain and not store._images


def test_injected_identity_mismatch_fences_real_native_file_permanently(owner):
    store, _, _ = owner
    data, identity = image_bytes(), w._identity
    def mismatched(handle):
        volume, identifier = identity(handle)
        return volume, identifier + 1
    provider = Stream(data)
    def read(limit):
        with patch.object(w, "_identity", side_effect=mismatched):
            store._check()
        return b""
    provider.read_hook = read
    with pytest.raises(ValueError): stage(store, bound(), provider)
    assert store._invalid and store._uncertain and provider.closes == 1
    with pytest.raises(ValueError, match="invalidated_observation"): store._check()
    assert next(iter(store._files.values()))[0].exists() and not store._images


def test_initial_native_metadata_failure_retains_file_and_original_handle(owner):
    store, _, _ = owner
    provider = Mock()
    with patch.object(a, "_file_acl", side_effect=ValueError("unsafe_acl")):
        with pytest.raises(ValueError, match="unsafe_acl"):
            stage(store, bound(), provider)
    provider.assert_not_called()
    assert store._invalid and store._uncertain and len(store._unobserved_files) == 1
    path, handle = store._unobserved_files[0]
    assert path.exists() and path.read_bytes() == b""
    assert w._identity(handle) == w._ordinary(path, directory=False)
    assert store.readiness()["retained_file_count"] == 1
    store.close()
    assert path.exists()


def test_real_native_content_change_after_write_is_compared_with_stream_hash(owner):
    store, _, _ = owner
    def fault(point):
        if point == "after_file_sync": next(iter(store._files.values()))[0].write_bytes(image_bytes("PNG", (4, 4)))
    store._fault = fault
    with pytest.raises(ValueError, match="content_changed"):
        stage(store, bound(), Stream(image_bytes()))
    assert store._uncertain and not store._images


def test_real_native_attempt_is_pinned_and_unlocked_before_every_callback(owner):
    store, _, _ = owner
    values = bound()
    provider, reentries = Stream(image_bytes()), []
    def fresh(envelope, remote):
        assert envelope is values[0] and remote is values[2]
        assert not store._lock._is_owned()
        if not reentries:
            reentries.append(True)
            with pytest.raises(ValueError, match="already_attempted"):
                stage(store, values, provider)
            with pytest.raises(ValueError, match="storage_busy"):
                store.create_image_for_characterization("promoted_assets", image_bytes())
        return True
    stage(store, values, provider, fresh)
    assert len(provider.lookups) == 1


def test_real_native_exact_host_freshness_inputs_bracket_all_remote_operations(owner):
    store, _, _ = owner
    values, events = bound(), []
    source = io.BytesIO(image_bytes())
    def fresh(envelope, remote):
        assert envelope is values[0] and remote is values[2]
        events.append("fresh")
        return True
    def read(limit):
        events.append("read")
        return source.read(limit)
    def close(): events.append("close")
    def provider(lookup):
        events.append("provider")
        return DownloadStream(len(source.getvalue()), read, close)
    stage(store, values, provider, fresh)
    assert events[0] == events[-1] == "fresh"
    for index, event in enumerate(events):
        if event in {"provider", "read", "close"}:
            assert events[index - 1] == events[index + 1] == "fresh"
    assert events.count("provider") == events.count("close") == 1


@pytest.mark.parametrize("operation", ["provider", "read", "close", "fresh"])
def test_real_native_callback_exception_messages_are_bounded_and_redacted(owner, operation):
    store, _, _ = owner
    def fail(*args): raise OSError("PRIVATE_ENDPOINT/PRIVATE_SECRET/local/path")
    provider = Stream(image_bytes())
    if operation == "read": provider.read_hook = fail
    elif operation == "close": provider.close_hook = fail
    code = "host_freshness_lost" if operation == "fresh" else (
        "download_close_failed" if operation == "close" else "download_interrupted")
    with pytest.raises(ValueError, match="^" + code + "$") as error:
        stage(store, bound(), fail if operation == "provider" else provider,
              fail if operation == "fresh" else lambda envelope, remote: True)
    assert "PRIVATE" not in str(error.value)
    assert "PRIVATE" not in "".join(traceback.format_exception(error.value))
    assert store._uncertain and not store._images


def test_real_native_trusted_freshness_requires_literal_true(owner):
    store, _, _ = owner
    provider = Mock()
    with pytest.raises(ValueError, match="host_freshness_lost"):
        stage(store, bound(), provider, lambda envelope, remote: 1)
    provider.assert_not_called()
    assert store._stream_attempts and store._uncertain and not store._files


@pytest.mark.parametrize("limit", ["request", "aggregate", "images"])
def test_real_native_limits_include_prior_images_and_failed_attempts(owner, limit):
    store, _, _ = owner
    data, values = image_bytes(), bound(images=2)
    if limit == "request": store._limits = ContainmentLimits(image_bytes=len(data), request_bytes=len(data), aggregate_bytes=2 * len(data))
    elif limit == "aggregate": store._limits = ContainmentLimits(image_bytes=len(data), request_bytes=2 * len(data), aggregate_bytes=len(data))
    else: store._limits = ContainmentLimits(images=1)
    provider = Stream(data)
    first = stage(store, values, provider)
    with pytest.raises(ValueError, match="storage_capacity|download_size_limit"):
        stage(store, values, Stream(data), index=1)
    assert store._files[(first.image.purpose, first.image.storage_identity)][0].read_bytes() == data
    assert store.readiness()["retained_byte_reservation"] == len(data)


def test_real_native_exact_envelope_request_and_remote_cannot_be_rebound(owner):
    store, _, _ = owner
    values = bound(images=2)
    stage(store, values, Stream(image_bytes()))
    envelope, prepared, remote = values
    for altered, code in [((copy.copy(envelope), prepared, remote), "storage_owner_mismatch"),
                          ((envelope, prepared, replace(remote)), "remote_binding_conflict")]:
        provider = Mock()
        with pytest.raises(ValueError, match=code): stage(store, altered, provider, index=1)
        provider.assert_not_called()


def test_real_native_http_view_composition_no_temp_gallery_project_or_activation(owner):
    store, _, _ = owner
    values, data = bound(), image_bytes()
    wire = Wire(Response(data, headers=[("Content-Length", str(len(data))), ("Content-Type", "text/plain")]))
    transport = PromptHTTPViewTransport(wire_factory=wire, characterization=True)
    with patch("tempfile.mkdtemp", side_effect=AssertionError("OS temp allocation")), \
         patch("pathlib.Path.mkdir", side_effect=AssertionError("Project/Gallery directory write")), \
         patch("core.gallery_generation.ingest_gallery_generation_outputs", side_effect=AssertionError("Candidate")), \
         patch("threading.Thread.start", side_effect=AssertionError("Worker")), \
         patch("urllib.request.urlopen", side_effect=AssertionError("network")):
        observed = stage(store, values, transport.provider_for_characterization(*values))
    assert observed.image.content_sha256 == hashlib.sha256(data).hexdigest()
    assert transport.observation().status == "downloaded"
    assert wire.closed and wire.response.closed and wire.response.finished
    assert not transport.execution_available and not transport.protected_storage_available
    assert_closed_gates(store.readiness())


def test_real_native_fresh_reopen_is_inspect_only_and_cannot_recover_remote_authority(owner):
    store, scope, _ = owner
    values = bound()
    original = stage(store, values, Stream(image_bytes()))
    paths = {p: str(r._path) for p, r in store._roots.items()}
    store.close()
    with a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True) as reopened:
        images = reopened.inspect_existing_for_characterization()
        assert len(images) == 1 and type(images[0]) is a.ProtectedImageObservation
        assert not reopened._stream_bindings and not reopened._stream_images
        assert reopened.readiness()["retained_byte_reservation"] == len(image_bytes())
        with pytest.raises(ValueError, match="image_owner_mismatch"):
            reopened.inspect_verified_remote_image_for_characterization(original)
        with pytest.raises(ValueError, match="inspect_only_or_uncertain"):
            stage(reopened, values, Stream(image_bytes()))
        assert_closed_gates(reopened.readiness())


def test_real_native_partial_failed_stream_reopen_keeps_bytes_and_no_remote_authority(owner):
    store, scope, _ = owner
    data, values = image_bytes(), bound()
    with pytest.raises(ValueError, match="short_download"):
        stage(store, values, Stream(data[:10], length=len(data)))
    paths = {p: str(r._path) for p, r in store._roots.items()}
    path = next(iter(store._files.values()))[0]
    store.close()
    with a.WindowsProtectedAssetsCharacterization.reopen_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True) as reopened:
        with pytest.raises(Exception, match="invalid_image_content"):
            reopened.inspect_existing_for_characterization()
        assert reopened._uncertain and not reopened._images and not reopened._stream_images
        assert reopened.readiness()["retained_byte_reservation"] == 10
        with pytest.raises(ValueError, match="inspect_only_or_uncertain"):
            stage(reopened, values, Stream(data))
    assert path.read_bytes() == data[:10]


def test_real_native_unmanaged_file_is_retained_and_blocks_stream_before_provider(owner):
    store, _, _ = owner
    unexpected = store._roots["temporary_containment"]._path / "keep.png"
    unexpected.write_bytes(b"retained unknown")
    provider = Mock()
    with pytest.raises(ValueError, match="unexpected_existing_file"):
        stage(store, bound(), provider)
    provider.assert_not_called()
    assert unexpected.read_bytes() == b"retained unknown" and store._uncertain and not store._files


def test_real_native_collision_never_overwrites_retained_image(owner):
    store, _, _ = owner
    values = bound(images=2)
    class Name: hex = "a" * 32
    with patch.object(a.uuid, "uuid4", return_value=Name()):
        first = stage(store, values, Stream(image_bytes()))
        with pytest.raises(Exception): stage(store, values, Stream(image_bytes()), index=1)
    path = store._files[(first.image.purpose, first.image.storage_identity)][0]
    assert len(store._files) == 1 and path.read_bytes() == image_bytes() and store._uncertain


def test_real_native_close_failure_fences_observation_and_attempts_all_handles(owner):
    store, _, _ = owner
    observed = stage(store, bound(), Stream(image_bytes()))
    key = (observed.image.purpose, observed.image.storage_identity)
    path, handle, identity, acl = store._files[key]
    class FailedClose:
        def Close(self):
            handle.Close()
            raise OSError("ambiguous close")
    store._files[key] = path, FailedClose(), identity, acl
    with pytest.raises(ValueError, match="native_close_failed"): store.close()
    assert store._closed and store._invalid and store._uncertain
    assert all(root._closed for root in store._roots.values()) and path.exists()
    with pytest.raises(ValueError): store.inspect_verified_remote_image_for_characterization(observed)


@pytest.mark.parametrize("count", [1, 3])
def test_real_native_batch_receipt_commits_all_exact_images_and_is_owner_held(owner, count):
    store, _, _ = owner
    values, data = bound(images=count), image_bytes()
    observations = tuple(stage(store, values, Stream(data), index=index) for index in range(count))
    envelope, prepared, remote = values
    receipt = store.commit_verified_remote_image_batch_for_characterization(
        envelope, prepared, remote, observations, host_freshness=lambda e, r: e is envelope and r is remote)

    assert type(receipt) is a.VerifiedProtectedImageBatchReceipt
    assert not issubclass(a.VerifiedProtectedImageBatchReceipt, (LocalOutputReceipt, PromotedImage))
    assert (receipt.job_id, receipt.claim_id, receipt.manifest_identity, receipt.request_id,
            receipt.request_index, receipt.workflow_identity, receipt.prompt_id,
            receipt.remote_receipt_identity) == (
        remote.job_id, remote.claim_id, remote.manifest_identity, prepared.request_id,
        prepared.request_index, prepared.workflow_identity, remote.prompt_id, remote.identity)
    assert receipt.observations == observations
    assert tuple(item.descriptor_identity for item in receipt.observations) == tuple(
        descriptor.identity for descriptor in remote.images)
    assert store.inspect_verified_remote_image_batch_for_characterization(receipt) is receipt
    with pytest.raises(ValueError, match="batch_owner_mismatch"):
        store.inspect_verified_remote_image_batch_for_characterization(replace(receipt))
    with pytest.raises(ValueError, match="already_attempted"):
        store.commit_verified_remote_image_batch_for_characterization(
            envelope, prepared, remote, observations, host_freshness=lambda e, r: True)
    assert store.inspect_verified_remote_image_batch_for_characterization(receipt) is receipt
    assert store.readiness()["verified_batch_count"] == 1
    assert_closed_gates(store.readiness())


@pytest.mark.parametrize("variant,code", [
    ("missing", "batch_observation_incomplete"),
    ("duplicate", "batch_observation_ambiguous"),
    ("substituted", "batch_observation_substitution"),
    ("extra", "batch_observation_ambiguous"),
])
def test_real_native_incomplete_or_substituted_batch_never_partially_commits(owner, variant, code):
    store, _, _ = owner
    values, data = bound(images=2), image_bytes()
    observations = tuple(stage(store, values, Stream(data), index=index) for index in range(2))
    envelope, prepared, remote = values
    if variant == "missing": candidate = observations[:1]
    elif variant == "duplicate": candidate = (observations[0], observations[0])
    elif variant == "substituted": candidate = (replace(observations[0], request_id="other"), observations[1])
    else: candidate = (observations[0], replace(observations[1], descriptor_identity="extra"))

    with pytest.raises(ValueError, match=code):
        store.commit_verified_remote_image_batch_for_characterization(
            envelope, prepared, remote, candidate, host_freshness=lambda e, r: True)
    assert not store._stream_batches and store._uncertain
    assert len(store._stream_images) == 2 and all(record[0].exists() for record in store._files.values())
    with pytest.raises(ValueError, match="inspect_only_or_uncertain"):
        store.commit_verified_remote_image_batch_for_characterization(
            envelope, prepared, remote, observations, host_freshness=lambda e, r: True)


@pytest.mark.parametrize("binding", ["envelope", "prepared", "remote"])
def test_real_native_batch_requires_exact_original_objects_without_consuming_correct_binding(owner, binding):
    store, _, _ = owner
    values = bound(images=2)
    observations = tuple(stage(store, values, Stream(image_bytes()), index=index) for index in range(2))
    envelope, prepared, remote = values
    altered = [envelope, prepared, remote]
    if binding == "envelope": altered[0] = copy.copy(envelope)
    elif binding == "prepared": altered[1] = replace(prepared)
    else: altered[2] = replace(remote)
    fresh = Mock(return_value=True)
    expected = "remote_correlation_mismatch" if binding == "prepared" else (
        "storage_owner_mismatch" if binding == "envelope" else "remote_binding_conflict")
    with pytest.raises(ValueError, match=expected):
        store.commit_verified_remote_image_batch_for_characterization(
            *altered, observations, host_freshness=fresh)
    fresh.assert_not_called()
    assert not store._stream_batch_attempts and not store._uncertain
    receipt = store.commit_verified_remote_image_batch_for_characterization(
        envelope, prepared, remote, observations, host_freshness=lambda e, r: True)
    assert store.inspect_verified_remote_image_batch_for_characterization(receipt) is receipt


@pytest.mark.parametrize("failure", ["content", "acl", "freshness"])
def test_real_native_batch_revalidates_bytes_acl_and_host_freshness(owner, failure):
    store, _, api = owner
    values, data = bound(), image_bytes()
    observation = stage(store, values, Stream(data))
    path = next(iter(store._files.values()))[0]
    if failure == "content": path.write_bytes(image_bytes("PNG", (4, 4)))
    elif failure == "acl": mutate_disposable_acl(path, api, "changed_owner_only")
    fresh = Mock(return_value=False if failure == "freshness" else True)
    with pytest.raises(ValueError, match="host_freshness_lost|content_changed|native_observation_changed"):
        store.commit_verified_remote_image_batch_for_characterization(
            *values, (observation,), host_freshness=fresh)
    assert fresh.call_count == (0 if failure == "acl" else 1)
    assert not store._stream_batches and store._uncertain
    if failure == "acl": mutate_disposable_acl(path, api, "original")
    assert path.exists()


def test_real_native_batch_rechecks_host_freshness_after_slow_native_verification(owner):
    store, _, _ = owner
    values, data = bound(), image_bytes()
    observation = stage(store, values, Stream(data))
    current, freshness_calls = [True], []

    def fresh(envelope, remote):
        assert envelope is values[0] and remote is values[2]
        assert not store._lock._is_owned()
        freshness_calls.append(current[0])
        return current[0]

    inspect = store.inspect_image_for_characterization

    def inspect_then_expire(image):
        result = inspect(image)
        current[0] = False
        return result

    with patch.object(store, "inspect_image_for_characterization", side_effect=inspect_then_expire):
        with pytest.raises(ValueError, match="host_freshness_lost"):
            store.commit_verified_remote_image_batch_for_characterization(
                *values, (observation,), host_freshness=fresh)

    assert freshness_calls == [True, False]
    assert not store._stream_batches and store._uncertain
    assert next(iter(store._files.values()))[0].read_bytes() == data


def test_real_native_batch_failed_stream_has_no_receipt_and_no_retry(owner):
    store, _, _ = owner
    values = bound()
    provider = Stream(image_bytes())
    provider.read_hook = lambda limit: b""
    with pytest.raises(ValueError, match="short_download"):
        stage(store, values, provider)
    fresh = Mock(return_value=True)
    with pytest.raises(ValueError, match="inspect_only_or_uncertain"):
        store.commit_verified_remote_image_batch_for_characterization(
            *values, (), host_freshness=fresh)
    fresh.assert_not_called()
    assert not store._stream_batches and provider.closes == 1
    assert all(record[0].exists() for record in store._files.values())


def test_real_native_batch_duplicate_call_during_host_check_is_one_shot(owner):
    store, _, _ = owner
    values = bound(images=2)
    observations = tuple(stage(store, values, Stream(image_bytes()), index=index) for index in range(2))
    envelope, prepared, remote = values
    entered, resume = threading.Event(), threading.Event()
    results, errors = [], []

    def slow_freshness(e, r):
        assert e is envelope and r is remote and not store._lock._is_owned()
        entered.set()
        assert resume.wait(5)
        return True

    def commit_worker():
        try:
            results.append(store.commit_verified_remote_image_batch_for_characterization(
                envelope, prepared, remote, observations, host_freshness=slow_freshness))
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=commit_worker)
    worker.start()
    assert entered.wait(5)
    with pytest.raises(ValueError, match="already_attempted"):
        store.commit_verified_remote_image_batch_for_characterization(
            envelope, prepared, remote, observations, host_freshness=Mock(return_value=True))
    resume.set()
    worker.join(10)
    assert not worker.is_alive() and not errors and len(results) == 1
    assert store.inspect_verified_remote_image_batch_for_characterization(results[0]) is results[0]
    assert not store._uncertain


def test_real_native_batch_close_during_host_check_withholds_receipt_and_retains_files(owner):
    store, _, _ = owner
    values = bound(images=2)
    observations = tuple(stage(store, values, Stream(image_bytes()), index=index) for index in range(2))
    envelope, prepared, remote = values
    entered, resume = threading.Event(), threading.Event()
    errors = []

    def slow_freshness(e, r):
        assert e is envelope and r is remote and not store._lock._is_owned()
        entered.set()
        assert resume.wait(5)
        return True

    def commit_worker():
        try:
            store.commit_verified_remote_image_batch_for_characterization(
                envelope, prepared, remote, observations, host_freshness=slow_freshness)
        except BaseException as exc:
            errors.append(exc)

    paths = [record[0] for record in store._files.values()]
    worker = threading.Thread(target=commit_worker)
    worker.start()
    assert entered.wait(5)
    store.close()
    resume.set()
    worker.join(10)
    assert not worker.is_alive() and len(errors) == 1
    assert isinstance(errors[0], ValueError) and not store._stream_batches
    assert store._closed and store._uncertain
    assert all(path.exists() and path.read_bytes() == image_bytes() for path in paths)


def test_real_native_protected_batch_acceptance_is_distinct_exact_and_one_shot(owner):
    store, _, _ = owner
    values = bound(images=2)
    fresh = lambda e, r: e is values[0] and r is values[2]
    observations = tuple(stage(store, values, Stream(image_bytes()), fresh=fresh, index=index)
                         for index in range(2))
    batch = store.commit_verified_remote_image_batch_for_characterization(
        *values, observations, host_freshness=fresh)
    acceptor = acceptance(store, values, batch, fresh)

    accepted = acceptor.accept_for_characterization()

    assert type(accepted) is AcceptedProtectedOutputBatch
    assert not isinstance(accepted, (LocalOutputReceipt, PromotedImage, a.VerifiedProtectedImageBatchReceipt))
    assert accepted.batch_identity == batch.identity and accepted.image_count == 2
    assert accepted._protected_owner is store and accepted._batch_receipt is batch
    assert accepted._envelope is values[0] and accepted._prepared is values[1] and accepted._remote is values[2]
    assert store._stream_batch_acceptances[(values[1].request_id, values[2].identity)] is accepted
    assert acceptor.inspect_for_characterization(accepted) is accepted
    with pytest.raises(ValueError, match="acceptance_owner_mismatch"):
        acceptor.inspect_for_characterization(replace(accepted))
    with pytest.raises(ValueError, match="acceptance_already_attempted"):
        acceptor.accept_for_characterization()
    assert not hasattr(store, "_records") and not hasattr(store, "_remote") and not hasattr(store, "_storage")
    assert all(path.exists() and path.read_bytes() == image_bytes() for path, *_ in store._files.values())
    assert store.readiness()["accepted_batch_count"] == 1
    assert acceptor.readiness()["authorship"] == "unverified"
    assert acceptor.readiness()["execution_available"] is False
    assert acceptor.readiness()["protected_storage_available"] is False
    assert acceptor.readiness()["promotion_available"] is False
    assert acceptor.readiness()["recovery_execution_allowed"] is False
    assert acceptor.readiness()["human_start_allowed"] is False
    assert acceptor.readiness()["publication_allowed"] is False
    paths = [path for path, *_ in store._files.values()]
    store.close()
    with pytest.raises(ValueError, match="closed_observation"):
        acceptor.inspect_for_characterization(accepted)
    assert all(path.exists() and path.read_bytes() == image_bytes() for path in paths)


@pytest.mark.parametrize("substitution", ["copied_batch", "other_freshness"])
def test_real_native_acceptance_rejects_copied_or_substituted_evidence_without_consuming_batch(owner, substitution):
    store, _, _ = owner
    values = bound()
    fresh = Mock(return_value=True)
    observation = stage(store, values, Stream(image_bytes()), fresh=fresh)
    batch = store.commit_verified_remote_image_batch_for_characterization(
        *values, (observation,), host_freshness=fresh)
    current = replace(batch) if substitution == "copied_batch" else batch
    other_freshness = Mock(return_value=True) if substitution == "other_freshness" else fresh
    acceptor = acceptance(store, values, current, other_freshness)
    fresh_calls, other_calls = fresh.call_count, other_freshness.call_count

    with pytest.raises(ValueError, match="batch_owner_mismatch|host_freshness_owner_mismatch"):
        acceptor.accept_for_characterization()

    assert fresh.call_count == fresh_calls
    assert other_freshness.call_count == other_calls
    assert not store._stream_batch_acceptances
    assert next(iter(store._files.values()))[0].exists()
    assert not store._uncertain
    correct = acceptance(store, values, batch, fresh)
    assert correct.accept_for_characterization().batch_identity == batch.identity


def test_real_native_acceptance_rejects_incomplete_batch_before_host_freshness(owner):
    store, _, _ = owner
    values = bound(images=2)
    fresh = Mock(return_value=True)
    observations = tuple(stage(store, values, Stream(image_bytes()), fresh=fresh, index=index)
                         for index in range(2))
    batch = store.commit_verified_remote_image_batch_for_characterization(
        *values, observations, host_freshness=fresh)
    incomplete = replace(batch, observations=observations[:1])
    calls = fresh.call_count

    with pytest.raises(ValueError, match="protected_acceptance_binding_invalid"):
        acceptance(store, values, incomplete, fresh)

    assert fresh.call_count == calls
    assert store._stream_batch_acceptances == {}
    assert all(path.exists() and path.read_bytes() == image_bytes() for path, *_ in store._files.values())


def test_real_native_acceptance_rejects_receipt_from_another_protected_owner(owner):
    store, scope, _ = owner
    values = bound()
    fresh = lambda e, r: e is values[0] and r is values[2]
    observation = stage(store, values, Stream(image_bytes()), fresh=fresh)
    batch = store.commit_verified_remote_image_batch_for_characterization(
        *values, (observation,), host_freshness=fresh)
    path = next(iter(store._files.values()))[0]

    with a.WindowsProtectedAssetsCharacterization.provision_for_characterization(
            str(scope), characterization=True, disposable_opt_in=True) as other_owner:
        acceptor = acceptance(other_owner, values, batch, fresh)
        with pytest.raises(ValueError, match="storage_owner_mismatch"):
            acceptor.accept_for_characterization()
        assert not other_owner._stream_batch_acceptances
        assert not store._stream_batch_acceptances
        assert path.exists() and path.read_bytes() == image_bytes()

    correct = acceptance(store, values, batch, fresh)
    assert correct.accept_for_characterization().batch_identity == batch.identity


@pytest.mark.parametrize("drift", ["content", "acl"])
def test_real_native_acceptance_revalidates_content_and_acl_retaining_evidence(owner, drift):
    store, _, api = owner
    values = bound()
    fresh = lambda e, r: e is values[0] and r is values[2]
    observation = stage(store, values, Stream(image_bytes()), fresh=fresh)
    batch = store.commit_verified_remote_image_batch_for_characterization(
        *values, (observation,), host_freshness=fresh)
    path = next(iter(store._files.values()))[0]
    retained_bytes = image_bytes()
    if drift == "content":
        retained_bytes = image_bytes("PNG", (4, 4))
        path.write_bytes(retained_bytes)
    else:
        mutate_disposable_acl(path, api, "changed_owner_only")
    acceptor = acceptance(store, values, batch, fresh)

    with pytest.raises(ValueError, match="content_changed|native_observation_changed|unsafe_acl|unsupported_acl"):
        acceptor.accept_for_characterization()

    assert not store._stream_batch_acceptances and path.exists()
    assert path.read_bytes() == retained_bytes  # drifted evidence is retained, never cleaned
    if drift == "acl":
        mutate_disposable_acl(path, api, "original")


def test_real_native_acceptance_rejects_stale_original_host_and_retains_evidence(owner):
    store, _, _ = owner
    values = bound()
    current = [True]
    fresh = lambda e, r: current[0] and e is values[0] and r is values[2]
    observation = stage(store, values, Stream(image_bytes()), fresh=fresh)
    batch = store.commit_verified_remote_image_batch_for_characterization(
        *values, (observation,), host_freshness=fresh)
    current[0] = False
    acceptor = acceptance(store, values, batch, fresh)

    with pytest.raises(ValueError, match="host_freshness_lost"):
        acceptor.accept_for_characterization()

    path = next(iter(store._files.values()))[0]
    assert not store._stream_batch_acceptances and path.exists() and path.read_bytes() == image_bytes()
    assert acceptor.readiness()["acceptance"] == "uncertain"
    with pytest.raises(ValueError, match="acceptance_invalidated"):
        acceptor.accept_for_characterization()


def test_real_native_acceptance_duplicate_race_is_one_shot(owner):
    store, _, _ = owner
    values = bound()
    hold, entered, resume = [False], threading.Event(), threading.Event()

    def fresh(envelope, remote):
        assert envelope is values[0] and remote is values[2]
        if hold[0]:
            entered.set()
            assert resume.wait(5)
        return True

    observation = stage(store, values, Stream(image_bytes()), fresh=fresh)
    batch = store.commit_verified_remote_image_batch_for_characterization(
        *values, (observation,), host_freshness=fresh)
    first, second = acceptance(store, values, batch, fresh), acceptance(store, values, batch, fresh)
    hold[0] = True
    results, errors = [], []

    def worker():
        try:
            results.append(first.accept_for_characterization())
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(5)
    with pytest.raises(ValueError, match="acceptance_already_attempted"):
        second.accept_for_characterization()
    resume.set()
    thread.join(10)

    assert not thread.is_alive() and not errors and len(results) == 1
    assert store._stream_batch_acceptances[(values[1].request_id, values[2].identity)] is results[0]
    assert first.inspect_for_characterization(results[0]) is results[0]
    assert next(iter(store._files.values()))[0].read_bytes() == image_bytes()


@pytest.mark.parametrize("loser", ["protected_close", "acceptance_close", "acceptance_invalidation"])
def test_real_native_acceptance_race_with_close_or_invalidation_withholds_acceptance(owner, loser):
    store, _, _ = owner
    values = bound()
    hold, entered, resume = [False], threading.Event(), threading.Event()

    def fresh(envelope, remote):
        assert envelope is values[0] and remote is values[2]
        if hold[0]:
            entered.set()
            assert resume.wait(5)
        return True

    observation = stage(store, values, Stream(image_bytes()), fresh=fresh)
    batch = store.commit_verified_remote_image_batch_for_characterization(
        *values, (observation,), host_freshness=fresh)
    acceptor = acceptance(store, values, batch, fresh)
    path = next(iter(store._files.values()))[0]
    hold[0] = True
    errors = []

    def worker():
        try:
            acceptor.accept_for_characterization()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(5)
    if loser == "protected_close":
        store.close()
    elif loser == "acceptance_close":
        acceptor.close()
    else:
        acceptor.invalidate_for_characterization()
    resume.set()
    thread.join(10)

    assert not thread.is_alive() and len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert not store._stream_batch_acceptances and path.exists() and path.read_bytes() == image_bytes()
    assert acceptor.readiness()["acceptance"] in ("closed", "invalidated", "uncertain")


@pytest.mark.parametrize("terminal_action", ["close", "invalidate"])
def test_real_native_acceptance_commit_is_atomic_against_close_or_invalidation(owner, terminal_action):
    store, _, _ = owner
    values = bound()
    fresh = lambda envelope, remote: envelope is values[0] and remote is values[2]
    observation = stage(store, values, Stream(image_bytes()), fresh=fresh)
    batch = store.commit_verified_remote_image_batch_for_characterization(
        *values, (observation,), host_freshness=fresh)
    acceptor = acceptance(store, values, batch, fresh)
    key = (values[1].request_id, values[2].identity)
    publish_started, allow_publish = threading.Event(), threading.Event()
    terminal_attempted, terminal_outcome = threading.Event(), []
    terminal_finished = threading.Event()
    results, errors = [], []

    class GateAcceptancePublication(dict):
        def __setitem__(self, item_key, value):
            if item_key == key:
                publish_started.set()
                assert allow_publish.wait(5)
            super().__setitem__(item_key, value)

    class ObserveProtectedOwnerLock:
        def __init__(self, inner):
            self.inner = inner
            self.terminal_attempt_observed = False

        def __enter__(self):
            if (threading.current_thread().name == "acceptance-terminal"
                    and not self.terminal_attempt_observed):
                self.terminal_attempt_observed = True
                if self.inner.acquire(blocking=False):
                    terminal_outcome.append("acquired_before_publication")
                    terminal_attempted.set()
                    return self
                terminal_outcome.append("blocked_by_publication")
                terminal_attempted.set()
            self.inner.acquire()
            return self

        def __exit__(self, exc_type, exc_value, tb):
            self.inner.release()

    store._stream_batch_acceptances = GateAcceptancePublication(store._stream_batch_acceptances)
    # close() / invalidate() enter the protected owner before the acceptance
    # owner, matching the production lock order (protected -> acceptance).
    store._lock = ObserveProtectedOwnerLock(store._lock)

    def accept():
        try:
            results.append(acceptor.accept_for_characterization())
        except BaseException as error:
            errors.append(error)

    def invalidate_or_close():
        try:
            if terminal_action == "close":
                acceptor.close()
            else:
                acceptor.invalidate_for_characterization()
        except BaseException as error:
            errors.append(error)
        finally:
            terminal_finished.set()

    accept_thread = threading.Thread(target=accept)
    accept_thread.start()
    terminal_thread = None
    try:
        assert publish_started.wait(5)
        terminal_thread = threading.Thread(target=invalidate_or_close, name="acceptance-terminal")
        terminal_thread.start()
        assert terminal_attempted.wait(5)
        assert terminal_outcome == ["blocked_by_publication"]
        assert key not in store._stream_batch_acceptances
        assert not terminal_finished.is_set()
    finally:
        allow_publish.set()
    accept_thread.join(10)
    if terminal_thread is not None:
        terminal_thread.join(10)

    assert not accept_thread.is_alive()
    assert terminal_thread is not None and not terminal_thread.is_alive()
    assert terminal_finished.is_set() and not errors and len(results) == 1
    accepted = results[0]
    assert type(accepted) is AcceptedProtectedOutputBatch
    assert store._stream_batch_acceptances[key] is accepted
    assert acceptor._receipt is accepted
    assert acceptor.readiness()["acceptance"] == ("closed" if terminal_action == "close" else "invalidated")
    with pytest.raises(ValueError, match="acceptance_closed|acceptance_invalidated"):
        acceptor.inspect_for_characterization(accepted)
    path = next(iter(store._files.values()))[0]
    assert path.exists() and path.read_bytes() == image_bytes()


def test_modules_resolve_to_this_isolated_worktree():
    root = Path(__file__).resolve().parents[1]
    assert Path(a.__file__).resolve().is_relative_to(root)
    assert Path(w.__file__).resolve().is_relative_to(root)
