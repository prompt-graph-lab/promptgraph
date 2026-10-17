"""Offline contracts for the separately identified multi-request Journal."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from core import generation_ownership_journal as legacy
from core import generation_multi_request_journal as multi


def make_operation(project_root, count=2, *, long_ids=False):
    project_file = project_root / "project.json"
    project_file.write_text(json.dumps({"prompt_lines": [{"id": f"line-{i}"} for i in range(count)]}))
    approved = legacy.ApprovedRoot.capture_for_characterization(
        "project", str(project_root), characterization=True)
    width = 140 if long_ids else 1
    requests = tuple(legacy.FrozenRequestCorrelation(
        f"request-{i}-" + "r" * width, i, f"line-{i}-" + "l" * width,
        1 + (i % 5), f"workflow-{i}-" + "w" * width) for i in range(count))
    operation = legacy.OperationObservation("operation", "job", "manifest",
        hashlib.sha256(project_file.read_bytes()).hexdigest(), approved.key, approved.path,
        approved.identity, "project.json", legacy._file_identity(project_file.stat()),
        "process", "session", "claim", "c" * 64, requests)
    return approved, operation


def new_writer(tmp_path, count=2, **kwargs):
    project = tmp_path / "project"
    project.mkdir(parents=True)
    project_root, operation = make_operation(project, count, **kwargs)
    journal_path = tmp_path / "journal"
    journal_path.mkdir(parents=True)
    journal_root = legacy.ApprovedRoot.capture_for_characterization(
        "journal", str(journal_path), characterization=True)
    writer = multi.MultiRequestJournalWriter(journal_root, operation, characterization=True)
    return journal_root, operation, writer


def settle(writer, tip, index, disposition="execution_completed", prompt_id="prompt"):
    operation = writer.operation
    request = operation.requests[index]
    facts = multi.ValidatedOriginalHostSettlement(
        operation.operation_id, operation.job_id, operation.claim_id, operation.manifest_identity,
        operation.process_identity, operation.session_identity, index, request.request_id,
        request.illustration_id, request.run_index, request.workflow_identity, disposition,
        prompt_id, f"host-observation-{index}", tip.revision, tip.digest)
    return multi._issue_original_host_settlement_for_characterization(
        writer, tip, index, lambda observed_operation, observed_request, observed_tip: facts)


def test_several_requests_follow_intent_outcome_and_host_settlement_chain(tmp_path):
    root, operation, writer = new_writer(tmp_path, 3)
    tip = None
    for index in range(3):
        tip = writer.append_intent_for_characterization(tip, index)
        assert tip.revision == index * 3 + 1
        tip = writer.append_submission_outcome_for_characterization(
            tip, "accepted", f"prompt-{index}")
        with pytest.raises(ValueError, match="invalid_request_order"):
            writer.append_intent_for_characterization(tip, index + 1)
        disposition = "execution_failed" if index == 0 else "execution_completed"
        observed = settle(writer, tip, index, disposition, f"prompt-{index}")
        tip = writer.append_settlement_for_characterization(tip, observed)
    reopened = multi.reopen_multi_request_journal(root, "operation.json")
    assert reopened.operation == operation
    assert reopened.revision == 9
    assert reopened.next_request_index == 3
    assert reopened.state == "all_requests_settled"
    assert [type(event) for event in reopened.events] == [
        multi.SubmissionIntent, multi.SubmissionOutcome, multi.RequestSettlement] * 3
    assert reopened.trust == "inspect_only"
    assert reopened.execution_available is False
    assert reopened.authorship == "unverified"


def test_definite_pre_send_rejection_requires_original_host_settlement_before_next(tmp_path):
    _, _, writer = new_writer(tmp_path, 2)
    tip = writer.append_intent_for_characterization(None, 0)
    tip = writer.append_submission_outcome_for_characterization(tip, "pre_send_rejected")
    with pytest.raises(ValueError, match="invalid_request_order"):
        writer.append_intent_for_characterization(tip, 1)
    observation = settle(writer, tip, 0, "pre_send_rejected", None)
    tip = writer.append_settlement_for_characterization(tip, observation)
    assert writer.append_intent_for_characterization(tip, 1).revision == 4


def test_accepted_or_unknown_without_settlement_never_authorizes_later_intent(tmp_path):
    _, _, writer = new_writer(tmp_path, 2)
    tip = writer.append_intent_for_characterization(None, 0)
    tip = writer.append_submission_outcome_for_characterization(tip, "accepted", "prompt-0")
    with pytest.raises(ValueError, match="invalid_request_order"):
        writer.append_intent_for_characterization(tip, 1)

    root2, _, writer2 = new_writer(tmp_path / "unknown", 2)
    tip2 = writer2.append_intent_for_characterization(None, 0)
    tip2 = writer2.append_submission_outcome_for_characterization(tip2, "unknown")
    with pytest.raises(ValueError, match="invalid_request_order"):
        writer2.append_intent_for_characterization(tip2, 1)
    with pytest.raises(ValueError, match="settlement_not_expected"):
        writer2.append_settlement_for_characterization(tip2, settle(writer2, tip2, 0, "execution_failed", "prompt"))
    assert multi.reopen_multi_request_journal(root2, "operation.json").state == "submission_outcome_unknown"


def test_exact_ack_tip_and_request_order_are_required(tmp_path):
    _, _, writer = new_writer(tmp_path, 2)
    with pytest.raises(ValueError, match="invalid_request_order"):
        writer.append_intent_for_characterization(None, 1)
    tip = writer.append_intent_for_characterization(None, 0)
    with pytest.raises(ValueError, match="acknowledged_tip_conflict"):
        writer.append_submission_outcome_for_characterization(replace(tip), "accepted", "prompt")
    with pytest.raises(ValueError, match="invalid_request_order"):
        writer.append_intent_for_characterization(tip, 1)
    tip = writer.append_submission_outcome_for_characterization(tip, "accepted", "prompt")
    with pytest.raises(ValueError, match="submission_outcome_not_expected"):
        writer.append_submission_outcome_for_characterization(tip, "accepted", "prompt")
    with pytest.raises(ValueError, match="settlement_outcome_mismatch"):
        settle(writer, tip, 0, "execution_completed", "different-prompt")
    counterfeit = settle(writer, tip, 0, "execution_completed", "prompt")
    copied = replace(counterfeit)
    with pytest.raises(ValueError, match="original_host_settlement_required"):
        writer.append_settlement_for_characterization(tip, copied)
    next_tip = writer.append_settlement_for_characterization(tip, counterfeit)
    with pytest.raises(ValueError, match="acknowledged_tip_conflict"):
        writer.append_intent_for_characterization(tip, 1)
    assert next_tip.revision == 3


@pytest.mark.parametrize("boundary,expected_revision", [("before_replace", 0), ("after_replace_before_ack", 1)])
def test_replace_failures_are_uncertain_and_reopen_is_inspect_only(tmp_path, boundary, expected_revision):
    root, _, writer = new_writer(tmp_path)
    writer.fault = lambda observed: (_ for _ in ()).throw(RuntimeError("injected")) if observed == boundary else None
    with pytest.raises(RuntimeError, match="injected"):
        writer.append_intent_for_characterization(None, 0)
    assert writer._uncertain is True
    with pytest.raises(ValueError, match="writer_uncertain"):
        writer.append_intent_for_characterization(None, 0)
    if expected_revision:
        reopened = multi.reopen_multi_request_journal(root, "operation.json")
        assert reopened.revision == expected_revision
        assert reopened.state == "intent_outcome_unknown"
    else:
        assert not (Path(root.path) / "operation.json").exists()
    assert (Path(root.path) / "operation.lock").exists()
    if not expected_revision:
        assert list(Path(root.path).glob("operation.*.tmp"))


def test_digest_tip_file_identity_and_cross_schema_conflicts_fail_closed(tmp_path):
    root, _, writer = new_writer(tmp_path, 1)
    tip = writer.append_intent_for_characterization(None, 0)
    path = Path(root.path) / "operation.json"
    raw = json.loads(path.read_text())
    raw["revisions"][0]["event"]["request_id"] = "substituted"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="request_identity_conflicting|digest_mismatch"):
        multi.reopen_multi_request_journal(root, "operation.json")
    with pytest.raises(ValueError, match="conflicting_revision|file_identity_changed|digest_mismatch|request_identity_conflicting"):
        writer.append_submission_outcome_for_characterization(tip, "accepted", "prompt")
    assert writer._uncertain is True


def test_reopen_checks_approved_root_and_never_resumes_a_live_writer(tmp_path):
    root, operation, writer = new_writer(tmp_path, 1)
    writer.append_intent_for_characterization(None, 0)
    view = multi.reopen_multi_request_journal(root, "operation.json")
    assert view.state == "intent_outcome_unknown"
    assert view.trust == "inspect_only" and not view.execution_available
    with pytest.raises(ValueError, match="stale_revision"):
        multi.reopen_multi_request_journal(root, "operation.json", expected_revision=2)
    with pytest.raises(ValueError, match="conflicting_revision"):
        multi.reopen_multi_request_journal(root, "operation.json", expected_digest="0" * 64)

    other_path = tmp_path / "other-journal"
    other_path.mkdir()
    other_root = legacy.ApprovedRoot.capture_for_characterization(
        "other-journal", str(other_path), characterization=True)
    (other_path / "operation.json").write_bytes((Path(root.path) / "operation.json").read_bytes())
    with pytest.raises(ValueError, match="root_identity_changed"):
        multi.reopen_multi_request_journal(other_root, "operation.json")

    resumed = multi.MultiRequestJournalWriter(root, operation, characterization=True)
    with pytest.raises(ValueError, match="conflicting_revision"):
        resumed.append_intent_for_characterization(None, 0)
    assert resumed._uncertain is True


def test_worst_case_capacity_is_reserved_before_first_intent(tmp_path, monkeypatch):
    root, operation, _ = new_writer(tmp_path, 100, long_ids=True)
    maximum, cumulative = multi._maximum_workload(operation, root)
    assert 0 < maximum <= multi.MAX_FILE_BYTES
    assert 0 < cumulative <= multi.MAX_CUMULATIVE_WRITE_BYTES
    assert multi.MAX_REQUESTS == 100
    assert multi.MAX_REVISIONS == 300
    assert multi.MAX_RETAINED_OBSERVATIONS == 300

    monkeypatch.setattr(multi, "MAX_CUMULATIVE_WRITE_BYTES", 1)
    with pytest.raises(ValueError, match="journal_write_budget_exceeded"):
        multi.MultiRequestJournalWriter(root, operation, characterization=True)
    assert not (Path(root.path) / "operation.json").exists()
    assert not (Path(root.path) / "operation.lock").exists()

    monkeypatch.setattr(multi, "MAX_CUMULATIVE_WRITE_BYTES", 128 * 1024 * 1024)
    monkeypatch.setattr(multi, "MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError, match="journal_capacity_exceeded"):
        multi.MultiRequestJournalWriter(root, operation, characterization=True)
    assert not (Path(root.path) / "operation.json").exists()


def test_refuse_over_revision_ceiling_without_authorizing_next_request(tmp_path, monkeypatch):
    root, _, writer = new_writer(tmp_path, 2)
    monkeypatch.setattr(multi, "MAX_REVISIONS", 3)
    monkeypatch.setattr(multi, "MAX_RETAINED_OBSERVATIONS", 3)
    tip = writer.append_intent_for_characterization(None, 0)
    tip = writer.append_submission_outcome_for_characterization(tip, "pre_send_rejected")
    tip = writer.append_settlement_for_characterization(tip, settle(writer, tip, 0, "pre_send_rejected", None))
    with pytest.raises(ValueError, match="revision_limit_exceeded"):
        writer.append_intent_for_characterization(tip, 1)
    assert multi.reopen_multi_request_journal(root, "operation.json").next_request_index == 1


def test_existing_v1_eight_checkpoint_format_remains_separate(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    project_root, operation = make_operation(project, 1)
    journal_path = tmp_path / "legacy"
    journal_path.mkdir()
    root = legacy.ApprovedRoot.capture_for_characterization("journal", str(journal_path), characterization=True)
    writer = legacy.OfflineJournalWriter(root, operation, characterization=True)
    writer.append_for_characterization(legacy.Observation("submission_intent", "intent"))
    with pytest.raises(ValueError, match="unknown_version"):
        multi.reopen_multi_request_journal(root, "operation.json")
    assert legacy.reopen_journal(root, "operation.json").revision == 1
