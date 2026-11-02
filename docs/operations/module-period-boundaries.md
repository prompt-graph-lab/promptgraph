# Module period boundaries (Public Issue #230)

Module candidate inspection, Global candidate inspection, reviewed candidate
Apply, Create & Bind / Replace With Module, body Swap, reference Swap and the
read-only H1 producer share an operation-only projection. The ordinary
`core.parser.parse_prompt` and `_parse_prompt_for_module_preset` retain their
comma-only token persistence semantics. Inspection never migrates stored tokens.

The supported lexical context is deliberately narrow:

- The raw prompt contains a comma. A legacy Module-operation token can contain
  one or more `.` followed by whitespace boundaries.
- Every fragment in that token must be one to five lowercase ASCII words,
  separated by single spaces or hyphens, or a standalone `<mod:Name>` reference.
- A fixed exclusion set rejects common abbreviations, pronouns and auxiliary /
  finite verbs (see `_AMBIGUOUS` in `core/module_period_projection.py`). There is
  no semantic inference. Lowercase short prose can be lexically indistinguishable
  from tags; this rule does not claim to recognize natural-language sentences.
- Capitals, digits, internal punctuation, decimals, weights, URLs, domains,
  filenames, versions, repeated periods and terminal sentence punctuation do not
  qualify. Prompts without a comma retain their existing interpretation.
- Periods inside parentheses, brackets, braces, inline Modules and paired Module
  ranges remain opaque. Unclosed opening markup protects the following text;
  mismatched/orphan closing markup disables the projection. This does not repair
  or validate malformed markup.

For example, the exact synthetic positive prompt
`  pose phrase. fictional character name,  scene detail,  ` can match the
`fictional character name` Module. Binding produces
`  pose phrase, <mod:Source>,  scene detail,  `: the period directly touching
the inserted reference becomes a comma so the unchanged persisted parser sees
an independent, expandable and toggleable Module token. When a reference has
period boundaries on both sides, both adjacent delimiters become commas. Body
Swap changes only that phrase to `replacement character` and retains the period.
The original leading spaces, delimiter whitespace, doubled comma spacing and
trailing comma/spaces survive. Full Before/After previews show these bounded
punctuation changes; other period delimiters are preserved. Negative prompts,
image references, Candidates and
unrelated Module metadata use their existing owners. Existing exact whole-token
rules and whole-token creation selections remain usable alongside new fragments.
An explicitly saved whole-token core rule retains the legacy comma-token
interpretation, including Module bodies containing other commas. Missing saved
core/minimum fields retain their legacy defaults; inspection does not replace
those defaults with fragment rules. Newly authored Modules still receive
fragment rules, and explicitly editing the rules changes the interpretation
without changing the Module body. Candidate planning, freshness checks, counters
and strict Swap use that same effective rule interpretation. Candidate rule
choices retain whole and fragment options; mixing incompatible interpretations
shows a warning and blocks Preview/Save Rules. The shared core guard also
refuses persisted mixed rules reached through local or Global scanning and
Apply APIs, including zero scan thresholds. Conflicting Modules are not imported
as a side effect of applying other candidates. Body Swap refuses incompatible
source or target rule interpretations in both strict and loose modes; explicit
reference Swap retains precedence because it does not materialize body tokens.
Selected Scenes and H1 use the existing reason/diagnostics fields to report
`incompatible_module_core_rules`. A body-only H1 refusal has `valid=false` and
`changed_count=0`; a valid explicit-reference change can retain `valid=true`
while carrying that bounded diagnostic for refused body matching. No H1 fields
or version are added. Project and Global Module editors
retain the effective core and minimum bound on Save, including newly authored
fragment rules. When fragment projection would change literal body punctuation,
the token Inspector explains that its row-based Update/Add actions are
unavailable; the Module Body (Advanced) literal editor remains available.
Comma-only editor spelling, ordering and duplicates are retained.
Activating a period boundary also retains bracket/brace groups as original whole
source spans; it does not expose the persistence-oriented Module parser's partial
`[red` / `blue]` tokens to candidate detection or the target selector.

Rewrites replay edits against original source spans. Apart from the
reference-adjacent delimiter conversion above, if removing multiple
projected fragments would consume a period delimiter or require an ambiguous
insertion, the operation refuses the rewrite rather than normalizing the prompt.
Prompts containing ambiguous period-space text still replay separately matched
comma-token edits losslessly against their legacy spans. Ordinary comma-only
prompts retain their established serializer. Existing preview skip/no-match counts
represent unsafe rewrite refusals; candidate block
and Create/Bind malformed skip counters also include an unsafe punctuation
rewrite. Such a refusal is not evidence that the original prompt is corrupt.
A whole legacy token explicitly selected as the target remains an atomic target.

The actual Create & Bind selector projects current text, while retaining whole
legacy selections at their original source positions, including alongside
unrelated standalone Module references. Create, Replace, local and
Global candidate Apply and ordinary Swap UI previews request every Project row.
Create/Replace/local candidate review renders literal full Before/After text;
Global candidate and Swap use their existing full-text renderer. Selected Scenes
Swap renders every entry rather than hiding entries after 40; if a plan entry
cannot be rendered under its Scene summary, Apply is disabled. Skip labels
explain that an unsafe punctuation rewrite can be refused without a change. Existing human
Preview/Apply and explicit Save ownership remains in place. H1 retains its
existing bounded/truncated read-only contract rather than becoming an Apply
review surface.

No HTML entity decoding is performed. A synthetic literal `&#x20;` survives
inspection and Apply exactly. The user's raw Project was not inspected, so this
does not establish whether the reported entity was raw data or presentation.

H1 keeps `promptgraph.agent-facade.v1`, `scene_module_swap`, exact target order,
legacy after-token shape, canonical digests, bounds and read-only status. Its
period-bearing fixture now reflects this Public operation grammar. Desktop
PR #228 is merged at Desktop main commit
`a107eb025f028e44e8a091e16fcaf629efd12778`. The coordinator independently compared
synthetic Public H1 observations with Desktop D1 against an archived copy of that
commit using direct core calls. Lowercase, legacy-whole-core and standalone
reference cases matched. A capitalized grammar case was incompatible with a
row/projection mismatch. A valid reference preview carrying mixed-core
diagnostics was refused as `handoff-producer-refused`. Both synthetic Projects
remained unchanged.

This is bounded offline compatibility evidence, not full Public/Desktop parity:
the capitalized grammar mismatch remains unresolved. It does not establish HTTP
transport, live Project behavior or a Windows/Tauri cross-app smoke result.
Do not weaken D1 or treat Public `plan_id` as Desktop Apply authority.

Validation uses synthetic Projects and temporary JSON only. No real Project,
ComfyUI execution, Desktop mutation or cross-app smoke is part of this change.


A precise remaining limitation is a valid standalone library reference preceding
an otherwise eligible boundary: `<mod:Quality>, pose phrase. character name,
detail` does not activate the new boundary, even when Quality exists in the
Project library. A reference following the phrase does not have this limitation.
The pure lexical projection has no Project-library context, so an unmatched
opening marker and a true unclosed range have identical syntax there. This
change deliberately keeps that ambiguity protected. Supporting preceding valid
references requires propagating library-aware reference classification through
candidate, Create/Bind, Swap and H1 owners together; do not simply allow all
unmatched opening markers, which would expose malformed range content. Legacy
whole-token behavior remains available, and no stored tokens are migrated.


Explicit source-reference Swap retains precedence over body-token matching,
including when a whole legacy period token is also present. If the reference
rewrite is refused, the operation remains unchanged; it never falls through to
an unrelated body replacement. A preexisting `<mod:Source>. literal` token
that cannot be safely projected is refused rather than replacing the entire
legacy token and swallowing its literal suffix. Newly bound independent comma
references can be swapped normally. H1 uses the same planner behavior.

Create/Bind and Replace With Module conservatively refuse a line when a mixed
whole-token/fragment selection requires incompatible representations of that
line. In particular, selecting a whole first period token and a fragment of a
second period token does not authorize a partial replacement. This uses the
existing visible unsafe/malformed skip count. Saving a newly authored Module
itself retains the existing library-creation behavior even when its binding is
skipped; the preview reports zero affected Illustrations in that case.
