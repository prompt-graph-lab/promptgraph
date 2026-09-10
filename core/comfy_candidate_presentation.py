"""Read-only labels and role-based default choices for workflow text-node candidates."""


def _comfy_candidate_label(candidate: dict) -> str:
    preview = candidate.get("text_preview") or ""
    preview_text = f" - {preview}" if preview else ""
    return f"{candidate['node_id']} - {candidate['class_type']} - {candidate['role']}{preview_text}"


def _candidate_default_index(candidates: list[dict], role: str, fallback_index: int = 0) -> int:
    for index, candidate in enumerate(candidates):
        if candidate.get("role") == role:
            return index
    return fallback_index if candidates else 0
