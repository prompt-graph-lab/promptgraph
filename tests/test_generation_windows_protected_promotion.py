"""Offline and real disposable Windows contracts for protected promotion."""
from dataclasses import FrozenInstanceError, replace
import threading
from unittest.mock import patch

import pytest

from core import generation_windows_protected_assets as assets
from core import generation_windows_protected_storage as storage
from core import generation_windows_protected_promotion as promotion
from core.comfy_output_containment import ContainmentLimits
from core.generation_output_promotion import DurableGenerationAssets, PromotedImage
from test_comfy_output_containment import image_bytes
from test_generation_windows_protected_stream import Stream, acceptance, bound, stage
from test_generation_windows_protected_assets import owner, assert_closed_gates
from test_generation_windows_protected_storage import native_scope, mutate_disposable_acl


def accepted_batch(store, *, count=1, freshness=None):
    values = bound(images=count)
    freshness = freshness or (lambda envelope, remote: envelope is values[0] and remote is values[2])
    source_bytes = tuple(image_bytes(size=(3 + index, 4 + index)) for index in range(count))
    observations = tuple(stage(store, values, Stream(source_bytes[index]), fresh=freshness, index=index)
                         for index in range(count))
    batch = store.commit_verified_remote_image_batch_for_characterization(
        *values, observations, host_freshness=freshness)
    acceptance_owner = acceptance(store, values, batch, freshness)
    accepted = acceptance_owner.accept_for_characterization()
    return values, freshness, source_bytes, batch, acceptance_owner, accepted


def new_promotion(store, acceptance_owner, accepted):
    return promotion.ProtectedDurablePromotionCharacterization.create_for_characterization(
        store, acceptance_owner, accepted, characterization=True, disposable_opt_in=True)


def test_portable_protected_promotion_refuses_missing_opt_in_and_fabricated_owners():
    assert not promotion.ProtectedDurablePromotionCharacterization.execution_available
    assert not promotion.ProtectedDurablePromotionCharacterization.protected_storage_available
    assert not promotion.ProtectedDurablePromotionCharacterization.promotion_available
    with pytest.raises(ValueError, match="execution_unavailable"):
        promotion.ProtectedDurablePromotionCharacterization.create_for_characterization(
            object(), object(), object())
    with pytest.raises(ValueError, match="protected_promotion_binding_invalid"):
        promotion.ProtectedDurablePromotionCharacterization.create_for_characterization(
            object(), object(), object(), characterization=True, disposable_opt_in=True)
    with pytest.raises(ValueError, match="host_protected_promotion_required"):
        promotion.ProtectedDurablePromotionCharacterization(object(), object(), object())


def test_real_native_single_and_multiple_image_promotion_is_exact_and_distinct(owner):
    store, _, api = owner
    acceptance_ref, promotion_ref, expected_binding = {}, {}, {}
    def freshness(envelope, remote):
        assert not store._lock._is_owned()
        if acceptance_ref:
            assert not acceptance_ref["owner"]._lock._is_owned()
        if promotion_ref:
            assert not promotion_ref["owner"]._lock._is_owned()
        if expected_binding:
            assert envelope is expected_binding["envelope"] and remote is expected_binding["remote"]
        return True
    values, _, originals, batch, acceptor, accepted = accepted_batch(
        store, count=2, freshness=freshness)
    acceptance_ref["owner"] = acceptor
    expected_binding.update(envelope=values[0], remote=values[2])
    source_paths = tuple(store._files[(item.image.purpose, item.image.storage_identity)][0]
                         for item in batch.observations)
    source_before = tuple(path.read_bytes() for path in source_paths)
    promoter = new_promotion(store, acceptor, accepted)
    promotion_ref["owner"] = promoter

    receipt = promoter.promote_for_characterization()

    assert type(receipt) is promotion.VerifiedProtectedPromotionReceipt
    assert not isinstance(receipt, (PromotedImage, DurableGenerationAssets))
    assert receipt._promotion_owner is promoter and receipt._protected_owner is store
    assert receipt._acceptance_owner is acceptor and receipt._accepted is accepted
    assert receipt.accepted_identity == accepted.identity and receipt.batch_identity == batch.identity
    assert receipt.job_id == accepted._remote.job_id
    assert receipt.prompt_id == accepted._remote.prompt_id
    assert len(receipt.images) == 2
    assert tuple(row.descriptor_identity for row in receipt.images) == tuple(
        item.identity for item in accepted._remote.images)
    assert len({row.promoted_image.storage_identity for row in receipt.images}) == 2
    for index, row in enumerate(receipt.images):
        assert row.source_observation is batch.observations[index]
        image = row.promoted_image
        assert image.purpose == "promoted_assets"
        assert image.content_sha256 == batch.observations[index].image.content_sha256
        assert image.byte_count == batch.observations[index].image.byte_count == len(originals[index])
        destination = store._files[("promoted_assets", image.storage_identity)]
        path, handle, native_identity, acl = destination
        assert path.parent == store._roots["promoted_assets"]._path
        assert path.read_bytes() == originals[index]
        assert storage._identity(handle) == native_identity == storage._ordinary(path, directory=False)
        assert storage._acl(handle, api, storage._current_user(api)) == acl[0]
        assert len(acl[0]) == 1 and acl[0][0][1] == 3
        source = batch.observations[index].image
        source_path, source_handle, source_identity, source_acl = store._files[
            ("temporary_containment", source.storage_identity)]
        assert storage._identity(source_handle) == source_identity == storage._ordinary(
            source_path, directory=False)
        assert storage._acl(source_handle, api, storage._current_user(api)) == source_acl[0]
        assert len(source_acl[0]) == 1 and source_acl[0][0][1] == 3
        assert_closed_gates(promoter.readiness())
    assert tuple(path.read_bytes() for path in source_paths) == source_before
    assert promoter.inspect_for_characterization(receipt) is receipt
    with pytest.raises(FrozenInstanceError):
        receipt.identity = "changed"
    with pytest.raises(FrozenInstanceError):
        receipt.images[0].descriptor_identity = "changed"
    assert store._stream_promotions[(values[1].request_id, values[2].identity)] is receipt
    assert store.readiness()["protected_promotion_count"] == 1
    assert promoter.readiness()["image_count"] == 2
    assert promoter.readiness()["authorship"] == "unverified"
    assert promoter.readiness()["execution_available"] is False


@pytest.mark.parametrize("substitution", ["missing", "copy", "substituted", "other_acceptance", "cross_owner"])
def test_real_native_promotion_requires_exact_accepted_owner(owner, substitution):
    store, scope, _ = owner
    values, fresh, _, batch, acceptor, accepted = accepted_batch(store)
    with pytest.raises(ValueError, match="protected_promotion_binding_invalid"):
        if substitution == "missing":
            new_promotion(store, acceptor, None)
        elif substitution == "copy":
            new_promotion(store, acceptor, replace(accepted))
        elif substitution == "substituted":
            new_promotion(store, acceptor, replace(accepted, identity="f" * 64))
        elif substitution == "other_acceptance":
            other = acceptance(store, values, batch, fresh)
            new_promotion(store, other, accepted)
        else:
            with assets.WindowsProtectedAssetsCharacterization.provision_for_characterization(
                    str(scope), characterization=True, disposable_opt_in=True) as other_store:
                new_promotion(other_store, acceptor, accepted)
    assert not store._stream_promotions
    assert all(path.exists() and path.read_bytes() == image_bytes(size=(3, 4))
               for path, *_ in store._files.values())


@pytest.mark.parametrize("drift", ["content", "acl"])
def test_real_native_promotion_revalidates_source_identity_acl_and_bytes(owner, drift):
    store, _, api = owner
    _, _, _, batch, acceptor, accepted = accepted_batch(store)
    path = store._files[("temporary_containment", batch.observations[0].image.storage_identity)][0]
    before = path.read_bytes()
    if drift == "content":
        path.write_bytes(image_bytes(size=(11, 12)))
    else:
        mutate_disposable_acl(path, api, "writable_principal")
    promoter = new_promotion(store, acceptor, accepted)

    with pytest.raises(ValueError, match=("native_observation_changed|content_changed|inspect_only_or_uncertain"
                                         "|unsafe_acl")):
        promoter.promote_for_characterization()

    assert not any(purpose == "promoted_assets" for purpose, *_ in store._files)
    assert path.exists() and path.read_bytes() != b""
    if drift == "content":
        assert path.read_bytes() != before
    assert not store._stream_promotions
    assert promoter.readiness()["promotion"] == "uncertain"


def test_real_native_promotion_freshness_loss_retains_staging_without_destination(owner):
    store, _, _ = owner
    current = {"fresh": True}
    values, fresh, _, _, acceptor, accepted = accepted_batch(
        store, freshness=lambda envelope, remote: current["fresh"])
    current["fresh"] = False
    promoter = new_promotion(store, acceptor, accepted)

    with pytest.raises(ValueError, match="host_freshness_lost"):
        promoter.promote_for_characterization()

    assert not any(purpose == "promoted_assets" for purpose, *_ in store._files)
    assert len(store._stream_promotion_attempts) == 1
    assert not store._stream_promotions
    assert all(path.exists() for path, *_ in store._files.values())
    with pytest.raises(ValueError, match="promotion_already_attempted"):
        promoter.promote_for_characterization()


def test_real_native_host_freshness_loss_after_destination_check_withholds_batch_receipt(owner):
    store, _, _ = owner
    current = {"fresh": True}
    _, _, originals, _, acceptor, accepted = accepted_batch(
        store, freshness=lambda envelope, remote: current["fresh"])
    promoter = new_promotion(store, acceptor, accepted)
    original_inspect = store.inspect_image_for_characterization
    def lose_freshness_after_promoted_check(image):
        result = original_inspect(image)
        if image.purpose == "promoted_assets":
            current["fresh"] = False
        return result
    store.inspect_image_for_characterization = lose_freshness_after_promoted_check

    with pytest.raises(ValueError, match="host_freshness_lost"):
        promoter.promote_for_characterization()

    destinations = [path for key, (path, *_rest) in store._files.items() if key[0] == "promoted_assets"]
    assert len(destinations) == 1 and destinations[0].read_bytes() == originals[0]
    assert not store._stream_promotions


@pytest.mark.parametrize("drift", ["content", "acl"])
def test_real_native_promoted_destination_drift_is_retained_and_not_inspectable(owner, drift):
    store, _, api = owner
    _, _, _, _, acceptor, accepted = accepted_batch(store)
    promoter = new_promotion(store, acceptor, accepted)
    receipt = promoter.promote_for_characterization()
    row = receipt.images[0]
    path = store._files[("promoted_assets", row.promoted_image.storage_identity)][0]
    before = path.read_bytes()
    if drift == "content":
        path.write_bytes(image_bytes(size=(15, 16)))
    else:
        mutate_disposable_acl(path, api, "writable_principal")

    with pytest.raises(ValueError, match=("native_observation_changed|content_changed|inspect_only_or_uncertain"
                                         "|unsafe_acl")):
        promoter.inspect_for_characterization(receipt)

    assert path.exists()
    if drift == "content":
        assert path.read_bytes() != before
    assert promoter.readiness()["promotion"] == "uncertain"


@pytest.mark.parametrize("failure", ["after_file_create", "after_file_write", "after_file_sync", "short_write", "flush"])
def test_real_native_failed_or_incomplete_copy_retains_destination_and_never_retries(owner, failure):
    store, _, _ = owner
    _, _, originals, _, acceptor, accepted = accepted_batch(store)
    if failure.startswith("after_file_"):
        def fault(boundary):
            if boundary == failure:
                raise RuntimeError("injected copy failure")
        store._fault = fault
    elif failure in {"short_write", "flush"}:
        root = store._roots["promoted_assets"]
        file_api = root._api[2]
        if failure == "short_write":
            original_write = file_api.WriteFile
            def short_write(handle, data):
                partial = data[:max(1, len(data) // 2)]
                return original_write(handle, partial)
            patcher = patch.object(file_api, "WriteFile", side_effect=short_write)
        else:
            patcher = patch.object(file_api, "FlushFileBuffers", side_effect=OSError("injected flush failure"))
        patcher.start()
    promoter = new_promotion(store, acceptor, accepted)
    try:
        with pytest.raises((ValueError, RuntimeError)):
            promoter.promote_for_characterization()
    finally:
        if failure in {"short_write", "flush"}:
            patcher.stop()

    destinations = [(key, value) for key, value in store._files.items() if key[0] == "promoted_assets"]
    assert len(destinations) == 1
    path, handle, identity, acl = destinations[0][1]
    assert path.exists()
    assert storage._identity(handle) == identity == storage._ordinary(path, directory=False)
    assert storage._acl(handle, store._roots["promoted_assets"]._api,
                        store._roots["promoted_assets"]._user) == acl[0]
    if failure == "after_file_create":
        assert path.read_bytes() == b""
    elif failure == "short_write":
        assert 0 < len(path.read_bytes()) < len(originals[0])
    else:
        assert path.read_bytes() == originals[0]
    assert not store._stream_promotions
    assert promoter.readiness()["promotion"] == "uncertain"
    with pytest.raises(ValueError, match="promotion_already_attempted"):
        promoter.promote_for_characterization()
    assert path.exists()


def test_real_native_partial_multi_image_promotion_has_no_batch_success(owner):
    store, _, _ = owner
    _, _, originals, _, acceptor, accepted = accepted_batch(store, count=2)
    count = {"created": 0}
    def fault(boundary):
        if boundary == "after_file_create":
            count["created"] += 1
            if count["created"] == 2:
                raise RuntimeError("second destination interrupted")
    store._fault = fault
    promoter = new_promotion(store, acceptor, accepted)

    with pytest.raises(ValueError, match="protected_promotion_uncertain"):
        promoter.promote_for_characterization()

    destinations = [record[0] for key, record in store._files.items() if key[0] == "promoted_assets"]
    assert len(destinations) == 2
    assert sorted(path.read_bytes() for path in destinations) == sorted((b"", originals[0]))
    assert not store._stream_promotions
    assert all(path.exists() for path in destinations)


def test_real_native_capacity_failure_is_one_shot_and_retains_source(native_scope):
    scope, _ = native_scope
    data = image_bytes(size=(3, 4))
    limits = ContainmentLimits(image_bytes=len(data), request_bytes=len(data),
                               aggregate_bytes=len(data) + 1, images=2)
    with assets.WindowsProtectedAssetsCharacterization.provision_for_characterization(
            str(scope), characterization=True, disposable_opt_in=True, limits=limits) as store:
        _, _, _, _, acceptor, accepted = accepted_batch(store)
        promoter = new_promotion(store, acceptor, accepted)
        source_path = next(path for path, *_ in store._files.values())
        with pytest.raises(ValueError, match="storage_capacity"):
            promoter.promote_for_characterization()
        assert source_path.exists()
        assert not any(key[0] == "promoted_assets" for key in store._files)
        assert not store._stream_promotions
        with pytest.raises(ValueError, match="promotion_already_attempted"):
            promoter.promote_for_characterization()


@pytest.mark.parametrize("stale_action", ["protected_close", "acceptance_invalidate"])
def test_real_native_close_or_invalidation_before_final_commit_retains_copy(owner, stale_action):
    store, _, _ = owner
    _, _, _, _, acceptor, accepted = accepted_batch(store)
    promoter = new_promotion(store, acceptor, accepted)
    entered, resume = threading.Event(), threading.Event()
    original = promoter._build_receipt
    def gated(rows):
        entered.set()
        assert resume.wait(5)
        return original(rows)
    promoter._build_receipt = gated
    results, errors = [], []
    def run():
        try:
            results.append(promoter.promote_for_characterization())
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(5)
    if stale_action == "protected_close":
        store.close()
    else:
        acceptor.invalidate_for_characterization()
    resume.set()
    thread.join(10)

    assert not thread.is_alive() and not results and len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert not store._stream_promotions
    assert any(key[0] == "promoted_assets" for key in store._files)
    assert all(path.exists() for path, *_ in store._files.values())


@pytest.mark.parametrize("terminal_action", ["protected_close", "acceptance_invalidate"])
def test_real_native_commit_boundary_serializes_terminal_action(owner, terminal_action):
    store, _, _ = owner
    _, _, _, _, acceptor, accepted = accepted_batch(store)
    promoter = new_promotion(store, acceptor, accepted)
    key = (accepted._prepared.request_id, accepted._remote.identity)
    publish_started, allow_publish = threading.Event(), threading.Event()
    terminal_attempted, terminal_outcome, terminal_finished = threading.Event(), [], threading.Event()
    results, errors = [], []

    class GatePublication(dict):
        def __setitem__(self, item_key, value):
            if item_key == key:
                publish_started.set()
                assert allow_publish.wait(5)
            super().__setitem__(item_key, value)

    class ObserveLock:
        def __init__(self, inner):
            self.inner = inner
        def __enter__(self):
            if threading.current_thread().name == "promotion-terminal":
                if self.inner.acquire(blocking=False):
                    terminal_outcome.append("acquired_before_commit")
                    terminal_attempted.set()
                    return self
                terminal_outcome.append("blocked_by_commit")
                terminal_attempted.set()
            self.inner.acquire()
            return self
        def __exit__(self, exc_type, exc_value, tb):
            self.inner.release()

    store._stream_promotions = GatePublication(store._stream_promotions)
    # Both terminal operations enter through the protected owner first, which
    # preserves the protected -> acceptance lock order used by promotion.
    store._lock = ObserveLock(store._lock)

    def run():
        try:
            results.append(promoter.promote_for_characterization())
        except BaseException as error:
            errors.append(error)
    def terminal():
        try:
            if terminal_action == "protected_close":
                store.close()
            else:
                acceptor.invalidate_for_characterization()
        except BaseException as error:
            errors.append(error)
        finally:
            terminal_finished.set()

    worker = threading.Thread(target=run, name="promotion-worker")
    worker.start()
    terminal_thread = None
    try:
        assert publish_started.wait(5)
        terminal_thread = threading.Thread(target=terminal, name="promotion-terminal")
        terminal_thread.start()
        assert terminal_attempted.wait(5)
        assert terminal_outcome == ["blocked_by_commit"]
    finally:
        allow_publish.set()
    worker.join(10)
    assert terminal_thread is not None
    terminal_thread.join(10)

    assert not worker.is_alive() and not terminal_thread.is_alive()
    assert terminal_finished.is_set() and not errors and len(results) == 1
    receipt = results[0]
    assert type(receipt) is promotion.VerifiedProtectedPromotionReceipt
    assert store._stream_promotions[key] is receipt and promoter._receipt is receipt
    if terminal_action == "protected_close":
        assert store.readiness()["asset_observation"] == "closed"
    else:
        assert acceptor.readiness()["acceptance"] == "invalidated"
    with pytest.raises(ValueError, match=("promotion_closed|protected_promotion_invalidated|closed_observation"
                                         "|acceptance_invalidated")):
        promoter.inspect_for_characterization(receipt)


def test_real_native_duplicate_promotion_owners_and_calls_do_not_copy_twice(owner):
    store, _, _ = owner
    _, _, originals, _, acceptor, accepted = accepted_batch(store)
    first = new_promotion(store, acceptor, accepted)
    second = new_promotion(store, acceptor, accepted)
    receipt = first.promote_for_characterization()
    paths = [path for key, (path, *_rest) in store._files.items() if key[0] == "promoted_assets"]
    with pytest.raises(ValueError, match="promotion_already_attempted"):
        first.promote_for_characterization()
    with pytest.raises(ValueError, match="promotion_already_attempted"):
        second.promote_for_characterization()
    assert first._receipt is receipt and store._stream_promotions[(accepted._prepared.request_id,
        accepted._remote.identity)] is receipt
    assert len(paths) == 1 and paths[0].read_bytes() == originals[0]
