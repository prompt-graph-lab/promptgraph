"""Selected Routes planning and result routing for Gallery Generation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from collections import Counter
from typing import Any, Callable

from core.route_operations import sanitize_selected_route_ids


RequestBuilder = Callable[[Any, int], Any]
CandidateFactory = Callable[[str, Any, dict[str, Any]], Any]
CandidateAppender = Callable[[Any, list[Any]], None]
RequestSubmitter = Callable[[dict[str, Any]], Any]
PathResolver = Callable[[str], str]
PathExists = Callable[[str], bool]


def _safe_lines(project: Any) -> tuple[list[Any], list[str]]:
    if project is None:
        return [], ["project is missing"]
    value = getattr(project, "prompt_lines", None)
    if not isinstance(value, (list, tuple)):
        return [], ["prompt_lines is not a list"]
    return list(value), []


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
        return sorted((_signature_value(item) for item in value), key=str)
    return {"unsupported_type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _digest(value: Any) -> str:
    payload = json.dumps(
        _signature_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _line_type(line: Any) -> str:
    return str(getattr(line, "line_type", "") or "")


def _line_label(line: Any) -> str:
    return str(
        getattr(line, "original_file_name", "")
        or getattr(line, "id", "")
        or "Line"
    )


def _request_builder_result(value: Any) -> tuple[Any, str]:
    if isinstance(value, tuple) and len(value) == 2:
        return value[0], str(value[1] or "")
    if isinstance(value, dict) and "workflow_json" in value:
        return value.get("workflow_json"), str(value.get("warning") or "")
    return value, ""


def build_selected_routes_generation_plan(
    project: Any,
    selected_route_ids: Any,
    *,
    run_count: Any = 1,
    generation_options: Any = None,
    project_path: str = "",
    request_builder: RequestBuilder | None = None,
    example_limit: int = 20,
) -> dict[str, Any]:
    """Build a non-mutating, physical-order generation plan.

    ``request_builder`` may parse or read an existing workflow, but this helper
    never submits requests, writes files, mutates Project data, or adds
    Candidates. A builder failure blocks the whole plan before submission.
    """

    lines, diagnostics = _safe_lines(project)
    selection = sanitize_selected_route_ids(project, selected_route_ids)
    diagnostics.extend(selection.get("diagnostics") or [])
    for field_name, label in (
        ("removed_missing_ids", "missing Route id"),
        ("removed_deleted_ids", "deleted Route id"),
        ("removed_non_separator_ids", "non-separator selected id"),
        ("removed_duplicate_ids", "duplicate or ambiguous Route id"),
    ):
        diagnostics.extend(
            f"ignored {label}: {value or '(empty)'}"
            for value in selection.get(field_name, [])
        )

    try:
        normalized_run_count = int(run_count)
    except (TypeError, ValueError, OverflowError):
        normalized_run_count = 0
    if normalized_run_count < 1:
        diagnostics.append("generation count must be at least 1")

    if generation_options is None:
        options = {}
    elif isinstance(generation_options, dict):
        options = generation_options
    else:
        options = {}
        diagnostics.append("generation options are malformed")

    try:
        preview_limit = max(0, int(example_limit))
    except (TypeError, ValueError, OverflowError):
        preview_limit = 20
        diagnostics.append("preview limit is malformed")

    line_id_counts = Counter(
        str(getattr(line, "id", "") or "").strip()
        for line in lines
        if str(getattr(line, "id", "") or "").strip()
    )
    selected_handles = list(selection.get("selected_route_ids") or [])
    selected_handle_set = set(selected_handles)
    route_order_by_handle = {
        route_handle: route_order
        for route_order, route_handle in enumerate(selected_handles)
    }
    route_summary_by_handle = {
        str(summary.get("route_handle") or ""): summary
        for summary in selection.get("selected_route_summaries") or []
        if isinstance(summary, dict)
    }

    target_lines = []
    line_entries = []
    skipped_lines = []
    blocked_lines = []
    route_entries: dict[str, dict[str, Any]] = {}
    current_route_handle = ""
    current_route_line_order = 0

    for project_order, line in enumerate(lines):
        line_type = _line_type(line)
        line_id = str(getattr(line, "id", "") or "").strip()
        if line_type == "separator":
            current_route_handle = line_id if line_id in selected_handle_set else ""
            current_route_line_order = 0
            if current_route_handle:
                summary = route_summary_by_handle.get(current_route_handle, {})
                route_entries[current_route_handle] = {
                    "route_handle": current_route_handle,
                    "route_label": str(summary.get("label") or getattr(line, "separator_label", "") or line_id),
                    "route_order": route_order_by_handle[current_route_handle],
                    "project_order": project_order,
                    "target_line_count": 0,
                    "request_count": 0,
                    "expected_image_count": 0,
                    "skipped_count": 0,
                    "blocked_count": 0,
                }
            continue
        if not current_route_handle:
            continue

        route_entry = route_entries[current_route_handle]
        if line_type == "workbench":
            route_entry["skipped_count"] += 1
            skipped_lines.append({
                "line_id": line_id,
                "line_label": _line_label(line),
                "route_handle": current_route_handle,
                "project_order": project_order,
                "reason": "Workbench line",
            })
            continue
        if getattr(line, "deleted", False):
            route_entry["skipped_count"] += 1
            skipped_lines.append({
                "line_id": line_id,
                "line_label": _line_label(line),
                "route_handle": current_route_handle,
                "project_order": project_order,
                "reason": "deleted line",
            })
            continue

        route_line_order = current_route_line_order
        current_route_line_order += 1
        reason = ""
        if not line_id:
            reason = "line id is missing"
        elif line_id_counts[line_id] > 1:
            reason = "duplicate or ambiguous Line id"
        elif not isinstance(getattr(line, "generated_candidates", None), list):
            reason = "generated_candidates is malformed"

        entry = {
            "line_id": line_id,
            "line_label": _line_label(line),
            "route_handle": current_route_handle,
            "route_label": route_entry["route_label"],
            "route_order": route_entry["route_order"],
            "project_order": project_order,
            "route_line_order": route_line_order,
            "prompt": str(getattr(line, "current_text", "") or ""),
            "negative_prompt": str(getattr(line, "negative_prompt", "") or ""),
            "prompt_preview": str(getattr(line, "current_text", "") or "")[:240],
            "negative_prompt_preview": str(getattr(line, "negative_prompt", "") or "")[:240],
            "prompt_hash": _digest(str(getattr(line, "current_text", "") or "")),
            "negative_prompt_hash": _digest(str(getattr(line, "negative_prompt", "") or "")),
            "source_generation_info": _signature_value(getattr(line, "source_generation_info", {})),
            "tokens": _signature_value(getattr(line, "tokens", None)),
            "request_count": normalized_run_count if not reason else 0,
            "expected_candidate_count": normalized_run_count if not reason else 0,
            "blocked_reason": reason,
        }
        line_entries.append(entry)
        if reason:
            route_entry["blocked_count"] += 1
            blocked_lines.append(entry)
            diagnostics.append(f"{line_id or '(missing Line id)'}: {reason}")
            continue
        target_lines.append(line)
        route_entry["target_line_count"] += 1

    workflow_plan = {}
    preflight_blocked_line_ids = set()
    entry_by_id = {entry["line_id"]: entry for entry in line_entries if not entry["blocked_reason"]}
    if normalized_run_count > 0 and request_builder is not None:
        for line in target_lines:
            line_id = str(getattr(line, "id", "") or "").strip()
            line_entry = entry_by_id[line_id]
            try:
                workflow_json, warning = _request_builder_result(
                    request_builder(copy.deepcopy(line), 1)
                )
                if not isinstance(workflow_json, dict):
                    raise ValueError("workflow builder did not return a workflow object")
                workflow_plan[line_id] = {
                    "workflow_json": workflow_json,
                    "workflow_warning": warning,
                }
            except Exception as exc:
                reason = f"request preflight failed: {exc}"
                line_entry["blocked_reason"] = reason
                line_entry["request_count"] = 0
                line_entry["expected_candidate_count"] = 0
                blocked_lines.append({**line_entry, "run_index": 1})
                diagnostics.append(f"{line_id}: {reason}")
                route_entries[line_entry["route_handle"]]["blocked_count"] += 1
                preflight_blocked_line_ids.add(line_id)

    request_plan = []
    if normalized_run_count > 0 and request_builder is not None:
        for line in target_lines:
            line_id = str(getattr(line, "id", "") or "").strip()
            if line_id in preflight_blocked_line_ids:
                continue
            line_entry = entry_by_id[line_id]
            for run_index in range(1, normalized_run_count + 1):
                request_id = f"gallery_generation:{line_id}:{run_index}"
                request_plan.append({
                    "request_id": request_id,
                    "source_line_id": line_id,
                    "source_line_label": line_entry["line_label"],
                    "source_route_handle": line_entry["route_handle"],
                    "source_route_label": line_entry["route_label"],
                    "source_project_order": line_entry["project_order"],
                    "source_route_line_order": line_entry["route_line_order"],
                    "run_index": run_index,
                    "workflow_key": line_id,
                })

    blocked_line_ids = {
        str(entry.get("line_id") or "")
        for entry in blocked_lines
        if str(entry.get("line_id") or "")
    }
    if blocked_line_ids:
        request_plan = [
            request
            for request in request_plan
            if request["source_line_id"] not in blocked_line_ids
        ]
    for route_entry in route_entries.values():
        if request_builder is None:
            route_request_count = route_entry["target_line_count"] * max(0, normalized_run_count)
        else:
            route_request_count = sum(
                1
                for request in request_plan
                if request["source_route_handle"] == route_entry["route_handle"]
            )
        route_entry["request_count"] = route_request_count
        route_entry["expected_image_count"] = route_request_count

    structure = [
        {
            "project_order": index,
            "line_id": str(getattr(line, "id", "") or ""),
            "line_type": _line_type(line),
            "deleted": bool(getattr(line, "deleted", False)),
            "separator_label": str(getattr(line, "separator_label", "") or ""),
            "separator_color": str(getattr(line, "separator_color", "") or ""),
        }
        for index, line in enumerate(lines)
    ]
    input_signature_payload = {
        "scope": "selected_routes",
        "project_path": str(project_path or ""),
        "selected_route_ids": selected_handles,
        "project_structure": structure,
        "generation_options": _signature_value(options),
        "run_count": normalized_run_count,
        "project_metadata_hash": _digest(getattr(project, "project_metadata", None)),
        "module_library_hash": _digest(getattr(project, "module_library", None)),
        "line_entries": [
            {
                key: value
                for key, value in entry.items()
                if key not in {
                    "prompt",
                    "negative_prompt",
                    "prompt_preview",
                    "negative_prompt_preview",
                    "blocked_reason",
                    "request_count",
                    "expected_candidate_count",
                }
            }
            for entry in line_entries
        ],
        "target_request_shape": {
            "target_line_ids": [
                str(getattr(line, "id", "") or "").strip()
                for line in target_lines
            ],
            "run_count": normalized_run_count,
        },
    }
    input_signature = _digest(input_signature_payload)
    workflow_signatures = {
        line_id: _digest(item.get("workflow_json"))
        for line_id, item in sorted(workflow_plan.items())
    }
    signature_payload = {
        "input_signature": input_signature,
        "preflight_complete": request_builder is not None,
        "workflow_signatures": workflow_signatures,
    }
    signature = _digest(signature_payload)
    reason = ""
    if not selected_handles:
        reason = "Selected Routesがありません。"
    elif not target_lines:
        reason = "選択されたRouteに生成対象Lineがありません。"
    elif blocked_lines:
        reason = "生成前チェックに失敗したLineがあります。"
    elif request_builder is not None and not request_plan:
        reason = "生成requestがありません。"

    route_summaries = sorted(route_entries.values(), key=lambda item: item["route_order"])
    valid = not reason and normalized_run_count > 0
    return {
        "scope": "selected_routes",
        "resolved_route_handles": selected_handles,
        "resolved_route_labels": list(selection.get("selected_route_labels") or []),
        "selected_route_count": len(selected_handles),
        "target_lines": target_lines,
        "target_line_ids": [str(getattr(line, "id", "") or "") for line in target_lines],
        "target_line_count": len(target_lines),
        "route_summaries": route_summaries,
        "line_entries": line_entries[:preview_limit],
        "line_entry_count": len(line_entries),
        "hidden_line_count": max(0, len(line_entries) - preview_limit),
        "skipped_lines": skipped_lines,
        "skipped_line_count": len(skipped_lines),
        "blocked_lines": blocked_lines,
        "blocked_line_count": len(blocked_lines),
        "request_plan": request_plan,
        "workflow_plan": workflow_plan,
        "request_count": (
            len(request_plan)
            if request_builder is not None
            else len(target_lines) * max(0, normalized_run_count)
        ),
        "expected_image_count": (
            len(request_plan)
            if request_builder is not None
            else len(target_lines) * max(0, normalized_run_count)
        ),
        "generation_options": _signature_value(options),
        "source_fingerprint": _digest({"project_structure": structure, "line_entries": line_entries}),
        "input_signature_payload": input_signature_payload,
        "input_signature": input_signature,
        "signature_payload": signature_payload,
        "signature": signature,
        "preflight_complete": request_builder is not None,
        "diagnostics": diagnostics,
        "valid": valid,
        "reason": reason,
    }


def resolve_gallery_generation_result_target(project: Any, source_line_id: Any) -> dict[str, Any]:
    """Resolve one active normal source Line by unambiguous stable ID."""

    lines, diagnostics = _safe_lines(project)
    line_id = str(source_line_id or "").strip()
    if not line_id:
        return {"target_line": None, "reason": "source Line id is missing", "diagnostics": diagnostics}
    matches = [line for line in lines if str(getattr(line, "id", "") or "").strip() == line_id]
    if not matches:
        return {"target_line": None, "reason": "source Line is missing", "diagnostics": diagnostics}
    if len(matches) != 1:
        return {"target_line": None, "reason": "source Line id is ambiguous", "diagnostics": diagnostics}
    line = matches[0]
    if getattr(line, "deleted", False):
        return {"target_line": None, "reason": "source Line is deleted", "diagnostics": diagnostics}
    if _line_type(line) in {"separator", "workbench"}:
        return {"target_line": None, "reason": "source Line is not a normal Line", "diagnostics": diagnostics}
    return {"target_line": line, "reason": "", "diagnostics": diagnostics}


def validate_selected_routes_generation_submit(
    stored_preview: Any,
    current_preview: Any,
) -> dict[str, Any]:
    """Require an unchanged, valid Fresh Preview before any request submission."""

    if (
        not isinstance(stored_preview, dict)
        or not stored_preview.get("signature")
        or not stored_preview.get("preflight_complete")
    ):
        return {"allowed": False, "reason": "Fresh Previewが必要です。"}
    if not isinstance(current_preview, dict) or not current_preview.get("valid"):
        return {
            "allowed": False,
            "reason": str((current_preview or {}).get("reason") or "現在の生成planが無効です。"),
        }
    if stored_preview.get("input_signature") != current_preview.get("input_signature"):
        return {"allowed": False, "reason": "Previewが古くなりました。Fresh Previewを再実行してください。"}
    if (
        current_preview.get("preflight_complete")
        and stored_preview.get("signature") != current_preview.get("signature")
    ):
        return {"allowed": False, "reason": "Workflow Previewが古くなりました。Fresh Previewを再実行してください。"}
    if not stored_preview.get("valid"):
        return {"allowed": False, "reason": str(stored_preview.get("reason") or "Previewが無効です。")}
    return {"allowed": True, "reason": ""}


def ingest_gallery_generation_outputs(
    project: Any,
    request: Any,
    output_paths: Any,
    *,
    candidate_factory: CandidateFactory,
    candidate_appender: CandidateAppender,
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
) -> dict[str, Any]:
    """Append only real, unique outputs to the request's stable source Line."""

    if not isinstance(request, dict):
        return {"added_count": 0, "added_paths": [], "reason": "generation request is malformed"}
    target = resolve_gallery_generation_result_target(project, request.get("source_line_id"))
    line = target.get("target_line")
    if line is None:
        return {"added_count": 0, "added_paths": [], "reason": target.get("reason", "invalid source Line")}
    if not isinstance(output_paths, (list, tuple)):
        return {"added_count": 0, "added_paths": [], "reason": "generation outputs are malformed"}

    def resolved_path(value: Any) -> str:
        raw_path = str(value or "").strip()
        if not raw_path:
            return ""
        try:
            return str(resolve_path(raw_path) or "").strip() if resolve_path else os.path.abspath(raw_path)
        except (OSError, TypeError, ValueError):
            return ""

    existing_paths = {
        os.path.normcase(os.path.abspath(candidate_path))
        for record in getattr(line, "generated_candidates", [])
        if isinstance(record, dict)
        for candidate_path in [resolved_path(record.get("path"))]
        if candidate_path
    } if isinstance(getattr(line, "generated_candidates", None), list) else set()
    unique_paths = []
    seen = set()
    diagnostics = []
    for value in output_paths:
        raw_path = str(value or "").strip()
        path = resolved_path(raw_path)
        if not raw_path or not path:
            if raw_path:
                diagnostics.append(f"could not resolve generation output: {raw_path}")
            continue
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized in seen or normalized in existing_paths:
            continue
        try:
            exists = bool(path_exists(path)) if path_exists else os.path.isfile(path)
        except (OSError, TypeError, ValueError):
            exists = False
        if not exists:
            diagnostics.append(f"missing generation output: {raw_path}")
            continue
        seen.add(normalized)
        unique_paths.append(path)
    record_pairs = [
        (path, candidate_factory(path, line, request))
        for path in unique_paths
    ]
    record_pairs = [(path, record) for path, record in record_pairs if record]
    records = [record for _path, record in record_pairs]
    if records:
        candidate_appender(line, records)
    return {
        "added_count": len(records),
        "added_paths": [path for path, _record in record_pairs],
        "reason": "" if records else (
            "no existing generation outputs" if diagnostics else "no new generation outputs"
        ),
        "diagnostics": diagnostics,
        "source_line_id": str(request.get("source_line_id") or ""),
        "request_id": str(request.get("request_id") or ""),
    }


def execute_gallery_generation_plan(
    project: Any,
    plan: Any,
    *,
    submitter: RequestSubmitter,
    candidate_factory: CandidateFactory,
    candidate_appender: CandidateAppender,
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
) -> dict[str, Any]:
    """Execute a preflighted plan sequentially and report partial failures."""

    if (
        not isinstance(plan, dict)
        or not plan.get("valid")
        or not plan.get("preflight_complete")
    ):
        return {
            "submitted_count": 0,
            "completed_request_count": 0,
            "candidate_count": 0,
            "failures": [],
            "request_results": [],
            "reason": str((plan or {}).get("reason") or "generation plan is not preflighted"),
        }
    requests = plan.get("request_plan")
    if not isinstance(requests, list) or not requests:
        return {
            "submitted_count": 0,
            "completed_request_count": 0,
            "candidate_count": 0,
            "failures": [],
            "request_results": [],
            "reason": "generation request plan is empty",
        }

    submitted_count = 0
    completed_count = 0
    candidate_count = 0
    failures = []
    request_results = []
    seen_request_ids = set()
    workflow_plan = plan.get("workflow_plan") if isinstance(plan.get("workflow_plan"), dict) else {}
    for request in requests:
        if not isinstance(request, dict):
            failures.append({"request_id": "", "error": "generation request is malformed"})
            continue
        request_id = str(request.get("request_id") or "").strip()
        if not request_id or request_id in seen_request_ids:
            failures.append({
                "request_id": request_id,
                "source_line_id": str(request.get("source_line_id") or ""),
                "error": "generation request id is missing or duplicate",
            })
            continue
        seen_request_ids.add(request_id)
        try:
            workflow_item = workflow_plan.get(str(request.get("workflow_key") or ""))
            if not isinstance(workflow_item, dict) or not isinstance(workflow_item.get("workflow_json"), dict):
                raise RuntimeError("preflighted workflow is missing")
            submission_request = {
                **request,
                "workflow_json": copy.deepcopy(workflow_item["workflow_json"]),
                "workflow_warning": str(workflow_item.get("workflow_warning") or ""),
            }
            submitted_count += 1
            submitted = submitter(submission_request)
            if isinstance(submitted, dict):
                output_paths = submitted.get("output_paths", [])
                submit_metadata = {
                    key: value for key, value in submitted.items() if key != "output_paths"
                }
            else:
                output_paths = submitted
                submit_metadata = {}
            ingestion = ingest_gallery_generation_outputs(
                project,
                request,
                output_paths,
                candidate_factory=candidate_factory,
                candidate_appender=candidate_appender,
                resolve_path=resolve_path,
                path_exists=path_exists,
            )
            if ingestion.get("added_count", 0) <= 0:
                ingestion_error = RuntimeError(
                    ingestion.get("reason") or "generation produced no Candidate"
                )
                ingestion_error.diagnostics = list(ingestion.get("diagnostics") or [])
                raise ingestion_error
            completed_count += 1
            candidate_count += int(ingestion.get("added_count", 0) or 0)
            request_results.append({
                "request_id": request_id,
                "source_line_id": str(request.get("source_line_id") or ""),
                "status": "completed",
                "added_count": int(ingestion.get("added_count", 0) or 0),
                "added_paths": list(ingestion.get("added_paths") or []),
                "diagnostics": list(ingestion.get("diagnostics") or []),
                **submit_metadata,
            })
        except Exception as exc:
            failure = {
                "request_id": request_id,
                "source_line_id": str(request.get("source_line_id") or ""),
                "source_route_handle": str(request.get("source_route_handle") or ""),
                "run_index": request.get("run_index"),
                "error": str(exc),
            }
            failure_diagnostics = getattr(exc, "diagnostics", None)
            if failure_diagnostics:
                failure["diagnostics"] = failure_diagnostics
            failures.append(failure)
            request_results.append({**failure, "status": "failed"})

    return {
        "submitted_count": submitted_count,
        "completed_request_count": completed_count,
        "candidate_count": candidate_count,
        "failures": failures,
        "request_results": request_results,
        "reason": "" if completed_count else "no generation request completed",
    }
