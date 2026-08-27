import os
import re
from collections import defaultdict


LORA_FILE_EXTENSIONS = {".safetensors", ".pt", ".ckpt"}
LORA_TAG_RE = re.compile(r"<lora:([^>]+)>", re.IGNORECASE)


def _clean_lora_part(value: str) -> str:
    return str(value or "").strip()


def extract_lora_references_from_text(text: str) -> list[dict]:
    references = []
    if not isinstance(text, str) or not text:
        return references

    for match in LORA_TAG_RE.finditer(text):
        raw = match.group(0)
        body = match.group(1)
        parts = body.split(":")
        name = _clean_lora_part(parts[0]) if parts else ""
        if not name:
            continue
        model_weight = _clean_lora_part(parts[1]) if len(parts) > 1 else ""
        clip_weight = _clean_lora_part(parts[2]) if len(parts) > 2 else ""
        references.append({
            "name": name,
            "model_weight": model_weight,
            "clip_weight": clip_weight,
            "raw": raw,
            "line_id": "",
            "line_label": "",
        })
    return references


def extract_lora_references_from_lines(lines) -> list[dict]:
    references = []
    for line in lines or []:
        text = getattr(line, "current_text", "") or ""
        line_refs = extract_lora_references_from_text(text)
        for ref in line_refs:
            ref["line_id"] = str(getattr(line, "id", "") or "")
            ref["line_label"] = str(getattr(line, "original_file_name", "") or ref["line_id"])
        references.extend(line_refs)
    return references


def scan_lora_directory(directory_path: str) -> list[dict]:
    if not directory_path:
        raise ValueError("LoRA directory path is empty.")

    root_path = os.path.abspath(os.path.expanduser(directory_path))
    if not os.path.isdir(root_path):
        raise ValueError(f"LoRA directory not found: {root_path}")

    files = []
    for root, _dirs, filenames in os.walk(root_path):
        for filename in filenames:
            extension = os.path.splitext(filename)[1].lower()
            if extension not in LORA_FILE_EXTENSIONS:
                continue
            path = os.path.abspath(os.path.join(root, filename))
            relative_path = os.path.relpath(path, root_path).replace(os.sep, "/")
            relative_no_ext = os.path.splitext(relative_path)[0]
            files.append({
                "stem": os.path.splitext(filename)[0],
                "relative_path": relative_path,
                "relative_stem": relative_no_ext,
                "filename": filename,
                "path": path,
                "extension": extension,
            })
    return sorted(files, key=lambda item: item["path"].lower())


def normalize_lora_name(name: str) -> str:
    lowered = str(name or "").lower()
    return re.sub(r"[\s_-]+", "", lowered)


def _weight_label(reference: dict) -> str:
    model_weight = reference.get("model_weight") or ""
    clip_weight = reference.get("clip_weight") or ""
    if model_weight and clip_weight:
        return f"{model_weight}/{clip_weight}"
    return model_weight or clip_weight or ""


def _dedupe_sorted(values) -> list[str]:
    return sorted({str(value) for value in values if str(value)})


def _aggregate_references(references: list[dict]) -> list[dict]:
    grouped = {}
    for ref in references:
        name = ref.get("name", "")
        if not name:
            continue
        entry = grouped.setdefault(name, {
            "name": name,
            "weights": set(),
            "line_ids": set(),
            "line_labels": set(),
            "raw": set(),
        })
        weight = _weight_label(ref)
        if weight:
            entry["weights"].add(weight)
        if ref.get("line_id"):
            entry["line_ids"].add(ref["line_id"])
        if ref.get("line_label"):
            entry["line_labels"].add(ref["line_label"])
        if ref.get("raw"):
            entry["raw"].add(ref["raw"])

    aggregated = []
    for entry in grouped.values():
        aggregated.append({
            "name": entry["name"],
            "weights": _dedupe_sorted(entry["weights"]),
            "line_ids": _dedupe_sorted(entry["line_ids"]),
            "line_labels": _dedupe_sorted(entry["line_labels"]),
            "raw": _dedupe_sorted(entry["raw"]),
        })
    return sorted(aggregated, key=lambda item: item["name"].lower())


def _file_display(file_info: dict) -> str:
    return file_info.get("path") or file_info.get("filename") or file_info.get("stem") or ""


def _file_match_keys(file_info: dict) -> list[str]:
    return _dedupe_sorted([
        file_info.get("stem", ""),
        file_info.get("relative_stem", ""),
    ])


def lora_file_injection_name(file_info: dict) -> str:
    relative_path = str(file_info.get("relative_path") or "").strip().replace("\\", "/")
    if relative_path:
        return relative_path
    return str(file_info.get("filename") or "").strip()


def match_lora_references_to_files(references: list[dict], files: list[dict]) -> list[dict]:
    aggregated_refs = _aggregate_references(references)

    exact_by_stem = defaultdict(list)
    lower_by_stem = defaultdict(list)
    normalized_files = []
    for file_info in files or []:
        for key in _file_match_keys(file_info):
            exact_by_stem[key].append(file_info)
            lower_by_stem[key.lower()].append(file_info)
            normalized_files.append((normalize_lora_name(key), file_info))

    results = []
    for ref in aggregated_refs:
        name = ref["name"]
        exact_matches = exact_by_stem.get(name, [])
        case_matches = [] if exact_matches else lower_by_stem.get(name.lower(), [])
        candidates = []
        status = "missing"
        matches = []

        if exact_matches:
            status = "found"
            matches = exact_matches
        elif case_matches:
            status = "found"
            matches = case_matches
        else:
            normalized_name = normalize_lora_name(name)
            seen_candidate_paths = set()
            if normalized_name:
                for normalized_stem, file_info in normalized_files:
                    if not normalized_stem:
                        continue
                    if normalized_name in normalized_stem or normalized_stem in normalized_name:
                        candidate_path = _file_display(file_info)
                        if candidate_path in seen_candidate_paths:
                            continue
                        seen_candidate_paths.add(candidate_path)
                        candidates.append(file_info)
            if candidates:
                status = "candidates"

        results.append({
            "name": name,
            "weights": ref["weights"],
            "line_ids": ref["line_ids"],
            "line_labels": ref["line_labels"],
            "raw": ref["raw"],
            "status": status,
            "matches": [_file_display(item) for item in matches],
            "candidates": [_file_display(item) for item in candidates],
            "match_files": matches,
            "candidate_files": candidates,
        })
    return results


def summarize_mapping_results(results: list[dict]) -> dict:
    summary = {
        "total": len(results or []),
        "found": 0,
        "candidates": 0,
        "missing": 0,
    }
    for result in results or []:
        status = result.get("status")
        if status in summary:
            summary[status] += 1
    return summary
