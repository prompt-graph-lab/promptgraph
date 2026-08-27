from __future__ import annotations

import csv
import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote


SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
CSV_EXTENSIONS = {".csv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

LIKELY_DATA_NAME_PARTS = ("animadex", "character", "characters", "chara", "tag", "tags")
LIKELY_THUMBNAIL_NAME_PARTS = ("thumb", "thumbnail", "cover", "preview", "image", "images")
RECORD_TYPES = ("character", "artist", "copyright", "unknown")
SUMMARY_RECORD_KEYS = {
    "character": "character_records",
    "artist": "artist_records",
    "copyright": "copyright_records",
    "unknown": "unknown_records",
}
CHARACTER_TABLE_NAMES = {"character", "characters", "char", "chars", "chara", "charas"}
ARTIST_TABLE_NAMES = {"artist", "artists", "creator", "creators", "author", "authors"}
COPYRIGHT_TABLE_NAMES = {"copyright", "copyrights", "work", "works", "series", "franchise", "franchises"}

FIELD_ALIASES = {
    "character_id": ("character_id", "characterid", "id", "uid", "uuid", "key", "hash"),
    "name": ("name", "display_name", "displayname", "title"),
    "character": ("character", "character_name", "charactername", "chara", "char_name"),
    "copyright": ("copyright", "series", "work", "source", "franchise"),
    "copyright_name": ("copyright_name", "copyrightname", "series_name", "work_name"),
    "series": ("series", "series_name", "seriesname", "copyright", "copyright_name", "work", "work_name", "franchise"),
    "work": ("work", "work_name", "workname", "series", "series_name", "copyright", "copyright_name", "source"),
    "franchise": ("franchise", "franchise_name", "franchisename", "series", "copyright", "source"),
    "artist": ("artist", "artist_name", "artistname", "creator", "creator_name", "author", "author_name"),
    "trigger": ("trigger", "activation_text", "activationtext", "prompt", "main_tag", "tag"),
    "core_tags": ("core_tags", "coretags", "tags", "prompt_tags", "stable_tags", "tag_string"),
    "hair color": ("hair_color", "haircolor", "hair_colour", "haircolour"),
    "hair length": ("hair_length", "hairlength"),
    "eye color": ("eye_color", "eyecolor", "eye_colour", "eyecolour", "eyes"),
    "gender": ("gender", "sex"),
    "lora info": ("lora", "lora_name", "loraname", "lora_info", "lorainfo", "model"),
    "source url": ("source_url", "sourceurl", "url", "reference_url", "referenceurl"),
    "image path": ("image_path", "imagepath", "image", "file", "file_path", "filepath"),
    "thumbnail path": ("thumbnail_path", "thumbnailpath", "thumb", "thumb_path", "cover_path"),
    "count": ("count", "popularity", "uses", "usage_count", "post_count", "favorites", "score"),
}

TRAIT_FIELDS = ("hair color", "hair length", "eye color", "gender")
SEARCH_FIELD_ALIASES = {
    "all": (
        "name",
        "character",
        "copyright",
        "copyright_name",
        "series",
        "work",
        "franchise",
        "artist",
        "trigger",
        "core_tags",
        "lora info",
        "source url",
        *TRAIT_FIELDS,
    ),
    "name": ("name", "character"),
    "series": ("copyright", "copyright_name", "series", "work", "franchise"),
    "trigger": ("trigger",),
    "tags": ("core_tags", *TRAIT_FIELDS, "lora info"),
}


def discover_animadex_local_data(
    root_path: str | os.PathLike[str],
    *,
    sample_limit: int = 5,
    file_scan_limit: int = 2000,
    image_scan_limit: int = 500,
) -> dict[str, Any]:
    """Return a read-only summary of likely local AnimaDex data.

    This helper intentionally does not create, update, import, or download
    anything. It samples local SQLite/CSV/image files so a future UI can preview
    available character-module sources before any Global Module import step.
    """

    root = Path(root_path).expanduser()
    summary: dict[str, Any] = {
        "root_path": str(root),
        "exists": root.exists(),
        "source_types": [],
        "sqlite_files": [],
        "csv_files": [],
        "thumbnail_directories": [],
        "directory_records": [],
        "character_records": [],
        "artist_records": [],
        "copyright_records": [],
        "unknown_records": [],
        "warnings": [],
    }

    if not root.exists():
        summary["warnings"].append(f"Path does not exist: {root}")
        return summary

    sqlite_files, csv_files, image_files, scan_warnings = _scan_local_files(root, file_scan_limit, image_scan_limit)
    summary["warnings"].extend(scan_warnings)

    if sqlite_files:
        summary["source_types"].append("sqlite")
    if csv_files:
        summary["source_types"].append("csv")
    if image_files:
        summary["source_types"].append("directory")

    for sqlite_file in sqlite_files:
        sqlite_summary = inspect_animadex_sqlite(sqlite_file, sample_limit=sample_limit)
        summary["sqlite_files"].append(sqlite_summary)
        for record_type, record_key in SUMMARY_RECORD_KEYS.items():
            summary[record_key].extend(sqlite_summary.get(record_key, []))

    for csv_file in csv_files:
        csv_summary = inspect_animadex_csv(csv_file, sample_limit=sample_limit)
        summary["csv_files"].append(csv_summary)
        for record_type, record_key in SUMMARY_RECORD_KEYS.items():
            summary[record_key].extend(csv_summary.get(record_key, []))

    summary["thumbnail_directories"] = summarize_thumbnail_directories(image_files, root)
    summary["directory_records"] = [
        normalize_animadex_directory_image_record(image_path, root, index)
        for index, image_path in enumerate(_prioritize_thumbnail_images(image_files), start=1)
        if index <= sample_limit
    ]
    summary["character_records"].extend(summary["directory_records"])
    _attach_nearby_thumbnail_paths(summary["character_records"], image_files)
    _attach_nearby_thumbnail_paths(summary["artist_records"], image_files)
    _attach_nearby_thumbnail_paths(summary["copyright_records"], image_files)
    return summary


def inspect_animadex_sqlite(path: str | os.PathLike[str], *, sample_limit: int = 5) -> dict[str, Any]:
    db_path = Path(path).expanduser()
    summary: dict[str, Any] = {
        "path": str(db_path),
        "exists": db_path.exists(),
        "is_likely_animadex": _looks_like_data_path(db_path),
        "tables": [],
        "sample_records": [],
        "character_records": [],
        "artist_records": [],
        "copyright_records": [],
        "unknown_records": [],
        "warnings": [],
    }
    if not db_path.exists():
        summary["warnings"].append(f"SQLite file does not exist: {db_path}")
        return summary

    conn = None
    try:
        conn = _connect_sqlite_readonly(db_path)
        with conn:
            table_names = [
                row[0]
                for row in conn.execute(
                    "select name from sqlite_schema where type = 'table' and name not like 'sqlite_%' order by name"
                ).fetchall()
            ]
            for table_name in table_names:
                table_summary = _inspect_sqlite_table(conn, table_name, db_path, sample_limit)
                summary["tables"].append(table_summary)
                record_key = SUMMARY_RECORD_KEYS.get(table_summary.get("record_type"), "unknown_records")
                summary[record_key].extend(table_summary.get("sample_records", []))
                if table_summary.get("record_type") == "character":
                    summary["sample_records"].extend(table_summary.get("sample_records", []))
    except sqlite3.DatabaseError as exc:
        summary["warnings"].append(f"Could not inspect SQLite file: {exc}")
    except OSError as exc:
        summary["warnings"].append(f"Could not open SQLite file: {exc}")
    finally:
        if conn is not None:
            conn.close()

    return summary


def inspect_animadex_csv(path: str | os.PathLike[str], *, sample_limit: int = 5) -> dict[str, Any]:
    csv_path = Path(path).expanduser()
    summary: dict[str, Any] = {
        "path": str(csv_path),
        "exists": csv_path.exists(),
        "is_likely_animadex": _looks_like_data_path(csv_path),
        "columns": [],
        "likely_character_file": False,
        "record_type": "unknown",
        "sample_records": [],
        "character_records": [],
        "artist_records": [],
        "copyright_records": [],
        "unknown_records": [],
        "warnings": [],
    }
    if not csv_path.exists():
        summary["warnings"].append(f"CSV file does not exist: {csv_path}")
        return summary

    try:
        with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = [str(column or "").strip() for column in (reader.fieldnames or []) if str(column or "").strip()]
            summary["columns"] = columns
            record_type = classify_animadex_record_source(csv_path.name, columns)
            summary["record_type"] = record_type
            summary["likely_character_file"] = record_type == "character"
            record_key = SUMMARY_RECORD_KEYS.get(record_type, "unknown_records")
            for index, row in enumerate(reader, start=1):
                if index > sample_limit:
                    break
                record = normalize_animadex_character_record(
                    row,
                    source_type="csv",
                    source_path=csv_path,
                    source_detail=csv_path.name,
                    row_index=index,
                    record_type=record_type,
                )
                summary[record_key].append(record)
                if record_type == "character":
                    summary["sample_records"].append(record)
    except csv.Error as exc:
        summary["warnings"].append(f"Could not parse CSV file: {exc}")
    except OSError as exc:
        summary["warnings"].append(f"Could not open CSV file: {exc}")

    return summary


def summarize_thumbnail_directories(image_files: list[Path], root: Path | None = None) -> list[dict[str, Any]]:
    root = root.expanduser() if root else None
    grouped: dict[str, dict[str, Any]] = {}
    for image_path in image_files:
        directory = image_path.parent
        key = str(directory)
        record = grouped.setdefault(
            key,
            {
                "path": key,
                "is_likely_thumbnail_directory": _looks_like_thumbnail_path(directory),
                "sample_count": 0,
                "sample_paths": [],
            },
        )
        record["sample_count"] += 1
        if len(record["sample_paths"]) < 8:
            record["sample_paths"].append(_display_path(image_path, root))
    return sorted(grouped.values(), key=lambda item: (not item["is_likely_thumbnail_directory"], item["path"]))


def normalize_animadex_directory_image_record(
    image_path: str | os.PathLike[str],
    root: Path | None = None,
    row_index: int = 0,
) -> dict[str, Any]:
    path = Path(image_path).expanduser()
    name = path.stem.replace("_", " ").replace("-", " ").strip()
    return {
        "character_id": _stable_character_key("directory", str(path.parent), row_index, name, ""),
        "name": name,
        "character": name,
        "copyright": "",
        "copyright_name": "",
        "trigger": "",
        "core_tags": [],
        "traits": {},
        "lora_info": "",
        "source_url": "",
        "image_path": str(path),
        "thumbnail_path": str(path),
        "count": "",
        "popularity": "",
        "record_type": "character",
        "source_type": "directory",
        "source_path": str(root or path.parent),
        "source_detail": _display_path(path, root),
    }


def normalize_animadex_character_record(
    row: dict[str, Any],
    *,
    source_type: str,
    source_path: str | os.PathLike[str],
    source_detail: str = "",
    row_index: int = 0,
    record_type: str = "character",
) -> dict[str, Any]:
    source_path_obj = Path(source_path)
    lowered = {_normalize_column_name(key): value for key, value in (row or {}).items()}

    def pick(field_name: str) -> Any:
        for alias in FIELD_ALIASES[field_name]:
            value = lowered.get(_normalize_column_name(alias))
            if _has_value(value):
                return value
        return ""

    traits = {
        trait_name: _clean_scalar(pick(trait_name))
        for trait_name in TRAIT_FIELDS
        if _has_value(pick(trait_name))
    }
    for key, value in (row or {}).items():
        normalized_key = _normalize_column_name(key)
        if normalized_key.startswith("trait") or normalized_key.startswith("facet"):
            clean_value = _clean_scalar(value)
            if clean_value:
                traits[str(key).strip()] = clean_value

    trigger = _clean_scalar(pick("trigger"))
    character = _clean_scalar(pick("character"))
    name = _clean_scalar(pick("name")) or character or trigger
    character_id = _clean_scalar(pick("character_id"))
    if not character_id:
        character_id = _stable_character_key(source_type, source_detail, row_index, name, trigger)

    image_path = _resolve_local_path(pick("image path"), source_path_obj.parent)
    thumbnail_path = _resolve_local_path(pick("thumbnail path"), source_path_obj.parent)

    return {
        "character_id": character_id,
        "name": name,
        "character": character,
        "copyright": _clean_scalar(pick("copyright")),
        "copyright_name": _clean_scalar(pick("copyright_name")),
        "series": _clean_scalar(pick("series")),
        "work": _clean_scalar(pick("work")),
        "franchise": _clean_scalar(pick("franchise")),
        "artist": _clean_scalar(pick("artist")),
        "trigger": trigger,
        "core_tags": _split_tags(pick("core_tags")),
        "traits": traits,
        "lora_info": _clean_scalar(pick("lora info")),
        "source_url": _clean_scalar(pick("source url")),
        "image_path": image_path,
        "thumbnail_path": thumbnail_path,
        "count": _clean_scalar(pick("count")),
        "popularity": _clean_scalar(pick("count")),
        "record_type": record_type if record_type in RECORD_TYPES else "unknown",
        "source_type": source_type,
        "source_path": str(source_path_obj),
        "source_detail": source_detail,
    }


def _scan_local_files(root: Path, file_scan_limit: int, image_scan_limit: int) -> tuple[list[Path], list[Path], list[Path], list[str]]:
    warnings: list[str] = []
    sqlite_files: list[Path] = []
    csv_files: list[Path] = []
    image_files: list[Path] = []

    if root.is_file():
        candidates = [root]
        image_root = root.parent
    else:
        candidates = []
        image_root = root
        scanned = 0
        try:
            for candidate in root.rglob("*"):
                if not candidate.is_file():
                    continue
                scanned += 1
                if scanned > file_scan_limit:
                    warnings.append(f"Stopped file scan after {file_scan_limit} files.")
                    break
                candidates.append(candidate)
        except OSError as exc:
            warnings.append(f"Could not scan directory: {exc}")

    for candidate in candidates:
        suffix = candidate.suffix.lower()
        if suffix in SQLITE_EXTENSIONS or _looks_like_sqlite_name(candidate):
            sqlite_files.append(candidate)
        elif suffix in CSV_EXTENSIONS:
            csv_files.append(candidate)

    image_scanned = 0
    try:
        image_candidates = image_root.rglob("*") if image_root.is_dir() else []
        for candidate in image_candidates:
            if not candidate.is_file() or candidate.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            image_files.append(candidate)
            image_scanned += 1
            if image_scanned >= image_scan_limit:
                warnings.append(f"Stopped image scan after {image_scan_limit} images.")
                break
    except OSError as exc:
        warnings.append(f"Could not scan image directory: {exc}")

    return (
        sorted(set(sqlite_files), key=lambda item: str(item).lower()),
        sorted(set(csv_files), key=lambda item: str(item).lower()),
        sorted(set(image_files), key=lambda item: str(item).lower()),
        warnings,
    )


def _prioritize_thumbnail_images(image_files: list[Path]) -> list[Path]:
    return sorted(image_files, key=lambda path: (not _looks_like_thumbnail_path(path), str(path).lower()))


def _connect_sqlite_readonly(path: Path) -> sqlite3.Connection:
    uri_path = quote(path.resolve().as_posix(), safe="/:")
    conn = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _inspect_sqlite_table(
    conn: sqlite3.Connection,
    table_name: str,
    db_path: Path,
    sample_limit: int,
) -> dict[str, Any]:
    columns = [row["name"] for row in conn.execute(f"pragma table_info({_quote_sqlite_identifier(table_name)})")]
    record_type = classify_animadex_record_source(table_name, columns)
    likely_character_table = record_type == "character"
    sample_records = []
    if record_type in RECORD_TYPES:
        try:
            rows = conn.execute(f"select * from {_quote_sqlite_identifier(table_name)} limit ?", (sample_limit,)).fetchall()
            for index, row in enumerate(rows, start=1):
                sample_records.append(
                    normalize_animadex_character_record(
                        dict(row),
                        source_type="sqlite",
                        source_path=db_path,
                        source_detail=table_name,
                        row_index=index,
                        record_type=record_type,
                    )
                )
        except sqlite3.DatabaseError:
            sample_records = []

    return {
        "name": table_name,
        "columns": columns,
        "record_type": record_type,
        "likely_character_table": likely_character_table,
        "sample_records": sample_records,
    }


def search_animadex_records(
    discovery_summary: dict[str, Any],
    *,
    query: str = "",
    record_type: str = "character",
    search_mode: str = "all",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Search discovered local records without loading full SQLite databases."""

    selected_types = _selected_record_types(record_type)
    remaining = max(1, int(limit or 100))
    records: list[dict[str, Any]] = []

    for sqlite_summary in discovery_summary.get("sqlite_files", []) or []:
        if remaining <= 0:
            break
        records.extend(
            search_animadex_sqlite_records(
                sqlite_summary.get("path", ""),
                query=query,
                record_type=record_type,
                search_mode=search_mode,
                limit=remaining,
            )
        )
        remaining = max(0, int(limit or 100) - len(records))

    if remaining > 0:
        fallback_records = []
        for selected_type in selected_types:
            fallback_records.extend(
                record
                for record in discovery_summary.get(SUMMARY_RECORD_KEYS[selected_type], []) or []
                if record.get("source_type") != "sqlite"
            )
        records.extend(_filter_normalized_records(fallback_records, query, search_mode, limit=remaining))

    return records[: int(limit or 100)]


def search_animadex_sqlite_records(
    path: str | os.PathLike[str],
    *,
    query: str = "",
    record_type: str = "character",
    search_mode: str = "all",
    limit: int = 100,
) -> list[dict[str, Any]]:
    db_path = Path(path).expanduser()
    if not db_path.exists():
        return []

    selected_types = _selected_record_types(record_type)
    results: list[dict[str, Any]] = []
    conn = None
    try:
        conn = _connect_sqlite_readonly(db_path)
        table_names = [
            row[0]
            for row in conn.execute(
                "select name from sqlite_schema where type = 'table' and name not like 'sqlite_%' order by name"
            ).fetchall()
        ]
        for table_name in table_names:
            if len(results) >= limit:
                break
            columns = [row["name"] for row in conn.execute(f"pragma table_info({_quote_sqlite_identifier(table_name)})")]
            table_record_type = classify_animadex_record_source(table_name, columns)
            if table_record_type not in selected_types:
                continue
            rows = _search_sqlite_table_rows(
                conn,
                table_name,
                columns,
                query=query,
                search_mode=search_mode,
                limit=max(0, limit - len(results)),
            )
            for index, row in enumerate(rows, start=1):
                results.append(
                    normalize_animadex_character_record(
                        dict(row),
                        source_type="sqlite",
                        source_path=db_path,
                        source_detail=table_name,
                        row_index=index,
                        record_type=table_record_type,
                    )
                )
    except (sqlite3.DatabaseError, OSError):
        return []
    finally:
        if conn is not None:
            conn.close()

    return results[:limit]


def collect_animadex_record_facets(records: list[dict[str, Any]], *, limit: int = 12) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, dict[str, int]] = {"copyright": {}, "series": {}, "work": {}, "franchise": {}}
    for record in records or []:
        values = {
            "copyright": record.get("copyright_name") or record.get("copyright"),
            "series": record.get("series") or record.get("copyright_name") or record.get("copyright"),
            "work": record.get("work"),
            "franchise": record.get("franchise"),
        }
        for key, value in values.items():
            clean_value = _clean_scalar(value)
            if clean_value:
                buckets[key][clean_value] = buckets[key].get(clean_value, 0) + 1
    return {
        key: [
            {"value": value, "count": count}
            for value, count in sorted(values.items(), key=lambda item: (-item[1], item[0].casefold()))[:limit]
        ]
        for key, values in buckets.items()
    }


def classify_animadex_record_source(source_name: str, columns: list[str]) -> str:
    normalized_name = _normalize_column_name(Path(str(source_name)).stem)
    normalized_columns = {_normalize_column_name(column) for column in columns}

    if normalized_name in ARTIST_TABLE_NAMES or any(name in normalized_name for name in ARTIST_TABLE_NAMES):
        return "artist"
    if normalized_name in COPYRIGHT_TABLE_NAMES or any(name in normalized_name for name in COPYRIGHT_TABLE_NAMES):
        return "copyright"
    if normalized_name in CHARACTER_TABLE_NAMES or any(name in normalized_name for name in CHARACTER_TABLE_NAMES):
        return "character"

    artist_columns = _alias_set("artist")
    copyright_columns = _alias_set("copyright") | _alias_set("copyright_name") | _alias_set("series") | _alias_set("work")
    character_columns = _alias_set("character") | _alias_set("trigger")
    tag_columns = _alias_set("core_tags")

    if normalized_columns & artist_columns and not (normalized_columns & character_columns):
        return "artist"
    if normalized_columns & character_columns:
        return "character"
    if normalized_columns & copyright_columns and not (normalized_columns & (character_columns | tag_columns)):
        return "copyright"
    if _looks_like_character_columns(columns):
        return "character"
    return "unknown"


def _search_sqlite_table_rows(
    conn: sqlite3.Connection,
    table_name: str,
    columns: list[str],
    *,
    query: str,
    search_mode: str,
    limit: int,
) -> list[sqlite3.Row]:
    if limit <= 0:
        return []

    quoted_table = _quote_sqlite_identifier(table_name)
    terms = [term for term in str(query or "").strip().split() if term]
    if not terms:
        return conn.execute(f"select * from {quoted_table} limit ?", (limit,)).fetchall()

    searchable_columns = _searchable_sqlite_columns(columns, search_mode)
    if not searchable_columns:
        return []

    where_parts = []
    params: list[Any] = []
    for term in terms:
        column_parts = [f"cast({_quote_sqlite_identifier(column)} as text) like ? collate nocase" for column in searchable_columns]
        where_parts.append("(" + " or ".join(column_parts) + ")")
        params.extend([f"%{term}%" for _ in searchable_columns])
    params.append(limit)
    where_clause = " and ".join(where_parts)
    return conn.execute(f"select * from {quoted_table} where {where_clause} limit ?", params).fetchall()


def _searchable_sqlite_columns(columns: list[str], search_mode: str) -> list[str]:
    normalized_to_column = {_normalize_column_name(column): column for column in columns}
    selected_fields = SEARCH_FIELD_ALIASES.get(search_mode, SEARCH_FIELD_ALIASES["all"])
    selected_columns = []
    seen = set()
    for field_name in selected_fields:
        for alias in FIELD_ALIASES.get(field_name, ()):
            normalized_alias = _normalize_column_name(alias)
            column = normalized_to_column.get(normalized_alias)
            if column and column not in seen:
                selected_columns.append(column)
                seen.add(column)
    if search_mode in ("all", "tags"):
        for column in columns:
            normalized_column = _normalize_column_name(column)
            if (normalized_column.startswith("trait") or normalized_column.startswith("facet")) and column not in seen:
                selected_columns.append(column)
                seen.add(column)
    return selected_columns


def _filter_normalized_records(
    records: list[dict[str, Any]],
    query: str,
    search_mode: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    terms = [term.casefold() for term in str(query or "").strip().split() if term]
    if not terms:
        return list(records or [])[:limit]
    filtered = []
    for record in records or []:
        text = _normalized_record_search_text(record, search_mode)
        if all(term in text for term in terms):
            filtered.append(record)
            if len(filtered) >= limit:
                break
    return filtered


def _normalized_record_search_text(record: dict[str, Any], search_mode: str) -> str:
    fields = SEARCH_FIELD_ALIASES.get(search_mode, SEARCH_FIELD_ALIASES["all"])
    values = []
    for field_name in fields:
        if field_name == "core_tags":
            values.extend(str(tag) for tag in record.get("core_tags", []) or [])
        elif field_name in TRAIT_FIELDS:
            values.append((record.get("traits") or {}).get(field_name, ""))
        else:
            values.append(record.get(field_name, ""))
    if search_mode in ("all", "tags"):
        values.extend(str(value) for value in (record.get("traits") or {}).values())
    return " ".join(str(value) for value in values if value).casefold()


def _selected_record_types(record_type: str) -> tuple[str, ...]:
    if record_type == "all":
        return RECORD_TYPES
    if record_type in RECORD_TYPES:
        return (record_type,)
    return ("character",)


def _alias_set(field_name: str) -> set[str]:
    return {_normalize_column_name(alias) for alias in FIELD_ALIASES.get(field_name, ())}


def _quote_sqlite_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _looks_like_sqlite_name(path: Path) -> bool:
    name = path.name.lower()
    return "sqlite" in name or (path.suffix.lower() in SQLITE_EXTENSIONS and _looks_like_data_path(path))


def _looks_like_data_path(path: Path) -> bool:
    lowered = str(path).lower()
    return any(part in lowered for part in LIKELY_DATA_NAME_PARTS)


def _looks_like_thumbnail_path(path: Path) -> bool:
    lowered = str(path).lower()
    return any(part in lowered for part in LIKELY_THUMBNAIL_NAME_PARTS)


def _looks_like_character_columns(columns: list[str]) -> bool:
    normalized_columns = {_normalize_column_name(column) for column in columns}
    signal_count = 0
    for field_name in ("name", "character", "trigger", "core_tags", "copyright", "thumbnail path", "image path"):
        aliases = {_normalize_column_name(alias) for alias in FIELD_ALIASES[field_name]}
        if normalized_columns & aliases:
            signal_count += 1
    return signal_count >= 2


def _normalize_column_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _has_value(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return " ".join(str(value).replace("\r", "\n").split())


def _split_tags(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_tags = value
    else:
        text = _clean_scalar(value)
        if not text:
            return []
        raw_tags = re.split(r"[,;|\n]+", text)
    tags = []
    seen = set()
    for raw_tag in raw_tags:
        tag = _clean_scalar(raw_tag)
        if not tag or tag in seen:
            continue
        tags.append(tag)
        seen.add(tag)
    return tags


def _resolve_local_path(value: Any, base_dir: Path) -> str:
    text = _clean_scalar(value)
    if not text:
        return ""
    path = Path(text).expanduser()
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def _stable_character_key(source_type: str, source_detail: str, row_index: int, name: str, trigger: str) -> str:
    seed = "|".join([source_type, source_detail, str(row_index), name, trigger])
    digest = hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"animadex_{digest}"


def _display_path(path: Path, root: Path | None) -> str:
    if root:
        try:
            return str(path.relative_to(root))
        except ValueError:
            pass
    return str(path)


def _attach_nearby_thumbnail_paths(records: list[dict[str, Any]], image_files: list[Path]) -> None:
    if not records or not image_files:
        return
    images_by_stem = {_normalize_column_name(image.stem): image for image in image_files}
    for record in records:
        if record.get("thumbnail_path"):
            continue
        for key in (record.get("character_id"), record.get("name"), record.get("character"), record.get("trigger")):
            normalized_key = _normalize_column_name(key)
            if normalized_key and normalized_key in images_by_stem:
                record["thumbnail_path"] = str(images_by_stem[normalized_key])
                break
