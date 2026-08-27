import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from core.generation_settings_analysis import extract_generation_settings_from_metadata
from core.io import (
    build_lineage_info_from_candidate,
    build_source_generation_info_from_candidate,
)


PathResolver = Callable[[str], str]
PathExists = Callable[[str], bool]
PathStat = Callable[[str], os.stat_result]
APPLY_SUPPORTED_SCOPES = {"selected_lines", "current_route", "selected_route", "selected_routes"}
APPLY_SUPPORTED_SOURCES = {"latest", "first"}
GALLERY_VARIANT_PREVIEW_SOURCE = "latest_gallery_variant"
ALL_APPLY_CONFIRM_PHRASE = "APPLY ALL"


DRIFT_WARNING = (
    "This operation changes image references in batch. Prompt text is not rewritten automatically. "
    "Review whether displayed images still match prompt meaning before applying. "
    "Run Candidate Prompt Adoption separately when needed."
)


def is_route_batch_adoption_apply_supported(scope: str, source: str) -> bool:
    if scope == "all_lines":
        return source in APPLY_SUPPORTED_SOURCES or source == GALLERY_VARIANT_PREVIEW_SOURCE
    if scope not in APPLY_SUPPORTED_SCOPES:
        return False
    if source in APPLY_SUPPORTED_SOURCES:
        return True
    return source == GALLERY_VARIANT_PREVIEW_SOURCE


def is_route_batch_adoption_apply_button_enabled(
    *,
    scope: str,
    source: str,
    preview_current: bool,
    will_adopt_count: int,
    confirmed: bool,
    all_confirm_phrase: str = "",
) -> bool:
    if not preview_current:
        return False
    if not is_route_batch_adoption_apply_supported(scope, source):
        return False
    if int(will_adopt_count or 0) <= 0:
        return False
    if not confirmed:
        return False
    if scope == "all_lines" and str(all_confirm_phrase or "").strip() != ALL_APPLY_CONFIRM_PHRASE:
        return False
    return True


def build_route_batch_adoption_preview_signature(
    *,
    source: str,
    scope: str,
    selected_route_id: str = "",
    current_route_anchor_id: str = "",
    selected_line_ids: Iterable[str] | None = None,
    all_scope_line_ids: Iterable[str] | None = None,
) -> dict:
    signature = {
        "source": source,
        "scope": scope,
        "selected_route_id": selected_route_id,
        "current_route_anchor_id": current_route_anchor_id,
        "selected_line_ids": tuple(line_id for line_id in (selected_line_ids or []) if line_id),
    }
    if scope == "all_lines":
        line_ids = tuple(line_id for line_id in (all_scope_line_ids or []) if line_id)
        signature["all_scope_line_ids"] = line_ids
        signature["all_scope_line_count"] = len(line_ids)
    return signature


def _candidate_path(candidate: Any) -> str:
    if isinstance(candidate, dict):
        return str(candidate.get("path") or "").strip()
    return str(candidate or "").strip()


def _candidate_is_trashed(candidate: Any) -> bool:
    return bool(isinstance(candidate, dict) and candidate.get("trashed"))


def _is_appended_gallery_variant_record(variant: Any) -> bool:
    if not isinstance(variant, dict):
        return False
    return (
        variant.get("kind") == "gallery_variant"
        or variant.get("source") == "batch_candidate_adoption"
        or str(variant.get("id") or "").startswith("variant_")
    )


def _normalize_path(path: str, resolve_path: PathResolver | None = None) -> str:
    clean_path = str(path or "").strip()
    if not clean_path:
        return ""
    if resolve_path:
        clean_path = resolve_path(clean_path) or clean_path
    try:
        return os.path.normcase(os.path.abspath(clean_path))
    except (OSError, ValueError):
        return clean_path


def _path_matches(path_a: str, path_b: str, resolve_path: PathResolver | None = None) -> bool:
    normalized_a = _normalize_path(path_a, resolve_path)
    normalized_b = _normalize_path(path_b, resolve_path)
    return bool(normalized_a and normalized_b and normalized_a == normalized_b)


def _active_candidates(line: Any) -> list[dict]:
    candidates = getattr(line, "generated_candidates", None)
    if not isinstance(candidates, list):
        return []
    active = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if _candidate_is_trashed(candidate):
            continue
        if _candidate_path(candidate):
            active.append(candidate)
    return active


def _line_candidates(line: Any) -> list[dict]:
    candidates = getattr(line, "generated_candidates", None)
    if not isinstance(candidates, list):
        return []
    return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]


def _candidate_for_source(line: Any, source: str) -> dict | None:
    candidates = _active_candidates(line)
    if not candidates:
        return None
    if source == "first":
        return candidates[0]
    return candidates[-1]


def _active_gallery_variants(line: Any) -> list[dict]:
    variants = getattr(line, "gallery_variants", None)
    if not isinstance(variants, list):
        return []
    active = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if variant.get("trashed"):
            continue
        if not _is_appended_gallery_variant_record(variant):
            continue
        if _candidate_path(variant):
            active.append(dict(variant))
    return active


def _variant_for_source(line: Any, source: str) -> dict | None:
    if source != GALLERY_VARIANT_PREVIEW_SOURCE:
        return None
    variants = _active_gallery_variants(line)
    if not variants:
        return None
    return variants[-1]


def _adoption_record_for_source(
    line: Any,
    source: str,
    candidate_path: str,
    resolve_path: PathResolver | None = None,
) -> dict | None:
    record = (
        _variant_for_source(line, source)
        if source == GALLERY_VARIANT_PREVIEW_SOURCE
        else _candidate_for_source(line, source)
    )
    if not isinstance(record, dict):
        return None
    if not _path_matches(_candidate_path(record), candidate_path, resolve_path):
        return None
    return record


def _adoption_provenance_metadata(record: dict, source: str) -> dict:
    if source != GALLERY_VARIANT_PREVIEW_SOURCE:
        return copy.deepcopy(record)

    candidate_metadata = record.get("candidate_metadata")
    metadata = copy.deepcopy(candidate_metadata) if isinstance(candidate_metadata, dict) else {}
    for key in ("id", "origin_line_id", "origin_line_index", "source", "created_at", "run_index"):
        if record.get(key) not in (None, ""):
            metadata.setdefault(key, copy.deepcopy(record[key]))

    source_info = record.get("source_generation_info")
    if isinstance(source_info, dict):
        for key in ("source_prompt", "source_negative_prompt"):
            if source_info.get(key) not in (None, ""):
                metadata.setdefault(key, copy.deepcopy(source_info[key]))
        generation_settings = source_info.get("source_generation_settings")
        if isinstance(generation_settings, dict):
            for key, value in generation_settings.items():
                metadata.setdefault(str(key), copy.deepcopy(value))
        raw_metadata = source_info.get("source_raw_metadata")
        if isinstance(raw_metadata, dict):
            metadata.setdefault("raw_metadata", copy.deepcopy(raw_metadata))
    return metadata or copy.deepcopy(record)


def _adoption_source_label(source: str) -> str:
    if source == "first":
        return "first_candidate"
    if source == GALLERY_VARIANT_PREVIEW_SOURCE:
        return "latest_gallery_variant"
    return "latest_candidate"


def _metadata_text(metadata: Any, *keys: str) -> str:
    if not isinstance(metadata, dict):
        return ""
    lowered = {str(key).casefold(): value for key, value in metadata.items()}
    for key in keys:
        value = lowered.get(key.casefold())
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _candidate_prompt_details(line: Any, target: Any) -> dict[str, Any]:
    metadata = target if isinstance(target, dict) else {}
    nested_source = metadata.get("source_generation_info")
    nested_source = nested_source if isinstance(nested_source, dict) else {}
    candidate_prompt = _metadata_text(
        metadata,
        "source_prompt",
        "prompt_text",
        "prompt",
        "positive_prompt",
        "positive",
    ) or _metadata_text(nested_source, "source_prompt", "prompt_text", "prompt")
    candidate_negative = _metadata_text(
        metadata,
        "source_negative_prompt",
        "negative_prompt",
        "negative",
    ) or _metadata_text(nested_source, "source_negative_prompt", "negative_prompt")
    candidate_generation = (
        extract_generation_settings_from_metadata(metadata)
        or metadata.get("source_generation_settings")
        or metadata.get("generation_settings")
        or metadata.get("settings")
        or nested_source.get("source_generation_settings")
        or {}
    )
    source_info = getattr(line, "source_generation_info", {})
    source_info = source_info if isinstance(source_info, dict) else {}
    current_generation = source_info.get("source_generation_settings") or {}
    current_prompt = str(getattr(line, "current_text", "") or "")
    current_negative = str(getattr(line, "negative_prompt", "") or "")

    drift = []
    if not candidate_prompt:
        drift.append("Candidate prompt unavailable")
    elif candidate_prompt != current_prompt:
        drift.append("prompt differs")
    if candidate_negative and candidate_negative != current_negative:
        drift.append("negative prompt differs")
    if candidate_generation and candidate_generation != current_generation:
        drift.append("generation metadata differs")
    if not drift:
        drift.append("no drift")

    return {
        "candidate_id": str(metadata.get("id") or "").strip(),
        "candidate_prompt_preview": candidate_prompt[:240],
        "candidate_negative_prompt_preview": candidate_negative[:240],
        "candidate_generation_metadata": copy.deepcopy(candidate_generation),
        "drift_classifications": drift,
        "prompt_drift": drift != ["no drift"],
    }


def _line_candidate_has_path(
    line: Any,
    candidate_path: str,
    resolve_path: PathResolver | None = None,
) -> bool:
    return any(
        _path_matches(_candidate_path(candidate), candidate_path, resolve_path)
        for candidate in _line_candidates(line)
    )


def _mark_adopted_candidate_record(
    line: Any,
    candidate_path: str,
    *,
    adopted_at: str,
    resolve_path: PathResolver | None = None,
) -> None:
    candidates = _line_candidates(line)
    updated = []
    matched = False
    for candidate in candidates:
        record = dict(candidate)
        if _path_matches(record.get("path"), candidate_path, resolve_path):
            record["adoption_mode"] = "route_batch_candidate_adoption"
            record["batch_adopted_to_main_at"] = adopted_at
            matched = True
        updated.append(record)
    if matched:
        line.generated_candidates = updated


def _append_retreat_record(
    line: Any,
    previous_main_path: str,
    previous_main_field: str,
    *,
    adopted_at: str,
    resolve_path: PathResolver | None = None,
) -> bool:
    if not previous_main_path or _line_candidate_has_path(line, previous_main_path, resolve_path):
        return False
    candidates = _line_candidates(line)
    candidates.append(
        {
            "path": previous_main_path,
            "created_at": adopted_at,
            "source": "route_batch_candidate_adoption_retreat",
            "adoption_mode": "retreated_main_image",
            "previous_role": "main_image",
            "previous_main_image_field": previous_main_field,
            "origin_line_id": getattr(line, "id", "") or "",
            "origin_line_index": getattr(line, "current_index", getattr(line, "original_index", None)),
        }
    )
    line.generated_candidates = candidates
    return True


def _main_image_reference(
    line: Any,
    *,
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
) -> dict:
    for field in ("selected_candidate_path", "generated_image_path", "image_path"):
        raw_path = str(getattr(line, field, None) or "").strip()
        if not raw_path:
            continue
        resolved_path = resolve_path(raw_path) if resolve_path else raw_path
        if path_exists and not path_exists(resolved_path):
            continue
        return {
            "path": raw_path,
            "resolved_path": resolved_path,
            "field": field,
        }
    return {}


def _line_label(line: Any) -> str:
    label = (
        getattr(line, "original_file_name", None)
        or getattr(line, "id", None)
        or "Line"
    )
    line_number = getattr(line, "original_index", None)
    if line_number is not None:
        return f"{label}:{line_number + 1}"
    return str(label)


def _skip_entry(line: Any, reason: str, route_id: str = "", route_label: str = "") -> dict:
    return {
        "line_id": getattr(line, "id", "") or "",
        "line_index": getattr(line, "current_index", getattr(line, "original_index", None)),
        "display_id": _line_label(line),
        "route_id": route_id,
        "route_label": route_label,
        "prompt_preview": str(getattr(line, "current_text", "") or "")[:240],
        "negative_prompt_preview": str(getattr(line, "negative_prompt", "") or "")[:240],
        "before_image_path": "",
        "after_image_path": "",
        "adoption_source": "",
        "operation": "skipped",
        "skip_reason": reason,
    }


def build_route_batch_candidate_adoption_preview(
    lines: Iterable[Any],
    *,
    source: str = "latest",
    scope: str = "",
    route_id: str = "",
    route_label: str = "",
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
    example_limit: int = 20,
) -> dict:
    """Build a dry-run preview for scoped candidate image adoption.

    This function is intentionally read-only. It does not mutate lines,
    candidates, lineage, prompt text, image references, or files.
    """

    entries = []
    skipped_entries = []
    targeted_count = 0
    will_adopt_count = 0
    first_main_count = 0
    swap_count = 0
    skipped_count = 0

    for line in list(lines or []):
        targeted_count += 1
        line_type = getattr(line, "line_type", None)
        if getattr(line, "deleted", False):
            entry = _skip_entry(line, "deleted line", route_id, route_label)
        elif line_type == "separator":
            entry = _skip_entry(line, "Route separator", route_id, route_label)
        elif line_type == "workbench":
            entry = _skip_entry(line, "Workbench line", route_id, route_label)
        else:
            is_variant_source = source == GALLERY_VARIANT_PREVIEW_SOURCE
            adoption_target = _variant_for_source(line, source) if is_variant_source else _candidate_for_source(line, source)
            if not adoption_target:
                if is_variant_source:
                    reason = "gallery variant target not found"
                else:
                    raw_candidates = getattr(line, "generated_candidates", None)
                    trashed_only = (
                        isinstance(raw_candidates, list)
                        and bool(raw_candidates)
                        and all(_candidate_is_trashed(candidate) for candidate in raw_candidates if isinstance(candidate, dict))
                    )
                    reason = "trashed candidate only" if trashed_only else "adoption target not found"
                entry = _skip_entry(line, reason, route_id, route_label)
            else:
                adoption_target_path = _candidate_path(adoption_target)
                resolved_target_path = resolve_path(adoption_target_path) if resolve_path else adoption_target_path
                if not adoption_target_path or (path_exists and not path_exists(resolved_target_path)):
                    reason = "missing gallery variant file" if is_variant_source else "missing candidate file"
                    entry = _skip_entry(line, reason, route_id, route_label)
                else:
                    before = _main_image_reference(line, resolve_path=resolve_path, path_exists=path_exists)
                    before_path = before.get("path") or ""
                    target_details = _candidate_prompt_details(line, adoption_target)
                    if before_path and _path_matches(before_path, adoption_target_path, resolve_path):
                        entry = {
                            **_skip_entry(line, "already adopted / no-op", route_id, route_label),
                            **target_details,
                            "before_image_path": before_path,
                            "before_image_field": before.get("field") or "",
                            "after_image_path": adoption_target_path,
                            "candidate_path": adoption_target_path,
                            "adoption_source": _adoption_source_label(source),
                            "operation": "no_op",
                        }
                    else:
                        operation = "swap_with_retreat" if before_path else "first_main_image"
                        if operation == "swap_with_retreat":
                            swap_count += 1
                        else:
                            first_main_count += 1
                        will_adopt_count += 1
                        entry = {
                            **target_details,
                            "line_id": getattr(line, "id", "") or "",
                            "line_index": getattr(line, "current_index", getattr(line, "original_index", None)),
                            "display_id": _line_label(line),
                            "route_id": route_id,
                            "route_label": route_label,
                            "prompt_preview": str(getattr(line, "current_text", "") or "")[:240],
                            "negative_prompt_preview": str(getattr(line, "negative_prompt", "") or "")[:240],
                            "before_image_path": before_path,
                            "before_image_field": before.get("field") or "",
                            "after_image_path": adoption_target_path,
                            "candidate_path": adoption_target_path,
                            "adoption_source": _adoption_source_label(source),
                            "operation": operation,
                            "skip_reason": None,
                        }
        if entry.get("operation") in {"skipped", "no_op"}:
            skipped_count += 1
            skipped_entries.append(entry)
        entries.append(entry)

    return {
        "scope": scope,
        "source": source,
        "route_id": route_id,
        "route_label": route_label,
        "targeted_line_count": targeted_count,
        "will_adopt_count": will_adopt_count,
        "first_main_image_count": first_main_count,
        "swap_with_retreat_count": swap_count,
        "skipped_count": skipped_count,
        "drift_warning": DRIFT_WARNING,
        "apply_implemented": False,
        "entries": entries[:example_limit],
        "skipped_entries": skipped_entries[:example_limit],
        "entry_count": len(entries),
        "skipped_entry_count": len(skipped_entries),
        "example_limit": example_limit,
    }


def apply_route_batch_candidate_adoption_preview(
    lines: Iterable[Any],
    *,
    scope: str,
    source: str = "latest",
    route_id: str = "",
    route_label: str = "",
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
    now: str | None = None,
) -> dict:
    """Apply route-scope candidate adoption for the supported narrow scopes.

    The function updates the selected image reference, Candidate records, and
    image provenance as one line-level adoption. It does not rewrite prompt
    text, negative prompts, image files, ``image_path``, or
    ``generated_image_path``.
    """

    if not is_route_batch_adoption_apply_supported(scope, source):
        unsupported_scope = scope if scope not in APPLY_SUPPORTED_SCOPES else ""
        unsupported_source = source if source not in APPLY_SUPPORTED_SOURCES else ""
        if source == GALLERY_VARIANT_PREVIEW_SOURCE:
            unsupported_source = source
        return {
            "applied_count": 0,
            "first_main_image_count": 0,
            "swap_with_retreat_count": 0,
            "skipped_count": 1,
            "skipped_reasons": {"unsupported source/scope": 1},
            "applied_line_ids": [],
            "unsupported_scope": unsupported_scope,
            "unsupported_source": unsupported_source,
            "unsupported_source_scope": {"scope": scope, "source": source},
        }

    target_lines = list(lines or [])
    preview = build_route_batch_candidate_adoption_preview(
        target_lines,
        source=source,
        scope=scope,
        route_id=route_id,
        route_label=route_label,
        resolve_path=resolve_path,
        path_exists=path_exists,
        example_limit=1000000,
    )
    line_lookup = {getattr(line, "id", "") or "": line for line in target_lines}
    applied_line_ids = []
    skipped_reasons: dict[str, int] = {}
    applied_count = 0
    first_main_count = 0
    swap_count = 0
    skipped_count = 0
    applied_at = now or datetime.now(timezone.utc).isoformat(timespec="seconds")

    for entry in preview.get("entries", []):
        operation = entry.get("operation")
        if operation not in {"first_main_image", "swap_with_retreat"}:
            skipped_count += 1
            reason = entry.get("skip_reason") or operation or "skipped"
            skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
            continue

        line = line_lookup.get(entry.get("line_id") or "")
        candidate_path = entry.get("after_image_path") or ""
        if not line or not candidate_path:
            skipped_count += 1
            skipped_reasons["line or candidate not found"] = skipped_reasons.get("line or candidate not found", 0) + 1
            continue

        adoption_record = _adoption_record_for_source(
            line,
            source,
            candidate_path,
            resolve_path,
        )
        if adoption_record is None:
            skipped_count += 1
            reason = "adoption source record changed"
            skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
            continue
        provenance_metadata = _adoption_provenance_metadata(adoption_record, source)
        source_generation_info = build_source_generation_info_from_candidate(
            line,
            candidate_path,
            provenance_metadata,
        )
        lineage_info = build_lineage_info_from_candidate(
            line,
            candidate_path,
            provenance_metadata,
        )

        if operation == "swap_with_retreat":
            _append_retreat_record(
                line,
                entry.get("before_image_path") or "",
                entry.get("before_image_field") or "",
                adopted_at=applied_at,
                resolve_path=resolve_path,
            )
            swap_count += 1
        else:
            first_main_count += 1

        line.selected_candidate_path = candidate_path
        line.source_generation_info = source_generation_info
        line.lineage_info = lineage_info
        if source in APPLY_SUPPORTED_SOURCES:
            _mark_adopted_candidate_record(
                line,
                candidate_path,
                adopted_at=applied_at,
                resolve_path=resolve_path,
            )
        applied_count += 1
        applied_line_ids.append(getattr(line, "id", "") or "")

    return {
        "applied_count": applied_count,
        "first_main_image_count": first_main_count,
        "swap_with_retreat_count": swap_count,
        "skipped_count": skipped_count,
        "skipped_reasons": skipped_reasons,
        "applied_line_ids": applied_line_ids,
        "unsupported_scope": "",
        "unsupported_source": "",
        "unsupported_source_scope": {},
    }


def _signature_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _signature_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_signature_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_signature_value(item) for item in value), key=lambda item: str(item))
    return {"unsupported_type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _signature_digest(value: Any) -> str:
    payload = json.dumps(_signature_value(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolved_path(path: Any, resolve_path: PathResolver | None) -> str:
    clean_path = str(path or "").strip()
    if not clean_path:
        return ""
    try:
        return str(resolve_path(clean_path) or clean_path) if resolve_path else clean_path
    except (OSError, TypeError, ValueError):
        return clean_path


def _file_signature(
    path: Any,
    *,
    resolve_path: PathResolver | None,
    path_exists: PathExists | None,
    path_stat: PathStat | None,
) -> dict[str, Any]:
    raw_path = str(path or "").strip()
    resolved_path = _resolved_path(raw_path, resolve_path)
    if not raw_path:
        return {"path": "", "resolved_path": "", "exists": False, "stat": {}}
    try:
        exists = bool(path_exists(resolved_path)) if path_exists else os.path.exists(resolved_path)
    except (OSError, TypeError, ValueError):
        exists = False
    stat_payload = {}
    if exists:
        try:
            stat_result = path_stat(resolved_path) if path_stat else os.stat(resolved_path)
            stat_payload = {
                "size": int(getattr(stat_result, "st_size", 0) or 0),
                "mtime_ns": int(
                    getattr(
                        stat_result,
                        "st_mtime_ns",
                        int(getattr(stat_result, "st_mtime", 0) * 1_000_000_000),
                    )
                    or 0
                ),
            }
        except (OSError, TypeError, ValueError):
            stat_payload = {}
    return {
        "path": raw_path,
        "resolved_path": resolved_path,
        "exists": exists,
        "stat": stat_payload,
    }


def _record_collection_signature(
    value: Any,
    *,
    resolve_path: PathResolver | None,
    path_exists: PathExists | None,
    path_stat: PathStat | None,
) -> dict[str, Any]:
    if not isinstance(value, list):
        return {
            "collection_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "records": [],
        }
    records = []
    for record in value:
        if isinstance(record, dict):
            records.append(
                {
                    "record": _signature_value(record),
                    "file": _file_signature(
                        record.get("path"),
                        resolve_path=resolve_path,
                        path_exists=path_exists,
                        path_stat=path_stat,
                    ),
                }
            )
        else:
            records.append({"record": _signature_value(record), "file": {}})
    return {"collection_type": "list", "records": records}


def _selected_routes_signature_payload(
    project: Any,
    selected_route_ids: Any,
    *,
    source: str,
    project_path: str,
    resolve_path: PathResolver | None,
    path_exists: PathExists | None,
    path_stat: PathStat | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from core.route_operations import resolve_selected_route_export_lines

    resolution = resolve_selected_route_export_lines(project, selected_route_ids)
    raw_lines = getattr(project, "prompt_lines", None) if project is not None else None
    lines = list(raw_lines) if isinstance(raw_lines, (list, tuple)) else []
    structure = []
    line_state = []
    target_ids = set(resolution.get("target_line_ids") or [])
    for project_order, line in enumerate(lines):
        line_id = str(getattr(line, "id", "") or "").strip()
        structure.append(
            {
                "project_order": project_order,
                "line_id": line_id,
                "line_type": str(getattr(line, "line_type", "") or ""),
                "deleted": bool(getattr(line, "deleted", False)),
                "separator_label": str(getattr(line, "separator_label", "") or ""),
                "separator_color": str(getattr(line, "separator_color", "") or ""),
            }
        )
        if line_id not in target_ids:
            continue
        image_references = {
            field: _file_signature(
                getattr(line, field, None),
                resolve_path=resolve_path,
                path_exists=path_exists,
                path_stat=path_stat,
            )
            for field in ("selected_candidate_path", "generated_image_path", "image_path")
        }
        line_state.append(
            {
                "project_order": project_order,
                "line_id": line_id,
                "current_text_hash": _signature_digest(str(getattr(line, "current_text", "") or "")),
                "negative_prompt_hash": _signature_digest(str(getattr(line, "negative_prompt", "") or "")),
                "source_generation_info": _signature_value(getattr(line, "source_generation_info", {})),
                "lineage_info": _signature_value(getattr(line, "lineage_info", {})),
                "image_references": image_references,
                "generated_candidates": _record_collection_signature(
                    getattr(line, "generated_candidates", None),
                    resolve_path=resolve_path,
                    path_exists=path_exists,
                    path_stat=path_stat,
                ),
                "gallery_variants": _record_collection_signature(
                    getattr(line, "gallery_variants", None),
                    resolve_path=resolve_path,
                    path_exists=path_exists,
                    path_stat=path_stat,
                ),
            }
        )
    payload = {
        "scope": "selected_routes",
        "source": source,
        "project_path": str(project_path or ""),
        "selected_route_ids": list(resolution.get("resolved_route_handles") or []),
        "selected_route_labels": list(resolution.get("resolved_route_labels") or []),
        "target_line_ids": list(resolution.get("target_line_ids") or []),
        "project_structure": structure,
        "target_line_state": line_state,
    }
    return payload, resolution


def build_selected_routes_candidate_adoption_signature(
    project: Any,
    selected_route_ids: Any,
    *,
    source: str = "latest",
    project_path: str = "",
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
    path_stat: PathStat | None = None,
) -> str:
    payload, _resolution = _selected_routes_signature_payload(
        project,
        selected_route_ids,
        source=source,
        project_path=project_path,
        resolve_path=resolve_path,
        path_exists=path_exists,
        path_stat=path_stat,
    )
    return _signature_digest(payload)


def build_selected_routes_candidate_adoption_preview(
    project: Any,
    selected_route_ids: Any,
    *,
    source: str = "latest",
    project_path: str = "",
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
    path_stat: PathStat | None = None,
    example_limit: int = 20,
) -> dict[str, Any]:
    from core.route_operations import sanitize_selected_route_ids

    payload, resolution = _selected_routes_signature_payload(
        project,
        selected_route_ids,
        source=source,
        project_path=project_path,
        resolve_path=resolve_path,
        path_exists=path_exists,
        path_stat=path_stat,
    )
    selection = sanitize_selected_route_ids(project, selected_route_ids)
    allowed_objects = {id(line) for line in resolution.get("target_lines") or []}
    entries = []
    per_route = []
    totals = {
        "targeted_line_count": 0,
        "will_adopt_count": 0,
        "first_main_image_count": 0,
        "swap_with_retreat_count": 0,
        "skipped_count": 0,
    }
    for summary, block in zip(
        selection.get("selected_route_summaries") or [],
        selection.get("selected_route_blocks") or [],
    ):
        route_lines = [
            line for line in block.active_normal_member_lines if id(line) in allowed_objects
        ]
        route_preview = build_route_batch_candidate_adoption_preview(
            route_lines,
            source=source,
            scope="selected_routes",
            route_id=summary.get("route_handle", ""),
            route_label=summary.get("label", ""),
            resolve_path=resolve_path,
            path_exists=path_exists,
            example_limit=1000000,
        )
        for key in totals:
            totals[key] += int(route_preview.get(key, 0) or 0)
        entries.extend(route_preview.get("entries") or [])
        per_route.append(
            {
                "route_id": summary.get("route_handle", ""),
                "route_label": summary.get("label", ""),
                "route_color": summary.get("color"),
                "targeted_line_count": route_preview.get("targeted_line_count", 0),
                "will_adopt_count": route_preview.get("will_adopt_count", 0),
                "applicable_count": route_preview.get("will_adopt_count", 0),
                "first_main_image_count": route_preview.get("first_main_image_count", 0),
                "swap_with_retreat_count": route_preview.get("swap_with_retreat_count", 0),
                "no_op_count": sum(
                    1 for entry in route_preview.get("entries") or [] if entry.get("operation") == "no_op"
                ),
                "skipped_count": route_preview.get("skipped_count", 0),
                "missing_count": sum(
                    1
                    for entry in route_preview.get("entries") or []
                    if entry.get("skip_reason") in {"missing candidate file", "missing gallery variant file"}
                ),
                "blocked_count": sum(
                    1
                    for entry in route_preview.get("entries") or []
                    if entry.get("skip_reason")
                    in {
                        "missing candidate file",
                        "missing gallery variant file",
                        "adoption target not found",
                        "gallery variant target not found",
                        "trashed candidate only",
                    }
                ),
                "invalid_count": 0,
                "drift_count": sum(
                    1 for entry in route_preview.get("entries") or [] if entry.get("prompt_drift")
                ),
            }
        )
    no_op_count = sum(1 for entry in entries if entry.get("operation") == "no_op")
    blocked_reasons = {
        "missing candidate file",
        "missing gallery variant file",
        "adoption target not found",
        "gallery variant target not found",
        "trashed candidate only",
    }
    blocked_count = sum(1 for entry in entries if entry.get("skip_reason") in blocked_reasons)
    missing_count = sum(
        1
        for entry in entries
        if entry.get("skip_reason") in {"missing candidate file", "missing gallery variant file"}
    )
    diagnostics = list(resolution.get("diagnostics") or [])
    for line in resolution.get("target_lines") or []:
        line_id = str(getattr(line, "id", "") or "").strip()
        for field_name in ("generated_candidates", "gallery_variants"):
            records = getattr(line, field_name, None)
            if not isinstance(records, list):
                continue
            record_ids: dict[str, int] = {}
            for record in records:
                record_id = str(record.get("id") or "").strip() if isinstance(record, dict) else ""
                if record_id:
                    record_ids[record_id] = record_ids.get(record_id, 0) + 1
            diagnostics.extend(
                f"{line_id}: duplicate {field_name} id: {record_id}"
                for record_id, count in sorted(record_ids.items())
                if count > 1
            )
    return {
        "scope": "selected_routes",
        "source": source,
        "signature": _signature_digest(payload),
        "selected_route_ids": list(resolution.get("resolved_route_handles") or []),
        "selected_route_labels": list(resolution.get("resolved_route_labels") or []),
        "selected_route_count": int(resolution.get("selected_route_count", 0) or 0),
        "route_summaries": per_route,
        "target_line_ids": list(resolution.get("target_line_ids") or []),
        **totals,
        "applicable_count": totals["will_adopt_count"],
        "no_op_count": no_op_count,
        "blocked_count": blocked_count,
        "missing_count": missing_count,
        "invalid_count": len(diagnostics),
        "drift_count": sum(1 for entry in entries if entry.get("prompt_drift")),
        "diagnostics": diagnostics,
        "scope_warnings": diagnostics,
        "drift_warning": DRIFT_WARNING,
        "prompt_text_unchanged": True,
        "apply_implemented": True,
        "valid": bool(resolution.get("valid")),
        "reason": resolution.get("reason", ""),
        "entries": entries[:example_limit],
        "skipped_entries": [
            entry for entry in entries if entry.get("operation") in {"skipped", "no_op"}
        ][:example_limit],
        "entry_count": len(entries),
        "skipped_entry_count": totals["skipped_count"],
        "example_limit": example_limit,
    }


def apply_selected_routes_candidate_adoption(
    project: Any,
    selected_route_ids: Any,
    *,
    expected_signature: str,
    source: str = "latest",
    project_path: str = "",
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
    path_stat: PathStat | None = None,
    now: str | None = None,
    mutation_hook: Callable[[Any, dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Build and apply a Selected Routes plan on a clone, never partially mutating the source."""

    current_preview = build_selected_routes_candidate_adoption_preview(
        project,
        selected_route_ids,
        source=source,
        project_path=project_path,
        resolve_path=resolve_path,
        path_exists=path_exists,
        path_stat=path_stat,
        example_limit=1000000,
    )
    if not expected_signature or current_preview.get("signature") != expected_signature:
        return {
            "applied": False,
            "stale_preview": True,
            "applied_count": 0,
            "skipped_count": 0,
            "error": "Selected Routes Candidate Adoption preview is stale",
            "updated_project": None,
        }
    if not current_preview.get("valid") or int(current_preview.get("will_adopt_count", 0) or 0) <= 0:
        return {
            "applied": False,
            "stale_preview": False,
            "applied_count": 0,
            "skipped_count": int(current_preview.get("skipped_count", 0) or 0),
            "error": current_preview.get("reason") or "no applicable Candidate adoption targets",
            "updated_project": None,
        }

    try:
        working_project = copy.deepcopy(project)
        working_preview = build_selected_routes_candidate_adoption_preview(
            working_project,
            selected_route_ids,
            source=source,
            project_path=project_path,
            resolve_path=resolve_path,
            path_exists=path_exists,
            path_stat=path_stat,
            example_limit=1000000,
        )
        if working_preview.get("signature") != expected_signature:
            return {
                "applied": False,
                "stale_preview": True,
                "applied_count": 0,
                "skipped_count": 0,
                "error": "Selected Routes Candidate Adoption preview changed before apply",
                "updated_project": None,
            }
        target_ids = set(working_preview.get("target_line_ids") or [])
        target_lines = [
            line
            for line in getattr(working_project, "prompt_lines", [])
            if str(getattr(line, "id", "") or "").strip() in target_ids
        ]
        result = apply_route_batch_candidate_adoption_preview(
            target_lines,
            scope="selected_routes",
            source=source,
            resolve_path=resolve_path,
            path_exists=path_exists,
            now=now,
        )
        if int(result.get("applied_count", 0) or 0) != int(working_preview.get("will_adopt_count", 0) or 0):
            raise RuntimeError("Selected Routes Candidate Adoption plan changed during apply")
        if mutation_hook:
            mutation_hook(working_project, result)
    except Exception as exc:
        return {
            "applied": False,
            "stale_preview": False,
            "applied_count": 0,
            "skipped_count": 0,
            "error": str(exc),
            "updated_project": None,
        }

    return {
        **result,
        "applied": True,
        "stale_preview": False,
        "error": "",
        "updated_project": working_project,
        "selected_route_ids": list(working_preview.get("selected_route_ids") or []),
        "selected_route_labels": list(working_preview.get("selected_route_labels") or []),
    }
