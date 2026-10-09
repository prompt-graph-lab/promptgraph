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

from core import module_swap_selected_routes, operations
from core.parser import parse_prompt
from core.project import Project, PromptLine
from core import candidate_inspection, candidate_observation_handles


CONTRACT_VERSION = "promptgraph.agent-facade.v1"
OPERATION = "batch_replace"
MAX_ITEMS = 100
MAX_CANDIDATE_RECORDS = 1000
MAX_CANDIDATE_SNAPSHOT_NODES = 20000
MAX_CANDIDATE_SNAPSHOT_CHARS = 1000000
MAX_GENERATION_RUNS = 5
MAX_GENERATION_REQUESTS = 100
MAX_TARGETS = 1000
MAX_TEXT = 4000
MAX_REQUEST_TEXT = 10000
EXAMPLE_LIMIT = 5
REPLACE_MODES = ("exact_token", "contains_token", "literal", "token_set")
SEARCH_MODES = ("exact_token", "contains_token", "literal")
SCENE_MODULE_SWAP_MODES = ("strict", "loose")
SCENE_MODULE_SWAP_OPERATION = "scene_module_swap"
_SCENE_MODULE_SWAP_KIND_CODES = {"body_tokens": "body_tokens", "reference": "module_reference"}
_SCENE_MODULE_SWAP_DRIFT_CODES = {
    "no prompt change": "no_prompt_change",
    "image reference unavailable": "image_reference_unavailable",
    "prompt changed, no representative image": "no_representative_image",
    "positive and negative changed while main image remains unchanged": "prompt_changed_image_unchanged",
    "prompt changed while main image remains unchanged": "prompt_changed_image_unchanged",
}


class _Invalid(ValueError):
    pass


def _json_copy(value: Any, *, node_limit=100000, text_limit=None) -> Any:
    """Accept built-in JSON values only; never call a supplied object's hooks."""
    remaining = node_limit
    remaining_text = text_limit
    active = set()

    def visit(item, depth):
        nonlocal remaining, remaining_text
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise _Invalid("json_bounds_exceeded")
        kind = type(item)
        if kind in (str, int, bool) or item is None:
            if kind is str:
                if remaining_text is not None:
                    remaining_text -= len(item)
                    if remaining_text < 0:
                        raise _Invalid("json_bounds_exceeded")
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
        if text_limit is not None and len(item) > remaining:
            raise _Invalid("json_bounds_exceeded")
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
        "observations": ["project_summary", "scenes", "illustrations", "illustration",
                         "illustration_search", "candidates", "candidate"],
        "candidate_observation": {"read_only": True, "persistent_records_only": True,
                                  "image_availability": "unknown", "image_bytes": False,
                                  "max_collection_records": MAX_CANDIDATE_RECORDS,
                                  "max_snapshot_nodes": MAX_CANDIDATE_SNAPSHOT_NODES,
                                  "max_snapshot_chars": MAX_CANDIDATE_SNAPSHOT_CHARS},
        "generation_preview": {"read_only": True, "requires_host_configuration": True,
                               "max_run_count": MAX_GENERATION_RUNS,
                               "max_requests": MAX_GENERATION_REQUESTS,
                               "shared_workflow_only": True,
                               "review_request_available": True, "review_request_requires_paired_host": True,
                               "review_ui_available": False, "execution_available": False},
        "illustration_search": {"modes": list(SEARCH_MODES), "max_results": MAX_ITEMS,
                                "query_text_chars": MAX_REQUEST_TEXT},
        "mutations": [
            {"operation": OPERATION, "modes": list(REPLACE_MODES),
             "requires_explicit_illustration_ids": True,
             "requires_reviewed_plan": True},
            {"operation": SCENE_MODULE_SWAP_OPERATION,
             "modes": list(SCENE_MODULE_SWAP_MODES),
             "requires_explicit_scene_id": True,
             "requires_explicit_source_module_name": True,
             "requires_explicit_target_module_name": True,
             "requires_reviewed_preview_before_host_apply": True},
        ],
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


def _illustration_targets(project, lines, scene_id=None):
    ownership = _scene_map(project)
    if scene_id is not None:
        scene_id = _id(scene_id)
        if scene_id not in {scene["route_id"] for scene in _scenes(project)}:
            raise _Invalid("unknown_scene_id")
    normal = [line for line in lines if _normal(line)]
    targets = [(index, line) for index, line in enumerate(normal)
               if scene_id is None or ownership.get(line.id, {}).get("route_id") == scene_id]
    return ownership, targets


def list_illustrations(project: Project, *, scene_id=None, limit=MAX_ITEMS):
    try:
        lines = _lines(project)
        _limit(limit)
        ownership, targets = _illustration_targets(project, lines, scene_id)
        return _response(illustrations=[_illustration(line, ownership, index)
                                       for index, line in targets[:limit]],
                         total_count=len(targets), truncated=len(targets) > limit)
    except _Invalid as error:
        return _response(False, error.args[0])
    except (AttributeError, TypeError, ValueError):
        return _response(False, "invalid_project_state")


def search_illustrations(project: Project, query_text, *, match_mode="exact_token",
                         scene_id=None, limit=MAX_ITEMS):
    """Count and list bounded matches among active Illustrations, read-only."""
    try:
        lines = _lines(project)
        if (type(query_text) is not str or len(query_text) > MAX_REQUEST_TEXT
                or not query_text.strip()):
            raise _Invalid("invalid_search_query")
        if type(match_mode) is not str or match_mode not in SEARCH_MODES:
            raise _Invalid("invalid_search_mode")
        _limit(limit)
        ownership, targets = _illustration_targets(project, lines, scene_id)
        matches = []
        total_count = 0
        for sequence_index, line in targets:
            if not operations.prompt_text_matches(line.current_text, query_text, match_mode):
                continue
            total_count += 1
            if len(matches) < limit:
                scene = ownership.get(line.id)
                matches.append({
                    "illustration_id": line.id,
                    "scene_id": scene["route_id"] if scene else None,
                    "sequence_index": sequence_index,
                })
        return _response(match_mode=match_mode, matches=matches,
                         total_count=total_count, truncated=total_count > limit)
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


def _candidate_rows(project, illustration_id, binding):
    lines = _lines(project)
    target_id = _id(illustration_id)
    if target_id != illustration_id:
        raise _Invalid("invalid_id")
    line = next((item for item in lines if item.id == target_id), None)
    if line is None:
        raise _Invalid("unknown_illustration_id")
    if not _normal(line):
        raise _Invalid("unsupported_illustration_target")
    if type(line.generated_candidates) is not list:
        raise _Invalid("invalid_candidate_records")
    if len(line.generated_candidates) > MAX_CANDIDATE_RECORDS:
        raise _Invalid("candidate_collection_too_large")
    # Hash full persistent input privately, including order/Trash/unknown fields.
    # No hash or raw path crosses the boundary; handles are keyed opaque values.
    if len(lines) * 4 > MAX_CANDIDATE_SNAPSHOT_NODES:
        raise _Invalid("candidate_observation_bounds_exceeded")
    try:
        snapshot = _json_copy({
            "structure": [[item.id, item.line_type, item.deleted] for item in lines],
            "illustration": [line.id, line.current_text, line.negative_prompt,
                             line.selected_candidate_path, line.generated_image_path,
                             line.image_path, line.source_generation_info, line.lineage_info],
            "records": line.generated_candidates,
        }, node_limit=MAX_CANDIDATE_SNAPSHOT_NODES,
           text_limit=MAX_CANDIDATE_SNAPSHOT_CHARS)
    except _Invalid as error:
        if error.args[0] == "json_bounds_exceeded":
            raise _Invalid("candidate_observation_bounds_exceeded") from None
        raise
    revision = _digest(snapshot)
    records = snapshot["records"]
    if binding is None:
        binding = candidate_observation_handles.project_identity(project)
    else:
        binding = _json_copy(binding)
    rows = []
    for index, record in enumerate(records):
        if type(record) is str:
            if not record.strip():
                raise _Invalid("invalid_candidate_record")
            candidate = {"path": record}
        elif type(record) is dict:
            candidate = record
            if type(candidate.get("path")) is not str or not candidate["path"].strip():
                raise _Invalid("invalid_candidate_record")
            for flag in ("pinned", "trashed"):
                value = candidate.get(flag)
                if value is not None and type(value) not in (bool, str, int, float):
                    raise _Invalid("invalid_candidate_state")
        else:
            raise _Invalid("invalid_candidate_record")
        pinned = candidate_inspection._candidate_is_pinned(candidate)
        trashed = candidate_inspection._candidate_is_trashed(candidate)
        # Only these authored prompt fields are projected; nested/raw workflow
        # and arbitrary metadata stay private. Preserve existing source gate.
        safe_prompt = {key: candidate[key] for key in (
            "source", "candidate_prompt_source", "prompt_text", "positive_prompt",
            "source_prompt", "negative_prompt", "source_negative_prompt", "negative")
            if key in candidate and candidate[key] is not None}
        if any(type(value) is not str for value in safe_prompt.values()):
            raise _Invalid("invalid_candidate_metadata")
        metadata = candidate_inspection._candidate_prompt_metadata(safe_prompt)
        for key in ("positive_prompt", "negative_prompt"):
            text = metadata.get(key, "")
            if candidate_inspection._looks_like_workflow_json_prompt(text):
                metadata[key] = ""
        seed = candidate.get("seed")
        if seed is not None and (type(seed) is not int or not -(2**63) <= seed < 2**64):
            raise _Invalid("invalid_candidate_metadata")
        source = candidate.get("source")
        source = source if type(source) is str and source in {
            "manual_import", "gallery_global_generate", "focus_generate",
            "single_generate", "multi_generate", "gallery_generate",
            "main_image_retreat", "batch_candidate_adoption"} else "unknown"
        row = {"candidate_handle": candidate_observation_handles.sign_candidate(binding, revision, index),
               "illustration_id": line.id, "pinned": pinned, "trashed": trashed,
               "selected": candidate["path"] == candidate_inspection._selected_candidate_path(line),
               "legacy_record": type(record) is str, "source": source, "seed": seed,
               "positive_prompt": _text(metadata.get("positive_prompt", "")),
               "negative_prompt": _text(metadata.get("negative_prompt", "")),
               "image_availability": "unknown"}
        rows.append((index, row))
    return [row for index, row in sorted(rows, key=lambda item: (not item[1]["pinned"], item[0]))]


def list_candidates(project, illustration_id, *, limit=MAX_ITEMS, include_trashed=False,
                    observation_binding=None):
    """Observe persistent records only; never reconcile UI caches or probe files."""
    try:
        _limit(limit)
        if type(include_trashed) is not bool:
            raise _Invalid("invalid_include_trashed")
        rows = _candidate_rows(project, illustration_id, observation_binding)
        rows = [row for row in rows if include_trashed or not row["trashed"]]
        return _response(candidates=rows[:limit], total_count=len(rows),
                         truncated=len(rows) > limit, persistent_records_only=True)
    except _Invalid as error:
        return _response(False, error.args[0])
    except (AttributeError, TypeError, ValueError):
        return _response(False, "invalid_project_state")


def get_candidate(project, illustration_id, candidate_handle, *, include_trashed=False,
                  observation_binding=None):
    try:
        if (type(candidate_handle) is not str or len(candidate_handle) != 74
                or not candidate_handle.startswith("candidate_")
                or any(char not in "0123456789abcdef" for char in candidate_handle[10:])):
            raise _Invalid("invalid_candidate_handle")
        if type(include_trashed) is not bool:
            raise _Invalid("invalid_include_trashed")
        rows = _candidate_rows(project, illustration_id, observation_binding)
        row = next((item for item in rows if item["candidate_handle"] == candidate_handle
                    and (include_trashed or not item["trashed"])), None)
        if row is None:
            raise _Invalid("unknown_or_stale_candidate_handle")
        return _response(candidate=row, persistent_records_only=True)
    except _Invalid as error:
        return _response(False, error.args[0])
    except (AttributeError, TypeError, ValueError):
        return _response(False, "invalid_project_state")


def generation_preview_project_state(project):
    """Private semantic freshness snapshot; never a transport projection."""
    lines = _lines(project)
    if len(lines) > MAX_TARGETS:
        raise _Invalid("generation_target_limit_exceeded")
    return _json_copy({"modules": project.module_library, "metadata": project.project_metadata,
                      "source_directory": project.source_directory,
                      "lines": [[line.id, line.original_file_name, line.line_type, line.deleted, line.separator_label,
                                 line.separator_color, line.current_text, line.negative_prompt,
                                 line.tokens, line.source_generation_info, line.generated_candidates]
                                for line in lines]}, node_limit=20000, text_limit=1000000)


def preview_generation(project, scene_id, *, run_count=1, host_context_provider=None,
                       observation_binding=None):
    """Preflight one explicit Scene through host configuration, never execute."""
    from core.gallery_generation import build_selected_routes_generation_plan
    from core.comfy_workflow_metadata import _is_executable_comfy_workflow
    from core.comfy_workflow_outputs import _workflow_output_nodes, _workflow_save_image_nodes
    try:
        lines = _lines(project)
        target = _id(scene_id)
        if target != scene_id:
            raise _Invalid("invalid_id")
        if type(run_count) is not int or not 1 <= run_count <= MAX_GENERATION_RUNS:
            raise _Invalid("invalid_generation_run_count")
        scenes = _scenes(project)
        scene = next((item for item in scenes if item["route_id"] == target), None)
        if scene is None:
            raise _Invalid("unknown_scene_id")
        target_ids = set(scene["line_ids"])
        eligible = [line for line in lines if line.id in target_ids and _normal(line)]
        if not eligible:
            raise _Invalid("no_generation_targets")
        if len(eligible) * run_count > MAX_GENERATION_REQUESTS or len(lines) > MAX_TARGETS:
            raise _Invalid("generation_target_limit_exceeded")
        source_state = generation_preview_project_state(project)
        if host_context_provider is None:
            raise _Invalid("generation_host_unavailable")
        context = host_context_provider(project, run_count)
        if type(context) is not dict or not callable(context.get("request_builder")):
            raise _Invalid("invalid_generation_host_context")
        options = _json_copy(context.get("generation_options"), node_limit=20000, text_limit=1000000)
        if type(options) is not dict:
            raise _Invalid("invalid_generation_host_context")
        prepared = {}
        workflow_budget = 8 * 1024 * 1024
        def build(line, index):
            nonlocal workflow_budget
            if workflow_budget <= 0:
                raise ValueError("workflow plan budget exhausted")
            item = context["request_builder"](line, index)
            if type(item) is not dict:
                raise ValueError("invalid preflight")
            workflow = _json_copy(item.get("workflow_json"), node_limit=20000, text_limit=1000000)
            workflow_budget -= len(json.dumps(workflow, ensure_ascii=False, allow_nan=False).encode("utf-8"))
            if workflow_budget < 0:
                raise ValueError("workflow plan too large")
            if not _is_executable_comfy_workflow(workflow):
                raise ValueError("unsupported workflow")
            if any(type(node) is not dict or type(node.get("inputs")) is not dict
                   or type(node.get("class_type")) is not str or not node["class_type"]
                   for node in workflow.values()):
                raise ValueError("unsupported API workflow")
            output_count = len(_workflow_output_nodes(workflow))
            if not output_count:
                raise ValueError("no image output")
            positive = item.get("resolved_positive_prompt")
            negative = item.get("resolved_negative_prompt")
            if type(positive) is not str or type(negative) is not str:
                raise ValueError("invalid prompts")
            prepared[line.id] = {"positive_prompt": _text(positive), "negative_prompt": _text(negative),
                                 "prompt_summary_kind": "active_illustration_inputs", "workflow_binding_verified": False,
                                 "workflow_node_count": len(workflow), "image_output_node_count": output_count,
                                 "save_image_node_count": len(_workflow_save_image_nodes(workflow)),
                                 "warnings": ["prompt_binding_requires_review"] if item.get("warning") else []}
            return workflow, ""
        plan = build_selected_routes_generation_plan(
            project, [target], run_count=run_count, generation_options=options,
            project_path=context.get("project_path", ""), request_builder=build, example_limit=MAX_ITEMS)
        # Re-read host configuration/file identity after all preflight, without
        # retaining any plan or changing the configured generation operation.
        fresh = host_context_provider(project, run_count)
        if (type(fresh) is not dict or _json_copy(fresh.get("generation_options"),
                node_limit=20000, text_limit=1000000) != options
                or fresh.get("project_path", "") != context.get("project_path", "")):
            raise _Invalid("generation_configuration_changed")
        if generation_preview_project_state(project) != source_state:
            raise _Invalid("generation_project_changed")
        rows = []
        for entry in plan["line_entries"]:
            line_id = entry["line_id"]
            rows.append({"illustration_id": line_id, "project_order": entry["project_order"],
                         "authored_positive_prompt": _text(entry["prompt"]),
                         "authored_negative_prompt": _text(entry["negative_prompt"]),
                         "eligible": not bool(entry["blocked_reason"]),
                         "blocker": "workflow_preflight_failed" if entry["blocked_reason"] else "",
                         **prepared.get(line_id, {})})
        binding = (candidate_observation_handles.project_identity(project)
                   if observation_binding is None else _json_copy(observation_binding))
        return _response(valid=bool(plan["valid"]), scene_id=target, scene_label=_text(scene["route_label"]),
                         run_count=run_count, target_count=plan["target_line_count"],
                         request_count=plan["request_count"] if plan["valid"] else 0,
                         expected_image_count=plan["expected_image_count"] if plan["valid"] else 0,
                         output_count_is_estimate=True, illustrations=rows,
                         expected_output_node_count=(sum(item["image_output_node_count"] for item in prepared.values()) * run_count
                                                     if plan["valid"] else 0),
                         skipped_count=plan["skipped_line_count"], blocked_count=plan["blocked_line_count"],
                         skipped=[{"illustration_id": item["line_id"],
                                   "reason": "workbench" if item["reason"] == "Workbench line" else "deleted"}
                                  for item in plan["skipped_lines"][:MAX_ITEMS]],
                         skipped_truncated=plan["skipped_line_count"] > MAX_ITEMS,
                         plan_id=_digest([plan["signature"], binding]),
                         workflow_summary={"source": "host_configured", "endpoint": "host_configured"},
                         warnings=["preview_only_no_job_submitted", "image_count_is_estimate",
                                   "execution_seeds_not_committed", "workflow_bindings_not_certified"],
                         blockers=[] if plan["valid"] else ["workflow_preflight_failed"],
                         review_requested=False, job_submitted=False)
    except _Invalid as error:
        return _response(False, error.args[0])
    except Exception:
        # Host/workflow diagnostics can contain paths, credentials or JSON.
        return _response(False, "generation_preflight_unavailable")


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


def _scene_module_swap_invalid(reason, *, request=None, scene_id=None, scene_label=None):
    plan = {
        "contract_version": CONTRACT_VERSION,
        "operation": SCENE_MODULE_SWAP_OPERATION,
        "valid": False,
        "reason": reason,
        "diagnostics": [{"code": reason}],
        "request": request,
        "source_fingerprint": None,
        "projection_digest": None,
        "plan_id": "",
        "scene_id": scene_id,
        "scene_label": _text(scene_label) if type(scene_label) is str else None,
        "target_ids": [],
        "target_count": 0,
        "changed_count": 0,
        "no_op_count": 0,
        "skipped_count": 0,
        "blocked_count": 0,
        "drift_count": 0,
        "prompt_only": True,
        "negative_prompt_semantics": "unchanged_by_module_swap",
        "review_rows": [],
        "review_rows_truncated": False,
        "review_rows_omitted": 0,
    }
    plan["plan_id"] = _digest({key: value for key, value in plan.items() if key != "plan_id"})
    return plan


def _scene_module_swap_request(value):
    copied = _json_copy(value)
    required = {"scene_id", "source_module_name", "target_module_name"}
    optional = {"match_mode"}
    if type(copied) is not dict or not required <= copied.keys() or copied.keys() - required - optional:
        raise _Invalid("invalid_request_shape")
    normalized = {}
    for field_name in ("scene_id", "source_module_name", "target_module_name"):
        field_value = copied[field_name]
        if (type(field_value) is not str or not field_value or len(field_value) > 200
                or field_value != field_value.strip()):
            raise _Invalid("invalid_" + field_name)
        try:
            field_value.encode("utf-8")
        except UnicodeError:
            raise _Invalid("invalid_" + field_name) from None
        normalized[field_name] = field_value
    if normalized["source_module_name"] == normalized["target_module_name"]:
        raise _Invalid("same_module")
    mode = copied.get("match_mode", "strict")
    if type(mode) is not str or mode not in SCENE_MODULE_SWAP_MODES:
        raise _Invalid("invalid_match_mode")
    normalized["match_mode"] = mode
    return normalized


def _scene_module_swap_project_state(project):
    lines = _lines(project)
    if type(project.source_directory) not in (str, type(None)):
        raise _Invalid("invalid_project_state")
    for line in lines:
        if line.line_type == "separator" and any(
                type(value) not in (str, type(None))
                for value in (line.separator_label, line.separator_color)):
            raise _Invalid("invalid_project_state")
    library = project.module_library
    if type(library) is not dict:
        raise _Invalid("invalid_project_state")
    try:
        library = _json_copy(library)
    except _Invalid:
        raise _Invalid("invalid_project_state") from None
    return lines, library


def _scene_module_swap_module(library, name, reason):
    if name not in library:
        raise _Invalid(reason)
    record = library[name]
    if type(record) is not dict:
        raise _Invalid("malformed_module")
    if ("body" in record and type(record["body"]) is not str) or (
            "type" in record and type(record["type"]) is not str):
        raise _Invalid("malformed_module")


def _scene_module_swap_projection(plan, target_ids):
    entries = plan.get("entries")
    if type(entries) is not list or len(entries) != len(target_ids):
        raise _Invalid("module_swap_preview_failed")
    projection = []
    for order, (target_id, entry) in enumerate(zip(target_ids, entries, strict=True)):
        if type(entry) is not dict or entry.get("line_id") != target_id:
            raise _Invalid("module_swap_preview_failed")
        before = entry.get("before_positive_prompt")
        after = entry.get("after_positive_prompt")
        after_tokens = entry.get("after_tokens")
        added = entry.get("positive_added_tokens")
        removed = entry.get("positive_removed_tokens")
        if (type(before) is not str or type(after) is not str
                or type(after_tokens) is not list
                or any(type(token) is not str for token in after_tokens)
                or type(added) is not list or any(type(token) is not str for token in added)
                or type(removed) is not list or any(type(token) is not str for token in removed)
                or type(entry.get("positive_changed")) is not bool
                or type(entry.get("negative_changed")) is not bool
                or type(entry.get("no_op")) is not bool
                or type(entry.get("match_count")) is not int):
            raise _Invalid("invalid_project_state")
        swap_kind = entry.get("swap_kind", "")
        if type(swap_kind) is not str:
            raise _Invalid("module_swap_preview_failed")
        drift_risk = entry.get("drift_risk", "")
        if type(drift_risk) is not str:
            raise _Invalid("module_swap_preview_failed")
        projection.append({
            "illustration_id": target_id,
            "scene_order": order,
            "before_positive_prompt": before,
            "after_positive_prompt": after,
            "after_tokens": after_tokens,
            "changed": entry["positive_changed"] or entry["negative_changed"],
            "no_op": entry["no_op"],
            "match_count": entry["match_count"],
            "swap_kind": _SCENE_MODULE_SWAP_KIND_CODES.get(swap_kind, "unknown"),
            "positive_added_tokens": added,
            "positive_removed_tokens": removed,
            "negative_prompt_unchanged": True,
            "drift_risk": _SCENE_MODULE_SWAP_DRIFT_CODES.get(drift_risk, "unknown"),
        })
    try:
        return _json_copy(projection)
    except _Invalid:
        raise _Invalid("invalid_project_state") from None


def _scene_module_swap_review_row(row):
    added = row["positive_added_tokens"]
    removed = row["positive_removed_tokens"]
    return {
        "illustration_id": row["illustration_id"],
        "scene_order": row["scene_order"],
        "before_positive_prompt": _text(row["before_positive_prompt"]),
        "after_positive_prompt": _text(row["after_positive_prompt"]),
        "changed": row["changed"],
        "no_op": row["no_op"],
        "token_delta": {
            "added": [_text(token) for token in added[:MAX_ITEMS]],
            "removed": [_text(token) for token in removed[:MAX_ITEMS]],
            "added_count": len(added),
            "removed_count": len(removed),
            "added_truncated": len(added) > MAX_ITEMS,
            "removed_truncated": len(removed) > MAX_ITEMS,
        },
        "match_count": row["match_count"],
        "swap_kind": row["swap_kind"],
        "drift_risk": row["drift_risk"],
    }


def _preview_scene_module_swap_for_host_review(project: Project, request):
    """Return the safe facade envelope and its ephemeral host-only planner result.

    The raw plan stays inside the Python host boundary so the human review UI
    can inspect every target without rebuilding the expensive planner result.
    MCP callers continue to use preview_scene_module_swap(), which returns
    only the safe envelope.
    """
    normalized = None
    scene_id = None
    scene_label = None
    try:
        normalized = _scene_module_swap_request(request)
        scene_id = normalized["scene_id"]
        lines, library = _scene_module_swap_project_state(project)
        by_id = {line.id: line for line in lines}
        selected_separator = by_id.get(scene_id)
        if selected_separator is None:
            raise _Invalid("unknown_scene_id")
        if selected_separator.deleted or selected_separator.line_type != "separator":
            raise _Invalid("invalid_scene_id")
        scene = next((item for item in _scenes(project) if item["route_id"] == scene_id), None)
        if scene is None:
            raise _Invalid("invalid_scene_id")
        scene_label = scene["route_label"]
        if type(scene_label) is not str:
            raise _Invalid("invalid_project_state")
        target_ids = scene["line_ids"]
        if type(target_ids) is not list or any(type(item) is not str for item in target_ids):
            raise _Invalid("invalid_project_state")
        if len(target_ids) > MAX_TARGETS:
            raise _Invalid("target_limit_exceeded")
        if not target_ids:
            raise _Invalid("no_scene_targets")
        _scene_module_swap_module(library, normalized["source_module_name"],
                                  "unknown_source_module")
        _scene_module_swap_module(library, normalized["target_module_name"],
                                  "unknown_target_module")
        for target_id in target_ids:
            line = by_id.get(target_id)
            if line is None or line.deleted or line.line_type in ("separator", "workbench"):
                raise _Invalid("invalid_project_state")
            if (type(line.current_text) is not str or type(line.negative_prompt) is not str
                    or type(line.tokens) is not list
                    or any(type(token) is not str for token in line.tokens)
                    or type(line.original_file_name) is not str
                    or type(line.original_index) is not int
                    or type(line.current_index) is not int
                    or any(type(getattr(line, field)) not in (str, type(None))
                           for field in ("selected_candidate_path", "generated_image_path", "image_path"))):
                raise _Invalid("invalid_project_state")
        plan = module_swap_selected_routes.build_selected_routes_module_swap_plan(
            project,
            [scene_id],
            source_module_name=normalized["source_module_name"],
            target_module_name=normalized["target_module_name"],
            match_mode=normalized["match_mode"],
            project_path="",
            disabled_modules=None,
            preview_func=operations.preview_module_swap,
        )
        if type(plan) is not dict:
            raise _Invalid("module_swap_preview_failed")
        if plan.get("valid") is not True:
            planner_reason = plan.get("reason")
            if planner_reason == "Source or replacement Module is empty":
                raise _Invalid("module_without_usable_tokens")
            if planner_reason == "Selected Routes have no Module Swap target Lines":
                raise _Invalid("no_scene_targets")
            raise _Invalid("module_swap_preview_failed")
        if (plan.get("selected_route_ids") != [scene_id]
                or plan.get("selected_route_count") != 1):
            raise _Invalid("module_swap_preview_failed")
        planner_target_ids = plan.get("target_line_ids")
        if (type(planner_target_ids) is not list
                or any(type(item) is not str for item in planner_target_ids)
                or len(planner_target_ids) > MAX_TARGETS
                or any(item not in target_ids for item in planner_target_ids)):
            raise _Invalid("module_swap_preview_failed")
        if not planner_target_ids:
            raise _Invalid("no_scene_targets")
        projection = _scene_module_swap_projection(plan, planner_target_ids)
        source_fingerprint = plan.get("source_fingerprint")
        if (type(source_fingerprint) is not str or len(source_fingerprint) != 64
                or any(char not in "0123456789abcdef" for char in source_fingerprint)):
            raise _Invalid("module_swap_preview_failed")
        changed_count = sum(item["changed"] for item in projection)
        no_op_count = sum(item["no_op"] for item in projection)
        if (changed_count != plan.get("changed_line_count")
                or no_op_count != plan.get("no_op_count")
                or changed_count + no_op_count != len(projection)):
            raise _Invalid("module_swap_preview_failed")
        projection_digest = _digest(projection)
        envelope = {
            "contract_version": CONTRACT_VERSION,
            "operation": SCENE_MODULE_SWAP_OPERATION,
            "valid": True,
            "reason": "",
            "diagnostics": [],
            "request": normalized,
            "source_fingerprint": source_fingerprint,
            "projection_digest": projection_digest,
            "plan_id": "",
            "scene_id": scene_id,
            "scene_label": _text(scene_label),
            "target_ids": list(planner_target_ids),
            "target_count": len(projection),
            "changed_count": changed_count,
            "no_op_count": no_op_count,
            "skipped_count": int(plan.get("skipped_count", 0)),
            "blocked_count": int(plan.get("blocked_count", 0)),
            "drift_count": int(plan.get("drift_count", 0)),
            "prompt_only": True,
            "negative_prompt_semantics": "unchanged_by_module_swap",
            "review_rows": [_scene_module_swap_review_row(row)
                            for row in projection[:MAX_ITEMS]],
            "review_rows_truncated": len(projection) > MAX_ITEMS,
            "review_rows_omitted": max(0, len(projection) - MAX_ITEMS),
        }
        envelope["plan_id"] = _digest({key: value for key, value in envelope.items()
                                       if key != "plan_id"})
        return envelope, plan
    except _Invalid as error:
        return (
            _scene_module_swap_invalid(
                error.args[0], request=normalized,
                scene_id=scene_id, scene_label=scene_label,
            ),
            None,
        )
    except Exception:
        return (
            _scene_module_swap_invalid(
                "module_swap_preview_failed", request=normalized,
                scene_id=scene_id, scene_label=scene_label,
            ),
            None,
        )


def preview_scene_module_swap(project: Project, request):
    """Create a safe, bounded single-Scene Module Swap review Preview."""

    envelope, _host_plan = _preview_scene_module_swap_for_host_review(project, request)
    return envelope


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
