from __future__ import annotations

import hashlib
import re
from typing import Any

from core.parser import parse_prompt


ANIMADEX_METADATA_FIELDS = (
    "character_id",
    "name",
    "character",
    "copyright",
    "copyright_name",
    "traits",
    "lora_info",
    "source_url",
    "thumbnail_path",
    "image_path",
    "source_type",
    "source_path",
    "source_detail",
    "count",
    "popularity",
)


def dedupe_prompt_tokens(tokens: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for token in tokens or []:
        token_text = str(token or "").strip()
        if not token_text:
            continue
        token_key = token_text.casefold()
        if token_key in seen:
            continue
        deduped.append(token_text)
        seen.add(token_key)
    return deduped


def normalize_module_name_from_animadex_record(record: dict[str, Any]) -> str:
    for field_name in ("name", "character", "trigger"):
        value = str((record or {}).get(field_name) or "").strip()
        if value:
            return _clean_module_name(value)
    return "AnimaDex Character"


def disambiguate_animadex_module_name(
    base_name: str,
    record: dict[str, Any],
    existing_names: set[str] | list[str] | tuple[str, ...],
) -> str:
    existing = {str(name) for name in existing_names or []}
    name = _clean_module_name(base_name)
    if name and name not in existing:
        return name

    copyright_name = str(
        (record or {}).get("copyright_name")
        or (record or {}).get("copyright")
        or ""
    ).strip()
    if copyright_name:
        candidate = _clean_module_name(f"{name} ({copyright_name})")
        if candidate not in existing:
            return candidate

    source_key = str(
        (record or {}).get("character_id")
        or (record or {}).get("source_detail")
        or (record or {}).get("source_path")
        or name
    )
    digest = hashlib.sha1(source_key.encode("utf-8", errors="replace")).hexdigest()[:8]
    candidate = _clean_module_name(f"{name} {digest}")
    suffix = 2
    while candidate in existing:
        candidate = _clean_module_name(f"{name} {digest} {suffix}")
        suffix += 1
    return candidate


def build_global_module_preview_from_animadex_record(
    record: dict[str, Any],
    *,
    existing_names: set[str] | list[str] | tuple[str, ...] | None = None,
    include_core_tags_in_core: bool = False,
    include_core_tags_in_body: bool = True,
) -> dict[str, Any]:
    record = record or {}
    trigger = str(record.get("trigger") or "").strip()
    core_tags = [str(token).strip() for token in record.get("core_tags") or [] if str(token).strip()]

    body_tokens = []
    if trigger:
        body_tokens.append(trigger)
    if include_core_tags_in_body:
        body_tokens.extend(core_tags)
    body_tokens = dedupe_prompt_tokens(_split_prompt_tokens(body_tokens))

    core_tokens = []
    if trigger:
        core_tokens.append(trigger)
    if include_core_tags_in_core:
        core_tokens.extend(core_tags)
    core_tokens = dedupe_prompt_tokens(_split_prompt_tokens(core_tokens))
    if not core_tokens and body_tokens:
        core_tokens = body_tokens[:1]

    base_name = normalize_module_name_from_animadex_record(record)
    module_name = disambiguate_animadex_module_name(base_name, record, existing_names or set())
    metadata = build_animadex_module_metadata(record)
    return {
        "module_name": module_name,
        "module_type": "character",
        "module_body": ", ".join(body_tokens),
        "body_tokens": body_tokens,
        "core_tokens": core_tokens,
        "min_match_tokens": max(1, len(core_tokens)) if body_tokens else 0,
        "metadata": metadata,
        "persisted_metadata": {
            "source": "animadex",
            "record": metadata,
        },
        "warnings": _preview_warnings(record, body_tokens, core_tokens),
    }


def build_animadex_module_metadata(record: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field_name in ANIMADEX_METADATA_FIELDS:
        value = (record or {}).get(field_name)
        if value in (None, "", [], {}):
            continue
        metadata[field_name] = value
    if (record or {}).get("trigger"):
        metadata["trigger"] = str(record.get("trigger")).strip()
    if (record or {}).get("core_tags"):
        metadata["core_tags"] = dedupe_prompt_tokens([str(tag) for tag in record.get("core_tags") or []])
    return metadata


def _split_prompt_tokens(tokens: list[str]) -> list[str]:
    split_tokens = []
    for token in tokens or []:
        parsed_tokens = [str(parsed).strip() for parsed in parse_prompt(str(token or "")) if str(parsed).strip()]
        split_tokens.extend(parsed_tokens or [str(token or "").strip()])
    return split_tokens


def _clean_module_name(value: str) -> str:
    name = " ".join(str(value or "").replace("\r", "\n").split())
    name = name.replace("<", "").replace(">", "").replace(",", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name or "AnimaDex Character"


def _preview_warnings(record: dict[str, Any], body_tokens: list[str], core_tokens: list[str]) -> list[str]:
    warnings = []
    if not str((record or {}).get("trigger") or "").strip():
        if body_tokens:
            warnings.append("Record has no trigger; the first body token is used as a fallback Core token.")
        else:
            warnings.append("Record has no trigger; import is disabled until a trigger/body token is available.")
    if not body_tokens:
        warnings.append("Module body is empty.")
    if not core_tokens:
        warnings.append("Core tokens are empty.")
    return warnings
