"""Pure structural helpers for separator-based Gallery Route operations."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
import copy
import uuid

from core.io import build_source_generation_info_from_candidate


ROUTE_ACTION_SPECS = {
    "generation": {"operation": "generation"},
    "candidate_adoption": {"operation": "candidate_adoption"},
    "final_export": {"operation": "final_export"},
    "lightweight_fork": {"operation": "lightweight_fork"},
}

ROUTE_REMOVALS_METADATA_KEY = "route_removals"


def safe_record_list(value: Any) -> list[Any]:
    """Return only supported record collections without iterating malformed values."""

    return list(value) if isinstance(value, (list, tuple)) else []


def _prompt_lines(project_or_lines: Any) -> list[Any]:
    if project_or_lines is None:
        return []
    lines = getattr(project_or_lines, "prompt_lines", project_or_lines)
    return list(lines or [])


def _is_separator(line: Any) -> bool:
    return getattr(line, "line_type", None) == "separator"


def _is_workbench(line: Any) -> bool:
    return getattr(line, "line_type", None) == "workbench"


def _has_path(record: Any) -> bool:
    return isinstance(record, dict) and bool(str(record.get("path") or "").strip())


def _is_appended_gallery_variant(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        record.get("kind") == "gallery_variant"
        or record.get("source") == "batch_candidate_adoption"
        or str(record.get("id") or "").startswith("variant_")
    )


def _candidate_counts(lines: Iterable[Any]) -> tuple[int, int, int]:
    total = 0
    active = 0
    trashed = 0
    for line in lines:
        for record in safe_record_list(getattr(line, "generated_candidates", None)):
            if not _has_path(record):
                continue
            total += 1
            if isinstance(record, dict) and record.get("trashed"):
                trashed += 1
            else:
                active += 1
    return active, total, trashed


def _gallery_variant_counts(lines: Iterable[Any]) -> tuple[int, int, int]:
    total = 0
    active = 0
    trashed = 0
    for line in lines:
        for record in safe_record_list(getattr(line, "gallery_variants", None)):
            if not _has_path(record) or not _is_appended_gallery_variant(record):
                continue
            total += 1
            if isinstance(record, dict) and record.get("trashed"):
                trashed += 1
            else:
                active += 1
    return active, total, trashed


@dataclass(frozen=True)
class RouteBlock:
    """A read-only positional Route block resolved from a separator line.

    ``block_start_index`` is the separator index. ``block_end_index`` is
    exclusive and points to the next separator or ``len(prompt_lines)``.
    ``block_lines`` includes the separator; member collections do not.
    Counts use structural members unless their name explicitly says active or
    deleted. Candidate and Gallery Variant counts follow visible Gallery
    semantics: active records have a non-empty path and are not trashed.
    """

    separator: Any | None = None
    separator_index: int | None = None
    block_start_index: int | None = None
    block_end_index: int | None = None
    block_lines: tuple[Any, ...] = field(default_factory=tuple)
    member_lines: tuple[Any, ...] = field(default_factory=tuple)
    active_member_lines: tuple[Any, ...] = field(default_factory=tuple)
    deleted_member_lines: tuple[Any, ...] = field(default_factory=tuple)
    normal_member_lines: tuple[Any, ...] = field(default_factory=tuple)
    active_normal_member_lines: tuple[Any, ...] = field(default_factory=tuple)
    deleted_normal_member_lines: tuple[Any, ...] = field(default_factory=tuple)
    workbench_lines: tuple[Any, ...] = field(default_factory=tuple)
    active_workbench_lines: tuple[Any, ...] = field(default_factory=tuple)
    deleted_workbench_lines: tuple[Any, ...] = field(default_factory=tuple)
    previous_separator: Any | None = None
    next_separator: Any | None = None
    route_handle: str = ""
    separator_label: str = ""
    total_block_line_count: int = 0
    normal_member_count: int = 0
    active_member_count: int = 0
    deleted_member_count: int = 0
    active_normal_member_count: int = 0
    deleted_normal_member_count: int = 0
    workbench_count: int = 0
    active_workbench_count: int = 0
    deleted_workbench_count: int = 0
    candidate_count: int = 0
    candidate_total_count: int = 0
    trashed_candidate_count: int = 0
    gallery_variant_count: int = 0
    gallery_variant_total_count: int = 0
    trashed_gallery_variant_count: int = 0
    deleted: bool = False
    resolved: bool = False
    is_valid: bool = False
    diagnostics: tuple[str, ...] = field(default_factory=tuple)

    @property
    def failure_reason(self) -> str:
        return self.diagnostics[0] if self.diagnostics else ""


def _failure(*diagnostics: str) -> RouteBlock:
    return RouteBlock(diagnostics=tuple(diagnostics))


def resolve_route_block(project_or_lines: Any, separator_id: str) -> RouteBlock:
    """Resolve one separator-owned block without mutating the input."""

    lines = _prompt_lines(project_or_lines)
    target_id = str(separator_id or "").strip()
    if not target_id:
        return _failure("separator id not found")

    separator_index = next(
        (index for index, line in enumerate(lines) if getattr(line, "id", "") == target_id),
        None,
    )
    if separator_index is None:
        return _failure("separator id not found")
    separator = lines[separator_index]
    if not _is_separator(separator):
        diagnostics = ["specified line is not a separator"]
        if not any(_is_separator(line) for line in lines[:separator_index]):
            diagnostics.append("head block has no separator")
        return RouteBlock(
            separator=separator,
            separator_index=separator_index,
            block_start_index=None,
            block_end_index=None,
            route_handle="",
            separator_label="",
            deleted=bool(getattr(separator, "deleted", False)),
            resolved=False,
            is_valid=False,
            diagnostics=tuple(diagnostics),
        )

    next_separator_index = next(
        (
            index
            for index, line in enumerate(lines[separator_index + 1:], start=separator_index + 1)
            if _is_separator(line)
        ),
        len(lines),
    )
    member_lines = tuple(lines[separator_index + 1:next_separator_index])
    active_member_lines = tuple(line for line in member_lines if not getattr(line, "deleted", False))
    deleted_member_lines = tuple(line for line in member_lines if getattr(line, "deleted", False))
    normal_member_lines = tuple(line for line in member_lines if not _is_workbench(line))
    active_normal_member_lines = tuple(
        line for line in normal_member_lines if not getattr(line, "deleted", False)
    )
    deleted_normal_member_lines = tuple(
        line for line in normal_member_lines if getattr(line, "deleted", False)
    )
    workbench_lines = tuple(line for line in member_lines if _is_workbench(line))
    active_workbench_lines = tuple(line for line in workbench_lines if not getattr(line, "deleted", False))
    deleted_workbench_lines = tuple(line for line in workbench_lines if getattr(line, "deleted", False))
    candidate_count, candidate_total_count, trashed_candidate_count = _candidate_counts(active_normal_member_lines)
    gallery_variant_count, gallery_variant_total_count, trashed_gallery_variant_count = _gallery_variant_counts(
        active_normal_member_lines
    )

    diagnostics = []
    if getattr(separator, "deleted", False):
        diagnostics.append("separator is deleted")
    if not active_normal_member_lines:
        diagnostics.append("active member is missing")
        diagnostics.append("block is empty")

    previous_separator = next(
        (lines[index] for index in range(separator_index - 1, -1, -1) if _is_separator(lines[index])),
        None,
    )
    next_separator = lines[next_separator_index] if next_separator_index < len(lines) else None
    separator_label = str(
        getattr(separator, "separator_label", None)
        or getattr(separator, "current_text", None)
        or getattr(separator, "original_file_name", None)
        or getattr(separator, "id", "")
        or "Route"
    )
    return RouteBlock(
        separator=separator,
        separator_index=separator_index,
        block_start_index=separator_index,
        block_end_index=next_separator_index,
        block_lines=tuple(lines[separator_index:next_separator_index]),
        member_lines=member_lines,
        active_member_lines=active_member_lines,
        deleted_member_lines=deleted_member_lines,
        normal_member_lines=normal_member_lines,
        active_normal_member_lines=active_normal_member_lines,
        deleted_normal_member_lines=deleted_normal_member_lines,
        workbench_lines=workbench_lines,
        active_workbench_lines=active_workbench_lines,
        deleted_workbench_lines=deleted_workbench_lines,
        previous_separator=previous_separator,
        next_separator=next_separator,
        route_handle=target_id,
        separator_label=separator_label,
        total_block_line_count=next_separator_index - separator_index,
        normal_member_count=len(normal_member_lines),
        active_member_count=len(active_member_lines),
        deleted_member_count=len(deleted_member_lines),
        active_normal_member_count=len(active_normal_member_lines),
        deleted_normal_member_count=len(deleted_normal_member_lines),
        workbench_count=len(workbench_lines),
        active_workbench_count=len(active_workbench_lines),
        deleted_workbench_count=len(deleted_workbench_lines),
        candidate_count=candidate_count,
        candidate_total_count=candidate_total_count,
        trashed_candidate_count=trashed_candidate_count,
        gallery_variant_count=gallery_variant_count,
        gallery_variant_total_count=gallery_variant_total_count,
        trashed_gallery_variant_count=trashed_gallery_variant_count,
        deleted=bool(getattr(separator, "deleted", False)),
        resolved=True,
        is_valid=not bool(getattr(separator, "deleted", False)),
        diagnostics=tuple(diagnostics),
    )


def _route_removal_timestamp(value: Any = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat(timespec="seconds")
    return str(value)


def _project_metadata(project_or_lines: Any) -> dict[str, Any] | None:
    metadata = getattr(project_or_lines, "project_metadata", None)
    return metadata if isinstance(metadata, dict) else None


def _route_removal_records(project_or_lines: Any, *, create: bool = False) -> list[dict[str, Any]] | None:
    metadata = _project_metadata(project_or_lines)
    if metadata is None:
        return None
    if ROUTE_REMOVALS_METADATA_KEY not in metadata:
        if create:
            records = []
            metadata[ROUTE_REMOVALS_METADATA_KEY] = records
            return records
        return []
    records = metadata.get(ROUTE_REMOVALS_METADATA_KEY)
    if isinstance(records, list):
        return records
    # A user/plugin-owned malformed value must never be silently replaced.
    return None


def _route_removal_record_diagnostics(record: Any) -> list[str]:
    if not isinstance(record, dict):
        return ["malformed removal record: record is not an object"]
    diagnostics = []
    if not str(record.get("id") or "").strip():
        diagnostics.append("malformed removal record: missing removal id")
    if not str(record.get("route_handle") or "").strip():
        diagnostics.append("malformed removal record: missing route handle")
    line_ids = record.get("line_ids")
    if not isinstance(line_ids, list) or not all(str(line_id or "").strip() for line_id in line_ids):
        diagnostics.append("malformed removal record: line_ids is not a valid list")
    pre_remove_deleted = record.get("pre_remove_deleted")
    if not isinstance(pre_remove_deleted, dict):
        diagnostics.append("malformed removal record: pre_remove_deleted is not an object")
    changed_ids = record.get("changed_to_deleted_line_ids")
    if not isinstance(changed_ids, list):
        diagnostics.append("malformed removal record: changed_to_deleted_line_ids is not a valid list")
    status = str(record.get("status") or "")
    if status not in {"active", "consumed", "restored"}:
        diagnostics.append("malformed removal record: invalid status")
    return diagnostics


def _valid_route_removal_record(record: Any, *, active_only: bool = False) -> bool:
    diagnostics = _route_removal_record_diagnostics(record)
    if diagnostics:
        return False
    return not active_only or str(record.get("status") or "") == "active"


def _duplicate_route_removal_ids(records: Iterable[Any]) -> set[str]:
    counts: dict[str, int] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("id") or "").strip()
        if record_id:
            counts[record_id] = counts.get(record_id, 0) + 1
    return {record_id for record_id, count in counts.items() if count > 1}


def _ambiguous_active_route_handles(records: Iterable[Any]) -> set[str]:
    counts: dict[str, int] = {}
    for record in records or []:
        if not isinstance(record, dict) or str(record.get("status") or "").strip() != "active":
            continue
        route_handle = str(record.get("route_handle") or "").strip()
        if route_handle:
            counts[route_handle] = counts.get(route_handle, 0) + 1
    return {route_handle for route_handle, count in counts.items() if count > 1}


def get_route_removal_diagnostics(project: Any) -> list[str]:
    """Report malformed or ambiguous removal metadata without mutating it."""

    records = _route_removal_records(project)
    if records is None:
        return ["project_metadata.route_removals is not a list"]

    diagnostics = []
    for index, record in enumerate(records):
        for diagnostic in _route_removal_record_diagnostics(record):
            diagnostics.append(f"route_removals[{index}]: {diagnostic}")
    for record_id in sorted(_duplicate_route_removal_ids(records)):
        diagnostics.append(f"duplicate Route removal id: {record_id}")
    for route_handle in sorted(_ambiguous_active_route_handles(records)):
        diagnostics.append(f"ambiguous active Route handle: {route_handle}")
    return diagnostics


def get_active_route_removal_records(project: Any) -> list[dict[str, Any]]:
    """Return copies of active Route removal records for Trash UI consumers."""

    records = _route_removal_records(project)
    if not records:
        return []
    duplicate_ids = _duplicate_route_removal_ids(records)
    ambiguous_route_handles = _ambiguous_active_route_handles(records)
    return [
        dict(record)
        for record in records
        if _valid_route_removal_record(record, active_only=True)
        and str(record.get("id") or "").strip() not in duplicate_ids
        and str(record.get("route_handle") or "").strip() not in ambiguous_route_handles
    ]


def list_active_route_removal_records(project: Any) -> list[dict[str, Any]]:
    """Compatibility alias for callers that need the active record list."""

    return get_active_route_removal_records(project)


def get_active_route_removal_record(project: Any, route_handle: str) -> dict[str, Any] | None:
    clean_handle = str(route_handle or "").strip()
    return next(
        (
            record
            for record in get_active_route_removal_records(project)
            if str(record.get("route_handle") or "").strip() == clean_handle
        ),
        None,
    )


def _route_removal_result(
    *,
    removed: bool,
    route_handle: str,
    reason: str = "",
    record: dict[str, Any] | None = None,
    affected_line_ids: Iterable[str] = (),
    changed_to_deleted_line_ids: Iterable[str] = (),
    already_deleted_line_ids: Iterable[str] = (),
    diagnostics: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "removed": removed,
        "route_handle": route_handle,
        "reason": reason,
        "record": record or {},
        "record_id": str((record or {}).get("id") or ""),
        "removal_id": str((record or {}).get("id") or ""),
        "affected_line_ids": [line_id for line_id in affected_line_ids if line_id],
        "changed_to_deleted_line_ids": [
            line_id for line_id in changed_to_deleted_line_ids if line_id
        ],
        "already_deleted_line_ids": [line_id for line_id in already_deleted_line_ids if line_id],
        "diagnostics": [diagnostic for diagnostic in diagnostics if diagnostic],
    }


def remove_route_block(
    project: Any,
    separator_id: str,
    *,
    now: Any = None,
    removal_id: str | None = None,
) -> dict[str, Any]:
    """Move one separator-owned Route block into non-destructive Trash.

    The existing PromptLine ``deleted`` flag is the only line state changed.
    The pre-remove mask is stored in ``project_metadata`` so restore can leave
    lines that were already deleted before the Route operation untouched.
    """

    route_handle = str(separator_id or "").strip()
    block = resolve_route_block(project, route_handle)
    if block.separator is None:
        return _route_removal_result(
            removed=False,
            route_handle=route_handle,
            reason="separator not found",
        )
    metadata = _project_metadata(project)
    records = _route_removal_records(project)
    if metadata is not None and records is None:
        return _route_removal_result(
            removed=False,
            route_handle=route_handle,
            reason="malformed removal record",
            diagnostics=["project_metadata.route_removals is not a list"],
        )
    ambiguous_route_handles = _ambiguous_active_route_handles(records or [])
    if route_handle in ambiguous_route_handles:
        return _route_removal_result(
            removed=False,
            route_handle=route_handle,
            reason="ambiguous active Route handle",
            diagnostics=[f"ambiguous active Route handle: {route_handle}"],
        )
    active_record = next(
        (
            record
            for record in records or []
            if _valid_route_removal_record(record, active_only=True)
            and str(record.get("route_handle") or "").strip() == route_handle
        ),
        None,
    )
    malformed_active_record = next(
        (
            record
            for record in records or []
            if isinstance(record, dict)
            and str(record.get("route_handle") or "").strip() == route_handle
            and str(record.get("status") or "") == "active"
            and not _valid_route_removal_record(record, active_only=True)
        ),
        None,
    )
    if malformed_active_record is not None:
        return _route_removal_result(
            removed=False,
            route_handle=route_handle,
            reason="malformed removal record",
            record=dict(malformed_active_record),
            diagnostics=_route_removal_record_diagnostics(malformed_active_record),
        )
    if active_record is not None:
        return _route_removal_result(
            removed=False,
            route_handle=route_handle,
            reason="active removal record already exists",
            record=dict(active_record),
        )
    if not block.resolved or not block.is_valid:
        return _route_removal_result(
            removed=False,
            route_handle=route_handle,
            reason=(
                "separator already deleted without active Route removal record"
                if block.deleted
                else "target is not separator"
            ),
        )

    records = _route_removal_records(project, create=True)
    if records is None:
        return _route_removal_result(
            removed=False,
            route_handle=route_handle,
            reason="project metadata is not available",
        )

    requested_removal_id = str(removal_id or "").strip()
    generated_removal_id = requested_removal_id or f"route_remove_{uuid.uuid4().hex}"
    if any(
        isinstance(record, dict)
        and str(record.get("id") or "").strip() == generated_removal_id
        for record in records
    ):
        return _route_removal_result(
            removed=False,
            route_handle=route_handle,
            reason="duplicate removal id",
            diagnostics=[f"duplicate Route removal id: {generated_removal_id}"],
        )

    line_ids = [str(getattr(line, "id", "") or "") for line in block.block_lines]
    line_ids = [line_id for line_id in line_ids if line_id]
    pre_remove_deleted = {
        str(getattr(line, "id", "") or ""): bool(getattr(line, "deleted", False))
        for line in block.block_lines
        if getattr(line, "id", "")
    }
    changed_to_deleted_line_ids = [
        line_id for line_id in line_ids if not pre_remove_deleted.get(line_id, True)
    ]
    already_deleted_line_ids = [
        line_id for line_id in line_ids if pre_remove_deleted.get(line_id, False)
    ]
    created_at = _route_removal_timestamp(now)
    record = {
        "id": generated_removal_id,
        "route_handle": route_handle,
        "separator_line_id": route_handle,
        "line_ids": line_ids,
        "pre_remove_deleted": pre_remove_deleted,
        "changed_to_deleted_line_ids": changed_to_deleted_line_ids,
        "already_deleted_line_ids": already_deleted_line_ids,
        "route_label": block.separator_label,
        "route_color": getattr(block.separator, "separator_color", None),
        "removed_line_count": len(line_ids),
        "active_line_count_before_remove": len(changed_to_deleted_line_ids),
        "workbench_line_count": len(block.workbench_lines),
        "created_at": created_at,
        "removed_at": created_at,
        "restored_at": None,
        "status": "active",
        "version": 1,
        "diagnostics": [],
    }

    for line in block.block_lines:
        line.deleted = True
    records.append(record)
    return _route_removal_result(
        removed=True,
        route_handle=route_handle,
        record=record,
        affected_line_ids=line_ids,
        changed_to_deleted_line_ids=changed_to_deleted_line_ids,
        already_deleted_line_ids=already_deleted_line_ids,
    )


def _route_restore_result(
    *,
    restored: bool,
    route_handle: str,
    reason: str = "",
    record: dict[str, Any] | None = None,
    restored_line_ids: Iterable[str] = (),
    already_active_line_ids: Iterable[str] = (),
    preserved_deleted_line_ids: Iterable[str] = (),
    missing_line_ids: Iterable[str] = (),
    consumed: bool = False,
    diagnostics: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "restored": restored,
        "route_handle": route_handle,
        "reason": reason,
        "record": record or {},
        "record_id": str((record or {}).get("id") or ""),
        "removal_id": str((record or {}).get("id") or ""),
        "restored_line_ids": [line_id for line_id in restored_line_ids if line_id],
        "already_active_line_ids": [
            line_id for line_id in already_active_line_ids if line_id
        ],
        "preserved_deleted_line_ids": [
            line_id for line_id in preserved_deleted_line_ids if line_id
        ],
        "missing_line_ids": [line_id for line_id in missing_line_ids if line_id],
        "consumed": consumed,
        "record_consumed": consumed,
        "diagnostics": [diagnostic for diagnostic in diagnostics if diagnostic],
    }


def restore_route_block(
    project: Any,
    route_handle: str,
    *,
    removal_id: str | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Atomically restore a Route using its persisted pre-remove deleted mask."""

    clean_handle = str(route_handle or "").strip()
    requested_removal_id = str(removal_id or "").strip()
    metadata = _project_metadata(project)
    records = _route_removal_records(project)
    if metadata is None:
        return _route_restore_result(
            restored=False,
            route_handle=clean_handle,
            reason="project metadata is not available",
        )
    if records is None:
        return _route_restore_result(
            restored=False,
            route_handle=clean_handle,
            reason="malformed removal record",
            diagnostics=["project_metadata.route_removals is not a list"],
        )

    duplicate_ids = _duplicate_route_removal_ids(records)
    if requested_removal_id and requested_removal_id in duplicate_ids:
        return _route_restore_result(
            restored=False,
            route_handle=clean_handle,
            reason="duplicate removal id",
            diagnostics=[f"duplicate Route removal id: {requested_removal_id}"],
        )
    if clean_handle and clean_handle in _ambiguous_active_route_handles(records):
        return _route_restore_result(
            restored=False,
            route_handle=clean_handle,
            reason="ambiguous active Route handle",
            diagnostics=[f"ambiguous active Route handle: {clean_handle}"],
        )

    target_index = None
    if requested_removal_id:
        target_index = next(
            (
                index
                for index, record in enumerate(records)
                if isinstance(record, dict)
                and str(record.get("id") or "").strip() == requested_removal_id
            ),
            None,
        )
    else:
        target_index = next(
            (
                index
                for index, record in enumerate(records)
                if _valid_route_removal_record(record, active_only=True)
                and str(record.get("route_handle") or "").strip() == clean_handle
            ),
            None,
        )
    if target_index is None:
        return _route_restore_result(
            restored=False,
            route_handle=clean_handle,
            reason="removal record not found",
        )

    record = records[target_index]
    record_id = str(record.get("id") or "").strip() if isinstance(record, dict) else ""
    if record_id in duplicate_ids:
        return _route_restore_result(
            restored=False,
            route_handle=clean_handle,
            reason="duplicate removal id",
            record=dict(record) if isinstance(record, dict) else {},
            diagnostics=[f"duplicate Route removal id: {record_id}"],
        )
    record_diagnostics = _route_removal_record_diagnostics(record)
    if record_diagnostics:
        return _route_restore_result(
            restored=False,
            route_handle=clean_handle,
            reason="malformed removal record",
            record=dict(record) if isinstance(record, dict) else {},
            diagnostics=record_diagnostics,
        )
    if str(record.get("status") or "") != "active":
        return _route_restore_result(
            restored=False,
            route_handle=str(record.get("route_handle") or clean_handle),
            reason="removal record already consumed",
            record=dict(record),
            diagnostics=["removal record is not active"],
        )

    record_route_handle = str(record.get("route_handle") or "").strip()
    if record_route_handle in _ambiguous_active_route_handles(records):
        return _route_restore_result(
            restored=False,
            route_handle=record_route_handle,
            reason="ambiguous active Route handle",
            record=dict(record),
            diagnostics=[f"ambiguous active Route handle: {record_route_handle}"],
        )
    line_ids = [str(line_id or "") for line_id in record.get("line_ids", [])]
    line_ids = [line_id for line_id in line_ids if line_id]
    pre_remove_deleted = record.get("pre_remove_deleted")
    changed_ids = [str(line_id or "") for line_id in record.get("changed_to_deleted_line_ids", [])]
    changed_ids = [line_id for line_id in changed_ids if line_id]
    if not isinstance(pre_remove_deleted, dict) or any(
        line_id not in pre_remove_deleted for line_id in line_ids
    ) or any(line_id not in line_ids for line_id in changed_ids):
        return _route_restore_result(
            restored=False,
            route_handle=record_route_handle,
            reason="malformed removal record",
            record=dict(record),
            diagnostics=["removal record deleted mask or changed line ids are inconsistent"],
        )

    line_by_id = {
        str(getattr(line, "id", "") or ""): line
        for line in _prompt_lines(project)
        if getattr(line, "id", "")
    }
    missing_line_ids = [line_id for line_id in line_ids if line_id not in line_by_id]
    restored_line_ids = []
    already_active_line_ids = []
    preserved_deleted_line_ids = []
    for line_id in changed_ids:
        line = line_by_id.get(line_id)
        if line is None:
            continue
        if getattr(line, "deleted", False):
            line.deleted = False
            restored_line_ids.append(line_id)
        else:
            already_active_line_ids.append(line_id)
    for line_id in line_ids:
        if not bool(pre_remove_deleted[line_id]):
            continue
        line = line_by_id.get(line_id)
        if line is None:
            continue
        if getattr(line, "deleted", False):
            preserved_deleted_line_ids.append(line_id)
        else:
            # A pre-existing deleted line may have been individually restored;
            # Route Restore must never re-delete it.
            already_active_line_ids.append(line_id)

    diagnostics = []
    if missing_line_ids:
        diagnostics.append(
            "missing line ids: " + ", ".join(missing_line_ids)
        )
    existing_changed_line_ids = {
        line_id for line_id in changed_ids if line_id in line_by_id
    }
    if not existing_changed_line_ids:
        return _route_restore_result(
            restored=False,
            route_handle=record_route_handle,
            reason="no restorable lines",
            record=dict(record),
            missing_line_ids=missing_line_ids,
            diagnostics=diagnostics,
        )

    reason = "partial restore with missing lines" if missing_line_ids else (
        "no restorable lines" if not restored_line_ids else ""
    )
    restored_at = _route_removal_timestamp(now)
    consumed_record = dict(record)
    consumed_record["restored_at"] = restored_at
    consumed_record["status"] = "consumed"
    consumed_record["restored_line_ids"] = list(restored_line_ids)
    consumed_record["already_active_line_ids"] = list(already_active_line_ids)
    consumed_record["preserved_deleted_line_ids"] = list(preserved_deleted_line_ids)
    consumed_record["missing_line_ids"] = list(missing_line_ids)
    consumed_record["restore_diagnostics"] = list(diagnostics)
    records[target_index] = consumed_record
    return _route_restore_result(
        restored=True,
        route_handle=record_route_handle,
        reason=reason,
        record=consumed_record,
        restored_line_ids=restored_line_ids,
        already_active_line_ids=already_active_line_ids,
        preserved_deleted_line_ids=preserved_deleted_line_ids,
        missing_line_ids=missing_line_ids,
        consumed=True,
        diagnostics=diagnostics,
    )


def restore_removed_route(
    project: Any,
    removal_id_or_route_handle: str,
    *,
    now: Any = None,
) -> dict[str, Any]:
    """Restore by removal id first, falling back to the Route handle."""

    requested = str(removal_id_or_route_handle or "").strip()
    records = _route_removal_records(project)
    duplicate_ids = _duplicate_route_removal_ids(records or [])
    if requested and requested in duplicate_ids:
        return _route_restore_result(
            restored=False,
            route_handle="",
            reason="duplicate removal id",
            diagnostics=[f"duplicate Route removal id: {requested}"],
        )
    matching_record = next(
        (
            record
            for record in records or []
            if isinstance(record, dict) and str(record.get("id") or "").strip() == requested
        ),
        None,
    )
    if matching_record is not None:
        return restore_route_block(
            project,
            str(matching_record.get("route_handle") or "").strip(),
            removal_id=requested,
            now=now,
        )
    return restore_route_block(project, requested, now=now)


def _mutable_prompt_lines(project_or_lines: Any) -> list[Any] | None:
    if project_or_lines is None:
        return None
    if hasattr(project_or_lines, "prompt_lines"):
        lines = getattr(project_or_lines, "prompt_lines", None)
    else:
        lines = project_or_lines
    return lines if isinstance(lines, list) else None


def _route_move_result(
    *,
    moved: bool,
    direction: str,
    route_handle: str,
    source_start: int | None = None,
    source_end: int | None = None,
    destination_index: int | None = None,
    previous_route_handle: str = "",
    next_route_handle: str = "",
    reason: str = "",
    affected_line_ids: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "moved": moved,
        "direction": direction,
        "route_handle": route_handle,
        "source_start": source_start,
        "source_end": source_end,
        "destination_index": destination_index,
        "previous_route_handle": previous_route_handle,
        "next_route_handle": next_route_handle,
        "reason": reason,
        "affected_line_ids": [line_id for line_id in affected_line_ids if line_id],
    }


def get_route_block_move_availability(project_or_lines: Any, separator_id: str) -> dict[str, Any]:
    """Describe whether an active separator block can move up or down."""

    route_handle = str(separator_id or "").strip()
    block = resolve_route_block(project_or_lines, route_handle)
    result = {
        "route_handle": route_handle,
        "can_move_up": False,
        "can_move_down": False,
        "previous_route_handle": "",
        "next_route_handle": "",
        "reason": "",
    }
    if not route_handle:
        result["reason"] = "separator not found"
        return result
    if block.separator is None:
        result["reason"] = "separator not found"
        return result
    if not block.resolved or not block.is_valid:
        result["reason"] = "separator is deleted" if block.deleted else "target is not separator"
        return result

    previous_separator = block.previous_separator
    next_separator = block.next_separator
    previous_handle = str(getattr(previous_separator, "id", "") or "")
    next_handle = str(getattr(next_separator, "id", "") or "")
    result["previous_route_handle"] = previous_handle
    result["next_route_handle"] = next_handle
    if previous_separator is not None:
        previous_block = resolve_route_block(project_or_lines, previous_handle)
        result["can_move_up"] = previous_block.is_valid and not previous_block.deleted
    if next_separator is not None:
        next_block = resolve_route_block(project_or_lines, next_handle)
        result["can_move_down"] = next_block.is_valid and not next_block.deleted
    if not result["can_move_up"] and not result["can_move_down"]:
        result["reason"] = "no adjacent Route"
    return result


def get_route_move_ui_state(
    project_or_lines: Any,
    *,
    route_handle: str,
    focused_line_id: str | None = None,
    highlighted_line_id: str | None = None,
    expanded_line_id: str | None = None,
) -> dict[str, str | None]:
    """Preserve valid Gallery line state after a Route block reorder."""

    lines = _prompt_lines(project_or_lines)
    valid_line_ids = {
        str(getattr(line, "id", "") or "")
        for line in lines
        if getattr(line, "id", "") and not getattr(line, "deleted", False)
    }
    target_route_handle = str(route_handle or "").strip()
    target_route = next(
        (
            line
            for line in lines
            if str(getattr(line, "id", "") or "") == target_route_handle
        ),
        None,
    )
    selected_route_id = (
        target_route_handle
        if target_route is not None
        and _is_separator(target_route)
        and not getattr(target_route, "deleted", False)
        else ""
    )

    def preserve(line_id: str | None) -> str | None:
        clean_id = str(line_id or "").strip()
        return clean_id if clean_id in valid_line_ids else None

    return {
        "focused_line_id": preserve(focused_line_id),
        "highlighted_line_id": preserve(highlighted_line_id),
        "gallery_expanded_line_id": preserve(expanded_line_id),
        "gallery_selected_route_separator_id": selected_route_id,
    }


def get_route_remove_ui_state(
    project_or_lines: Any,
    *,
    route_handle: str,
    focused_line_id: str | None = None,
    highlighted_line_id: str | None = None,
    expanded_line_id: str | None = None,
    selected_route_separator_id: str | None = None,
) -> dict[str, str | None]:
    """Sanitize Gallery state after a Route block becomes deleted."""

    lines = _prompt_lines(project_or_lines)
    active_line_ids = {
        str(getattr(line, "id", "") or "")
        for line in lines
        if getattr(line, "id", "") and not getattr(line, "deleted", False)
    }
    active_separator_ids = {
        str(getattr(line, "id", "") or "")
        for line in lines
        if getattr(line, "id", "") and _is_separator(line) and not getattr(line, "deleted", False)
    }

    def preserve(line_id: str | None) -> str | None:
        clean_id = str(line_id or "").strip()
        return clean_id if clean_id in active_line_ids else None

    selected_route_id = str(selected_route_separator_id or "").strip()
    if selected_route_id not in active_separator_ids:
        selected_route_id = ""
    return {
        "focused_line_id": preserve(focused_line_id),
        "highlighted_line_id": preserve(highlighted_line_id),
        "gallery_expanded_line_id": preserve(expanded_line_id),
        "gallery_selected_route_separator_id": selected_route_id,
        "removed_route_handle": str(route_handle or "").strip(),
    }


def get_route_duplicate_ui_state(
    project_or_lines: Any,
    *,
    source_route_handle: str,
    new_route_handle: str,
    focused_line_id: str | None = None,
    highlighted_line_id: str | None = None,
    expanded_line_id: str | None = None,
    collapsed_routes: dict[str, bool] | None = None,
    default_collapsed: bool = True,
) -> dict[str, Any]:
    """Preserve Gallery state while selecting a newly duplicated Route.

    The collapse map is copied rather than mutated so callers can apply the
    returned state after rebuilding the graph.  Existing Route collapse state
    remains unchanged and the new Route inherits the source state.
    """

    lines = _prompt_lines(project_or_lines)
    active_line_ids = {
        str(getattr(line, "id", "") or "")
        for line in lines
        if getattr(line, "id", "") and not getattr(line, "deleted", False)
    }
    active_separator_ids = {
        str(getattr(line, "id", "") or "")
        for line in lines
        if getattr(line, "id", "")
        and _is_separator(line)
        and not getattr(line, "deleted", False)
    }

    def preserve(line_id: str | None) -> str | None:
        clean_id = str(line_id or "").strip()
        return clean_id if clean_id in active_line_ids else None

    source_handle = str(source_route_handle or "").strip()
    new_handle = str(new_route_handle or "").strip()
    collapsed = dict(collapsed_routes) if isinstance(collapsed_routes, dict) else {}
    if source_handle in collapsed:
        collapsed[new_handle] = bool(collapsed[source_handle])
    else:
        collapsed[new_handle] = bool(default_collapsed)

    return {
        "focused_line_id": preserve(focused_line_id),
        "highlighted_line_id": preserve(highlighted_line_id),
        "gallery_expanded_line_id": preserve(expanded_line_id),
        "gallery_selected_route_separator_id": (
            new_handle if new_handle in active_separator_ids else ""
        ),
        "gallery_collapsed_routes": collapsed,
    }


def _selected_route_lines(project_or_lines: Any) -> tuple[list[Any], list[str]]:
    if project_or_lines is None:
        return [], ["prompt_lines are missing"]
    raw_lines = getattr(project_or_lines, "prompt_lines", project_or_lines)
    if raw_lines is None:
        return [], ["prompt_lines are missing"]
    if not isinstance(raw_lines, (list, tuple)):
        return [], ["prompt_lines is not a list"]
    return list(raw_lines), []


def _selected_route_context(project_or_lines: Any) -> dict[str, Any]:
    lines, diagnostics = _selected_route_lines(project_or_lines)
    id_counts: dict[str, int] = {}
    lines_by_id: dict[str, list[Any]] = {}
    for line in lines:
        line_id = str(getattr(line, "id", "") or "").strip()
        if not line_id:
            continue
        id_counts[line_id] = id_counts.get(line_id, 0) + 1
        lines_by_id.setdefault(line_id, []).append(line)

    duplicate_ids = {
        line_id for line_id, count in id_counts.items() if count > 1
    }
    diagnostics.extend(
        f"ambiguous separator id: {line_id}"
        for line_id in sorted(duplicate_ids)
        if any(_is_separator(line) for line in lines_by_id.get(line_id, []))
    )

    selectable = []
    for line in lines:
        line_id = str(getattr(line, "id", "") or "").strip()
        if not line_id or not _is_separator(line) or line_id in duplicate_ids:
            continue
        if getattr(line, "deleted", False):
            continue
        block = resolve_route_block(lines, line_id)
        if not block.resolved or not block.is_valid or block.separator is not line:
            if block.diagnostics:
                diagnostics.extend(
                    f"{line_id}: {diagnostic}"
                    for diagnostic in block.diagnostics
                    if diagnostic not in {"active member is missing", "block is empty"}
                )
            continue
        selectable.append({"route_handle": line_id, "line": line, "block": block})

    return {
        "lines": lines,
        "lines_by_id": lines_by_id,
        "duplicate_ids": duplicate_ids,
        "selectable": selectable,
        "selectable_by_id": {
            item["route_handle"]: item for item in selectable
        },
        "diagnostics": diagnostics,
    }


def _selected_route_input_ids(selected_route_ids: Any) -> list[Any]:
    if selected_route_ids is None:
        return []
    if isinstance(selected_route_ids, str):
        return [selected_route_ids]
    if isinstance(selected_route_ids, (list, tuple, set, frozenset)):
        return list(selected_route_ids)
    return [selected_route_ids]


def _selected_route_summary(item: dict[str, Any]) -> dict[str, Any]:
    line = item["line"]
    block = item["block"]
    return {
        "route_handle": item["route_handle"],
        "label": block.separator_label,
        "color": getattr(line, "separator_color", None),
        "block_line_count": block.total_block_line_count,
        "active_line_count": 1 + block.active_member_count,
        "main_line_count": block.active_normal_member_count,
        "workbench_count": block.workbench_count,
        "deleted_member_count": block.deleted_member_count,
        "candidate_count": block.candidate_count,
        "gallery_variant_count": block.gallery_variant_count,
        "block": block,
    }


def sanitize_selected_route_ids(
    project_or_lines: Any,
    selected_route_ids: Any,
) -> dict[str, Any]:
    """Normalize session-only Route handles against the current Project order."""

    context = _selected_route_context(project_or_lines)
    selectable = context["selectable"]
    selectable_by_id = context["selectable_by_id"]
    selectable_ids = [item["route_handle"] for item in selectable]
    raw_ids = _selected_route_input_ids(selected_route_ids)
    seen_input_ids: set[str] = set()
    accepted_ids: set[str] = set()
    removed_missing_ids = []
    removed_deleted_ids = []
    removed_non_separator_ids = []
    removed_duplicate_ids = []
    diagnostics = list(context["diagnostics"])

    for raw_id in raw_ids:
        clean_id = str(raw_id or "").strip()
        if not clean_id:
            removed_missing_ids.append(clean_id)
            continue
        if clean_id in seen_input_ids:
            removed_duplicate_ids.append(clean_id)
            continue
        seen_input_ids.add(clean_id)
        matching_lines = context["lines_by_id"].get(clean_id, [])
        if not matching_lines:
            removed_missing_ids.append(clean_id)
            continue
        if clean_id in context["duplicate_ids"]:
            removed_duplicate_ids.append(clean_id)
            diagnostics.append(f"ambiguous selected Route id: {clean_id}")
            continue
        matching_line = matching_lines[0]
        if not _is_separator(matching_line):
            removed_non_separator_ids.append(clean_id)
            continue
        if getattr(matching_line, "deleted", False):
            removed_deleted_ids.append(clean_id)
            continue
        if clean_id not in selectable_by_id:
            diagnostics.append(f"selected Route is not selectable: {clean_id}")
            continue
        accepted_ids.add(clean_id)

    selected_items = [item for item in selectable if item["route_handle"] in accepted_ids]
    selected_summaries = [_selected_route_summary(item) for item in selected_items]
    selectable_summaries = [_selected_route_summary(item) for item in selectable]
    selected_blocks = [item["block"] for item in selected_items]
    selected_line_count = sum(block.total_block_line_count for block in selected_blocks)
    selected_deleted_member_count = sum(block.deleted_member_count for block in selected_blocks)
    selected_active_line_count = selected_line_count - selected_deleted_member_count
    selected_main_line_count = sum(block.active_normal_member_count for block in selected_blocks)
    selected_workbench_count = sum(block.workbench_count for block in selected_blocks)
    selected_candidate_count = sum(block.candidate_count for block in selected_blocks)
    selected_gallery_variant_count = sum(block.gallery_variant_count for block in selected_blocks)
    selected_ids = [item["route_handle"] for item in selected_items]

    return {
        "selected_route_ids": selected_ids,
        "selected_route_handles": list(selected_ids),
        "selected_route_blocks": selected_blocks,
        "selected_route_summaries": selected_summaries,
        "selectable_route_ids": selectable_ids,
        "selectable_route_handles": list(selectable_ids),
        "selectable_route_summaries": selectable_summaries,
        "removed_missing_ids": removed_missing_ids,
        "removed_deleted_ids": removed_deleted_ids,
        "removed_non_separator_ids": removed_non_separator_ids,
        "removed_duplicate_ids": removed_duplicate_ids,
        "diagnostics": diagnostics,
        "selected_route_count": len(selected_ids),
        "selected_line_count": selected_line_count,
        "selected_active_line_count": selected_active_line_count,
        "selected_main_line_count": selected_main_line_count,
        "selected_workbench_count": selected_workbench_count,
        "selected_deleted_member_count": selected_deleted_member_count,
        "selected_candidate_count": selected_candidate_count,
        "selected_gallery_variant_count": selected_gallery_variant_count,
        "selected_route_labels": [item["label"] for item in selected_summaries],
    }


def resolve_selected_routes(project_or_lines: Any, selected_route_ids: Any) -> dict[str, Any]:
    """Compatibility-named resolver for the session-only Selected Routes set."""

    return sanitize_selected_route_ids(project_or_lines, selected_route_ids)


def get_selectable_route_handles(project_or_lines: Any) -> list[str]:
    return list(sanitize_selected_route_ids(project_or_lines, [])[
        "selectable_route_ids"
    ])


def get_selectable_route_summaries(project_or_lines: Any) -> list[dict[str, Any]]:
    return list(sanitize_selected_route_ids(project_or_lines, [])[
        "selectable_route_summaries"
    ])


def get_selected_route_blocks(project_or_lines: Any, selected_route_ids: Any) -> list[RouteBlock]:
    return list(sanitize_selected_route_ids(project_or_lines, selected_route_ids)[
        "selected_route_blocks"
    ])


def get_selected_route_summary(project_or_lines: Any, selected_route_ids: Any) -> dict[str, Any]:
    return sanitize_selected_route_ids(project_or_lines, selected_route_ids)


def toggle_selected_route(
    project_or_lines: Any,
    selected_route_ids: Any,
    route_handle: Any,
    selected: bool | None = None,
) -> list[str]:
    state = sanitize_selected_route_ids(project_or_lines, selected_route_ids)
    clean_handle = str(route_handle or "").strip()
    if clean_handle not in state["selectable_route_ids"]:
        return list(state["selected_route_ids"])
    current_ids = set(state["selected_route_ids"])
    should_select = clean_handle not in current_ids if selected is None else bool(selected)
    if should_select:
        current_ids.add(clean_handle)
    else:
        current_ids.discard(clean_handle)
    return [
        route_id
        for route_id in state["selectable_route_ids"]
        if route_id in current_ids
    ]


def select_all_routes(project_or_lines: Any) -> list[str]:
    return get_selectable_route_handles(project_or_lines)


def clear_selected_routes(_project_or_lines: Any = None) -> list[str]:
    return []


def invert_selected_routes(project_or_lines: Any, selected_route_ids: Any) -> list[str]:
    state = sanitize_selected_route_ids(project_or_lines, selected_route_ids)
    selected_ids = set(state["selected_route_ids"])
    return [
        route_id
        for route_id in state["selectable_route_ids"]
        if route_id not in selected_ids
    ]


def initialize_selected_route_widget_state(
    widget_state: Any,
    widget_prefix: str,
    route_handle: Any,
    selected_route_ids: Any,
) -> str:
    """Initialize one uncreated Route checkbox from logical selection state."""

    clean_handle = str(route_handle or "").strip()
    widget_key = f"{str(widget_prefix or '')}{clean_handle}"
    if widget_key not in widget_state:
        selected_ids = {
            str(route_id or "").strip()
            for route_id in _selected_route_input_ids(selected_route_ids)
            if str(route_id or "").strip()
        }
        widget_state[widget_key] = clean_handle in selected_ids
    return widget_key


def resolve_selected_route_export_lines(
    project_or_lines: Any,
    selected_route_ids: Any,
) -> dict[str, Any]:
    """Resolve exportable normal Lines for selected Routes in Project order."""

    state = sanitize_selected_route_ids(project_or_lines, selected_route_ids)
    lines, _line_diagnostics = _selected_route_lines(project_or_lines)
    line_id_counts: dict[str, int] = {}
    for line in lines:
        line_id = str(getattr(line, "id", "") or "").strip()
        if line_id:
            line_id_counts[line_id] = line_id_counts.get(line_id, 0) + 1

    selected_member_ids = {
        str(getattr(line, "id", "") or "").strip()
        for block in state["selected_route_blocks"]
        for line in block.active_normal_member_lines
        if str(getattr(line, "id", "") or "").strip()
    }
    duplicate_member_ids = {
        line_id
        for line_id in selected_member_ids
        if line_id_counts.get(line_id, 0) > 1
    }
    diagnostics = list(state["diagnostics"])
    for field_name, label in (
        ("removed_missing_ids", "missing Route id"),
        ("removed_deleted_ids", "deleted Route id"),
        ("removed_non_separator_ids", "non-separator selected id"),
        ("removed_duplicate_ids", "duplicate or ambiguous Route id"),
    ):
        diagnostics.extend(
            f"ignored {label}: {value or '(empty)'}"
            for value in state.get(field_name, [])
        )
    diagnostics.extend(
        f"ambiguous selected Route line id: {line_id}"
        for line_id in sorted(duplicate_member_ids)
    )

    target_lines = [
        line
        for line in lines
        if (
            str(getattr(line, "id", "") or "").strip() in selected_member_ids
            and str(getattr(line, "id", "") or "").strip() not in duplicate_member_ids
            and not getattr(line, "deleted", False)
            and not _is_separator(line)
            and not _is_workbench(line)
        )
    ]
    route_summaries = [
        {key: value for key, value in summary.items() if key != "block"}
        for summary in state["selected_route_summaries"]
    ]
    reason = ""
    if not state["selected_route_ids"]:
        reason = "no selected Routes"
    elif not target_lines:
        reason = "selected Routes have no exportable Lines"

    return {
        "scope": "selected_routes",
        "target_lines": target_lines,
        "target_line_ids": [
            str(getattr(line, "id", "") or "").strip()
            for line in target_lines
            if str(getattr(line, "id", "") or "").strip()
        ],
        "resolved_route_handles": list(state["selected_route_ids"]),
        "resolved_route_labels": list(state["selected_route_labels"]),
        "selected_route_count": state["selected_route_count"],
        "selected_main_line_count": state["selected_main_line_count"],
        "selected_workbench_count": state["selected_workbench_count"],
        "selected_deleted_member_count": state["selected_deleted_member_count"],
        "selected_candidate_count": state["selected_candidate_count"],
        "selected_gallery_variant_count": state["selected_gallery_variant_count"],
        "route_summaries": route_summaries,
        "diagnostics": diagnostics,
        "warnings": diagnostics,
        "valid": bool(state["selected_route_ids"]) and bool(target_lines),
        "reason": reason,
    }


def _duplicate_route_result(
    *,
    duplicated: bool,
    source_route_handle: str,
    new_route_handle: str = "",
    reason: str = "",
    diagnostics: Iterable[str] = (),
    source_line_ids: Iterable[str] = (),
    new_line_ids: Iterable[str] = (),
    line_id_map: dict[str, str] | None = None,
    duplicate_lines: Iterable[Any] = (),
    inserted_start: int | None = None,
    inserted_end: int | None = None,
    cleared_candidate_line_ids: Iterable[str] = (),
    cleared_variant_line_ids: Iterable[str] = (),
    normalized_selected_image_line_ids: Iterable[str] = (),
) -> dict[str, Any]:
    source_ids = [line_id for line_id in source_line_ids if line_id]
    new_ids = [line_id for line_id in new_line_ids if line_id]
    return {
        "duplicated": duplicated,
        "success": duplicated,
        "source_route_handle": source_route_handle,
        "new_route_handle": new_route_handle,
        "source_line_ids": source_ids,
        "new_line_ids": new_ids,
        "line_id_map": dict(line_id_map or {}),
        "duplicate_lines": list(duplicate_lines),
        "inserted_start": inserted_start,
        "inserted_end": inserted_end,
        "duplicated_line_count": len(new_ids),
        "cleared_candidate_line_ids": [line_id for line_id in cleared_candidate_line_ids if line_id],
        "cleared_variant_line_ids": [line_id for line_id in cleared_variant_line_ids if line_id],
        "normalized_selected_image_line_ids": [
            line_id for line_id in normalized_selected_image_line_ids if line_id
        ],
        "reason": reason,
        "diagnostics": [diagnostic for diagnostic in diagnostics if diagnostic],
    }


def _duplicate_current_image_path(line: Any) -> Any:
    """Resolve a baseline path without checking the filesystem."""
    return _duplicate_current_image_reference(line).get("path")


def _duplicate_current_image_reference(line: Any) -> dict[str, Any]:
    for attribute in ("selected_candidate_path", "generated_image_path", "image_path"):
        value = getattr(line, attribute, None)
        if value is not None and str(value).strip():
            return {"field": attribute, "path": value}
    return {"field": "", "path": None}


def _duplicate_paths_match(path_a: Any, path_b: Any) -> bool:
    if path_a is None or path_b is None:
        return False
    left = str(path_a).strip().replace("\\", "/")
    right = str(path_b).strip().replace("\\", "/")
    return bool(left and right and left.casefold() == right.casefold())


def _duplicate_candidate_record(line: Any, candidate_path: Any) -> dict[str, Any] | None:
    candidates = getattr(line, "generated_candidates", None)
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        record_path = candidate.get("path") or candidate.get("image_path")
        if _duplicate_paths_match(record_path, candidate_path):
            return candidate
    return None


def _duplicate_source_info_for_existing_path(source_info: Any, image_path: Any) -> dict[str, Any]:
    normalized = copy.deepcopy(source_info) if isinstance(source_info, dict) else {}
    source_image_path = normalized.get("source_image_path")
    if source_image_path and image_path and not _duplicate_paths_match(source_image_path, image_path):
        normalized["source_image_path"] = str(image_path)
    return normalized


def _duplicate_route_timestamp(value: Any = None) -> str:
    return _route_removal_timestamp(value)


def _candidate_derived_source_info(source_info: Any) -> bool:
    if not isinstance(source_info, dict):
        return False
    source_kind = str(source_info.get("source_kind") or source_info.get("source") or "").lower()
    if "candidate" in source_kind or "variant" in source_kind:
        return True
    return any(
        key in source_info
        for key in (
            "candidate_path",
            "candidate_image_path",
            "candidate_id",
            "variant_id",
            "variant_path",
        )
    )


def _duplicate_line_id_factory_call(
    id_factory: Callable[..., Any],
    source_id: str,
    role: str,
) -> str:
    try:
        generated = id_factory(source_id, role)
    except TypeError:
        generated = id_factory(source_id)
    return str(generated or "").strip()


def _prepare_route_baseline_duplicate(
    project: Any,
    separator_id: str,
    *,
    label: str | None = None,
    id_factory: Callable[..., Any] | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Validate and build a Route duplicate without mutating ``project``."""

    source_handle = str(separator_id or "").strip()
    block = resolve_route_block(project, source_handle)
    if block.separator is None:
        return _duplicate_route_result(
            duplicated=False,
            source_route_handle=source_handle,
            reason="separator not found",
        )
    if not block.resolved or not block.is_valid:
        return _duplicate_route_result(
            duplicated=False,
            source_route_handle=source_handle,
            reason="separator is deleted" if block.deleted else "target is not separator",
        )

    records = _route_removal_records(project)
    if records is None:
        return _duplicate_route_result(
            duplicated=False,
            source_route_handle=source_handle,
            reason="malformed removal record",
            diagnostics=["project_metadata.route_removals is not a list"],
        )
    duplicate_removal_ids = _duplicate_route_removal_ids(records)
    if duplicate_removal_ids:
        return _duplicate_route_result(
            duplicated=False,
            source_route_handle=source_handle,
            reason="malformed removal record",
            diagnostics=[
                "duplicate Route removal id: " + removal_id
                for removal_id in sorted(duplicate_removal_ids)
            ],
        )
    if source_handle in _ambiguous_active_route_handles(records):
        return _duplicate_route_result(
            duplicated=False,
            source_route_handle=source_handle,
            reason="ambiguous active Route handle",
            diagnostics=[f"ambiguous active Route handle: {source_handle}"],
        )
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("route_handle") or "").strip() != source_handle:
            continue
        if str(record.get("status") or "").strip() == "active":
            if not _valid_route_removal_record(record, active_only=True):
                return _duplicate_route_result(
                    duplicated=False,
                    source_route_handle=source_handle,
                    reason="malformed removal record",
                    diagnostics=_route_removal_record_diagnostics(record),
                )
            return _duplicate_route_result(
                duplicated=False,
                source_route_handle=source_handle,
                reason="active removal record exists",
            )

    source_lines = list(block.block_lines)
    source_line_ids = [str(getattr(line, "id", "") or "").strip() for line in source_lines]
    if any(not line_id for line_id in source_line_ids):
        return _duplicate_route_result(
            duplicated=False,
            source_route_handle=source_handle,
            reason="malformed source Route",
            diagnostics=["Route contains a line with an empty id"],
        )
    if len(set(source_line_ids)) != len(source_line_ids):
        return _duplicate_route_result(
            duplicated=False,
            source_route_handle=source_handle,
            reason="duplicate ID collision",
            diagnostics=["source Route contains duplicate line ids"],
        )

    if label is None:
        new_label = f"{block.separator_label} Baseline".strip()
    elif isinstance(label, str):
        new_label = label.strip()
    else:
        new_label = ""
    if not new_label:
        return _duplicate_route_result(
            duplicated=False,
            source_route_handle=source_handle,
            reason="invalid label",
        )

    source_ids_in_block = set(source_line_ids)
    for line in source_lines:
        if not _is_workbench(line):
            continue
        source_line_id = str(getattr(line, "workbench_source_line_id", "") or "").strip()
        if source_line_id not in source_ids_in_block:
            return _duplicate_route_result(
                duplicated=False,
                source_route_handle=source_handle,
                reason="malformed Workbench source",
                diagnostics=[
                    f"Workbench line {getattr(line, 'id', '')} has an invalid source line id"
                ],
            )

    existing_ids = {
        str(getattr(line, "id", "") or "").strip()
        for line in _prompt_lines(project)
        if str(getattr(line, "id", "") or "").strip()
    }
    factory = id_factory or (lambda _source_id, role: f"{role}_{uuid.uuid4().hex}")
    line_id_map: dict[str, str] = {}
    used_new_ids: set[str] = set()
    for line in source_lines:
        source_line_id = str(getattr(line, "id", "") or "").strip()
        role = "separator" if _is_separator(line) else "workbench" if _is_workbench(line) else "line"
        try:
            new_id = _duplicate_line_id_factory_call(factory, source_line_id, role)
        except Exception as exc:
            return _duplicate_route_result(
                duplicated=False,
                source_route_handle=source_handle,
                reason="id factory failed",
                diagnostics=[str(exc)],
            )
        if not new_id or new_id in existing_ids or new_id in used_new_ids:
            return _duplicate_route_result(
                duplicated=False,
                source_route_handle=source_handle,
                reason="duplicate ID collision",
                diagnostics=[f"new line id collision: {new_id or '<empty>'}"],
            )
        line_id_map[source_line_id] = new_id
        used_new_ids.add(new_id)

    timestamp = _duplicate_route_timestamp(now)
    duplicate_lines = []
    cleared_candidate_line_ids = []
    cleared_variant_line_ids = []
    normalized_selected_image_line_ids = []
    duplicate_diagnostics = []
    known_reference_fields = (
        "parent_line_id",
        "source_line_id",
        "origin_line_id",
        "selected_route_separator_id",
    )
    experimental_fields = (
        "candidate_selection_state",
        "candidate_comparison_state",
        "candidate_preview_state",
        "candidate_apply_state",
        "selected_candidate_index",
        "candidate_index",
        "selected_gallery_variant_id",
        "gallery_variant_selection",
        "gallery_variant_preview",
        "gallery_variant_apply_result",
        "workbench_preview",
        "workbench_apply_result",
        "generation_state",
        "generation_preview",
    )
    try:
        for source_line in source_lines:
            duplicate_line = copy.deepcopy(source_line)
            source_line_id = str(getattr(source_line, "id", "") or "").strip()
            duplicate_line.id = line_id_map[source_line_id]
            duplicate_line.duplicated_from = source_line_id
            duplicate_line.edited = True
            image_reference = _duplicate_current_image_reference(source_line)
            image_field = image_reference["field"]
            image_path = image_reference["path"]
            duplicate_line.image_path = image_path
            duplicate_line.selected_candidate_path = None
            duplicate_line.generated_image_path = None
            if image_path is not None:
                normalized_selected_image_line_ids.append(source_line_id)

            duplicate_line.generated_candidates = []
            duplicate_line.gallery_variants = []
            if getattr(source_line, "generated_candidates", None):
                cleared_candidate_line_ids.append(source_line_id)
            if getattr(source_line, "gallery_variants", None):
                cleared_variant_line_ids.append(source_line_id)

            source_info = getattr(source_line, "source_generation_info", {})
            selected_candidate = None
            if image_field == "selected_candidate_path":
                selected_candidate = _duplicate_candidate_record(source_line, image_path)
                candidate_metadata = selected_candidate if selected_candidate is not None else {}
                duplicate_line.source_generation_info = build_source_generation_info_from_candidate(
                    source_line,
                    image_path,
                    candidate_metadata,
                )
                if selected_candidate is None:
                    duplicate_diagnostics.append(
                        f"{source_line_id}: selected Candidate record not found"
                    )
            elif _is_workbench(source_line):
                duplicate_line.source_generation_info = {}
            elif _candidate_derived_source_info(source_info) and image_path:
                duplicate_line.source_generation_info = _duplicate_source_info_for_existing_path(
                    source_info,
                    image_path,
                )
            elif isinstance(source_info, dict):
                duplicate_line.source_generation_info = _duplicate_source_info_for_existing_path(
                    source_info,
                    image_path,
                )
            else:
                duplicate_line.source_generation_info = {}

            lineage = getattr(source_line, "lineage_info", {})
            duplicate_line.lineage_info = copy.deepcopy(lineage) if isinstance(lineage, dict) else {}
            duplicate_line.lineage_info.update({
                "operation": "duplicate_route_as_baseline",
                "source_route_handle": source_handle,
                "new_route_handle": line_id_map[source_handle],
                "source_line_id": source_line_id,
                "duplicated_at": timestamp,
            })
            if image_field == "selected_candidate_path" and image_path:
                duplicate_line.lineage_info["adopted_candidate_path"] = str(image_path)
            for field_name in known_reference_fields:
                if not hasattr(duplicate_line, field_name):
                    continue
                reference = getattr(duplicate_line, field_name, None)
                reference_id = str(reference or "").strip()
                if reference_id in line_id_map:
                    setattr(duplicate_line, field_name, line_id_map[reference_id])
            if _is_workbench(source_line):
                duplicate_line.workbench_source_line_id = line_id_map[
                    str(getattr(source_line, "workbench_source_line_id", "") or "").strip()
                ]
                duplicate_line.workbench_status = None
            for field_name in experimental_fields:
                if hasattr(duplicate_line, field_name):
                    setattr(duplicate_line, field_name, None)
            if _is_separator(source_line):
                duplicate_line.separator_label = new_label
                duplicate_line.original_file_name = new_label
                duplicate_line.original_text = new_label
                duplicate_line.current_text = new_label
            duplicate_lines.append(duplicate_line)
    except Exception as exc:
        return _duplicate_route_result(
            duplicated=False,
            source_route_handle=source_handle,
            reason="unsupported Line state",
            diagnostics=[str(exc)],
        )

    return _duplicate_route_result(
        duplicated=True,
        source_route_handle=source_handle,
        new_route_handle=line_id_map[source_handle],
        source_line_ids=source_line_ids,
        new_line_ids=[line_id_map[line_id] for line_id in source_line_ids],
        line_id_map=line_id_map,
        duplicate_lines=duplicate_lines,
        inserted_start=int(block.block_end_index),
        inserted_end=int(block.block_end_index) + len(duplicate_lines),
        cleared_candidate_line_ids=cleared_candidate_line_ids,
        cleared_variant_line_ids=cleared_variant_line_ids,
        normalized_selected_image_line_ids=normalized_selected_image_line_ids,
        diagnostics=duplicate_diagnostics,
    )


def duplicate_route_as_baseline(
    project: Any,
    separator_id: str,
    *,
    label: str | None = None,
    id_factory: Callable[..., Any] | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Duplicate one active Route block in place without copying asset files."""

    prepared = _prepare_route_baseline_duplicate(
        project,
        separator_id,
        label=label,
        id_factory=id_factory,
        now=now,
    )
    if not prepared.get("duplicated"):
        prepared.pop("duplicate_lines", None)
        return prepared

    lines = _mutable_prompt_lines(project)
    if lines is None:
        prepared.pop("duplicate_lines", None)
        prepared["duplicated"] = False
        prepared["success"] = False
        prepared["reason"] = "prompt lines are not mutable"
        return prepared

    original_lines = list(lines)
    original_indexes = {
        id(line): getattr(line, "current_index", None) for line in original_lines
    }
    insert_at = int(prepared["inserted_start"])
    duplicate_lines = list(prepared.get("duplicate_lines") or [])
    try:
        lines[insert_at:insert_at] = duplicate_lines
        for index, line in enumerate(lines):
            line.current_index = index
    except Exception as exc:
        lines[:] = original_lines
        for line in original_lines:
            if id(line) in original_indexes:
                line.current_index = original_indexes[id(line)]
        prepared["duplicated"] = False
        prepared["success"] = False
        prepared["reason"] = "Route insertion failed"
        prepared["diagnostics"] = [str(exc)]
        prepared.pop("duplicate_lines", None)
        return prepared

    prepared.pop("duplicate_lines", None)
    return prepared


def move_route_block(
    project_or_lines: Any,
    separator_id: str,
    direction: str,
) -> dict[str, Any]:
    """Move one contiguous separator-owned Route block in place.

    Only the prompt-line list is reordered here. Callers own graph rebuild,
    history, persistence, and UI state restoration after a successful move.
    """

    direction_key = str(direction or "").strip().lower()
    route_handle = str(separator_id or "").strip()
    if direction_key not in {"up", "down"}:
        return _route_move_result(
            moved=False,
            direction=direction_key,
            route_handle=route_handle,
            reason="invalid direction",
        )

    lines = _mutable_prompt_lines(project_or_lines)
    if lines is None:
        return _route_move_result(
            moved=False,
            direction=direction_key,
            route_handle=route_handle,
            reason="prompt lines are not mutable",
        )

    block = resolve_route_block(lines, route_handle)
    if block.separator is None:
        return _route_move_result(
            moved=False,
            direction=direction_key,
            route_handle=route_handle,
            reason="separator not found",
        )
    if not block.resolved or not block.is_valid:
        reason = "separator is deleted" if block.deleted else "target is not separator"
        return _route_move_result(
            moved=False,
            direction=direction_key,
            route_handle=route_handle,
            reason=reason,
        )

    source_start = int(block.block_start_index)
    source_end = int(block.block_end_index)
    previous_handle = str(getattr(block.previous_separator, "id", "") or "")
    next_handle = str(getattr(block.next_separator, "id", "") or "")

    if direction_key == "up":
        if not previous_handle:
            return _route_move_result(
                moved=False,
                direction=direction_key,
                route_handle=route_handle,
                source_start=source_start,
                source_end=source_end,
                previous_route_handle=previous_handle,
                next_route_handle=next_handle,
                reason="already first Route",
                affected_line_ids=(getattr(line, "id", "") for line in block.block_lines),
            )
        previous_block = resolve_route_block(lines, previous_handle)
        if not previous_block.is_valid or previous_block.deleted:
            return _route_move_result(
                moved=False,
                direction=direction_key,
                route_handle=route_handle,
                source_start=source_start,
                source_end=source_end,
                previous_route_handle=previous_handle,
                next_route_handle=next_handle,
                reason="no adjacent Route",
                affected_line_ids=(getattr(line, "id", "") for line in block.block_lines),
            )
        destination_index = int(previous_block.block_start_index)
        previous_start = destination_index
        previous_end = source_start
        source_slice = list(lines[source_start:source_end])
        previous_slice = list(lines[previous_start:previous_end])
        lines[previous_start:source_end] = source_slice + previous_slice
        final_destination_index = destination_index
    else:
        if not next_handle:
            return _route_move_result(
                moved=False,
                direction=direction_key,
                route_handle=route_handle,
                source_start=source_start,
                source_end=source_end,
                previous_route_handle=previous_handle,
                next_route_handle=next_handle,
                reason="already last Route",
                affected_line_ids=(getattr(line, "id", "") for line in block.block_lines),
            )
        next_block = resolve_route_block(lines, next_handle)
        if not next_block.is_valid or next_block.deleted:
            return _route_move_result(
                moved=False,
                direction=direction_key,
                route_handle=route_handle,
                source_start=source_start,
                source_end=source_end,
                previous_route_handle=previous_handle,
                next_route_handle=next_handle,
                reason="no adjacent Route",
                affected_line_ids=(getattr(line, "id", "") for line in block.block_lines),
            )
        next_end = int(next_block.block_end_index)
        source_slice = list(lines[source_start:source_end])
        next_slice = list(lines[source_end:next_end])
        lines[source_start:next_end] = next_slice + source_slice
        final_destination_index = next_end - len(source_slice)

    for index, line in enumerate(lines):
        if hasattr(line, "current_index"):
            line.current_index = index

    return _route_move_result(
        moved=True,
        direction=direction_key,
        route_handle=route_handle,
        source_start=source_start,
        source_end=source_end,
        destination_index=final_destination_index,
        previous_route_handle=previous_handle,
        next_route_handle=next_handle,
        affected_line_ids=(getattr(line, "id", "") for line in block.block_lines),
    )


def move_route_block_up(project_or_lines: Any, separator_id: str) -> dict[str, Any]:
    return move_route_block(project_or_lines, separator_id, "up")


def move_route_block_down(project_or_lines: Any, separator_id: str) -> dict[str, Any]:
    return move_route_block(project_or_lines, separator_id, "down")


def get_route_action_dispatch_updates(
    action: str,
    route_handle: str,
    *,
    is_valid: bool = True,
    is_deleted: bool = False,
) -> dict[str, Any]:
    """Return safe session updates for a Route Action shortcut.

    This helper only describes a dispatch. It never performs preview, apply,
    export, generation, file, or project mutations.
    """

    action_key = str(action or "").strip()
    handle = str(route_handle or "").strip()
    if not handle:
        return {"dispatch": False, "reason": "missing Route handle", "updates": {}}
    if is_deleted:
        return {"dispatch": False, "reason": "deleted separator", "updates": {}}
    if not is_valid:
        return {"dispatch": False, "reason": "invalid Route separator", "updates": {}}
    spec = ROUTE_ACTION_SPECS.get(action_key)
    if not spec:
        return {"dispatch": False, "reason": "unknown Route Action", "updates": {}}

    operation = spec["operation"]
    return {
        "dispatch": True,
        "action": action_key,
        "operation": operation,
        "scope": "selected_route",
        "selected_route_id": handle,
        "route_handle": handle,
        "pending": {
            "operation": operation,
            "route_handle": handle,
        },
        "updates": {
            "gallery_operation_focus": operation,
            "gallery_selected_route_separator_id": handle,
        },
    }


def get_route_action_pending_updates(pending: Any) -> dict[str, Any]:
    """Return the session updates for an early Route Action pending phase.

    The click handler stores only the pending operation and Route handle. The
    caller applies these updates before rendering any operation widgets, which
    keeps Streamlit widget state writes out of the post-widget click phase.
    """

    if not isinstance(pending, dict):
        return {
            "apply": False,
            "reason": "missing Route Action pending dispatch",
            "updates": {},
            "remove": [],
        }

    operation = str(pending.get("operation") or "").strip()
    route_handle = str(pending.get("route_handle") or "").strip()
    if not route_handle:
        return {
            "apply": False,
            "reason": "missing Route handle",
            "updates": {},
            "remove": [],
        }
    if operation not in {spec["operation"] for spec in ROUTE_ACTION_SPECS.values()}:
        return {
            "apply": False,
            "reason": "unknown Route Action operation",
            "updates": {},
            "remove": [],
        }

    updates = {
        "gallery_selected_route_separator_id": route_handle,
        "gallery_route_action_notice": {
            "route_handle": route_handle,
            "route_label": str(pending.get("route_label") or ""),
            "operation": operation,
        },
    }
    remove = []
    active_panel_operations = {
        "generation": "gallery_generation",
        "candidate_adoption": "batch_candidate_adoption",
        "lightweight_fork": "lightweight_fork",
    }
    if operation in active_panel_operations:
        updates.update(
            {
                "gallery_operations_active": active_panel_operations[operation],
            }
        )
        remove.append("gallery_operation_focus")
    else:
        updates["gallery_operation_focus"] = operation
        remove.append("gallery_operations_active")

    operation_state_keys = {
        "generation": (
            "gallery_generation_scope",
            "gallery_generation_selected_route_id",
        ),
        "candidate_adoption": (
            "route_batch_candidate_adoption_preview_scope",
            "route_batch_candidate_adoption_preview_selected_route_id",
        ),
        "final_export": (
            "gallery_final_export_scope",
            "gallery_final_export_selected_route_id",
        ),
        "lightweight_fork": (
            "lightweight_fork_scope",
            "lightweight_fork_selected_route_id",
        ),
    }
    scope_key, route_key = operation_state_keys[operation]
    updates[scope_key] = "selected_route"
    updates[route_key] = route_handle

    return {
        "apply": True,
        "operation": operation,
        "route_handle": route_handle,
        "updates": updates,
        "remove": remove,
    }
