"""Transport-neutral PoC-0 observations and reviewed, clone-only Batch Replace.

Only ``AgentApplyResult.agent_result`` may cross an agent/transport boundary.
The host owns approval, publication, history, persistence and graph/UI wiring.
"""

import copy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

from core import operations
from core.parser import parse_prompt
from core.project import Project, PromptLine


CONTRACT_VERSION = "promptgraph.agent-facade.v1"
OPERATION = "batch_replace"
MAX_ITEMS = 100
MAX_TARGETS = 1000
MAX_TEXT = 4000
MAX_REQUEST_TEXT = 10000
EXAMPLE_LIMIT = 5
REPLACE_MODES = ("exact_token", "contains_token", "literal", "token_set")


class _Invalid(ValueError):
    pass


def _json_copy(value: Any) -> Any:
    """Accept built-in JSON values only; never call a supplied object's hooks."""
    remaining = 100000
    active = set()

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise _Invalid("json_bounds_exceeded")
        kind = type(item)
        if kind in (str, int, bool) or item is None:
            if kind is str:
                if len(item) > 1000000:
                    raise _Invalid("json_bounds_exceeded")
                try:
                    item.encode("utf-8")
                except UnicodeError:
                    raise _Invalid("invalid_unicode") from None
            return item
        if kind is float and math.isfinite(item):
            return item
        if kind not in (dict, list):
            raise _Invalid("non_json_value")
        identity = id(item)
        if identity in active:
            raise _Invalid("cyclic_json")
        active.add(identity)
        try:
            if kind is list:
                return [visit(child, depth + 1) for child in item]
            if any(type(key) is not str for key in item):
                raise _Invalid("non_string_json_key")
            return {visit(key, depth + 1): visit(child, depth + 1)
                    for key, child in item.items()}
        finally:
            active.remove(identity)

    return visit(value, 0)


def _digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _response(ok=True, reason="", **fields):
    return {"contract_version": CONTRACT_VERSION, "ok": ok, "reason": reason,
            "diagnostics": [] if ok else [{"code": reason}], **fields}


def _id(value):
    if type(value) is not str or not value.strip() or len(value) > 200:
        raise _Invalid("invalid_id")
    return value.strip()


def _lines(project):
    if project is None:
        raise _Invalid("missing_project")
    if type(project) is not Project:
        raise _Invalid("invalid_project")
    lines = project.prompt_lines
    if type(lines) is not list:
        raise _Invalid("invalid_project_lines")
    seen = set()
    for line in lines:
        if type(line) is not PromptLine:
            raise _Invalid("invalid_project_line")
        # Do not normalize persisted IDs: core resolution uses their exact value.
        if _id(line.id) != line.id:
            raise _Invalid("invalid_project_id")
        if line.id in seen:
            raise _Invalid("ambiguous_project_id")
        seen.add(line.id)
        if (type(line.current_text) is not str or type(line.deleted) is not bool
                or (line.line_type is not None and type(line.line_type) is not str)):
            raise _Invalid("invalid_project_line_state")
    return lines


def _normal(line):
    return not line.deleted and line.line_type not in ("separator", "workbench")


def _scenes(project):
    # This is the Gallery's active-separator semantics, including empty Scenes.
    # Deleted separators do not create active Scenes or truncate active ownership.
    for line in project.prompt_lines:
        if not line.deleted and line.line_type == "separator":
            if any(value is not None and type(value) is not str
                   for value in (line.separator_label, line.original_file_name)):
                raise _Invalid("invalid_scene_label")
            label = line.separator_label or line.current_text or line.original_file_name or line.id
            if type(label) is not str:
                raise _Invalid("invalid_scene_label")
    return operations.get_gallery_route_options(project)


def _scene_map(project):
    return {line_id: scene for scene in _scenes(project) for line_id in scene["line_ids"]}


def _limit(value):
    if type(value) is not int or not 1 <= value <= MAX_ITEMS:
        raise _Invalid("invalid_limit")
    return value


def _text(value):
    if type(value) is not str:
        raise _Invalid("invalid_project_text")
    return {"text": value[:MAX_TEXT], "truncated": len(value) > MAX_TEXT,
            "length": len(value)}


def _optional_text(value):
    return None if value is None else _text(value)


def _names(value):
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise _Invalid("invalid_project_names")
    # Only keys: opaque Module reference_assets and arbitrary metadata stay unread.
    return {"names": [_text(key) for key in sorted(value)[:MAX_ITEMS]],
            "count": len(value), "truncated": len(value) > MAX_ITEMS}


def _record_count(records, *, variants=False):
    """Count active path-bearing records, matching the Gallery/Route vocabulary."""
    if type(records) not in (list, tuple):
        return 0
    count = 0
    for record in records:
        if type(record) is not dict:
            continue
        path = record.get("path")
        if type(path) is not str or not path.strip():
            continue
        trashed = record.get("trashed")
        if trashed is not None and type(trashed) not in (str, bool, int, float):
            raise _Invalid("invalid_candidate_state")
        if trashed:
            continue
        variant_id, kind, source = record.get("id"), record.get("kind"), record.get("source")
        if variants and not ((type(kind) is str and kind == "gallery_variant")
                             or (type(source) is str and source == "batch_candidate_adoption")
                             or (type(variant_id) is str and variant_id.startswith("variant_"))):
            continue
        count += 1
    return count


def discover_capabilities():
    """Return a fresh, versioned, JSON-safe capability document."""
    return _response(capabilities={
        "observations": ["project_summary", "scenes", "illustrations", "illustration"],
        "mutations": [{"operation": OPERATION, "modes": list(REPLACE_MODES),
                       "requires_explicit_illustration_ids": True,
                       "requires_reviewed_plan": True}],
        "limits": {"items": MAX_ITEMS, "targets": MAX_TARGETS,
                   "text_chars": MAX_TEXT, "request_text_chars": MAX_REQUEST_TEXT,
                   "examples": EXAMPLE_LIMIT},
    })


def summarize_project(project: Project):
    """Counts only; no schema/metadata normalization or graph rebuilding."""
    try:
        lines = _lines(project)
        ownership = _scene_map(project)
        normal = [line for line in lines if _normal(line)]
        return _response(illustration_count=len(normal), scene_count=len(_scenes(project)),
                         baseline_illustration_count=sum(line.id not in ownership for line in normal),
                         deleted_line_count=sum(bool(line.deleted) for line in lines),
                         workbench_count=sum(not line.deleted and line.line_type == "workbench"
                                             for line in lines),
                         modules=_names(project.module_library),
                         attribute_groups=_names(project.attribute_groups),
                         candidate_count=sum(_record_count(line.generated_candidates) for line in normal),
                         variant_count=sum(_record_count(line.gallery_variants, variants=True)
                                           for line in normal))
    except _Invalid as error:
        return _response(False, error.args[0])
    except (AttributeError, TypeError, ValueError):
        return _response(False, "invalid_project_state")


def observe_scenes(project: Project, *, limit=MAX_ITEMS):
    """Observe active separator-backed Scenes in Project sequence order."""
    try:
        _lines(project)
        _limit(limit)
        scenes = _scenes(project)
        by_id = {line.id: line for line in project.prompt_lines}
        rows = [{"scene_id": scene["route_id"], "scene_order": index,
                 "label": _text(scene["route_label"]),
                 "color": _optional_text(by_id[scene["route_id"]].separator_color),
                 "illustration_count": scene["line_count"],
                 "illustration_ids": scene["line_ids"][:MAX_ITEMS],
                 "illustration_ids_truncated": len(scene["line_ids"]) > MAX_ITEMS}
                for index, scene in enumerate(scenes[:limit])]
        return _response(scenes=rows, total_count=len(scenes), truncated=len(scenes) > limit)
    except _Invalid as error:
        return _response(False, error.args[0])
    except (AttributeError, TypeError, ValueError):
        return _response(False, "invalid_project_state")


def _illustration(line, ownership, sequence_index, *, detail=False):
    scene = ownership.get(line.id)
    if type(line.edited) is not bool:
        raise _Invalid("invalid_project_line_state")
    row = {"illustration_id": line.id, "scene_id": scene["route_id"] if scene else None,
           "scene_label": _text(scene["route_label"]) if scene else None,
           "sequence_index": sequence_index, "filename": _text(line.original_file_name),
           "edited": line.edited, "positive_prompt": _text(line.current_text),
           "negative_prompt": _text(line.negative_prompt),
           "image_references": {"image_path": _optional_text(line.image_path),
                                "generated_image_path": _optional_text(line.generated_image_path),
                                "selected_candidate_path": _optional_text(line.selected_candidate_path)},
           "candidate_count": _record_count(line.generated_candidates),
           "variant_count": _record_count(line.gallery_variants, variants=True)}
    if detail:
        tokens = _json_copy(line.tokens)
        if type(tokens) is not list or any(type(token) is not str for token in tokens):
            raise _Invalid("invalid_project_tokens")
        row.update(tokens=[_text(token) for token in tokens[:MAX_ITEMS]],
                   token_count=len(tokens), tokens_truncated=len(tokens) > MAX_ITEMS)
    return row


def list_illustrations(project: Project, *, scene_id=None, limit=MAX_ITEMS):
    try:
        lines = _lines(project)
        _limit(limit)
        ownership = _scene_map(project)
        if scene_id is not None:
            scene_id = _id(scene_id)
            if scene_id not in {scene["route_id"] for scene in _scenes(project)}:
                raise _Invalid("unknown_scene_id")
        normal = [line for line in lines if _normal(line)]
        targets = [(index, line) for index, line in enumerate(normal)
                   if scene_id is None or ownership.get(line.id, {}).get("route_id") == scene_id]
        return _response(illustrations=[_illustration(line, ownership, index)
                                       for index, line in targets[:limit]],
                         total_count=len(targets), truncated=len(targets) > limit)
    except _Invalid as error:
        return _response(False, error.args[0])
    except (AttributeError, TypeError, ValueError):
        return _response(False, "invalid_project_state")


def get_illustration(project: Project, illustration_id):
    try:
        lines = _lines(project)
        target_id = _id(illustration_id)
        line = next((line for line in lines if line.id == target_id), None)
        if line is None:
            raise _Invalid("unknown_illustration_id")
        if not _normal(line):
            raise _Invalid("unsupported_illustration_target")
        sequence_index = [item.id for item in lines if _normal(item)].index(line.id)
        return _response(illustration=_illustration(line, _scene_map(project), sequence_index, detail=True))
    except _Invalid as error:
        return _response(False, error.args[0])
    except (AttributeError, TypeError, ValueError):
        return _response(False, "invalid_project_state")


def _request(value, lines):
    value = _json_copy(value)
    required = {"illustration_ids", "find_text", "replace_text"}
    optional = {"match_mode", "preserve_weights"}
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - optional:
        raise _Invalid("invalid_request_shape")
    ids = value["illustration_ids"]
    if type(ids) is not list or not 1 <= len(ids) <= MAX_TARGETS:
        raise _Invalid("explicit_illustration_ids_required")
    ids = [_id(item) for item in ids]
    if len(set(ids)) != len(ids):
        raise _Invalid("duplicate_requested_id")
    by_id = {line.id: line for line in lines}
    for target_id in ids:
        if target_id not in by_id:
            raise _Invalid("unknown_illustration_id")
        if not _normal(by_id[target_id]):
            raise _Invalid("unsupported_illustration_target")
    mode = value.get("match_mode", "exact_token")
    preserve = value.get("preserve_weights", True)
    if type(mode) is not str or mode not in REPLACE_MODES or type(preserve) is not bool:
        raise _Invalid("invalid_replace_options")
    find, replacement = value["find_text"], value["replace_text"]
    if any(type(text) is not str or len(text) > MAX_REQUEST_TEXT for text in (find, replacement)):
        raise _Invalid("invalid_replace_text")
    if not find.strip() or not replacement.strip():
        raise _Invalid("invalid_replace_text")
    validator = {"exact_token": operations.is_valid_exact_replace_target,
                 "token_set": operations.is_valid_token_set_replace_target}.get(mode)
    if validator and not validator(find, replacement):
        raise _Invalid("invalid_replace_tokens")
    if mode == "contains_token" and not operations.is_valid_replace_token(replacement):
        raise _Invalid("invalid_replace_tokens")
    selected = set(ids)
    return {"illustration_ids": [line.id for line in lines if line.id in selected],
            "find_text": find, "replace_text": replacement, "match_mode": mode,
            "preserve_weights": False if mode == "token_set" else preserve}


def _kwargs(request):
    return {"operation": "replace", "edit_text": request["replace_text"],
            "search_text": request["find_text"], "replace_match_mode": request["match_mode"],
            "preserve_replace_weights": request["preserve_weights"],
            "target_line_ids": request["illustration_ids"]}


def _source(project, request):
    return _json_copy({"request": request, "merge_by_word_only": project.merge_by_word_only,
                       "lines": [{"id": line.id, "type": line.line_type, "deleted": line.deleted,
                                  "positive_prompt": line.current_text, "tokens": line.tokens,
                                  "module_structure": [list(item) for item in
                                      operations.extract_module_structure_from_text(line.current_text)]}
                                 for line in project.prompt_lines]})


def _projection(project, request):
    kwargs = _kwargs(request)
    preview = operations.preview_batch_text_edit(project, **kwargs, example_limit=MAX_TARGETS)
    accepted = {item["line_id"]: item for item in preview["examples"]}
    targets = set(request["illustration_ids"])
    rows = []
    for line in project.prompt_lines:
        if line.id not in targets:
            continue
        # Reuse the core transform and structure guard; do not duplicate token rules.
        proposed = operations._batch_transform_text(
            line.current_text, "replace", request["replace_text"],
            search_text=request["find_text"], replace_match_mode=request["match_mode"],
            preserve_replace_weights=request["preserve_weights"],
        )
        guarded = operations._batch_text_edit_changes_module_structure(line.current_text, proposed)
        after = line.current_text if guarded else proposed
        changed = after != line.current_text
        if changed != (line.id in accepted) or (changed and accepted[line.id]["after"] != after):
            raise _Invalid("core_preview_mismatch")
        rows.append({"illustration_id": line.id, "before": line.current_text, "after": after,
                     "proposed_after": proposed, "changed": changed, "skipped": guarded,
                     "module_structure_guard": guarded})
    if (len(rows) != preview["target_line_count"]
            or sum(row["changed"] for row in rows) != preview["affected_line_count"]
            or sum(row["skipped"] for row in rows) != preview["skipped_module_structure_count"]):
        raise _Invalid("core_preview_mismatch")
    return rows


def _plan(project, value):
    lines = _lines(project)
    request = _request(value, lines)
    fingerprint = _digest(_source(project, request))
    projection = _projection(project, request)
    examples = [{**row, "before": _text(row["before"]), "after": _text(row["after"]),
                 "proposed_after": _text(row["proposed_after"])}
                for row in projection if row["changed"] or row["skipped"]][:EXAMPLE_LIMIT]
    plan = {"contract_version": CONTRACT_VERSION, "operation": OPERATION,
            "valid": True, "reason": "", "diagnostics": [], "request": request,
            "source_fingerprint": fingerprint, "projection_digest": _digest(projection),
            "target_ids": request["illustration_ids"], "target_count": len(projection),
            "affected_count": sum(row["changed"] for row in projection),
            "skipped_count": sum(row["skipped"] for row in projection),
            "unchanged_count": sum(not row["changed"] and not row["skipped"] for row in projection),
            "examples": examples, "examples_truncated": sum(row["changed"] or row["skipped"]
                                                             for row in projection) > EXAMPLE_LIMIT}
    plan["plan_id"] = _digest(plan)
    return plan, projection


def preview_batch_replace(project: Project, request):
    """Build a deterministic JSON envelope; no retained registry or side effects."""
    try:
        return _plan(project, request)[0]
    except _Invalid as error:
        reason = error.args[0]
    except Exception:
        reason = "preview_failed"
    plan = {"contract_version": CONTRACT_VERSION, "operation": OPERATION,
            "valid": False, "reason": reason, "diagnostics": [{"code": reason}],
            "request": None, "source_fingerprint": None, "projection_digest": None,
            "target_ids": [], "target_count": 0, "affected_count": 0, "skipped_count": 0,
            "unchanged_count": 0, "examples": [], "examples_truncated": False}
    plan["plan_id"] = _digest(plan)
    return plan


@dataclass(frozen=True)
class AgentApplyResult:
    """Host-only wrapper. Serialize ``agent_result`` alone, never this wrapper."""

    agent_result: dict
    updated_project: Project | None = None


def apply_batch_replace(project: Project, reviewed_plan) -> AgentApplyResult:
    """Freshness gate, clone, core Apply, and complete materialization verification."""
    try:
        plan = _json_copy(reviewed_plan)
        shape = {"contract_version", "operation", "valid", "reason", "diagnostics", "request",
                 "source_fingerprint", "projection_digest", "target_ids", "target_count",
                 "affected_count", "skipped_count", "unchanged_count", "examples",
                 "examples_truncated", "plan_id"}
        if type(plan) is not dict or plan.keys() != shape:
            raise _Invalid("invalid_plan_shape")
        if plan["contract_version"] != CONTRACT_VERSION or plan["operation"] != OPERATION:
            raise _Invalid("unsupported_plan_contract")
        unsigned = {key: value for key, value in plan.items() if key != "plan_id"}
        if type(plan["plan_id"]) is not str or plan["plan_id"] != _digest(unsigned):
            raise _Invalid("plan_tampered")
        if plan["valid"] is not True:
            raise _Invalid("invalid_reviewed_plan")
        try:
            fresh, projection = _plan(project, plan["request"])
        except _Invalid:
            raise _Invalid("stale_plan") from None
        if plan != fresh:
            raise _Invalid("stale_plan")
        if fresh["affected_count"] == 0:
            raise _Invalid("no_changes")
        updated = copy.deepcopy(project)
        updated = operations.apply_batch_text_edit(updated, **_kwargs(fresh["request"]))
        if updated is project or type(updated) is not Project:
            raise _Invalid("apply_materialization_mismatch")
        after_lines = _lines(updated)
        if [line.id for line in after_lines] != [line.id for line in project.prompt_lines]:
            raise _Invalid("apply_materialization_mismatch")
        by_id = {line.id: line for line in after_lines}
        projected = {row["illustration_id"]: row for row in projection}
        for before in project.prompt_lines:
            after = by_id[before.id]
            row = projected.get(before.id)
            expected = row["after"] if row else before.current_text
            expected_tokens = parse_prompt(expected) if row and row["changed"] else before.tokens
            expected_edited = True if row and row["changed"] else before.edited
            if (after.current_text != expected or after.tokens != expected_tokens
                    or after.edited != expected_edited
                    or after.line_type != before.line_type or after.deleted != before.deleted):
                raise _Invalid("apply_materialization_mismatch")
        return AgentApplyResult(_response(plan_id=plan["plan_id"], applied=True,
                                         affected_count=fresh["affected_count"],
                                         skipped_count=fresh["skipped_count"]), updated)
    except _Invalid as error:
        return AgentApplyResult(_response(False, error.args[0], applied=False))
    except Exception:
        return AgentApplyResult(_response(False, "apply_failed", applied=False))
