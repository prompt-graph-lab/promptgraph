# Executable Generation Review and human confirmation (Phase 4-C2B-2)

The existing Generation Review workspace now includes an Executable Review
section. **Prepare executable review** freezes the per-request workflows and
seeds introduced in [C2B-1](agent-generation-executable-manifest.md). It keeps
Generation Preview, Reject/Dismiss and Return to Project available. Preparing
or confirming never consumes the pending proposal or changes Scene Module
Swap custody, its queued ACK, the Project, Candidates, history or autosave.

The UI renders only `inspect_executable_generation_review`'s freshly validated
allowlisted projection. Twenty requests appear per page, covering every
physical Illustration and run up to the existing 100-request limit. Each row
shows physical order, request/run order, certification and blockers, exact
verified positive/negative prompt text, final seed/noise_seed values and policy,
supported sampler/latent parameters and workflow fingerprint. Prompts are not
silently truncated: existing certification text limits block certification.
An uncertifiable target blocks the complete review while every affected target
and request remains inspectable. Private request IDs, raw node IDs, workflow
JSON, host configuration, endpoint, paths and credentials stay private.

Prepared/certified means verified offline, not guaranteed ComfyUI runtime
success. Uncertifiable means blockers prevent confirmation. Confirmed means
the human acknowledged the exact displayed details. Stale/unavailable means
confirmation cannot be recorded. The UI always explains:

> Confirmation does not start generation. ComfyUI execution is not available yet.

## Session ownership and freshness

`ProjectAgentSessionRuntime` owns one private detached executable carrier and
at most one immutable human acknowledgment. Neither is stored in a widget
value, persisted Project, MCP projection or mailbox reply. The existing 8 MiB
manifest/projection limits bound the retained carrier; replacing it releases
the previous carrier and acknowledgment. Callback arguments remain server-held
carrier references. Client-visible widget keys, page values, public plan IDs
and confirmation flags grant no authority.

Preparation reserves a session revision under the runtime publication gate,
then reads and finalizes outside owner/mailbox locks. The final gate rejects
in-flight target, custody or revision replacement. Concurrent Prepare actions
reuse an existing preparation; they do not draw another manifest. Ordinary
reruns, request pagination, Return to Project, Scene Module Swap navigation and
Management workspace navigation retain the carrier and finalized seeds.
Returning to inspect it performs fresh verification. Explicit **Refresh
executable review** first removes the old carrier and acknowledgment, then
finalizes new seeds. A failed refresh cannot resurrect the old confirmation.

**Confirm reviewed execution details** is a direct human callback tied to the
exact session-held carrier. It reconstructs current authoritative proposal,
Project activation, pairing, host configuration and workflow inputs using
already finalized seeds. It compares the entire immutable manifest and the
displayed projection, not just their public identifiers. Only a complete fresh
certified carrier can record acknowledgment. Final publication follows the
existing runtime gate and route operation fence -> mailbox -> Generation custodian lock order, with no
workflow recomputation under custody locks. Concurrent/double clicks record
one acknowledgment; old, replaced, tampered or conflicting callbacks fail
closed. Supported host Project/config writers remain serialized by full app
run ownership; unrelated background mutation is not a supported writer.
The route operation fence excludes pairing replacement between final pairing
inspection and acknowledgment, preserving registry-before-mailbox ordering.

The acknowledgment binds exact proposal, private origin, manifest identity,
complete projection bytes, session incarnation and preparation revision.
Project switch or Save As invalidates it immediately during target
synchronization. Reject/Dismiss, explicit disarm and session close remove it.
Expiry or proposal replacement is pruned during normal target synchronization.
Scene/prompt/Module changes, host configuration/workflow changes or replacement
pairing refuse fresh inspection/confirmation and retire the retained carrier.
Temporary preflight/read failure shows unavailable, records no new confirmation
and never becomes human rejection or dismissal. The retained seeds and prior
acknowledgment may recover after a transient read failure, only after a fresh
successful inspection. Mere acknowledgment existence is never freshness proof.

## Execution remains unavailable

Human acknowledgment is not a worker claim, Start token, execution certificate
or permission to submit requests. Production C2A still returns
`executable_review_required`, including when supplied the real private
acknowledgment. `execution_available` and `job_submitted` remain false. No
Start/Generate/Run/Apply control, executor submission, job claim, worker launch,
output write/recovery or Candidate publication is introduced.

The execution slice still requires a **new explicit human Start action**, an
actual bounded worker inbox and executor custody, submission of the exact
frozen workflows without seed mutation, ambiguous-submission handling, output
verification/recovery and host-owned Candidate/history/save publication. A
future executor must not infer Start authority from acknowledgment existence.

Focused AppTest and lifecycle coverage exercises prepare/display/confirm,
1/20/21/100 request pages, multiple runs, seed retention/refresh, complete safe
display, uncertifiable targets, stale callbacks, concurrent confirmation,
proposal/content/config/pairing/activation drift, expiry/Reject/Dismiss/close,
temporary read failures, management navigation and unchanged Scene Module Swap
custody. Focused existing manifest, Review, C2A, custody and job tests protect
the independent execution gate; no full-suite or live generation is required.
