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
