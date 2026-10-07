"""Preview and stale-safe in-memory Apply for cross-Project Scene imports."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import fields as dataclass_fields
from typing import Any

from core.parser import parse_prompt
from core.project import Project, PromptLine
from core.graph_builder import build_graph
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
_MAX_REVIEWED_PREVIEW_JSON_NODES = 1_000_000
_MAX_REVIEWED_PREVIEW_STRING_CHARS = 20_000_000
SCENE_IMPORT_APPLY_CONTRACT_VERSION = "promptgraph.scene-import-apply.v1"
_PROMPT_LINE_FIELD_NAMES = {item.name for item in dataclass_fields(PromptLine)}


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


def _safe_json_copy(
    value: Any,
    *,
    max_nodes: int = _MAX_JSON_NODES,
    max_string_chars: int = _MAX_JSON_STRING_CHARS,
) -> Any:
    """Validate/copy persisted JSON values with bounded traversal and cycles rejected."""
    active: set[int] = set()
    stats = {"nodes": 0, "string_chars": 0}

    def visit(item: Any, depth: int) -> Any:
        if depth > _MAX_JSON_DEPTH:
            raise ValueError("unsupported_target_json")
        stats["nodes"] += 1
        if stats["nodes"] > max_nodes:
            raise ValueError("unsupported_target_json")
        if type(item) is str:
            stats["string_chars"] += len(item)
            if stats["string_chars"] > max_string_chars:
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
                if stats["string_chars"] > max_string_chars:
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
    for physical_index, line in enumerate(lines):
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
        if current_index != physical_index:
            return None, set(), "stale_target_current_index"
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


def _preview_projection_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": SCENE_IMPORT_PREVIEW_CONTRACT_VERSION,
        "operation": SCENE_IMPORT_PREVIEW_OPERATION,
        "source_scene_fingerprint": result["source_scene_fingerprint"],
        "target_freshness_fingerprint": result["target_freshness_fingerprint"],
        "target_line_count": result["target_line_count"],
        "insertion_index": result["insertion_index"],
        "planned_separator": result["planned_separator"],
        "planned_illustrations": result["planned_illustrations"],
        "resulting_scene_block_order": result["resulting_scene_block_order"],
        "module_actions": result["module_actions"],
        "source_to_target_map": result["source_to_target_map"],
        "planned_receipt": result["planned_receipt"],
        "planned_receipt_append_index": result["planned_receipt_append_index"],
    }


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
    merge_by_word_only = target_project.merge_by_word_only
    if type(merge_by_word_only) is not bool:
        return _fail(result, "invalid_target_merge_by_word_only")

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
        "merge_by_word_only": merge_by_word_only,
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
    try:
        result["projection_digest"] = _digest(_preview_projection_payload(result))
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


def _empty_apply_result() -> dict[str, Any]:
    return {
        "contract_version": SCENE_IMPORT_APPLY_CONTRACT_VERSION,
        "operation": SCENE_IMPORT_PREVIEW_OPERATION,
        "applied": False,
        "reason": None,
        "blockers": [],
        "diagnostics": [],
        "reviewed_plan_id": None,
        "projection_digest": None,
        "source_scene_fingerprint": None,
        "target_freshness_fingerprint": None,
        "transfer_id": None,
        "target_separator_id": None,
        "imported_illustration_ids": [],
        "imported_module_names": [],
        "reused_module_names": [],
        "resulting_target_line_count": None,
    }


def _apply_fail(result: dict[str, Any], code: str) -> dict[str, Any]:
    result["applied"] = False
    result["reason"] = code
    if code not in result["blockers"] and len(result["blockers"]) < _MAX_DIAGNOSTICS:
        result["blockers"].append(code)
    if not result["diagnostics"]:
        result["diagnostics"].append({"code": code})
    return result


def _is_digest(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _validate_reviewed_preview(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if type(value) is not dict:
        return None, "malformed_reviewed_preview"
    try:
        reviewed = _safe_json_copy(
            value,
            max_nodes=_MAX_REVIEWED_PREVIEW_JSON_NODES,
            max_string_chars=_MAX_REVIEWED_PREVIEW_STRING_CHARS,
        )
        _canonical_json(reviewed)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None, "malformed_reviewed_preview"

    if set(reviewed) != set(_empty_result()):
        return None, "malformed_reviewed_preview"
    if (
        reviewed.get("contract_version") != SCENE_IMPORT_PREVIEW_CONTRACT_VERSION
        or reviewed.get("operation") != SCENE_IMPORT_PREVIEW_OPERATION
    ):
        return None, "incompatible_reviewed_preview"
    if type(reviewed.get("valid")) is not bool or reviewed["valid"] is not True:
        return None, "reviewed_preview_invalid"
    if type(reviewed.get("eligible")) is not bool or reviewed["eligible"] is not True:
        return None, "reviewed_preview_ineligible"
    if (
        type(reviewed.get("blockers")) is not list
        or reviewed["blockers"]
        or type(reviewed.get("diagnostics")) is not list
        or reviewed["diagnostics"]
    ):
        return None, "malformed_reviewed_preview"
    if (
        not _is_digest(reviewed.get("plan_id"))
        or not _is_digest(reviewed.get("projection_digest"))
        or not _is_digest(reviewed.get("source_scene_fingerprint"))
        or not _is_digest(reviewed.get("target_freshness_fingerprint"))
    ):
        return None, "malformed_reviewed_preview"
    if (
        type(reviewed.get("target_line_count")) is not int
        or reviewed["target_line_count"] < 0
        or type(reviewed.get("insertion_index")) is not int
        or reviewed["insertion_index"] != reviewed["target_line_count"]
        or type(reviewed.get("planned_separator")) is not dict
        or type(reviewed.get("planned_illustrations")) is not list
        or len(reviewed["planned_illustrations"]) > _MAX_TARGET_LINES
        or type(reviewed.get("resulting_scene_block_order")) is not list
        or type(reviewed.get("module_actions")) is not list
        or len(reviewed["module_actions"]) > 256
        or type(reviewed.get("source_to_target_map")) is not dict
        or type(reviewed.get("planned_receipt")) is not dict
        or type(reviewed.get("planned_receipt_append_index")) is not int
        or reviewed["planned_receipt_append_index"] < 0
    ):
        return None, "malformed_reviewed_preview"

    try:
        expected_projection_digest = _digest(_preview_projection_payload(reviewed))
        unsigned = {key: item for key, item in reviewed.items() if key != "plan_id"}
        expected_plan_id = _digest(unsigned)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return None, "malformed_reviewed_preview"
    if (
        reviewed["projection_digest"] != expected_projection_digest
        or reviewed["plan_id"] != expected_plan_id
    ):
        return None, "reviewed_preview_integrity_mismatch"
    return reviewed, None


def _apply_identity_from_preview(result: dict[str, Any], preview: dict[str, Any]) -> None:
    result.update({
        "reviewed_plan_id": preview["plan_id"],
        "projection_digest": preview["projection_digest"],
        "source_scene_fingerprint": preview["source_scene_fingerprint"],
        "target_freshness_fingerprint": preview["target_freshness_fingerprint"],
    })


def _apply_details_from_preview(result: dict[str, Any], preview: dict[str, Any]) -> None:
    separator = preview["planned_separator"]
    receipt = preview["planned_receipt"]
    result.update({
        "transfer_id": receipt.get("transfer_id"),
        "target_separator_id": separator.get("id"),
        "imported_illustration_ids": [
            row.get("id") for row in preview["planned_illustrations"]
        ],
        "imported_module_names": [
            action["name"] for action in preview["module_actions"]
            if action.get("action") == "import"
        ],
        "reused_module_names": [
            action["name"] for action in preview["module_actions"]
            if action.get("action") == "reuse"
        ],
        "resulting_target_line_count": (
            preview["target_line_count"]
            + 1
            + len(preview["planned_illustrations"])
        ),
    })


def _materialize_preview_row(row: Any) -> PromptLine:
    if type(row) is not dict or set(row) != _PROMPT_LINE_FIELD_NAMES:
        raise ValueError("invalid_planned_prompt_line")
    return PromptLine(**copy.deepcopy(row))


def _append_preview_receipt(project: Project, preview: dict[str, Any]) -> None:
    metadata = project.project_metadata
    if type(metadata) is not dict:
        raise ValueError("invalid_receipt_metadata")
    receipts = metadata.get("scene_transfers", [])
    append_index = preview["planned_receipt_append_index"]
    if type(receipts) is not list or len(receipts) != append_index:
        raise ValueError("invalid_receipt_append_index")
    if type(preview["planned_receipt"]) is not dict:
        raise ValueError("invalid_planned_receipt")
    receipts.append(copy.deepcopy(preview["planned_receipt"]))
    metadata["scene_transfers"] = receipts


def _apply_preview_modules(project: Project, preview: dict[str, Any]) -> tuple[list[str], list[str]]:
    actions = preview["module_actions"]
    if not actions:
        return [], []
    library = project.module_library
    if type(library) is not dict:
        raise ValueError("invalid_module_library")
    imported: list[str] = []
    reused: list[str] = []
    for action in actions:
        if type(action) is not dict:
            raise ValueError("invalid_module_action")
        name = action.get("name")
        kind = action.get("action")
        if type(name) is not str or not name:
            raise ValueError("invalid_module_name")
        if kind == "reuse":
            if name not in library:
                raise ValueError("reused_module_missing")
            reused.append(name)
        elif kind == "import":
            definition = action.get("import_definition")
            if name in library or type(definition) is not dict:
                raise ValueError("module_import_conflict")
            library[name] = copy.deepcopy(definition)
            imported.append(name)
        else:
            raise ValueError("ineligible_module_action")
    return imported, reused


def _verify_staged_apply(
    original: Project,
    staged: Project,
    preview: dict[str, Any],
    imported_modules: list[str],
    reused_modules: list[str],
) -> bool:
    target_count = preview["target_line_count"]
    expected_separator = preview["planned_separator"]
    expected_illustrations = preview["planned_illustrations"]
    expected_ids = preview["resulting_scene_block_order"]
    if (
        len(original.prompt_lines) != target_count
        or preview["insertion_index"] != target_count
        or len(staged.prompt_lines) != target_count + len(expected_ids)
        or len(expected_ids) != 1 + len(expected_illustrations)
    ):
        return False

    for before, after in zip(original.prompt_lines, staged.prompt_lines[:target_count]):
        before_fields = vars(before).copy()
        after_fields = vars(after).copy()
        before_fields.pop("node_path", None)
        after_fields.pop("node_path", None)
        if before_fields != after_fields:
            return False

    imported_rows = staged.prompt_lines[target_count:]
    if [line.id for line in imported_rows] != expected_ids:
        return False
    planned_rows = [expected_separator, *expected_illustrations]
    for offset, (line, planned) in enumerate(zip(imported_rows, planned_rows)):
        if type(line) is not PromptLine or set(planned) != _PROMPT_LINE_FIELD_NAMES:
            return False
        if line.current_index != target_count + offset:
            return False
        actual_fields = vars(line).copy()
        expected_fields = copy.deepcopy(planned)
        actual_fields.pop("node_path", None)
        expected_fields.pop("node_path", None)
        if actual_fields != expected_fields:
            return False

    for name in imported_modules:
        matching_actions = [
            action for action in preview["module_actions"]
            if action.get("name") == name and action.get("action") == "import"
        ]
        if (
            len(matching_actions) != 1
            or name not in staged.module_library
            or staged.module_library[name] != matching_actions[0].get("import_definition")
        ):
            return False
    for name in reused_modules:
        if (
            name not in original.module_library
            or name not in staged.module_library
            or staged.module_library[name] != original.module_library[name]
        ):
            return False

    original_receipts = original.project_metadata.get("scene_transfers", [])
    staged_receipts = staged.project_metadata.get("scene_transfers", [])
    append_index = preview["planned_receipt_append_index"]
    if (
        type(original_receipts) is not list
        or type(staged_receipts) is not list
        or len(original_receipts) != append_index
        or staged_receipts[:append_index] != original_receipts
        or len(staged_receipts) != append_index + 1
        or staged_receipts[append_index] != preview["planned_receipt"]
    ):
        return False

    if (
        type(staged.line_map) is not dict
        or len(staged.line_map) != len(staged.prompt_lines)
        or any(staged.line_map.get(line.id) is not line for line in staged.prompt_lines)
        or type(staged.nodes) is not dict
        or type(staged.edges) is not list
        or type(staged.node_freq) is not dict
        or type(staged.phrase_freq) is not dict
        or type(staged.global_group_freq) is not dict
    ):
        return False
    return True


def _commit_staged_project(target: Project, staged: Project, preview: dict[str, Any]) -> None:
    target_count = preview["target_line_count"]
    original_lines = target.prompt_lines
    staged_lines = staged.prompt_lines
    new_lines = [*original_lines, *staged_lines[target_count:]]
    new_line_map = {line.id: line for line in new_lines}

    new_metadata = dict(target.project_metadata)
    old_receipts = target.project_metadata.get("scene_transfers", [])
    new_metadata["scene_transfers"] = [*old_receipts, copy.deepcopy(preview["planned_receipt"])]

    imported_names = [
        action["name"] for action in preview["module_actions"]
        if action["action"] == "import"
    ]
    if imported_names:
        new_module_library = dict(target.module_library)
        for name in imported_names:
            new_module_library[name] = copy.deepcopy(staged.module_library[name])
    else:
        new_module_library = target.module_library

    updated_project_state = dict(vars(target))
    updated_project_state.update({
        "prompt_lines": new_lines,
        "line_map": new_line_map,
        "nodes": staged.nodes,
        "edges": staged.edges,
        "node_freq": staged.node_freq,
        "phrase_freq": staged.phrase_freq,
        "global_group_freq": staged.global_group_freq,
        "project_metadata": new_metadata,
        "module_library": new_module_library,
    })
    node_paths = [copy.deepcopy(line.node_path) for line in staged_lines[:target_count]]
    previous_node_paths = [line.node_path for line in original_lines]
    try:
        for line, node_path in zip(original_lines, node_paths):
            line.node_path = node_path
        target.__dict__ = updated_project_state
    except Exception:
        for line, node_path in zip(original_lines, previous_node_paths):
            line.node_path = node_path
        raise


def apply_scene_import(
    source_project: Project,
    separator_id: str,
    target_project: Project,
    reviewed_preview: Any,
) -> dict[str, Any]:
    """Apply an exact, reviewed Scene Import Preview to an in-memory Project.

    The complete Preview is revalidated against current source/target state.
    A plan id identifies content only; human approval remains a host concern.
    """
    result = _empty_apply_result()
    if type(source_project) is Project and source_project is target_project:
        return _apply_fail(result, "same_project")

    reviewed, review_error = _validate_reviewed_preview(reviewed_preview)
    if review_error:
        return _apply_fail(result, review_error)
    _apply_identity_from_preview(result, reviewed)

    if type(source_project) is not Project:
        return _apply_fail(result, "source_now_invalid")
    if type(target_project) is not Project:
        return _apply_fail(result, "target_now_invalid")

    try:
        current_raw = preview_scene_import(source_project, separator_id, target_project)
    except Exception:
        return _apply_fail(result, "current_preview_failed")
    if type(current_raw) is not dict or current_raw.get("valid") is not True:
        current_blockers = current_raw.get("blockers", []) if type(current_raw) is dict else []
        source_codes = {"source_projection_failed", "source_projection_invalid", "invalid_source_project"}
        if type(current_blockers) is list and any(code in source_codes for code in current_blockers):
            return _apply_fail(result, "source_now_invalid")
        return _apply_fail(result, "target_now_invalid")
    if current_raw.get("eligible") is not True:
        return _apply_fail(result, "current_preview_ineligible")
    current, current_error = _validate_reviewed_preview(current_raw)
    if current_error or current is None:
        return _apply_fail(result, "current_preview_invalid")
    if current != reviewed:
        return _apply_fail(result, "reviewed_preview_stale")
    _apply_details_from_preview(result, current)

    target_count = current["target_line_count"]
    if (
        type(target_project.prompt_lines) is not list
        or len(target_project.prompt_lines) != target_count
        or current["insertion_index"] != target_count
    ):
        return _apply_fail(result, "target_now_invalid")

    try:
        staged = copy.deepcopy(target_project)
        if staged is target_project:
            return _apply_fail(result, "staging_failed")
    except Exception:
        return _apply_fail(result, "staging_failed")

    try:
        rows = [current["planned_separator"], *current["planned_illustrations"]]
        materialized = [_materialize_preview_row(row) for row in rows]
        if len(staged.prompt_lines) != target_count:
            return _apply_fail(result, "row_materialization_failed")
        staged.prompt_lines.extend(materialized)
    except Exception:
        return _apply_fail(result, "row_materialization_failed")

    try:
        imported_modules, reused_modules = _apply_preview_modules(staged, current)
    except Exception:
        return _apply_fail(result, "module_import_invariant_failed")

    try:
        _append_preview_receipt(staged, current)
    except Exception:
        return _apply_fail(result, "receipt_append_invariant_failed")

    try:
        rebuilt = build_graph(staged)
        if rebuilt is not staged:
            return _apply_fail(result, "graph_rebuild_failed")
    except Exception:
        return _apply_fail(result, "graph_rebuild_failed")

    try:
        if not _verify_staged_apply(target_project, staged, current, imported_modules, reused_modules):
            return _apply_fail(result, "postcondition_failed")
    except Exception:
        return _apply_fail(result, "postcondition_failed")

    result["imported_module_names"] = imported_modules
    result["reused_module_names"] = reused_modules
    result["applied"] = True
    result["reason"] = None
    result["resulting_target_line_count"] = len(staged.prompt_lines)
    try:
        _canonical_json(result)
        _commit_staged_project(target_project, staged, current)
    except Exception:
        failure = _empty_apply_result()
        _apply_identity_from_preview(failure, current)
        return _apply_fail(failure, "commit_failed")
    return result
