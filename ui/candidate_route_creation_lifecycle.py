"""Application-side apply lifecycle for Candidate Route Creation.

The owner rechecks the reviewed plan, synchronizes target Candidates, snapshots
history, and materializes Routes. Shared graph, focus, and save publication
remains with the app after a successful apply.
"""

import copy
import json
import os
import uuid
from datetime import datetime, timezone

from core.candidate_inspection import _candidate_route_candidate_seed, _candidate_route_candidate_workflow
from core.gallery_variant_promotion import normalize_candidate_line_for_main_sequence
from core.io import build_lineage_info_from_candidate, build_source_generation_info_from_candidate
from core.parser import parse_prompt
from core.project import PromptLine


def _build_candidate_route_line(
    source_line, candidate, candidate_path: str, candidate_index: int,
    route_id: str, parent_route_id: str, created_at: str, *,
    apply_candidate_prompt_to_line,
):
    candidate_metadata = dict(candidate) if isinstance(candidate, dict) else {}
    new_line = copy.deepcopy(source_line)
    new_line.id = f"line_{uuid.uuid4().hex[:8]}"
    new_line.original_file_name = os.path.basename(str(candidate_path)) or source_line.original_file_name
    new_line.original_text = source_line.current_text
    new_line.current_text = source_line.current_text
    new_line.tokens = parse_prompt(source_line.current_text)
    new_line.negative_prompt = getattr(source_line, "negative_prompt", "") or ""
    new_line.duplicated_from = source_line.id
    new_line.edited = True
    new_line.deleted = False
    new_line.line_type = None
    new_line.separator_label = None
    new_line.separator_color = None
    new_line.image_path = candidate_path
    new_line.generated_image_path = None
    new_line.selected_candidate_path = None
    new_line.generated_candidates = []
    new_line.gallery_variants = []
    normalize_candidate_line_for_main_sequence(new_line)
    apply_candidate_prompt_to_line(new_line, candidate_metadata)
    new_line.source_generation_info = build_source_generation_info_from_candidate(
        source_line,
        candidate_path,
        candidate_metadata,
    )
    lineage_info = build_lineage_info_from_candidate(
        source_line,
        candidate_path,
        candidate_metadata,
    )
    lineage_info.update({
        "source": "candidate_route_creation",
        "lineage_kind": "candidate_route_creation",
        "parent_line_id": str(getattr(source_line, "id", "") or ""),
        "parent_line_index": getattr(source_line, "current_index", None),
        "parent_route_id": parent_route_id,
        "candidate_path": candidate_path,
        "candidate_image_path": candidate_path,
        "candidate_index": candidate_index,
        "candidate_seed": _candidate_route_candidate_seed(candidate),
        "candidate_workflow": _candidate_route_candidate_workflow(candidate),
        "created_route_id": route_id,
        "created_at": created_at,
    })
    new_line.lineage_info = lineage_info
    return new_line


def apply_candidate_route_creation_plan(
    project, scope: str, selected_line_ids=None, *, preview=None,
    preview_candidate_route_creation, get_line_generated_candidates,
    push_history, apply_candidate_prompt_to_line, reindex_project_lines,
) -> dict:
    stale = {"applied": False, "stale_preview": True,
             "error": "Previewが古くなりました。Fresh Previewを再実行してください。"}
    if not isinstance(preview, dict) or not preview.get("apply_plan") or not preview.get("fingerprint"):
        return stale
    # This read-only recomputation is the final gate before history or any Project mutation.
    current = preview_candidate_route_creation(project, scope, selected_line_ids, example_limit=0)
    if (preview["fingerprint"] != current["fingerprint"]
            or preview["apply_plan"] != current["apply_plan"]):
        return stale

    stored_plan = json.loads(preview["apply_plan"])
    route_plans = stored_plan["routes"]
    skipped_count = preview["skip_count"]
    missing_count = preview["missing_count"]
    duplicate_count = preview["duplicate_count"]
    no_candidate_count = preview["no_candidate_count"]
    if not route_plans:
        return {
            "applied": False,
            "route_count": 0,
            "line_count": 0,
            "skipped_count": skipped_count,
            "missing_count": missing_count,
            "duplicate_count": duplicate_count,
            "no_candidate_count": no_candidate_count,
            "first_separator_id": "",
        }

    # Legacy Apply merged and synchronized every target before its undo snapshot.
    # Do this only after the final stale gate; the returned live records never
    # feed the derived Lines, which use the frozen plan below.
    for target in stored_plan["targets"]:
        source = next(line for line in project.prompt_lines if getattr(line, "id", "") == target["line_id"])
        get_line_generated_candidates(source)
    push_history()
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    created_route_count = 0
    created_line_count = 0
    first_separator_id = ""
    for plan in reversed(route_plans):
        source = plan["source"]
        source_line = PromptLine(
            id=source["id"], original_file_name=source["original_file_name"],
            original_index=source["original_index"], current_index=source["current_index"],
            original_text=source["current_text"], current_text=source["current_text"],
            tokens=[], negative_prompt=source["negative_prompt"], node_path=source["node_path"],
            image_path=source["image_path"], generated_image_path=source["generated_image_path"],
            selected_candidate_path=source["selected_candidate_path"],
        )
        source_line_id = getattr(source_line, "id", "")
        route_id = f"separator_{uuid.uuid4().hex[:8]}"
        route_label = plan["route_label"]
        separator = PromptLine(
            id=route_id,
            original_file_name=route_label,
            original_index=(getattr(source_line, "current_index", 0) or 0) + 1,
            current_index=(getattr(source_line, "current_index", 0) or 0) + 1,
            original_text=route_label,
            current_text=route_label,
            tokens=[],
            negative_prompt="",
            edited=True,
            line_type="separator",
            separator_label=route_label,
            separator_color="gray",
            lineage_info={
                "source": "candidate_route_creation",
                "parent_line_id": source_line_id,
                "parent_line_index": getattr(source_line, "current_index", None),
                "candidate_count": len(plan["candidates"]),
                "created_at": created_at,
            },
        )
        new_lines = [
            separator,
            *[
                _build_candidate_route_line(
                    source_line,
                    candidate["record"],
                    candidate["path"],
                    candidate["index"],
                    route_id,
                    plan["parent_route_id"],
                    created_at,
                    apply_candidate_prompt_to_line=apply_candidate_prompt_to_line,
                )
                for candidate in plan["candidates"]
            ],
        ]
        insert_index = next(
            index for index, line in enumerate(project.prompt_lines)
            if getattr(line, "id", "") == source_line_id
        ) + 1
        project.prompt_lines[insert_index:insert_index] = new_lines
        first_separator_id = first_separator_id or route_id
        created_route_count += 1
        created_line_count += len(new_lines) - 1

    reindex_project_lines(project)
    return {
        "applied": True,
        "route_count": created_route_count,
        "line_count": created_line_count,
        "skipped_count": skipped_count,
        "missing_count": missing_count,
        "duplicate_count": duplicate_count,
        "no_candidate_count": no_candidate_count,
        "first_separator_id": first_separator_id,
    }
