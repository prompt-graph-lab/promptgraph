"""Disposable C2B-8C-1 observations; no production effects or ACL mutation."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core import generation_ownership_journal as j
from core import generation_protected_storage as p
from ui.agent_generation_human_recovery import HumanRecoveryReviewOwner


@pytest.fixture
def storage(tmp_path):
    paths = {}
    for purpose in p.PURPOSES[:-1]:
        path = tmp_path / purpose
        path.mkdir()
        paths[purpose] = str(path)
    project_dir = tmp_path / "original_project"
    project_dir.mkdir()
    selected = project_dir / "project.json"
    selected.write_text('{"prompt_lines":[{"id":"line","generated_candidates":[]}]}')
    paths[p.PURPOSES[-1]] = str(selected)
    owner = p.ProtectedStorageCharacterization.capture_for_characterization(
        str(tmp_path), paths, characterization=True, disposable_opt_in=True)
    return tmp_path, paths, owner


def assert_closed(view):
    for key in ("execution_available", "recovery_execution_allowed", "attachment_allowed",
                "publication_allowed", "project_save_allowed", "cleanup_allowed",
                "protected_storage_available", "power_loss_guarantee",
                "same_user_process_authentication"):
        assert view[key] is False
    assert view["authorship"] == "unverified"
    assert view["current_authorization"] == "absent"
    assert view["digest_chain"] == "not_inspected"


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin", "unknown"])
def test_explicit_roots_redacted_and_platforms_fail_closed(storage, platform):
    scope, paths, owner = storage
    with patch.object(p.sys, "platform", platform):
        view = owner.readiness()
    assert_closed(view)
    assert len(view["roots"]) == 4
    assert [r["purpose"] for r in view["roots"]] == list(p.PURPOSES)
    assert all(r["identity"] == "observed_unchanged" for r in view["roots"])
    assert all(r["acl"] == "unavailable" and r["integrity"] == "not_inspected" for r in view["roots"])
    assert view["handle_pinning"] == "unavailable" and view["filesystem"] == "unverified"
    assert view["blocker"] == ("native_observation_required" if platform == "win32" else "unsupported_platform")
    encoded = json.dumps(view)
    assert str(scope) not in encoded and not any(path in encoded for path in paths.values())
    assert len(encoded) < 2200
    view["roots"][0]["identity"] = "forged"
    assert owner.readiness()["roots"][0]["identity"] == "observed_unchanged"


@pytest.mark.parametrize("characterization,opt_in", [(False, True), (True, False), (1, True), (True, 1)])
def test_opt_in_required_before_probing(characterization, opt_in):
    with patch.object(Path, "lstat", side_effect=AssertionError("must not probe")):
        with pytest.raises(ValueError, match="execution_unavailable"):
            p.ProtectedStorageCharacterization.capture_for_characterization(
                "unused", {}, characterization=characterization, disposable_opt_in=opt_in)


def test_unapproved_or_inferred_purposes_refused_before_io(storage):
    scope, paths, _ = storage
    for changed in ({**paths, "private_journal": str(scope.parent / "unapproved")},
                    {**paths, "promoted_assets": str(scope)}, {"private_journal": paths["private_journal"]}):
        with patch.object(Path, "lstat", side_effect=AssertionError("must not probe")):
            with pytest.raises(ValueError, match="unapproved_root|explicit_purposes_required"):
                p.ProtectedStorageCharacterization.capture_for_characterization(
                    str(scope), changed, characterization=True, disposable_opt_in=True)


def test_overlapping_purposes_and_other_project_refused(storage):
    scope, paths, _ = storage
    changed = {**paths, "promoted_assets": paths["private_journal"]}
    with pytest.raises(ValueError, match="purpose_overlap"):
        p.ProtectedStorageCharacterization.capture_for_characterization(
            str(scope), changed, characterization=True, disposable_opt_in=True)
    changed = {**paths, "selected_project_json": str(scope / "project.txt")}
    with pytest.raises(ValueError, match="selected_json_required"):
        p.ProtectedStorageCharacterization.capture_for_characterization(
            str(scope), changed, characterization=True, disposable_opt_in=True)


@pytest.mark.parametrize("purpose", p.PURPOSES)
def test_identity_substitution_never_recaptured(storage, purpose):
    _, paths, owner = storage
    target = Path(paths[purpose])
    target.rename(target.with_name(target.name + ".retained"))
    if purpose == "selected_project_json":
        target.write_bytes(target.with_name(target.name + ".retained").read_bytes())
    else:
        target.mkdir()
    view = owner.readiness()
    assert next(r for r in view["roots"] if r["purpose"] == purpose)["identity"] == "changed"
    assert_closed(view)


def test_scope_substitution_and_unreadable_redacted(storage):
    _, _, owner = storage
    original = p._ordinary
    def substitute(path, *, directory):
        if path == owner._scope:
            return (0, 0)
        return original(path, directory=directory)
    with patch.object(p, "_ordinary", substitute):
        assert all(r["identity"] == "changed" for r in owner.readiness()["roots"])
    with patch.object(Path, "lstat", side_effect=PermissionError("PRIVATE PATH SID SECRET")):
        view = owner.readiness()
    assert all(r["identity"] == "unsafe_or_unavailable" for r in view["roots"])
    assert "SECRET" not in json.dumps(view)
    assert_closed(view)


@pytest.mark.parametrize("kind", ["reparse", "symlink"])
@pytest.mark.parametrize("ancestor", [False, True])
def test_reparse_and_symlink_observations_fail_closed(storage, kind, ancestor):
    _, paths, owner = storage
    target = Path(paths["selected_project_json"])
    changed = target.parent if ancestor else target
    original = Path.lstat
    def injected(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path != changed:
            return info
        values = {name: getattr(info, name) for name in ("st_mode", "st_dev", "st_ino", "st_nlink")}
        values["st_file_attributes"] = 0x400 if kind == "reparse" else 0
        if kind == "symlink":
            import stat
            values["st_mode"] = stat.S_IFLNK
        return SimpleNamespace(**values)
    with patch.object(Path, "lstat", injected):
        view = owner.readiness()
        assert view["roots"][-1]["identity"] == "unsafe_or_unavailable"
    assert_closed(view)


def test_actual_hardlink_refused(storage):
    scope, paths, owner = storage
    os.link(paths["selected_project_json"], scope / "project-alias.json")
    assert owner.readiness()["roots"][-1]["identity"] == "unsafe_or_unavailable"
    with pytest.raises(ValueError, match="multiple_file_links"):
        p.ProtectedStorageCharacterization.capture_for_characterization(
            str(scope), paths, characterization=True, disposable_opt_in=True)


def test_readiness_has_no_writes_content_reads_scans_or_network(storage):
    _, paths, owner = storage
    selected = Path(paths["selected_project_json"])
    before = selected.read_bytes()
    with patch.multiple(os, open=pytest.fail, mkdir=pytest.fail, unlink=pytest.fail,
                        remove=pytest.fail, replace=pytest.fail, chmod=pytest.fail, scandir=pytest.fail), \
         patch("socket.socket", side_effect=AssertionError("no transport")), \
         patch.object(Path, "read_bytes", side_effect=AssertionError("no content reads")):
        assert_closed(owner.readiness())
    assert selected.read_bytes() == before


USER = "S-1-5-21-101-202-303-1001"


@pytest.fixture
def acl():
    return p.AclPolicySample(USER, USER, True, True, ((USER, "allow", 0x1F01FF, False),))


def test_compatible_acl_sample_never_verifies_or_authenticates(acl):
    view = p.characterize_acl_policy(acl)
    assert view["policy"] == "compatible_model_only"
    assert not any(v for key, v in view.items() if key != "policy")
    assert USER not in json.dumps(view)


@pytest.mark.parametrize("changes", [
    {"owner_sid": "S-1-5-18"}, {"protected_dacl": False}, {"dacl_present": False},
    {"entries": (("S-1-1-0", "allow", 0x1F01FF, False),)},  # Everyone
    {"entries": (("S-1-5-32-545", "allow", 1, False),)},  # Users, even read access
    {"entries": ((USER, "allow", 0x1F01FF, True),)},
    {"entries": (("S-1-5-18", "allow", 0x1F01FF, False),)},
])
def test_unsafe_owner_principals_or_inheritance(acl, changes):
    view = p.characterize_acl_policy(replace(acl, **changes))
    assert view["policy"] == "unsafe" and not view["acl_verified"]
    assert not view["execution_available"]


@pytest.mark.parametrize("changes", [
    {"entries": ((USER, "deny", 1, False),)},
    {"entries": ((USER, "object_allow", 1, False),)},
    {"entries": ((USER, "allow", 0x1000, False),)},
    {"entries": ((USER, "allow", True, False),)},
    {"entries": ()}, {"entries": ((USER, "allow", 1, False),) * 65},
    {"current_user_sid": "secret not a SID"}, {"protected_dacl": 1},
])
def test_unmodeled_acl_fail_closed(acl, changes):
    view = p.characterize_acl_policy(replace(acl, **changes))
    assert view["policy"] == "unsupported" and not view["acl_verified"]
    assert not view["execution_available"]


@pytest.fixture
def journal(storage):
    _, paths, _ = storage
    journal_root = j.ApprovedRoot.capture_for_characterization(
        "journal", paths["private_journal"], characterization=True)
    project_path = Path(paths["selected_project_json"])
    project_root = j.ApprovedRoot.capture_for_characterization(
        "project", str(project_path.parent), characterization=True)
    op = j.OperationObservation("operation", "job", "manifest", hashlib.sha256(project_path.read_bytes()).hexdigest(),
        "project", project_root.path, project_root.identity, project_path.name,
        j._file_identity(project_path.stat()), "process", "session", "claim", "c" * 64,
        (j.FrozenRequestCorrelation("request", 0, "line", 1, "workflow"),))
    writer = j.OfflineJournalWriter(journal_root, op, characterization=True)
    writer.append_for_characterization(j.Observation("submission_intent", "intent"))
    return journal_root, project_root, writer


@pytest.mark.parametrize("boundary,revision", [("before_replace", 1), ("after_replace_before_ack", 2)])
def test_real_disposable_interruption_and_ambiguous_ack(journal, boundary, revision):
    root, _, writer = journal
    def fault(point):
        if point == boundary:
            raise RuntimeError("disposable interruption")
    writer.fault = fault
    with pytest.raises(RuntimeError):
        writer.append_for_characterization(j.Observation("submission_observed", "unknown"))
    reopened = j.reopen_journal(root, "operation.json")
    assert reopened.revision == revision and reopened.authenticity == "unverified"
    view = p.characterize_write_boundary(boundary)
    assert view["acknowledgment"] == ("ambiguous" if revision == 2 else "unacknowledged")
    assert view["directory_durability"] == "unsupported" and not view["power_loss_guarantee"]
    assert not view["retry_allowed"] and not view["external_effect_confirmed"]
    with pytest.raises(ValueError, match="writer_uncertain"):
        writer.append_for_characterization(j.Observation("submission_observed", "unknown"))


def test_file_sync_failure_preserves_previous_journal(journal):
    root, _, writer = journal
    before = (Path(root.path) / "operation.json").read_bytes()
    with patch.object(j.os, "fsync", side_effect=OSError("unsupported flush")):
        with pytest.raises(OSError):
            writer.append_for_characterization(j.Observation("submission_observed", "unknown"))
    assert (Path(root.path) / "operation.json").read_bytes() == before
    assert list(Path(root.path).glob("*.tmp"))  # evidence retained, no cleanup
    assert p.characterize_write_boundary("file_sync_failed")["acknowledgment"] == "unacknowledged"


def test_acknowledged_write_still_has_no_directory_or_transaction_guarantee():
    view = p.characterize_write_boundary("acknowledged")
    assert view["visible_file"] == "new_observed" and view["acknowledgment"] == "observed"
    assert not any(view[k] for k in ("power_loss_guarantee", "cross_file_transaction",
                                   "external_effect_confirmed", "execution_available"))
    with pytest.raises(ValueError, match="unsupported_write_boundary"):
        p.characterize_write_boundary("SECRET payload")


def test_digest_valid_same_user_rewrite_and_rollback_remain_inspect_only(journal, storage):
    root, project, writer = journal
    path = Path(root.path) / "operation.json"
    first = path.read_bytes()
    tip = writer.append_for_characterization(j.Observation("submission_observed", "unknown"))
    value = json.loads(path.read_bytes())
    # Same-user process can rewrite claimed author and recompute all SHA digests.
    value["operation"]["process_identity"] = "other-process"
    previous = "0" * 64
    for entry in value["revisions"]:
        entry["previous_digest"] = previous
        unsigned = {key: val for key, val in entry.items() if key != "digest"}
        entry["digest"] = j._hash({"schema": j.SCHEMA, "version": 1, "operation": value["operation"], **unsigned})
        previous = entry["digest"]
    path.write_text(json.dumps(value))
    forged = j.reopen_journal(root, "operation.json")
    assert forged.operation.process_identity == "other-process"
    assert forged.authenticity == "unverified" and not forged.execution_available
    path.write_bytes(first)
    rolled_back = j.reopen_journal(root, "operation.json")
    assert rolled_back.revision == 1 and rolled_back.trust == "inspect_only"
    with pytest.raises(ValueError, match="stale_revision"):
        j.reopen_journal(root, "operation.json", expected_revision=tip.revision, expected_digest=tip.digest)
    before = path.read_bytes(), (Path(project.path) / "project.json").read_bytes()
    recovery = HumanRecoveryReviewOwner(root, "operation.json", project, "project.json", (), characterization=True)
    view = recovery.projection_for_characterization()
    assert view["status"] == "inspect_only"
    assert not any(view[key] for key in ("execution_available", "attachment_allowed", "publication_allowed", "cleanup_allowed"))
    assert before == (path.read_bytes(), (Path(project.path) / "project.json").read_bytes())
    assert_closed(storage[2].readiness())
