"""Pure, in-memory search helpers for the Global Module Library."""

from __future__ import annotations

import unicodedata
from typing import Any, Dict, Iterable, List


_EXCLUDED_FIELD_NAMES = {
    "checksum",
    "created_at",
    "created_timestamp",
    "digest",
    "hash",
    "library_path",
    "private",
    "private_state",
    "runtime",
    "runtime_only",
    "runtime_state",
    "schema_version",
    "temporary",
    "temporary_state",
    "timestamp",
    "ui_state",
    "updated_at",
    "updated_timestamp",
}


def _safe_search_string(value: object) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        # Search must fail soft for malformed or unsupported in-memory values.
        return ""


def normalize_module_library_search_text(value: object) -> str:
    """Normalize one query/document fragment without interpreting it as regex."""

    text = _safe_search_string(value)
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(normalized.split())


def _field_is_searchable(field_name: object) -> bool:
    if not isinstance(field_name, (str, bool, int, float)):
        return False
    normalized = normalize_module_library_search_text(field_name)
    if not normalized or normalized.startswith("_"):
        return False
    key = normalized.replace(" ", "_")
    if key in _EXCLUDED_FIELD_NAMES:
        return False
    if key == "path" or key.endswith("_path") or key.endswith("_paths"):
        return False
    if "checksum" in key or "digest" in key:
        return False
    if key.endswith("_hash") or key.startswith("hash_"):
        return False
    if key.endswith("_timestamp"):
        return False
    if key.startswith(("private_", "runtime_", "temporary_", "temp_", "ui_")):
        return False
    return True


def _append_search_values(
    value: Any,
    fragments: List[str],
    seen_containers: set[int],
) -> None:
    if value is None or isinstance(value, (bytes, bytearray, memoryview)):
        return
    if isinstance(value, str):
        normalized = normalize_module_library_search_text(value)
        if normalized:
            fragments.append(normalized)
        return
    if isinstance(value, (bool, int, float)):
        normalized = normalize_module_library_search_text(value)
        if normalized:
            fragments.append(normalized)
        return

    if isinstance(value, dict):
        identity = id(value)
        if identity in seen_containers:
            return
        seen_containers.add(identity)
        for raw_key, nested_value in value.items():
            if not _field_is_searchable(raw_key):
                continue
            if isinstance(nested_value, (dict, list, tuple, set, frozenset)):
                normalized_key = normalize_module_library_search_text(raw_key)
                if normalized_key:
                    fragments.append(normalized_key)
            _append_search_values(
                nested_value,
                fragments,
                seen_containers,
            )
        return

    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in seen_containers:
            return
        seen_containers.add(identity)
        for item in value:
            _append_search_values(item, fragments, seen_containers)
        return

    if isinstance(value, (set, frozenset)):
        identity = id(value)
        if identity in seen_containers:
            return
        seen_containers.add(identity)
        normalized_items = []
        for item in value:
            if isinstance(item, (str, bool, int, float)):
                normalized = normalize_module_library_search_text(item)
                if normalized:
                    normalized_items.append(normalized)
            elif isinstance(item, (dict, list, tuple, set, frozenset)):
                nested_fragments: List[str] = []
                _append_search_values(
                    item,
                    nested_fragments,
                    seen_containers,
                )
                normalized_items.extend(nested_fragments)
        fragments.extend(sorted(normalized_items))


def build_global_module_search_document(
    module_name: str,
    module_data: object,
) -> str:
    """Build a normalized document from already-loaded Module data only."""

    fragments = []
    normalized_name = normalize_module_library_search_text(module_name)
    if normalized_name:
        fragments.append(normalized_name)
    _append_search_values(module_data, fragments, set())
    return " ".join(fragments)


def _module_category(module_data: object) -> str:
    if not isinstance(module_data, dict):
        return ""
    return normalize_module_library_search_text(module_data.get("category"))


def filter_global_module_library(
    global_modules: dict,
    *,
    query: str = "",
    category: str = "",
) -> Dict[str, Any]:
    """Filter loaded Global Modules with stable, whitespace-term AND matching."""

    normalized_query = normalize_module_library_search_text(query)
    terms = [term for term in normalized_query.split(" ") if term]
    normalized_category = normalize_module_library_search_text(category)
    category_enabled = bool(
        normalized_category and normalized_category != "all"
    )

    if not isinstance(global_modules, dict):
        module_items: Iterable[tuple[object, object]] = ()
    else:
        module_items = global_modules.items()

    all_names = []
    matched_names = []
    matched_items = []
    for raw_name, module_data in module_items:
        if not isinstance(raw_name, (str, bool, int, float)):
            continue
        module_name = _safe_search_string(raw_name)
        if not module_name:
            continue
        all_names.append(module_name)
        document = build_global_module_search_document(
            module_name,
            module_data,
        )
        if terms and not all(term in document for term in terms):
            continue
        if (
            category_enabled
            and _module_category(module_data) != normalized_category
        ):
            continue
        matched_names.append(module_name)
        matched_items.append(
            {
                "name": module_name,
                "module": module_data,
                "search_document": document,
            }
        )

    return {
        "query": _safe_search_string(query),
        "normalized_query": normalized_query,
        "terms": terms,
        "category": _safe_search_string(category),
        "normalized_category": normalized_category,
        "total_count": len(all_names),
        "matched_count": len(matched_names),
        "all_names": all_names,
        "matched_names": matched_names,
        "items": matched_items,
    }


def normalize_global_module_search_selection(
    current_selection: object,
    visible_names: Iterable[str],
) -> str:
    """Keep a visible selection or safely fall back to the first result."""

    options = list(visible_names or [])
    current = _safe_search_string(current_selection)
    if current in options:
        return current
    return options[0] if options else ""
