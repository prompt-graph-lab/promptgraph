"""Focused C2B-8D-17A storage admission characterization tests."""
from dataclasses import replace
import hashlib
import sys
import threading
from types import SimpleNamespace

import pytest

from core import generation_storage_admission as admission
from core import generation_multi_request_journal as multi_journal
from core import generation_ownership_journal as journal
from core import generation_protected_journal as protected_journal
from core import generation_windows_protected_storage as windows


def _limits(*, assets=100, retained=100):
    return admission.ProtectedStorageCapacityLimits(
        journal_bytes=1000, shared_temporary_and_promoted_bytes=assets,
        retained_uncertain_bytes=retained, journal_entries=20,
        shared_temporary_and_promoted_entries=4, retained_uncertain_entries=20)


def _empty_inventory():
    return {purpose: {} for purpose in admission._WRITABLE}


def _ready_ledger(limits=None, inventory=None):
    result = admission._CapacityLedger(limits or _limits())
    result.set_initial_inventory(inventory or _empty_inventory())
    return result


def _journal_replacement_rig(*, limits=None, inventory=None, operation_id="journal-operation"):
    limits = limits or admission.ProtectedStorageCapacityLimits(
        journal_bytes=admission._JOURNAL_BYTES,
        shared_temporary_and_promoted_bytes=100,
        retained_uncertain_bytes=100,
        journal_entries=20,
        shared_temporary_and_promoted_entries=4,
        retained_uncertain_entries=20)
    root = object()
    owner = SimpleNamespace(_roots={"private_journal": root})
    journal_owner = SimpleNamespace(_native=root)
    ledger = admission._CapacityLedger(limits, owner_identity=owner)
    ledger.set_initial_inventory(inventory or _empty_inventory())
    operation = ledger.begin_operation(operation_id)
    writer_operation = SimpleNamespace(operation_id=operation_id)
    writer = SimpleNamespace(operation=writer_operation, filename=operation_id + ".json",
        _revision=0, _digest="0" * 64, _file_identity=None, _uncertain=False, _closed=False)
    return ledger, owner, journal_owner, operation, writer


def _journal_binding(ledger, owner, journal_owner, operation, writer, *, schema=None):
    filename = writer.filename
    prior_record = ledger._journal_files.get(filename)
    if writer._revision and prior_record is not None:
        prior_ack = prior_record["acknowledgement"]
    else:
        prior_ack = None
    row = ledger._inventory["private_journal"].get(filename)
    return admission._JournalReplacementBinding(
        owner, journal_owner, owner._roots["private_journal"], writer,
        schema or admission.journal.SCHEMA, writer.operation.operation_id, filename,
        writer._revision, writer._digest, writer._file_identity, row, prior_ack,
        admission._freeze_inventory(ledger._inventory),
        admission._JOURNAL_REPLACEMENT_ISSUER)


def _journal_after_inventory(ledger, writer, data_size, *, native_identity, file_identity,
                             binding=None, acl=("protected-acl",)):
    inventory = {purpose: dict(entries) for purpose, entries in ledger._inventory.items()}
    digest = f"{writer._revision + 1:064x}"
    row = (native_identity, data_size, acl)
    inventory["private_journal"][writer.filename] = row
    writer._revision += 1
    writer._digest = digest
    writer._file_identity = file_identity
    acknowledgement = admission.journal.ReopenedJournal(
        writer.operation, (), writer._revision, digest, file_identity)
    completion = admission._JournalReplacementCompletion(
        binding, acknowledgement, file_identity, row,
        admission._JOURNAL_REPLACEMENT_ISSUER)
    return inventory, acknowledgement, completion


def _commit_portable_journal_replacement(ledger, owner, journal_owner, operation, writer,
                                        *, data_size, native_identity, file_identity,
                                        acl=("protected-acl",), free_bytes=4 * 1024 * 1024):
    binding = _journal_binding(ledger, owner, journal_owner, operation, writer)
    write = ledger.admit_journal_replacement(operation, binding)
    inventory, acknowledgement, completion = _journal_after_inventory(
        ledger, writer, data_size, native_identity=native_identity,
        file_identity=file_identity, binding=binding, acl=acl)
    summary = ledger.complete_journal_replacement(
        operation, write, inventory, free_bytes, completion)
    return write, binding, acknowledgement, summary


def _native_journal_operation(scope):
    project_path = scope / "selected-project.json"
    approved = journal.ApprovedRoot.capture_for_characterization(
        "project", str(scope), characterization=True)
    operation = journal.OperationObservation(
        "replacement-operation", "job", "manifest",
        hashlib.sha256(project_path.read_bytes()).hexdigest(), approved.key,
        approved.path, approved.identity, project_path.name,
        journal._file_identity(journal._ordinary(project_path, directory=False)),
        "process", "session", "claim", "c" * 64,
        (journal.FrozenRequestCorrelation("request", 0, "line", 1, "workflow"),))
    return operation


def _native_journal_owner(roots, operation, schema, *, fault=lambda _: None):
    owner = protected_journal.WindowsProtectedJournalCharacterization._from_native(
        roots["private_journal"], writable=True, fault=fault)
    if schema == journal.SCHEMA:
        owner.initialize_for_characterization(operation)
    else:
        owner.initialize_multi_request_for_characterization(operation)
    return owner


def _native_append_journal(owner, schema, tip):
    if schema == journal.SCHEMA:
        observation = journal.Observation(
            "submission_intent" if tip is None else "submission_observed",
            "intent" if tip is None else "unknown")
        return owner.append_for_characterization(observation)
    if tip is None:
        return owner.append_multi_request_intent_for_characterization(None, 0)
    return owner.append_multi_request_outcome_for_characterization(
        tip, "pre_send_rejected", None)


def test_journal_replacement_accounts_old_snapshot_once_and_lock_as_zero_bytes():
    limits = admission.ProtectedStorageCapacityLimits(
        journal_bytes=admission._JOURNAL_BYTES,
        shared_temporary_and_promoted_bytes=100,
        retained_uncertain_bytes=100,
        journal_entries=3,
        shared_temporary_and_promoted_entries=4,
        retained_uncertain_entries=20)
    ledger, owner, journal_owner, operation, writer = _journal_replacement_rig(limits=limits)
    _write, _binding, first_ack, first = _commit_portable_journal_replacement(
        ledger, owner, journal_owner, operation, writer,
        data_size=admission._JOURNAL_BYTES, native_identity=(1, 10), file_identity=(2, 20))
    assert first_ack.revision == 1
    assert first["roots"][0]["reserved_bytes"] == 0
    assert first["roots"][0]["observed_used_bytes"] == admission._JOURNAL_BYTES
    assert first["roots"][0]["observed_used_entries"] == 1

    binding = _journal_binding(ledger, owner, journal_owner, operation, writer)
    write = ledger.admit_journal_replacement(operation, binding)
    during = ledger.readiness()["roots"][0]
    assert during["observed_used_bytes"] == admission._JOURNAL_BYTES
    assert during["reserved_bytes"] == admission._JOURNAL_BYTES  # TMP upper bound only
    assert during["observed_used_bytes"] + during["reserved_bytes"] == admission._JOURNAL_REPLACEMENT_LIVE_BYTES
    assert during["observed_used_entries"] == 1
    assert during["reserved_entries"] == 2  # TMP plus zero-byte lock

    inventory, second_ack, completion = _journal_after_inventory(
        ledger, writer, 37, native_identity=(1, 11), file_identity=(2, 21), binding=binding)
    after = ledger.complete_journal_replacement(
        operation, write, inventory, 4 * 1024 * 1024, completion)["roots"][0]
    assert second_ack.revision == 2
    assert after["reserved_bytes"] == 0 and after["reserved_entries"] == 0
    assert after["observed_used_bytes"] == 37 and after["observed_used_entries"] == 1
    assert after["retained_uncertain_bytes"] == 0


def test_generic_cancel_cannot_release_journal_replacement_without_precreate_proof():
    ledger, owner, journal_owner, operation, writer = _journal_replacement_rig()
    binding = _journal_binding(ledger, owner, journal_owner, operation, writer)
    write = ledger.admit_journal_replacement(operation, binding)
    with pytest.raises(ValueError, match="journal_replacement_precreate_proof_required"):
        ledger.cancel_write_before_create(operation, write)
    assert ledger._active_write is write
    assert ledger.readiness()["roots"][0]["reserved_bytes"] == admission._JOURNAL_BYTES
    ledger.retain_uncertain(operation, write)
    row = ledger.readiness()["roots"][0]
    assert row["reserved_bytes"] == 0
    assert row["retained_uncertain_bytes"] == admission._JOURNAL_BYTES


def test_journal_replacement_preflight_refusal_does_not_change_successful_inventory():
    limits = admission.ProtectedStorageCapacityLimits(
        journal_bytes=admission._JOURNAL_BYTES,
        shared_temporary_and_promoted_bytes=100,
        retained_uncertain_bytes=100,
        journal_entries=1,
        shared_temporary_and_promoted_entries=4,
        retained_uncertain_entries=20)
    ledger, owner, journal_owner, operation, writer = _journal_replacement_rig(limits=limits)
    before = ledger.readiness()
    binding = _journal_binding(ledger, owner, journal_owner, operation, writer)
    with pytest.raises(ValueError, match="journal_replacement_capacity_exceeded"):
        ledger.admit_journal_replacement(operation, binding)
    after = ledger.readiness()
    assert after == before
    assert ledger._operations[operation]["state"] == "open"
    assert ledger._active_write is None


def test_journal_replacement_preflight_subtracts_other_uncertain_capacity():
    inventory = _empty_inventory()
    inventory["temporary_containment"]["orphan.bin"] = ((1, 1), 2, ("acl",))
    ledger, owner, journal_owner, operation, writer = _journal_replacement_rig(inventory=inventory)
    ledger._available_free_bytes = admission._JOURNAL_BYTES + 1
    before = ledger.readiness()
    binding = _journal_binding(ledger, owner, journal_owner, operation, writer)
    with pytest.raises(ValueError, match="observed_free_capacity_insufficient"):
        ledger.admit_journal_replacement(operation, binding)
    assert ledger.readiness() == before
    assert ledger._operations[operation]["state"] == "open"
    assert ledger._active_write is None


@pytest.mark.parametrize("tamper", [
    "missing_target", "additional_lock", "additional_temp", "changed_acl",
    "same_native_identity", "wrong_acknowledgement", "unrelated_file_change",
])
def test_journal_replacement_uncertainty_retains_old_plus_full_upper_bound(tamper):
    ledger, owner, journal_owner, operation, writer = _journal_replacement_rig()
    _commit_portable_journal_replacement(
        ledger, owner, journal_owner, operation, writer,
        data_size=64, native_identity=(3, 30), file_identity=(4, 40))
    binding = _journal_binding(ledger, owner, journal_owner, operation, writer)
    write = ledger.admit_journal_replacement(operation, binding)
    inventory, acknowledgement, completion = _journal_after_inventory(
        ledger, writer, 32, native_identity=(3, 31), file_identity=(4, 41), binding=binding)
    if tamper == "missing_target":
        del inventory["private_journal"][writer.filename]
    elif tamper == "additional_lock":
        inventory["private_journal"][writer.operation.operation_id + ".lock"] = (
            (3, 32), 0, ("protected-acl",))
    elif tamper == "additional_temp":
        inventory["private_journal"][writer.operation.operation_id + ".extra.tmp"] = (
            (3, 33), 4, ("protected-acl",))
    elif tamper == "changed_acl":
        row = (completion.native_row[0], completion.native_row[1], ("changed-acl",))
        inventory["private_journal"][writer.filename] = row
        completion = replace(completion, native_row=row)
    elif tamper == "same_native_identity":
        old_identity = binding.previous_native_row[0]
        row = (old_identity, completion.native_row[1], completion.native_row[2])
        inventory["private_journal"][writer.filename] = row
        completion = replace(completion, native_row=row)
    elif tamper == "wrong_acknowledgement":
        wrong_ack = replace(acknowledgement, digest="f" * 64)
        completion = replace(completion, acknowledgement=wrong_ack)
    elif tamper == "unrelated_file_change":
        inventory["temporary_containment"]["unrelated.bin"] = ((9, 90), 1, ("acl",))

    with pytest.raises(ValueError, match="journal_replacement_"):
        ledger.complete_journal_replacement(operation, write, inventory, 4 * 1024 * 1024, completion)
    row = ledger.readiness()["roots"][0]
    assert ledger.readiness()["status"] == "unavailable"
    assert row["reserved_bytes"] == 0 and row["reserved_entries"] == 0
    assert row["observed_used_bytes"] == 64 and row["observed_used_entries"] == 1
    assert row["retained_uncertain_bytes"] == admission._JOURNAL_BYTES
    assert row["retained_uncertain_entries"] == 2


def test_journal_replacement_close_fences_commit_and_retains_reservation():
    ledger, owner, journal_owner, operation, writer = _journal_replacement_rig()
    binding = _journal_binding(ledger, owner, journal_owner, operation, writer)
    write = ledger.admit_journal_replacement(operation, binding)
    inventory, _acknowledgement, completion = _journal_after_inventory(
        ledger, writer, 20, native_identity=(5, 50), file_identity=(6, 60), binding=binding)
    ledger.close()
    with pytest.raises(ValueError, match="storage_owner_unavailable"):
        ledger.complete_journal_replacement(operation, write, inventory, 4 * 1024 * 1024, completion)
    row = ledger.readiness()["roots"][0]
    assert row["reserved_bytes"] == 0
    assert row["retained_uncertain_bytes"] == admission._JOURNAL_BYTES
    assert row["retained_uncertain_entries"] == 2
    assert row["observed_used_bytes"] == 0


def test_journal_replacement_tokens_are_one_shot_and_owner_bound():
    ledger, owner, journal_owner, operation, writer = _journal_replacement_rig()
    foreign_ledger, foreign_owner, foreign_journal, foreign_operation, _ = _journal_replacement_rig(
        operation_id="other-operation")
    binding = _journal_binding(ledger, owner, journal_owner, operation, writer)
    with pytest.raises(ValueError, match="journal_replacement_binding_invalid"):
        foreign_ledger.admit_journal_replacement(foreign_operation, binding)
    with pytest.raises(ValueError, match="journal_replacement_binding_invalid"):
        ledger.admit_journal_replacement(foreign_operation, binding)
    write = ledger.admit_journal_replacement(operation, binding)
    inventory, _acknowledgement, completion = _journal_after_inventory(
        ledger, writer, 22, native_identity=(7, 70), file_identity=(8, 80), binding=binding)
    ledger.complete_journal_replacement(operation, write, inventory, 4 * 1024 * 1024, completion)
    with pytest.raises(ValueError, match="journal_replacement_binding_invalid"):
        ledger.admit_journal_replacement(operation, binding)
    with pytest.raises(ValueError, match="write_admission_unavailable"):
        ledger.complete_journal_replacement(
            operation, write, inventory, 4 * 1024 * 1024, completion)


def test_generic_image_writer_inventory_remains_append_only_on_replacement():
    original = {purpose: {} for purpose in admission._WRITABLE}
    original["temporary_containment"]["existing.png"] = ((1, 1), 5, ("acl",))
    ledger = _ready_ledger(inventory=original)
    operation = ledger.begin_operation("image-operation")
    reservation = ledger.reserve(operation, {
        "temporary_containment": admission.CapacityEstimate(10, 1)})
    write = ledger.admit_write(operation, reservation)
    replaced = {purpose: dict(entries) for purpose, entries in original.items()}
    replaced["temporary_containment"]["existing.png"] = ((1, 2), 7, ("acl",))
    with pytest.raises(ValueError, match="storage_inventory_changed"):
        ledger.complete_write(operation, write, replaced)
    row = next(item for item in ledger.readiness()["roots"]
               if item["purpose"] == "temporary_containment")
    assert row["retained_uncertain_bytes"] == 15  # unattributed old file plus retained write bound
    assert row["observed_used_bytes"] == 0


def test_concurrent_reservations_share_asset_capacity_and_refuse_before_admission():
    ledger = _ready_ledger(_limits(assets=100))
    first = ledger.begin_operation("operation-a")
    second = ledger.begin_operation("operation-b")
    gate = threading.Barrier(3)
    results = []

    def reserve(operation, purpose):
        gate.wait()
        try:
            ledger.reserve(operation, {purpose: admission.CapacityEstimate(60, 2)})
            results.append("reserved")
        except ValueError as error:
            results.append(str(error))

    threads = [threading.Thread(target=reserve, args=(first, "temporary_containment")),
               threading.Thread(target=reserve, args=(second, "promoted_assets"))]
    for thread in threads:
        thread.start()
    gate.wait()
    for thread in threads:
        thread.join()
    assert results.count("reserved") == 1
    assert len(results) == 2 and all(value == "reserved" or "shared_asset_capacity_exceeded" in value
                                      for value in results)
    after = ledger.readiness()
    assert sum(row["reserved_bytes"] for row in after["roots"]
               if row["purpose"] in ("temporary_containment", "promoted_assets")) == 60


def test_exact_operation_owns_reservation_and_prewrite_cancel_is_one_shot():
    ledger = _ready_ledger()
    first = ledger.begin_operation("operation-a")
    second = ledger.begin_operation("operation-b")
    reservation = ledger.reserve(first, {"private_journal": admission.CapacityEstimate(50, 2)})
    with pytest.raises(ValueError, match="reservation_unavailable"):
        ledger.admit_write(second, reservation)
    with pytest.raises(ValueError, match="reservation_not_releasable"):
        ledger.cancel_before_write(second, reservation)
    ledger.cancel_before_write(first, reservation)
    with pytest.raises(ValueError, match="reservation_not_releasable"):
        ledger.cancel_before_write(first, reservation)
    with pytest.raises(ValueError, match="operation_identity_reused"):
        ledger.begin_operation("operation-a")
    assert all(row["reserved_bytes"] == 0 for row in ledger.readiness()["roots"])


def test_only_one_write_is_admitted_at_a_time():
    ledger = _ready_ledger()
    first = ledger.begin_operation("first")
    second = ledger.begin_operation("second")
    first_reservation = ledger.reserve(first, {"temporary_containment": admission.CapacityEstimate(20, 1)})
    second_reservation = ledger.reserve(second, {"promoted_assets": admission.CapacityEstimate(20, 1)})
    ledger.admit_write(first, first_reservation)
    with pytest.raises(ValueError, match="write_admission_busy"):
        ledger.admit_write(second, second_reservation)
    summary = ledger.readiness()
    assert sum(row["reserved_bytes"] for row in summary["roots"]) == 40


def test_owner_cancels_unused_reservation_while_another_write_is_active():
    ledger = _ready_ledger(_limits(assets=100))
    owner = object.__new__(admission.WindowsProtectedStorageAdmissionCharacterization)
    owner._ledger = ledger
    owner._lock = threading.RLock()
    owner._closed = False
    owner._invalid = False
    owner._refresh = lambda: (_ for _ in ()).throw(ValueError("storage_write_in_progress"))
    active_operation = ledger.begin_operation("active-write")
    cancelled_operation = ledger.begin_operation("cancelled-before-write")
    active_reservation = ledger.reserve(
        active_operation, {"temporary_containment": admission.CapacityEstimate(20, 1)})
    cancelled_reservation = ledger.reserve(
        cancelled_operation, {"promoted_assets": admission.CapacityEstimate(30, 1)})
    write = ledger.admit_write(active_operation, active_reservation)

    owner.cancel_before_write_for_characterization(cancelled_operation, cancelled_reservation)

    rows = {row["purpose"]: row for row in ledger.readiness()["roots"]}
    assert rows["temporary_containment"]["reserved_bytes"] == 20
    assert rows["promoted_assets"]["reserved_bytes"] == 0
    next_operation = ledger.begin_operation("after-prewrite-cancel")
    next_reservation = ledger.reserve(
        next_operation, {"promoted_assets": admission.CapacityEstimate(70, 1)})
    ledger.cancel_before_write(next_operation, next_reservation)
    ledger.retain_uncertain(active_operation, write)


def test_close_racing_reservation_never_releases_an_admitted_upper_bound():
    ledger = _ready_ledger()
    operation = ledger.begin_operation("race")
    gate = threading.Barrier(3)
    outcomes = []

    def reserve():
        gate.wait()
        try:
            ledger.reserve(operation, {"private_journal": admission.CapacityEstimate(33, 1)})
            outcomes.append("reserved")
        except ValueError:
            outcomes.append("refused")

    def close():
        gate.wait()
        ledger.close()
        outcomes.append("closed")

    threads = [threading.Thread(target=reserve), threading.Thread(target=close)]
    for thread in threads:
        thread.start()
    gate.wait()
    for thread in threads:
        thread.join()
    summary = ledger.readiness()
    row = next(row for row in summary["roots"] if row["purpose"] == "private_journal")
    assert "closed" in outcomes and len(outcomes) == 2
    assert summary["status"] == "unavailable" and row["reserved_bytes"] == 0
    assert row["retained_uncertain_bytes"] in (0, 33)


def test_forged_or_substituted_reservation_and_write_tokens_are_refused():
    ledger = _ready_ledger()
    operation = ledger.begin_operation("operation")
    reservation = ledger.reserve(operation, {"promoted_assets": admission.CapacityEstimate(30, 1)})
    with pytest.raises(ValueError, match="reservation_unavailable"):
        ledger.admit_write(operation, object())
    write = ledger.admit_write(operation, reservation)
    with pytest.raises(ValueError, match="write_admission_unavailable"):
        ledger.complete_write(operation, object(), _empty_inventory())
    with pytest.raises(ValueError, match="write_admission_unavailable"):
        ledger.retain_uncertain(object(), write)


def test_completed_write_releases_unused_reservation_and_records_observed_usage():
    ledger = _ready_ledger()
    operation = ledger.begin_operation("operation")
    reservation = ledger.reserve(operation, {"temporary_containment": admission.CapacityEstimate(40, 2)})
    write = ledger.admit_write(operation, reservation)
    inventory = _empty_inventory()
    inventory["temporary_containment"]["new.bin"] = ((1, 2), 12, ("owner-acl",))
    summary = ledger.complete_write(operation, write, inventory)
    row = next(row for row in summary["roots"] if row["purpose"] == "temporary_containment")
    assert row["reserved_bytes"] == 0 and row["reserved_entries"] == 0
    assert row["observed_used_bytes"] == 12 and row["observed_used_entries"] == 1
    assert row["retained_uncertain_bytes"] == 0 and row["remaining_policy_bytes"] == 88


def test_unchanged_inventory_after_write_admission_retains_full_reservation():
    ledger = _ready_ledger(_limits(assets=100))
    operation = ledger.begin_operation("operation")
    reservation = ledger.reserve(
        operation, {"temporary_containment": admission.CapacityEstimate(40, 2)})
    write = ledger.admit_write(operation, reservation)

    with pytest.raises(ValueError, match="no_new_storage_observed"):
        ledger.complete_write(operation, write, _empty_inventory())

    summary = ledger.readiness()
    row = next(row for row in summary["roots"]
               if row["purpose"] == "temporary_containment")
    assert summary["status"] == "unavailable"
    assert row["reserved_bytes"] == 0 and row["reserved_entries"] == 0
    assert row["observed_used_bytes"] == 0 and row["observed_used_entries"] == 0
    assert row["retained_uncertain_bytes"] == 40
    assert row["retained_uncertain_entries"] == 2
    assert row["remaining_policy_bytes"] == 60
    with pytest.raises(ValueError, match="storage_owner_unavailable"):
        ledger.begin_operation("later")


@pytest.mark.parametrize("state", ["explicit", "close"])
def test_uncertain_or_closed_reservations_are_retained_not_released(state):
    ledger = _ready_ledger()
    operation = ledger.begin_operation("operation")
    reservation = ledger.reserve(operation, {"private_journal": admission.CapacityEstimate(70, 3)})
    if state == "explicit":
        write = ledger.admit_write(operation, reservation)
        ledger.retain_uncertain(operation, write)
    else:
        ledger.close()
    summary = ledger.readiness()
    row = next(row for row in summary["roots"] if row["purpose"] == "private_journal")
    assert summary["status"] == "unavailable"
    assert row["reserved_bytes"] == 0 and row["retained_uncertain_bytes"] == 70
    assert row["retained_uncertain_entries"] == 3
    with pytest.raises(ValueError, match="storage_owner_unavailable"):
        ledger.begin_operation("later")


def test_inventory_drift_invalidates_owner_and_retains_open_reservation():
    ledger = _ready_ledger()
    operation = ledger.begin_operation("operation")
    ledger.reserve(operation, {"promoted_assets": admission.CapacityEstimate(20, 1)})
    changed = _empty_inventory()
    changed["promoted_assets"]["external.bin"] = ((4, 5), 2, ("acl",))
    with pytest.raises(ValueError, match="storage_inventory_changed"):
        ledger.observe_inventory(changed)
    summary = ledger.readiness()
    row = next(row for row in summary["roots"] if row["purpose"] == "promoted_assets")
    assert summary["status"] == "unavailable"
    assert row["reserved_bytes"] == 0 and row["retained_uncertain_bytes"] == 20


def test_unattributed_initial_files_are_retained_uncertain_not_adopted():
    inventory = _empty_inventory()
    inventory["temporary_containment"]["existing.bin"] = ((1, 7), 25, ("owner-acl",))
    ledger = admission._CapacityLedger(_limits(assets=100))
    ledger.set_initial_inventory(inventory, 1000)
    row = next(row for row in ledger.readiness()["roots"]
               if row["purpose"] == "temporary_containment")
    assert row["observed_used_bytes"] == 0
    assert row["retained_uncertain_bytes"] == 25
    assert row["retained_uncertain_entries"] == 1
    assert row["remaining_policy_bytes"] == 75


@pytest.mark.parametrize("estimate", [
    admission.CapacityEstimate(True, 1),
    admission.CapacityEstimate(0, 1),
    admission.CapacityEstimate(1, 0),
    admission.CapacityEstimate(10**100, 1),
])
def test_invalid_and_overflowing_estimates_fail_closed(estimate):
    ledger = _ready_ledger()
    operation = ledger.begin_operation("operation")
    with pytest.raises(ValueError, match="invalid_capacity_estimate"):
        ledger.reserve(operation, {"temporary_containment": estimate})
    assert all(row["reserved_bytes"] == 0 for row in ledger.readiness()["roots"])


def test_invalid_limits_and_read_only_json_reservations_are_rejected():
    with pytest.raises(ValueError, match="invalid_capacity_limits"):
        admission.ProtectedStorageCapacityLimits(journal_bytes=True).validate()
    ledger = _ready_ledger()
    operation = ledger.begin_operation("operation")
    with pytest.raises(ValueError, match="invalid_capacity_estimate"):
        ledger.reserve(operation, {"selected_project_json": admission.CapacityEstimate(1, 1)})


def test_low_observed_free_capacity_refuses_reservation_before_write_admission():
    ledger = _ready_ledger()
    ledger._available_free_bytes = 9
    operation = ledger.begin_operation("operation")
    before = ledger.readiness()
    with pytest.raises(ValueError, match="observed_free_capacity_insufficient"):
        ledger.reserve(operation, {"temporary_containment": admission.CapacityEstimate(10, 1)})
    after = ledger.readiness()
    assert after["roots"] == before["roots"]
    assert after["observed_free_bytes"] == 9


@pytest.fixture
def native_storage_roots(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows native characterization only")
    pytest.importorskip("win32security")
    api = windows._api()
    scope = tmp_path / "owner-only-scope"
    api[2].CreateDirectory(str(scope), windows._security_attributes(api, windows._current_user(api)))
    project = scope / "selected-project.json"
    _, c, f, _, _, _ = api
    handle = f.CreateFile(str(project), c.GENERIC_WRITE, c.FILE_SHARE_READ,
        windows._security_attributes(api, windows._current_user(api)), c.CREATE_NEW,
        c.FILE_ATTRIBUTE_NORMAL | 0x00200000, None)
    try:
        f.WriteFile(handle, b'{"disposable":true}')
    finally:
        handle.Close()
    roots = {}
    try:
        roots["private_journal"] = windows.WindowsProtectedRootCharacterization.provision_journal_for_characterization(
            str(scope), characterization=True, disposable_opt_in=True)
        roots["temporary_containment"] = windows.WindowsProtectedRootCharacterization.provision_asset_for_characterization(
            str(scope), "temporary_containment", characterization=True, disposable_opt_in=True)
        roots["retained_uncertain"] = windows.WindowsProtectedRootCharacterization.provision_retained_for_characterization(
            str(scope), characterization=True, disposable_opt_in=True)
        roots["promoted_assets"] = windows.WindowsProtectedRootCharacterization.provision_asset_for_characterization(
            str(scope), "promoted_assets", characterization=True, disposable_opt_in=True)
        roots["selected_project_json"] = windows.WindowsProtectedRootCharacterization.capture_for_characterization(
            str(scope), str(project), "selected_project_json", characterization=True,
            disposable_opt_in=True)
        yield scope, project, api, roots
    finally:
        for root in roots.values():
            root.close()


def _capture_native(scope, roots, limits=None):
    return admission.WindowsProtectedStorageAdmissionCharacterization.capture_for_characterization(
        str(scope), roots, characterization=True, disposable_opt_in=True,
        limits=limits or admission.ProtectedStorageCapacityLimits())


@pytest.mark.parametrize("schema", [journal.SCHEMA, multi_journal.SCHEMA])
def test_native_protected_journal_replacement_reserves_then_reconciles_exact_snapshot(
        native_storage_roots, schema):
    scope, _, api, roots = native_storage_roots
    capacity = _capture_native(scope, roots)
    operation = _native_journal_operation(scope)
    journal_owner = _native_journal_owner(roots, operation, schema)
    capacity_operation = capacity.begin_operation_for_characterization(operation.operation_id)
    try:
        assert list(roots["private_journal"]._path.iterdir()) == []
        write = capacity.admit_journal_replacement_for_characterization(
            capacity_operation, journal_owner)
        # Admission is pure accounting: no lock, TMP or JSON is created yet.
        assert list(roots["private_journal"]._path.iterdir()) == []
        before_first = capacity.readiness()["roots"][0]
        assert before_first["reserved_bytes"] == admission._JOURNAL_BYTES
        assert before_first["reserved_entries"] == 2
        with pytest.raises(ValueError, match="write_admission_unavailable"):
            capacity.complete_journal_replacement_for_characterization(
                capacity_operation, object(), journal_owner, None)
        assert capacity.readiness()["status"] == "characterization_only"
        assert next(row for row in capacity.readiness()["roots"]
                    if row["purpose"] == "private_journal")["reserved_bytes"] == admission._JOURNAL_BYTES

        first_ack = _native_append_journal(journal_owner, schema, None)
        capacity.complete_journal_replacement_for_characterization(
            capacity_operation, write, journal_owner, first_ack)
        target = roots["private_journal"]._path / (operation.operation_id + ".json")
        assert target.is_file()
        first_identity = journal._file_identity(journal._ordinary(target, directory=False))
        first_native_identity = windows._ordinary(target, directory=False)
        first_row = next(row for row in capacity.readiness()["roots"]
                         if row["purpose"] == "private_journal")
        assert first_row["reserved_bytes"] == 0 and first_row["reserved_entries"] == 0
        assert first_row["observed_used_bytes"] == target.stat().st_size <= admission._JOURNAL_BYTES
        assert first_row["observed_used_entries"] == 1
        assert first_row["retained_uncertain_bytes"] == 0

        second_write = capacity.admit_journal_replacement_for_characterization(
            capacity_operation, journal_owner)
        during_replace = next(row for row in capacity.readiness()["roots"]
                              if row["purpose"] == "private_journal")
        assert during_replace["observed_used_bytes"] == target.stat().st_size
        assert during_replace["reserved_bytes"] == admission._JOURNAL_BYTES
        assert during_replace["observed_used_entries"] == 1
        assert during_replace["reserved_entries"] == 2  # empty lock entry plus TMP
        second_ack = _native_append_journal(journal_owner, schema, first_ack)
        capacity.complete_journal_replacement_for_characterization(
            capacity_operation, second_write, journal_owner, second_ack)
        second_identity = journal._file_identity(journal._ordinary(target, directory=False))
        second_native_identity = windows._ordinary(target, directory=False)
        assert second_identity != first_identity
        assert second_native_identity != first_native_identity
        assert [path.name for path in roots["private_journal"]._path.iterdir()] == [target.name]
        if schema == journal.SCHEMA:
            reopened = journal_owner.reopen_journal_for_characterization(
                target.name, expected_revision=2)
        else:
            reopened = journal_owner.reopen_multi_request_journal_for_characterization(
                target.name, expected_revision=2)
        assert reopened.file_identity == second_identity

        handle = windows._open(target, False, api)
        try:
            assert windows._identity(handle) == second_native_identity
            acl = windows._acl(handle, api, roots["private_journal"]._user)
            assert acl == journal_owner._file_acls[second_native_identity]
        finally:
            handle.Close()
        final_row = next(row for row in capacity.readiness()["roots"]
                         if row["purpose"] == "private_journal")
        assert final_row["observed_used_bytes"] == target.stat().st_size
        assert final_row["observed_used_entries"] == 1
        assert final_row["retained_uncertain_bytes"] == 0
        view = capacity.readiness()
        assert view["execution_available"] is False
        assert view["protected_storage_available"] is False
        assert view["promotion_available"] is False
        assert view["candidate_publication_allowed"] is False
        assert view["writer_integrated"] is False
        assert view["promotion_writer_integrated"] is False
        assert view["authorship"] == "unverified"
    finally:
        journal_owner.close()
        capacity.close()


def test_native_journal_replacement_requires_exact_shared_root_owner(native_storage_roots):
    scope, _, _, roots = native_storage_roots
    capacity = _capture_native(scope, roots)
    operation = _native_journal_operation(scope)
    other_root = windows.WindowsProtectedRootCharacterization.capture_for_characterization(
        str(scope), str(roots["private_journal"]._path), "private_journal",
        characterization=True, disposable_opt_in=True)
    journal_owner = None
    try:
        assert other_root is not roots["private_journal"]
        assert other_root._identity == roots["private_journal"]._identity
        journal_owner = protected_journal.WindowsProtectedJournalCharacterization._from_native(
            other_root, writable=True, fault=lambda _: None)
        journal_owner.initialize_for_characterization(operation)
        capacity_operation = capacity.begin_operation_for_characterization(operation.operation_id)
        with pytest.raises(ValueError, match="journal_replacement_root_mismatch"):
            capacity.admit_journal_replacement_for_characterization(
                capacity_operation, journal_owner)
        assert list(roots["private_journal"]._path.iterdir()) == []
        assert capacity.readiness()["status"] == "characterization_only"
        assert capacity._ledger._operations[capacity_operation]["state"] == "open"
    finally:
        if journal_owner is not None:
            journal_owner.close()
        else:
            other_root.close()
        capacity.close()


@pytest.mark.parametrize("boundary", ["before_replace", "after_replace_before_ack"])
def test_native_journal_replacement_failure_retains_old_and_full_upper_bound(
        native_storage_roots, boundary):
    scope, _, _, roots = native_storage_roots
    capacity = _capture_native(scope, roots)
    operation = _native_journal_operation(scope)
    journal_owner = _native_journal_owner(roots, operation, journal.SCHEMA)
    capacity_operation = capacity.begin_operation_for_characterization(operation.operation_id)
    try:
        first_write = capacity.admit_journal_replacement_for_characterization(
            capacity_operation, journal_owner)
        first_ack = journal_owner.append_for_characterization(
            journal.Observation("submission_intent", "intent"))
        capacity.complete_journal_replacement_for_characterization(
            capacity_operation, first_write, journal_owner, first_ack)
        target = roots["private_journal"]._path / (operation.operation_id + ".json")
        old_bytes = target.read_bytes()
        old_identity = journal._file_identity(journal._ordinary(target, directory=False))

        def fail_at(point):
            if point == boundary:
                raise RuntimeError("injected unknown replacement outcome")

        journal_owner._fault = fail_at
        journal_owner._writer.fault = fail_at
        second_write = capacity.admit_journal_replacement_for_characterization(
            capacity_operation, journal_owner)
        with pytest.raises(RuntimeError, match="unknown replacement outcome"):
            journal_owner.append_for_characterization(
                journal.Observation("submission_observed", "unknown"))
        capacity.retain_journal_replacement_uncertain_for_characterization(
            capacity_operation, second_write)

        row = next(item for item in capacity.readiness()["roots"]
                   if item["purpose"] == "private_journal")
        assert row["reserved_bytes"] == 0 and row["reserved_entries"] == 0
        assert row["observed_used_bytes"] == len(old_bytes)
        assert row["observed_used_entries"] == 1
        assert row["retained_uncertain_bytes"] == admission._JOURNAL_BYTES
        assert row["retained_uncertain_entries"] == 2
        assert capacity.readiness()["status"] == "unavailable"
        assert target.exists()
        if boundary == "before_replace":
            assert target.read_bytes() == old_bytes
            assert journal._file_identity(journal._ordinary(target, directory=False)) == old_identity
            assert list(roots["private_journal"]._path.glob("*.tmp"))
        else:
            assert target.read_bytes() != old_bytes
            assert journal._file_identity(journal._ordinary(target, directory=False)) != old_identity
        assert (roots["private_journal"]._path / (operation.operation_id + ".lock")).exists()
        assert not capacity.readiness()["execution_available"]
        capacity.retain_journal_replacement_uncertain_for_characterization(
            capacity_operation, second_write)
        retained_again = next(row for row in capacity.readiness()["roots"]
                              if row["purpose"] == "private_journal")
        assert retained_again["retained_uncertain_bytes"] == admission._JOURNAL_BYTES
        assert retained_again["retained_uncertain_entries"] == 2
    finally:
        journal_owner.close()
        capacity.close()


def test_native_journal_replacement_close_during_create_cannot_commit(native_storage_roots):
    scope, _, _, roots = native_storage_roots
    capacity = _capture_native(scope, roots)
    operation = _native_journal_operation(scope)
    entered_create = threading.Event()
    release_create = threading.Event()
    first_create = [True]
    empty_lock_size = [None]

    def pause_after_create(point):
        if point == "after_file_create" and first_create[0]:
            first_create[0] = False
            lock_path = roots["private_journal"]._path / (operation.operation_id + ".lock")
            empty_lock_size[0] = lock_path.stat().st_size
            entered_create.set()
            if not release_create.wait(timeout=10):
                raise RuntimeError("test release timed out")

    journal_owner = _native_journal_owner(roots, operation, journal.SCHEMA,
                                           fault=pause_after_create)
    capacity_operation = capacity.begin_operation_for_characterization(operation.operation_id)
    write = capacity.admit_journal_replacement_for_characterization(
        capacity_operation, journal_owner)
    outcome = []

    def append():
        try:
            outcome.append(journal_owner.append_for_characterization(
                journal.Observation("submission_intent", "intent")))
        except BaseException as error:
            outcome.append(error)

    thread = threading.Thread(target=append)
    thread.start()
    try:
        assert entered_create.wait(timeout=10)
        capacity.close()
    finally:
        release_create.set()
        thread.join(timeout=10)
        journal_owner.close()
    assert not thread.is_alive()
    assert len(outcome) == 1 and type(outcome[0]) is journal.ReopenedJournal
    assert empty_lock_size == [0]
    with pytest.raises(ValueError):
        capacity.complete_journal_replacement_for_characterization(
            capacity_operation, write, journal_owner, outcome[0])
    capacity.retain_journal_replacement_uncertain_for_characterization(
        capacity_operation, write)
    row = next(item for item in capacity._ledger.readiness()["roots"]
               if item["purpose"] == "private_journal")
    assert row["reserved_bytes"] == 0 and row["reserved_entries"] == 0
    assert row["observed_used_bytes"] == 0 and row["observed_used_entries"] == 0
    assert row["retained_uncertain_bytes"] == admission._JOURNAL_BYTES
    assert row["retained_uncertain_entries"] == 2
    assert (roots["private_journal"]._path / (operation.operation_id + ".json")).exists()


def test_native_distinct_roots_are_pinned_but_do_not_enable_storage(native_storage_roots):
    from test_generation_windows_protected_storage import native_descriptors
    scope, project, api, roots = native_storage_roots
    before = tuple(sorted(path.name for path in scope.iterdir()))
    protected_paths = (scope, *(root._path for purpose, root in roots.items()
                                if purpose != "selected_project_json"), project)
    before_acls = native_descriptors(api, protected_paths)
    owner = _capture_native(scope, roots)
    view = owner.readiness()
    assert view["status"] == "characterization_only"
    assert view["filesystem"] == "local_ntfs_observed"
    assert {row["purpose"] for row in view["roots"]} == set(admission._WRITABLE)
    assert not any(view[key] for key in ("execution_available", "protected_storage_available",
        "promotion_available", "candidate_publication_allowed", "disk_space_guaranteed",
        "writer_integrated", "cross_process_quota", "cleanup_allowed"))
    assert view["authorship"] == "unverified" and view["current_authorization"] == "absent"
    assert tuple(sorted(path.name for path in scope.iterdir())) == before
    assert project.read_bytes() == b'{"disposable":true}'
    assert native_descriptors(api, protected_paths) == before_acls
    assert roots["selected_project_json"]._purpose == "selected_project_json"
    owner.close()


def test_native_duplicate_capture_cannot_create_an_independent_capacity_ledger(native_storage_roots):
    scope, project, _, roots = native_storage_roots
    before = tuple(sorted(path.name for path in scope.iterdir()))
    owner = _capture_native(scope, roots)
    with pytest.raises(ValueError, match="storage_accounting_scope_already_captured"):
        _capture_native(scope, roots)

    # Closing the first owner cannot release an uncertain in-process claim and
    # permit a fresh empty ledger over the same physical capacity.
    owner.close()
    with pytest.raises(ValueError, match="storage_accounting_scope_already_captured"):
        _capture_native(scope, roots)

    assert tuple(sorted(path.name for path in scope.iterdir())) == before
    assert project.read_bytes() == b'{"disposable":true}'


def test_native_partial_root_overlap_cannot_create_an_independent_capacity_ledger(
        native_storage_roots):
    scope, project, _, roots = native_storage_roots
    owner = _capture_native(scope, roots)
    alternate_promoted = None
    try:
        alternate_promoted = windows.WindowsProtectedRootCharacterization.provision_asset_for_characterization(
            str(scope), "promoted_assets", characterization=True, disposable_opt_in=True)
        alternate_roots = dict(roots)
        alternate_roots["promoted_assets"] = alternate_promoted
        assert alternate_roots["temporary_containment"] is roots["temporary_containment"]
        assert alternate_roots["promoted_assets"] is not roots["promoted_assets"]
        assert alternate_roots["promoted_assets"]._path != roots["promoted_assets"]._path

        # The same scope with a partially different root set cannot split
        # capacity accounting, either while the first owner is live or after
        # it closes. The new disposable directory is retained by the fixture;
        # no existing root or ACL is modified.
        with pytest.raises(ValueError, match="storage_accounting_scope_already_captured"):
            _capture_native(scope, alternate_roots)
        owner.close()
        with pytest.raises(ValueError, match="storage_accounting_scope_already_captured"):
            _capture_native(scope, alternate_roots)

        assert project.read_bytes() == b'{"disposable":true}'
        assert roots["temporary_containment"]._path.exists()
        assert roots["promoted_assets"]._path.exists()
        assert alternate_promoted._path.exists()
    finally:
        owner.close()
        if alternate_promoted is not None:
            alternate_promoted.close()


def test_native_admission_counts_existing_files_as_uncertain_without_adopting(native_storage_roots):
    scope, _, api, roots = native_storage_roots
    path = roots["temporary_containment"]._path / "unattributed.bin"
    _, c, f, _, _, _ = api
    handle = f.CreateFile(str(path), c.GENERIC_WRITE, c.FILE_SHARE_READ,
        windows._security_attributes(api, roots["temporary_containment"]._user), c.CREATE_NEW,
        c.FILE_ATTRIBUTE_NORMAL | 0x00200000, None)
    try:
        f.WriteFile(handle, b"orphan")
    finally:
        handle.Close()
    owner = _capture_native(scope, roots)
    row = next(row for row in owner.readiness()["roots"] if row["purpose"] == "temporary_containment")
    assert row["observed_used_bytes"] == 0
    assert row["retained_uncertain_bytes"] == 6
    assert row["retained_uncertain_entries"] == 1
    assert path.read_bytes() == b"orphan"
    owner.close()


def test_native_approved_scope_and_purpose_aliases_fail_without_repair(native_storage_roots):
    scope, _, _, roots = native_storage_roots
    aliased = dict(roots)
    aliased["promoted_assets"] = roots["temporary_containment"]
    with pytest.raises(ValueError, match="native_root_purpose_mismatch|purpose_alias"):
        _capture_native(scope, aliased)
    assert roots["temporary_containment"]._path.exists()
    assert roots["promoted_assets"]._path.exists()


def test_native_root_from_another_scope_identity_is_refused(native_storage_roots):
    scope, _, api, roots = native_storage_roots
    alternate_scope = scope / "alternate-scope"
    api[2].CreateDirectory(str(alternate_scope), windows._security_attributes(api, windows._current_user(api)))
    other = windows.WindowsProtectedRootCharacterization.provision_asset_for_characterization(
        str(alternate_scope), "promoted_assets", characterization=True, disposable_opt_in=True)
    try:
        substituted = dict(roots)
        substituted["promoted_assets"] = other
        with pytest.raises(ValueError, match="approved_scope_identity_missing|unapproved_root"):
            _capture_native(scope, substituted)
        assert other._path.exists() and roots["promoted_assets"]._path.exists()
    finally:
        other.close()


def test_native_root_path_identity_substitution_is_refused(native_storage_roots):
    scope, _, _, roots = native_storage_roots
    root = roots["promoted_assets"]
    original = root._path
    root._path = roots["temporary_containment"]._path
    try:
        with pytest.raises(ValueError, match="native_root_identity_mismatch"):
            _capture_native(scope, roots)
    finally:
        root._path = original


def test_native_write_admission_observes_new_protected_file_and_limits_usage(native_storage_roots):
    scope, _, api, roots = native_storage_roots
    limits = _limits(assets=1024)
    owner = _capture_native(scope, roots, limits)
    operation = owner.begin_operation_for_characterization("fixture-operation")
    reservation = owner.reserve_for_characterization(
        operation, {"temporary_containment": admission.CapacityEstimate(100, 1)})
    write = owner.admit_write_for_characterization(operation, reservation)
    path = roots["temporary_containment"]._path / "new.bin"
    _, c, f, _, _, _ = api
    handle = f.CreateFile(str(path), c.GENERIC_WRITE | c.READ_CONTROL, c.FILE_SHARE_READ,
        windows._security_attributes(api, roots["temporary_containment"]._user), c.CREATE_NEW,
        c.FILE_ATTRIBUTE_NORMAL | 0x00200000, None)
    try:
        f.WriteFile(handle, b"abc")
    finally:
        handle.Close()
    summary = owner.complete_write_for_characterization(operation, write)
    row = next(row for row in summary["roots"] if row["purpose"] == "temporary_containment")
    assert row["reserved_bytes"] == 0 and row["observed_used_bytes"] == 3
    assert row["observed_used_entries"] == 1 and row["retained_uncertain_bytes"] == 0
    assert path.read_bytes() == b"abc"
    owner.close()


def test_native_unchanged_inventory_after_write_admission_retains_capacity(native_storage_roots):
    scope, _, _, roots = native_storage_roots
    owner = _capture_native(scope, roots, _limits(assets=1024))
    operation = owner.begin_operation_for_characterization("no-file-operation")
    reservation = owner.reserve_for_characterization(
        operation, {"temporary_containment": admission.CapacityEstimate(100, 1)})
    write = owner.admit_write_for_characterization(operation, reservation)
    before = tuple(sorted(path.name for path in roots["temporary_containment"]._path.iterdir()))

    with pytest.raises(ValueError, match="no_new_storage_observed"):
        owner.complete_write_for_characterization(operation, write)

    view = owner.readiness()
    row = next(row for row in view["roots"] if row["purpose"] == "temporary_containment")
    after = tuple(sorted(path.name for path in roots["temporary_containment"]._path.iterdir()))
    assert view["status"] == "unavailable"
    assert row["reserved_bytes"] == 0 and row["reserved_entries"] == 0
    assert row["observed_used_bytes"] == 0 and row["observed_used_entries"] == 0
    assert row["retained_uncertain_bytes"] == 100
    assert row["retained_uncertain_entries"] == 1
    assert before == after == ()
    owner.close()


def test_native_acl_drift_invalidates_and_retains_reservation(native_storage_roots):
    from test_generation_windows_protected_storage import mutate_disposable_acl
    scope, _, api, roots = native_storage_roots
    owner = _capture_native(scope, roots)
    operation = owner.begin_operation_for_characterization("fixture-operation")
    owner.reserve_for_characterization(
        operation, {"promoted_assets": admission.CapacityEstimate(100, 1)})
    mutate_disposable_acl(roots["promoted_assets"]._path, api, "writable_principal")
    view = owner.readiness()
    row = next(row for row in view["roots"] if row["purpose"] == "promoted_assets")
    assert view["status"] == "unavailable"
    assert row["reserved_bytes"] == 0 and row["retained_uncertain_bytes"] == 100
    owner.close()
