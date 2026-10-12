"""Offline disposable evidence; no transport, live Project or recovery writer."""
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core import generation_ownership_journal as j
from PIL import Image


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (4, 3)).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def rig(tmp_path):
    roots = []
    for key in ("journal", "project", "contained", "promoted"):
        path = tmp_path / key
        path.mkdir()
        roots.append(j.ApprovedRoot.capture_for_characterization(key, str(path), characterization=True))
    journal, project, contained, promoted = roots
    project_path = Path(project.path) / "project.json"
    project_path.write_text(json.dumps({"prompt_lines": [{"id": "line", "generated_candidates": []}], "unknown": {"keep": 7}}))
    op = j.OperationObservation("operation", "job", "manifest", hashlib.sha256(project_path.read_bytes()).hexdigest(), "project", project.path, project.identity, "project.json",
                                j._file_identity(project_path.stat()), "process", "session", "claim", "c" * 64,
                                (j.FrozenRequestCorrelation("request", 0, "line", 1, "workflow"),))
    candidate = j.CandidateObservation("line", "job", "claim", "manifest", "request", 0, 1, "workflow", "prompt",
                                       "remote", "local", "descriptor", 1, "b" * 64, "promoted", "image.png")
    writer = j.OfflineJournalWriter(journal, op, characterization=True)
    return roots, op, candidate, writer


def append_all(writer, candidate=None, files=(), save="saved"):
    outcomes = ("intent", "accepted", "intent", "verified", "intent", "registered", "intent", save)
    reopened = None
    for index, (checkpoint, outcome) in enumerate(zip(j.CHECKPOINTS, outcomes)):
        reopened = writer.append_for_characterization(j.Observation(checkpoint, outcome,
                           tuple(f for f in files if f.role == "contained") if index == 3 else
                           tuple(f for f in files if f.role == "promoted") if index == 5 else (),
                           (candidate,) if candidate and index == 5 else (),
                           save=j.ProjectSaveObservation("project", "project.json", outcome) if index in (6, 7) else None))
    return reopened


def saved_record(candidate, roots):
    provenance = asdict(candidate)
    provenance.pop("asset_root_key")
    provenance.pop("asset_relative_path")
    provenance.pop("claim_id")
    return {"path": str(Path(roots[3].path) / candidate.asset_relative_path), "generation_provenance": provenance,
            "unknown_candidate": "preserved"}


def write_candidates(roots, candidates):
    path = Path(roots[1].path) / "project.json"
    path.write_text(json.dumps({"prompt_lines": [{"id": "line", "generated_candidates": candidates}], "unknown": {"keep": 7}}))


def test_normal_reopen_all_checkpoints_are_inspect_only(rig):
    roots, op, candidate, writer = rig
    reopened = append_all(writer, candidate)
    assert reopened == j.reopen_journal(roots[0], "operation.json")
    assert reopened.operation == op
    assert reopened.revision == 8
    assert [o.checkpoint for o in reopened.observations] == list(j.CHECKPOINTS)
    assert reopened.authenticity == "unverified" and reopened.trust == "inspect_only"
    assert not reopened.execution_available
    with pytest.raises(ValueError, match="journal_complete"):
        writer.append_for_characterization(j.Observation("save_observed", "saved"))
    with pytest.raises(ValueError, match="execution_unavailable"):
        j.OfflineJournalWriter(roots[0], op)


@pytest.mark.parametrize("boundary,revision", [("before_replace", 1), ("after_replace_before_ack", 2)])
def test_interruption_old_or_new_complete_revision_no_retry(rig, boundary, revision):
    roots, _, _, writer = rig
    writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    def fault(point):
        if point == boundary:
            raise RuntimeError("simulated crash")
    writer.fault = fault
    with pytest.raises(RuntimeError):
        writer.append_for_characterization(j.Observation("submission_observed", "unknown"))
    reopened = j.reopen_journal(roots[0], "operation.json")
    assert reopened.revision == revision
    assert reopened.trust == "inspect_only"
    with pytest.raises(ValueError, match="writer_uncertain"):
        writer.append_for_characterization(j.Observation("submission_observed", "accepted"))
    if boundary == "before_replace":
        assert list(Path(roots[0].path).glob("*.tmp"))


def test_durability_order_and_no_overwrite(rig):
    roots, op, _, writer = rig
    events = []
    actual_fsync, actual_replace = os.fsync, os.replace
    def fsync(fd):
        events.append("fsync")
        actual_fsync(fd)
    def replace_file(source, destination):
        events.append("replace")
        actual_replace(source, destination)
    writer.fault = events.append
    with patch.object(j.os, "fsync", fsync), patch.object(j.os, "replace", replace_file):
        writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    assert events == ["fsync", "before_replace", "replace", "after_replace_before_ack"]
    before = (Path(roots[0].path) / "operation.json").read_bytes()
    stale = j.OfflineJournalWriter(roots[0], op, characterization=True)
    with pytest.raises(ValueError, match="conflicting_revision"):
        stale.append_for_characterization(j.Observation("submission_intent", "intent"))
    assert (Path(roots[0].path) / "operation.json").read_bytes() == before


def test_exclusive_writer_collision_retains_other_lock(rig):
    roots, _, _, writer = rig
    lock = Path(roots[0].path) / "operation.lock"
    lock.write_bytes(b"other writer")
    with pytest.raises(FileExistsError):
        writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    assert lock.read_bytes() == b"other writer"
    assert not (Path(roots[0].path) / "operation.json").exists()


def test_missing_revision_and_conflicting_changed_file(rig):
    roots, _, _, writer = rig
    with pytest.raises(FileNotFoundError):
        j.reopen_journal(roots[0], "operation.json")
    writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    path = Path(roots[0].path) / "operation.json"
    clone = path.with_suffix(".new")
    clone.write_bytes(path.read_bytes())
    os.replace(clone, path)
    with pytest.raises(ValueError, match="conflicting_revision"):
        writer.append_for_characterization(j.Observation("submission_observed", "accepted"))


@pytest.mark.parametrize("mutation,code", [
    (lambda v: v.update(version=2), "unknown_version"),
    (lambda v: v.update(version=True), "unknown_version"),
    (lambda v: v.update(extra="credential"), "invalid_schema"),
    (lambda v: v["revisions"][0].update(revision=2), "conflicting_revision"),
    (lambda v: v["revisions"][0].update(previous_digest="f" * 64), "conflicting_revision"),
    (lambda v: v["revisions"][0].update(digest="f" * 64), "digest_mismatch"),
    (lambda v: v["operation"].update(project_relative_path="../other.json"), "unsafe_relative_path"),
    (lambda v: v.update(root_identity=[0, 0]), "root_identity_changed"),
    (lambda v: v.update(root_path="C:/forged"), "root_identity_changed"),
    (lambda v: v["operation"].update(operation_id="forged"), "operation_identity_mismatch"),
])
def test_untrusted_strict_reopen(rig, mutation, code):
    roots, _, _, writer = rig
    writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    path = Path(roots[0].path) / "operation.json"
    value = json.loads(path.read_bytes())
    mutation(value)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match=code):
        j.reopen_journal(roots[0], "operation.json")


@pytest.mark.parametrize("data,code", [(b'{"schema":1,"schema":2}', "duplicate_key"),
                                      (b"{broken", "invalid_json"),
                                      (b"x" * (j.MAX_BYTES + 1), "oversize")], ids=["duplicate", "corrupt", "oversize"])
def test_bad_json_never_advances(rig, data, code):
    roots, _, _, _ = rig
    (Path(roots[0].path) / "operation.json").write_bytes(data)
    with pytest.raises(ValueError, match=code):
        j.reopen_journal(roots[0], "operation.json")
    inventory = j.inspect_inventory(roots[0])
    assert not inventory.journals and inventory.errors[0][1] == code


def test_order_types_and_no_live_payload(rig):
    _, _, candidate, writer = rig
    for obs in (j.Observation("save_intent", "intent"),
                j.Observation("submission_intent", "accepted"),
                j.Observation("submission_intent", "intent", files=({},)),
                j.Observation("submission_intent", "intent", candidates=(replace(candidate, job_id="other"),))):
        with pytest.raises(ValueError):
            writer.append_for_characterization(obs)
    assert set(j.OperationObservation.__dataclass_fields__) == {"operation_id", "job_id", "manifest_identity",
            "source_sha256", "project_root_key", "project_root_path", "project_root_identity", "project_relative_path", "project_file_identity",
            "process_identity", "session_identity", "claim_id", "review_sha256", "requests"}


def test_intent_without_observed_result_does_not_imply_no_send(rig):
    roots, _, _, writer = rig
    writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    journal = j.inspect_inventory(roots[0]).journals[0]
    assert journal.observations[-1].checkpoint == "submission_intent"
    assert journal.trust == "inspect_only" and not journal.execution_available
    assert j.reconcile_selected_project(journal, roots[1], "project.json").state == "uncertain"


def test_contained_promoted_missing_tampered_and_orphan_inventory(rig):
    roots, _, _, writer = rig
    observations = []
    for root, name in ((roots[2], "contained.png"), (roots[3], "promoted.png"),
                       (roots[3], "missing.png"), (roots[3], "tampered.png")):
        path = Path(root.path) / name
        data = image_bytes()
        path.write_bytes(data)
        observations.append(j.FileObservation(root.key, root.path, root.identity, name, j._file_identity(path.stat()),
                            hashlib.sha256(data).hexdigest(), len(data), root.key, "PNG", 4, 3,
                            "request", "descriptor", 1, "verified"))
    append_all(writer, files=tuple(observations))
    (Path(roots[3].path) / "missing.png").unlink()
    (Path(roots[3].path) / "tampered.png").write_bytes(b"different bytes!!")
    (Path(roots[3].path) / "orphan.png").write_bytes(b"unowned")
    before = {str(p): p.read_bytes() for root in roots for p in Path(root.path).iterdir() if p.is_file()}
    inventory = j.inspect_inventory(roots[0], roots[2:])
    assert [f[2] for f in inventory.files] == ["exact", "exact", "missing", "tampered"]
    assert inventory.orphans == (("promoted", "orphan.png", "unverified"),)
    assert before == {str(p): p.read_bytes() for root in roots for p in Path(root.path).iterdir() if p.is_file()}
    assert all(not x.execution_available for x in inventory.journals)


def test_changed_root_symlink_traversal_and_budget(rig, tmp_path):
    roots, _, _, writer = rig
    writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    with pytest.raises(ValueError, match="unsafe_relative_path"):
        j.reopen_journal(roots[0], "../project/project.json")
    forged = replace(roots[0], identity=(0, 0))
    with pytest.raises(ValueError, match="root_identity_changed"):
        j.reopen_journal(forged, "operation.json")
    (Path(roots[0].path) / "unknown.tmp").write_bytes(b"retain")
    assert j.inspect_inventory(roots[0], max_entries=1).truncated
    link = Path(roots[0].path) / "linked.json"
    try:
        link.symlink_to(Path(roots[0].path) / "operation.json")
    except OSError:
        # Windows may require Developer Mode; reparse refusal remains tested below.
        pass
    else:
        with pytest.raises(ValueError, match="unsafe_storage|unsafe_path"):
            j.reopen_journal(roots[0], "linked.json")
    original = j._storage_ordinary
    from core.comfy_output_containment import _ContainmentFailure
    def reparse(path, *, directory):
        if not directory:
            raise _ContainmentFailure("unsafe_storage")
        return original(path, directory=directory)
    with patch.object(j, "_storage_ordinary", reparse):
        with pytest.raises(ValueError, match="unsafe_storage"):
            j.reopen_journal(roots[0], "operation.json")


@pytest.mark.parametrize("save", ["saved", "failed", "uncertain"])
def test_selected_saved_exact_absent_partial_conflicting_is_read_only(rig, save):
    roots, _, candidate, writer = rig
    second = replace(candidate, output_index=2, descriptor_identity="second", asset_relative_path="second.png")
    for i, (checkpoint, outcome) in enumerate(zip(j.CHECKPOINTS,
            ("intent", "accepted", "intent", "verified", "intent", "registered", "intent", save))):
        journal = writer.append_for_characterization(j.Observation(checkpoint, outcome,
                   candidates=(candidate, second) if i == 5 else (),
                   save=j.ProjectSaveObservation("project", "project.json", outcome) if i in (6, 7) else None))
    records = [saved_record(candidate, roots), saved_record(second, roots)]
    for state, actual in (("exact", records), ("absent", []), ("partial", records[:1]),
                          ("conflicting", [records[0], records[0]])):
        write_candidates(roots, actual)
        path = Path(roots[1].path) / "project.json"
        before = path.read_bytes()
        result = j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:])
        assert result.state == state and result.save_observation == save
        assert result.trust == "inspect_only" and not result.attachment_allowed and not result.execution_available
        assert path.read_bytes() == before
    assert j.reconcile_selected_project(journal, roots[1], "other.json", roots[2:]).state == "conflicting"


@pytest.mark.parametrize("candidate_count", [1, 2])
@pytest.mark.parametrize("duplicate_record", ["absent", "conflicting"])
def test_duplicate_source_illustration_is_conflicting(rig, candidate_count, duplicate_record):
    roots, _, candidate, writer = rig
    second = replace(candidate, output_index=2, descriptor_identity="second", asset_relative_path="second.png")
    for i, (checkpoint, outcome) in enumerate(zip(j.CHECKPOINTS,
            ("intent", "accepted", "intent", "verified", "intent", "registered", "intent", "saved"))):
        journal = writer.append_for_characterization(j.Observation(checkpoint, outcome,
                   candidates=(candidate, second)[:candidate_count] if i == 5 else (),
                   save=j.ProjectSaveObservation("project", "project.json", outcome) if i in (6, 7) else None))
    record = saved_record(candidate, roots)
    other = saved_record(candidate, roots)
    other["generation_provenance"]["content_sha256"] = "f" * 64
    path = Path(roots[1].path) / "project.json"
    path.write_text(json.dumps({"prompt_lines": [
        {"id": candidate.illustration_id, "generated_candidates": [record]},
        {"id": candidate.illustration_id, "generated_candidates": [other] if duplicate_record == "conflicting" else []},
    ], "unknown": {"keep": 7}}))
    before = {str(p): p.read_bytes() for root in roots for p in Path(root.path).iterdir() if p.is_file()}
    result = j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:])
    assert result.state == "conflicting" and result.matched == 0 and result.expected == candidate_count
    assert result.trust == "inspect_only" and not result.attachment_allowed and not result.execution_available
    assert before == {str(p): p.read_bytes() for root in roots for p in Path(root.path).iterdir() if p.is_file()}


@pytest.mark.parametrize("source_fields", [{}, {"id": None}, {"id": False}, {"id": 17},
                                          {"id": ""}, {"id": []}, {"id": {}}, {"id": "../line"}])
def test_malformed_saved_source_identity_is_uncertain(rig, source_fields):
    roots, op, candidate, _ = rig
    # A numeric/bool ID must not become an exact match through string coercion.
    source_id = source_fields.get("id")
    illustration_id = str(source_id) if type(source_id) in (bool, int) else candidate.illustration_id
    op = replace(op, requests=(replace(op.requests[0], illustration_id=illustration_id),))
    candidate = replace(candidate, illustration_id=illustration_id)
    writer = j.OfflineJournalWriter(roots[0], op, characterization=True)
    journal = append_all(writer, candidate)
    path = Path(roots[1].path) / "project.json"
    path.write_text(json.dumps({"prompt_lines": [
        {**source_fields, "generated_candidates": [saved_record(candidate, roots)]},
    ]}))
    before = path.read_bytes()
    result = j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:])
    assert result.state == "uncertain" and result.matched == 0
    assert result.trust == "inspect_only" and not result.attachment_allowed and not result.execution_available
    assert path.read_bytes() == before


@pytest.mark.parametrize("source", ["unique", "missing", "moved"])
def test_unique_or_missing_original_illustration_keeps_saved_association_state(rig, source):
    roots, _, candidate, writer = rig
    journal = append_all(writer, candidate)
    lines = [{"id": "other", "generated_candidates": []}]
    if source == "unique":
        lines.append({"id": candidate.illustration_id, "generated_candidates": [saved_record(candidate, roots)]})
    elif source == "moved":
        lines[0]["generated_candidates"] = [saved_record(candidate, roots)]
    path = Path(roots[1].path) / "project.json"
    path.write_text(json.dumps({"prompt_lines": lines, "unknown": {"keep": 7}}))
    before = path.read_bytes()
    result = j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:])
    assert result.state == {"unique": "exact", "missing": "absent", "moved": "conflicting"}[source]
    assert result.matched == (1 if source == "unique" else 0) and result.expected == 1
    assert result.trust == "inspect_only" and not result.attachment_allowed and not result.execution_available
    assert path.read_bytes() == before


def test_conflicting_hash_path_missing_unreadable_unknown_fields(rig):
    roots, _, candidate, writer = rig
    journal = append_all(writer, candidate, save="uncertain")
    record = saved_record(candidate, roots)
    for changed in ({**record, "path": "../outside.png"},
                    {**record, "generation_provenance": {**record["generation_provenance"], "content_sha256": "f" * 64}}):
        write_candidates(roots, [changed])
        assert j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:]).state == "conflicting"
    path = Path(roots[1].path) / "project.json"
    path.write_bytes(b"corrupt")
    assert j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:]).state == "uncertain"
    with patch.object(j, "_read", side_effect=PermissionError):
        assert j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:]).state == "unreadable"
    path.unlink()
    assert j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:]).state == "missing"


def test_restart_no_runtime_callbacks_or_filesystem_mutation(rig):
    roots, _, candidate, writer = rig
    append_all(writer, candidate, save="uncertain")
    write_candidates(roots, [saved_record(candidate, roots)])
    del writer
    with patch.object(j.os, "replace", side_effect=AssertionError("save")), \
         patch.object(j.os, "unlink", side_effect=AssertionError("delete")), \
         patch.object(j.os, "open", wraps=os.open) as opens:
        journal = j.inspect_inventory(roots[0], roots[2:]).journals[0]
        result = j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:])
        assert result.state == "exact" and not result.attachment_allowed
        assert all(call.args[1] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT) == 0 for call in opens.call_args_list)
    assert not hasattr(journal, "claim") and not hasattr(journal, "envelope")


def test_offline_checkpoint_order_around_disposable_effects(rig):
    roots, _, candidate, writer = rig
    events = []
    def record(checkpoint, outcome, **kwargs):
        if checkpoint in ("save_intent", "save_observed"):
            kwargs["save"] = j.ProjectSaveObservation("project", "project.json", outcome)
        reopened = writer.append_for_characterization(j.Observation(checkpoint, outcome, **kwargs))
        events.append(checkpoint)
        return reopened
    request = j.RequestObservation("request", 0, "workflow", "intent")
    record("submission_intent", "intent", requests=(request,))
    events.append("fake_submission")
    record("submission_observed", "accepted", requests=(replace(request, outcome="accepted", prompt_id="prompt"),))
    record("download_attempt", "intent")
    data = image_bytes()
    contained = Path(roots[2].path) / "image.png"
    contained.write_bytes(data)
    events.append("fake_download_and_verify")
    image = j.FileObservation(roots[2].key, roots[2].path, roots[2].identity, "image.png",
                             j._file_identity(contained.stat()), hashlib.sha256(data).hexdigest(), len(data), "contained", "PNG", 4, 3,
                             "request", "descriptor", 1, "verified")
    record("images_verified", "verified", files=(image,))
    record("promotion_intent", "intent")
    promoted = Path(roots[3].path) / "image.png"
    promoted.write_bytes(data)
    events.append("disposable_asset_copy")
    candidate = replace(candidate, content_sha256=image.content_sha256)
    live_disposable_candidates = [saved_record(candidate, roots)]
    events.append("disposable_in_memory_append")
    promoted_image = replace(image, root_key=roots[3].key, root_path=roots[3].path,
                             root_identity=roots[3].identity, file_identity=j._file_identity(promoted.stat()), role="promoted")
    record("registration_observed", "registered", candidates=(candidate,), files=(promoted_image,))
    record("save_intent", "intent")
    project_path = Path(roots[1].path) / "project.json"
    temp = project_path.with_suffix(".temp")
    temp.write_text(json.dumps({"prompt_lines": [{"id": "line", "generated_candidates": live_disposable_candidates}]}))
    os.replace(temp, project_path)
    events.append("disposable_json_replace")
    record("save_observed", "saved")
    assert events == ["submission_intent", "fake_submission", "submission_observed", "download_attempt",
                      "fake_download_and_verify", "images_verified", "promotion_intent", "disposable_asset_copy",
                      "disposable_in_memory_append", "registration_observed", "save_intent", "disposable_json_replace", "save_observed"]
    inventory = j.inspect_inventory(roots[0], roots[2:])
    assert [x[2] for x in inventory.files] == ["exact", "exact"]
    result = j.reconcile_selected_project(inventory.journals[0], roots[1], "project.json", roots[2:])
    assert result.state == "exact" and not result.attachment_allowed


def test_recomputed_forgery_and_stale_prefix_remain_untrusted(rig):
    roots, _, _, writer = rig
    first = writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    path = Path(roots[0].path) / "operation.json"
    prefix = path.read_bytes()
    second = writer.append_for_characterization(j.Observation("submission_observed", "unknown"))
    path.write_bytes(prefix)
    # Without independently pinned head, a valid prefix is observational only.
    assert j.reopen_journal(roots[0], "operation.json").uncertainties == ("submission_intent_outcome_unknown", "authenticity_unverified")
    with pytest.raises(ValueError, match="stale_revision"):
        j.reopen_journal(roots[0], "operation.json", expected_revision=second.revision)
    with pytest.raises(ValueError, match="conflicting_revision"):
        j.reopen_journal(roots[0], "operation.json", expected_digest=second.digest)
    value = json.loads(prefix)
    value["operation"]["job_id"] = "forged_job"
    entry = value["revisions"][0]
    entry["digest"] = j._hash({"schema": j.SCHEMA, "version": 1, "operation": value["operation"],
                               **{k: v for k, v in entry.items() if k != "digest"}})
    path.write_text(json.dumps(value))
    forged = j.reopen_journal(roots[0], "operation.json")
    assert forged.operation.job_id == "forged_job"
    assert forged.authenticity == "unverified" and forged.trust == "inspect_only"


def test_missing_middle_revision_and_request_drift(rig):
    roots, _, _, writer = rig
    request = j.RequestObservation("request", 0, "workflow", "intent")
    writer.append_for_characterization(j.Observation("submission_intent", "intent", requests=(request,)))
    with pytest.raises(ValueError, match="request_identity_conflicting"):
        writer.append_for_characterization(j.Observation("submission_observed", "unknown",
                                          requests=(replace(request, request_index=1, outcome="unknown"),)))
    writer.append_for_characterization(j.Observation("submission_observed", "unknown", requests=(replace(request, outcome="unknown"),)))
    writer.append_for_characterization(j.Observation("download_attempt", "intent"))
    path = Path(roots[0].path) / "operation.json"
    value = json.loads(path.read_bytes())
    del value["revisions"][1]
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="conflicting_revision"):
        j.reopen_journal(roots[0], "operation.json")


def test_fsync_failure_and_exclusive_temp_collision_preserve_bytes(rig):
    roots, _, _, writer = rig
    writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    path = Path(roots[0].path) / "operation.json"
    before = path.read_bytes()
    with patch.object(j.os, "fsync", side_effect=OSError("injected fsync")):
        with pytest.raises(OSError):
            writer.append_for_characterization(j.Observation("submission_observed", "unknown"))
    assert path.read_bytes() == before
    assert list(Path(roots[0].path).glob("*.tmp"))


def test_changed_original_project_before_save_intent_is_uncertain(rig):
    roots, _, candidate, writer = rig
    for i, (checkpoint, outcome) in enumerate(zip(j.CHECKPOINTS[:6],
            ("intent", "accepted", "intent", "verified", "intent", "registered"))):
        journal = writer.append_for_characterization(j.Observation(checkpoint, outcome,
                   candidates=(candidate,) if i == 5 else ()))
    project = Path(roots[1].path) / "project.json"
    substitute = project.with_suffix(".new")
    substitute.write_text(json.dumps({"prompt_lines": [{"id": "line", "generated_candidates": [saved_record(candidate, roots)]}]}))
    os.replace(substitute, project)
    assert j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:]).state == "uncertain"


def test_budget_invalid_images_and_changed_asset_root_are_observations(rig):
    roots, _, _, writer = rig
    path = Path(roots[2].path) / "bad.png"
    data = b"not an image"
    path.write_bytes(data)
    image = j.FileObservation(roots[2].key, roots[2].path, roots[2].identity, "bad.png",
                             j._file_identity(path.stat()), hashlib.sha256(data).hexdigest(), len(data), "contained", "PNG", 4, 3,
                             "request", "descriptor", 1, "quarantined")
    append_all(writer, files=(image,))
    assert j.inspect_inventory(roots[0], roots[2:]).files[0][2] == "image_invalid"
    assert j.inspect_inventory(roots[0], roots[2:], max_file_bytes=1).files[0][2] == "budget_exceeded"
    assert j.inspect_inventory(roots[0], ()).files[0][2] == "unapproved_root"
    changed = replace(roots[2], identity=(0, 0))
    assert j.inspect_inventory(roots[0], (changed, roots[3])).files[0][2] == "root_identity_changed"


def test_exclusive_temporary_file_never_overwrites(rig):
    roots, _, _, writer = rig
    existing = Path(roots[0].path) / "operation.fixed.tmp"
    existing.write_bytes(b"retain original temporary evidence")
    from types import SimpleNamespace
    with patch.object(j.uuid, "uuid4", return_value=SimpleNamespace(hex="fixed")):
        with pytest.raises(FileExistsError):
            writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    assert existing.read_bytes() == b"retain original temporary evidence"
    assert not (Path(roots[0].path) / "operation.json").exists()


def test_untrusted_absolute_names_are_not_probed(rig):
    roots, _, candidate, writer = rig
    journal = append_all(writer, candidate)
    record = saved_record(candidate, roots)
    record["path"] = str(Path(roots[1].path).parent / "unapproved" / "image.png")
    write_candidates(roots, [record])
    original_resolve = Path.resolve
    def resolve(path, *args, **kwargs):
        assert "unapproved" not in str(path)
        return original_resolve(path, *args, **kwargs)
    with patch.object(Path, "resolve", resolve):
        assert j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:]).state == "conflicting"


def test_remote_containment_promotion_and_unresolved_records_reopen(rig):
    roots, op, candidate, writer = rig
    request = j.RequestObservation("request", 0, "workflow", "intent")
    writer.append_for_characterization(j.Observation("submission_intent", "intent", requests=(request,)))
    writer.append_for_characterization(j.Observation("submission_observed", "accepted",
            requests=(replace(request, outcome="accepted", prompt_id="prompt"),)))
    remote = j.RemoteResultObservation("request", "prompt", "remote", "d" * 64, "validated_success", "ready")
    writer.append_for_characterization(j.Observation("download_attempt", "intent", remote_results=(remote,)))
    containment = j.ContainmentObservation("request", "remote", "local", "quarantined", 2, 1)
    unresolved = j.UnresolvedObservation("request", "quarantined", "partial_operation")
    writer.append_for_characterization(j.Observation("images_verified", "partial", containment=(containment,), unresolved=(unresolved,)))
    promotion = j.PromotionObservation("request", "local", "promoted", ("image.png",), "intent")
    writer.append_for_characterization(j.Observation("promotion_intent", "intent", promotions=(promotion,)))
    writer.append_for_characterization(j.Observation("registration_observed", "uncertain",
            promotions=(replace(promotion, state="partial"),), candidates=(candidate,),
            unresolved=(j.UnresolvedObservation("request", "stale", "host_lost"),)))
    writer.append_for_characterization(j.Observation("save_intent", "intent",
            save=j.ProjectSaveObservation("project", "project.json", "intent")))
    reopened = writer.append_for_characterization(j.Observation("save_observed", "uncertain",
            save=j.ProjectSaveObservation("project", "project.json", "uncertain"),
            unresolved=(j.UnresolvedObservation(None, "unresolved", "crash_interrupted"),)))
    assert reopened.operation.process_identity == "process" and reopened.operation.session_identity == "session"
    assert reopened.operation.claim_id == "claim" and reopened.operation.review_sha256 == "c" * 64
    assert reopened.observations[2].remote_results == (remote,)
    assert reopened.observations[3].containment == (containment,)
    assert reopened.checkpoint_coverage == "complete" and reopened.unresolved_next_stage == "none_recorded"
    assert "quarantined_partial_operation" in reopened.uncertainties
    assert "stale_host_lost" in reopened.uncertainties and "unresolved_crash_interrupted" in reopened.uncertainties
    assert reopened.trust == "inspect_only" and not reopened.execution_available


@pytest.mark.parametrize("kind", ["candidate", "remote", "containment", "promotion", "save"])
def test_stage_misplacement_is_refused_before_writing(rig, kind):
    roots, _, candidate, writer = rig
    kwargs = {
        "candidate": dict(candidates=(candidate,)),
        "remote": dict(remote_results=(j.RemoteResultObservation("request", "prompt", "remote", "d" * 64, "validated_success", "ready"),)),
        "containment": dict(containment=(j.ContainmentObservation("request", "remote", "local", "verified", 1, 1),)),
        "promotion": dict(promotions=(j.PromotionObservation("request", "local", "promoted", ("image.png",), "complete"),)),
        "save": dict(save=j.ProjectSaveObservation("project", "project.json", "saved")),
    }[kind]
    with pytest.raises(ValueError):
        writer.append_for_characterization(j.Observation("submission_intent", "intent", **kwargs))
    assert not (Path(roots[0].path) / "operation.json").exists()


@pytest.mark.parametrize("field,value", [("claim_id", "different"), ("job_id", "different"),
                                         ("manifest_identity", "different"), ("run_index", 2),
                                         ("workflow_identity", "different"), ("illustration_id", "different")])
def test_candidate_correlation_is_bound_to_immutable_operation(rig, field, value):
    roots, _, candidate, writer = rig
    for checkpoint, outcome in zip(j.CHECKPOINTS[:5], ("intent", "accepted", "intent", "verified", "intent")):
        writer.append_for_characterization(j.Observation(checkpoint, outcome))
    before = (Path(roots[0].path) / "operation.json").read_bytes()
    with pytest.raises(ValueError, match="identity.*conflicting|operation_identity_mismatch"):
        writer.append_for_characterization(j.Observation("registration_observed", "registered", candidates=(replace(candidate, **{field: value}),)))
    assert (Path(roots[0].path) / "operation.json").read_bytes() == before


def test_operation_wide_reference_and_byte_budgets_reject_before_write(rig):
    roots, _, _, writer = rig
    writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    writer.append_for_characterization(j.Observation("submission_observed", "unknown"))
    writer.append_for_characterization(j.Observation("download_attempt", "intent"))
    image = j.FileObservation("contained", roots[2].path, roots[2].identity, "a.png", (1, 1), "a" * 64,
                             32 * 1024 * 1024, "contained", "PNG", 4, 3, "request", "descriptor", 1, "verified")
    before = (Path(roots[0].path) / "operation.json").read_bytes()
    with pytest.raises(ValueError, match="operation_budget_exceeded"):
        writer.append_for_characterization(j.Observation("images_verified", "verified",
                    files=tuple(replace(image, relative_path=f"{i}.png") for i in range(9))))
    assert (Path(roots[0].path) / "operation.json").read_bytes() == before
    # A low injected bound exercises the operation-wide union across stages,
    # including repeated paths and Candidate references without huge fixtures.
    with patch.object(j, "MAX_OPERATION_FILES", 2):
        writer.append_for_characterization(j.Observation("images_verified", "verified", files=(replace(image, byte_count=1),)))
        writer.append_for_characterization(j.Observation("promotion_intent", "intent",
                promotions=(j.PromotionObservation("request", "local", "promoted", ("a.png",), "intent"),)))
        before = (Path(roots[0].path) / "operation.json").read_bytes()
        promoted = replace(image, role="promoted", root_key="promoted", root_path=roots[3].path,
                           root_identity=roots[3].identity, byte_count=1)
        with pytest.raises(ValueError, match="operation_budget_exceeded"):
            writer.append_for_characterization(j.Observation("registration_observed", "registered",
                    files=(promoted, replace(promoted, relative_path="extra.png"))))
        assert (Path(roots[0].path) / "operation.json").read_bytes() == before


def test_incomplete_checkpoint_inventory_preserves_unresolved_stage(rig):
    roots, _, _, writer = rig
    writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    reopened = j.inspect_inventory(roots[0]).journals[0]
    assert reopened.checkpoint_coverage == "incomplete"
    assert reopened.unresolved_next_stage == "submission_observed"
    assert "submission_intent_outcome_unknown" in reopened.uncertainties


def test_existing_gallery_request_id_format_is_preserved(rig):
    roots, op, candidate, _ = rig
    request_id = "gallery_generation:line:1"
    op = replace(op, requests=(replace(op.requests[0], request_id=request_id),))
    writer = j.OfflineJournalWriter(roots[0], op, characterization=True)
    candidate = replace(candidate, request_id=request_id)
    journal = append_all(writer, candidate)
    assert journal.operation.requests[0].request_id == request_id
    assert journal.observations[5].candidates[0].request_id == request_id
    with pytest.raises(ValueError, match="invalid_operation_identifier"):
        j.OfflineJournalWriter(roots[0], replace(op, operation_id="../escape"), characterization=True)


def test_substituted_root_refuses_replace_and_lock_cleanup(rig):
    roots, _, _, writer = rig
    writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    root = Path(roots[0].path)
    original = root.with_name("original-journal-root")
    before = (root / "operation.json").read_bytes()
    def substitute(boundary):
        if boundary == "before_replace":
            root.rename(original)
            root.mkdir()
    writer.fault = substitute
    with pytest.raises(ValueError, match="root_identity_changed"):
        writer.append_for_characterization(j.Observation("submission_observed", "unknown"))
    assert (original / "operation.json").read_bytes() == before
    assert (original / "operation.lock").exists()
    assert not list(root.iterdir())


@pytest.mark.parametrize("field,value", [("request_id", "different-request"),
                                         ("job_id", "different-job"), ("output_index", 2)])
def test_exact_asset_illustration_with_different_provenance_is_conflicting(rig, field, value):
    roots, _, candidate, writer = rig
    journal = append_all(writer, candidate)
    record = saved_record(candidate, roots)
    record["generation_provenance"][field] = value
    write_candidates(roots, [record])
    result = j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:])
    assert result.state == "conflicting" and result.matched == 0 and result.expected == 1
    assert not result.attachment_allowed and result.trust == "inspect_only"
    # A hash match at another path is genuinely absent for this expected pair.
    record["path"] = str(Path(roots[3].path) / "different.png")
    write_candidates(roots, [record])
    absent = j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:])
    assert absent.state == "absent" and not absent.attachment_allowed


def test_candidate_reference_without_file_evidence_is_missing_or_unverified(rig):
    roots, _, candidate, writer = rig
    journal = append_all(writer, candidate)
    inventory = j.inspect_inventory(roots[0], roots[2:])
    assert inventory.files == (("promoted", "image.png", "missing"),)
    asset = Path(roots[3].path) / "image.png"
    asset.write_bytes(b"unverified bytes")
    # Without size/identity evidence, Candidate hash is never used to verify it.
    with patch.object(j, "_read", wraps=j._read) as reads:
        inventory = j.inspect_inventory(roots[0], roots[2:])
        assert inventory.files == (("promoted", "image.png", "unverified"),)
        assert all(call.args[0] is roots[0] for call in reads.call_args_list)
    assert not inventory.orphans
    write_candidates(roots, [saved_record(candidate, roots)])
    result = j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:])
    assert result.state == "exact" and not result.attachment_allowed


@pytest.mark.parametrize("state", ["missing", "tampered", "conflicting"])
def test_candidate_asset_with_promoted_evidence_is_checked(rig, state):
    roots, _, candidate, writer = rig
    asset = Path(roots[3].path) / "image.png"
    data = image_bytes()
    asset.write_bytes(data)
    image = j.FileObservation("promoted", roots[3].path, roots[3].identity, "image.png",
            j._file_identity(asset.stat()), hashlib.sha256(data).hexdigest(), len(data), "promoted", "PNG", 4, 3,
            "request", "descriptor", 1, "verified")
    candidate = replace(candidate, content_sha256=image.content_sha256)
    if state == "conflicting":
        candidate = replace(candidate, content_sha256="f" * 64)
    journal = append_all(writer, candidate, files=(image,))
    if state == "missing":
        asset.unlink()
    elif state == "tampered":
        asset.write_bytes(b"changed image bytes")
    inventory = j.inspect_inventory(roots[0], roots[2:])
    assert inventory.files == (("promoted", "image.png", state),)
    write_candidates(roots, [saved_record(candidate, roots)])
    result = j.reconcile_selected_project(journal, roots[1], "project.json", roots[2:])
    assert result.state == "exact" and not result.attachment_allowed
