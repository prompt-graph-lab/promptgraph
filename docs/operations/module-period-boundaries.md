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
`fictional character name` Module. Binding changes only that phrase to
`<mod:Source>`; body Swap changes only that phrase to `replacement character`.
The original leading spaces, period-space delimiter, doubled comma spacing and
trailing comma/spaces survive. Negative prompts, image references, Candidates and
unrelated Module metadata use their existing owners. Existing exact whole-token
rules and whole-token creation selections remain usable alongside new fragments.
Activating a period boundary also retains bracket/brace groups as original whole
source spans; it does not expose the persistence-oriented Module parser's partial
`[red` / `blue]` tokens to candidate detection or the target selector.

Rewrites replay edits against original source spans. If removing multiple
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
Issue #227 is independently owned and still requires its own implementation and
focused compatibility validation. Public/Desktop parity is unverified; Desktop
D1 may correctly report these previews incompatible until its grammar agrees.
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
an unrelated body replacement. H1 uses the same planner behavior.

Create/Bind and Replace With Module conservatively refuse a line when a mixed
whole-token/fragment selection requires incompatible representations of that
line. In particular, selecting a whole first period token and a fragment of a
second period token does not authorize a partial replacement. This uses the
existing visible unsafe/malformed skip count. Saving a newly authored Module
itself retains the existing library-creation behavior even when its binding is
skipped; the preview reports zero affected Illustrations in that case.
