import re
from collections import Counter
from typing import Callable, Iterable


GENERATION_SETTING_FIELDS = (
    ("steps", "Steps", ("steps",)),
    ("sampler", "Sampler", ("sampler",)),
    ("schedule_type", "Schedule type", ("schedule_type", "schedule type", "schedule")),
    ("cfg_scale", "CFG scale", ("cfg_scale", "cfg scale", "cfg")),
    ("seed", "Seed", ("seed",)),
    ("size", "Size", ("size",)),
    ("model", "Model", ("model",)),
    ("model_hash", "Model hash", ("model_hash", "model hash")),
    ("denoising_strength", "Denoising strength", ("denoising_strength", "denoising strength")),
    ("clip_skip", "Clip skip", ("clip_skip", "clip skip")),
    ("hires_upscale", "Hires upscale", ("hires_upscale", "hires upscale")),
    ("hires_steps", "Hires steps", ("hires_steps", "hires steps")),
    ("hires_upscaler", "Hires upscaler", ("hires_upscaler", "hires upscaler")),
    ("vae_module", "VAE / Module", ("vae", "module", "module 1", "hires module 1")),
    ("version", "Version", ("version",)),
)

FIELD_LABELS = {field: label for field, label, _aliases in GENERATION_SETTING_FIELDS}
FIELD_BY_ALIAS = {
    alias.casefold(): field
    for field, _label, aliases in GENERATION_SETTING_FIELDS
    for alias in aliases
}
KNOWN_TEXT_KEYS = sorted(FIELD_BY_ALIAS, key=len, reverse=True)
STRONG_A1111_START_KEYS = (
    "Steps",
    "Sampler",
    "Schedule type",
    "CFG scale",
    "Seed",
    "Size",
)


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    return ""


def _line_label(line) -> str:
    name = str(getattr(line, "original_file_name", "") or "").strip()
    line_id = str(getattr(line, "id", "") or "").strip()
    if name and line_id:
        return f"{name} ({line_id})"
    return name or line_id or "Prompt line"


def _metadata_value(metadata: dict, *keys: str):
    if not isinstance(metadata, dict):
        return None
    lowered = {str(key).casefold(): value for key, value in metadata.items()}
    for key in keys:
        value = lowered.get(str(key).casefold())
        if value is not None:
            return value
    return None


def _field_from_key(key: str) -> str:
    normalized = re.sub(r"[_\s-]+", " ", str(key or "").strip()).casefold()
    return FIELD_BY_ALIAS.get(normalized, "")


def _store_setting(settings: dict, key: str, value):
    field = _field_from_key(key)
    text = _as_text(value)
    if field and text and field not in settings:
        settings[field] = text


def _settings_from_mapping(mapping: dict) -> dict:
    settings = {}
    if not isinstance(mapping, dict):
        return settings
    for key, value in mapping.items():
        _store_setting(settings, str(key), value)
    return settings


def _metadata_text_candidates(metadata: dict) -> list[str]:
    if not isinstance(metadata, dict):
        return []

    candidates = []
    for key in ("parameters", "raw_parameters", "prompt", "description", "caption"):
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


def _settings_text_start(text: str) -> int:
    starts = []
    for key in STRONG_A1111_START_KEYS:
        match = re.search(rf"(?:^|\n|,\s*){re.escape(key)}\s*:", text, re.IGNORECASE)
        if match:
            starts.append(match.start())
    return min(starts) if starts else -1


def _split_setting_chunks(text: str) -> list[str]:
    chunks = []
    current = []
    quote_char = ""
    escape_next = False
    for char in text.replace("\n", ", "):
        if escape_next:
            current.append(char)
            escape_next = False
            continue
        if char == "\\" and quote_char:
            current.append(char)
            escape_next = True
            continue
        if char in ("'", '"'):
            if quote_char == char:
                quote_char = ""
            elif not quote_char:
                quote_char = char
            current.append(char)
            continue
        if char == "," and not quote_char:
            chunk = "".join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = []
            continue
        current.append(char)

    chunk = "".join(current).strip()
    if chunk:
        chunks.append(chunk)
    return chunks


def extract_generation_settings_from_parameters(text: str) -> dict:
    text = _as_text(text).replace("\r\n", "\n").replace("\r", "\n")
    if not text:
        return {}

    start = _settings_text_start(text)
    if start >= 0:
        text = text[start:]

    settings = {}
    key_pattern = "|".join(re.escape(key) for key in KNOWN_TEXT_KEYS)
    for chunk in _split_setting_chunks(text):
        match = re.match(rf"({key_pattern})\s*:\s*(.*)$", chunk, re.IGNORECASE)
        if not match:
            continue
        key = match.group(1)
        value = match.group(2).strip()
        _store_setting(settings, key, value)
    return settings


def extract_generation_settings_from_metadata(metadata: dict | None = None) -> dict:
    if not isinstance(metadata, dict):
        return {}

    settings = {}
    settings.update(_settings_from_mapping(metadata))
    generation_params = metadata.get("generation_params")
    settings.update({key: value for key, value in _settings_from_mapping(generation_params).items() if key not in settings})

    raw_metadata = metadata.get("raw_metadata")
    if isinstance(raw_metadata, dict):
        for key, value in _settings_from_mapping(raw_metadata).items():
            settings.setdefault(key, value)

    for candidate in _metadata_text_candidates(metadata):
        for key, value in extract_generation_settings_from_parameters(candidate).items():
            settings.setdefault(key, value)
    return settings


def get_line_generation_settings(line, metadata: dict | None = None) -> dict:
    settings = {}
    for attr in ("generation_settings", "generation_params", "metadata"):
        value = getattr(line, attr, None)
        if isinstance(value, dict):
            settings.update({key: val for key, val in _settings_from_mapping(value).items() if key not in settings})

    for field in FIELD_LABELS:
        value = getattr(line, field, None)
        if value is not None:
            settings.setdefault(field, _as_text(value))

    for key, value in extract_generation_settings_from_metadata(metadata).items():
        settings.setdefault(key, value)
    return settings


def analyze_generation_settings(
    lines: Iterable,
    metadata_lookup: Callable | None = None,
    mostly_constant_threshold: float = 0.8,
) -> dict:
    lines = list(lines or [])
    per_line = []
    values_by_field = {field: [] for field in FIELD_LABELS}

    for line in lines:
        metadata = None
        if metadata_lookup is not None:
            try:
                metadata = metadata_lookup(line)
            except Exception:
                metadata = None
        settings = get_line_generation_settings(line, metadata)
        per_line.append({
            "line_id": str(getattr(line, "id", "") or ""),
            "line_label": _line_label(line),
            "settings": settings,
            "missing_fields": [field for field in FIELD_LABELS if field not in settings],
        })
        for field, value in settings.items():
            if field not in values_by_field:
                continue
            values_by_field[field].append(value)

    field_rows = []
    constant_fields = []
    mostly_constant_fields = []
    varied_fields = []
    partial_fields = []
    total_lines = len(per_line)

    def field_line_values(field_name: str) -> list[dict]:
        return [
            {
                "line_label": row["line_label"],
                "line_id": row["line_id"],
                "value": row["settings"].get(field_name, "(missing)"),
            }
            for row in per_line
        ]

    for field, label in FIELD_LABELS.items():
        values = values_by_field[field]
        present_count = len(values)
        counts = Counter(values)
        most_common_value, most_common_count = counts.most_common(1)[0] if counts else ("", 0)
        unique_count = len(counts)
        presence_coverage = present_count / total_lines if total_lines else 0.0
        value_coverage = most_common_count / present_count if present_count else 0.0
        if not values:
            status = "missing"
        elif present_count == total_lines and unique_count == 1:
            status = "constant"
            constant_fields.append({"field": field, "label": label, "value": most_common_value})
        elif unique_count == 1:
            status = "partial constant"
            field_detail = {
                "field": field,
                "label": label,
                "status": status,
                "most_common_value": most_common_value,
                "presence_coverage": presence_coverage,
                "value_coverage": value_coverage,
                "values": field_line_values(field),
            }
            partial_fields.append(field_detail)
        elif presence_coverage >= mostly_constant_threshold and value_coverage >= mostly_constant_threshold:
            status = "mostly constant"
            mostly_constant_fields.append({
                "field": field,
                "label": label,
                "status": status,
                "value": most_common_value,
                "presence_coverage": presence_coverage,
                "value_coverage": value_coverage,
                "values": field_line_values(field),
            })
        else:
            if value_coverage >= mostly_constant_threshold:
                status = "partial mostly constant"
            elif present_count < total_lines:
                status = "partial"
            else:
                status = "varied"

            field_detail = {
                "field": field,
                "label": label,
                "status": status,
                "most_common_value": most_common_value,
                "presence_coverage": presence_coverage,
                "value_coverage": value_coverage,
                "values": field_line_values(field),
            }
            if status == "varied":
                varied_fields.append(field_detail)
            else:
                partial_fields.append(field_detail)
        field_rows.append({
            "field": field,
            "label": label,
            "detected_count": present_count,
            "present_count": present_count,
            "unique_count": unique_count,
            "most_common_value": most_common_value,
            "most_common_count": most_common_count,
            "presence_coverage": presence_coverage,
            "value_coverage": value_coverage,
            "status": status,
        })

    lines_with_settings = sum(1 for row in per_line if row["settings"])
    return {
        "total_lines": len(per_line),
        "lines_with_settings": lines_with_settings,
        "lines_without_settings": len(per_line) - lines_with_settings,
        "field_rows": field_rows,
        "constant_fields": constant_fields,
        "mostly_constant_fields": mostly_constant_fields,
        "partial_fields": partial_fields,
        "varied_fields": varied_fields,
        "per_line": per_line,
    }
