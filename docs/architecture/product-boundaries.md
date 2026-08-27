# Product Boundaries: Pro, Exp, LineageEditor

## Current Pro boundary: 2026-05-31

PromptGraph Pro now treats reusable module work as a practical production-assist feature:

- Project modules remain project-local and are the active source for insertion, replacement, export, and active prompt expansion.
- Global Module Library v1 stores reusable user assets in `~/PromptGraph/modules/global_modules.json`.
- Saving globally copies a saved project module into the user-level library.
- Loading globally copies a global module into the current project library.
- There is no synchronization, versioning, inheritance, dependency management, remote repository, or marketplace behavior.

PromptGraph Pro now also closes the final output / publishing export loop for ordered image sets. Users can keep generated, imported, candidate, reference, and after images with their project metadata intact while exporting new ordered copies for sharing or publishing. Optional PNG metadata removal is export-only and does not clean or rewrite project-linked source images.

Gallery Candidate work in Pro v1 is manual and non-destructive. Image-less lines can adopt a candidate as the line image, image-present lines can swap a candidate with the current main image, and the previous main image is retreated into the candidate list. Candidate files, source/reference files, and imported source metadata are not moved, deleted, or overwritten by these operations.

Image reference adoption, prompt adoption/revert controls, and final export should stay separate. Candidate/main-image swap changes the resolved Gallery/export image only. Candidate Prompt Adoption and Prompt Revert change editable positive prompt text only. Final Images Export copies the resolved main image sequence to `exports/final` and must not clean, move, or overwrite project-linked source or candidate files.

Lightweight Fork / Final Sequence Materialization is a Pro v1 practical production workflow, not ISDL materialization, semantic prompt rewrite, Candidate Prompt Adoption, or multi-set Re-assembly. Gallery UI Create Fork now requires a saved source project, fresh preview, explicit confirmation, destination validation, and the exact `FORK FINAL` phrase for All scope. Core materialization copies the reviewed final sequence into a new editable project while keeping the source project and source images non-destructive; the fork is opened only through an explicit user action. The focused design note is [Lightweight Fork / Final Sequence Materialization Design](lightweight-fork-final-sequence.md).

Pro v1 also supports **Append Selected Routes to Existing Fork** for a Fork created from the same saved source Project. It appends only Route handles not already represented in the manifest, preserves existing Fork edits and assets, creates fresh IDs and continued image sequence names only for new Lines, records append history, and commits through an atomic directory swap. It is not a cross-project merge, Route replacement/update, duplicate Route version, reverse sync, or schema migration.

Route is a first-class production unit in Pro v1, but not a first-class schema object. Gallery generation, prompt batch operations, Candidate insertion, Candidate Route creation, Sequence Preview, and Final Images Export should continue to resolve Route scopes through route separators while excluding the separator lines themselves. Workbench cards are scratch spaces for one source line and should not leak workbench-only fields into normal main-sequence PromptLines.

Route Operations for Pro v1 are design-fixed in [Route Operations Design](route-operations.md): a Route block is the separator plus its positionally-owned lines, the separator PromptLine id is the Route handle, and a shared structural RouteBlock resolver is the boundary that operation-specific eligibility must stay out of. Approved Pro v1 scope is separator-card Route Actions that dispatch into existing preview/apply panels, Route move up/down, flag-based Route remove with atomic Route-level restore and no physical deletion, Duplicate Route as Baseline with reused image paths, fresh line ids, preserved deleted state, and cleared candidate state, the session-only Selected Routes foundation, and its consumers in Final Images Export, Lightweight Fork, Route-scope Batch Candidate Adoption, Gallery Generation, Module Swap, and Attribute Group Swap. The foundation has no schema or save/load persistence; all six consumers are preview-first and use Project-order selected handles. Export and Fork leave source references/assets unchanged; Candidate Adoption changes the established selected main-image reference/retreat state together with its Candidate-derived `source_generation_info` and `lineage_info`, keeps editable prompt text and source files unchanged, and commits the selected-Route plan atomically. Selected Routes Generation reuses the existing ComfyUI workflow and Candidate registration path, performs full preflight before submission, and changes only Candidate state for real outputs; main image references, prompts, and image provenance stay unchanged. Selected Routes Module Swap and Attribute Group Swap reuse their existing matching and Prompt replacement semantics, preview Prompt diffs and image / Prompt Drift, revalidate immediately before apply, and commit one atomic Prompt-only undo unit while preserving images, Candidates, Gallery Variants, and provenance. Attribute Group Swap additionally requires compatible normalized Attribute Slots and keeps negative metadata preview-only. Selected Routes Fork preserves selected Route boundaries and clears Candidate/Variant state only in the new fork copy; the existing Route scopes remain separate. Candidate Prompt Adoption and other Multi-Route operation connections remain v1.1, as do Multiple Routes Fork and reduced Route Candidate Review. The full Route Take pipeline and a first-class Route object / Project Object Model are Desktop / Pro v2.

Global Route Template is design-fixed in [Global Route Template Design](global-route-template.md) as a conditional Pro v1 candidate: slot-free, single-Route, one JSON file per template in a user-level `route_templates` directory, embedded Module snapshots with unknown-metadata preservation, no absolute paths, no silent overwrite, and no silent same-name Module conflict resolution. Binding is delegated to the existing Route-scope Module Swap. Slot binding, Template Pack / Know-how Pack, and state-aware templates stay out of Pro v1.

Trash is a Pro v1 manual isolation and restore area. It may contain clearly failed examples in real production use, but Pro v1 does not analyze Trash, mine negative prompts, compare Candidate pools against Trash, or extract automatic failure memory.

Future module workflow work should stay v1-minimal unless it has been validated elsewhere. Attribute-aware module ideas are captured in [Module Attribute / Semantic Slot Design](module-attribute-design.md), but automatic tag normalization should stay out of Pro until it is safer.

Attribute State / StateDomain is a future model boundary, not current Pro runtime behavior. Pro v1 may document the separation between AttributeSlot, Attribute Variant, StateDomain, and per-line LineBinding, but it should not add state-aware swap, state inference, timeline UI, JSON schema changes, or migration work until those ideas are validated in Exp / Desktop design. The conceptual storage boundary is summarized in [PromptGraph Domain Model Notes](domain-model.md).

Illustration Set Description Language / ISDL is also future-facing. It can describe a long-term language for illustration-set structure, state transitions, reuse knowledge, and lineage, but it should not turn Pro v1 into a research framework or a teacher-data production tool. Pro v1 can produce useful reviewed project data for future Exp/Desktop workflows, but its primary boundary remains practical illustration-set production.

この文書は、PromptGraph 系プロジェクトの役割分担を将来の開発セッション向けに記録する project memory です。

Gallery Edit Mode should remain the main production workspace. Lightweight launchers may expose essential route/project-wide operations near Gallery, but detailed Module, Attribute, AnimaDex, and line-management tools should stay in their dedicated preview-first sections instead of permanently expanding the Gallery or side panels.

Selected Line and Workbench integration should stay conservative for Pro v1. A future always-on editor that combines Module, Attribute, State, semantic summary, and State Timeline controls belongs after LineBinding design is stable. Current Workbench cards remain scratch spaces, not main sequence lines and not export / Module Swap / Batch Edit targets.

## Future boundary: Illustration Set Re-assembly

Pro v1 remains a single-illustration-set product boundary. It should stabilize the existing Metadata Import, Gallery, Candidate, Route, Lineage, Global Module, Attribute Group, Batch Edit, ComfyUI generation, and Export workflows around one active project/set.

Multiple illustration sets loaded at the same time are out of Pro v1 scope. Comparing Source Sets, extracting reusable Module / Attribute / Route / Lineage / Metadata / Gallery structure, and producing a new Derived Set through a Recipe would require broader changes to the Project Model, save format, UI assumptions, thumbnail/cache handling, and local asset management.

Illustration Set Re-assembly / Know-how Mashup remains a longer-term design
direction. Pro v1.1 can prepare AI-first foundations such as
model-boundary refactoring, local/Qwen-assisted prompt summaries, Module
classification, Attribute Group inference, Attribute State extraction,
exchangeable-region suggestions, Lightweight Fork design, Route-scope Batch
Candidate Adoption design, and diff-edit proposal workflows. Full Re-assembly
is a Desktop / Pro v2 candidate where local images, caches, ComfyUI integration,
resident models, and MCP/API integrations can be treated as first-class
assumptions.

## PromptGraph Pro

PromptGraph Pro は、実用的な AI イラスト制作 workflow tool である。

Pro で優先するもの:

- UI clarity
- prompt editing stability
- image / candidate management
- save / load / autosave safety
- ComfyUI execution practicality
- Lite / Pro boundary stability
- 制作中に workflow が崩壊しないこと

Pro は研究概念をすべて詰め込む場所ではない。制作作業を完了できること、復帰できること、破綻しないことを優先する。

## PromptGraph Exp

PromptGraph Exp は、研究・実験・個人ラボ的な環境である。

Exp に置くべきもの:

- lineage / state transition analysis
- generation archive reconstruction
- Trash Analysis / Failure Pattern Scan
- Candidate vs Trash comparison
- negative prompt suggestion
- AI-assisted prompt anti-pattern extraction
- automatic failure memory mining
- semantic inference
- hidden lineage inference
- AI-assisted reconstruction
- autonomous or agent-driven generation workflows
- 成熟前の speculative UI / workflow

Pro に入れるには早い、危険、または制作 UI を複雑にしすぎるものは、まず Exp で検証する。

## LineageEditor

LineageEditor は、将来的な core / OSS layer の概念である。

扱う可能性があるもの:

- state transition editing
- lineage graph editing
- reusable transition concepts
- generation history and branch structures
- PromptGraph 系以外にも応用できる抽象レイヤー

PromptGraph Pro は LineageEditor の実装実験から学ぶことはあるが、Pro v1 のために LineageEditor 全体を完成させる必要はない。

## AI Assistance の扱い

AI assistance は将来的に Pro に入ってよい。ただし、Pro に入れるのは mature, safe, production-assist な機能に限る。

- speculative inference は Exp で検証する。
- autonomous workflow は Exp で安全性と UX を検証する。
- 制作を壊さず、ユーザーが確認でき、戻せる AI 支援は Pro に graduate できる。
- Pro では hidden / surprising / irreversible な AI 操作を避ける。

## 境界判断

迷ったときの判断:

- 制作を安定させるなら Pro。
- 研究・推論・再構築・自律化なら Exp。
- lineage / transition の汎用概念なら LineageEditor。
- 成熟して安全になった production-assist AI は Pro へ移す候補。
