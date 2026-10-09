# Agent Generation review custody

This is the approved custody-first split of Phase 4-B. The paired host supports
`promptgraph_request_generation_review` with explicit `scene_id`, integer
`run_count` 1–5 and a 64-character lowercase hex `expected_plan_id` obtained
from [Generation Preview](agent-generation-preview.md) in the same pairing and
target. Complete arguments are checked before Project capture. The standalone
adapter validates the shape but returns `host_review_unavailable`; it cannot
create proposals. An expected plan ID is a freshness precondition, never an
execution or approval capability.

## Ownership and acceptance

The trusted bridge recomputes the existing bounded Generation Preview and
checks actionable coverage, plan identity and live captured Project content.
The normal-run pump rechecks Preview at publication. Host workflow/config and
Project content changes refuse acceptance; switch, Save As and session closure
also invalidate custody through the existing target epoch. No network request,
download, Candidate append, output directory creation, history or autosave is
performed. Ordinary Preview creates no custody.

`ui/agent_generation_review_custody.py` owns one proposal slot per browser
session independently of Scene Module Swap. It shares only immutable protocol
carriers and bounded JSON helpers with that owner. It has no Apply claim or
generation method. Proposals retain detached safe Preview JSON and bounded
intent/correlation bookkeeping, never a Project, workflow JSON, raw settings,
paths, credentials or image bytes. The envelope is capped at 8 MiB; underlying
Preview limits remain 100 planned requests and the existing workflow budgets.

Prepare reserves a private record for at most 120 seconds. Mailbox completion
holds mailbox then custodian locks, checks claim/target/deadline/intent/ACK,
commits custody to pending, and only then publishes the queue acknowledgement.
Consumers cannot read positive ACKs before custody commits. Failure aborts or
rolls back the prepared record. Pending expiry is 15 minutes from commitment;
retry does not extend it. The ACK says `queued_for_review`, not approved,
completed or started. No generation has started.

Publication-boundary config/workflow drift or unavailable verification stales
only the exact prepared or pending retry carrier under mailbox/custodian locks.
It records `stale_preview` in the failure reply and bounded tombstone, so exact
retries return the same reason; host inspection reports `stale`, never a human
Reject/Dismiss. No positive queue ACK is published on this path.

The mailbox records which operation owns each review ACK. Inspection,
Reject/Dismiss, expiry and explicit disarm retire only the matching operation's
queued ACK. Both custody slots invalidate on target changes and host closure.
Mailbox session closure also closes Generation custody. Ordinary pipe
release/disconnect retains host proposals; a request from another pairing
generation invalidates old Generation custody, and reused old request IDs are
rejected as cross-generation replay. No Project or host session is closed by
ordinary transport release.

## Retries and terminal states

The same request ID, exact normalized intent, pairing and epoch can retry a
pending request only after fresh Preview validation. It receives the exact
same ACK/proposal without renewing expiry. Changed intent returns
`request_id_conflict`; another request while the slot is occupied returns
`review_already_pending`. Consumed/failed correlations retain at most 64
tombstones, oldest first. Replay protection is bounded session bookkeeping,
not durable exactly-once delivery; evicted IDs may be used for a fresh request.
Host-only exact-proposal Reject/Dismiss methods exist for the future UI.

## Deferred human surface

There is no dedicated Generation Review navigation or UI in this slice.
Capabilities explicitly report `review_ui_available: false` and
`execution_available: false`. The next bounded PR must revalidate current
Project/config/plan before rendering, show full ordered targets via paging,
authored/resolved prompt summaries, counts/estimates and safe summaries, and
support exact-proposal Reject/Dismiss only. Prompt binding remains uncertified
and runtime success is never guaranteed. No Approve/Start/Run/Apply is planned
for that review-only UI slice.
