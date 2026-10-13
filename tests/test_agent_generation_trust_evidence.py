"""Offline, detached trust diagnostics with real existing owner composition."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from core import generation_ownership_journal as j
from core import generation_windows_protected_storage as w
from ui import agent_generation_trust_evidence as t
from test_agent_generation_human_recovery import rig, build, disk_bytes
from test_generation_protected_journal import rig as native_rig, intent, observed
from test_generation_windows_protected_storage import native_scope, mutate_disposable_acl


def inspect(rig, **kwargs):
    roots, _ = rig
    return t.inspect_trust_evidence_for_characterization(roots[0], "operation.json",
        selected_project_root=roots[1], asset_roots=roots[2:], characterization=True, **kwargs)


def no_authority(view):
    assert view["status"] == "inspect_only"
    assert view["authorship"] == "unverified"
    assert not view["execution_available"] and not view["protected_storage_available"]
    assert view["fresh_authorization_required"]
    assert view["evidence"]["runtime_authorization"] == "absent"
    assert view["evidence"]["current_session"] == "missing"
    assert view["evidence"]["activation"] == view["evidence"]["pairing"] == "unavailable"
    recovery = view["human_recovery"]
    if recovery:
        assert recovery["status"] == "inspect_only"
        assert not any(recovery[k] for k in ("execution_available", "attachment_allowed", "publication_allowed", "cleanup_allowed"))


def test_complete_no_tip_detached_redacted_read_only(rig):
    build(rig)
    before = disk_bytes(rig[0])
    view = inspect(rig)
    no_authority(view)
    e = view["evidence"]
    assert e["native_acl"] == e["protected_root"] == "not_inspected"
    assert e["schema_revision_digest_chain"] == "valid_observed_chain"
    assert e["checkpoint_coverage"] == "complete"
    assert e["producer"] == "reopened_assertion"
    assert e["expected_tip"]["comparison"] == "no_expected_tip"
    assert e["candidate_association"] == "exact" and e["save_certainty"] == "saved_bytes_observed"
    assert e["source"] == e["review"] == "recorded_unverified"
    assert e["source_comparison"] == e["review_comparison"] == "independent_observation_unavailable"
    encoded = json.dumps(view)
    for secret in (str(rig[0][0].path), "process-secret", "session-secret", "claim-secret", "request-secret",
                   "FULL PROMPT SECRET", "api_key", "descriptor", "workflow", "S-1-", "manifest"):
        assert secret not in encoded
    assert len(encoded.encode()) <= t.MAX_PROJECTION_BYTES
    view["human_recovery"]["images"].clear()
    view["evidence"]["authorship"] = "forged"
    assert len(inspect(rig)["human_recovery"]["images"]) == 1
    assert disk_bytes(rig[0]) == before


def test_matching_tip_is_observation_not_custody(rig):
    journal, _, _ = build(rig)
    view = inspect(rig, expected_revision=journal.revision, expected_digest=journal.digest)
    assert view["evidence"]["expected_tip"] == {"availability": "supplied", "comparison": "matches",
        "provenance": "caller_observation_unverified", "custody": "unverified"}
    no_authority(view)
    assert journal.digest not in json.dumps(view)


def test_digest_valid_rollback_and_same_revision_rewrite(rig):
    journal, _, _ = build(rig)
    path = Path(rig[0][0].path) / "operation.json"
    raw = json.loads(path.read_bytes())
    raw["revisions"] = raw["revisions"][:2]
    path.write_text(json.dumps(raw))
    view = inspect(rig, expected_revision=journal.revision, expected_digest=journal.digest)
    assert view["evidence"]["schema_revision_digest_chain"] == "valid_observed_chain"
    assert view["evidence"]["expected_tip"]["comparison"] == "behind_supplied_tip"
    no_authority(view)
    # Same-user rewriting and resealing cannot establish author authentication.
    prior = j.reopen_journal(rig[0][0], "operation.json")
    raw["operation"]["source_sha256"] = "a" * 64
    raw["operation"]["review_sha256"] = "b" * 64
    previous = "0" * 64
    for entry in raw["revisions"]:
        entry["previous_digest"] = previous
        unsigned = {k: v for k, v in entry.items() if k != "digest"}
        previous = j._hash({"schema": j.SCHEMA, "version": 1, "operation": raw["operation"], **unsigned})
        entry["digest"] = previous
    path.write_text(json.dumps(raw))
    view = inspect(rig, expected_revision=prior.revision, expected_digest=prior.digest)
    assert view["evidence"]["schema_revision_digest_chain"] == "valid_observed_chain"
    assert view["evidence"]["expected_tip"]["comparison"] == "conflicts"
    assert view["evidence"]["source"] == "recorded_unverified"
    assert view["evidence"]["review"] == "recorded_unverified"
    assert view["evidence"]["source_comparison"] == "independent_observation_unavailable"
    assert view["evidence"]["review_comparison"] == "independent_observation_unavailable"
    assert inspect(rig)["evidence"]["authorship"] == "unverified"
    no_authority(view)


@pytest.mark.parametrize("damage", ["malformed", "digest", "missing"])
def test_missing_malformed_conflicting_journal(rig, damage):
    build(rig)
    path = Path(rig[0][0].path) / "operation.json"
    if damage == "missing":
        path.unlink()  # disposable test setup only; inspector never removes evidence
    elif damage == "malformed":
        path.write_bytes(b'{"secret":')
    else:
        raw = json.loads(path.read_bytes())
        raw["revisions"][-1]["digest"] = "0" * 64
        path.write_text(json.dumps(raw))
    before = disk_bytes(rig[0])
    view = inspect(rig)
    assert view["evidence"]["schema_revision_digest_chain"] == "unverified"
    assert "journal_missing_unreadable_or_conflicting" in view["reasons"]
    no_authority(view)
    assert disk_bytes(rig[0]) == before


@pytest.mark.parametrize("state", ["missing", "changed", "partial", "save", "remote", "truncated"])
def test_incomplete_independent_axes(rig, state):
    kwargs = {}
    if state == "partial":
        kwargs.update(candidates=2, saved_candidates=1)
    if state == "save":
        kwargs.update(save="uncertain", saved_digest=False)
    if state == "remote":
        kwargs.update(remote="unproven")
    build(rig, **kwargs)
    path = Path(rig[0][1].path) / "project.json"
    if state == "missing":
        path.unlink()
    if state == "changed":
        path.write_text('{"prompt_lines":[{"id":"different"}]}')
    if state == "truncated":
        (Path(rig[0][0].path) / "unindexed-secret.tmp").write_bytes(b"uncertain evidence")
    view = inspect(rig, **({"max_entries": 1} if state == "truncated" else {}))
    e = view["evidence"]
    if state == "missing":
        assert e["original_project"] == "missing"
    elif state == "changed":
        assert e["original_project"] == "changed_original_project"
    elif state == "partial":
        assert e["candidate_association"] == "partial"
    elif state == "save":
        assert e["save"] == "uncertain" and e["save_certainty"] == "uncertain"
    elif state == "remote":
        assert e["external_submission"] == "unknown"
    elif state == "truncated":
        assert e["inventory"] == "incomplete"
    no_authority(view)


def test_no_flags_context_or_tip_authentication_parameters(rig):
    build(rig)
    for options in ({"authorship": "verified"}, {"native": True}, {"context": {}},
                    {"trusted": True}, {"expected_tip_trusted": True}, {"producer": ()}):
        with pytest.raises(TypeError):
            inspect(rig, **options)
    for options in ({"expected_revision": 8}, {"expected_digest": "c" * 64},
                    {"expected_revision": True, "expected_digest": "c" * 64},
                    {"expected_revision": 9, "expected_digest": "c" * 64}):
        with pytest.raises(ValueError, match="invalid_expected_tip"):
            inspect(rig, **options)
    with pytest.raises(ValueError, match="execution_unavailable"):
        t.inspect_trust_evidence_for_characterization(rig[0][0], "operation.json")
    with pytest.raises(ValueError, match="invalid_allowlist"):
        t.inspect_trust_evidence_for_characterization(str(rig[0][0].path), "operation.json", characterization=True)


def test_limit_withholds_overgrown_case(rig):
    build(rig)
    with patch.object(t, "MAX_PROJECTION_BYTES", 1500):
        view = inspect(rig)
    assert view["human_recovery"] is None
    assert "projection_limit_exceeded" in view["reasons"]
    no_authority(view)


def test_no_effects_on_inspection(rig):
    build(rig)
    before = disk_bytes(rig[0])
    with patch("os.replace", side_effect=AssertionError("no replacement")), \
         patch("pathlib.Path.unlink", side_effect=AssertionError("no deletion")), \
         patch("socket.create_connection", side_effect=AssertionError("no network")), \
         patch.object(j.OfflineJournalWriter, "append_for_characterization", side_effect=AssertionError("no write")):
        view = inspect(rig)
    no_authority(view)
    assert disk_bytes(rig[0]) == before


def test_native_live_then_fresh_reopen(native_rig):
    owner, scope, _, op, selected = native_rig
    owner.initialize_for_characterization(op)
    tip = owner.append_for_characterization(intent())
    view = owner.inspect_trust_evidence_for_characterization("operation.json", selected_project_root=selected,
        expected_revision=tip.revision, expected_digest=tip.digest)
    assert view["evidence"]["native_acl"] == "owner_only_acl_observed"
    assert view["evidence"]["producer"] == "live_acknowledged_snapshot_observed"
    no_authority(view)
    path = owner._native._path
    owner.close()
    assert owner.inspect_trust_evidence_for_characterization("operation.json")["evidence"]["protected_root"] == "closed"
    from core.generation_protected_journal import WindowsProtectedJournalCharacterization
    with WindowsProtectedJournalCharacterization.reopen_for_characterization(str(scope), str(path),
            characterization=True, disposable_opt_in=True) as reopened:
        view = reopened.inspect_trust_evidence_for_characterization("operation.json", selected_project_root=selected)
        assert view["evidence"]["producer"] == "reopened_assertion"
        assert view["evidence"]["native_acl"] == "owner_only_acl_observed"
        no_authority(view)


@pytest.mark.parametrize("target,post_read", [("root", False), ("file", False), ("root", True)])
def test_native_acl_drift_withholds_recovery(native_rig, target, post_read):
    owner, _, api, op, _ = native_rig
    owner.initialize_for_characterization(op)
    owner.append_for_characterization(intent())
    path = owner._native._path if target == "root" else owner._native._path / "operation.json"
    if post_read:
        owner._fault = lambda point: mutate_disposable_acl(path, api, "writable_principal") if point == "after_operation_before_ack" else None
    else:
        mutate_disposable_acl(path, api, "writable_principal")
    view = owner.inspect_trust_evidence_for_characterization("operation.json")
    assert view["evidence"]["protected_root"] == "unsafe_or_unavailable"
    assert view["human_recovery"] is None
    assert path.exists()
    no_authority(view)
