"""Reviewed Apply plan for Global Module candidate references.

This cross-container path is separate from Project Module Candidate Apply. A
reviewed replacement and its Global-to-Project import decision travel together.
"""

import copy
import json
from dataclasses import dataclass
from typing import Optional

from core.graph_builder import build_graph
from core.module_container_policy import REFERENCE_ASSETS_FIELD
from core.operations import (
    _parse_prompt_for_module_preset,
    normalize_module_library,
    preview_apply_detected_modules,
)


_PROMPT_MODULE_FIELDS = ("body", "type", "graph", "core_tokens", "min_match_tokens")


@dataclass(frozen=True)
class GlobalModuleCandidateApplyPlan:
    module_names: tuple[str, ...]
    min_core_match_lines: int
    prompt_state_json: str
    # Physical line position, id, exact reviewed before text, exact reviewed after text.
    replacements: tuple[tuple[int, str, str, str], ...]
    # Name and serialized prompt-only Global entry, frozen at Preview.
    imports: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class GlobalModuleCandidateApplyResult:
    applied: bool
    stale: bool
    project: object


def _prompt_entry(entry):
    """Select prompt fields without reading opaque Project Module extensions."""
    if isinstance(entry, dict):
        return {key: entry[key] for key in _PROMPT_MODULE_FIELDS if key in entry}
    return entry


def _selected_prompt_library(library, names):
    source = library if isinstance(library, dict) else {}
    return normalize_module_library({
        name: _prompt_entry(source[name])
        for name in names if name in source
    })


def _selected_names(global_library, module_names):
    source = global_library if isinstance(global_library, dict) else {}
    names = []
    seen = set()
    for module_name in module_names or []:
        name = str(module_name or "").strip()
        if name and name in source and name not in seen:
            names.append(name)
            seen.add(name)
    return tuple(names)


def _prompt_state_json(project, global_library, names, min_core_match_lines):
    project_library = getattr(project, "module_library", None) or {}
    global_prompt = _selected_prompt_library(global_library, names)
    project_prompt = _selected_prompt_library(project_library, names)
    state = {
        "module_names": names,
        "min_core_match_lines": min_core_match_lines,
        "global_prompt": global_prompt,
        "project_prompt": project_prompt,
        "import_needed": [name for name in names if name not in project_library],
        "lines": [
            {
                "id": getattr(line, "id", ""),
                "deleted": getattr(line, "deleted", False),
                "line_type": getattr(line, "line_type", None),
                "original_file_name": getattr(line, "original_file_name", ""),
                "original_index": getattr(line, "original_index", 0),
                "current_index": getattr(line, "current_index", 0),
                "tokens": getattr(line, "tokens", None),
                "current_text": getattr(line, "current_text", ""),
            }
            for line in getattr(project, "prompt_lines", [])
        ],
    }
    return json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _frozen_import_entry(global_library, name):
    """Freeze the full Global entry except its reserved Project-local field.

    The value of ``reference_assets``, if a stale caller supplied it, is never
    read or copied. Other Global metadata keeps the existing import semantics.
    """
    entry = global_library[name]
    if isinstance(entry, dict):
        entry = {key: value for key, value in entry.items() if key != REFERENCE_ASSETS_FIELD}
    normalized = normalize_module_library({name: entry})[name]
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_global_module_candidate_apply_plan(
    project,
    global_library,
    module_names,
    *,
    min_core_match_lines=1,
    example_limit=50,
) -> tuple[Optional[GlobalModuleCandidateApplyPlan], dict]:
    """Freeze every replacement and import; limit only displayed examples."""
    names = _selected_names(global_library, module_names)
    project_library = getattr(project, "module_library", None) or {}
    prompt_project = copy.copy(project)
    prompt_project.module_library = _selected_prompt_library(project_library, names)
    global_prompt = _selected_prompt_library(global_library, names)
    preview = preview_apply_detected_modules(
        prompt_project,
        global_prompt,
        list(names),
        min_core_match_lines=min_core_match_lines,
        example_limit=None,
    )
    positions = {
        getattr(line, "id", ""): index
        for index, line in enumerate(getattr(project, "prompt_lines", []))
    }
    if len(positions) != len(getattr(project, "prompt_lines", [])):
        return None, {**preview, "affected_line_count": 0, "examples": []}
    replacements = tuple(
        (positions[row["line_id"]], row["line_id"], row["before"], row["after"])
        for row in preview["examples"]
    )
    if len(replacements) != preview["affected_line_count"]:
        raise ValueError("Global Module Apply preview omitted a replacement")
    imports = tuple(
        (name, _frozen_import_entry(global_library, name))
        for name in preview["import_needed"]
    )
    shown = preview["examples"] if example_limit is None else preview["examples"][:max(0, example_limit)]
    display_preview = {**preview, "examples": shown}
    plan = GlobalModuleCandidateApplyPlan(
        module_names=names,
        min_core_match_lines=min_core_match_lines,
        prompt_state_json=_prompt_state_json(project, global_library, names, min_core_match_lines),
        replacements=replacements,
        imports=imports,
    )
    return plan, display_preview


def global_module_candidate_apply_plan_is_current(project, global_library, plan) -> bool:
    """Check the reviewed prompt inputs and cross-container decisions."""
    if not isinstance(plan, GlobalModuleCandidateApplyPlan):
        return False
    return _prompt_state_json(
        project, global_library, plan.module_names, plan.min_core_match_lines
    ) == plan.prompt_state_json


def apply_reviewed_global_module_candidates(
    project, global_library, plan
) -> GlobalModuleCandidateApplyResult:
    """Build an isolated result from the reviewed plan, or reject it unchanged."""
    if not global_module_candidate_apply_plan_is_current(project, global_library, plan):
        return GlobalModuleCandidateApplyResult(False, True, project)
    if not plan.replacements:
        return GlobalModuleCandidateApplyResult(False, False, project)

    updated = copy.copy(project)
    updated.prompt_lines = [copy.copy(line) for line in project.prompt_lines]
    updated.module_library = dict(getattr(project, "module_library", None) or {})
    for name, payload_json in plan.imports:
        if name in updated.module_library:
            return GlobalModuleCandidateApplyResult(False, True, project)
        updated.module_library[name] = json.loads(payload_json)
    for position, line_id, before, after in plan.replacements:
        line = updated.prompt_lines[position]
        if line.id != line_id or line.current_text != before:
            return GlobalModuleCandidateApplyResult(False, True, project)
        line.current_text = after
        line.tokens = _parse_prompt_for_module_preset(after)
        line.edited = True
    return GlobalModuleCandidateApplyResult(True, False, build_graph(updated))
