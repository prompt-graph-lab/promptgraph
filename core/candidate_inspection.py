"""Read-only Candidate/Gallery values; mutation and UI remain caller-owned."""

import json
import re
from core.parser import parse_prompt


def _candidate_path(candidate):
    if isinstance(candidate, dict):
        return str(candidate.get("path") or "")
    return str(candidate) if candidate else ""


def _selected_candidate_path(line):
    return getattr(line, "selected_candidate_path", None) or getattr(line, "generated_image_path", None)


def _candidate_prompt_metadata(candidate) -> dict:
    if not isinstance(candidate, dict):
        return {}

    if candidate.get("source") == "manual_import" and candidate.get("candidate_prompt_source") != "imported_image_metadata":
        return {}

    positive_prompt = str(
        candidate.get("prompt_text")
        or candidate.get("positive_prompt")
        or candidate.get("source_prompt")
        or ""
    ).strip()
    negative_prompt = str(
        candidate.get("negative_prompt")
        or candidate.get("source_negative_prompt")
        or candidate.get("negative")
        or ""
    ).strip()
    if not positive_prompt and not negative_prompt:
        return {}
    return {
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
    }


def _looks_like_workflow_json_prompt(text: str) -> bool:
    clean_text = str(text or "").strip()
    if not clean_text or clean_text[0] not in "{[":
        return False
    try:
        parsed = json.loads(clean_text)
    except Exception:
        return False
    return isinstance(parsed, (dict, list))


def _candidate_nested_value(candidate: dict, section_key: str, value_key: str):
    section = candidate.get(section_key)
    if isinstance(section, dict):
        return section.get(value_key)
    return None


def get_candidate_prompt_text(candidate) -> str:
    if not isinstance(candidate, dict):
        return ""
    top_level_keys = (
        "source_prompt",
        "prompt_text",
        "prompt",
        "positive_prompt",
        "positive",
    )
    nested_sections = (
        "source_generation_info",
        "metadata",
        "source_raw_metadata",
    )
    nested_keys = (
        "source_prompt",
        "prompt_text",
        "prompt",
        "positive_prompt",
        "positive",
    )
    values = [candidate.get(key) for key in top_level_keys]
    values.extend(
        _candidate_nested_value(candidate, section_key, value_key)
        for section_key in nested_sections
        for value_key in nested_keys
    )
    for value in values:
        if not isinstance(value, str):
            continue
        prompt_text = value.strip()
        if prompt_text and not _looks_like_workflow_json_prompt(prompt_text):
            return prompt_text
    return ""


def get_original_prompt_text(line) -> str:
    return str(getattr(line, "original_text", "") or "").strip()


def normalize_prompt_for_revert_compare(text: str) -> list[str]:
    text = str(text or "")
    if not text.strip():
        return []
    try:
        return [str(token).strip() for token in parse_prompt(text) if str(token).strip()]
    except Exception:
        return [part.strip() for part in re.split(r"\s*,\s*", text.strip()) if part.strip()]


def is_line_prompt_changed_from_original(line) -> bool:
    original_text = get_original_prompt_text(line)
    if not original_text:
        return False
    current_text = str(getattr(line, "current_text", "") or "").strip()
    return normalize_prompt_for_revert_compare(current_text) != normalize_prompt_for_revert_compare(original_text)


def _prompt_original_status_label(line) -> str:
    if not get_original_prompt_text(line):
        return "Prompt: no original"
    if is_line_prompt_changed_from_original(line):
        return "Prompt: edited"
    return "Prompt: original"


def _candidate_metadata_caption(candidate):
    parts = []
    created_at = candidate.get("created_at") if isinstance(candidate, dict) else None
    source = candidate.get("source") if isinstance(candidate, dict) else None
    run_index = candidate.get("run_index") if isinstance(candidate, dict) else None
    origin_line_index = candidate.get("origin_line_index") if isinstance(candidate, dict) else None
    if created_at:
        parts.append(str(created_at))
    if source:
        parts.append(str(source))
    if run_index is not None:
        parts.append(f"run {run_index}")
    if origin_line_index is not None:
        parts.append(f"line {origin_line_index}")
    return " / ".join(parts)


def _candidate_is_pinned(candidate):
    return bool(candidate.get("pinned")) if isinstance(candidate, dict) else False


def _candidate_is_trashed(candidate):
    return bool(candidate.get("trashed")) if isinstance(candidate, dict) else False


def _active_candidates(candidates):
    return [candidate for candidate in candidates or [] if not _candidate_is_trashed(candidate)]


def _trashed_candidates(candidates):
    return [candidate for candidate in candidates or [] if _candidate_is_trashed(candidate)]


def _sort_candidates_for_display(candidates):
    return [
        candidate
        for _idx, candidate in sorted(
            enumerate(candidates),
            key=lambda item: (not _candidate_is_pinned(item[1]), item[0]),
        )
    ]
