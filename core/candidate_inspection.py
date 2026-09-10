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
