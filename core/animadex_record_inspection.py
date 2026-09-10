"""In-memory AnimaDex record identity, filtering and display projections.

Discovery, file access, settings, module conversion and UI remain separate.
"""

import hashlib


def _animadex_record_identity(record):
    parts = [
        record.get("source_type", ""),
        record.get("source_path", ""),
        record.get("source_detail", ""),
        record.get("character_id", ""),
        record.get("name", ""),
        record.get("trigger", ""),
    ]
    return hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8", errors="replace")).hexdigest()


def _animadex_record_search_text(record):
    fields = [
        record.get("name", ""),
        record.get("character", ""),
        record.get("copyright", ""),
        record.get("copyright_name", ""),
        record.get("series", ""),
        record.get("work", ""),
        record.get("franchise", ""),
        record.get("artist", ""),
        record.get("trigger", ""),
        " ".join(str(tag) for tag in record.get("core_tags", []) or []),
        " ".join(str(value) for value in (record.get("traits") or {}).values()),
    ]
    return " ".join(str(field) for field in fields if field).casefold()


def _filter_animadex_records(records, query):
    query_text = str(query or "").strip().casefold()
    if not query_text:
        return list(records or [])
    terms = [term for term in query_text.split() if term]
    return [
        record
        for record in records or []
        if all(term in _animadex_record_search_text(record) for term in terms)
    ]


def _animadex_record_label(record):
    name = record.get("name") or record.get("character") or record.get("trigger") or "(unnamed)"
    trigger = record.get("trigger") or "no trigger"
    copyright_name = (
        record.get("copyright_name")
        or record.get("copyright")
        or record.get("series")
        or record.get("work")
        or "unknown work"
    )
    record_type = record.get("record_type") or "character"
    source_type = record.get("source_type") or "unknown"
    return f"{name} | {copyright_name} | {trigger} | {record_type} | {source_type}"


def _animadex_summary_rows(records):
    rows = []
    for record in records or []:
        rows.append({
            "type": record.get("record_type", ""),
            "name": record.get("name", ""),
            "character": record.get("character", ""),
            "copyright": record.get("copyright_name") or record.get("copyright", ""),
            "series": record.get("series", ""),
            "work": record.get("work", ""),
            "trigger": record.get("trigger", ""),
            "core tag count": len(record.get("core_tags") or []),
            "source type": record.get("source_type", ""),
        })
    return rows


def _animadex_preview_metadata_rows(metadata):
    rows = []
    for key, value in (metadata or {}).items():
        if isinstance(value, dict):
            display_value = ", ".join(f"{sub_key}: {sub_value}" for sub_key, sub_value in value.items())
        elif isinstance(value, list):
            display_value = ", ".join(str(item) for item in value)
        else:
            display_value = str(value)
        if display_value:
            rows.append({"field": key, "value": display_value})
    return rows
