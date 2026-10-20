"""C2B-8D-19C-B four-root and independent Project binding characterization."""

import gc
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from core import generation_storage_admission as admission
from core import generation_windows_protected_storage as windows


_PURPOSES = admission._WRITABLE


def _synthetic_root(purpose, path, identity):
    root = object.__new__(windows.WindowsProtectedRootCharacterization)
    root._purpose = purpose
    root._path = Path(path)
    root._identity = identity
    root._closed = False
    return root


def test_profile_a_root_set_shape_is_exact_nonaliased_and_nonoverlapping(tmp_path):
    roots = {purpose: _synthetic_root(purpose, tmp_path / purpose, (1, index + 1))
             for index, purpose in enumerate(_PURPOSES)}
    assert admission._validate_profile_a_root_set_shape(roots) == roots

    with pytest.raises(ValueError, match="profile_a_four_roots_required"):
        admission._validate_profile_a_root_set_shape({purpose: roots[purpose]
                                                       for purpose in _PURPOSES[:-1]})
    with pytest.raises(ValueError, match="profile_a_root_alias"):
        admission._validate_profile_a_root_set_shape({
            **roots,
            "promoted_assets": _synthetic_root("promoted_assets", tmp_path / "promoted_assets",
                                                roots["temporary_containment"]._identity),
        })
    overlapping = dict(roots)
    overlapping["promoted_assets"] = _synthetic_root(
        "promoted_assets", tmp_path / "private_journal" / "nested", (2, 5))
    with pytest.raises(ValueError, match="profile_a_root_overlap"):
        admission._validate_profile_a_root_set_shape(overlapping)
    wrong_purpose = dict(roots)
    wrong_purpose["retained_uncertain"] = _synthetic_root(
        "promoted_assets", tmp_path / "retained_uncertain", (3, 1))
    with pytest.raises(ValueError, match="profile_a_root_purpose_mismatch"):
        admission._validate_profile_a_root_set_shape(wrong_purpose)


@pytest.fixture
def native_profile_a_roots(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows native characterization only")
    pytest.importorskip("win32security")
    api = windows._api()
    user = windows._current_user(api)
    scope = tmp_path / "profile-a-owner-only-scope"
    api[2].CreateDirectory(str(scope), windows._security_attributes(api, user))
    roots = {}
    try:
        for purpose in _PURPOSES:
            path = scope / purpose
            api[2].CreateDirectory(str(path), windows._security_attributes(api, user))
            roots[purpose] = windows.WindowsProtectedRootCharacterization.capture_for_characterization(
                str(scope), str(path), purpose,
                characterization=True, disposable_opt_in=True,
            )
        project = tmp_path / "user-selected-project.json"
        project.write_text('{"disposable":true}', encoding="utf-8")
        yield scope, roots, project, api
    finally:
        for root in roots.values():
            root.close()


def _capture_profile_a(scope, roots):
    return admission.WindowsProtectedStorageAdmissionCharacterization.capture_profile_a_root_set_for_characterization(
        str(scope), roots, characterization=True, disposable_opt_in=True,
    )


def _create_owner_only_fixture_file(path, root, content):
    api = root._api
    win32file, win32con = api[2], api[1]
    handle = win32file.CreateFile(
        str(path), win32con.GENERIC_WRITE, 0,
        windows._security_attributes(api, root._user),
        win32con.CREATE_NEW, win32con.FILE_ATTRIBUTE_NORMAL, None,
    )
    try:
        win32file.WriteFile(handle, content)
        win32file.FlushFileBuffers(handle)
    finally:
        handle.Close()


def _synthetic_profile_a_owner():
    owner = object.__new__(admission.WindowsProtectedStorageAdmissionCharacterization)
    owner._profile_a_root_set = True
    owner._roots = {purpose: object() for purpose in _PURPOSES}
    owner._closed = False
    owner._invalid = False
    owner._scope_lease = SimpleNamespace(_state="held")
    owner._lock = threading.RLock()
    owner._host_lifecycle_refs = []
    owner._ledger = SimpleNamespace(
        _lock=threading.RLock(), _operations={}, _active_write=None,
        _uncertain={purpose: [0, 0] for purpose in _PURPOSES}, close=lambda: None,
    )
    owner.readiness = lambda: {
        "status": "characterization_only" if not owner._closed else "unavailable",
        "root_set_contract": "profile_a_four_writable_roots",
        "scope_writer_lease": "held" if owner._scope_lease._state == "held" else "released",
    }
    return owner


def _synthetic_project_reference(path):
    reference = object.__new__(windows.WindowsProjectJsonReferenceCharacterization)
    reference._closed = False
    reference._path = Path(path)
    reference.readiness = lambda: {"status": "read_only_reference_observed"}
    return reference


def _child_try_scope_lease(scope, *, abandon=False, release=False):
    code = r'''
import os, sys
from pathlib import Path
from core import generation_windows_protected_storage as w
scope = Path(sys.argv[1])
api = w._api()
handle = w._open(scope, True, api)
try:
    identity = w._identity(handle)
finally:
    handle.Close()
lease = w.WindowsProtectedScopeWriterLease._acquire_for_characterization(
    scope, identity, api, w._current_user(api))
print("held", flush=True)
if sys.argv[2] == "abandon":
    os._exit(0)
if sys.argv[2] == "release":
    lease.release_settled_for_characterization()
    print("released", flush=True)
    sys.exit(0)
input()
lease.release_settled_for_characterization()
'''
    mode = "abandon" if abandon else "release" if release else "normal"
    return subprocess.run(
        [sys.executable, "-c", code, str(scope), mode],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=15,
    )


def test_profile_a_four_root_capacity_reuses_one_ledger_and_keeps_gates_closed(
        native_profile_a_roots):
    scope, roots, project, _api = native_profile_a_roots
    before_project = project.read_bytes()
    owner = _capture_profile_a(scope, roots)
    try:
        view = owner.readiness()
        assert set(owner._roots) == set(_PURPOSES)
        assert owner._profile_a_root_set is True
        assert view["root_set_contract"] == "profile_a_four_writable_roots"
        assert view["scope_writer_lease"] == "held"
        assert {row["purpose"] for row in view["roots"]} == set(_PURPOSES)
        assert not any(view[key] for key in (
            "execution_available", "protected_storage_available", "promotion_available",
            "candidate_publication_allowed", "project_save_allowed", "cleanup_allowed",
        ))
        assert view["authorship"] == "unverified"
        assert project.read_bytes() == before_project
        assert not Path(project).is_relative_to(scope)
    finally:
        owner.close()


def test_cross_process_lease_excludes_second_process_while_first_owner_is_live(
        native_profile_a_roots):
    scope, roots, _project, _api = native_profile_a_roots
    owner = _capture_profile_a(scope, roots)
    marker = owner._scope_lease._path
    try:
        result = _child_try_scope_lease(scope)
        # This child intentionally has no stdin attached, so it only returns
        # after lease acquisition fails; an accidental acquire exits nonzero.
        assert result.returncode != 0
        assert "scope_writer_lease_unavailable" in result.stderr
        assert marker.exists() and marker.stat().st_size == 0
    finally:
        owner.close()


def test_abandoned_scope_lease_is_not_taken_over_or_reconstructed(native_profile_a_roots):
    scope, roots, _project, _api = native_profile_a_roots
    result = _child_try_scope_lease(scope, abandon=True)
    assert result.returncode == 0 and result.stdout.strip() == "held"
    marker = next(scope.glob(".promptgraph-scope-lease-v1-*"))
    marker_bytes = marker.read_bytes()
    with pytest.raises(ValueError, match="scope_writer_lease_unavailable"):
        _capture_profile_a(scope, roots)
    assert marker.exists() and marker.read_bytes() == marker_bytes == b""


def test_uncertain_capacity_retains_scope_lease_and_never_admits_second_owner(
        native_profile_a_roots):
    scope, roots, _project, _api = native_profile_a_roots
    owner = _capture_profile_a(scope, roots)
    operation = owner.begin_operation_for_characterization("uncertain-profile-a-op")
    owner.reserve_for_characterization(
        operation, {"temporary_containment": admission.CapacityEstimate(8, 1)},
    )
    marker = owner._scope_lease._path
    owner.close()
    assert owner._scope_lease._state == "retained_uncertain"
    assert marker.exists()
    with pytest.raises(ValueError, match="storage_accounting_scope_already_captured"):
        _capture_profile_a(scope, roots)
    cross_process = _child_try_scope_lease(scope)
    assert cross_process.returncode != 0
    assert "scope_writer_lease_unavailable" in cross_process.stderr


def test_preexisting_inventory_remains_uncertain_and_holds_lease_across_close_and_process_boundary(
        native_profile_a_roots):
    scope, roots, _project, _api = native_profile_a_roots
    unknown_file = roots["temporary_containment"]._path / "preexisting-evidence.bin"
    _create_owner_only_fixture_file(
        unknown_file, roots["temporary_containment"], b"unattributed retained evidence",
    )
    owner = _capture_profile_a(scope, roots)
    marker = owner._scope_lease._path
    before = unknown_file.read_bytes()
    retained = next(row for row in owner.readiness()["roots"]
                    if row["purpose"] == "temporary_containment")
    assert retained["retained_uncertain_entries"] == 1
    assert retained["retained_uncertain_bytes"] == len(before)

    owner.close()
    assert owner._scope_lease._state == "retained_uncertain"
    assert marker.exists()
    second_process = _child_try_scope_lease(scope)
    assert second_process.returncode != 0
    assert "scope_writer_lease_unavailable" in second_process.stderr
    assert unknown_file.read_bytes() == before


def test_clean_empty_scope_releases_marker_for_a_later_process(native_profile_a_roots):
    scope, roots, _project, _api = native_profile_a_roots
    owner = _capture_profile_a(scope, roots)
    marker = owner._scope_lease._path
    assert marker.exists()

    owner.close()
    assert owner._scope_lease._state == "released"
    assert not marker.exists()
    later_process = _child_try_scope_lease(scope, release=True)
    assert later_process.returncode == 0
    assert later_process.stdout.splitlines() == ["held", "released"]
    assert not marker.exists()


def test_project_reference_detects_file_revision_change_and_rejects_reparse_alias(
        native_profile_a_roots, monkeypatch):
    _scope, _roots, project_path, api = native_profile_a_roots
    reference = windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
        str(project_path), characterization=True, disposable_opt_in=True,
    )
    try:
        assert reference.readiness()["status"] == "read_only_reference_observed"
        with pytest.raises(OSError):
            project_path.rename(project_path.with_name("moved.json"))
        assert reference.readiness()["status"] == "read_only_reference_observed"

        # A same-file edit retains the native file ID; size/last-write binding
        # must still make the previously captured Project reference stale.
        project_path.write_text('{"disposable":true,"changed":"with a larger body"}',
                                encoding="utf-8")
        assert reference.readiness()["status"] == "unsafe_or_unavailable"
    finally:
        reference.close()

    with pytest.raises(ValueError, match="reparse_or_link|unsafe_path|unsupported_path"):
        original_information = api[2].GetFileInformationByHandle

        def reparse_attribute(handle):
            information = original_information(handle)
            return (information[0] | 0x400, *information[1:])

        monkeypatch.setattr(api[2], "GetFileInformationByHandle", reparse_attribute)
        windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
            str(project_path), characterization=True, disposable_opt_in=True,
        )


def test_project_reference_rejects_native_directory_junction_ancestor(native_profile_a_roots):
    _scope, _roots, project_path, _api = native_profile_a_roots
    target_dir = project_path.parent / "junction-target"
    target_dir.mkdir()
    (target_dir / project_path.name).write_bytes(b'{"junction":true}')
    junction = project_path.parent / "project-junction"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target_dir)],
                   check=True, capture_output=True, text=True, timeout=10)
    try:
        alias_path = junction / project_path.name
        with pytest.raises(ValueError, match="reparse_or_link|unsupported_path"):
            windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
                str(alias_path), characterization=True, disposable_opt_in=True,
            )
        assert (target_dir / project_path.name).read_bytes() == b'{"junction":true}'
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(junction)],
                       check=True, capture_output=True, text=True, timeout=10)


def test_project_reference_acl_drift_is_detected_without_owner_only_policy(native_profile_a_roots):
    from test_generation_windows_protected_storage import mutate_disposable_acl

    _scope, _roots, project_path, api = native_profile_a_roots
    reference = windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
        str(project_path), characterization=True, disposable_opt_in=True,
    )
    try:
        assert reference.readiness()["status"] == "read_only_reference_observed"
        mutate_disposable_acl(project_path, api, "changed_owner_only")
        view = reference.readiness()
        assert view["status"] == "unsafe_or_unavailable"
        assert view["protected_root_acl_required"] is False
        assert view["project_save_allowed"] is False
    finally:
        reference.close()


def test_project_json_reference_uses_separate_read_only_policy_and_host_binding(
        native_profile_a_roots):
    from core.project import Project
    from ui.project_agent_session_pump import ProjectAgentSessionRuntime

    scope, roots, project_path, api = native_profile_a_roots
    original_bytes = project_path.read_bytes()
    project_reference = windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
        str(project_path), characterization=True, disposable_opt_in=True,
    )
    owner = _capture_profile_a(scope, roots)
    runtime = ProjectAgentSessionRuntime()
    project = Project(project_metadata={"name": "host-project"})
    runtime.opt_in_generation_original_host_lifecycle_for_characterization(
        project, str(project_path),
    )
    lifecycle = runtime._generation_original_host_lifecycle
    try:
        assert project_reference.readiness()["read_access_only"] is True
        assert project_reference.readiness()["protected_root_acl_required"] is False
        assert runtime.bind_generation_profile_a_storage_for_characterization(
            owner, project_reference,
        ) == "matched_reference_only"
        assert lifecycle.readiness()["profile_a_storage"] == "bound_reference_only"
        assert owner._closed is False

        project_b = Project(project_metadata={"name": "other-project"})
        runtime.synchronize_target(project_b, str(project_path.with_name("other.json")))
        assert lifecycle.readiness()["lifecycle_state"] == "closed"
        assert lifecycle.readiness()["profile_a_storage"] == "unbound"
        assert owner._closed is False and owner._scope_lease._state == "held"

        # Switching back creates a new lifecycle with no restored binding.
        runtime.synchronize_target(project, str(project_path))
        lifecycle_again = runtime._generation_original_host_lifecycle
        assert lifecycle_again is not lifecycle
        assert lifecycle_again.readiness()["profile_a_storage"] == "unbound"
        assert project_path.read_bytes() == original_bytes
        assert not any(owner.readiness()[key] for key in (
            "execution_available", "protected_storage_available", "promotion_available",
            "candidate_publication_allowed", "project_save_allowed",
        ))
    finally:
        runtime.close()
        project_reference.close()
        owner.close()
        assert project_path.read_bytes() == original_bytes


def test_owner_close_during_native_storage_observation_does_not_strand_unpublished_binding(
        native_profile_a_roots, monkeypatch):
    from core.project import Project
    from ui.project_agent_session_pump import ProjectAgentSessionRuntime

    scope, roots, project_path, _api = native_profile_a_roots
    reference = windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
        str(project_path), characterization=True, disposable_opt_in=True,
    )
    owner = _capture_profile_a(scope, roots)
    marker = owner._scope_lease._path
    runtime = ProjectAgentSessionRuntime()
    project = Project(project_metadata={"name": "close-during-storage-observation"})
    runtime.opt_in_generation_original_host_lifecycle_for_characterization(
        project, str(project_path),
    )
    lifecycle = runtime._generation_original_host_lifecycle
    actual_readiness = owner.readiness
    entered, release = threading.Event(), threading.Event()
    outcome = []

    def blocked_readiness():
        entered.set()
        assert release.wait(10)
        return actual_readiness()

    monkeypatch.setattr(owner, "readiness", blocked_readiness)

    def bind():
        outcome.append(runtime.bind_generation_profile_a_storage_for_characterization(
            owner, reference,
        ))

    thread = threading.Thread(target=bind)
    thread.start()
    try:
        assert entered.wait(10)
        owner.close()
        assert owner._scope_lease._state == "released"
        assert not marker.exists()
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    assert outcome == ["storage_observation_unavailable"]
    assert lifecycle.readiness()["profile_a_storage"] == "unbound"
    assert owner._host_lifecycle_refs == []
    runtime.close()
    reference.close()


def test_owner_close_serializes_with_successful_profile_a_binding_publication(monkeypatch):
    from core.project import Project
    from ui.project_agent_session_pump import ProjectAgentSessionRuntime

    class CloseObservedRLock:
        def __init__(self, close_attempted):
            self._lock = threading.RLock()
            self._close_attempted = close_attempted

        def __enter__(self):
            if threading.current_thread().name == "profile-a-owner-close":
                self._close_attempted.set()
            self._lock.acquire()
            return self

        def __exit__(self, *_exc_info):
            self._lock.release()

    path = r"C:\PG\publication-race.json"
    owner = _synthetic_profile_a_owner()
    reference = _synthetic_project_reference(path)
    runtime = ProjectAgentSessionRuntime()
    project = Project(project_metadata={"name": "publication-close-race"})
    runtime.opt_in_generation_original_host_lifecycle_for_characterization(project, path)
    lifecycle = runtime._generation_original_host_lifecycle
    original_observe = lifecycle.observe_profile_a_storage_binding_for_characterization
    callback_entered, callback_release = threading.Event(), threading.Event()
    close_attempted, close_done = threading.Event(), threading.Event()
    outcome = []

    def blocked_observe(capacity_owner, project_json_reference):
        callback_entered.set()
        assert callback_release.wait(10)
        return original_observe(capacity_owner, project_json_reference)

    monkeypatch.setattr(
        lifecycle, "observe_profile_a_storage_binding_for_characterization", blocked_observe,
    )
    owner._lock = CloseObservedRLock(close_attempted)

    binding_thread = threading.Thread(target=lambda: outcome.append(
        runtime.bind_generation_profile_a_storage_for_characterization(owner, reference)
    ))

    def close_owner():
        owner.close()
        close_done.set()

    binding_thread.start()
    assert callback_entered.wait(10)
    close_thread = threading.Thread(target=close_owner, name="profile-a-owner-close")
    close_thread.start()
    try:
        assert close_attempted.wait(10)
        assert not close_done.is_set()
    finally:
        callback_release.set()
        binding_thread.join(10)
        close_thread.join(10)

    assert not binding_thread.is_alive() and not close_thread.is_alive()
    assert outcome == ["matched_reference_only"]
    assert close_done.is_set() and owner._closed is True
    assert lifecycle.readiness()["profile_a_storage"] == "bound_reference_only"
    assert owner._host_lifecycle_refs == [lifecycle]
    runtime.close()


@pytest.mark.parametrize("invalidation_timing", ["before", "during"])
def test_profile_a_binding_requires_live_job_claim_at_both_host_snapshots(
        monkeypatch, invalidation_timing):
    from test_agent_generation_executor_handoff import ready, start

    owner = _synthetic_profile_a_owner()
    values = ready()
    runtime, _route, state = values[:3]
    assert start(values).status == "characterized_acceptance"
    assert runtime.opt_in_generation_original_host_lifecycle_for_characterization(
        state["project"], state["current_project_path"],
    ) == "bound_non_executing"
    lifecycle = runtime._generation_original_host_lifecycle

    # This test isolates the in-memory host/claim guard. Native root behavior
    # and real Project-file identity are covered by the Windows tests above.
    reference = _synthetic_project_reference(state["current_project_path"])

    if invalidation_timing == "before":
        runtime.generation_jobs.invalidate_execution_custody()
        result = runtime.bind_generation_profile_a_storage_for_characterization(
            owner, reference,
        )
        assert result == "host_evidence_unavailable"
    else:
        actual_readiness = owner.readiness
        entered, release = threading.Event(), threading.Event()
        outcome = []

        def blocked_readiness():
            entered.set()
            assert release.wait(10)
            return actual_readiness()

        monkeypatch.setattr(owner, "readiness", blocked_readiness)
        thread = threading.Thread(target=lambda: outcome.append(
            runtime.bind_generation_profile_a_storage_for_characterization(
                owner, reference,
            )
        ))
        thread.start()
        try:
            assert entered.wait(10)
            runtime.generation_jobs.invalidate_execution_custody()
        finally:
            release.set()
            thread.join(10)
        assert not thread.is_alive()
        assert outcome == ["host_evidence_unavailable"]

    assert lifecycle.readiness()["profile_a_storage"] == "unbound"
    assert owner._host_lifecycle_refs == []
    runtime.close()


def test_scope_lease_retains_host_lifecycle_for_late_worker_uncertainty(native_profile_a_roots):
    from core.project import Project
    from ui.project_agent_session_pump import ProjectAgentSessionRuntime

    scope, roots, project_path, _api = native_profile_a_roots
    owner = _capture_profile_a(scope, roots)
    project_reference = windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
        str(project_path), characterization=True, disposable_opt_in=True,
    )
    project = Project(project_metadata={"name": "lease-retention"})
    runtime = ProjectAgentSessionRuntime()
    runtime.opt_in_generation_original_host_lifecycle_for_characterization(project, str(project_path))
    assert runtime.bind_generation_profile_a_storage_for_characterization(
        owner, project_reference,
    ) == "matched_reference_only"
    lifecycle = runtime._generation_original_host_lifecycle
    integration = SimpleNamespace(
        _lock=threading.RLock(), _state="running", _active=object(), _uncertain_leases={},
    )
    lifecycle._worker_storage_integration = integration
    marker = owner._scope_lease._path
    owner.close()
    assert owner.release_scope_writer_lease_if_settled_for_characterization() == (
        "retained_for_active_host")
    assert marker.exists()

    project_reference.close()
    del runtime, lifecycle, project_reference, project
    gc.collect()
    with integration._lock:
        integration._state = "uncertain"
        integration._active = None
        integration._uncertain_leases = {"operation": object()}
    assert owner.release_scope_writer_lease_if_settled_for_characterization() == (
        "retained_uncertain")
    assert marker.exists()


def test_host_project_path_mismatch_and_target_change_during_native_observation_fail_closed(
        native_profile_a_roots, monkeypatch):
    from core.project import Project
    from ui.project_agent_session_pump import ProjectAgentSessionRuntime

    scope, roots, project_path, _api = native_profile_a_roots
    other_path = project_path.with_name("different-project.json")
    other_path.write_text('{"other":true}', encoding="utf-8")
    project_reference = windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
        str(other_path), characterization=True, disposable_opt_in=True,
    )
    matching_project_reference = windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
        str(project_path), characterization=True, disposable_opt_in=True,
    )
    owner = _capture_profile_a(scope, roots)
    runtime = ProjectAgentSessionRuntime()
    project = Project(project_metadata={"name": "host-project"})
    runtime.opt_in_generation_original_host_lifecycle_for_characterization(project, str(project_path))
    try:
        assert runtime.bind_generation_profile_a_storage_for_characterization(
            owner, project_reference,
        ) == "project_reference_mismatch"
        assert runtime._generation_original_host_lifecycle.readiness()["profile_a_storage"] == "unbound"

        actual_readiness = owner.readiness
        entered, release, switched = threading.Event(), threading.Event(), threading.Event()
        outcome = []

        def blocked_readiness():
            entered.set()
            assert release.wait(10)
            return actual_readiness()

        monkeypatch.setattr(owner, "readiness", blocked_readiness)

        def bind():
            outcome.append(runtime.bind_generation_profile_a_storage_for_characterization(
                owner, matching_project_reference,
            ))

        def switch_target():
            try:
                runtime.synchronize_target(Project(project_metadata={"name": "switched"}),
                                           str(other_path))
            finally:
                switched.set()

        bind_thread = threading.Thread(target=bind)
        bind_thread.start()
        try:
            assert entered.wait(10)
            switch_thread = threading.Thread(target=switch_target)
            switch_thread.start()
            assert switched.wait(10), "host switch blocked by native storage observation"
        finally:
            release.set()
            bind_thread.join(10)
            if "switch_thread" in locals():
                switch_thread.join(10)
        assert not bind_thread.is_alive()
        assert outcome == ["stale_host_binding"]
        assert runtime._generation_original_host_lifecycle.readiness()["profile_a_storage"] == "unbound"
        assert owner._host_lifecycle_refs == []
    finally:
        runtime.close()
        project_reference.close()
        matching_project_reference.close()
        owner.close()
