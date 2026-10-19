"""Focused C2B-8D-17A storage admission characterization tests."""
import sys
import threading

import pytest

from core import generation_storage_admission as admission
from core import generation_windows_protected_storage as windows


def _limits(*, assets=100, retained=100):
    return admission.ProtectedStorageCapacityLimits(
        journal_bytes=1000, shared_temporary_and_promoted_bytes=assets,
        retained_uncertain_bytes=retained, journal_entries=20,
        shared_temporary_and_promoted_entries=4, retained_uncertain_entries=20)


def _empty_inventory():
    return {purpose: {} for purpose in admission._WRITABLE}


def _ready_ledger(limits=None):
    result = admission._CapacityLedger(limits or _limits())
    result.set_initial_inventory(_empty_inventory())
    return result


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
