"""Original-host, injected-wire composition for offline HTTP characterization.

This module only assembles the existing bounded transports, Journal owner and
Executor. It does not register a worker, provide a default network wire, or
enable production execution.
"""
from threading import Lock

from core.comfy_http_history import (
    PromptHTTPHistoryTransport,
    stdlib_history_wire_for_characterization,
)
from core.comfy_http_submission import (
    PromptHTTPPolicy,
    PromptHTTPSubmissionTransport,
    stdlib_prompt_wire_for_characterization,
)
from ui.agent_generation_comfy_executor import (
    ComfyExecutorAdapter,
    history_result_provider_for_characterization,
)
from ui.agent_generation_executor_handoff import deliver_executor_event_for_characterization
from ui.agent_generation_executor_inbox import GenerationExecutorInbox
from ui.agent_generation_executor_journal import GenerationExecutorJournalIntent
from ui.agent_generation_job import GenerationJobRegistry
from ui.project_agent_session_pump import ProjectAgentSessionRuntime


class OfflineHTTPExecutorComposition:
    """Small host-only handle over the existing offline characterization owners."""

    execution_available = False
    protected_storage_available = False
    promotion_available = False
    candidate_publication_allowed = False
    authorship = "unverified"

    def __init__(self, adapter, submission_transport, history_transport, history_reader, history_lock):
        self._adapter = adapter
        self._submission_transport = submission_transport
        self._history_transport = history_transport
        self._history_reader = history_reader
        self._history_read_lock = history_lock

    def accept_offer_for_characterization(self, offer):
        return self._adapter.accept_and_run_for_characterization(offer)

    def advance_for_characterization(self):
        return self._adapter.advance_for_characterization()

    def observation_for_characterization(self):
        return self._adapter.observation()

    def read_current_history_for_characterization(self):
        """Explicitly GET the current accepted prompt; never resubmit POST /prompt."""
        adapter = self._adapter
        # Preserve the adapter's Journal/send/result serialization order:
        # adapter advance lock -> History read lock -> release read lock ->
        # deliver through the existing result gate while the adapter lock is
        # still held. This fences an explicit GET racing the initial GET or
        # another result transition without holding host/job/inbox locks.
        if not adapter._journal_advance_lock.acquire(blocking=False):
            return self._adapter.observation()
        try:
            if not self._history_read_lock.acquire(blocking=False):
                return adapter.observation()
            try:
                prepared, prompt_id = adapter._active_prepared, adapter._active_prompt
                if (adapter._phase != "awaiting_remote_result" or prepared is None
                        or prompt_id is None):
                    return adapter.observation()
                result = self._history_reader(prepared, prompt_id)
            finally:
                self._history_read_lock.release()
            return adapter.receive_result_for_characterization(result)
        finally:
            adapter._journal_advance_lock.release()

def compose_http_executor_for_characterization(
        state, runtime, journal_intent_owner, *, submission_wire_factory,
        history_wire_factory, policy=PromptHTTPPolicy(), characterization=False):
    """Bind injected HTTP contracts to the exact original host and Journal owner.

    The standard-library HTTP factories are deliberately rejected here: this
    composition is offline-only even though those transport wires exist for
    separately reviewed characterization. Each transport still derives its
    destination only from the per-request frozen ComfyUI origin.
    """
    if (characterization is not True or type(characterization) is not bool
            or type(state) is not dict or type(runtime) is not ProjectAgentSessionRuntime
            or type(journal_intent_owner) is not GenerationExecutorJournalIntent
            or type(runtime.generation_jobs) is not GenerationJobRegistry
            or type(runtime._generation_executor_inbox) is not GenerationExecutorInbox
            or not runtime.generation_jobs._characterization
            or not runtime._generation_executor_inbox._characterization
            or runtime._closed or runtime._registration is None
            or runtime._generation_publication_origin is not None
            or journal_intent_owner._state is not state
            or journal_intent_owner._runtime is not runtime
            or journal_intent_owner._closed
            or journal_intent_owner._state_name != "unbound"
            or not callable(submission_wire_factory) or not callable(history_wire_factory)
            or submission_wire_factory is stdlib_prompt_wire_for_characterization
            or history_wire_factory is stdlib_history_wire_for_characterization
            or type(policy) is not PromptHTTPPolicy):
        raise ValueError("offline_http_executor_unavailable")
    root = journal_intent_owner._journal_root(journal_intent_owner._journal_owner)
    if root.identity != journal_intent_owner._journal_root_identity:
        raise ValueError("offline_http_executor_unavailable")
    root.check()

    # One policy object keeps endpoint timeouts consistent for POST and GET.
    submission = PromptHTTPSubmissionTransport(
        wire_factory=submission_wire_factory, policy=policy, characterization=True)
    history = PromptHTTPHistoryTransport(
        wire_factory=history_wire_factory, policy=policy, characterization=True)
    read_history = history_result_provider_for_characterization(history)
    history_lock = Lock()

    def serialized_history_provider(prepared, prompt_id):
        with history_lock:
            return read_history(prepared, prompt_id)

    adapter = ComfyExecutorAdapter(
        runtime.generation_jobs,
        runtime._generation_executor_inbox,
        fake_transport=submission,
        fake_result_provider=serialized_history_provider,
        host_event_sink=lambda event: deliver_executor_event_for_characterization(
            state, runtime, event),
        characterization=True,
        journal_intent_owner=journal_intent_owner,
    )
    composed = OfflineHTTPExecutorComposition(
        adapter, submission, history, read_history, history_lock)
    return composed
