"""Native Windows ACL characterization for the multi-request Journal."""
import hashlib
import json
from pathlib import Path

import pytest

from core import generation_ownership_journal as legacy
from core import generation_multi_request_journal as multi
from core import generation_protected_journal as protected
from core import generation_windows_protected_storage as windows
from test_generation_windows_protected_storage import native_scope, mutate_disposable_acl


@pytest.fixture
def rig(native_scope):
    scope, api = native_scope
    project = scope / "project"
    project.mkdir()
    project_file = project / "project.json"
    project_file.write_text(json.dumps({"prompt_lines": [{"id": "line-0"}, {"id": "line-1"}]}))
    approved = legacy.ApprovedRoot.capture_for_characterization(
        "project", str(project), characterization=True)
    requests = tuple(legacy.FrozenRequestCorrelation(
        f"request-{index}", index, f"line-{index}", 1, f"workflow-{index}") for index in range(2))
    operation = legacy.OperationObservation("operation", "job", "manifest",
        hashlib.sha256(project_file.read_bytes()).hexdigest(), approved.key, approved.path,
        approved.identity, "project.json", legacy._file_identity(project_file.stat()),
        "process", "session", "claim", "c" * 64, requests)
    owner = protected.WindowsProtectedJournalCharacterization.provision_for_characterization(
        str(scope), characterization=True, disposable_opt_in=True)
    try:
        yield owner, scope, api, operation
    finally:
        owner.close()


def assert_all_children_protected(owner, api):
    paths = list(owner._native._path.iterdir())
    assert paths
    for path in paths:
        handle = windows._open(path, False, api)
        try:
            assert windows._acl(handle, api, windows._current_user(api))
            assert windows._identity(handle) == windows._ordinary(path, directory=False)
        finally:
            handle.Close()


def host_settlement(writer, tip, index, prompt_id):
    operation = writer.operation
    request = operation.requests[index]
    facts = multi.ValidatedOriginalHostSettlement(
        operation.operation_id, operation.job_id, operation.claim_id, operation.manifest_identity,
        operation.process_identity, operation.session_identity, index, request.request_id,
        request.illustration_id, request.run_index, request.workflow_identity,
        "execution_completed", prompt_id, f"native-host-observation-{index}",
        tip.revision, tip.digest)
    return multi._issue_original_host_settlement_for_characterization(
        writer, tip, index, lambda observed_operation, observed_request, observed_tip: facts)


def test_native_multi_request_lifecycle_keeps_every_child_acl_protected(rig):
    owner, scope, api, operation = rig
    events = []

    def verify(boundary):
        events.append(boundary)
        if list(owner._native._path.iterdir()):
            assert_all_children_protected(owner, api)

    owner._fault = verify
    owner.initialize_multi_request_for_characterization(operation)
    writer = owner._multi_request_writer
    tip = None
    for index in range(2):
        tip = owner.append_multi_request_intent_for_characterization(tip, index)
        tip = owner.append_multi_request_outcome_for_characterization(tip, "accepted", f"prompt-{index}")
        settlement = host_settlement(writer, tip, index, f"prompt-{index}")
        tip = owner.append_multi_request_settlement_for_characterization(tip, settlement)
    assert tip.revision == 6
    assert events.count("before_replace") == 6
    assert events.count("after_replace_before_ack") == 6
    assert events.count("after_file_create") == 12
    reopened = owner.reopen_multi_request_journal_for_characterization("operation.json")
    assert reopened.state == "all_requests_settled"
    assert reopened.revision == 6
    assert reopened.execution_available is False
    assert reopened.trust == "inspect_only" and reopened.authorship == "unverified"
    assert_all_children_protected(owner, api)

    journal_dir = owner._native._path
    owner.close()
    with pytest.raises(ValueError, match="protected_root_unavailable"):
        owner.reopen_multi_request_journal_for_characterization("operation.json")
    with protected.WindowsProtectedJournalCharacterization.reopen_for_characterization(
            str(scope), str(journal_dir), characterization=True, disposable_opt_in=True) as reopened_owner:
        reopened_view = reopened_owner.reopen_multi_request_journal_for_characterization("operation.json")
        assert reopened_view == reopened
        with pytest.raises(ValueError, match="writer_unavailable"):
            reopened_owner.initialize_multi_request_for_characterization(operation)


def test_native_acl_drift_during_multi_request_append_fails_closed_and_retains_files(rig):
    owner, _, api, operation = rig
    owner.initialize_multi_request_for_characterization(operation)

    def change_acl(boundary):
        if boundary == "after_file_create":
            paths = list(owner._native._path.iterdir())
            target = next((path for path in paths if path.suffix == ".tmp"), paths[0])
            mutate_disposable_acl(target, api, "writable_principal")

    owner._fault = change_acl
    owner._multi_request_writer.fault = change_acl
    with pytest.raises(ValueError):
        owner.append_multi_request_intent_for_characterization(None, 0)
    assert owner.readiness()["journal_lifecycle"] == "unsafe_or_unavailable"
    assert owner._uncertain is True
    assert list(owner._native._path.iterdir())
