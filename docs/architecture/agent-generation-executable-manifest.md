# Agent Generation executable manifest (Phase 4-C2B-1)

This slice makes exact per-request work available for a future human review.
The subsequent [C2B-2 executable review UI](agent-generation-executable-review-ui.md)
now retains these carriers in the session host and records explicit human
acknowledgment; generation execution remains unavailable.
It grants no execution authority. The shipped Generation Preview and Review UI
remain safe observation surfaces, and production C2A still returns
`executable_review_required`. No visible Start, MCP execution tool, worker,
executor inbox, ComfyUI submission, output write, Candidate append, history or
autosave is added. Scene Module Swap custody and behavior are unchanged.

## Finalized work ownership

`core/generation_executable_manifest.py` owns offline finalization. The private
host preflight sink reuses the existing Facade/Gallery planner, retaining the
ordered request set, prepared workflow, host configuration and detached prompt
preparation evidence. `core.comfy_workflow_preparation` supplies the original
configured API workflow, expanded Illustration inputs and, when applicable,
the existing grouped-prompt result before injection. None of this private
evidence enters the safe Preview or Generation proposal custody.

Every physical request gets a separate detached workflow, including repeated
runs of an Illustration. Request order remains physical Illustration order,
then run 1..N. The complete target/run Cartesian product is checked against the
original Preview; omitted, reordered or duplicate requests refuse finalization.
Stable Illustration identity and private request correlation survive freezing.
Canonical UTF-8 JSON bytes and their SHA-256 digest identify each exact payload.
The immutable manifest binds proposal, original plan, Scene, complete host
preflight identity, final host options, request order, workflow digests and seed
provenance. It retains bytes/scalars only, with no live Project or callbacks.

The host setting `agent_generation_seed_policy` supports `random_u64` (default)
and `preserve_u64`. This is a host configuration input, not an agent argument or
new UI control. Both `seed` and `noise_seed` slots are finalized before review.
Preservation accepts integer values and integral finite numeric values in
0..2^64-1, explicitly preserving zero; booleans, negative sentinels, fractional
values, links and out-of-range values are uncertifiable. Random policy takes
bounded 64-bit draws and resolves collisions by incrementing with wraparound,
so final random-policy seed slots are distinct across the complete manifest
without probabilistic retries. Private provenance records the source node/key,
original value, final value and policy. Public seed rows contain bounded slot
ordinals, key, final value and policy. Injected deterministic random sources
make tests independent of collision probability.

`core.comfy_prompt_request.prepare_prompt_request` intentionally randomizes
numeric seed slots while preparing legacy Gallery submissions. Its behavior is
unchanged. A future executor must submit the frozen workflow exactly, without
calling that mutating preparation path or rerandomizing seeds after human
review. This slice does not add a transport implementation.

## Certification limits

Certification is deliberately narrow: standard `KSampler`/`KSamplerAdvanced`
positive and negative links must point directly to separate standard
`CLIPTextEncode.text` slots at output index zero. Missing nodes/keys, shared
positive/negative slots, custom samplers/encoders, conditioning intermediates,
other unreviewed text nodes and unavailable private evidence block certification.
Each recognized `SaveImage` or `PreviewImage` path must trace through the
standard `VAEDecode.samples` input at output index zero to a standard
`KSampler`/`KSamplerAdvanced`; every certified sampler must reach at least one
such output. Unsupported, ambiguous or malformed output paths block
certification; unknown custom-node semantics are never inferred. This is
offline binding and output-path evidence, never proof of server connectivity,
complete ComfyUI schema validity, successful generation or exact output counts.

For ordinary injection, every supported final positive and negative slot must
equal the corresponding expanded Illustration input. A successful injection
return or placeholder replacement alone cannot prove this; for example, the
legacy placeholder path may leave negative text unchanged and is refused.

For group mappings, every produced group requires an explicit configured
destination. Every destination must reference an existing supported text slot,
all positive/negative slots must be covered once, and ambiguous/unsupported
mapping shapes fail closed. After validating mapping completeness, the verifier
reuses the existing injection owner on the retained source workflow to preserve
group order, token deduplication, fallback and merge/overwrite semantics. It then
compares every final slot against that independently reconstructed text. Public
prompt rows identify their actual positive/negative role and `group_mapping`
semantics; grouped negative text is not mislabeled as authored negative text.
No arbitrary custom workflow support is inferred from injection success.

The existing limits remain five runs and 100 requests, 20,000 JSON nodes and
1,000,000 string characters per workflow, 1,000,000 serialized bytes per
finalized workflow and 8 MiB aggregate repeated workflows, provenance and host
options. Private serialized source identity and public projection are also
capped at 8 MiB. Prompt text is limited to 4,000 characters per verified slot;
longer text blocks certification rather than hiding the exact text behind
truncation. Each request has at most 100 prompt bindings, 100 seed slots and
100 parameter rows. A budget failure never delivers a partial manifest.

## Human surface and freshness

`ui.agent_generation_executable_review.build_executable_generation_review` is
a host-only entry point used by the C2B-2 UI, with no MCP caller. It recomputes the
existing Generation Review and authoritative host preflight before and after
finalization. The returned immutable carrier is retained by the session host.
Inspection revalidates the exact pending proposal and reconstructs the carrier
from fresh authoritative inputs plus its already finalized seeds. It compares
both private manifest and projection, rather than trusting public IDs or a
caller-supplied certificate. Inspection does not reroll seeds.

Private origin identity binds runtime incarnation, active Project identity,
path/target epoch, pairing, exact original proposal/intent and Preview. Prompt,
Module, Scene/configuration, configured workflow file, Project activation,
Save As, expiry and session/pairing drift refuse inspection. Existing host
full-app-run writer ownership remains required; arbitrary concurrent writers
are not supported. Transient host read failure reports unavailable computation,
without claiming human rejection or consuming pending custody.

The allowlisted projection includes Scene label/identity, all target identities
and physical order, all request/run indices and counts, exact verified final
prompt text, finalized seed policy/values, relevant standard sampler and latent
parameters, workflow fingerprints, warnings, unsupported-binding codes,
blockers and certified/uncertifiable target distinction. Parameter projection
is limited to supported standard sampler/EmptyLatentImage scalar fields; raw
node IDs and arbitrary/custom node data are private. Raw workflow JSON,
filesystem paths, endpoint/credentials, arbitrary settings and request
correlation never enter the projection. A changed projection cannot pass
inspection merely because its public manifest/plan ID matches.

One uncertifiable target blocks the complete executable review. Every target
and request remains represented with its blocker; no partial manifest is
returned. In that case finalized workflow fingerprints/seeds/parameters are
withheld throughout the projection, while verified prompt text can explain
individual target status. Pending Generation custody is retained and no job
is created or claimed, for both certified and uncertifiable observations.

The C2B-2 human confirmation lifecycle separately binds the complete displayed
carrier to the exact private manifest without entering the C2A one-shot claim
boundary. Production Start still requires a new explicit human Start action,
bounded executor custody/inbox, output verification/recovery and normal host
Candidate/history/save publication. Neither this offline `certified` state,
public IDs nor the C2A characterization certificate proves human review or
permits execution. No automatic merge or real generation validates this slice.

Focused tests cover deterministic multiple runs/Illustrations, zero/u64/noise
seeds, collision resolution, immutable payloads, binding/group semantics and
silent skips, target coverage/privacy/budgets, actual configured-file drift,
activation/config/Module drift, custody preservation, C2A fail-closed behavior
and existing Preview/Review/Gallery regressions. No full suite is required.
