"""Disposable journal/Project evidence; all review decisions stay inspect-only."""
from dataclasses import FrozenInstanceError, asdict, replace
import ast
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pytest

from core import generation_ownership_journal as j
from ui.agent_generation_human_recovery import HumanRecoveryReviewOwner, RecoveryContext, recovery_projection


@pytest.fixture
def rig(tmp_path):
    roots = []
    for key in ("journal", "project", "contained", "promoted"):
        path = tmp_path / key
        path.mkdir()
        roots.append(j.ApprovedRoot.capture_for_characterization(key, str(path), characterization=True))
    project = Path(roots[1].path) / "project.json"
    project.write_text(json.dumps({"prompt_lines": [{"id": "line", "generated_candidates": []}], "unknown": {"keep": 7}}))
    operation = j.OperationObservation("operation", "job", "manifest", hashlib.sha256(project.read_bytes()).hexdigest(),
        "project", roots[1].path, roots[1].identity, "project.json", j._file_identity(project.stat()),
        "process-secret", "session-secret", "claim-secret", "c" * 64,
        (j.FrozenRequestCorrelation("request-secret", 0, "line", 1, "workflow"),))
    return roots, operation


def build(rig, *, candidates=1, saved_candidates=None, save="saved", checkpoint=8,
          role="promoted", verification="verified", remote="validated_success", saved_digest=True):
    roots, op = rig
    data = io.BytesIO()
    Image.new("RGB", (4, 3)).save(data, format="PNG")
    encoded = data.getvalue()
    root = roots[3] if role == "promoted" else roots[2]
    file = Path(root.path) / "image.png"
    file.write_bytes(encoded)
    image = j.FileObservation(root.key, root.path, root.identity, "image.png", j._file_identity(file.stat()),
        hashlib.sha256(encoded).hexdigest(), len(encoded), role, "PNG", 4, 3, "request-secret", "descriptor", 1, verification)
    candidate = j.CandidateObservation("line", "job", "claim-secret", "manifest", "request-secret", 0, 1, "workflow",
        "prompt", "remote", "local", "descriptor", 1, image.content_sha256, root.key, "image.png")
    all_candidates = [candidate]
    if candidates == 2:
        other_path = Path(root.path) / "second.png"
        other_path.write_bytes(encoded)
        all_candidates.append(replace(candidate, output_index=2, descriptor_identity="second", asset_relative_path="second.png"))
    actual = candidates if saved_candidates is None else saved_candidates
    records = []
    for item in all_candidates[:actual]:
        provenance = asdict(item)
        for key in ("claim_id", "asset_root_key", "asset_relative_path"):
            provenance.pop(key)
        provenance["prompts"] = [{"text": "FULL PROMPT SECRET", "endpoint": "https://secret/?api_key=SECRET"}]
        records.append({"path": str(Path(root.path) / item.asset_relative_path), "generation_provenance": provenance,
                        "unknown_candidate": {"keep": 17}})
    project = Path(roots[1].path) / "project.json"
    # Preserve original bytes when testing genuinely unpublished contained output.
    if actual:
        project.write_text(json.dumps({"prompt_lines": [{"id": "line", "generated_candidates": records}], "unknown": {"keep": 7}}))
    writer = j.OfflineJournalWriter(roots[0], op, characterization=True)
    files = [image]
    if candidates == 2:
        files.append(replace(image, relative_path="second.png", file_identity=j._file_identity(other_path.stat()),
                             output_index=2, descriptor_identity="second"))
    outcomes = ("intent", "accepted", "intent", "verified", "intent", "registered", "intent", save)
    reopened = None
    for index in range(checkpoint):
        reopened = writer.append_for_characterization(j.Observation(j.CHECKPOINTS[index], outcomes[index],
            files=tuple(files) if index == (5 if role == "promoted" else 3) else (),
            candidates=tuple(all_candidates[:candidates]) if index == 5 else (),
            requests=(j.RequestObservation("request-secret", 0, "workflow", "accepted", "prompt"),) if index == 1 else (),
            remote_results=(j.RemoteResultObservation("request-secret", "prompt", "remote", "d" * 64, remote,
                            "ready" if remote != "unproven" else "unknown"),) if index == 2 else (),
            save=j.ProjectSaveObservation("project", "project.json", outcomes[index],
                observed_json_sha256=hashlib.sha256(project.read_bytes()).hexdigest() if index == 7 and saved_digest else None)
                if index in (6, 7) else None))
    return reopened, image, candidate


def owner(rig, **kwargs):
    roots, operation = rig
    kwargs.setdefault("original_project_sha256", operation.source_sha256)
    return HumanRecoveryReviewOwner(roots[0], "operation.json", roots[1], "project.json", roots[2:],
        characterization=True, context=RecoveryContext("observed", "original_observed", "recorded", "recorded"), **kwargs)


def disk_bytes(roots):
    return {str(p): p.read_bytes() for root in roots for p in Path(root.path).rglob("*") if p.is_file()}


def category(view, name):
    return next(v for v in view["retention"]["assets"] if v["classification"] == name)


def test_complete_candidate_and_image_is_inspection_not_authority(rig):
    journal, image, _ = build(rig)
    review = owner(rig)
    case = review.case_for_characterization()
    assert case.journal.operation == journal.operation and case.journal.digest == journal.digest
    with pytest.raises(FrozenInstanceError):
        case.revision = 7
    view = review.projection_for_characterization()
    assert view["candidate_association"] == "exact" and view["matched_candidates"] == 1
    assert view["images"][0]["available_for_inspection"]
    assert view["requests"] == [{"request": 1, "illustration": 1, "run": 1, "external_execution": "observed_result"}]
    assert view["save_outcome"] == "saved" and not view["save_uncertain"]
    assert category(view, "published_saved_candidate_assets")["observed_bytes"] == image.byte_count
    assert view["retention"]["capacity"] == "incomplete_or_unknown"
    assert not view["retention"]["external_count_complete"]
    assert "journal_authenticity_unverified" in view["blockers"]
    assert view["classifications"]["candidate_already_associated"]
    assert view["classifications"]["evidence_currently_unsafe_to_associate"]
    assert not any(view[k] for k in ("execution_available", "attachment_allowed", "publication_allowed", "cleanup_allowed"))


def test_verified_unpublished_image_and_no_recorded_candidate(rig):
    build(rig, candidates=0, checkpoint=4, role="contained")
    view = owner(rig).projection_for_characterization()
    assert category(view, "verified_unpublished")["observed_count"] == 1
    assert view["images"][0]["candidate_association"] == "no_recorded_candidate"
    assert view["journal"]["checkpoint"] == "images_verified"
    assert "checkpoint_coverage_incomplete" in view["blockers"]


def test_grouping_preserves_request_illustration_runs_with_private_ids(rig):
    roots, operation = rig
    operation = replace(operation, requests=operation.requests + (
        j.FrozenRequestCorrelation("second-secret", 1, "line", 2, "workflow"),
        j.FrozenRequestCorrelation("third-secret", 2, "other-line", 1, "workflow")))
    rig = roots, operation
    build(rig, candidates=0, checkpoint=4, role="contained")
    view = owner(rig).projection_for_characterization()
    assert [(r["request"], r["illustration"], r["run"]) for r in view["requests"]] == [(1, 1, 1), (2, 1, 2), (3, 2, 1)]
    assert view["retention"]["unknown_external_submissions"] == 2
    assert not view["retention"]["external_count_complete"]


def test_saved_unrecorded_reference_is_not_verified_unpublished(rig):
    build(rig, candidates=0, checkpoint=4, role="contained")
    roots, _ = rig
    project = Path(roots[1].path) / "project.json"
    value = json.loads(project.read_bytes())
    value["prompt_lines"][0]["generated_candidates"] = [{"path": str(Path(roots[2].path) / "image.png")}]
    project.write_text(json.dumps(value))
    current_digest = hashlib.sha256(project.read_bytes()).hexdigest()
    view = owner(rig, original_project_sha256=current_digest).projection_for_characterization()
    assert category(view, "verified_unpublished")["observed_count"] == 0
    assert "unrecorded_candidate_association" in view["blockers"]
    assert view["images"][0]["candidate_association"] == "saved_reference_needs_reconciliation"


def test_contained_copy_of_published_output_is_not_unpublished(rig):
    _, image, _ = build(rig)
    roots, _ = rig
    contained_path = Path(roots[2].path) / "contained.png"
    contained_path.write_bytes((Path(roots[3].path) / "image.png").read_bytes())
    contained = replace(image, root_key="contained", root_path=roots[2].path, root_identity=roots[2].identity,
                        relative_path="contained.png", file_identity=j._file_identity(contained_path.stat()), role="contained")
    path = Path(roots[0].path) / "operation.json"
    value = json.loads(path.read_bytes())
    value["revisions"][3]["observation"]["files"] = [asdict(contained)]
    rehash(value)
    path.write_text(json.dumps(value))
    view = owner(rig).projection_for_characterization()
    assert category(view, "verified_unpublished")["observed_count"] == 0
    assert view["images"][0]["candidate_association"] == "related_recorded_candidate"


def test_partial_candidate_insert_separate_from_save(rig):
    build(rig, candidates=2, saved_candidates=1, save="failed")
    view = owner(rig).projection_for_characterization()
    assert view["candidate_association"] == "partial" and view["matched_candidates"] == 1
    assert "candidate_association_partial" in view["blockers"]
    assert category(view, "promoted_after_failed_or_uncertain_save")["observed_count"] == 2


@pytest.mark.parametrize("change,reason", [("different", "project_different_selected_project"),
    ("missing", "project_missing"), ("content", "project_changed_original_project"),
    ("duplicate", "duplicate_illustration_id"), ("missing_line", "original_illustration_missing")])
def test_changed_missing_or_duplicate_original_project(rig, tmp_path, change, reason):
    build(rig)
    roots, _ = rig
    project = Path(roots[1].path) / "project.json"
    if change == "missing":
        project.unlink()
    elif change in ("content", "duplicate", "missing_line"):
        value = json.loads(project.read_bytes())
        if change == "content":
            value["prompt_lines"][0]["prompt"] = "CHANGED SECRET"
        elif change == "duplicate":
            value["prompt_lines"].append({"id": "line", "generated_candidates": []})
        else:
            value["prompt_lines"][0]["id"] = "changed-line"
        project.write_text(json.dumps(value))
    if change == "different":
        path = tmp_path / "other"
        path.mkdir()
        root = j.ApprovedRoot.capture_for_characterization("other", str(path), characterization=True)
        review = HumanRecoveryReviewOwner(roots[0], "operation.json", root, "project.json", roots[2:], characterization=True)
    else:
        review = owner(rig)
    assert reason in review.projection_for_characterization()["blockers"]


@pytest.mark.parametrize("change", ["missing", "tampered", "unverified", "incomplete", "quarantined", "stale"])
def test_unavailable_unsafe_asset_metadata_withheld(rig, change):
    build(rig, verification=change if change in ("incomplete", "quarantined", "stale") else "verified")
    roots, _ = rig
    path = Path(roots[3].path) / "image.png"
    if change == "missing":
        path.unlink()
    elif change == "tampered":
        data = bytearray(path.read_bytes())
        data[40] ^= 1
        path.write_bytes(data)
    elif change == "unverified":
        # Supported saved Candidate reference with no original file observation.
        journal_path = Path(roots[0].path) / "operation.json"
        value = json.loads(journal_path.read_bytes())
        value["revisions"][5]["observation"]["files"] = []
        rehash(value)
        journal_path.write_text(json.dumps(value))
    view = owner(rig).projection_for_characterization()
    image = view["images"][0]
    assert not image["available_for_inspection"] and image["format"] is None and image["observed_bytes"] is None
    assert category(view, "quarantined_or_stale" if change in ("quarantined", "stale") else "orphan_or_incomplete")["recorded_or_listed_count"] == 1


@pytest.mark.parametrize("save", ["failed", "uncertain"])
def test_save_uncertainty_does_not_upgrade_from_matching_candidate(rig, save):
    build(rig, save=save)
    review = owner(rig)
    view = review.projection_for_characterization()
    assert view["candidate_association"] == "exact" and view["save_outcome"] == save
    assert view["save_uncertain"] and "project_save_" + save in view["blockers"]
    decision = review.decide_for_characterization(review.case_for_characterization(), "request_recovery_review")
    assert decision.status == "review_intention_recorded" and not decision.permission_granted
    assert review.projection_for_characterization()["journal"]["authenticity"] == "unverified"


def test_uncertain_persistence_missing_saved_fingerprint(rig):
    build(rig, saved_digest=False)
    view = owner(rig).projection_for_characterization()
    assert view["project"] == "content_needs_reconciliation"
    assert category(view, "published_saved_candidate_assets")["observed_count"] == 0


def test_journal_source_digest_does_not_imply_original_json_digest(rig):
    roots, operation = rig
    operation = replace(operation, source_sha256="e" * 64)
    rig = roots, operation
    build(rig, candidates=0, checkpoint=4, role="contained")
    view = owner(rig, original_project_sha256=None).projection_for_characterization()
    assert view["project"] == "original_identity_observed_content_unverified"
    assert category(view, "verified_unpublished")["observed_count"] == 0
    original_digest = hashlib.sha256((Path(roots[1].path) / "project.json").read_bytes()).hexdigest()
    view = owner(rig, original_project_sha256=original_digest).projection_for_characterization()
    assert view["project"] == "original_bytes_observed"
    assert category(view, "verified_unpublished")["observed_count"] == 1


@pytest.mark.parametrize("change", ["content", "identity"])
def test_original_json_changed_before_save_intent(rig, change):
    build(rig, candidates=0, checkpoint=4, role="contained")
    roots, _ = rig
    project = Path(roots[1].path) / "project.json"
    if change == "content":
        value = json.loads(project.read_bytes())
        value["unknown"]["keep"] = 9
        project.write_text(json.dumps(value))
    else:
        replacement = project.with_suffix(".new")
        replacement.write_bytes(project.read_bytes())
        replacement.replace(project)
    view = owner(rig).projection_for_characterization()
    assert view["project"] == "changed_original_project"
    assert category(view, "verified_unpublished")["observed_count"] == 0


def test_project_change_during_reconciliation_marks_snapshot_conflicting(rig):
    build(rig)
    roots, _ = rig
    project = Path(roots[1].path) / "project.json"
    actual = j.reconcile_selected_project
    def reconcile_and_change(*args, **kwargs):
        result = actual(*args, **kwargs)
        value = json.loads(project.read_bytes())
        value["unknown"]["keep"] += 1
        project.write_text(json.dumps(value))
        return result
    with patch.object(j, "reconcile_selected_project", reconcile_and_change):
        review = owner(rig)
        assert review.case_for_characterization().project.state == "snapshot_conflicting"
        assert review.decide_for_characterization(review.case_for_characterization(), "defer").status == "stale_case"


def test_unknown_remote_even_with_image_and_candidate_no_resubmit(rig):
    build(rig, remote="unproven")
    view = owner(rig).projection_for_characterization()
    assert view["external_execution"] == "unknown"
    assert view["retention"]["unknown_external_submissions"] == 1
    assert "external_execution_unknown" in view["blockers"]


def test_intent_only_unknown_is_not_evidence_of_no_submission(rig):
    build(rig, candidates=0, checkpoint=1)
    view = owner(rig).projection_for_characterization()
    assert view["requests"][0]["external_execution"] == "unknown"
    assert view["save_outcome"] == "unknown"


def test_truncated_inventory_and_orphans_have_unknown_capacity(rig):
    build(rig)
    roots, _ = rig
    for index in range(3):
        (Path(roots[3].path) / f"orphan-secret-{index}.png").write_bytes(b"unowned")
    view = owner(rig, max_entries=1).projection_for_characterization()
    assert view["inventory"] == "not fully inspected"
    assert "inventory_not_fully_inspected" in view["blockers"]
    assert view["retention"]["capacity"] == "incomplete_or_unknown"
    assert "no other files" not in json.dumps(view)


def test_byte_budget_and_missing_journal_are_not_fully_inspected(rig):
    build(rig)
    view = owner(rig, max_file_bytes=1).projection_for_characterization()
    assert view["inventory"] == "not fully inspected"
    assert view["images"][0]["inspection"] == "budget_exceeded"
    roots, _ = rig
    (Path(roots[0].path) / "operation.json").unlink()
    view = owner(rig).projection_for_characterization()
    assert "journal_missing" in view["blockers"]
    assert not view["retention"]["external_count_complete"]
    assert view["retention"]["unknown_external_submissions"] is None
    assert view["external_execution"] == "unknown"


def rehash(value):
    previous = "0" * 64
    for entry in value["revisions"]:
        entry["previous_digest"] = previous
        entry["digest"] = j._hash({"schema": j.SCHEMA, "version": 1, "operation": value["operation"],
                                  **{k: v for k, v in entry.items() if k != "digest"}})
        previous = entry["digest"]


def test_conflicting_inventory_two_operations_same_asset(rig):
    build(rig)
    roots, _ = rig
    path = Path(roots[0].path) / "operation.json"
    value = json.loads(path.read_bytes())
    value["operation"]["operation_id"] = "other"
    value["revisions"][5]["observation"]["files"][0]["content_sha256"] = "f" * 64
    value["revisions"][5]["observation"]["candidates"][0]["content_sha256"] = "f" * 64
    rehash(value)
    (Path(roots[0].path) / "other.json").write_text(json.dumps(value))
    view = owner(rig).projection_for_characterization()
    assert view["images"][0]["inspection"] == "conflicting"
    assert not view["images"][0]["available_for_inspection"]


def test_rollback_expected_revision_and_digest_fail_closed(rig):
    reopened, _, _ = build(rig)
    roots, _ = rig
    path = Path(roots[0].path) / "operation.json"
    value = json.loads(path.read_bytes())
    value["revisions"] = value["revisions"][:4]
    path.write_text(json.dumps(value))
    view = owner(rig, expected_revision=reopened.revision, expected_digest=reopened.digest).projection_for_characterization()
    assert view["journal"]["checkpoint"] == "unavailable"
    assert "journal_unreadable_stale_or_conflicting" in view["blockers"]
    # Without a host retained tip, an internally valid prefix is still unverified.
    assert owner(rig).projection_for_characterization()["journal"]["authenticity"] == "unverified"


def test_recomputed_matching_journal_cannot_authenticate_or_grant_permission(rig):
    build(rig)
    roots, _ = rig
    path = Path(roots[0].path) / "operation.json"
    value = json.loads(path.read_bytes())
    value["operation"]["review_sha256"] = "f" * 64
    rehash(value)
    path.write_text(json.dumps(value))
    review = owner(rig)
    result = review.decide_for_characterization(review.case_for_characterization(), "request_recovery_review")
    assert not result.permission_granted
    view = review.projection_for_characterization()
    assert view["candidate_association"] == "exact"
    assert view["journal"]["authenticity"] == "unverified"
    assert not view["retention"]["external_count_complete"]


@pytest.mark.parametrize("change", ["image", "project", "journal", "orphan"])
def test_changed_evidence_invalidates_pending_review_and_copied_case(rig, change):
    build(rig)
    review = owner(rig)
    case = review.case_for_characterization()
    assert review.decide_for_characterization(replace(case), "defer").status == "stale_case"
    assert review.decide_for_characterization(case, "request_recovery_review").status == "review_intention_recorded"
    roots, _ = rig
    if change == "image":
        (Path(roots[3].path) / "image.png").unlink()
    elif change == "project":
        path = Path(roots[1].path) / "project.json"
        value = json.loads(path.read_bytes())
        value["unknown"]["keep"] = 8
        path.write_text(json.dumps(value))
    elif change == "journal":
        (Path(roots[0].path) / "operation.json").write_bytes(b"broken")
    else:
        (Path(roots[3].path) / "extra.png").write_bytes(b"unknown")
    assert review.decide_for_characterization(case, "request_discard_review").status == "stale_case"
    assert review.projection_for_characterization()["decision"] == "undecided"
    assert review.case_for_characterization().revision == case.revision + 1


@pytest.mark.parametrize("change", ["tampered", "unverified_orphan"])
def test_changed_unsafe_file_invalidates_review_even_when_status_unchanged(rig, change):
    build(rig)
    roots, _ = rig
    if change == "tampered":
        path = Path(roots[3].path) / "image.png"
        data = bytearray(path.read_bytes())
        data[40] ^= 1
        path.write_bytes(data)
    else:
        path = Path(roots[3].path) / "orphan.png"
        path.write_bytes(b"unverified-1")
    review = owner(rig)
    case = review.case_for_characterization()
    review.decide_for_characterization(case, "request_discard_review")
    current_statuses = case.inventory.files, case.inventory.orphans
    if change == "tampered":
        data[41] ^= 1
        path.write_bytes(data)
    else:
        path.write_bytes(b"unverified-2")
    assert review.decide_for_characterization(case, "request_discard_review").status == "stale_case"
    new_case = review.case_for_characterization()
    assert (new_case.inventory.files, new_case.inventory.orphans) == current_statuses
    assert new_case.local_identities != case.local_identities
    assert review.projection_for_characterization()["decision"] == "undecided"


@pytest.mark.parametrize("intention", ["defer", "request_recovery_review", "request_discard_review"])
def test_decisions_idempotent_but_cannot_conflict(rig, intention):
    build(rig)
    review = owner(rig)
    case = review.case_for_characterization()
    assert review.decide_for_characterization(case, "inspect").status == "inspection_only"
    assert review.decide_for_characterization(case, intention).status == "review_intention_recorded"
    assert review.decide_for_characterization(case, intention).status == "repeated"
    different = "defer" if intention != "defer" else "request_discard_review"
    assert review.decide_for_characterization(case, different).status == "conflicting_decision"
    assert review.decide_for_characterization(case, "inspect").intention == intention
    for forbidden in ("recover", "discard", "publish", "save", "resume", "submit", "grant_permission"):
        assert review.decide_for_characterization(case, forbidden).status == "unsupported_decision"


def test_session_loss_expiry_and_missing_provenance_withhold_authority(rig):
    build(rig)
    review = owner(rig)
    case = review.case_for_characterization()
    review.decide_for_characterization(case, "request_recovery_review")
    changed = review.refresh_for_characterization(context=RecoveryContext("expired", "stale", "missing", "missing"))
    assert changed.revision == case.revision + 1
    view = review.projection_for_characterization()
    assert view["decision"] == "undecided"
    assert {"runtime_authority_expired", "original_session_stale", "source_provenance_missing", "review_provenance_missing"} <= set(view["blockers"])
    assert review.decide_for_characterization(case, "request_recovery_review").status == "stale_case"
    missing = review.refresh_for_characterization(context=RecoveryContext())
    assert {"runtime_authority_missing", "original_session_lost"} <= set(missing.reasons)


def test_projection_redacts_paths_payloads_prompts_and_claims(rig):
    build(rig)
    roots, _ = rig
    (Path(roots[3].path) / "credential-secret.png").write_bytes(b"SECRET")
    case = owner(rig).case_for_characterization()
    encoded = json.dumps(recovery_projection(case))
    for private in (roots[0].path, roots[1].path, "claim-secret", "session-secret", "process-secret", "request-secret",
                    "FULL PROMPT SECRET", "https://secret", "SECRET", "credential-secret", "generation_provenance"):
        assert private not in encoded
    assert roots[1].path not in repr(case) and "claim-secret" not in repr(case)


def test_no_mutation_save_delete_move_network_or_worker_restart(rig):
    build(rig)
    roots, _ = rig
    before = disk_bytes(roots)
    def forbidden(*args, **kwargs):
        pytest.fail("recovery inspection attempted a side effect")
    with patch("core.io.save_project_to_json", forbidden), patch("core.io.save_project_to_json_atomically", forbidden), \
         patch("os.replace", forbidden), patch("os.remove", forbidden), \
         patch("os.unlink", forbidden), patch("shutil.move", forbidden), patch("socket.socket", forbidden), \
         patch("threading.Thread.start", forbidden), patch.object(j.OfflineJournalWriter, "append_for_characterization", forbidden):
        review = owner(rig)
        for intention in ("inspect", "defer", "request_recovery_review", "request_discard_review"):
            review.decide_for_characterization(review.case_for_characterization(), intention)
            review.projection_for_characterization()
        review.refresh_for_characterization()
        review.close()
        assert review.decide_for_characterization(review.case_for_characterization(), "inspect").status == "closed"
    assert disk_bytes(roots) == before


def test_recovery_owner_is_separate_from_runtime_jobs_and_executors():
    from ui import agent_generation_human_recovery as recovery
    source = Path(recovery.__file__).read_text()
    imports = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module)
    assert not any(name.startswith("ui.") for name in imports)
    assert not any(name in source for name in ("GenerationJobRegistry", "GenerationCandidatePublication",
                                               "GenerationExecutorInbox", "ProjectAgentSessionRuntime"))


def test_no_production_owner_or_unbounded_budgets(rig):
    roots, _ = rig
    with pytest.raises(ValueError, match="execution_unavailable"):
        HumanRecoveryReviewOwner(roots[0], "operation.json", roots[1], "project.json")
    for kwargs in ({"max_entries": 65}, {"max_file_bytes": 33 * 1024 * 1024}):
        with pytest.raises(ValueError, match="invalid_budget"):
            owner(rig, **kwargs)
