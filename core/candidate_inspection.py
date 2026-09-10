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
