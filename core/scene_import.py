"""Pure, read-only Preview planning for cross-Project Scene imports."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from core.parser import parse_prompt
from core.project import Project, PromptLine
from core.scene_portability import (
    project_portable_module_definition,
    project_scene_portability_payload,
)


SCENE_IMPORT_PREVIEW_CONTRACT_VERSION = "promptgraph.scene-import-preview.v1"
SCENE_IMPORT_PREVIEW_OPERATION = "scene_import"
_MAX_ID_CHARS = 1024
_MAX_TARGET_LINES = 100_000
_MAX_JSON_NODES = 20_000
_MAX_JSON_STRING_CHARS = 500_000
_MAX_JSON_DEPTH = 128
_MAX_DIAGNOSTICS = 16
_ID_COLLISION_ATTEMPTS = 128


def _empty_result() -> dict[str, Any]:
    return {
        "contract_version": SCENE_IMPORT_PREVIEW_CONTRACT_VERSION,
        "operation": SCENE_IMPORT_PREVIEW_OPERATION,
        "valid": False,
        "eligible": False,
        # Set only after the source projection validates the handle. In
        # particular, never echo an invalid path-shaped input identifier.
        "source_separator_id": None,
        "source_scene_fingerprint": None,
        "target_freshness_fingerprint": None,
        "target_line_count": None,
        "insertion_index": None,
        "planned_separator": None,
        "planned_illustrations": [],
        "resulting_scene_block_order": [],
        "source_to_target_map": None,
        "module_actions": [],
        "planned_receipt": None,
        "planned_receipt_append_index": None,
        "projection_digest": None,
        "plan_id": None,
        "blockers": [],
        "diagnostics": [],
    }


def _block(result: dict[str, Any], code: str) -> None:
    blockers = result["blockers"]
    if code not in blockers and len(blockers) < _MAX_DIAGNOSTICS:
        blockers.append(code)
    diagnostics = result["diagnostics"]
    if not any(item.get("code") == code for item in diagnostics) and len(diagnostics) < _MAX_DIAGNOSTICS:
        diagnostics.append({"code": code})


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_json_copy(value: Any) -> Any:
    """Validate/copy persisted JSON values with bounded traversal and cycles rejected."""
    active: set[int] = set()
    stats = {"nodes": 0, "string_chars": 0}

    def visit(item: Any, depth: int) -> Any:
        if depth > _MAX_JSON_DEPTH:
            raise ValueError("unsupported_target_json")
        stats["nodes"] += 1
        if stats["nodes"] > _MAX_JSON_NODES:
            raise ValueError("unsupported_target_json")
        if type(item) is str:
            stats["string_chars"] += len(item)
            if stats["string_chars"] > _MAX_JSON_STRING_CHARS:
                raise ValueError("unsupported_target_json")
            return item
        if item is None or type(item) in (bool, int):
            return item
        if type(item) is float:
            if not math.isfinite(item):
                raise ValueError("unsupported_target_json")
            return item
        if type(item) not in (dict, list):
            raise ValueError("unsupported_target_json")
        identity = id(item)
        if identity in active:
            raise ValueError("unsupported_target_json")
        active.add(identity)
        try:
            if type(item) is list:
                return [visit(child, depth + 1) for child in item]
            copied: dict[str, Any] = {}
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("unsupported_target_json")
                stats["string_chars"] += len(key)
                if stats["string_chars"] > _MAX_JSON_STRING_CHARS:
                    raise ValueError("unsupported_target_json")
                copied[key] = visit(child, depth + 1)
            return copied
        finally:
            active.remove(identity)

    return visit(value, 0)


def _target_line_state(project: Project) -> tuple[list[dict[str, Any]] | None, set[str], str | None]:
    lines = project.prompt_lines
    if type(lines) is not list or len(lines) > _MAX_TARGET_LINES:
        return None, set(), "malformed_target_lines"
    state: list[dict[str, Any]] = []
    ids: set[str] = set()
    for line in lines:
        if type(line) is not PromptLine:
            return None, set(), "malformed_target_lines"
        values = vars(line)
        line_id = values.get("id")
        if (
            type(line_id) is not str
            or not line_id
            or line_id != line_id.strip()
            or len(line_id) > _MAX_ID_CHARS
        ):
            return None, set(), "invalid_target_line_id"
        if line_id in ids:
            return None, set(), "ambiguous_target_line_id"
        ids.add(line_id)

        line_type = values.get("line_type")
        deleted = values.get("deleted", False)
        if (line_type is not None and type(line_type) is not str) or type(deleted) is not bool:
            return None, set(), "malformed_target_line_state"
        original_index = values.get("original_index")
        current_index = values.get("current_index")
        if any(value is not None and type(value) is not int for value in (original_index, current_index)):
            return None, set(), "malformed_target_line_state"
        original_text = values.get("original_text")
        current_text = values.get("current_text")
        negative_prompt = values.get("negative_prompt", "")
        tokens = values.get("tokens")
        edited = values.get("edited", False)
        if (
            type(original_text) is not str
            or type(current_text) is not str
            or type(negative_prompt) is not str
            or type(tokens) is not list
            or any(type(token) is not str for token in tokens)
            or type(edited) is not bool
        ):
            return None, set(), "malformed_target_line_state"
        row = {
            "id": line_id,
            "original_file_name": values.get("original_file_name") if type(values.get("original_file_name")) is str else None,
            "line_type": line_type,
            "deleted": deleted,
            "original_index": original_index,
            "current_index": current_index,
            "original_text": original_text,
            "current_text": current_text,
            "negative_prompt": negative_prompt,
            "tokens": list(tokens),
            "edited": edited,
        }
        if line_type == "separator":
            for field in ("separator_label", "separator_color"):
                value = values.get(field)
                if value is not None and type(value) is not str:
                    return None, set(), "malformed_target_line_state"
                row[field] = value
        state.append(row)
    return state, ids, None


def _receipt_state(project: Project) -> tuple[list[dict[str, Any]] | None, set[str], str | None]:
    metadata = project.project_metadata
    if type(metadata) is not dict:
        return None, set(), "malformed_receipt_namespace"
    raw_receipts = metadata.get("scene_transfers", [])
    if type(raw_receipts) is not list:
        return None, set(), "malformed_receipt_namespace"
    try:
        receipts = _safe_json_copy(raw_receipts)
    except (TypeError, ValueError, OverflowError):
        return None, set(), "malformed_receipt_namespace"
    transfer_ids: set[str] = set()
    for receipt in receipts:
        if type(receipt) is not dict:
            return None, set(), "malformed_receipt_namespace"
        transfer_id = receipt.get("transfer_id")
        if type(transfer_id) is not str or not transfer_id or len(transfer_id) > 200:
            return None, set(), "malformed_receipt_namespace"
        if transfer_id in transfer_ids:
            return None, set(), "malformed_receipt_namespace"
        transfer_ids.add(transfer_id)
    return receipts, transfer_ids, None


def _planned_line(**values: Any) -> dict[str, Any]:
    """Return every persisted PromptLine field for deterministic later Apply."""
    fields = {
        "id": values["id"],
        "original_file_name": values["original_file_name"],
        "original_index": values["index"],
        "current_index": values["index"],
        "original_text": values["text"],
        "current_text": values["text"],
        "tokens": list(values.get("tokens", [])),
        "negative_prompt": values.get("negative_prompt", ""),
        "source_generation_info": {},
        "lineage_info": {},
        "node_path": [],
        "edited": values["edited"],
        "deleted": False,
        "duplicated_from": None,
        "image_path": None,
        "generated_image_path": None,
        "selected_candidate_path": None,
        "generated_candidates": [],
        "gallery_variants": [],
        "line_type": values.get("line_type"),
        "separator_label": values.get("separator_label"),
        "separator_color": values.get("separator_color"),
        "workbench_source_line_id": None,
        "workbench_title": None,
        "workbench_note": None,
        "workbench_status": None,
    }
    return fields


def _allocate_id(prefix: str, seed: dict[str, Any], used: set[str]) -> str | None:
    for counter in range(_ID_COLLISION_ATTEMPTS):
        candidate = f"{prefix}_{_digest({**seed, 'collision_counter': counter})[7:39]}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    return None


def _fail(result: dict[str, Any], code: str) -> dict[str, Any]:
    _block(result, code)
    result["valid"] = False
    result["eligible"] = False
    return result


def preview_scene_import(
    source_project: Project,
    separator_id: str,
    target_project: Project,
) -> dict[str, Any]:
    """Preview an image-less source Scene append without mutating either Project.

    The returned plan is a content identity only. It grants no approval or
    authority and this module deliberately provides no Apply operation.
    """
    result = _empty_result()
    if type(source_project) is Project and source_project is target_project:
        return _fail(result, "same_project")

    try:
        source = project_scene_portability_payload(source_project, separator_id)
    except Exception:
        return _fail(result, "source_projection_failed")
    if type(source) is not dict or source.get("valid") is not True:
        source_blockers = source.get("blockers", []) if type(source) is dict else []
        source_blockers = [
            code for code in source_blockers
            if type(code) is str and len(code) <= 120
        ][: _MAX_DIAGNOSTICS]
        _block(result, "source_projection_invalid")
        result["diagnostics"] = [{"code": "source_projection_invalid", "source_blockers": source_blockers}]
        result["source_projection_blockers"] = source_blockers
        return result

    result["source_scene_fingerprint"] = source.get("source_scene_fingerprint")
    result["source_separator_id"] = source.get("source_separator_id")
    if type(target_project) is not Project:
        return _fail(result, "invalid_target_project")

    target_lines, existing_ids, line_error = _target_line_state(target_project)
    if line_error:
        return _fail(result, line_error)
    receipts, existing_transfer_ids, receipt_error = _receipt_state(target_project)
    if receipt_error:
        return _fail(result, receipt_error)

    snapshots = source.get("module_snapshots")
    illustrations = source.get("illustrations")
    scene = source.get("scene")
    source_separator = source.get("source_separator_id")
    source_fingerprint = source.get("source_scene_fingerprint")
    if (
        type(snapshots) is not list
        or type(illustrations) is not list
        or type(scene) is not dict
        or type(source_separator) is not str
        or type(source_fingerprint) is not str
    ):
        return _fail(result, "malformed_source_projection")

    source_ids = {source_separator}
    normalized_snapshots: list[tuple[str, dict[str, Any]]] = []
    for snapshot in snapshots:
        if type(snapshot) is not dict:
            return _fail(result, "malformed_source_projection")
        name = snapshot.get("name")
        definition = snapshot.get("definition")
        if type(name) is not str or not name or type(definition) is not dict:
            return _fail(result, "malformed_source_projection")
        normalized_snapshots.append((name, definition))
    normalized_snapshots.sort(key=lambda item: item[0])

    normalized_illustrations: list[dict[str, Any]] = []
    for illustration in illustrations:
        if type(illustration) is not dict:
            return _fail(result, "malformed_source_projection")
        source_line_id = illustration.get("source_line_id")
        positive = illustration.get("positive_prompt")
        negative = illustration.get("negative_prompt")
        if (
            type(source_line_id) is not str
            or not source_line_id
            or type(positive) is not str
            or type(negative) is not str
        ):
            return _fail(result, "malformed_source_projection")
        if source_line_id in source_ids:
            return _fail(result, "malformed_source_projection")
        source_ids.add(source_line_id)
        normalized_illustrations.append(illustration)
    if len(normalized_illustrations) > _MAX_TARGET_LINES:
        return _fail(result, "source_plan_limit_exceeded")

    relevant_module_state: list[dict[str, Any]] = []
    module_actions: list[dict[str, Any]] = []
    if normalized_snapshots:
        target_library = target_project.module_library
        if type(target_library) is not dict:
            return _fail(result, "malformed_target_module_library")
    else:
        target_library = {}

    for name, source_definition in normalized_snapshots:
        source_definition_digest = _digest(source_definition)
        present = name in target_library
        if not present:
            action = {
                "name": name,
                "action": "import",
                "source_definition_digest": source_definition_digest,
                "import_definition": source_definition,
                "target_definition_digest": None,
                "reason": None,
            }
            relevant_module_state.append({"name": name, "exists": False})
        else:
            projected_target = project_portable_module_definition(name, target_library[name])
            if type(projected_target) is not dict or projected_target.get("valid") is not True:
                action = {
                    "name": name,
                    "action": "conflict",
                    "source_definition_digest": source_definition_digest,
                    "import_definition": None,
                    "target_definition_digest": None,
                    "reason": "malformed_target_module",
                }
                result["module_actions"] = [*module_actions, action]
                return _fail(result, "malformed_target_module")
            target_definition = projected_target.get("definition")
            target_definition_digest = _digest(target_definition)
            same_definition = target_definition == source_definition
            action = {
                "name": name,
                "action": "reuse" if same_definition else "conflict",
                "source_definition_digest": source_definition_digest,
                "import_definition": None,
                "target_definition_digest": target_definition_digest,
                "reason": None if same_definition else "same_name_definition_differs",
            }
            relevant_module_state.append({"name": name, "exists": True, "definition": target_definition})
        module_actions.append(action)

    target_freshness_payload = {
        "contract_version": SCENE_IMPORT_PREVIEW_CONTRACT_VERSION,
        "prompt_lines": target_lines,
        "relevant_modules": relevant_module_state,
        "scene_transfers": receipts,
    }
    try:
        target_fingerprint = _digest(target_freshness_payload)
    except (TypeError, ValueError, OverflowError):
        return _fail(result, "unsupported_target_state")

    used_ids = set(existing_ids) | source_ids
    id_seed_base = {
        "contract_version": SCENE_IMPORT_PREVIEW_CONTRACT_VERSION,
        "source_scene_fingerprint": source_fingerprint,
        "target_freshness_fingerprint": target_fingerprint,
    }
    target_separator_id = _allocate_id(
        "separator_import",
        {**id_seed_base, "kind": "separator", "source_id": source_separator},
        used_ids,
    )
    if target_separator_id is None:
        return _fail(result, "target_id_allocation_failed")

    target_illustration_ids: list[str] = []
    for order, illustration in enumerate(normalized_illustrations):
        target_id = _allocate_id(
            "line_import",
            {
                **id_seed_base,
                "kind": "illustration",
                "source_id": illustration["source_line_id"],
                "scene_order": order,
            },
            used_ids,
        )
        if target_id is None:
            return _fail(result, "target_id_allocation_failed")
        target_illustration_ids.append(target_id)

    insertion_index = len(target_lines)
    scene_label = scene.get("label")
    scene_color = scene.get("color")
    if (scene_label is not None and type(scene_label) is not str) or (
        scene_color is not None and type(scene_color) is not str
    ):
        return _fail(result, "malformed_source_projection")
    scene_label = scene_label or "Scene"
    planned_separator = _planned_line(
        id=target_separator_id,
        original_file_name="scene-import-separator.txt",
        index=insertion_index,
        text=scene_label,
        tokens=[],
        negative_prompt="",
        edited=True,
        line_type="separator",
        separator_label=scene_label,
        separator_color=scene_color,
    )
    planned_illustrations = []
    correspondence = []
    for order, (illustration, target_id) in enumerate(zip(normalized_illustrations, target_illustration_ids)):
        index = insertion_index + order + 1
        positive = illustration["positive_prompt"]
        planned_illustrations.append(
            _planned_line(
                id=target_id,
                original_file_name=f"scene-import-illustration-{order + 1:04d}.txt",
                index=index,
                text=positive,
                tokens=parse_prompt(positive),
                negative_prompt=illustration["negative_prompt"],
                edited=False,
                line_type=None,
                separator_label=None,
                separator_color=None,
            )
        )
        correspondence.append({
            "source_line_id": illustration["source_line_id"],
            "target_line_id": target_id,
        })

    source_to_target_map = {
        "separator": {"source_id": source_separator, "target_id": target_separator_id},
        "illustrations": correspondence,
    }
    receipt_seed = {
        **id_seed_base,
        "source_to_target_map": source_to_target_map,
        "module_actions": module_actions,
    }
    transfer_id = None
    for counter in range(_ID_COLLISION_ATTEMPTS):
        candidate = "transfer_" + _digest({**receipt_seed, "collision_counter": counter})[7:39]
        if candidate not in existing_transfer_ids:
            transfer_id = candidate
            break
    if transfer_id is None:
        return _fail(result, "transfer_id_allocation_failed")

    planned_receipt = {
        "transfer_id": transfer_id,
        "source_scene_fingerprint": source_fingerprint,
        "source_separator_id": source_separator,
        "target_separator_id": target_separator_id,
        "illustrations": correspondence,
    }
    if scene_label:
        planned_receipt["source_scene_label"] = scene_label

    block_order = [target_separator_id, *target_illustration_ids]
    result.update({
        "target_line_count": len(target_lines),
        "insertion_index": insertion_index,
        "planned_separator": planned_separator,
        "planned_illustrations": planned_illustrations,
        "resulting_scene_block_order": block_order,
        "source_to_target_map": source_to_target_map,
        "module_actions": module_actions,
        "planned_receipt": planned_receipt,
        "planned_receipt_append_index": len(receipts),
        "target_freshness_fingerprint": target_fingerprint,
    })
    reviewed_projection = {
        "contract_version": SCENE_IMPORT_PREVIEW_CONTRACT_VERSION,
        "operation": SCENE_IMPORT_PREVIEW_OPERATION,
        "source_scene_fingerprint": source_fingerprint,
        "target_freshness_fingerprint": target_fingerprint,
        "target_line_count": len(target_lines),
        "insertion_index": insertion_index,
        "planned_separator": planned_separator,
        "planned_illustrations": planned_illustrations,
        "resulting_scene_block_order": block_order,
        "module_actions": module_actions,
        "source_to_target_map": source_to_target_map,
        "planned_receipt": planned_receipt,
        "planned_receipt_append_index": len(receipts),
    }
    try:
        result["projection_digest"] = _digest(reviewed_projection)
        result["valid"] = True
        result["eligible"] = True
        if any(action["action"] == "conflict" for action in module_actions):
            _block(result, "module_conflict")
            result["eligible"] = False
        unsigned = {key: value for key, value in result.items() if key != "plan_id"}
        result["plan_id"] = _digest(unsigned)
        _canonical_json(result)
    except (TypeError, ValueError, OverflowError):
        return _fail(result, "unsupported_preview_result")
    return result
