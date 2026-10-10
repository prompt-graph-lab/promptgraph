"""C2B-6 original-host characterization. No production call site or Start.

Existing Gallery ingestion is the sole router. Host supplies its existing app
factory/appender and exact-object/path save callback. Files, factory work and
JSON persistence run outside job/inbox locks; disk I/O also releases host gates.
"""
from contextlib import contextmanager, nullcontext
import copy
from dataclasses import dataclass
import json
from pathlib import Path
import threading

from core.candidate_record_normalization import _normalize_candidate_records
from core.gallery_generation import ingest_gallery_generation_outputs, resolve_gallery_generation_result_target
from core.generation_output_promotion import DurableGenerationAssets
from core.io import _project_to_serializable_data
from ui.agent_generation_executor_inbox import ExecutionEnvelope
from ui.agent_generation_executor_handoff import GenerationPublicationOrigin
from ui.agent_generation_job import JobRequest, _PROCESS_INCARNATION
from ui.project_agent_session_pump import ProjectAgentSessionRuntime


@dataclass(frozen=True)
class PublicationReceipt:
    request_index: int
    promotion_state: str
    registration_state: str
    registered_count: int = 0


class GenerationCandidatePublication:
    execution_available = False

    @classmethod
    def create_for_characterization(cls, state, runtime, envelope, *, approved_directory,
                                    candidate_factory, candidate_appender, save_project,
                                    characterization=False):
        if (characterization is not True or type(runtime) is not ProjectAgentSessionRuntime
                or not runtime.generation_jobs._characterization
                or not runtime._generation_executor_inbox._characterization):
            raise ValueError("execution_unavailable")
        origin = runtime._generation_publication_origin
        if (type(envelope) is not ExecutionEnvelope or type(origin) is not GenerationPublicationOrigin
                or origin.envelope is not envelope or origin.project is None
                or origin.source_snapshot is None or not origin.path
                or not all(callable(c) for c in (candidate_factory, candidate_appender, save_project))):
            raise ValueError("original_host_required")
        options = json.loads(envelope.manifest.host_config_json)
        # Explicit host approval must exactly name the original frozen output
        # configuration, never a path recomputed from the currently active UI.
        if (type(approved_directory) is not str or not Path(approved_directory).is_absolute()
                or options.get("output_directory") != approved_directory):
            raise ValueError("destination_not_approved")
        owner = cls(state, runtime, envelope, candidate_factory, candidate_appender, save_project,
                    _factory=_FACTORY)
        with owner._authority() as current:
            if not current:
                raise ValueError("stale_original_host")
            if getattr(runtime, "_generation_candidate_publication", None) is not None:
                raise ValueError("publication_owner_exists")
            runtime._generation_candidate_publication = owner
        # Allocation is pinned even if it fails. No implicit recovery/retry.
        owner._assets = DurableGenerationAssets.create_for_characterization(
            approved_directory, characterization=True)
        with owner._authority() as current:
            if not current:
                raise ValueError("stale_original_host")
        return owner

    def __init__(self, state, runtime, envelope, factory, appender, save, *, _factory=None):
        if _factory is not _FACTORY:
            raise ValueError("host_publication_factory_required")
        self._state, self._runtime, self._envelope = state, runtime, envelope
        self._factory, self._appender, self._save = factory, appender, save
        self._origin = runtime._generation_publication_origin
        self._expected = copy.deepcopy(self._origin.source_snapshot)
        self._assets = None
        self._lock = threading.Lock()
        self._busy = False
        self._records, self._evidence = {}, {}
        self._save_state = "not_attempted"

    @contextmanager
    def _authority(self, index=None, remote=None, local=None, *, source=True, _gate_held=False):
        runtime, envelope = self._runtime, self._envelope
        jobs, inbox = runtime.generation_jobs, runtime._generation_executor_inbox
        with nullcontext() if _gate_held else runtime._publication_gate:
            route = (runtime._registry._record_for_registration(runtime._registration)
                     if not runtime._closed and runtime._registration is not None else None)
            if route is None:
                yield False
                return
            with route.operation_lock:
                epoch = runtime._synchronize_target_locked(self._state.get("project"),
                                                          self._state.get("current_project_path", ""))
                available, pairing = runtime._registration.inspect_pairing_generation()
                with jobs._lock:
                    jobs._cleanup_locked(jobs._clock())
                    job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                    with inbox._lock:
                        current = bool(available and jobs._characterization and inbox._characterization
                            and job is not None and job.binding == envelope.binding
                            and job.binding.session_id == jobs._session_incarnation
                            and job.binding.process_incarnation == _PROCESS_INCARNATION
                            and job.binding.target_epoch == epoch
                            and (job.binding.target_epoch, job.binding.activation_id) == jobs._target
                            and type(pairing) is int and job.binding.pairing_generation == pairing
                            and job.state not in {"expired", "cancelled", "unavailable",
                                "stale_target_outputs_not_registered", "submission_outcome_unknown"}
                            and inbox._envelope is envelope and inbox._state == "accepted" and not inbox._closed
                            and runtime._generation_publication_origin is self._origin
                            and self._origin.envelope is envelope
                            and self._state.get("project") is self._origin.project
                            and self._state.get("current_project_path", "") == self._origin.path)
                        if current and index is not None:
                            request = envelope.manifest.requests[index]
                            current = bool(job.request_states[index] == "awaiting_host_registration"
                                and job.requests[index] == JobRequest(request.request_id, request.illustration_id,
                                                                     request.run_index, request.workflow_identity)
                                and remote is not None and local is not None and local.state == "verified"
                                and (remote.job_id, remote.claim_id, remote.manifest_identity, remote.request_id,
                                     remote.request_index, remote.workflow_identity) ==
                                    (envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity,
                                     request.request_id, index, request.workflow_identity)
                                and (local.job_id, local.claim_id, local.manifest_identity, local.request_id,
                                     local.request_index, local.workflow_identity, local.remote_receipt_identity,
                                     local.prompt_id) ==
                                    (remote.job_id, remote.claim_id, remote.manifest_identity, remote.request_id,
                                     index, remote.workflow_identity, remote.identity, remote.prompt_id)
                                and remote.execution_succeeded
                                and local.verified_count == local.downloaded_count == len(remote.images)
                                and job.outputs[index] == local.verified_count
                                and tuple(i.descriptor_identity for i in local.images) == tuple(i.identity for i in remote.images)
                                and any(e.progress.request_index == index and e.progress.kind == "outputs_ready"
                                    and e.outputs.receipt_id == local.identity[:32]
                                    and e.outputs.output_count == local.verified_count for e in inbox._events.values()))
                # In-memory equality follows the serialized full-app host writer
                # contract, including prompts, Modules, routes and source images.
                if current and source:
                    current = self._origin.project == self._expected
                yield current  # no job/inbox/mailbox locks cross host mutation

    def publish_for_characterization(self, store, remote, local):
        index = getattr(local, "request_index", -1)
        if type(index) is not int or not 0 <= index < len(self._envelope.manifest.requests):
            return PublicationReceipt(-1, "not_attempted", "invalid_receipt")
        with self._lock:
            previous = self._records.get(index)
            if previous is not None:
                evidence = self._evidence[index]
                return previous if all(a is b for a, b in zip(evidence, (store, remote, local))) else PublicationReceipt(
                    index, "not_attempted", "receipt_conflict")
            if self._busy or self._save_state != "not_attempted":
                return PublicationReceipt(index, "not_attempted", "publication_busy")
            self._busy = True
            # One-shot attempt linearizes here, before any callbacks/I/O.
            self._records[index] = PublicationReceipt(index, "not_attempted", "publication_in_progress")
            self._evidence[index] = (store, remote, local)
        promotion = "not_attempted"
        mutation_started, observed_count = False, 0
        receipt = PublicationReceipt(index, promotion, "stale_original_host")
        try:
            with self._authority(index, remote, local) as current:
                if not current:
                    return receipt
            images = self._assets.promote_for_characterization(store, self._envelope, remote, local)
            promotion = "promoted"
            request = self._envelope.manifest.requests[index]
            row = json.loads(self._origin.review_json)["requests"][index]
            target = resolve_gallery_generation_result_target(self._expected, request.illustration_id)["target_line"]
            records = []
            for ordinal, promoted in enumerate(images, 1):
                # Existing app factory keeps its schema/timestamp/path behavior.
                record = self._factory(promoted.path, target, "agent_generation", request.run_index)
                if type(record) is not dict:
                    raise ValueError("candidate_factory_failed")
                record = copy.deepcopy(record)
                prompts = row["prompts"]
                def prompt(role):
                    values = [p["text"] for p in prompts if p["role"] == role]
                    return values[0] if values and len(set(values)) == 1 else None
                seed_values = [s["value"] for s in row["seeds"] if s["input_key"] == "seed"]
                record.update(path=promoted.path, prompt_text=prompt("positive"), negative_prompt=prompt("negative"),
                    candidate_prompt_source="frozen_execution", seed=seed_values[0] if len(seed_values) == 1 else None,
                    seed_mode="frozen_execution", run_index=request.run_index,
                    generation_provenance={"job_id": self._envelope.job_id,
                        "manifest_identity": self._envelope.manifest.manifest_identity,
                        "request_id": request.request_id, "request_index": index,
                        "illustration_id": request.illustration_id, "run_index": request.run_index,
                        "workflow_identity": request.workflow_identity, "prompt_id": remote.prompt_id,
                        "remote_receipt_identity": remote.identity, "local_receipt_identity": local.identity,
                        "descriptor_identity": promoted.image.descriptor_identity,
                        "content_sha256": promoted.image.content_sha256, "output_index": ordinal,
                        "prompts": prompts, "seeds": row["seeds"], "parameters": row["parameters"],
                        "prompt_available": prompt("positive") is not None,
                        "seed_available": len(seed_values) == 1})
                records.append(record)
            history_snapshot = copy.deepcopy(self._expected)
            normalized_existing = _normalize_candidate_records(target.generated_candidates)
            # Keep the expected-current snapshot detached even for nested
            # provenance. The existing app normalizer intentionally uses
            # shallow record copies; sharing those aliases would hide later
            # source metadata edits from this owner's freshness comparison.
            normalized_new = _normalize_candidate_records(copy.deepcopy(records))
            self._assets.revalidate_for_characterization(images)
            store.revalidate_for_characterization(local)
            by_path = {r["path"]: r for r in records}
            paths = [i.path for i in images]
            with self._authority(index, remote, local) as current:
                if not current:
                    receipt = PublicationReceipt(index, promotion, "stale_original_host")
                    return receipt
                history = self._state.get("history")
                if type(history) is not list:
                    raise ValueError("history_unavailable")
                history.append(history_snapshot)
                error = False
                actual = resolve_gallery_generation_result_target(self._origin.project,
                    request.illustration_id)["target_line"]
                mutation_started = True
                try:
                    ingest_gallery_generation_outputs(self._origin.project,
                        {"source_line_id": request.illustration_id, "request_id": request.request_id,
                         "run_index": request.run_index}, paths,
                        candidate_factory=lambda path, line, request: by_path[path],
                        candidate_appender=self._appender, resolve_path=lambda p: p,
                        path_exists=lambda p: p in by_path)
                except Exception:
                    error = True  # appender may have mutated before raising
                observed = [r for r in normalized_new if r in actual.generated_candidates]
                # `target` belongs to the detached expected-current snapshot.
                # Advance only this publisher's exact observed Candidate delta;
                # the immutable origin baseline and every other source value
                # remain unchanged for subsequent request/drift checks.
                target.generated_candidates = [*normalized_existing, *observed]
                count = len(observed)
                observed_count = count
                if not count:
                    history.pop()
                elif len(history) > 20:
                    history.pop(0)
                # Compare every other Project value before settling counts.
                intact = self._origin.project == self._expected
                with self._authority(index, remote, local, source=False, _gate_held=True) as still_current:
                    if not still_current or not intact:
                        receipt = PublicationReceipt(index, promotion, "registration_uncertain", count)
                        return receipt
                    result = self._runtime.generation_jobs.publication_for_characterization(
                        self._envelope.job_id, self._envelope.claim_id, binding=self._envelope.binding,
                        request_index=index, registered_count=count)
                status = ("registered" if count == len(records) and not error and result == "accepted"
                          else "registration_uncertain" if error or result != "accepted"
                          else "partially_registered" if count else "registration_failed")
                receipt = PublicationReceipt(index, promotion, status, count)
                return receipt
        except Exception:
            receipt = PublicationReceipt(index, "promotion_failed" if promotion != "promoted" else promotion,
                "registration_uncertain" if mutation_started else "registration_failed", observed_count)
            return receipt
        finally:
            with self._lock:
                self._records[index] = receipt
                self._busy = False

    def save_for_characterization(self):
        with self._lock:
            if self._save_state != "not_attempted":
                return self._save_state
            if self._busy:
                return "publication_busy"
            snapshot = self._runtime.generation_jobs.snapshot(self._envelope.job_id)
            if snapshot.get("state") not in {"completed", "partially_failed"}:
                return "registration_incomplete"
            if any(row["registered_count"] != (self._records[index].registered_count
                    if index in self._records else 0)
                    for index, row in enumerate(snapshot.get("requests", []))):
                return "registration_evidence_missing"
            if any(r.registration_state == "registration_uncertain" for r in self._records.values()):
                return "registration_uncertain"
            self._busy = True
            self._save_state = "saving"  # one-shot, no automatic retry
        outcome = "save_not_authorized"
        attempted = False
        try:
            # Rehash all durable references before attempting persistence.
            for attempt in self._assets._attempts.values():
                if type(attempt) is tuple:
                    self._assets.revalidate_for_characterization(attempt)
            # The established save owner normalizes Modules/attributes/Candidates
            # in place. Characterize those exact changes on a detached clone;
            # do not mistake this legacy normalization for source drift.
            saved_source = copy.deepcopy(self._expected)
            _project_to_serializable_data(saved_source, self._origin.path)
            with self._authority() as current:
                if not current:
                    return outcome
            # Exact captured object/path callback, outside every owner lock.
            try:
                attempted = True
                result = self._save(self._origin.project, self._origin.path,
                                    "Agent generation Candidates registered")
                outcome = "saved" if result is True else "save_failed" if result is False else "save_uncertain"
            except Exception:
                outcome = "save_uncertain"
            self._save_callback_outcome = outcome
            with self._authority(source=False) as current:
                current = current and self._origin.project in (self._expected, saved_source)
                if not current:
                    # A switched/closed host cannot attest its final persistence
                    # state. Preserve actual callback evidence privately.
                    outcome = "save_uncertain"
                else:
                    status = self._runtime.generation_jobs.save_for_characterization(
                        self._envelope.job_id, self._envelope.claim_id,
                        binding=self._envelope.binding, outcome=outcome)
                    if status != "accepted":
                        outcome = "save_uncertain"
            return outcome
        except Exception:
            outcome = "save_uncertain" if attempted else "save_not_authorized"
            return outcome
        finally:
            with self._lock:
                self._save_state, self._busy = outcome, False


_FACTORY = object()
