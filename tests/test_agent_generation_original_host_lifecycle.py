"""C2B-8D-19A original-host lifecycle; non-executing characterization only."""

from dataclasses import replace
import threading

from core.project import Project
from ui.project_agent_session_pump import ProjectAgentSessionRuntime
from ui.agent_generation_original_host_lifecycle import (
    GenerationWorkerResultObservation,
    OriginalHostGenerationLifecycle,
    _HostEvidence,
)
from test_agent_generation_executor_handoff import ready, start


def _project(name):
    return Project(project_metadata={"name": name})


def _bound_runtime(project=None, path=r"C:\PG\selected.json"):
    runtime = ProjectAgentSessionRuntime()
    project = project or _project("initial")
    assert runtime._generation_original_host_lifecycle is None
    assert runtime.synchronize_target(project, path)
    assert runtime._generation_original_host_lifecycle is None
    assert runtime.opt_in_generation_original_host_lifecycle_for_characterization(
        project, path,
    ) == "bound_non_executing"
    return runtime, project


def test_exact_binding_survives_same_target_reruns_and_all_gates_stay_closed():
    runtime, project = _bound_runtime()
    owner = runtime._generation_original_host_lifecycle
    assert type(owner) is OriginalHostGenerationLifecycle
    before = runtime.inspect_generation_original_host_readiness()
    assert before["lifecycle_state"] == "bound_non_executing"
    assert before["pairing"] == "unpaired"
    assert before["job_claim"] == "not_issued"

    for _ in range(4):
        assert runtime.synchronize_target(project, r"C:\PG\selected.json") == runtime.mailbox.target_epoch
        assert runtime._generation_original_host_lifecycle is owner
        assert runtime.inspect_generation_original_host_readiness() == before

    assert runtime.generation_worker_correlation_for_characterization().status == "claim_not_issued"
    assert before["execution_available"] is False
    assert before["protected_storage_available"] is False
    assert before["promotion_available"] is False
    assert before["candidate_publication_allowed"] is False
    assert before["project_save_allowed"] is False
    assert before["recovery_execution_allowed"] is False
    assert before["human_start_allowed"] is False
    assert before["cleanup_allowed"] is False
    assert before["authorship"] == "unverified"
    runtime.close()
    assert owner.readiness()["lifecycle_state"] == "closed"


def test_project_replacement_switch_away_back_and_save_as_never_resurrect_old_binding():
    runtime, project_a = _bound_runtime(path=r"C:\PG\a.json")
    owner_a = runtime._generation_original_host_lifecycle

    project_b = _project("b")
    runtime.synchronize_target(project_b, r"C:\PG\b.json")
    owner_b = runtime._generation_original_host_lifecycle
    assert owner_b is not owner_a
    assert owner_a.readiness()["lifecycle_state"] == "closed"

    runtime.synchronize_target(project_a, r"C:\PG\a.json")
    owner_a_again = runtime._generation_original_host_lifecycle
    assert owner_a_again is not owner_a
    assert owner_a_again is not owner_b

    runtime.synchronize_target(project_a, r"C:\PG\a-save-as.json")
    owner_saved_as = runtime._generation_original_host_lifecycle
    assert owner_saved_as is not owner_a_again
    assert owner_a_again.readiness()["lifecycle_state"] == "closed"
    runtime.close()


def test_pairing_generation_and_registration_replacement_rotate_lifecycle():
    runtime, project = _bound_runtime()
    owner_unpaired = runtime._generation_original_host_lifecycle
    offer = runtime.arm_local_pairing()
    assert offer.status == "armed"
    pair = runtime._registry.claim_pairing(
        offer.bootstrap.process_incarnation,
        offer.bootstrap.route_id,
        offer.bootstrap.capability,
    )
    assert pair.status == "paired"
    runtime.synchronize_target(project, r"C:\PG\selected.json")
    owner_paired = runtime._generation_original_host_lifecycle
    assert owner_paired is not owner_unpaired
    assert owner_unpaired.readiness()["lifecycle_state"] == "closed"

    assert runtime._registry.release_pairing(pair.paired_route).status == "released"
    runtime.synchronize_target(project, r"C:\PG\selected.json")
    owner_released = runtime._generation_original_host_lifecycle
    assert owner_released is not owner_paired
    assert owner_paired.readiness()["lifecycle_state"] == "closed"

    old_registration = runtime._registration
    assert old_registration.unregister() is True
    runtime._registration = runtime._registry.register_session(runtime.mailbox)
    runtime.synchronize_target(project, r"C:\PG\selected.json")
    owner_new_route = runtime._generation_original_host_lifecycle
    assert owner_new_route is not owner_released
    assert owner_released.readiness()["lifecycle_state"] == "closed"
    runtime.close()


def test_worker_results_are_exactly_correlated_bounded_and_non_authoritative():
    values = ready()
    runtime, _, state, *_ = values
    try:
        accepted = start(values)
        assert accepted.status == "characterized_acceptance"
        assert runtime.opt_in_generation_original_host_lifecycle_for_characterization(
            state["project"], state["current_project_path"],
        ) == "bound_non_executing"
        owner = runtime._generation_original_host_lifecycle
        correlation = runtime.generation_worker_correlation_for_characterization()
        assert correlation.status == "correlation_only"
        snapshot = runtime.generation_jobs.snapshot(correlation.job_id)

        observation = GenerationWorkerResultObservation(
            lifecycle_generation=correlation.lifecycle_generation,
            job_id=correlation.job_id,
            claim_id=correlation.claim_id,
            manifest_identity=correlation.manifest_identity,
            request_index=0,
            sequence=1,
            kind="submitted",
        )
        assert runtime.observe_generation_worker_result_for_characterization(
            observation,
        ) == "observed_non_authoritative"
        assert runtime.generation_jobs.snapshot(correlation.job_id) == snapshot

        foreign_claim = replace(observation, claim_id="f" * 32)
        foreign_generation = replace(observation, lifecycle_generation="e" * 32)
        foreign_manifest = replace(observation, manifest_identity="d" * 64)
        assert runtime.observe_generation_worker_result_for_characterization(
            foreign_claim,
        ) == "stale_non_authoritative"
        assert runtime.observe_generation_worker_result_for_characterization(
            foreign_generation,
        ) == "stale_non_authoritative"
        assert runtime.observe_generation_worker_result_for_characterization(
            foreign_manifest,
        ) == "stale_non_authoritative"

        foreign_values = ready()
        foreign_runtime, _, foreign_state, *_ = foreign_values
        try:
            assert start(foreign_values).status == "characterized_acceptance"
            assert foreign_runtime.opt_in_generation_original_host_lifecycle_for_characterization(
                foreign_state["project"], foreign_state["current_project_path"],
            ) == "bound_non_executing"
            foreign_correlation = foreign_runtime.generation_worker_correlation_for_characterization()
            foreign_observation = replace(
                observation,
                lifecycle_generation=foreign_correlation.lifecycle_generation,
                job_id=foreign_correlation.job_id,
                claim_id=foreign_correlation.claim_id,
                manifest_identity=foreign_correlation.manifest_identity,
            )
            assert runtime.observe_generation_worker_result_for_characterization(
                foreign_observation,
            ) == "stale_non_authoritative"
        finally:
            foreign_runtime.close()

        previous_generation = correlation.lifecycle_generation
        replacement = _project("replacement")
        runtime.synchronize_target(replacement, state["current_project_path"])
        assert owner.readiness()["lifecycle_state"] == "closed"
        late = replace(observation, lifecycle_generation=previous_generation)
        assert runtime.observe_generation_worker_result_for_characterization(
            late,
        ) == "stale_non_authoritative"
        assert runtime.generation_jobs.snapshot(correlation.job_id)["registered_count"] == 0
        assert runtime.generation_jobs.snapshot(correlation.job_id)["save_state"] == "not_attempted"
    finally:
        runtime.close()


def test_runtime_close_publishes_revocation_while_callback_is_blocked():
    runtime, _ = _bound_runtime()
    owner = runtime._generation_original_host_lifecycle
    callback_entered = threading.Event()
    callback_release = threading.Event()
    result = []

    def callback():
        callback_entered.set()
        assert callback_release.wait(5)

    thread = threading.Thread(
        target=lambda: result.append(owner._observe_non_io_callback_for_characterization(callback)),
    )
    thread.start()
    assert callback_entered.wait(5)
    runtime.close()
    assert owner.readiness()["lifecycle_state"] == "revocation_requested"
    assert runtime.inspect_generation_original_host_readiness()["lifecycle_state"] == "closed"
    callback_release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert result == ["revoked_non_authoritative"]
    assert owner.readiness()["lifecycle_state"] == "closed"
    assert runtime.synchronize_target(_project("after-close"), r"C:\PG\after.json") is None
    assert runtime._generation_original_host_lifecycle is None


def test_project_replacement_revokes_blocked_callback_without_waiting_or_resurrection():
    runtime, _ = _bound_runtime()
    old_owner = runtime._generation_original_host_lifecycle
    entered = threading.Event()
    release = threading.Event()
    result = []

    def callback():
        entered.set()
        assert release.wait(5)

    worker = threading.Thread(
        target=lambda: result.append(old_owner._observe_non_io_callback_for_characterization(callback)),
    )
    worker.start()
    assert entered.wait(5)

    replacement = _project("new-target")
    runtime.synchronize_target(replacement, r"C:\PG\new.json")
    new_owner = runtime._generation_original_host_lifecycle
    assert new_owner is not old_owner
    assert old_owner.readiness()["lifecycle_state"] == "revocation_requested"
    assert new_owner.readiness()["lifecycle_state"] == "bound_non_executing"

    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert result == ["revoked_non_authoritative"]
    assert old_owner.readiness()["lifecycle_state"] == "closed"
    runtime.close()


def test_reentrant_close_from_observation_does_not_deadlock_or_resurrect():
    runtime, _ = _bound_runtime()
    owner = runtime._generation_original_host_lifecycle
    observations = []

    def callback():
        runtime.close()
        observations.append(runtime.inspect_generation_original_host_readiness()["lifecycle_state"])

    assert owner._observe_non_io_callback_for_characterization(callback) == "revoked_non_authoritative"
    assert observations == ["closed"]
    assert owner.readiness()["lifecycle_state"] == "closed"
    assert runtime._generation_original_host_lifecycle is None


def test_protected_root_capacity_readiness_checks_exact_references_without_io():
    runtime, _ = _bound_runtime()
    owner = runtime._generation_original_host_lifecycle

    from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
    from core.generation_windows_protected_storage import WindowsProtectedRootCharacterization

    purposes = (
        "private_journal", "temporary_containment", "retained_uncertain",
        "promoted_assets", "selected_project_json",
    )
    roots = {}
    for purpose in purposes:
        root = object.__new__(WindowsProtectedRootCharacterization)
        root._purpose = purpose
        root._closed = False
        roots[purpose] = root
    capacity = object.__new__(WindowsProtectedStorageAdmissionCharacterization)
    capacity._roots = dict(roots)
    capacity._closed = False
    capacity._invalid = False

    assert runtime.inspect_generation_original_host_readiness(
        purpose_roots=roots, capacity_owner=capacity,
    )["protected_dependencies"]["root_capacity_identity"] == "matched_reference_only"
    readiness = runtime.inspect_generation_original_host_readiness()
    deps = readiness["protected_dependencies"]
    assert deps["root_capacity_identity"] == "matched_reference_only"
    assert deps["asset_writer"] == "absent"
    assert deps["journal_writer"] == "absent"
    assert deps["promotion_writer"] == "absent"
    assert deps["native_acl_or_identity_revalidated"] is False

    mismatched = dict(roots)
    mismatched["promoted_assets"] = roots["temporary_containment"]
    assert runtime.inspect_generation_original_host_readiness(
        purpose_roots=mismatched, capacity_owner=capacity,
    )["protected_dependencies"]["root_capacity_identity"] == "mismatched"
    assert owner.readiness()["protected_dependencies"]["root_capacity_identity"] == "mismatched"
    runtime.close()


def test_duplicate_or_forged_lifecycle_evidence_cannot_construct_owner():
    runtime, project = _bound_runtime()
    owner = runtime._generation_original_host_lifecycle
    assert owner is not None
    try:
        OriginalHostGenerationLifecycle(None)
    except ValueError as exc:
        assert str(exc) == "original_host_evidence_required"
    else:
        raise AssertionError("direct lifecycle construction unexpectedly succeeded")

    with runtime._publication_gate:
        evidence, reason = runtime._capture_generation_host_evidence_locked(
            project, r"C:\PG\selected.json", runtime.target_tracker._epoch,
        )
    assert reason is None
    assert type(evidence) is _HostEvidence
    try:
        OriginalHostGenerationLifecycle._create_for_runtime(runtime, evidence)
    except ValueError as exc:
        assert str(exc) == "original_runtime_binding_required"
    else:
        raise AssertionError("duplicate lifecycle creation unexpectedly succeeded")
    assert runtime._generation_original_host_lifecycle is owner
    runtime.close()


def test_foreign_process_evidence_cannot_bind_to_the_original_runtime():
    runtime = ProjectAgentSessionRuntime()
    project = _project("process-bound")
    path = r"C:\PG\selected.json"
    assert runtime.synchronize_target(project, path)
    with runtime._publication_gate:
        evidence, reason = runtime._capture_generation_host_evidence_locked(
            project, path, runtime.target_tracker._epoch,
        )
    assert reason is None
    assert evidence.process_incarnation == runtime._registry.process_incarnation

    foreign_process = replace(evidence, process_incarnation="foreign-process")
    try:
        OriginalHostGenerationLifecycle._create_for_runtime(runtime, foreign_process)
    except ValueError as exc:
        assert str(exc) == "original_runtime_binding_required"
    else:
        raise AssertionError("foreign process evidence unexpectedly bound")
    assert runtime._generation_original_host_lifecycle is None
    runtime.close()


def test_late_worker_observation_after_session_teardown_is_non_authoritative():
    values = ready()
    runtime, _, state, *_ = values
    try:
        assert start(values).status == "characterized_acceptance"
        assert runtime.opt_in_generation_original_host_lifecycle_for_characterization(
            state["project"], state["current_project_path"],
        ) == "bound_non_executing"
        correlation = runtime.generation_worker_correlation_for_characterization()
        observation = GenerationWorkerResultObservation(
            lifecycle_generation=correlation.lifecycle_generation,
            job_id=correlation.job_id,
            claim_id=correlation.claim_id,
            manifest_identity=correlation.manifest_identity,
            request_index=0,
            sequence=1,
            kind="failed",
        )
        runtime.close()
        assert runtime.observe_generation_worker_result_for_characterization(
            observation,
        ) == "stale_non_authoritative"
    finally:
        runtime.close()

def test_concurrent_close_and_binding_validation_cannot_resurrect_lifecycle():
    runtime, project = _bound_runtime()
    owner = runtime._generation_original_host_lifecycle
    validation_entered = threading.Event()
    validation_release = threading.Event()
    close_started = threading.Event()
    outcomes = []
    original_reconcile = owner._reconcile_evidence

    def paused_reconcile(evidence):
        validation_entered.set()
        assert validation_release.wait(5)
        return original_reconcile(evidence)

    owner._reconcile_evidence = paused_reconcile
    sync_thread = threading.Thread(
        target=lambda: outcomes.append(runtime.synchronize_target(project, r"C:\PG\selected.json")),
    )
    sync_thread.start()
    assert validation_entered.wait(5)

    def close_runtime():
        close_started.set()
        runtime.close()

    close_thread = threading.Thread(target=close_runtime)
    close_thread.start()
    assert close_started.wait(5)
    validation_release.set()
    sync_thread.join(5)
    close_thread.join(5)
    assert not sync_thread.is_alive()
    assert not close_thread.is_alive()
    assert outcomes
    assert owner.readiness()["lifecycle_state"] == "closed"
    assert runtime._generation_original_host_lifecycle is None
    assert runtime.synchronize_target(_project("no-resurrection"), r"C:\PG\other.json") is None

def test_uncertain_lifecycle_is_terminal_for_same_binding():
    runtime, project = _bound_runtime()
    owner = runtime._generation_original_host_lifecycle

    def failing_observation():
        raise RuntimeError("bounded characterization failure")

    assert owner._observe_non_io_callback_for_characterization(
        failing_observation,
    ) == "revoked_non_authoritative"
    assert owner.readiness()["lifecycle_state"] == "uncertain"
    runtime.synchronize_target(project, r"C:\PG\selected.json")
    assert runtime._generation_original_host_lifecycle is owner
    assert runtime.inspect_generation_original_host_readiness()["lifecycle_state"] == "uncertain"
    runtime.close()
