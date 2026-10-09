# Host Generation Review

The normal app sidebar exposes **Generation Review**, independent of Scene
Module Swap Agent Review. This completes the human review-only UI over
[Generation custody](agent-generation-review-custody.md). It does not execute
generation or approve a future run. The visible notice says: “No generation has
started; review only.” There is no Approve, Start, Generate, Run or Apply action.

## Owners and freshness

`ui/agent_generation_review_lifecycle.py` owns fresh host validation and a
bounded display projection. It synchronizes the live session's Project/path,
inspects custody through the mailbox, validates intent/envelope/identity/expiry,
then recomputes `core.agent_facade.preview_generation` with the host-configured
workflow provider. It binds the original Project, exact session route, target
epoch and stored pairing generation and compares the entire expected safe
Preview, including plan identity. It rechecks live Project/path, proposal and
pairing after computation. The registration's host-only pairing snapshot returns
no transport authority or credentials.

A genuine content/config/workflow mismatch marks the exact proposal stale
through the mailbox, retiring only its matching undelivered ACK. Temporary host
read/verification failure fails closed with no action controls and retains pending
custody for recovery. Ordinary route release preserves host review; a new pairing
generation stales the old proposal. Project switch, Save As, expiry, explicit
disarm and session close retain the existing custody lifecycle behavior.

Reject/Dismiss callbacks verify the exact rendered proposal and plan, recompute
freshness, and recheck target/proposal under the runtime publication gate before
the mailbox-coordinated terminal transition. Old callbacks and duplicate clicks
cannot consume another proposal. These actions alter session custody only; there
is no Project, Candidate, history, autosave or filesystem mutation.

## Display and navigation

`ui/agent_generation_review_panel.py` owns only Generation navigation/widget/page
state. App composition makes the two review surfaces mutually navigable without
sharing proposals, pages or action state. Return to Project does not resolve a
proposal. Review runs in the normal app run before management/missing-Project
workspace stops; the periodic agent fragment remains wake-only.

Every eligible Illustration is available in physical order on pages of 20,
including the maximum 100 targets. Page selection resets on proposal/plan
identity change. Rows display bounded authored and resolved active prompt
summaries, original lengths when truncated, eligibility, workflow node counts,
image-output counts and separate SaveImage counts. Scene/target/run/request and
estimated image/output-node counts, skipped details, warnings and expiry appear
above the rows. Skipped detail retains the existing 100-row bound and shows when
truncated. The UI uses only the existing safe host-configured workflow/output
summary: no workflow JSON, filenames, raw endpoint, output directory, settings,
credentials, image bytes or file probes. User prompt text is shown as code/plain
text, not interpreted Markdown.

Counts remain estimates, prompt/workflow binding remains uncertified, seeds are
not committed by Preview, and offline preflight never guarantees ComfyUI runtime
success. Unsupported/invalid proposals expose no actionable rows. Capabilities
now report `review_ui_available: true`; `execution_available` stays false.

## Limits and Phase 4-C

Focused lifecycle and AppTest coverage verifies 1/20/21/100 target pagination,
navigation/full reruns, freshness drift/recovery, callbacks, ACK retirement and
Scene Module Swap coexistence. Existing Preview/custody bounds and shared-workflow
configuration requirements remain unchanged. No dependencies were added.

Phase 4-C may now build a separately designed human-controlled execution/job
boundary. This UI grants no execution approval or job authority; proposal/plan
IDs cannot be reused as Start/Apply capabilities. ComfyUI submission/download,
async jobs, Candidate creation/adoption, multimodal review and Pixiv/export
remain outside this slice.
