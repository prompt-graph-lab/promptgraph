import re
from collections import Counter, defaultdict
from typing import Callable, Iterable


A1111_NEGATIVE_MARKER = "Negative prompt:"
A1111_GENERATION_STOP_MARKERS = (
    "Steps:",
    "Sampler:",
    "Schedule type:",
    "CFG scale:",
    "Seed:",
    "Size:",
    "Model hash:",
    "Model:",
    "Denoising strength:",
    "Clip skip:",
    "Hires",
    "Version:",
)


def _as_text(value) -> str:
    return value if isinstance(value, str) else ""


def _line_label(line) -> str:
    name = str(getattr(line, "original_file_name", "") or "").strip()
    line_id = str(getattr(line, "id", "") or "").strip()
    if name and line_id:
        return f"{name} ({line_id})"
    return name or line_id or "Prompt line"


def _metadata_value(metadata: dict, *keys: str):
    if not isinstance(metadata, dict):
        return None
    lowered = {str(key).lower(): value for key, value in metadata.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None:
            return value
    return None


def _metadata_text_candidates(metadata: dict) -> list[str]:
    if not isinstance(metadata, dict):
        return []

    candidates = []
    for key in ("raw_parameters", "parameters", "prompt", "description", "caption"):
        value = _metadata_value(metadata, key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)

    raw_metadata = metadata.get("raw_metadata")
    if isinstance(raw_metadata, dict):
        for key in ("parameters", "prompt", "description", "caption", "UserComment", "ImageDescription"):
            value = _metadata_value(raw_metadata, key)
            if isinstance(value, str) and value.strip():
                candidates.append(value)
    return candidates


def extract_negative_prompt_from_parameters(text: str) -> str:
    text = _as_text(text).replace("\r\n", "\n").replace("\r", "\n")
    marker_index = text.find(A1111_NEGATIVE_MARKER)
    if marker_index < 0:
        return ""

    remainder = text[marker_index + len(A1111_NEGATIVE_MARKER):]
    stop_pattern = re.compile(
        r"(?:^|\n|,\s*)("
        + "|".join(re.escape(marker) for marker in A1111_GENERATION_STOP_MARKERS)
        + r")",
        re.IGNORECASE,
    )
    match = stop_pattern.search(remainder)
    if match:
        remainder = remainder[:match.start()]
    return remainder.strip()


def get_metadata_negative_prompt(metadata: dict | None = None) -> str:
    if isinstance(metadata, dict):
        explicit_negative = _metadata_value(metadata, "negative_prompt", "negative")
        if isinstance(explicit_negative, str) and explicit_negative.strip():
            return explicit_negative.strip()

        for candidate in _metadata_text_candidates(metadata):
            extracted = extract_negative_prompt_from_parameters(candidate)
            if extracted:
                return extracted

    return ""


def get_line_negative_prompt(line, metadata: dict | None = None) -> str:
    line_negative = _as_text(getattr(line, "negative_prompt", "")).strip()
    if line_negative:
        return line_negative
    return get_metadata_negative_prompt(metadata)


def split_negative_tokens(text: str) -> list[str]:
    return [token.strip() for token in _as_text(text).split(",") if token.strip()]


def _token_key(token: str) -> str:
    return re.sub(r"\s+", " ", str(token or "").strip()).casefold()


def _short_preview(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", _as_text(text)).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def analyze_negative_prompts(
    lines: Iterable,
    metadata_lookup: Callable | None = None,
    near_common_threshold: float = 0.8,
) -> dict:
    lines = list(lines or [])
    per_line = []
    variant_lines = defaultdict(list)
    token_counts = Counter()
    token_display = {}

    for line in lines:
        metadata = None
        if metadata_lookup is not None:
            try:
                metadata = metadata_lookup(line)
            except Exception:
                metadata = None

        negative_prompt = get_line_negative_prompt(line, metadata)
        tokens = split_negative_tokens(negative_prompt)
        token_keys = []
        for token in tokens:
            key = _token_key(token)
            if not key:
                continue
            if key not in token_keys:
                token_keys.append(key)
            token_display.setdefault(key, token)

        if negative_prompt:
            variant_lines[negative_prompt].append(_line_label(line))
            token_counts.update(set(token_keys))

        per_line.append({
            "line_id": str(getattr(line, "id", "") or ""),
            "line_label": _line_label(line),
            "negative_prompt": negative_prompt,
            "negative_prompt_length": len(negative_prompt),
            "token_keys": token_keys,
            "tokens": tokens,
        })

    lines_with_negative = sum(1 for row in per_line if row["negative_prompt"])
    lines_without_negative = len(per_line) - lines_with_negative
    variants = []
    for prompt_text, labels in variant_lines.items():
        count = len(labels)
        variants.append({
            "negative_prompt": prompt_text,
            "preview": _short_preview(prompt_text),
            "count": count,
            "coverage": count / lines_with_negative if lines_with_negative else 0.0,
            "line_labels": labels,
        })
    variants.sort(key=lambda item: (-item["count"], item["preview"].casefold()))

    variant_id_by_prompt = {
        variant["negative_prompt"]: f"V{index + 1}"
        for index, variant in enumerate(variants)
    }

    common_token_keys = {
        key for key, count in token_counts.items()
        if lines_with_negative and count == lines_with_negative
    }
    near_common_token_keys = {
        key for key, count in token_counts.items()
        if lines_with_negative and count / lines_with_negative >= near_common_threshold
    }

    token_rows = [
        {
            "token": token_display.get(key, key),
            "line_count": count,
            "coverage": count / lines_with_negative if lines_with_negative else 0.0,
            "kind": "common" if key in common_token_keys else "near-common",
            "key": key,
        }
        for key, count in token_counts.items()
        if key in near_common_token_keys
    ]
    token_rows.sort(key=lambda item: (-item["line_count"], item["token"].casefold()))

    for row in per_line:
        row["variant_id"] = variant_id_by_prompt.get(row["negative_prompt"], "")
        row["line_specific_tokens"] = [
            token_display.get(key, key)
            for key in row["token_keys"]
            if key not in common_token_keys
        ]

    most_common = variants[0] if variants else {}
    return {
        "total_lines": len(per_line),
        "lines_with_negative": lines_with_negative,
        "lines_without_negative": lines_without_negative,
        "unique_negative_count": len(variants),
        "most_common_negative": most_common.get("negative_prompt", ""),
        "most_common_count": most_common.get("count", 0),
        "most_common_ratio": most_common.get("coverage", 0.0),
        "all_identical": bool(lines_with_negative and len(variants) == 1),
        "common_tokens": [row for row in token_rows if row["kind"] == "common"],
        "near_common_tokens": [row for row in token_rows if row["kind"] == "near-common"],
        "token_rows": token_rows,
        "variants": variants,
        "per_line": per_line,
    }


def build_global_negative_delta_preview(analysis: dict) -> dict:
    lines_with_negative = int((analysis or {}).get("lines_with_negative") or 0)
    preview = {
        "candidate_type": "no safe candidate",
        "candidate_text": "",
        "candidate_tokens": [],
        "candidate_token_keys": [],
        "lines_with_negative": lines_with_negative,
        "delta_line_count": 0,
        "delta_rows": [],
    }
    if not lines_with_negative:
        return preview

    per_line = [
        row for row in (analysis or {}).get("per_line", [])
        if isinstance(row, dict) and row.get("negative_prompt")
    ]
    if not per_line:
        return preview

    candidate_keys = []
    candidate_tokens = []
    if (analysis or {}).get("all_identical"):
        first_line = per_line[0]
        candidate_keys = list(first_line.get("token_keys") or [])
        candidate_tokens = list(first_line.get("tokens") or [])
        preview["candidate_type"] = "exact shared prompt"
        preview["candidate_text"] = str(
            (analysis or {}).get("most_common_negative")
            or first_line.get("negative_prompt")
            or ""
        ).strip()
    else:
        common_keys = {
            str(row.get("key") or "")
            for row in (analysis or {}).get("common_tokens", [])
            if row.get("key")
        }
        for line_row in per_line:
            for token, key in zip(line_row.get("tokens") or [], line_row.get("token_keys") or []):
                if key in common_keys and key not in candidate_keys:
                    candidate_keys.append(key)
                    candidate_tokens.append(token)
            if len(candidate_keys) == len(common_keys):
                break
        if candidate_tokens:
            preview["candidate_type"] = "all-line common tokens"
            preview["candidate_text"] = ", ".join(candidate_tokens)

    candidate_key_set = set(candidate_keys)
    delta_rows = []
    for line_row in per_line:
        delta_tokens = [
            token
            for token, key in zip(line_row.get("tokens") or [], line_row.get("token_keys") or [])
            if key not in candidate_key_set
        ]
        delta_rows.append({
            "line_label": line_row.get("line_label", ""),
            "line_id": line_row.get("line_id", ""),
            "variant_id": line_row.get("variant_id", ""),
            "delta_tokens": delta_tokens,
            "delta_text": ", ".join(delta_tokens),
            "negative_prompt_length": line_row.get("negative_prompt_length", 0),
        })

    preview["candidate_tokens"] = candidate_tokens
    preview["candidate_token_keys"] = candidate_keys
    preview["delta_rows"] = delta_rows
    preview["delta_line_count"] = sum(1 for row in delta_rows if row["delta_tokens"])
    return preview
