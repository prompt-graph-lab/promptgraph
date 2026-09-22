"""Normalize runtime Candidate records without assigning state or resolving files.

Persistence normalization in core.io deliberately retains different path semantics.
"""

import os

from core.candidate_inspection import _candidate_path


def _normalize_candidate_path(path):
    if not path:
        return ""
    path = str(path)
    if os.path.isabs(path):
        return os.path.abspath(path)
    return path.replace("\\", "/")


def _normalize_candidate_record(candidate):
    if isinstance(candidate, dict):
        path = _candidate_path(candidate)
        if not path:
            return None
        record = dict(candidate)
        record["path"] = _normalize_candidate_path(path)
        return record

    path = _candidate_path(candidate)
    if not path:
        return None
    return {"path": _normalize_candidate_path(path)}


def _normalize_candidate_records(candidates):
    normalized = []
    seen = set()
    for candidate in candidates or []:
        record = _normalize_candidate_record(candidate)
        if not record:
            continue
        path = record["path"]
        if path not in seen:
            normalized.append(record)
            seen.add(path)
    return normalized
