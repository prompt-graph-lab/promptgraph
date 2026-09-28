"""Reviewed, prompt-only Apply plan for a Project Module's candidates."""

import copy
import json
from dataclasses import dataclass
from typing import Optional

from core.graph_builder import build_graph
from core.operations import (
    _clamp_module_min_match,
    _module_rule_tokens,
    _normalize_module_rule_tokens,
    _parse_prompt_for_module_preset,
    build_module_reference_token,
    get_module_body,
    get_module_core_tokens,
    get_module_min_match_tokens,
    normalize_module_library,
    preview_apply_module_candidates,
    preview_module_candidates,
)


_PROMPT_MODULE_FIELDS = ("body", "type", "graph", "core_tokens", "min_match_tokens")


@dataclass(frozen=True)
class ModuleCandidateApplyPlan:
    module_name: str
    prompt_state_json: str
    # Physical line position, id, exact reviewed before text, exact reviewed after text.
    replacements: tuple[tuple[int, str, str, str], ...]


@dataclass(frozen=True)
class ModuleCandidateApplyResult:
    applied: bool
    stale: bool
    project: object


def project_module_candidate_prompt_library(project, module_name: str) -> dict:
    """Read only the selected Module's prompt fields, never its opaque extensions."""
    library = getattr(project, "module_library", None) or {}
    if module_name not in library:
        return {}
    entry = library[module_name]
    if isinstance(entry, dict):
        prompt_entry = {key: entry[key] for key in _PROMPT_MODULE_FIELDS if key in entry}
    else:
        prompt_entry = entry
    return normalize_module_library({module_name: prompt_entry})


def _prompt_project(project, prompt_library: dict):
    shell = copy.copy(project)
    shell.module_library = prompt_library
    return shell


def preview_project_module_candidates(project, module_name: str, *, core_tokens, min_match_tokens):
    prompt_library = project_module_candidate_prompt_library(project, module_name)
    return preview_module_candidates(
        _prompt_project(project, prompt_library),
        module_name,
        core_tokens=core_tokens,
        min_match_tokens=min_match_tokens,
    )


def _prompt_state_json(project, module_name: str, prompt_library: dict, core_tokens, min_match_tokens):
    effective_body = get_module_body(prompt_library, module_name)
    module_tokens = _module_rule_tokens(effective_body)
    effective_core = (
        _normalize_module_rule_tokens(core_tokens)
        if core_tokens is not None else get_module_core_tokens(prompt_library, module_name)
    ) or module_tokens[:1]
    effective_min = _clamp_module_min_match(
        min_match_tokens if min_match_tokens is not None
        else get_module_min_match_tokens(prompt_library, module_name),
        module_tokens,
    )
    state = {
        "module_name": module_name,
        "module_reference": build_module_reference_token(module_name),
        "effective_body": effective_body,
        "module_tokens": module_tokens,
        "reviewed_rules": {
            "core_tokens": effective_core,
            "min_match_tokens": effective_min,
        },
        "lines": [
            {
                "id": line.id,
                "deleted": line.deleted,
                "original_file_name": line.original_file_name,
                "original_index": line.original_index,
                "tokens": line.tokens,
                "current_text": line.current_text,
            }
            for line in project.prompt_lines
        ],
    }
    return json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_module_candidate_apply_plan(
    project,
    module_name: str,
    *,
    core_tokens,
    min_match_tokens,
    example_limit: int = 50,
) -> tuple[Optional[ModuleCandidateApplyPlan], dict]:
    """Freeze every reviewed replacement; limit only the examples shown in the UI."""
    prompt_library = project_module_candidate_prompt_library(project, module_name)
    if module_name not in prompt_library:
        return None, {}
    preview = preview_apply_module_candidates(
        _prompt_project(project, prompt_library),
        module_name,
        core_tokens=core_tokens,
        min_match_tokens=min_match_tokens,
        example_limit=None,
    )
    positions = {line.id: index for index, line in enumerate(project.prompt_lines)}
    # Persisted line ids are unique. If this invariant is broken, fail closed.
    if len(positions) != len(project.prompt_lines):
        return None, {**preview, "affected_line_count": 0, "examples": []}
    replacements = tuple(
        (positions[row["line_id"]], row["line_id"], row["before"], row["after"])
        for row in preview["examples"]
    )
    shown_examples = (
        preview["examples"]
        if example_limit is None else preview["examples"][:max(0, example_limit)]
    )
    display_preview = {**preview, "examples": shown_examples}
    plan = ModuleCandidateApplyPlan(
        module_name=module_name,
        prompt_state_json=_prompt_state_json(
            project, module_name, prompt_library, core_tokens, min_match_tokens
        ),
        replacements=replacements,
    )
    return plan, display_preview


def apply_reviewed_module_candidates(
    project,
    plan: ModuleCandidateApplyPlan,
    *,
    module_name: str,
    core_tokens,
    min_match_tokens,
) -> ModuleCandidateApplyResult:
    """Return an isolated updated Project only if the complete reviewed state is fresh."""
    if not isinstance(plan, ModuleCandidateApplyPlan) or module_name != plan.module_name:
        return ModuleCandidateApplyResult(False, True, project)
    prompt_library = project_module_candidate_prompt_library(project, module_name)
    if module_name not in prompt_library:
        return ModuleCandidateApplyResult(False, True, project)
    current_state = _prompt_state_json(
        project, module_name, prompt_library, core_tokens, min_match_tokens
    )
    if current_state != plan.prompt_state_json:
        return ModuleCandidateApplyResult(False, True, project)
    if not plan.replacements:
        return ModuleCandidateApplyResult(False, False, project)

    updated = copy.copy(project)
    updated.prompt_lines = [copy.copy(line) for line in project.prompt_lines]
    for position, line_id, before, after in plan.replacements:
        line = updated.prompt_lines[position]
        if line.id != line_id or line.current_text != before:
            return ModuleCandidateApplyResult(False, True, project)
        line.current_text = after
        line.tokens = _parse_prompt_for_module_preset(after)
        line.edited = True
    return ModuleCandidateApplyResult(True, False, build_graph(updated))
