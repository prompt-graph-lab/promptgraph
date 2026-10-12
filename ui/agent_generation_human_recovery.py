"""C2B-8B host-only inspection and review intentions; no production call site.

The immutable case is private evidence, never a claim, ACK, executable envelope
or publication receipt. The only outward surface is the bounded projection.
"""
from dataclasses import dataclass, field, replace
import hashlib
from pathlib import Path
import threading

from core import generation_ownership_journal as journal_owner


DECISIONS = ("inspect", "defer", "request_recovery_review", "request_discard_review")
RETENTION_CLASSES = ("verified_unpublished", "published_saved_candidate_assets",
                     "promoted_after_failed_or_uncertain_save", "orphan_or_incomplete",
                     "quarantined_or_stale")


@dataclass(frozen=True)
class RecoveryContext:
    """Host observations only. Even 'observed' is not runtime authority."""
    runtime_authority: str = "missing"
    session: str = "lost"
    source_provenance: str = "missing"
    review_provenance: str = "missing"

    def __post_init__(self):
        if (self.runtime_authority not in ("missing", "expired", "observed")
                or self.session not in ("lost", "stale", "original_observed")
                or self.source_provenance not in ("missing", "recorded")
                or self.review_provenance not in ("missing", "recorded")):
            raise ValueError("invalid_recovery_context")


@dataclass(frozen=True)
class SelectedProjectObservation:
    state: str
    digest: str | None = field(default=None, repr=False)
    file_identity: tuple | None = field(default=None, repr=False)
    illustration_counts: tuple = field(default=(), repr=False)
    asset_references: tuple = field(default=(), repr=False)


@dataclass(frozen=True)
class RecoveryCase:
    """Private immutable exact snapshot; deliberately has no serialized carrier."""
    revision: int
    journal: object = field(repr=False)
    inventory: object = field(repr=False)
    project: SelectedProjectObservation = field(repr=False)
    local_identities: tuple = field(repr=False)
    reconciliation: object = field(repr=False)
    context: RecoveryContext = field(repr=False)
    original_project_sha256: str | None = field(repr=False)
    reasons: tuple[str, ...]
    unknown_requests: tuple[str, ...] = field(repr=False)
    journal_error: str | None = None
    execution_available: bool = False


@dataclass(frozen=True)
class RecoveryDecision:
    status: str
    case_revision: int
    intention: str | None = None
    execution_available: bool = False
    permission_granted: bool = False


def _read_project(journal, root, relative, asset_roots, original_project_sha256):
    if journal is None:
        return SelectedProjectObservation("original_identity_unverified")
    op = journal.operation
    if (root is None or root.key != op.project_root_key or root.path != op.project_root_path
            or root.identity != op.project_root_identity or relative != op.project_relative_path):
        return SelectedProjectObservation("different_selected_project")
    try:
        data, identity = journal_owner._read(root, relative)
        digest = hashlib.sha256(data).hexdigest()
        value = journal_owner._json(data)
        if type(value) is not dict or type(value.get("prompt_lines")) is not list:
            raise ValueError("invalid_project")
        counts, references = {}, {}
        expected_paths = {Path(r.path) / f.relative_path: (f.root_key, f.relative_path)
                          for o in journal.observations for f in o.files
                          for r in asset_roots if r.key == f.root_key}
        for line in value["prompt_lines"]:
            if type(line) is not dict:
                raise ValueError("invalid_project")
            line_id = journal_owner._id(line.get("id"))
            counts[line_id] = counts.get(line_id, 0) + 1
            records = line.get("generated_candidates", [])
            if type(records) is not list:
                raise ValueError("invalid_project")
            for record in records:
                if type(record) is not dict or type(record.get("path")) is not str:
                    raise ValueError("invalid_project")
                path = Path(record["path"])
                if not path.is_absolute():
                    path = Path(root.path) / Path(relative).parent / journal_owner._relative(record["path"])
                journal_owner._observed_absolute(str(path))
                key = expected_paths.get(path)
                if key:
                    references[key] = references.get(key, 0) + 1
        state = "original_bytes_observed"
        if not any(o.checkpoint == "save_intent" for o in journal.observations):
            if identity != op.project_file_identity:
                state = "changed_original_project"
            elif original_project_sha256 is None:
                state = "original_identity_observed_content_unverified"
            elif digest != original_project_sha256:
                state = "changed_original_project"
        else:
            saved = journal.observations[-1].save
            if saved and saved.observed_json_sha256:
                state = ("saved_bytes_observed" if saved.observed_json_sha256 == digest
                         else "changed_original_project")
            elif original_project_sha256 is None or digest != original_project_sha256:
                state = "content_needs_reconciliation"
        return SelectedProjectObservation(state, digest, identity, tuple(sorted(counts.items())), tuple(sorted(references.items())))
    except FileNotFoundError:
        return SelectedProjectObservation("missing")
    except (ValueError, OSError):
        return SelectedProjectObservation("unreadable_or_unverified")


def _unknown_requests(journal):
    if journal is None:
        return ()
    requests, remote, unresolved = {}, {}, set()
    for observation in journal.observations:
        requests.update((r.request_id, r.outcome) for r in observation.requests)
        remote.update((r.request_id, (r.execution_evidence, r.state)) for r in observation.remote_results)
        unresolved.update(u.request_id for u in observation.unresolved
                          if u.state in ("unknown", "unresolved") or u.reason == "remote_unknown")
    # Accepted, a local image or a Candidate never proves remote completion.
    return tuple(r.request_id for r in journal.operation.requests
                 if r.request_id in unresolved or None in unresolved
                 or (requests.get(r.request_id) != "failed"
                     and remote.get(r.request_id) not in (("validated_success", "ready"),
                                                         ("validated_failure", "ready"))))


def _local_identities(inventory, asset_roots):
    """Bounded metadata for inspected/listed entries; no extra encoded reads."""
    roots = {r.key: r for r in asset_roots}
    values = []
    keys = sorted({(root, relative) for root, relative, _ in inventory.files + inventory.orphans})[:64]
    for key, relative in keys:
        root = roots.get(key)
        if root is None:
            values.append((key, relative, "unapproved_root", None))
            continue
        try:
            path = root.check() / journal_owner._relative(relative)
            journal_owner._canonical(path)
            stat = journal_owner._ordinary(path, directory=False)
            root.check()
            values.append((key, relative, "observed", (journal_owner._file_identity(stat),
                            stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)))
        except FileNotFoundError:
            values.append((key, relative, "missing", None))
        except (ValueError, OSError):
            values.append((key, relative, "unverified_or_unsafe", None))
    return tuple(values)


def _observe(spec, context, revision):
    journal_root, filename, project_root, relative, asset_roots, entries, byte_budget, expected_revision, expected_digest, original_project_sha256 = spec
    journal, error = None, None
    try:
        journal = journal_owner.reopen_journal(journal_root, filename,
                    expected_revision=expected_revision, expected_digest=expected_digest)
    except FileNotFoundError:
        error = "journal_missing"
    except (ValueError, OSError):
        # Do not expose exception text, filenames or attacker-controlled codes.
        error = "journal_unreadable_stale_or_conflicting"
    try:
        inventory = journal_owner.inspect_inventory(journal_root, asset_roots,
                        max_entries=entries, max_file_bytes=byte_budget)
    except (ValueError, OSError):
        inventory = journal_owner.InventoryResult((), (("", "inventory_unavailable"),), (), (), True)
    project = _read_project(journal, project_root, relative, asset_roots, original_project_sha256)
    local_identities = _local_identities(inventory, asset_roots)
    reconciliation = None
    if journal is not None and project_root is not None:
        reconciliation = journal_owner.reconcile_selected_project(journal, project_root, relative, asset_roots)
        if _read_project(journal, project_root, relative, asset_roots, original_project_sha256) != project:
            project = replace(project, state="snapshot_conflicting")
    reasons = []
    if error:
        reasons.append(error)
    # C2B-8A has no authenticated journal producer. No input or human decision
    # can switch this to verified, even when all bytes and Candidates match.
    reasons.append("journal_authenticity_unverified")
    if journal is not None:
        if journal not in inventory.journals:
            reasons.append("journal_inventory_snapshot_conflicting")
        if journal.checkpoint_coverage != "complete":
            reasons.append("checkpoint_coverage_incomplete")
        if not journal.operation.source_sha256 or context.source_provenance == "missing":
            reasons.append("source_provenance_missing")
        if not journal.operation.review_sha256 or context.review_provenance == "missing":
            reasons.append("review_provenance_missing")
        if any(o.unresolved or o.outcome in ("unknown", "uncertain", "partial") for o in journal.observations):
            reasons.append("journal_unresolved_evidence")
        if any(c.state != "verified" for o in journal.observations for c in o.containment):
            reasons.append("containment_incomplete_or_stale")
        if any(p.state not in ("intent", "complete") for o in journal.observations for p in o.promotions):
            reasons.append("promotion_incomplete_or_stale")
    if context.runtime_authority != "observed":
        reasons.append("runtime_authority_" + context.runtime_authority)
    if context.session != "original_observed":
        reasons.append("original_session_" + context.session)
    reasons.append("fresh_authorization_required")
    if project.state not in ("original_bytes_observed", "saved_bytes_observed"):
        reasons.append("project_" + project.state)
    if journal is not None:
        counts = dict(project.illustration_counts)
        if any(counts.get(r.illustration_id, 0) > 1 for r in journal.operation.requests):
            reasons.append("duplicate_illustration_id")
        if any(counts.get(r.illustration_id, 0) == 0 for r in journal.operation.requests):
            reasons.append("original_illustration_missing")
        candidate_paths = {(c.asset_root_key, c.asset_relative_path) for o in journal.observations for c in o.candidates}
        if any(key not in candidate_paths for key, count in project.asset_references if count):
            reasons.append("unrecorded_candidate_association")
    if reconciliation and reconciliation.state in ("partial", "conflicting", "missing", "unreadable", "uncertain"):
        reasons.append("candidate_association_" + reconciliation.state)
    save = reconciliation.save_observation if reconciliation else "unknown"
    if save != "saved":
        reasons.append("project_save_" + save)
    if inventory.truncated or any(f[2] == "budget_exceeded" for f in inventory.files):
        reasons.append("inventory_not_fully_inspected")
    if inventory.errors:
        reasons.append("inventory_errors")
    if inventory.orphans:
        reasons.append("unindexed_evidence")
    if any(f[2] != "exact" for f in inventory.files):
        reasons.append("missing_altered_conflicting_or_unverified_assets")
    if any(item[2] != "observed" for item in local_identities):
        reasons.append("local_file_identity_missing_or_unverified")
    if len({(root, relative) for root, relative, _ in inventory.files + inventory.orphans}) > 64:
        reasons.append("local_file_identities_not_fully_inspected")
    if journal is not None and any(f.verification_state != "verified"
                                  for o in journal.observations for f in o.files):
        reasons.append("asset_verification_incomplete_or_stale")
    unknown = _unknown_requests(journal)
    if unknown or journal is None:
        reasons.append("external_execution_unknown")
    return RecoveryCase(revision, journal, inventory, project, local_identities, reconciliation, context, original_project_sha256,
                        tuple(dict.fromkeys(reasons)), unknown, error)


def _retention(case, images):
    rows = []
    for category in RETENTION_CLASSES:
        values = [i for i in images if i["retention_class"] == category]
        sizes = [i["observed_bytes"] for i in values]
        rows.append({"classification": category, "recorded_or_listed_count": len(values),
                     "observed_count": sum(i["inspection"] in ("exact", "unverified", "tampered", "image_invalid", "image_metadata_conflicting") for i in values),
                     "observed_bytes": sum(s for s in sizes if s is not None),
                     "size_complete": all(s is not None for s in sizes)})
    return {"assets": rows, "unknown_external_submissions": len(case.unknown_requests) if case.journal else None,
            "external_count_complete": False,
            "external_count_scope": "observed recorded requests; completeness unverified",
            "capacity": "incomplete_or_unknown", "cleanup_allowed": False,
            "scope": "explicit approved roots and bounded recorded references"}


def recovery_projection(case):
    """Safe finite labels/metadata only; never serialize the private case."""
    if type(case) is not RecoveryCase:
        raise ValueError("invalid_recovery_case")
    journal, inventory, reconciliation = case.journal, case.inventory, case.reconciliation
    associations = reconciliation.state if reconciliation else "unverified"
    save = reconciliation.save_observation if reconciliation else "unknown"
    requests, images = [], []
    if journal:
        illustration_labels = {}
        for r in journal.operation.requests:
            illustration_labels.setdefault(r.illustration_id, len(illustration_labels) + 1)
            requests.append({"request": r.request_index + 1, "illustration": illustration_labels[r.illustration_id],
                             "run": r.run_index, "external_execution": "unknown" if r.request_id in case.unknown_requests else "observed_result"})
        request_labels = {r.request_id: r.request_index + 1 for r in journal.operation.requests}
        files = {(f.root_key, f.relative_path): f for o in journal.observations for f in o.files}
        candidates = {(c.asset_root_key, c.asset_relative_path): c for o in journal.observations for c in o.candidates}
        associated_outputs = {(c.request_id, c.descriptor_identity, c.output_index) for c in candidates.values()}
        keys = files.keys() | candidates.keys()
        saved_references = dict(case.project.asset_references)
        statuses = {(root, path): status for root, path, status in inventory.files}
        identity_states = {(root, path): state for root, path, state, _ in case.local_identities}
        # Only this operation's references, plus bounded root orphans. No other
        # journal's private identifiers or file paths enter this projection.
        for key in sorted(keys)[:64]:
            item, candidate = files.get(key), candidates.get(key)
            status = statuses.get(key, "not_inspected")
            if identity_states.get(key) != "observed":
                status = identity_states.get(key, "not_inspected")
            available = bool(item and status == "exact" and item.verification_state == "verified")
            category = "orphan_or_incomplete"
            if item and item.verification_state in ("quarantined", "stale"):
                category = "quarantined_or_stale"
            elif available:
                if item.role == "promoted" and save in ("failed", "uncertain", "unknown"):
                    category = "promoted_after_failed_or_uncertain_save"
                elif (candidate and associations == "exact" and save == "saved"
                      and case.project.state == "saved_bytes_observed"):
                    category = "published_saved_candidate_assets"
                elif (not candidate and not saved_references.get(key)
                      and (item.request_id, item.descriptor_identity, item.output_index) not in associated_outputs
                      and case.project.state in ("original_bytes_observed", "saved_bytes_observed")):
                    category = "verified_unpublished"
            images.append({"image": len(images) + 1, "request": request_labels.get(item.request_id if item else candidate.request_id),
                "output": item.output_index if item else candidate.output_index,
                "role": item.role if item else "candidate_reference", "inspection": status,
                "available_for_inspection": available, "format": item.image_format if available else None,
                "width": item.width if available else None, "height": item.height if available else None,
                "observed_bytes": item.byte_count if available else None,
                "candidate_association": (associations if candidate else "saved_reference_needs_reconciliation"
                                          if saved_references.get(key) else "related_recorded_candidate"
                                          if item and (item.request_id, item.descriptor_identity, item.output_index) in associated_outputs
                                          else "no_recorded_candidate"),
                "retention_class": category})
    # No orphan filename/root key is displayed, including filenames with secrets.
    for _ in inventory.orphans[:max(0, 64 - len(images))]:
        images.append({"image": len(images) + 1, "request": None, "output": None, "role": "unindexed",
            "inspection": "unverified", "available_for_inspection": False, "format": None, "width": None,
            "height": None, "observed_bytes": None, "candidate_association": "unverified",
            "retention_class": "orphan_or_incomplete"})
    inspection_available = any(i["available_for_inspection"] for i in images)
    return {"case_revision": case.revision, "status": "inspect_only", "execution_available": False,
            "journal": {"checkpoint": journal.observations[-1].checkpoint if journal else "unavailable",
                        "revision": journal.revision if journal else None, "authenticity": "unverified"},
            "project": case.project.state, "requests": requests, "images": images,
            "candidate_association": associations, "matched_candidates": reconciliation.matched if reconciliation else 0,
            "expected_candidates": reconciliation.expected if reconciliation else 0,
            "save_outcome": save, "save_uncertain": (save != "saved" or associations != "exact"
                                                       or case.project.state != "saved_bytes_observed"),
            "external_execution": "unknown" if case.unknown_requests or journal is None else "observed_results",
            "inventory": ("not fully inspected" if inventory.truncated or inventory.errors
                          or "local_file_identities_not_fully_inspected" in case.reasons
                          or any(f[2] == "budget_exceeded" for f in inventory.files) else "bounded scope inspected"),
            "classifications": {"evidence_available_for_human_inspection": inspection_available,
                "evidence_needing_further_reconciliation": bool(case.reasons),
                "candidate_already_associated": bool(reconciliation and reconciliation.matched),
                "recovery_request_needs_fresh_authorization": True, "evidence_currently_unsafe_to_associate": True},
            "blockers": list(case.reasons), "allowed_decisions": list(DECISIONS),
            "manual_checks": ["Verify journal authenticity independently", "Reconcile the original Project and unique Illustration IDs",
                "Inspect recorded images and incomplete inventory within approved roots", "Check saved Candidate associations and persistence uncertainty",
                "Resolve external execution without automatic resubmission", "Obtain fresh source, review, session and publication authorization"],
            "retention": _retention(case, images), "attachment_allowed": False,
            "publication_allowed": False, "cleanup_allowed": False}


class HumanRecoveryReviewOwner:
    """One bounded case and one non-executable review intention, outside jobs.

    Every decision re-reads evidence first. Refresh replaces the private carrier
    on any change; even equal copied cases cannot decide for the current case.
    No production SessionRuntime, widget, mailbox or GenerationJob integration.
    """
    execution_available = False

    def __init__(self, journal_root, filename, selected_project_root, selected_relative_path,
                 asset_roots=(), *, context=None, max_entries=64, max_file_bytes=32 * 1024 * 1024,
                 expected_revision=None, expected_digest=None, original_project_sha256=None, characterization=False):
        if characterization is not True:
            raise ValueError("execution_unavailable")
        if type(max_entries) is not int or not 1 <= max_entries <= 64:
            raise ValueError("invalid_budget")
        if type(max_file_bytes) is not int or not 1 <= max_file_bytes <= 32 * 1024 * 1024:
            raise ValueError("invalid_budget")
        asset_roots = tuple(asset_roots)
        if (type(journal_root) is not journal_owner.ApprovedRoot
                or (selected_project_root is not None and type(selected_project_root) is not journal_owner.ApprovedRoot)
                or any(type(r) is not journal_owner.ApprovedRoot for r in asset_roots)
                or len(asset_roots) > 7 or len({r.key for r in asset_roots}) != len(asset_roots)):
            raise ValueError("invalid_allowlist")
        journal_owner._relative(filename)
        journal_owner._relative(selected_relative_path)
        if original_project_sha256 is not None:
            journal_owner._digest(original_project_sha256)
        if not filename.endswith(".json"):
            raise ValueError("invalid_journal_filename")
        context = context if context is not None else RecoveryContext()
        if type(context) is not RecoveryContext:
            raise ValueError("invalid_recovery_context")
        self._spec = (journal_root, filename, selected_project_root, selected_relative_path, asset_roots,
                      max_entries, max_file_bytes, expected_revision, expected_digest, original_project_sha256)
        self._lock = threading.RLock()
        self._case = _observe(self._spec, context, 1)
        self._intention = None
        self._closed = False

    def case_for_characterization(self):
        with self._lock:
            return self._case

    def _refresh_locked(self, context):
        current = _observe(self._spec, context, self._case.revision)
        if current != self._case:
            self._case = replace(current, revision=self._case.revision + 1)
            self._intention = None
            return True
        return False

    def refresh_for_characterization(self, *, context=None):
        with self._lock:
            if self._closed:
                raise ValueError("review_owner_closed")
            context = self._case.context if context is None else context
            if type(context) is not RecoveryContext:
                raise ValueError("invalid_recovery_context")
            self._refresh_locked(context)
            return self._case

    def projection_for_characterization(self):
        with self._lock:
            self._refresh_locked(self._case.context)
            result = recovery_projection(self._case)
            result["decision"] = "closed" if self._closed else self._intention or "undecided"
            return result

    def decide_for_characterization(self, case, decision):
        with self._lock:
            if self._closed:
                return RecoveryDecision("closed", self._case.revision)
            if type(decision) is not str or decision not in DECISIONS:
                return RecoveryDecision("unsupported_decision", self._case.revision)
            changed = self._refresh_locked(self._case.context)
            if changed or case is not self._case:
                return RecoveryDecision("stale_case", self._case.revision)
            if decision == "inspect":
                return RecoveryDecision("inspection_only", case.revision, self._intention)
            if self._intention is not None:
                return RecoveryDecision("repeated" if self._intention == decision else "conflicting_decision",
                                        case.revision, self._intention)
            self._intention = decision
            return RecoveryDecision("review_intention_recorded", case.revision, decision)

    def close(self):
        with self._lock:
            self._closed = True
            self._intention = None
