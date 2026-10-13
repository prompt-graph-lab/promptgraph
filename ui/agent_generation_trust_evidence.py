"""C2B-8C-4 offline diagnostic composition; no production caller or authority.

Only existing host owners read files, validate Journal chains and reconcile the
explicit selected Project. Expected tips are caller observations, never trusted
heads. Native observations enter through the protected Journal's private seam.
"""
import json

from core import generation_ownership_journal as j
from ui.agent_generation_human_recovery import HumanRecoveryReviewOwner, recovery_projection


MAX_PROJECTION_BYTES = 64 * 1024


def _expected_tip(revision, digest):
    if revision is None and digest is None:
        return None
    if type(revision) is not int or not 1 <= revision <= 8:
        raise ValueError("invalid_expected_tip")
    try:
        j._digest(digest)
    except ValueError:
        raise ValueError("invalid_expected_tip") from None
    return revision, digest


def _tip(observed, expected):
    if expected is None:
        return {"availability": "unavailable", "comparison": "no_expected_tip",
                "provenance": "unavailable", "custody": "unverified"}
    state = "observed_tip_unavailable"
    if observed is not None:
        if observed.revision < expected[0]:
            state = "behind_supplied_tip"
        elif observed.revision == expected[0] and observed.digest == expected[1]:
            state = "matches"
        else:
            state = "conflicts"
    return {"availability": "supplied", "comparison": state,
            "provenance": "caller_observation_unverified", "custody": "unverified"}


def _empty(native="not_inspected", expected=None):
    return {"contract": "promptgraph.generation-trust-evidence.v1", "status": "inspect_only",
        "execution_available": False, "protected_storage_available": False,
        "authorship": "unverified", "fresh_authorization_required": True,
        "evidence": {
            "protected_root": native, "native_acl": native,
            "journal_file": "unavailable", "schema_revision_digest_chain": "unverified",
            "checkpoint_coverage": "unknown", "producer": "unavailable",
            "expected_tip": _tip(None, expected), "authorship": "unverified",
            "original_project": "unverified", "source": "unverified", "review": "unverified",
            "source_comparison": "independent_observation_unavailable",
            "review_comparison": "independent_observation_unavailable",
            "current_session": "missing", "activation": "unavailable", "pairing": "unavailable",
            "runtime_authorization": "absent", "candidate_association": "unverified",
            "save": "unknown", "save_certainty": "uncertain", "external_submission": "unknown",
            "inventory": "unavailable", "retention": "incomplete_or_unknown"},
        "reasons": ["fresh_authorization_required", "authorship_unverified", "latest_head_unverified"],
        "human_recovery": None}


def _bounded(view):
    # A final bound also protects against accidental growth of the composed
    # Recovery projection. Never truncate evidence into an apparently complete case.
    encoded = json.dumps(view, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PROJECTION_BYTES:
        limited = _empty()
        limited["reasons"].append("projection_limit_exceeded")
        return limited
    return json.loads(encoded)


def _inspect(root, filename, project_root, relative, asset_roots, entries, byte_budget,
             expected, *, native=False, producer=None):
    # Private composition interface. No public trust booleans, RecoveryContext,
    # stored root paths, case or serialized native observations are accepted.
    owner = HumanRecoveryReviewOwner(root, filename, project_root, relative, asset_roots,
        max_entries=entries, max_file_bytes=byte_budget, characterization=True)
    try:
        case = owner.refresh_for_characterization()
        recovery = recovery_projection(case)
    finally:
        owner.close()
    journal = case.journal
    view = _empty("owner_only_acl_observed" if native else "not_inspected", expected)
    evidence = view["evidence"]
    evidence.update({
        "journal_file": "identity_and_bytes_observed" if journal else "unavailable",
        "schema_revision_digest_chain": "valid_observed_chain" if journal else "unverified",
        "checkpoint_coverage": journal.checkpoint_coverage if journal else "unknown",
        "producer": "reopened_assertion" if journal else "unavailable",
        "expected_tip": _tip(journal, expected),
        "original_project": recovery["project"],
        "source": "recorded_unverified" if journal and journal.operation.source_sha256 else "missing",
        "review": "recorded_unverified" if journal and journal.operation.review_sha256 else "missing",
        "candidate_association": recovery["candidate_association"],
        "save": recovery["save_outcome"],
        "save_certainty": "uncertain" if recovery["save_uncertain"] else "saved_bytes_observed",
        "external_submission": recovery["external_execution"],
        "inventory": "incomplete" if recovery["inventory"] == "not fully inspected" else "bounded_scope_inspected",
        "retention": recovery["retention"]["capacity"]})
    if journal and producer is not None:
        observed = (journal.operation, journal.revision, journal.digest, journal.file_identity)
        evidence["producer"] = ("live_acknowledged_snapshot_observed" if observed == producer
                                else "live_snapshot_conflicting")
    if journal is None:
        view["reasons"].append("journal_missing_unreadable_or_conflicting")
    elif journal not in case.inventory.journals:
        view["reasons"].append("journal_inventory_snapshot_conflicting")
        evidence["journal_file"] = "snapshot_conflicting"
    comparison = evidence["expected_tip"]["comparison"]
    if comparison in ("conflicts", "behind_supplied_tip"):
        view["reasons"].append("supplied_tip_mismatch")
    if case.inventory.truncated or case.inventory.errors:
        view["reasons"].append("inventory_incomplete_or_conflicting")
    if evidence["original_project"] not in ("original_bytes_observed", "saved_bytes_observed"):
        view["reasons"].append("original_project_needs_reconciliation")
    view["human_recovery"] = recovery
    return _bounded(view)


def inspect_trust_evidence_for_characterization(journal_root, filename, *,
        selected_project_root=None, selected_relative_path="project.json", asset_roots=(),
        expected_revision=None, expected_digest=None, max_entries=64,
        max_file_bytes=32 * 1024 * 1024, characterization=False):
    """Portable inspection of explicit approved roots; no OS ACL certification.

    For native ACL/handle observations, use the protected Journal owner's method.
    The caller-supplied complete tip is only comparative evidence. Neither this
    API nor the nested Recovery projection grants any permission.
    """
    if characterization is not True:
        raise ValueError("execution_unavailable")
    expected = _expected_tip(expected_revision, expected_digest)
    return _inspect(journal_root, filename, selected_project_root, selected_relative_path,
                    asset_roots, max_entries, max_file_bytes, expected)
