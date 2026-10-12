"""Real Windows disposable Journal ACLs plus portable opt-in contracts."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from core import generation_ownership_journal as j
from core import generation_protected_journal as p
from core import generation_windows_protected_storage as w
from test_generation_windows_protected_storage import native_scope, mutate_disposable_acl


@pytest.fixture
def rig(native_scope):
    scope, api = native_scope
    project = scope / "project"
    project.mkdir()
    project_file = project / "project.json"
    project_file.write_text('{"prompt_lines":[{"id":"line"}]}')
    selected = j.ApprovedRoot.capture_for_characterization("project", str(project), characterization=True)
    op = j.OperationObservation("operation", "job", "manifest",
        hashlib.sha256(project_file.read_bytes()).hexdigest(), "project", selected.path,
        selected.identity, "project.json", j._file_identity(project_file.stat()),
        "process", "session", "claim", "c" * 64,
        (j.FrozenRequestCorrelation("request", 0, "line", 1, "workflow"),))
    owner = p.WindowsProtectedJournalCharacterization.provision_for_characterization(
        str(scope), characterization=True, disposable_opt_in=True)
    try:
        yield owner, scope, api, op, selected
    finally:
        owner.close()


def intent():
    return j.Observation("submission_intent", "intent")


def observed():
    return j.Observation("submission_observed", "unknown")


def assert_no_authority(view):
    assert view["execution_available"] is False
    assert view["protected_storage_available"] is False
    assert view["authorship"] == "unverified"
    for key in ("recovery_execution_allowed", "attachment_allowed", "publication_allowed",
                "project_save_allowed", "cleanup_allowed", "writer_retry_allowed"):
        assert view[key] is False
    assert view["trusted_latest_revision"] == "unavailable"


def assert_files_protected(owner, api):
    for path in owner._native._path.iterdir():
        handle = w._open(path, False, api)
        try:
            assert w._acl(handle, api, w._current_user(api))
            assert w._identity(handle) == w._ordinary(path, directory=False)
        finally:
            handle.Close()


def test_native_lifecycle_and_all_child_file_acls(rig):
    owner, scope, api, op, selected = rig
    events = []
    def inspect(boundary):
        events.append(boundary)
        assert_files_protected(owner, api)
    owner._fault = inspect
    owner.initialize_for_characterization(op)
    first = owner.append_for_characterization(intent())
    second = owner.append_for_characterization(observed())
    assert (first.revision, second.revision) == (1, 2)
    assert events.count("after_file_create") == 4  # both lock and temporary files, two revisions
    assert events.count("before_replace") == 2
    assert events.count("after_replace_before_ack") == 2
    assert list(owner._native._path.iterdir()) == [owner._native._path / "operation.json"]
    assert owner.reopen_journal_for_characterization("operation.json") == second
    inventory = owner.inspect_inventory_for_characterization()
    assert inventory.journals == (second,) and not inventory.errors
    assert inventory.trust == "inspect_only" and not inventory.execution_available
    view = owner.inspect_human_recovery_for_characterization("operation.json", selected_project_root=selected)
    assert view["status"] == "inspect_only" and not view["execution_available"]
    assert view["journal"]["authenticity"] == "unverified"
    assert_no_authority(owner.readiness())
    assert str(scope) not in json.dumps(owner.readiness())
    assert not list((scope / "project").glob("*.lock"))


@pytest.mark.parametrize("boundary,revision", [("before_replace", 1), ("after_replace_before_ack", 2),
                                             ("after_operation_before_ack", 2)])
def test_native_unknown_ack_retains_evidence_and_never_retries(rig, boundary, revision):
    owner, _, api, op, _ = rig
    owner.initialize_for_characterization(op)
    owner.append_for_characterization(intent())
    def crash(point):
        if point == boundary:
            raise RuntimeError("unknown acknowledgment")
    owner._fault = crash
    owner._writer.fault = crash
    with pytest.raises(RuntimeError):
        owner.append_for_characterization(observed())
    owner._fault = lambda _: None
    assert owner.reopen_journal_for_characterization("operation.json").revision == revision
    assert owner.readiness()["journal_lifecycle"] == "uncertain"
    with pytest.raises(ValueError, match="writer_unavailable"):
        owner.append_for_characterization(observed())
    if boundary != "after_operation_before_ack":
        assert (owner._native._path / "operation.lock").exists()
    if boundary == "before_replace":
        assert list(owner._native._path.glob("*.tmp"))
    assert_files_protected(owner, api)


@pytest.mark.parametrize("boundary", ["after_file_create", "before_replace", "after_replace_before_ack",
                                    "after_operation_before_ack"])
def test_native_acl_change_during_append_fails_closed(rig, boundary):
    owner, _, api, op, _ = rig
    owner.initialize_for_characterization(op)
    def change(point):
        if point == boundary:
            mutate_disposable_acl(owner._native._path, api, "writable_principal")
    owner._fault = change
    owner._writer.fault = change
    with pytest.raises(ValueError, match="protected_root_unavailable"):
        owner.append_for_characterization(intent())
    assert owner._uncertain and owner._writer._uncertain
    assert owner.readiness()["journal_lifecycle"] == "unsafe_or_unavailable"
    assert list(owner._native._path.iterdir())  # no deletion of uncertain evidence
    with pytest.raises(ValueError):
        owner.inspect_inventory_for_characterization()


@pytest.mark.parametrize("kind", ["lock", "temp", "final"])
def test_native_unsafe_file_refused_and_retained(rig, kind):
    owner, _, api, op, _ = rig
    owner.initialize_for_characterization(op)
    def change(point):
        paths = list(owner._native._path.iterdir())
        target = next((f for f in paths if (kind == "lock" and f.suffix == ".lock")
            or (kind == "temp" and f.suffix == ".tmp") or (kind == "final" and f.suffix == ".json")), None)
        if target:
            mutate_disposable_acl(target, api, "writable_principal")
    owner._fault = change
    owner._writer.fault = change
    with pytest.raises(ValueError, match="unsafe_acl"):
        owner.append_for_characterization(intent())
    assert owner._uncertain and list(owner._native._path.iterdir())
    assert_no_authority(owner.readiness())


def test_native_concurrent_writer_conflict_no_takeover(rig):
    owner, _, _, op, _ = rig
    owner.initialize_for_characterization(op)
    called = []
    def competitor(point):
        if point == "before_replace":
            other = p._ProtectedWriter(owner, op, lambda _: None)
            with pytest.raises(ValueError, match="exclusive_file_unavailable"):
                other.append_for_characterization(intent())
            called.append(True)
    owner._writer.fault = competitor
    assert owner.append_for_characterization(intent()).revision == 1
    assert called == [True]


def test_native_closed_lifecycle_fresh_reopen_inspect_only(rig):
    owner, scope, _, op, _ = rig
    owner.initialize_for_characterization(op)
    owner.append_for_characterization(intent())
    path = owner._native._path
    owner.close()
    with pytest.raises(ValueError, match="protected_root_unavailable"):
        owner.reopen_journal_for_characterization("operation.json")
    assert_no_authority(owner.readiness())
    with p.WindowsProtectedJournalCharacterization.reopen_for_characterization(str(scope), str(path),
            characterization=True, disposable_opt_in=True) as reopened:
        assert reopened.reopen_journal_for_characterization("operation.json").revision == 1
        with pytest.raises(ValueError, match="writer_unavailable"):
            reopened.initialize_for_characterization(op)
        assert_no_authority(reopened.readiness())


def test_native_root_and_scope_substitution_refused(rig):
    owner, scope, _, op, _ = rig
    owner.initialize_for_characterization(op)
    for path in (scope, owner._native._path):
        with pytest.raises(OSError):
            path.rename(path.with_name("substitution"))
    assert owner.append_for_characterization(intent()).revision == 1


def test_native_reopen_incomplete_rollback_and_missing_project(rig):
    owner, _, _, op, _ = rig
    owner.initialize_for_characterization(op)
    first = owner.append_for_characterization(intent())
    path = owner._native._path / "operation.json"
    original = path.read_bytes()
    second = owner.append_for_characterization(observed())
    path.write_bytes(original)  # same-user rollback does not change the owner-only ACL
    assert owner.reopen_journal_for_characterization("operation.json").revision == 1
    with pytest.raises(ValueError, match="stale_revision"):
        owner.reopen_journal_for_characterization("operation.json", expected_revision=second.revision)
    assert owner.reopen_journal_for_characterization("operation.json", expected_digest=first.digest).authenticity == "unverified"
    view = owner.inspect_human_recovery_for_characterization("operation.json")
    assert view["project"] == "different_selected_project" and view["status"] == "inspect_only"
    path.write_bytes(b'{"interrupted":')
    with pytest.raises(ValueError):
        owner.reopen_journal_for_characterization("operation.json")
    assert owner.inspect_inventory_for_characterization().errors
    assert owner.inspect_human_recovery_for_characterization("operation.json")["journal"]["revision"] is None
    assert path.exists()


def test_native_unsupported_filesystem_and_dependency_are_closed(native_scope):
    scope, _ = native_scope
    with patch.object(w, "_filesystem", side_effect=ValueError("unsupported_filesystem")):
        with pytest.raises(ValueError, match="unsupported_filesystem"):
            p.WindowsProtectedJournalCharacterization.provision_for_characterization(str(scope),
                characterization=True, disposable_opt_in=True)
    with patch.object(w, "_api", side_effect=ValueError("native_dependency_unavailable")):
        with pytest.raises(ValueError, match="native_dependency_unavailable"):
            p.WindowsProtectedJournalCharacterization.provision_for_characterization(str(scope),
                characterization=True, disposable_opt_in=True)
    assert not list(scope.iterdir())


def test_native_fsync_failure_retains_lock_and_temp(rig):
    owner, _, api, op, _ = rig
    owner.initialize_for_characterization(op)
    with patch.object(j.os, "fsync", side_effect=OSError("sync interrupted")):
        with pytest.raises(OSError):
            owner.append_for_characterization(intent())
    assert owner._uncertain
    assert not list(owner._native._path.glob("*.json"))
    assert list(owner._native._path.glob("*.tmp"))
    assert list(owner._native._path.glob("*.lock"))
    assert_files_protected(owner, api)


def test_native_missing_original_project_is_read_only(rig):
    owner, scope, _, op, original = rig
    missing_directory = scope / "missing-project"
    missing_directory.mkdir()
    selected = j.ApprovedRoot.capture_for_characterization("project", str(missing_directory), characterization=True)
    op = replace(op, project_root_path=selected.path, project_root_identity=selected.identity)
    original_bytes = (Path(original.path) / "project.json").read_bytes()
    owner.initialize_for_characterization(op)
    owner.append_for_characterization(intent())
    view = owner.inspect_human_recovery_for_characterization("operation.json", selected_project_root=selected)
    assert view["project"] == "missing" and not view["execution_available"]
    assert not list(Path(selected.path).iterdir())
    assert (Path(original.path) / "project.json").read_bytes() == original_bytes


def test_native_changed_compatible_file_acl_during_creation_is_not_new_baseline(rig):
    owner, _, api, op, _ = rig
    owner.initialize_for_characterization(op)
    def change(point):
        if point == "after_file_create":
            path = next(owner._native._path.iterdir())
            mutate_disposable_acl(path, api, "changed_owner_only")
    owner._fault = change
    with pytest.raises(ValueError, match="native_observation_changed"):
        owner.append_for_characterization(intent())
    assert owner._uncertain and owner._writer._uncertain
    assert (owner._native._path / "operation.lock").exists()
    assert_no_authority(owner.readiness())


def test_native_failed_read_still_revalidates_protection(rig):
    owner, _, api, op, _ = rig
    owner.initialize_for_characterization(op)
    owner.append_for_characterization(intent())
    def unreadable(*args, **kwargs):
        mutate_disposable_acl(owner._native._path, api, "writable_principal")
        raise ValueError("unreadable_journal")
    with patch.object(j, "reopen_journal", unreadable):
        with pytest.raises(ValueError, match="protected_root_unavailable"):
            owner.reopen_journal_for_characterization("operation.json")
    assert owner.readiness()["journal_lifecycle"] == "unsafe_or_unavailable"


def test_native_existing_nested_reopen_pins_intermediate_and_detects_acl_change(native_scope):
    scope, api = native_scope
    intermediate = scope / "nested"
    path = intermediate / "journal"
    for directory in (intermediate, path):
        api[2].CreateDirectory(str(directory), w._security_attributes(api, w._current_user(api)))
    with p.WindowsProtectedJournalCharacterization.reopen_for_characterization(str(scope), str(path),
            characterization=True, disposable_opt_in=True) as owner:
        with pytest.raises(OSError):
            intermediate.rename(scope / "replacement")
        assert not owner.inspect_inventory_for_characterization().journals
        mutate_disposable_acl(intermediate, api, "writable_principal")
        with pytest.raises(ValueError, match="protected_root_unavailable"):
            owner.inspect_inventory_for_characterization()
        assert not owner.readiness()["acl_verified"]
    assert path.exists() and not list(path.iterdir())


@pytest.mark.parametrize("operation", ["reopen", "inventory", "recovery"])
def test_native_failed_post_read_verification_withholds_result(rig, operation):
    owner, _, api, op, _ = rig
    owner.initialize_for_characterization(op)
    owner.append_for_characterization(intent())
    def change(point):
        if point == "after_operation_before_ack":
            mutate_disposable_acl(owner._native._path, api, "writable_principal")
    owner._fault = change
    with pytest.raises(ValueError, match="protected_root_unavailable"):
        if operation == "reopen":
            owner.reopen_journal_for_characterization("operation.json")
        elif operation == "inventory":
            owner.inspect_inventory_for_characterization()
        else:
            owner.inspect_human_recovery_for_characterization("operation.json")


def test_opt_ins_and_private_constructor_remain_closed(tmp_path):
    with patch.object(w, "_api", side_effect=AssertionError("no native call")):
        for options in ({}, {"characterization": True}, {"disposable_opt_in": True}):
            with pytest.raises(ValueError, match="execution_unavailable"):
                p.WindowsProtectedJournalCharacterization.provision_for_characterization(str(tmp_path), **options)
    with pytest.raises(ValueError, match="host_storage_required"):
        p.WindowsProtectedJournalCharacterization(None, None, True, lambda _: None)
    assert not list(tmp_path.iterdir())
