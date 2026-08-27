from typing import List, Set, Dict, Any, Optional
from core.project import Project
from core.graph_builder import build_graph
from core.parser import parse_prompt, extract_node_metadata, is_module_marker, is_structural_mod_marker, extract_mod_info
from core.modules import (
    create_blank_module_graph,
    flatten_module_graph_to_tokens,
    normalize_module_graph,
    validate_module_graph,
)
import re
import logging
import copy

logger = logging.getLogger(__name__)

MODULE_TYPES = [
    "generic",
    "character",
    "scene",
    "outfit",
    "camera",
    "expression",
    "style",
    "negative",
]
DEFAULT_MODULE_TYPE = "generic"
GLOBAL_MODULE_CATEGORIES = [
    "Character",
    "Quality / Header",
    "Location",
    "Outfit",
    "Pose / Action",
    "Lighting",
    "Camera / Composition",
    "Style",
    "Negative",
    "Other",
]
DEFAULT_GLOBAL_MODULE_CATEGORY = "Character"
ATTRIBUTE_LABEL_UNASSIGNED = "unassigned"
SUGGESTED_ATTRIBUTE_LABELS = [
    ATTRIBUTE_LABEL_UNASSIGNED,
    "name",
    "work_title",
    "series",
    "franchise",
    "character_group",
    "affiliation",
    "organization",
    "unit",
    "agency",
    "generation",
    "role",
    "species",
    "race",
    "character_type",
    "character_feature",
    "nonhuman_feature",
    "virtual_youtuber",
    "vtuber_agency",
    "vtuber_generation",
    "idol_group",
    "idol_unit",
    "skin_color",
    "body_type",
    "breast_size",
    "breast_shape",
    "horns",
    "wing_type",
    "wings",
    "halo",
    "tail",
    "animal_ears",
    "ears",
    "fangs",
    "claws",
    "scales",
    "hair_color",
    "hair_color_sub",
    "hair_length",
    "hair_texture",
    "hair_shape",
    "hair_accessory",
    "hair_ornament",
    "eye_shape",
    "eye_color",
    "eye_style",
    "pupil_shape",
    "outfit",
    "outfit_variant",
    "costume_theme",
    "uniform_type",
    "headwear",
    "neckwear",
    "handwear",
    "footwear",
    "pose",
    "expression",
    "behavior",
    "effect",
    "camera",
    "composition",
    "motif",
    "symbol",
    "character_symbol",
    "accessory_symbol",
    "theme_color",
]
SUGGESTED_ATTRIBUTE_SLOTS = [
    "character_identity",
    "hair_style",
    "outfit",
    "expression_set",
    "pose",
    "camera",
    "composition",
    "scene",
    "behavior",
    "effect",
    "custom",
]

def normalize_attribute_label(label: Any) -> str:
    normalized = str(label or "").strip().lower()
    normalized = re.sub(r"[\s\-]+", "_", normalized)
    normalized = re.sub(r"[^\w:]+", "_", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or ATTRIBUTE_LABEL_UNASSIGNED

def get_project_custom_attribute_labels(project: Project) -> List[str]:
    if not hasattr(project, "custom_attribute_labels") or project.custom_attribute_labels is None:
        project.custom_attribute_labels = []
    builtin = set(SUGGESTED_ATTRIBUTE_LABELS)
    normalized_labels = []
    seen = set()
    for label in getattr(project, "custom_attribute_labels", []) or []:
        normalized_label = normalize_attribute_label(label)
        if (
            not normalized_label
            or normalized_label == ATTRIBUTE_LABEL_UNASSIGNED
            or normalized_label in builtin
            or normalized_label in seen
        ):
            continue
        normalized_labels.append(normalized_label)
        seen.add(normalized_label)
    project.custom_attribute_labels = normalized_labels
    return project.custom_attribute_labels

def add_project_custom_attribute_labels(project: Project, labels: List[Any]) -> List[str]:
    existing = get_project_custom_attribute_labels(project)
    existing_set = set(existing)
    builtin = set(SUGGESTED_ATTRIBUTE_LABELS)
    added = []
    for label in labels or []:
        normalized_label = normalize_attribute_label(label)
        if (
            not normalized_label
            or normalized_label == ATTRIBUTE_LABEL_UNASSIGNED
            or normalized_label in builtin
            or normalized_label in existing_set
        ):
            continue
        existing.append(normalized_label)
        existing_set.add(normalized_label)
        added.append(normalized_label)
    project.custom_attribute_labels = existing
    return added

def get_project_attribute_label_usage_counts(project: Project) -> Dict[str, int]:
    if not hasattr(project, "attribute_label_usage_counts") or project.attribute_label_usage_counts is None:
        project.attribute_label_usage_counts = {}
    normalized_counts = {}
    for label, count in (getattr(project, "attribute_label_usage_counts", {}) or {}).items():
        normalized_label = normalize_attribute_label(label)
        if not normalized_label or normalized_label == ATTRIBUTE_LABEL_UNASSIGNED:
            continue
        try:
            normalized_count = int(count)
        except (TypeError, ValueError):
            continue
        if normalized_count <= 0:
            continue
        normalized_counts[normalized_label] = normalized_counts.get(normalized_label, 0) + normalized_count
    project.attribute_label_usage_counts = normalized_counts
    return project.attribute_label_usage_counts

def increment_attribute_label_usage_counts(project: Project, labels: Any) -> Dict[str, int]:
    counts = get_project_attribute_label_usage_counts(project)
    if isinstance(labels, dict):
        label_counts = labels.items()
    else:
        label_counts = ((label, 1) for label in (labels or []))
    for label, increment in label_counts:
        normalized_label = normalize_attribute_label(label)
        if not normalized_label or normalized_label == ATTRIBUTE_LABEL_UNASSIGNED:
            continue
        try:
            increment_value = int(increment)
        except (TypeError, ValueError):
            continue
        if increment_value <= 0:
            continue
        counts[normalized_label] = counts.get(normalized_label, 0) + increment_value
    project.attribute_label_usage_counts = counts
    return counts

def get_frequent_attribute_labels(project: Project, limit: int = 8, available_labels: List[Any] = None) -> List[str]:
    counts = get_project_attribute_label_usage_counts(project)
    if not counts:
        return []
    if available_labels is None:
        order_source = []
        for label in SUGGESTED_ATTRIBUTE_LABELS:
            normalized_label = normalize_attribute_label(label)
            if normalized_label and normalized_label not in order_source:
                order_source.append(normalized_label)
        for label in get_project_custom_attribute_labels(project):
            if label not in order_source:
                order_source.append(label)
    else:
        order_source = available_labels
    order_index = {
        normalize_attribute_label(label): index
        for index, label in enumerate(order_source or [])
    }
    sorted_labels = sorted(
        counts,
        key=lambda label: (-counts[label], order_index.get(label, len(order_index)), label),
    )
    return sorted_labels[:limit]

def get_attribute_label_options(project: Project = None, extra_labels: List[Any] = None) -> List[str]:
    base_options = []
    base_seen = set()
    for label in SUGGESTED_ATTRIBUTE_LABELS:
        normalized_label = normalize_attribute_label(label)
        if normalized_label and normalized_label not in base_seen:
            base_options.append(normalized_label)
            base_seen.add(normalized_label)
    if project is not None:
        for label in get_project_custom_attribute_labels(project):
            if label not in base_seen:
                base_options.append(label)
                base_seen.add(label)
    for label in extra_labels or []:
        normalized_label = normalize_attribute_label(label)
        if normalized_label and normalized_label not in base_seen:
            base_options.append(normalized_label)
            base_seen.add(normalized_label)

    options = [ATTRIBUTE_LABEL_UNASSIGNED]
    seen = {ATTRIBUTE_LABEL_UNASSIGNED}
    if project is not None:
        for label in get_frequent_attribute_labels(project, available_labels=base_options):
            if label not in seen:
                options.append(label)
                seen.add(label)
    for label in base_options:
        if label not in seen:
            options.append(label)
            seen.add(label)
    return options

def _normalize_metadata_key(value: Any) -> str:
    normalized = re.sub(r"\s+", "_", str(value or "").strip().lower())
    normalized = re.sub(r"[^a-z0-9_:-]+", "_", normalized).strip("_")
    return normalized

def normalize_attribute_group_name(name: Any) -> str:
    return _normalize_metadata_key(name)

def normalize_attribute_slot(slot: Any) -> str:
    return _normalize_metadata_key(slot)

def _node_attribute_key_from_token(token: Any) -> str:
    token_text = str(token or "").strip()
    if not token_text:
        return ""
    metadata = extract_node_metadata(token_text)
    base_word = str(metadata.get("base_word") or token_text).strip().lower()
    return re.sub(r"\s+", " ", base_word)

def get_node_attribute_key(project: Project, node_or_id: Any) -> str:
    node = node_or_id
    if isinstance(node_or_id, str):
        node = getattr(project, "nodes", {}).get(node_or_id)
    if not node:
        return ""
    for token in (
        getattr(node, "display", ""),
        getattr(node, "word", ""),
        getattr(node, "original", ""),
    ):
        key = _node_attribute_key_from_token(token)
        if key:
            return key
    return ""

def get_node_attribute_labels(project: Project) -> Dict[str, str]:
    if not hasattr(project, "node_attribute_labels") or project.node_attribute_labels is None:
        project.node_attribute_labels = {}
    normalized = {}
    for key, label in (project.node_attribute_labels or {}).items():
        token_key = _node_attribute_key_from_token(key)
        normalized_label = normalize_attribute_label(label)
        if token_key and normalized_label != ATTRIBUTE_LABEL_UNASSIGNED:
            normalized[token_key] = normalized_label
    project.node_attribute_labels = normalized
    return project.node_attribute_labels

def get_node_attribute_label(project: Project, node_or_id: Any) -> str:
    key = get_node_attribute_key(project, node_or_id)
    if not key:
        return ATTRIBUTE_LABEL_UNASSIGNED
    return get_node_attribute_labels(project).get(key, ATTRIBUTE_LABEL_UNASSIGNED)

def get_token_attribute_key(token: Any) -> str:
    return _node_attribute_key_from_token(token)

def get_token_attribute_label(project: Project, token: Any) -> str:
    key = get_token_attribute_key(token)
    if not key:
        return ATTRIBUTE_LABEL_UNASSIGNED
    return get_node_attribute_labels(project).get(key, ATTRIBUTE_LABEL_UNASSIGNED)

def set_node_attribute_label(project: Project, selected_node_ids: List[str], label: Any) -> List[str]:
    normalized_label = normalize_attribute_label(label)
    labels = get_node_attribute_labels(project)
    changed_keys = []
    seen_keys = set()
    for node_id in selected_node_ids or []:
        key = get_node_attribute_key(project, node_id)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        previous = labels.get(key, ATTRIBUTE_LABEL_UNASSIGNED)
        if normalized_label == ATTRIBUTE_LABEL_UNASSIGNED:
            if key in labels:
                labels.pop(key, None)
                changed_keys.append(key)
            continue
        if previous != normalized_label:
            labels[key] = normalized_label
            changed_keys.append(key)
    return changed_keys

def set_token_attribute_label(project: Project, token_key_or_text: Any, label: Any) -> List[str]:
    token_key = get_token_attribute_key(token_key_or_text)
    if not token_key:
        return []
    normalized_label = normalize_attribute_label(label)
    labels = get_node_attribute_labels(project)
    previous = labels.get(token_key, ATTRIBUTE_LABEL_UNASSIGNED)
    if normalized_label == ATTRIBUTE_LABEL_UNASSIGNED:
        if token_key in labels:
            labels.pop(token_key, None)
            return [token_key]
        return []
    if previous != normalized_label:
        labels[token_key] = normalized_label
        return [token_key]
    return []

def get_project_attribute_groups(project: Project) -> Dict[str, Dict[str, Any]]:
    if not hasattr(project, "attribute_groups") or project.attribute_groups is None:
        project.attribute_groups = {}
    normalized = {}
    for raw_key, raw_group in (project.attribute_groups or {}).items():
        if not isinstance(raw_group, dict):
            continue
        group_name = str(raw_group.get("name") or raw_key or "").strip()
        group_key = normalize_attribute_group_name(group_name or raw_key)
        slot = normalize_attribute_slot(raw_group.get("slot"))
        if not group_key or not slot:
            continue
        tokens = []
        seen_tokens = set()
        for token in raw_group.get("tokens", []) or []:
            token_key = get_token_attribute_key(token)
            if not token_key or token_key in seen_tokens:
                continue
            seen_tokens.add(token_key)
            tokens.append(token_key)
        negative_tags = _normalize_attribute_group_tag_list(raw_group.get("negative_tags", []))
        negative_when_disabled = _normalize_attribute_group_tag_list(raw_group.get("negative_when_disabled", []))
        normalized_group = copy.deepcopy(raw_group)
        normalized_group.update({
            "name": group_name or group_key,
            "slot": slot,
            "tokens": tokens,
            "created_from": str(raw_group.get("created_from") or "unknown"),
            "negative_tags": negative_tags,
            "negative_when_disabled": negative_when_disabled,
            "negative_notes": str(raw_group.get("negative_notes") or "").strip(),
        })
        normalized[group_key] = normalized_group
    project.attribute_groups = normalized
    return project.attribute_groups

def _normalize_attribute_group_tag_list(value: Any) -> List[str]:
    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []
    tags = []
    seen = set()
    for candidate in candidates:
        tag = str(candidate or "").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags

def create_attribute_group(
    project: Project,
    group_name: str,
    slot: str,
    selected_node_ids: List[str],
) -> Optional[str]:
    group_key = normalize_attribute_group_name(group_name)
    normalized_slot = normalize_attribute_slot(slot)
    if not group_key or not normalized_slot:
        return None
    groups = get_project_attribute_groups(project)
    if group_key in groups:
        return None
    tokens = []
    seen_tokens = set()
    for node_id in selected_node_ids or []:
        token_key = get_node_attribute_key(project, node_id)
        if not token_key or token_key in seen_tokens:
            continue
        seen_tokens.add(token_key)
        tokens.append(token_key)
    if not tokens:
        return None
    groups[group_key] = {
        "name": str(group_name or "").strip(),
        "slot": normalized_slot,
        "tokens": tokens,
        "created_from": "promptcloud_selection",
        "negative_tags": [],
        "negative_when_disabled": [],
        "negative_notes": "",
    }
    return group_key

def rename_attribute_group(project: Project, old_group_key: str, new_group_name: str) -> Optional[str]:
    group_key = normalize_attribute_group_name(old_group_key)
    new_group_key = normalize_attribute_group_name(new_group_name)
    if not group_key or not new_group_key:
        return None
    groups = get_project_attribute_groups(project)
    if group_key not in groups:
        return None
    if new_group_key != group_key and new_group_key in groups:
        return None
    group = dict(groups[group_key])
    group["name"] = str(new_group_name or "").strip()
    if new_group_key != group_key:
        groups.pop(group_key, None)
    groups[new_group_key] = group
    return new_group_key

def set_attribute_group_slot(project: Project, group_key: str, slot: str) -> bool:
    normalized_group_key = normalize_attribute_group_name(group_key)
    normalized_slot = normalize_attribute_slot(slot)
    if not normalized_group_key or not normalized_slot:
        return False
    groups = get_project_attribute_groups(project)
    group = groups.get(normalized_group_key)
    if not group:
        return False
    group["slot"] = normalized_slot
    return True

def set_attribute_group_tokens(project: Project, group_key: str, tokens: List[str]) -> bool:
    normalized_group_key = normalize_attribute_group_name(group_key)
    if not normalized_group_key:
        return False
    groups = get_project_attribute_groups(project)
    group = groups.get(normalized_group_key)
    if not group:
        return False
    normalized_tokens = []
    seen_tokens = set()
    for token in tokens or []:
        token_key = get_token_attribute_key(token)
        if not token_key or token_key in seen_tokens:
            continue
        seen_tokens.add(token_key)
        normalized_tokens.append(token_key)
    if not normalized_tokens:
        return False
    group["tokens"] = normalized_tokens
    return True

def set_attribute_group_negative_metadata(
    project: Project,
    group_key: str,
    negative_tags: List[str],
    negative_when_disabled: List[str],
    negative_notes: str = "",
) -> bool:
    normalized_group_key = normalize_attribute_group_name(group_key)
    if not normalized_group_key:
        return False
    groups = get_project_attribute_groups(project)
    group = groups.get(normalized_group_key)
    if not group:
        return False
    group["negative_tags"] = _normalize_attribute_group_tag_list(negative_tags)
    group["negative_when_disabled"] = _normalize_attribute_group_tag_list(negative_when_disabled)
    group["negative_notes"] = str(negative_notes or "").strip()
    return True

def _split_negative_preview_tokens(text: str) -> List[str]:
    tokens = []
    seen = set()
    for token in str(text or "").split(","):
        cleaned = token.strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        tokens.append(cleaned)
    return tokens

def _line_preview_label(line) -> str:
    name = str(getattr(line, "original_file_name", "") or "").strip()
    line_id = str(getattr(line, "id", "") or "").strip()
    if name and line_id:
        return f"{name} ({line_id})"
    return name or line_id or "Prompt line"

def build_attribute_group_negative_preview(project: Project, group_key: str, line) -> Dict[str, Any]:
    groups = get_project_attribute_groups(project)
    normalized_group_key = normalize_attribute_group_name(group_key)
    group = groups.get(normalized_group_key) if normalized_group_key else None
    if not group or line is None:
        return {}

    group_tokens = list(group.get("tokens", []) or [])
    line_tokens = get_display_tokens(line)
    line_token_by_key = {}
    for token in line_tokens:
        token_key = get_token_attribute_key(token)
        if token_key and token_key not in line_token_by_key:
            line_token_by_key[token_key] = token

    found_positive_tokens = []
    missing_positive_tokens = []
    for token in group_tokens:
        token_key = get_token_attribute_key(token)
        if token_key in line_token_by_key:
            found_positive_tokens.append(line_token_by_key[token_key])
        else:
            missing_positive_tokens.append(token)

    negative_tags = _normalize_attribute_group_tag_list(group.get("negative_tags", []))
    negative_when_disabled = _normalize_attribute_group_tag_list(group.get("negative_when_disabled", []))
    existing_negative_tokens = _split_negative_preview_tokens(getattr(line, "negative_prompt", "") or "")
    existing_keys = {token.casefold() for token in existing_negative_tokens}
    new_negative_tokens = [
        token for token in negative_when_disabled
        if token.casefold() not in existing_keys
    ]
    effective_negative_tokens = existing_negative_tokens + new_negative_tokens

    return {
        "line_id": str(getattr(line, "id", "") or ""),
        "line_label": _line_preview_label(line),
        "group_key": normalized_group_key,
        "group_name": group.get("name", normalized_group_key),
        "group_tokens": group_tokens,
        "found_positive_tokens": found_positive_tokens,
        "missing_positive_tokens": missing_positive_tokens,
        "negative_tags": negative_tags,
        "negative_when_disabled": negative_when_disabled,
        "negative_notes": str(group.get("negative_notes") or "").strip(),
        "existing_negative_tokens": existing_negative_tokens,
        "new_negative_tokens": new_negative_tokens,
        "effective_negative_preview": ", ".join(effective_negative_tokens),
    }

def add_nodes_to_attribute_group(project: Project, group_key: str, selected_node_ids: List[str]) -> int:
    normalized_group_key = normalize_attribute_group_name(group_key)
    if not normalized_group_key:
        return 0
    groups = get_project_attribute_groups(project)
    group = groups.get(normalized_group_key)
    if not group:
        return 0
    tokens = list(group.get("tokens", []) or [])
    seen_tokens = {get_token_attribute_key(token) for token in tokens}
    added_count = 0
    for node_id in selected_node_ids or []:
        token_key = get_node_attribute_key(project, node_id)
        if not token_key or token_key in seen_tokens:
            continue
        seen_tokens.add(token_key)
        tokens.append(token_key)
        added_count += 1
    if added_count:
        group["tokens"] = tokens
    return added_count

def delete_attribute_group(project: Project, group_key: str) -> bool:
    normalized_group_key = normalize_attribute_group_name(group_key)
    if not normalized_group_key:
        return False
    groups = get_project_attribute_groups(project)
    if normalized_group_key not in groups:
        return False
    groups.pop(normalized_group_key, None)
    return True

def get_attribute_group_rows(project: Project, group_name: str) -> List[Dict[str, str]]:
    group_key = normalize_attribute_group_name(group_name)
    group = get_project_attribute_groups(project).get(group_key)
    if not group:
        return []
    rows = []
    for token in group.get("tokens", []) or []:
        rows.append({
            "token": token,
            "attribute_label": get_token_attribute_label(project, token),
            "token_key": get_token_attribute_key(token),
        })
    return rows

def _module_rule_tokens(module_body: str) -> List[str]:
    tokens = []
    seen_bases = set()
    for token in parse_prompt(module_body or ""):
        if is_structural_mod_marker(token):
            continue
        token_text = str(token).strip()
        if not token_text:
            continue
        token_base = _token_match_key(token_text)
        if not token_base or token_base in seen_bases:
            continue
        seen_bases.add(token_base)
        tokens.append(token_text)
    return tokens

def _normalize_module_rule_tokens(tokens: Optional[List[str]]) -> List[str]:
    normalized = []
    seen_bases = set()
    for token in tokens or []:
        token_text = str(token).strip()
        if not token_text:
            continue
        token_base = _token_match_key(token_text)
        if not token_base or token_base in seen_bases:
            continue
        seen_bases.add(token_base)
        normalized.append(token_text)
    return normalized

def normalize_global_module_category(category: Any) -> str:
    clean_category = str(category or "").strip()
    if clean_category in GLOBAL_MODULE_CATEGORIES:
        return clean_category
    return DEFAULT_GLOBAL_MODULE_CATEGORY


def _normalize_module_attribute_groups(value: Any) -> Dict[str, Dict[str, Any]]:
    normalized = {}
    if not isinstance(value, dict):
        return normalized
    for raw_key, raw_group in value.items():
        if not isinstance(raw_group, dict):
            continue
        group_name = str(raw_group.get("name") or raw_key or "").strip()
        group_key = normalize_attribute_group_name(group_name or raw_key)
        if not group_key:
            continue
        tokens = []
        seen_tokens = set()
        for token in raw_group.get("tokens", []) or []:
            token_text = str(token or "").strip()
            token_key = get_token_attribute_key(token_text)
            if not token_text or not token_key or token_key in seen_tokens:
                continue
            seen_tokens.add(token_key)
            tokens.append(token_text)
        if not tokens:
            continue
        normalized[group_key] = {
            "name": group_name or group_key,
            "tokens": tokens,
            "core_tokens": _normalize_module_rule_tokens(raw_group.get("core_tokens")),
            "created_from": str(raw_group.get("created_from") or "unknown"),
            "source_module": str(raw_group.get("source_module") or "").strip(),
            "source_category": str(raw_group.get("source_category") or "").strip(),
        }
    return normalized

def _clamp_module_min_match(value: Any, module_tokens: List[str]) -> int:
    max_tokens = len(module_tokens)
    if max_tokens <= 0:
        return 0
    try:
        min_match = int(value)
    except (TypeError, ValueError):
        min_match = max_tokens
    return max(1, min(min_match, max_tokens))

def _default_module_core_tokens(module_body: str) -> List[str]:
    module_tokens = _module_rule_tokens(module_body)
    return module_tokens[:1]

def _default_module_min_match_tokens(module_body: str) -> int:
    return len(_module_rule_tokens(module_body))

def _token_match_key(token: str) -> str:
    metadata = extract_node_metadata(token or "")
    return str(metadata.get("base_word") or token or "").strip().lower()

def _line_display_id(line) -> str:
    file_name = getattr(line, "original_file_name", "") or "line"
    line_number = getattr(line, "original_index", 0) + 1
    return f"{file_name}:{line_number}"

def _rebuild_text(line):
    line.current_text = ", ".join(line.tokens)
    line.edited = True

def _line_in_targets(line, target_line_ids: List[str] = None) -> bool:
    return (
        not line.deleted
        and not _is_special_gallery_line(line)
        and (target_line_ids is None or line.id in target_line_ids)
    )

def get_project_line_groups(project: Project) -> Dict[str, List[str]]:
    if not hasattr(project, "line_groups") or project.line_groups is None:
        project.line_groups = {}
    return project.line_groups

def normalize_module_library(project_or_library) -> Dict[str, Dict[str, Any]]:
    library = project_or_library
    if hasattr(project_or_library, "module_library"):
        if project_or_library.module_library is None:
            project_or_library.module_library = {}
        library = project_or_library.module_library

    normalized = {}
    for name, entry in (library or {}).items():
        module_name = str(name)
        if isinstance(entry, dict):
            normalized_entry = dict(entry)
            body = str(entry.get("body", ""))
            module_type = str(entry.get("type", DEFAULT_MODULE_TYPE) or DEFAULT_MODULE_TYPE)
        else:
            normalized_entry = {}
            body = str(entry)
            module_type = DEFAULT_MODULE_TYPE
        if module_type not in MODULE_TYPES:
            module_type = DEFAULT_MODULE_TYPE
        graph = normalize_module_graph(module_name, normalized_entry if isinstance(entry, dict) else body, module_type)
        graph_errors = validate_module_graph(graph)
        if graph_errors:
            logger.warning(f"Invalid module graph for {module_name}: {'; '.join(graph_errors)}")
            graph = create_blank_module_graph(module_name, body, module_type)
        if not body:
            body = ", ".join(flatten_module_graph_to_tokens(graph))
        module_tokens = _module_rule_tokens(body)
        core_tokens = _normalize_module_rule_tokens(normalized_entry.get("core_tokens"))
        if not core_tokens:
            core_tokens = module_tokens[:1]
        normalized_entry["body"] = body
        normalized_entry["type"] = module_type
        normalized_entry["category"] = normalize_global_module_category(normalized_entry.get("category"))
        normalized_entry["graph"] = graph
        normalized_entry["core_tokens"] = core_tokens
        normalized_entry["attribute_groups"] = _normalize_module_attribute_groups(
            normalized_entry.get("attribute_groups")
        )
        normalized_entry["min_match_tokens"] = _clamp_module_min_match(
            normalized_entry.get("min_match_tokens", len(module_tokens)),
            module_tokens,
        )
        normalized[module_name] = normalized_entry

    if hasattr(project_or_library, "module_library"):
        project_or_library.module_library = normalized
    return normalized

def get_project_module_library(project: Project) -> Dict[str, Dict[str, Any]]:
    if not hasattr(project, "module_library") or project.module_library is None:
        project.module_library = {}
    return normalize_module_library(project)

def get_module_body(project_or_library, module_name: str) -> str:
    entry = normalize_module_library(project_or_library).get(module_name, {})
    graph = entry.get("graph")
    if isinstance(graph, dict):
        return ", ".join(flatten_module_graph_to_tokens(graph))
    return entry.get("body", "")

def get_module_attribute_rows(project: Project, module_name: str) -> List[Dict[str, str]]:
    module_library = get_project_module_library(project)
    if module_name not in module_library:
        return []
    module_body = get_module_body(module_library, module_name)
    rows = []
    for token in parse_prompt(module_body or ""):
        token_text = str(token).strip()
        if not token_text:
            continue
        token_key = get_token_attribute_key(token_text)
        rows.append({
            "token": token_text,
            "attribute_label": get_token_attribute_label(project, token_text),
            "token_key": token_key,
        })
    return rows

def get_module_type(project_or_library, module_name: str) -> str:
    return normalize_module_library(project_or_library).get(module_name, {}).get("type", DEFAULT_MODULE_TYPE)

def get_module_category(project_or_library, module_name: str) -> str:
    return normalize_global_module_category(
        normalize_module_library(project_or_library).get(module_name, {}).get("category")
    )

def get_module_core_tokens(project_or_library, module_name: str) -> List[str]:
    entry = normalize_module_library(project_or_library).get(module_name, {})
    body = get_module_body(project_or_library, module_name)
    return _normalize_module_rule_tokens(entry.get("core_tokens")) or _default_module_core_tokens(body)

def get_module_min_match_tokens(project_or_library, module_name: str) -> int:
    entry = normalize_module_library(project_or_library).get(module_name, {})
    body = get_module_body(project_or_library, module_name)
    module_tokens = _module_rule_tokens(body)
    return _clamp_module_min_match(
        entry.get("min_match_tokens", _default_module_min_match_tokens(body)),
        module_tokens,
    )

def set_module_candidate_rules(
    project: Project,
    module_name: str,
    core_tokens: List[str],
    min_match_tokens: int,
) -> bool:
    library = get_project_module_library(project)
    if module_name not in library:
        return False
    body = get_module_body(library, module_name)
    module_tokens = _module_rule_tokens(body)
    library[module_name]["core_tokens"] = _normalize_module_rule_tokens(core_tokens) or module_tokens[:1]
    library[module_name]["min_match_tokens"] = _clamp_module_min_match(min_match_tokens, module_tokens)
    return True

def preview_module_candidates(
    project: Project,
    module_name: str,
    core_tokens: Optional[List[str]] = None,
    min_match_tokens: Optional[int] = None,
    example_limit: int = 50,
) -> Dict[str, Any]:
    module_body = get_module_body(project, module_name)
    module_tokens = _module_rule_tokens(module_body)
    if not module_tokens:
        return {
            "module_name": module_name,
            "module_tokens": [],
            "core_tokens": [],
            "min_match_tokens": 0,
            "total_candidate_count": 0,
            "examples": [],
        }
    configured_core_tokens = (
        _normalize_module_rule_tokens(core_tokens)
        if core_tokens is not None
        else get_module_core_tokens(project, module_name)
    )
    if not configured_core_tokens:
        configured_core_tokens = module_tokens[:1]
    configured_min_match = _clamp_module_min_match(
        min_match_tokens if min_match_tokens is not None else get_module_min_match_tokens(project, module_name),
        module_tokens,
    )
    module_token_keys = {_token_match_key(token): token for token in module_tokens}
    core_keys = {_token_match_key(token) for token in configured_core_tokens if _token_match_key(token)}

    examples = []
    total_candidate_count = 0
    for line in getattr(project, "prompt_lines", []):
        if getattr(line, "deleted", False):
            continue
        line_keys = {
            _token_match_key(token)
            for token in getattr(line, "tokens", [])
            if not is_structural_mod_marker(token) and _token_match_key(token)
        }
        if core_keys and not core_keys.issubset(line_keys):
            continue

        matched_tokens = [
            token
            for key, token in module_token_keys.items()
            if key in line_keys
        ]
        missing_tokens = [
            token
            for key, token in module_token_keys.items()
            if key not in line_keys
        ]
        matched_count = len(matched_tokens)
        total_token_count = len(module_tokens)
        if matched_count < configured_min_match:
            continue

        total_candidate_count += 1
        if len(examples) >= example_limit:
            continue
        examples.append({
            "line_id": getattr(line, "id", ""),
            "display_id": _line_display_id(line),
            "file": getattr(line, "original_file_name", ""),
            "line_number": getattr(line, "original_index", 0) + 1,
            "matched_tokens": matched_tokens,
            "missing_tokens": missing_tokens,
            "matched_count": matched_count,
            "total_token_count": total_token_count,
            "match_ratio": (matched_count / total_token_count) if total_token_count else 0,
            "text": getattr(line, "current_text", ""),
        })

    return {
        "module_name": module_name,
        "module_tokens": module_tokens,
        "core_tokens": configured_core_tokens,
        "min_match_tokens": configured_min_match,
        "total_candidate_count": total_candidate_count,
        "examples": examples,
    }

def scan_global_module_candidates(
    project: Project,
    global_module_library: Dict[str, Any],
    min_core_match_lines: int = 1,
    example_limit: int = 3,
) -> Dict[str, Any]:
    global_library = normalize_module_library(global_module_library or {})
    project_library = get_project_module_library(project)
    try:
        min_core_match_lines = max(0, int(min_core_match_lines))
    except (TypeError, ValueError):
        min_core_match_lines = 1

    lines = [
        line
        for line in getattr(project, "prompt_lines", [])
        if not getattr(line, "deleted", False)
    ]
    line_rows = []
    for line in lines:
        tokens = getattr(line, "tokens", None) or parse_prompt(getattr(line, "current_text", "") or "")
        token_keys = {
            _token_match_key(token)
            for token in tokens
            if not is_structural_mod_marker(token) and _token_match_key(token)
        }
        line_rows.append((line, token_keys))

    results = []
    skipped_empty_count = 0
    below_threshold_count = 0
    for module_name in sorted(global_library, key=str.casefold):
        module_body = get_module_body(global_library, module_name)
        module_tokens = _module_rule_tokens(module_body)
        if not module_tokens:
            skipped_empty_count += 1
            continue

        module_token_by_key = {
            _token_match_key(token): token
            for token in module_tokens
            if _token_match_key(token)
        }
        module_keys = list(module_token_by_key.keys())
        core_tokens = get_module_core_tokens(global_library, module_name)
        core_keys = {
            _token_match_key(token)
            for token in core_tokens
            if _token_match_key(token)
        }
        if not core_keys and module_keys:
            core_keys = {module_keys[0]}
            core_tokens = [module_token_by_key[module_keys[0]]]

        core_match_line_count = 0
        token_match_line_count = 0
        ratio_sum = 0.0
        best_match_ratio = 0.0
        additional_token_match_count = 0
        examples = []
        for line, line_keys in line_rows:
            matched_keys = [key for key in module_keys if key in line_keys]
            if not matched_keys:
                continue

            token_match_line_count += 1
            match_ratio = len(matched_keys) / len(module_keys) if module_keys else 0.0
            ratio_sum += match_ratio
            best_match_ratio = max(best_match_ratio, match_ratio)
            core_match = bool(core_keys and core_keys.issubset(line_keys))
            if core_match:
                core_match_line_count += 1
                additional_token_match_count += sum(1 for key in matched_keys if key not in core_keys)

            if core_match and len(examples) < example_limit:
                missing_keys = [key for key in module_keys if key not in line_keys]
                examples.append({
                    "line_id": getattr(line, "id", ""),
                    "display_id": _line_display_id(line),
                    "file": getattr(line, "original_file_name", ""),
                    "line_number": getattr(line, "original_index", 0) + 1,
                    "line_index": getattr(line, "current_index", getattr(line, "original_index", 0)),
                    "matched_tokens": [module_token_by_key[key] for key in matched_keys],
                    "missing_tokens": [module_token_by_key[key] for key in missing_keys],
                    "match_ratio": match_ratio,
                    "prompt_preview": getattr(line, "current_text", "") or "",
                })

        average_match_ratio = (
            ratio_sum / token_match_line_count
            if token_match_line_count
            else 0.0
        )
        if core_match_line_count < min_core_match_lines:
            below_threshold_count += 1
            continue
        results.append({
            "module_name": module_name,
            "module_type": get_module_type(global_library, module_name),
            "module_tokens": module_tokens,
            "core_tokens": core_tokens,
            "core_match_line_count": core_match_line_count,
            "token_match_line_count": token_match_line_count,
            "average_match_ratio": average_match_ratio,
            "best_match_ratio": best_match_ratio,
            "additional_token_match_count": additional_token_match_count,
            "already_present": module_name in project_library,
            "examples": examples,
        })

    results.sort(
        key=lambda row: (
            -row["core_match_line_count"],
            -row["best_match_ratio"],
            str(row["module_name"]).casefold(),
        )
    )
    return {
        "scanned_module_count": len(global_library),
        "result_count": len(results),
        "skipped_empty_count": skipped_empty_count,
        "below_threshold_count": below_threshold_count,
        "line_count": len(lines),
        "min_core_match_lines": min_core_match_lines,
        "results": results,
    }

def import_global_modules_to_project(
    project: Project,
    global_module_library: Dict[str, Any],
    module_names: List[str],
    overwrite: bool = False,
) -> Dict[str, Any]:
    global_library = normalize_module_library(global_module_library or {})
    project_library = get_project_module_library(project)
    imported = []
    skipped_existing = []
    skipped_missing = []
    for module_name in module_names or []:
        name = str(module_name or "").strip()
        if not name or name not in global_library:
            if name:
                skipped_missing.append(name)
            continue
        if name in project_library and not overwrite:
            skipped_existing.append(name)
            continue
        project_library[name] = copy.deepcopy(global_library[name])
        imported.append(name)
    normalize_module_library(project)
    return {
        "imported": imported,
        "skipped_existing": skipped_existing,
        "skipped_missing": skipped_missing,
    }

def _replace_module_candidate_tokens_in_text(
    text: str,
    module_reference: str,
    module_tokens: List[str],
) -> tuple[str, bool, bool, bool]:
    tokens = _parse_prompt_for_module_preset(text or "")
    if any(extract_mod_info(token)["type"] in ("open", "close") for token in tokens):
        return text, False, False, True
    if module_reference in [token.strip() for token in tokens]:
        return text, False, True, False

    module_token_keys = {_token_match_key(token) for token in module_tokens if _token_match_key(token)}
    if not module_token_keys:
        return text, False, False, False

    result_tokens = []
    replaced_any = False
    inserted_reference = False
    for token in tokens:
        info = extract_mod_info(token)
        token_key = _token_match_key(token)
        if info["type"] not in ("inline", "open", "close") and token_key in module_token_keys:
            if not inserted_reference:
                result_tokens.append(module_reference)
                inserted_reference = True
            replaced_any = True
            continue
        result_tokens.append(token)

    if not replaced_any:
        return text, False, False, False
    return ", ".join(result_tokens), True, False, False

def preview_apply_module_candidates(
    project: Project,
    module_name: str,
    core_tokens: Optional[List[str]] = None,
    min_match_tokens: Optional[int] = None,
    example_limit: int = 50,
) -> Dict[str, Any]:
    candidate_preview = preview_module_candidates(
        project,
        module_name,
        core_tokens=core_tokens,
        min_match_tokens=min_match_tokens,
        example_limit=1000000,
    )
    module_reference = build_module_reference_token(module_name)
    line_lookup = {
        getattr(line, "id", ""): line
        for line in getattr(project, "prompt_lines", [])
        if not getattr(line, "deleted", False)
    }
    affected_line_count = 0
    skipped_existing_reference_count = 0
    skipped_existing_module_block_count = 0
    examples = []

    for candidate in candidate_preview["examples"]:
        line = line_lookup.get(candidate["line_id"])
        if not line:
            continue
        before = getattr(line, "current_text", "")
        after, changed, skipped_existing_reference, skipped_existing_module_block = _replace_module_candidate_tokens_in_text(
            before,
            module_reference,
            candidate_preview["module_tokens"],
        )
        if skipped_existing_module_block:
            skipped_existing_module_block_count += 1
            continue
        if skipped_existing_reference:
            skipped_existing_reference_count += 1
            continue
        if not changed or after == before:
            continue

        affected_line_count += 1
        if len(examples) >= example_limit:
            continue
        examples.append({
            "line_id": candidate["line_id"],
            "display_id": candidate["display_id"],
            "file": candidate["file"],
            "line_number": candidate["line_number"],
            "before": before,
            "after": after,
            "matched_tokens": candidate["matched_tokens"],
            "missing_tokens": candidate["missing_tokens"],
            "matched_count": candidate["matched_count"],
            "total_token_count": candidate["total_token_count"],
            "match_ratio": candidate["match_ratio"],
        })

    return {
        "module_name": module_name,
        "module_reference": module_reference,
        "module_tokens": candidate_preview["module_tokens"],
        "core_tokens": candidate_preview["core_tokens"],
        "min_match_tokens": candidate_preview["min_match_tokens"],
        "candidate_line_count": candidate_preview["total_candidate_count"],
        "affected_line_count": affected_line_count,
        "skipped_existing_reference_count": skipped_existing_reference_count,
        "skipped_existing_module_block_count": skipped_existing_module_block_count,
        "examples": examples,
    }

def apply_module_candidates(
    project: Project,
    module_name: str,
    core_tokens: Optional[List[str]] = None,
    min_match_tokens: Optional[int] = None,
) -> Project:
    apply_preview = preview_apply_module_candidates(
        project,
        module_name,
        core_tokens=core_tokens,
        min_match_tokens=min_match_tokens,
        example_limit=1000000,
    )
    if apply_preview["affected_line_count"] == 0:
        return project

    line_lookup = {
        getattr(line, "id", ""): line
        for line in getattr(project, "prompt_lines", [])
        if not getattr(line, "deleted", False)
    }
    changed_any = False
    for example in apply_preview["examples"]:
        line = line_lookup.get(example["line_id"])
        if not line:
            continue
        line.current_text = example["after"]
        line.tokens = _parse_prompt_for_module_preset(example["after"])
        line.edited = True
        changed_any = True

    if changed_any:
        return build_graph(project)
    return project

def _module_reference_replacement_preview(
    text: str,
    module_reference: str,
    module_tokens: List[str],
) -> Dict[str, Any]:
    tokens = _parse_prompt_for_module_preset(text or "")
    if any(extract_mod_info(token)["type"] in ("open", "close") for token in tokens):
        return {
            "after": text,
            "changed": False,
            "skipped_existing_reference": False,
            "skipped_existing_module_block": True,
            "removed_tokens": [],
        }
    if module_reference in [token.strip() for token in tokens]:
        return {
            "after": text,
            "changed": False,
            "skipped_existing_reference": True,
            "skipped_existing_module_block": False,
            "removed_tokens": [],
        }

    module_token_keys = {_token_match_key(token) for token in module_tokens if _token_match_key(token)}
    if not module_token_keys:
        return {
            "after": text,
            "changed": False,
            "skipped_existing_reference": False,
            "skipped_existing_module_block": False,
            "removed_tokens": [],
        }

    result_tokens = []
    removed_tokens = []
    inserted_reference = False
    for token in tokens:
        info = extract_mod_info(token)
        token_key = _token_match_key(token)
        if info["type"] not in ("inline", "open", "close") and token_key in module_token_keys:
            if not inserted_reference:
                result_tokens.append(module_reference)
                inserted_reference = True
            removed_tokens.append(token)
            continue
        result_tokens.append(token)

    if not removed_tokens:
        return {
            "after": text,
            "changed": False,
            "skipped_existing_reference": False,
            "skipped_existing_module_block": False,
            "removed_tokens": [],
        }
    return {
        "after": ", ".join(result_tokens),
        "changed": True,
        "skipped_existing_reference": False,
        "skipped_existing_module_block": False,
        "removed_tokens": removed_tokens,
    }

def preview_apply_detected_modules(
    project: Project,
    module_library: Dict[str, Any],
    module_names: List[str],
    min_core_match_lines: int = 1,
    example_limit: int = 50,
) -> Dict[str, Any]:
    normalized_library = normalize_module_library(module_library or {})
    selected_names = []
    seen_names = set()
    for module_name in module_names or []:
        name = str(module_name or "").strip()
        if not name or name in seen_names or name not in normalized_library:
            continue
        seen_names.add(name)
        selected_names.append(name)

    scan = scan_global_module_candidates(
        project,
        normalized_library,
        min_core_match_lines=min_core_match_lines,
        example_limit=1000000,
    )
    result_by_name = {
        result["module_name"]: result
        for result in scan["results"]
        if result["module_name"] in seen_names
    }
    line_lookup = {
        getattr(line, "id", ""): line
        for line in getattr(project, "prompt_lines", [])
        if not getattr(line, "deleted", False)
    }
    working_text_by_line_id = {
        line_id: getattr(line, "current_text", "")
        for line_id, line in line_lookup.items()
    }
    project_library = get_project_module_library(project)
    import_needed = [
        name
        for name in selected_names
        if name in normalized_library and name not in project_library
    ]

    affected_line_count = 0
    skipped_existing_reference_count = 0
    skipped_existing_module_block_count = 0
    skipped_no_change_count = 0
    affected_line_ids = set()
    examples = []
    for module_name in selected_names:
        result = result_by_name.get(module_name)
        if not result:
            continue
        module_reference = build_module_reference_token(module_name)
        module_tokens = result["module_tokens"]
        for candidate in result["examples"]:
            line_id = candidate["line_id"]
            if line_id not in working_text_by_line_id:
                continue
            before = working_text_by_line_id[line_id]
            replacement = _module_reference_replacement_preview(
                before,
                module_reference,
                module_tokens,
            )
            if replacement["skipped_existing_module_block"]:
                skipped_existing_module_block_count += 1
                continue
            if replacement["skipped_existing_reference"]:
                skipped_existing_reference_count += 1
                continue
            if not replacement["changed"] or replacement["after"] == before:
                skipped_no_change_count += 1
                continue

            working_text_by_line_id[line_id] = replacement["after"]
            affected_line_count += 1
            affected_line_ids.add(line_id)
            if len(examples) >= example_limit:
                continue
            examples.append({
                "line_id": line_id,
                "display_id": candidate["display_id"],
                "file": candidate["file"],
                "line_number": candidate["line_number"],
                "line_index": candidate["line_index"],
                "module_name": module_name,
                "module_reference": module_reference,
                "matched_tokens": candidate["matched_tokens"],
                "missing_tokens": candidate["missing_tokens"],
                "removed_tokens": replacement["removed_tokens"],
                "inserted_module_reference": module_reference,
                "match_ratio": candidate["match_ratio"],
                "before": before,
                "after": replacement["after"],
            })

    return {
        "selected_module_names": selected_names,
        "import_needed": import_needed,
        "candidate_line_count": sum(
            result_by_name[name]["core_match_line_count"]
            for name in selected_names
            if name in result_by_name
        ),
        "affected_line_count": affected_line_count,
        "affected_line_id_count": len(affected_line_ids),
        "skipped_existing_reference_count": skipped_existing_reference_count,
        "skipped_existing_module_block_count": skipped_existing_module_block_count,
        "skipped_no_change_count": skipped_no_change_count,
        "examples": examples,
    }

def apply_detected_modules(
    project: Project,
    module_library: Dict[str, Any],
    module_names: List[str],
    min_core_match_lines: int = 1,
) -> Project:
    normalized_library = normalize_module_library(module_library or {})
    preview = preview_apply_detected_modules(
        project,
        normalized_library,
        module_names,
        min_core_match_lines=min_core_match_lines,
        example_limit=1000000,
    )
    if preview["affected_line_count"] == 0:
        return project

    project_library = get_project_module_library(project)
    for module_name in preview["import_needed"]:
        if module_name in normalized_library and module_name not in project_library:
            project_library[module_name] = copy.deepcopy(normalized_library[module_name])

    line_lookup = {
        getattr(line, "id", ""): line
        for line in getattr(project, "prompt_lines", [])
        if not getattr(line, "deleted", False)
    }
    changed_any = False
    for example in preview["examples"]:
        line = line_lookup.get(example["line_id"])
        if not line:
            continue
        line.current_text = example["after"]
        line.tokens = _parse_prompt_for_module_preset(example["after"])
        line.edited = True
        changed_any = True

    if changed_any:
        normalize_module_library(project)
        return build_graph(project)
    return project

def _module_swap_empty_preview(
    source_module_name: str,
    target_module_name: str,
    match_mode: str,
    source_tokens: List[str] = None,
    target_tokens: List[str] = None,
    core_tokens: List[str] = None,
) -> Dict[str, Any]:
    return {
        "source_module_name": source_module_name,
        "target_module_name": target_module_name,
        "match_mode": match_mode,
        "source_tokens": source_tokens or [],
        "target_tokens": target_tokens or [],
        "core_tokens": core_tokens or [],
        "target_line_count": 0,
        "affected_line_count": 0,
        "skipped_no_match_count": 0,
        "skipped_same_module": bool(source_module_name and source_module_name == target_module_name),
        "examples": [],
    }

def _find_contiguous_token_span(tokens: List[str], target_keys: List[str]) -> tuple[int, int] | None:
    if not target_keys or len(target_keys) > len(tokens):
        return None
    token_keys = [
        "" if is_structural_mod_marker(token) else _token_match_key(token)
        for token in tokens
    ]
    span_len = len(target_keys)
    for start in range(0, len(token_keys) - span_len + 1):
        if token_keys[start:start + span_len] == target_keys:
            return start, start + span_len
    return None

def _dedupe_insert_tokens(insert_tokens: List[str], existing_tokens: List[str]) -> List[str]:
    existing_keys = {
        _token_match_key(token)
        for token in existing_tokens
        if not is_structural_mod_marker(token) and _token_match_key(token)
    }
    result = []
    result_keys = set()
    for token in insert_tokens:
        key = _token_match_key(token)
        if not key or key in existing_keys or key in result_keys:
            continue
        result.append(token)
        result_keys.add(key)
    return result

def _module_swap_line_preview(
    line,
    source_tokens: List[str],
    target_tokens: List[str],
    core_tokens: List[str],
    match_mode: str,
    source_module_name: str = "",
    target_module_name: str = "",
) -> Dict[str, Any] | None:
    tokens = _parse_prompt_for_module_preset(getattr(line, "current_text", "") or "")
    reference_preview = _module_reference_swap_line_preview(
        line,
        tokens,
        source_module_name,
        target_module_name,
    )
    if reference_preview:
        return reference_preview

    source_by_key = {
        _token_match_key(token): token
        for token in source_tokens
        if _token_match_key(token)
    }
    source_keys = list(source_by_key.keys())
    core_keys = {
        _token_match_key(token)
        for token in core_tokens
        if _token_match_key(token)
    }

    line_keys = {
        _token_match_key(token)
        for token in tokens
        if not is_structural_mod_marker(token) and _token_match_key(token)
    }
    matched_keys = [key for key in source_keys if key in line_keys]
    missing_keys = [key for key in source_keys if key not in line_keys]
    if not matched_keys:
        return None
    if match_mode == "strict" and core_keys and not core_keys.issubset(line_keys):
        return None

    matched_tokens = [source_by_key[key] for key in matched_keys]
    missing_tokens = [source_by_key[key] for key in missing_keys]
    matched_key_set = set(matched_keys)

    span = _find_contiguous_token_span(tokens, source_keys)
    removed_tokens = []
    if span is not None:
        start, end = span
        remaining_tokens = tokens[:start] + tokens[end:]
        removed_tokens = tokens[start:end]
        insert_at = start
    else:
        remaining_tokens = []
        insert_at = None
        for token in tokens:
            key = _token_match_key(token)
            if not is_structural_mod_marker(token) and key in matched_key_set:
                if insert_at is None:
                    insert_at = len(remaining_tokens)
                removed_tokens.append(token)
                continue
            remaining_tokens.append(token)
        if insert_at is None:
            return None

    inserted_tokens = _dedupe_insert_tokens(target_tokens, remaining_tokens)
    after_tokens = (
        remaining_tokens[:insert_at]
        + inserted_tokens
        + remaining_tokens[insert_at:]
    )
    before = getattr(line, "current_text", "") or ""
    after = ", ".join(after_tokens)
    if after == before:
        return None

    source_token_count = len(source_tokens)
    match_ratio = (len(matched_tokens) / source_token_count) if source_token_count else 0
    return {
        "line_id": getattr(line, "id", ""),
        "display_id": _line_display_id(line),
        "file": getattr(line, "original_file_name", ""),
        "line_number": getattr(line, "original_index", 0) + 1,
        "line_index": getattr(line, "current_index", getattr(line, "original_index", 0)),
        "swap_kind": "body_tokens",
        "matched_tokens": matched_tokens,
        "missing_tokens": missing_tokens,
        "removed_tokens": removed_tokens,
        "inserted_tokens": inserted_tokens,
        "removed_reference": "",
        "inserted_reference": "",
        "matched_count": len(matched_tokens),
        "total_token_count": source_token_count,
        "match_ratio": match_ratio,
        "before": before,
        "after": after,
        "after_tokens": after_tokens,
    }

def _module_reference_swap_line_preview(
    line,
    tokens: List[str],
    source_module_name: str,
    target_module_name: str,
) -> Dict[str, Any] | None:
    source_reference = build_module_reference_token(source_module_name)
    target_reference = build_module_reference_token(target_module_name)
    source_indices = [
        index
        for index, token in enumerate(tokens)
        if extract_mod_info(token)["type"] == "open"
        and extract_mod_info(token)["name"] == source_module_name
    ]
    if not source_indices:
        return None

    target_exists = any(
        extract_mod_info(token)["type"] == "open"
        and extract_mod_info(token)["name"] == target_module_name
        for token in tokens
    )
    replaced_target = False
    after_tokens = []
    removed_references = []
    inserted_references = []
    for index, token in enumerate(tokens):
        if index not in source_indices:
            after_tokens.append(token)
            continue
        removed_references.append(token)
        if target_exists or replaced_target:
            continue
        after_tokens.append(target_reference)
        inserted_references.append(target_reference)
        replaced_target = True

    before = getattr(line, "current_text", "") or ""
    after = ", ".join(after_tokens)
    if after == before:
        return None

    return {
        "line_id": getattr(line, "id", ""),
        "display_id": _line_display_id(line),
        "file": getattr(line, "original_file_name", ""),
        "line_number": getattr(line, "original_index", 0) + 1,
        "line_index": getattr(line, "current_index", getattr(line, "original_index", 0)),
        "swap_kind": "reference",
        "matched_tokens": [source_reference],
        "missing_tokens": [],
        "removed_tokens": [],
        "inserted_tokens": [],
        "removed_reference": ", ".join(removed_references),
        "inserted_reference": "" if target_exists else ", ".join(inserted_references),
        "matched_count": 1,
        "total_token_count": 1,
        "match_ratio": 1.0,
        "before": before,
        "after": after,
        "after_tokens": after_tokens,
    }

def preview_module_swap(
    project: Project,
    source_module_name: str,
    target_module_name: str,
    target_line_ids: Optional[List[str]] = None,
    match_mode: str = "strict",
    example_limit: int = 50,
) -> Dict[str, Any]:
    source_module_name = str(source_module_name or "").strip()
    target_module_name = str(target_module_name or "").strip()
    match_mode = "loose" if match_mode == "loose" else "strict"
    module_library = get_project_module_library(project)
    if (
        not source_module_name
        or not target_module_name
        or source_module_name == target_module_name
        or source_module_name not in module_library
        or target_module_name not in module_library
    ):
        return _module_swap_empty_preview(source_module_name, target_module_name, match_mode)

    source_tokens = _module_rule_tokens(get_module_body(module_library, source_module_name))
    target_tokens = _module_rule_tokens(get_module_body(module_library, target_module_name))
    core_tokens = get_module_core_tokens(module_library, source_module_name)
    if not source_tokens or not target_tokens:
        return _module_swap_empty_preview(
            source_module_name,
            target_module_name,
            match_mode,
            source_tokens=source_tokens,
            target_tokens=target_tokens,
            core_tokens=core_tokens,
        )

    target_line_set = set(target_line_ids or []) if target_line_ids is not None else None
    target_line_count = 0
    affected_line_count = 0
    skipped_no_match_count = 0
    examples = []
    for line in getattr(project, "prompt_lines", []):
        if _is_route_separator_line(line):
            continue
        if not _line_in_targets(line, target_line_set):
            continue
        target_line_count += 1
        example = _module_swap_line_preview(
            line,
            source_tokens,
            target_tokens,
            core_tokens,
            match_mode,
            source_module_name=source_module_name,
            target_module_name=target_module_name,
        )
        if not example:
            skipped_no_match_count += 1
            continue
        affected_line_count += 1
        if len(examples) < example_limit:
            examples.append(example)

    return {
        "source_module_name": source_module_name,
        "target_module_name": target_module_name,
        "match_mode": match_mode,
        "source_tokens": source_tokens,
        "target_tokens": target_tokens,
        "core_tokens": core_tokens,
        "target_line_count": target_line_count,
        "affected_line_count": affected_line_count,
        "skipped_no_match_count": skipped_no_match_count,
        "skipped_same_module": False,
        "examples": examples,
    }

def apply_module_swap(
    project: Project,
    source_module_name: str,
    target_module_name: str,
    target_line_ids: Optional[List[str]] = None,
    match_mode: str = "strict",
) -> Project:
    preview = preview_module_swap(
        project,
        source_module_name,
        target_module_name,
        target_line_ids=target_line_ids,
        match_mode=match_mode,
        example_limit=1000000,
    )
    if preview["affected_line_count"] == 0:
        return project
    line_lookup = {
        getattr(line, "id", ""): line
        for line in getattr(project, "prompt_lines", [])
        if not getattr(line, "deleted", False)
    }
    changed_any = False
    for example in preview["examples"]:
        line = line_lookup.get(example["line_id"])
        if not line:
            continue
        line.current_text = example["after"]
        line.tokens = _parse_prompt_for_module_preset(example["after"])
        line.edited = True
        changed_any = True
    if changed_any:
        return build_graph(project)
    return project

def _attribute_group_swap_empty_preview(
    from_group_key: str,
    to_group_key: str,
    require_full_match: bool = False,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "from_group_key": from_group_key,
        "to_group_key": to_group_key,
        "from_group_name": "",
        "to_group_name": "",
        "from_tokens": [],
        "to_tokens": [],
        "shared_tokens": [],
        "tokens_to_remove": [],
        "tokens_to_add": [],
        "target_line_count": 0,
        "affected_line_count": 0,
        "full_match_line_count": 0,
        "partial_match_line_count": 0,
        "no_match_line_count": 0,
        "already_present_to_tokens": [],
        "require_full_match": bool(require_full_match),
        "examples": [],
        "warnings": list(warnings or []),
    }

def _attribute_group_tokens(group: Dict[str, Any]) -> List[str]:
    tokens = []
    seen = set()
    for token in group.get("tokens", []) or []:
        token_key = get_token_attribute_key(token)
        if not token_key or token_key in seen:
            continue
        tokens.append(token_key)
        seen.add(token_key)
    return tokens

def _attribute_group_swap_line_preview(
    line,
    from_tokens: List[str],
    to_tokens: List[str],
    remove_tokens: List[str],
    add_tokens: List[str],
    require_full_match: bool = False,
) -> Dict[str, Any]:
    before = getattr(line, "current_text", "") or ""
    tokens = _parse_prompt_for_module_preset(before)
    if not tokens:
        tokens = list(getattr(line, "tokens", []) or [])
        before = ", ".join(tokens)

    line_token_keys = [get_token_attribute_key(token) for token in tokens]
    line_key_set = {token_key for token_key in line_token_keys if token_key}
    from_key_set = set(from_tokens)
    remove_key_set = set(remove_tokens)
    add_key_set = set(add_tokens)

    matched_from_tokens = [token for token in from_tokens if token in line_key_set]
    missing_from_tokens = [token for token in from_tokens if token not in line_key_set]
    matched_remove_tokens = [token for token in remove_tokens if token in line_key_set]
    already_present_to_tokens = [token for token in add_tokens if token in line_key_set]
    full_match = bool(from_tokens) and from_key_set.issubset(line_key_set)
    partial_match = bool(matched_from_tokens) and not full_match

    if require_full_match and not full_match:
        changed_tokens = list(tokens)
    elif not matched_remove_tokens:
        changed_tokens = list(tokens)
    else:
        inserted = False
        changed_tokens = []
        tokens_to_insert = [token for token in add_tokens if token not in line_key_set]
        for token, token_key in zip(tokens, line_token_keys):
            if token_key in remove_key_set:
                if not inserted:
                    changed_tokens.extend(tokens_to_insert)
                    inserted = True
                continue
            changed_tokens.append(token)
        if not inserted:
            changed_tokens.extend(tokens_to_insert)

    after = ", ".join(changed_tokens)
    changed = after != before

    return {
        "line_id": getattr(line, "id", ""),
        "display_id": _line_display_id(line),
        "file": getattr(line, "original_file_name", ""),
        "line_number": getattr(line, "original_index", 0) + 1,
        "line_index": getattr(line, "current_index", getattr(line, "original_index", 0)),
        "matched_from_tokens": matched_from_tokens,
        "missing_from_tokens": missing_from_tokens,
        "removed_tokens": matched_remove_tokens if changed else [],
        "added_tokens": [token for token in add_tokens if token not in line_key_set] if changed else [],
        "already_present_to_tokens": already_present_to_tokens,
        "full_match": full_match,
        "partial_match": partial_match,
        "changed": changed,
        "before": before,
        "after": after,
        "after_tokens": _parse_prompt_for_module_preset(after),
    }

def preview_attribute_group_swap(
    project: Project,
    from_group_key: str,
    to_group_key: str,
    target_line_ids: Optional[List[str]] = None,
    require_full_match: bool = False,
    example_limit: int = 10,
    include_unchanged_examples: bool = False,
) -> Dict[str, Any]:
    from_group_key = normalize_attribute_group_name(from_group_key)
    to_group_key = normalize_attribute_group_name(to_group_key)
    if not from_group_key or not to_group_key or from_group_key == to_group_key:
        return _attribute_group_swap_empty_preview(
            from_group_key,
            to_group_key,
            require_full_match,
            warnings=["Select two different Attribute Groups."],
        )

    groups = get_project_attribute_groups(project)
    from_group = groups.get(from_group_key)
    to_group = groups.get(to_group_key)
    if not from_group or not to_group:
        return _attribute_group_swap_empty_preview(
            from_group_key,
            to_group_key,
            require_full_match,
            warnings=["Selected Attribute Group was not found."],
        )

    from_tokens = _attribute_group_tokens(from_group)
    to_tokens = _attribute_group_tokens(to_group)
    if not from_tokens or not to_tokens:
        return _attribute_group_swap_empty_preview(
            from_group_key,
            to_group_key,
            require_full_match,
            warnings=["Both Attribute Groups need at least one token."],
        )

    from_token_set = set(from_tokens)
    to_token_set = set(to_tokens)
    shared_tokens = [token for token in from_tokens if token in to_token_set]
    remove_tokens = [token for token in from_tokens if token not in to_token_set]
    add_tokens = [token for token in to_tokens if token not in from_token_set]
    target_line_set = set(target_line_ids or []) if target_line_ids is not None else None

    target_line_count = 0
    affected_line_count = 0
    full_match_line_count = 0
    partial_match_line_count = 0
    no_match_line_count = 0
    already_present_to_tokens = []
    already_present_seen = set()
    examples = []

    for line in getattr(project, "prompt_lines", []) or []:
        if not _line_in_targets(line, target_line_set):
            continue
        target_line_count += 1
        example = _attribute_group_swap_line_preview(
            line,
            from_tokens,
            to_tokens,
            remove_tokens,
            add_tokens,
            require_full_match=require_full_match,
        )
        if example["full_match"]:
            full_match_line_count += 1
        elif example["partial_match"]:
            partial_match_line_count += 1
        else:
            no_match_line_count += 1

        if example["changed"]:
            affected_line_count += 1
            for token in example.get("already_present_to_tokens", []) or []:
                if token not in already_present_seen:
                    already_present_to_tokens.append(token)
                    already_present_seen.add(token)
        if (example["changed"] or include_unchanged_examples) and len(examples) < example_limit:
            examples.append(example)

    return {
        "from_group_key": from_group_key,
        "to_group_key": to_group_key,
        "from_group_name": from_group.get("name", from_group_key),
        "to_group_name": to_group.get("name", to_group_key),
        "from_tokens": from_tokens,
        "to_tokens": to_tokens,
        "shared_tokens": shared_tokens,
        "tokens_to_remove": remove_tokens,
        "tokens_to_add": add_tokens,
        "target_line_count": target_line_count,
        "affected_line_count": affected_line_count,
        "full_match_line_count": full_match_line_count,
        "partial_match_line_count": partial_match_line_count,
        "no_match_line_count": no_match_line_count,
        "already_present_to_tokens": already_present_to_tokens,
        "require_full_match": bool(require_full_match),
        "examples": examples,
        "warnings": [],
    }

def apply_attribute_group_swap(
    project: Project,
    from_group_key: str,
    to_group_key: str,
    target_line_ids: Optional[List[str]] = None,
    require_full_match: bool = False,
) -> Project:
    preview = preview_attribute_group_swap(
        project,
        from_group_key,
        to_group_key,
        target_line_ids=target_line_ids,
        require_full_match=require_full_match,
        example_limit=1000000,
    )
    if preview["affected_line_count"] == 0:
        return project

    line_lookup = {
        getattr(line, "id", ""): line
        for line in getattr(project, "prompt_lines", []) or []
        if not getattr(line, "deleted", False) and not _is_special_gallery_line(line)
    }
    changed_any = False
    for example in preview["examples"]:
        line = line_lookup.get(example["line_id"])
        if not line or not example.get("changed"):
            continue
        line.current_text = example["after"]
        line.tokens = _parse_prompt_for_module_preset(example["after"])
        line.edited = True
        changed_any = True
    if changed_any:
        return build_graph(project)
    return project

def _normalize_attribute_token_list(tokens: List[Any]) -> List[str]:
    normalized_tokens = []
    seen_tokens = set()
    for token in tokens or []:
        token_key = get_token_attribute_key(token)
        if not token_key or token_key in seen_tokens:
            continue
        normalized_tokens.append(token_key)
        seen_tokens.add(token_key)
    return normalized_tokens

def _propagate_attribute_tokens_empty_preview(
    group_key: str,
    require_full_match: bool = False,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "group_key": group_key,
        "group_name": "",
        "previous_tokens": [],
        "tokens_to_propagate": [],
        "target_line_count": 0,
        "matched_line_count": 0,
        "affected_line_count": 0,
        "no_match_line_count": 0,
        "already_present_tokens": [],
        "require_full_match": bool(require_full_match),
        "examples": [],
        "warnings": list(warnings or []),
    }

def _propagate_attribute_tokens_line_preview(
    line,
    previous_tokens: List[str],
    tokens_to_propagate: List[str],
    require_full_match: bool = False,
) -> Dict[str, Any]:
    before = getattr(line, "current_text", "") or ""
    tokens = _parse_prompt_for_module_preset(before)
    if not tokens:
        tokens = list(getattr(line, "tokens", []) or [])
        before = ", ".join(tokens)

    line_token_keys = [get_token_attribute_key(token) for token in tokens]
    line_key_set = {token_key for token_key in line_token_keys if token_key}
    previous_set = set(previous_tokens)
    matched_previous_tokens = [token for token in previous_tokens if token in line_key_set]
    full_match = bool(previous_tokens) and previous_set.issubset(line_key_set)
    matched = full_match if require_full_match else bool(matched_previous_tokens)
    already_present_tokens = [token for token in tokens_to_propagate if token in line_key_set]
    added_tokens = [token for token in tokens_to_propagate if token not in line_key_set]
    changed_tokens = list(tokens)
    if matched and added_tokens:
        changed_tokens.extend(added_tokens)
    after = ", ".join(changed_tokens)
    changed = after != before
    return {
        "line_id": getattr(line, "id", ""),
        "display_id": _line_display_id(line),
        "file": getattr(line, "original_file_name", ""),
        "line_number": getattr(line, "original_index", 0) + 1,
        "line_index": getattr(line, "current_index", getattr(line, "original_index", 0)),
        "matched_previous_tokens": matched_previous_tokens,
        "added_tokens": added_tokens if changed else [],
        "already_present_tokens": already_present_tokens,
        "full_match": full_match,
        "matched": matched,
        "changed": changed,
        "before": before,
        "after": after,
    }

def preview_propagate_attribute_group_tokens(
    project: Project,
    group_key: str,
    previous_tokens: List[str],
    tokens_to_propagate: List[str],
    target_line_ids: Optional[List[str]] = None,
    require_full_match: bool = False,
    example_limit: int = 10,
) -> Dict[str, Any]:
    normalized_group_key = normalize_attribute_group_name(group_key)
    groups = get_project_attribute_groups(project)
    group = groups.get(normalized_group_key)
    if not group:
        return _propagate_attribute_tokens_empty_preview(
            normalized_group_key,
            require_full_match,
            warnings=["Selected Attribute Group was not found."],
        )

    normalized_previous_tokens = _normalize_attribute_token_list(previous_tokens)
    normalized_tokens_to_propagate = _normalize_attribute_token_list(tokens_to_propagate)
    previous_set = set(normalized_previous_tokens)
    normalized_tokens_to_propagate = [
        token for token in normalized_tokens_to_propagate if token not in previous_set
    ]
    if not normalized_previous_tokens:
        return _propagate_attribute_tokens_empty_preview(
            normalized_group_key,
            require_full_match,
            warnings=["Previous group tokens are required for propagation matching."],
        )
    if not normalized_tokens_to_propagate:
        return _propagate_attribute_tokens_empty_preview(
            normalized_group_key,
            require_full_match,
            warnings=["Tokens to propagate are required and must not duplicate previous tokens."],
        )

    target_line_set = set(target_line_ids or []) if target_line_ids is not None else None
    target_line_count = 0
    matched_line_count = 0
    affected_line_count = 0
    no_match_line_count = 0
    already_present_tokens = []
    already_present_seen = set()
    examples = []

    for line in getattr(project, "prompt_lines", []) or []:
        if not _line_in_targets(line, target_line_set):
            continue
        target_line_count += 1
        example = _propagate_attribute_tokens_line_preview(
            line,
            normalized_previous_tokens,
            normalized_tokens_to_propagate,
            require_full_match=require_full_match,
        )
        if example["matched"]:
            matched_line_count += 1
            for token in example.get("already_present_tokens", []) or []:
                if token not in already_present_seen:
                    already_present_tokens.append(token)
                    already_present_seen.add(token)
        else:
            no_match_line_count += 1
        if example["changed"]:
            affected_line_count += 1
            if len(examples) < example_limit:
                examples.append(example)

    return {
        "group_key": normalized_group_key,
        "group_name": group.get("name", normalized_group_key),
        "previous_tokens": normalized_previous_tokens,
        "tokens_to_propagate": normalized_tokens_to_propagate,
        "target_line_count": target_line_count,
        "matched_line_count": matched_line_count,
        "affected_line_count": affected_line_count,
        "no_match_line_count": no_match_line_count,
        "already_present_tokens": already_present_tokens,
        "require_full_match": bool(require_full_match),
        "examples": examples,
        "warnings": [],
    }

def apply_propagate_attribute_group_tokens(
    project: Project,
    group_key: str,
    previous_tokens: List[str],
    tokens_to_propagate: List[str],
    target_line_ids: Optional[List[str]] = None,
    require_full_match: bool = False,
) -> Project:
    preview = preview_propagate_attribute_group_tokens(
        project,
        group_key,
        previous_tokens,
        tokens_to_propagate,
        target_line_ids=target_line_ids,
        require_full_match=require_full_match,
        example_limit=1000000,
    )
    if preview["affected_line_count"] == 0:
        return project

    line_lookup = {
        getattr(line, "id", ""): line
        for line in getattr(project, "prompt_lines", []) or []
        if not getattr(line, "deleted", False) and not _is_special_gallery_line(line)
    }
    changed_any = False
    for example in preview["examples"]:
        line = line_lookup.get(example["line_id"])
        if not line or not example.get("changed"):
            continue
        line.current_text = example["after"]
        line.tokens = _parse_prompt_for_module_preset(example["after"])
        line.edited = True
        changed_any = True
    if changed_any:
        return build_graph(project)
    return project

def set_module_entry(
    project: Project,
    module_name: str,
    module_body: str,
    module_type: str = DEFAULT_MODULE_TYPE,
    core_tokens: Optional[List[str]] = None,
    min_match_tokens: Optional[int] = None,
    category: Optional[str] = None,
) -> None:
    module_type = module_type if module_type in MODULE_TYPES else DEFAULT_MODULE_TYPE
    module_graph = create_blank_module_graph(module_name, module_body or "", module_type)
    body = ", ".join(flatten_module_graph_to_tokens(module_graph))
    module_tokens = _module_rule_tokens(body)
    get_project_module_library(project)[module_name] = {
        "body": body,
        "type": module_type,
        "category": normalize_global_module_category(category),
        "graph": module_graph,
        "core_tokens": _normalize_module_rule_tokens(core_tokens) if core_tokens is not None else module_tokens[:1],
        "min_match_tokens": _clamp_module_min_match(
            min_match_tokens if min_match_tokens is not None else len(module_tokens),
            module_tokens,
        ),
    }

def update_module_entry_preserving_metadata(
    existing_entry: Any,
    module_name: str,
    module_body: str,
    module_type: str = DEFAULT_MODULE_TYPE,
    core_tokens: Optional[List[str]] = None,
    min_match_tokens: Optional[int] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a module entry update while preserving unknown extension fields."""
    if isinstance(existing_entry, dict):
        updated_entry = copy.deepcopy(existing_entry)
    else:
        updated_entry = {}

    module_type = module_type if module_type in MODULE_TYPES else DEFAULT_MODULE_TYPE
    module_graph = create_blank_module_graph(module_name, module_body or "", module_type)
    body = ", ".join(flatten_module_graph_to_tokens(module_graph))
    module_tokens = _module_rule_tokens(body)
    updated_entry["body"] = body
    updated_entry["type"] = module_type
    updated_entry["category"] = normalize_global_module_category(category or updated_entry.get("category"))
    updated_entry["graph"] = module_graph
    updated_entry["core_tokens"] = (
        _normalize_module_rule_tokens(core_tokens)
        if core_tokens is not None
        else module_tokens[:1]
    )
    updated_entry["min_match_tokens"] = _clamp_module_min_match(
        min_match_tokens if min_match_tokens is not None else len(module_tokens),
        module_tokens,
    )
    return updated_entry

def create_library_module(
    project: Project,
    module_name: str,
    module_body: str,
    module_type: str = DEFAULT_MODULE_TYPE,
    core_tokens: Optional[List[str]] = None,
    min_match_tokens: Optional[int] = None,
    category: Optional[str] = None,
) -> bool:
    name = (module_name or "").strip()
    if not name or name in get_project_module_library(project):
        return False
    set_module_entry(project, name, module_body, module_type, core_tokens, min_match_tokens, category)
    return True


def copy_outfit_module_to_character_attribute_group(
    module_library: Dict[str, Any],
    outfit_module_name: str,
    character_module_name: str,
    group_name: str,
) -> Dict[str, Any]:
    library = normalize_module_library(module_library or {})
    outfit_name = str(outfit_module_name or "").strip()
    character_name = str(character_module_name or "").strip()
    clean_group_name = str(group_name or "").strip()
    if outfit_name not in library:
        return {"ok": False, "message": "Outfit Moduleが見つかりません。"}
    if character_name not in library:
        return {"ok": False, "message": "追加先Character Moduleが見つかりません。"}
    if get_module_category(library, outfit_name) != "Outfit":
        return {"ok": False, "message": "OutfitカテゴリのModuleを選択してください。"}
    if get_module_category(library, character_name) != "Character":
        return {"ok": False, "message": "追加先はCharacterカテゴリのModuleを選択してください。"}
    group_key = normalize_attribute_group_name(clean_group_name)
    if not group_key:
        return {"ok": False, "message": "Attribute Group名を入力してください。"}

    character_entry = library[character_name]
    attribute_groups = _normalize_module_attribute_groups(character_entry.get("attribute_groups"))
    if group_key in attribute_groups:
        return {"ok": False, "message": "同名のAttribute Groupが既にあります。"}

    outfit_body = get_module_body(library, outfit_name)
    outfit_tokens = _module_rule_tokens(outfit_body)
    if not outfit_tokens:
        return {"ok": False, "message": "Outfit Moduleにコピーできるtokensがありません。"}

    attribute_groups[group_key] = {
        "name": clean_group_name,
        "tokens": outfit_tokens,
        "core_tokens": get_module_core_tokens(library, outfit_name),
        "created_from": "outfit_module",
        "source_module": outfit_name,
        "source_category": "Outfit",
    }
    character_entry["attribute_groups"] = attribute_groups
    return {
        "ok": True,
        "message": f"'{outfit_name}' を '{character_name}' のAttribute Group '{clean_group_name}' として追加しました。",
        "library": library,
        "group_key": group_key,
    }

def resolve_line_group_ids(project: Project, group_name: str) -> List[str]:
    groups = get_project_line_groups(project)
    group_ids = set(groups.get(group_name, []))
    return [
        line.id
        for line in project.prompt_lines
        if line.id in group_ids and not getattr(line, "deleted", False) and not _is_special_gallery_line(line)
    ]

def _is_route_separator_line(line: Any) -> bool:
    return getattr(line, "line_type", None) == "separator"

def _is_workbench_line(line: Any) -> bool:
    return getattr(line, "line_type", None) == "workbench"

def _is_special_gallery_line(line: Any) -> bool:
    return getattr(line, "line_type", None) in {"separator", "workbench"}

def _route_separator_label(line: Any) -> str:
    return (
        getattr(line, "separator_label", None)
        or getattr(line, "current_text", None)
        or getattr(line, "original_file_name", None)
        or getattr(line, "id", None)
        or "Route"
    )

def get_module_swap_route_options(project: Project) -> List[Dict[str, Any]]:
    """Return route separator options with the prompt line ids each route owns."""

    active_lines = [
        line
        for line in getattr(project, "prompt_lines", []) or []
        if not getattr(line, "deleted", False)
    ]
    route_options = []
    current_route = None
    for line in active_lines:
        if _is_route_separator_line(line):
            current_route = {
                "route_id": getattr(line, "id", ""),
                "route_label": str(_route_separator_label(line)),
                "line_ids": [],
            }
            route_options.append(current_route)
            continue
        if current_route is not None and not _is_workbench_line(line):
            current_route["line_ids"].append(getattr(line, "id", ""))

    for route in route_options:
        route["line_count"] = len([line_id for line_id in route.get("line_ids", []) if line_id])
    return route_options

def get_gallery_route_options(project: Project) -> List[Dict[str, Any]]:
    return get_module_swap_route_options(project)

def resolve_gallery_route_for_line(project: Project, line_id: str) -> Dict[str, Any]:
    """Resolve the Gallery route that owns a separator or prompt line id."""

    active_lines = [
        line
        for line in getattr(project, "prompt_lines", []) or []
        if not getattr(line, "deleted", False)
    ]
    target_id = str(line_id or "").strip()
    if not target_id:
        return {
            "route_id": "",
            "route_label": "",
            "separator_line_id": "",
            "line_ids": [],
            "line_count": 0,
            "start_index": None,
            "end_index": None,
            "warnings": ["No current line is available to resolve a Route."],
        }

    target_index = next(
        (index for index, line in enumerate(active_lines) if getattr(line, "id", "") == target_id),
        None,
    )
    if target_index is None:
        return {
            "route_id": "",
            "route_label": "",
            "separator_line_id": "",
            "line_ids": [],
            "line_count": 0,
            "start_index": None,
            "end_index": None,
            "warnings": ["Current line is not available in the active Gallery lines."],
        }

    separator_index = target_index if _is_route_separator_line(active_lines[target_index]) else None
    if separator_index is None:
        for index in range(target_index, -1, -1):
            if _is_route_separator_line(active_lines[index]):
                separator_index = index
                break

    if separator_index is None:
        return {
            "route_id": "",
            "route_label": "",
            "separator_line_id": "",
            "line_ids": [],
            "line_count": 0,
            "start_index": None,
            "end_index": None,
            "warnings": ["No current Route resolved for the selected line."],
        }

    next_separator_index = next(
        (
            index
            for index, line in enumerate(active_lines[separator_index + 1:], start=separator_index + 1)
            if _is_route_separator_line(line)
        ),
        len(active_lines),
    )
    route_lines = [
        line
        for line in active_lines[separator_index + 1:next_separator_index]
        if not _is_special_gallery_line(line)
    ]
    line_ids = [getattr(line, "id", "") for line in route_lines if getattr(line, "id", "")]
    line_indexes = [
        getattr(line, "current_index", getattr(line, "original_index", None))
        for line in route_lines
        if getattr(line, "current_index", getattr(line, "original_index", None)) is not None
    ]
    separator = active_lines[separator_index]
    warnings = [] if line_ids else ["Current Route has no active prompt lines."]
    return {
        "route_id": getattr(separator, "id", ""),
        "route_label": str(_route_separator_label(separator)),
        "separator_line_id": getattr(separator, "id", ""),
        "line_ids": line_ids,
        "line_count": len(line_ids),
        "start_index": min(line_indexes) if line_indexes else None,
        "end_index": max(line_indexes) if line_indexes else None,
        "warnings": warnings,
    }

def resolve_route_line_ids(project: Project, route_ids: List[str]) -> List[str]:
    selected_route_ids = {str(route_id) for route_id in (route_ids or []) if str(route_id or "").strip()}
    if not selected_route_ids:
        return []

    line_ids = []
    seen = set()
    for route in get_module_swap_route_options(project):
        if route.get("route_id") not in selected_route_ids:
            continue
        for line_id in route.get("line_ids", []) or []:
            if line_id and line_id not in seen:
                line_ids.append(line_id)
                seen.add(line_id)
    return line_ids

def resolve_module_swap_target_line_ids(
    project: Project,
    scope: str,
    selected_line_groups: Optional[List[str]] = None,
    selected_routes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Resolve Module Swap scope into prompt line ids plus user-facing warnings."""

    active_prompt_line_ids = [
        line.id
        for line in getattr(project, "prompt_lines", []) or []
        if not getattr(line, "deleted", False) and not _is_special_gallery_line(line)
    ]
    scope = str(scope or "all")
    if scope == "all":
        return {
            "target_line_ids": None,
            "target_line_count": len(active_prompt_line_ids),
            "warnings": [],
        }

    if scope == "line_group":
        group_names = [name for name in (selected_line_groups or []) if str(name or "").strip()]
        if not group_names:
            return {
                "target_line_ids": [],
                "target_line_count": 0,
                "warnings": ["Select at least one Line Group."],
            }
        line_ids = []
        seen = set()
        for group_name in group_names:
            for line_id in resolve_line_group_ids(project, group_name):
                if line_id and line_id not in seen:
                    line_ids.append(line_id)
                    seen.add(line_id)
        warnings = [] if line_ids else ["Selected Line Group has no active prompt lines."]
        return {
            "target_line_ids": line_ids,
            "target_line_count": len(line_ids),
            "warnings": warnings,
        }

    if scope == "route":
        route_options = get_module_swap_route_options(project)
        if not route_options:
            return {
                "target_line_ids": [],
                "target_line_count": 0,
                "warnings": ["No Gallery routes are available in this project."],
            }
        route_ids = [route_id for route_id in (selected_routes or []) if str(route_id or "").strip()]
        if not route_ids:
            return {
                "target_line_ids": [],
                "target_line_count": 0,
                "warnings": ["Select at least one Route."],
            }
        line_ids = resolve_route_line_ids(project, route_ids)
        warnings = [] if line_ids else ["Selected Route has no active prompt lines."]
        return {
            "target_line_ids": line_ids,
            "target_line_count": len(line_ids),
            "warnings": warnings,
        }

    return {
        "target_line_ids": [],
        "target_line_count": 0,
        "warnings": [f"Unknown Module Swap scope: {scope}"],
    }

def create_line_group(project: Project, group_name: str, line_ids: List[str]) -> bool:
    name = (group_name or "").strip()
    groups = get_project_line_groups(project)
    if not name or name in groups:
        return False

    selected = set(line_ids or [])
    groups[name] = [
        line.id
        for line in project.prompt_lines
        if line.id in selected and not getattr(line, "deleted", False)
    ]
    return bool(groups[name])

def delete_line_group(project: Project, group_name: str) -> bool:
    groups = get_project_line_groups(project)
    if group_name not in groups:
        return False
    del groups[group_name]
    return True

def _join_prompt_parts(*parts: str) -> str:
    return ", ".join(part.strip() for part in parts if part and part.strip())

def _add_prompts_after_match(text: str, edit_text: str, insert_after_prompt: str = "") -> str:
    prompt = (insert_after_prompt or "").strip()
    if not prompt:
        return _join_prompt_parts(text, edit_text)

    match_index = text.find(prompt)
    if match_index < 0:
        return _join_prompt_parts(text, edit_text)

    insert_index = match_index + len(prompt)
    before = text[:insert_index]
    after = text[insert_index:].lstrip()
    if after.startswith(","):
        after = after[1:].lstrip()
    return _join_prompt_parts(before, edit_text, after)

def _line_contains_prompt(text: str, add_text: str, match_mode: str = "exact_token") -> bool:
    query = (add_text or "").strip()
    if not query:
        return False
    if match_mode == "literal":
        return query in text

    if match_mode == "exact_token":
        target_tokens = parse_prompt(add_text or "")
        if len(target_tokens) != 1:
            return False
        query = extract_node_metadata(target_tokens[0])["base_word"].strip()
        if not query:
            return False

    for token in parse_prompt(text):
        if is_structural_mod_marker(token):
            continue
        token_base = extract_node_metadata(token)["base_word"].strip()
        if _token_matches(token_base, query, match_mode):
            return True
    return False

def _normalize_prompt_commas(text: str) -> str:
    parts = [part.strip() for part in text.split(",") if part.strip()]
    return ", ".join(parts)

def _remove_prompts(text: str, remove_text: str, remove_mode: str = "first") -> str:
    prompt = (remove_text or "").strip()
    if not prompt:
        return text

    count = 1 if remove_mode == "first" else -1
    return _normalize_prompt_commas(text.replace(prompt, "", count))

def is_valid_exact_remove_target(remove_text: str) -> bool:
    tokens = parse_prompt(remove_text or "")
    return len(tokens) == 1 and bool(extract_node_metadata(tokens[0])["base_word"].strip())

def is_valid_exact_replace_target(find_text: str, replace_text: str) -> bool:
    find_tokens = parse_prompt(find_text or "")
    replace_tokens = parse_prompt(replace_text or "")
    if len(find_tokens) != 1 or len(replace_tokens) != 1:
        return False
    return (
        bool(extract_node_metadata(find_tokens[0])["base_word"].strip())
        and bool(extract_node_metadata(replace_tokens[0])["base_word"].strip())
    )

def is_valid_replace_token(replace_text: str) -> bool:
    replace_tokens = parse_prompt(replace_text or "")
    return len(replace_tokens) == 1 and bool(extract_node_metadata(replace_tokens[0])["base_word"].strip())

def is_valid_add_if_missing_target(add_text: str) -> bool:
    return is_valid_replace_token(add_text)

def _token_matches(token_base: str, query: str, match_mode: str) -> bool:
    query = (query or "").strip()
    if not query:
        return False
    if match_mode == "contains_token":
        return query in token_base
    return token_base == query

def _remove_prompt_tokens(
    text: str,
    remove_text: str,
    remove_mode: str = "first",
    match_mode: str = "exact_token"
) -> str:
    target_tokens = parse_prompt(remove_text or "")
    if match_mode == "exact_token":
        if len(target_tokens) != 1:
            return text
        target_base = extract_node_metadata(target_tokens[0])["base_word"].strip()
    else:
        target_base = (remove_text or "").strip()

    if not target_base:
        return text

    removed = 0
    result_tokens = []
    for token in parse_prompt(text):
        if is_structural_mod_marker(token):
            result_tokens.append(token)
            continue

        token_base = extract_node_metadata(token)["base_word"].strip()
        if _token_matches(token_base, target_base, match_mode) and (remove_mode == "all" or removed == 0):
            removed += 1
            continue
        result_tokens.append(token)

    return ", ".join(result_tokens)

def _replace_prompt_tokens(
    text: str,
    find_text: str,
    replace_text: str,
    preserve_weights: bool = True,
    match_mode: str = "exact_token"
) -> str:
    find_tokens = parse_prompt(find_text or "")
    replace_tokens = parse_prompt(replace_text or "")
    if len(replace_tokens) != 1:
        return text

    if match_mode == "exact_token":
        if len(find_tokens) != 1:
            return text
        target_base = extract_node_metadata(find_tokens[0])["base_word"].strip()
    else:
        target_base = (find_text or "").strip()

    replacement = replace_tokens[0]
    if not target_base or not extract_node_metadata(replacement)["base_word"].strip():
        return text

    result_tokens = []
    for token in parse_prompt(text):
        if is_structural_mod_marker(token):
            result_tokens.append(token)
            continue

        token_base = extract_node_metadata(token)["base_word"].strip()
        if _token_matches(token_base, target_base, match_mode):
            result_tokens.append(_replacement_token(replacement, token, preserve_weights))
        else:
            result_tokens.append(token)

    return ", ".join(result_tokens)

def _token_weight(token: str) -> float:
    try:
        return float(extract_node_metadata(token)["weight"])
    except (TypeError, ValueError):
        return 1.0

def _token_duplicate_key(token: str) -> str:
    return extract_node_metadata(token)["base_word"].strip()

def _contains_duplicate_candidates(base: str) -> List[str]:
    normalized = base.strip().lower()
    candidates = []
    if normalized:
        candidates.append(normalized)

    without_leading_digits = re.sub(r"^\d+", "", normalized).strip()
    if without_leading_digits and without_leading_digits not in candidates:
        candidates.append(without_leading_digits)

    singular = without_leading_digits[:-1] if without_leading_digits.endswith("s") else without_leading_digits
    if singular and singular not in candidates:
        candidates.append(singular)

    return candidates

def _duplicate_bases_match(left_base: str, right_base: str, match_mode: str) -> bool:
    if match_mode == "contains_token":
        left_candidates = _contains_duplicate_candidates(left_base)
        right_candidates = _contains_duplicate_candidates(right_base)
        for left in left_candidates:
            for right in right_candidates:
                if left and right and (left in right or right in left):
                    return True
        return False
    return left_base == right_base

def _duplicate_token_decisions(
    tokens: List[str],
    duplicate_match_mode: str = "exact_token",
    duplicate_preserve_strategy: str = "keep_first"
) -> Dict[int, str]:
    groups = []
    token_status = {idx: "keep" for idx in range(len(tokens))}

    for idx, token in enumerate(tokens):
        if is_structural_mod_marker(token):
            continue

        token_base = _token_duplicate_key(token)
        if not token_base:
            continue

        matched_group = None
        for group in groups:
            if any(_duplicate_bases_match(token_base, base, duplicate_match_mode) for base in group["bases"]):
                matched_group = group
                break

        if matched_group is None:
            groups.append({
                "bases": [token_base],
                "indexes": [idx],
                "preserved_index": idx,
            })
            continue

        matched_group["indexes"].append(idx)
        if token_base not in matched_group["bases"]:
            matched_group["bases"].append(token_base)

        if duplicate_preserve_strategy == "keep_strongest":
            preserved_index = matched_group["preserved_index"]
            if _token_weight(token) > _token_weight(tokens[preserved_index]):
                matched_group["preserved_index"] = idx

    for group in groups:
        if len(group["indexes"]) <= 1:
            continue
        preserved_index = group["preserved_index"]
        for idx in group["indexes"]:
            token_status[idx] = "preserve" if idx == preserved_index else "remove"

    return token_status

def get_duplicate_token_marks(
    text: str,
    duplicate_match_mode: str = "exact_token",
    duplicate_preserve_strategy: str = "keep_first"
) -> List[Dict[str, str]]:
    tokens = parse_prompt(text)
    token_status = _duplicate_token_decisions(
        tokens,
        duplicate_match_mode,
        duplicate_preserve_strategy,
    )
    return [
        {
            "token": token,
            "status": token_status.get(idx, "keep"),
        }
        for idx, token in enumerate(tokens)
    ]

def _deduplicate_prompt_tokens(
    text: str,
    duplicate_match_mode: str = "exact_token",
    duplicate_preserve_strategy: str = "keep_first"
) -> str:
    tokens = parse_prompt(text)
    token_status = _duplicate_token_decisions(
        tokens,
        duplicate_match_mode,
        duplicate_preserve_strategy,
    )
    result_tokens = [
        token
        for idx, token in enumerate(tokens)
        if token_status.get(idx) != "remove"
    ]
    return ", ".join(result_tokens)

def _clean_prompt_formatting(text: str) -> str:
    return ", ".join(parse_prompt(text))

def _normalize_weight_value(value: float) -> str:
    return f"{value:.12g}"

def _normalize_weighted_token(token: str) -> str:
    if is_structural_mod_marker(token):
        return token

    if extract_mod_info(token)["type"] == "inline":
        return token

    match = re.fullmatch(r"\(([^():][^:()]*):([0-9]+(?:\.[0-9]+)?)\)", token)
    if not match:
        return token

    base_token = match.group(1).strip()
    weight = float(match.group(2))
    if weight == 1.0:
        return base_token
    return f"({base_token}:{_normalize_weight_value(weight)})"

def _normalize_prompt_weights(text: str) -> str:
    return ", ".join(_normalize_weighted_token(token) for token in parse_prompt(text))

def _batch_transform_text(
    text: str,
    operation: str,
    edit_text: str = "",
    search_text: str = "",
    add_position: str = "end",
    insert_after_prompt: str = "",
    remove_mode: str = "first",
    remove_match_mode: str = "exact_token",
    replace_match_mode: str = "exact_token",
    preserve_replace_weights: bool = True,
    duplicate_match_mode: str = "exact_token",
    duplicate_preserve_strategy: str = "keep_first",
    add_if_missing: bool = False,
    add_match_mode: str = "exact_token",
    neighbor_patterns: Dict[str, Dict[str, int]] = None,
    learned_neighbor_fallback: str = "skip",
) -> str:
    if operation == "add":
        if add_if_missing and _line_contains_prompt(text, edit_text, add_match_mode):
            return text
        if add_position == "learned_neighbor":
            edit_tokens = parse_prompt(edit_text or "")
            if len(edit_tokens) != 1:
                return _join_prompt_parts(text, edit_text)
            if edit_tokens[0] in _parse_prompt_for_module_preset(text or ""):
                return text
            after, _changed, _placement = _insert_token_in_text(
                text,
                edit_tokens[0],
                "learned_neighbor",
                neighbor_patterns=neighbor_patterns or {},
                learned_neighbor_fallback=learned_neighbor_fallback,
            )
            return after
        if add_position == "start":
            return _join_prompt_parts(edit_text, text)
        if add_position == "after_match":
            return _add_prompts_after_match(text, edit_text, insert_after_prompt)
        return _join_prompt_parts(text, edit_text)
    if operation == "remove":
        if remove_match_mode in ("exact_token", "contains_token"):
            return _remove_prompt_tokens(text, search_text, remove_mode, remove_match_mode)
        return _remove_prompts(text, search_text, remove_mode)
    if operation == "replace" and replace_match_mode in ("exact_token", "contains_token"):
        return _replace_prompt_tokens(text, search_text, edit_text, preserve_replace_weights, replace_match_mode)
    if operation == "remove_duplicates":
        return _deduplicate_prompt_tokens(text, duplicate_match_mode, duplicate_preserve_strategy)
    if operation == "clean_formatting":
        return _clean_prompt_formatting(text)
    if operation == "normalize_weights":
        return _normalize_prompt_weights(text)
    if operation == "append":
        return _join_prompt_parts(text, edit_text)
    if operation == "prepend":
        return _join_prompt_parts(edit_text, text)
    if operation == "replace":
        return text.replace(search_text, edit_text)
    return text

def _batch_text_edit_changes_module_structure(before: str, after: str) -> bool:
    return extract_module_structure_from_text(before) != extract_module_structure_from_text(after)

def preview_batch_text_edit(
    project: Project,
    operation: str,
    edit_text: str,
    search_text: str = "",
    add_position: str = "end",
    insert_after_prompt: str = "",
    remove_mode: str = "first",
    remove_match_mode: str = "exact_token",
    replace_match_mode: str = "exact_token",
    preserve_replace_weights: bool = True,
    duplicate_match_mode: str = "exact_token",
    duplicate_preserve_strategy: str = "keep_first",
    add_if_missing: bool = False,
    add_match_mode: str = "exact_token",
    target_line_ids: List[str] = None,
    learned_neighbor_fallback: str = "skip",
    example_limit: int = 5
) -> Dict[str, Any]:
    target_line_count = 0
    affected_line_count = 0
    skipped_module_structure_count = 0
    skipped_no_neighbor_count = 0
    examples = []
    add_neighbor_patterns = {}
    if operation == "add" and add_position == "learned_neighbor":
        edit_tokens = parse_prompt(edit_text or "")
        if len(edit_tokens) == 1:
            add_neighbor_patterns = collect_neighbor_patterns(project, edit_tokens[0])

    for line in project.prompt_lines:
        if not _line_in_targets(line, target_line_ids):
            continue

        target_line_count += 1
        after = _batch_transform_text(
            line.current_text,
            operation,
            edit_text,
            search_text=search_text,
            add_position=add_position,
            insert_after_prompt=insert_after_prompt,
            remove_mode=remove_mode,
            remove_match_mode=remove_match_mode,
            replace_match_mode=replace_match_mode,
            preserve_replace_weights=preserve_replace_weights,
            duplicate_match_mode=duplicate_match_mode,
            duplicate_preserve_strategy=duplicate_preserve_strategy,
            add_if_missing=add_if_missing,
            add_match_mode=add_match_mode,
            neighbor_patterns=add_neighbor_patterns,
            learned_neighbor_fallback=learned_neighbor_fallback,
        )
        if after == line.current_text:
            if operation == "add" and add_position == "learned_neighbor" and learned_neighbor_fallback != "end":
                tokens = _parse_prompt_for_module_preset(line.current_text)
                edit_tokens = parse_prompt(edit_text or "")
                if len(edit_tokens) != 1 or edit_tokens[0] in tokens:
                    continue
                placement = infer_best_insert_position(
                    tokens,
                    add_neighbor_patterns,
                )[1]
                if placement.get("placement") == "fallback":
                    skipped_no_neighbor_count += 1
            continue

        if _batch_text_edit_changes_module_structure(line.current_text, after):
            skipped_module_structure_count += 1
            continue

        affected_line_count += 1
        if len(examples) < example_limit:
            examples.append({
                "line_id": line.id,
                "file": line.original_file_name,
                "line_number": line.original_index + 1,
                "before": line.current_text,
                "after": after,
                "duplicate_token_marks": get_duplicate_token_marks(
                    line.current_text,
                    duplicate_match_mode,
                    duplicate_preserve_strategy,
                ) if operation == "remove_duplicates" else [],
                "placement": infer_best_insert_position(
                    _parse_prompt_for_module_preset(line.current_text),
                    add_neighbor_patterns,
                )[1] if operation == "add" and add_position == "learned_neighbor" else {},
            })

    return {
        "operation": operation,
        "target_line_count": target_line_count,
        "affected_line_count": affected_line_count,
        "skipped_module_structure_count": skipped_module_structure_count,
        "skipped_no_neighbor_count": skipped_no_neighbor_count,
        "neighbor_patterns": add_neighbor_patterns,
        "examples": examples,
    }

def apply_batch_text_edit(
    project: Project,
    operation: str,
    edit_text: str,
    search_text: str = "",
    add_position: str = "end",
    insert_after_prompt: str = "",
    remove_mode: str = "first",
    remove_match_mode: str = "exact_token",
    replace_match_mode: str = "exact_token",
    preserve_replace_weights: bool = True,
    duplicate_match_mode: str = "exact_token",
    duplicate_preserve_strategy: str = "keep_first",
    add_if_missing: bool = False,
    add_match_mode: str = "exact_token",
    target_line_ids: List[str] = None,
    learned_neighbor_fallback: str = "skip",
) -> Project:
    changed = False
    add_neighbor_patterns = {}
    if operation == "add" and add_position == "learned_neighbor":
        edit_tokens = parse_prompt(edit_text or "")
        if len(edit_tokens) == 1:
            add_neighbor_patterns = collect_neighbor_patterns(project, edit_tokens[0])

    for line in project.prompt_lines:
        if not _line_in_targets(line, target_line_ids):
            continue

        after = _batch_transform_text(
            line.current_text,
            operation,
            edit_text,
            search_text=search_text,
            add_position=add_position,
            insert_after_prompt=insert_after_prompt,
            remove_mode=remove_mode,
            remove_match_mode=remove_match_mode,
            replace_match_mode=replace_match_mode,
            preserve_replace_weights=preserve_replace_weights,
            duplicate_match_mode=duplicate_match_mode,
            duplicate_preserve_strategy=duplicate_preserve_strategy,
            add_if_missing=add_if_missing,
            add_match_mode=add_match_mode,
            neighbor_patterns=add_neighbor_patterns,
            learned_neighbor_fallback=learned_neighbor_fallback,
        )
        if after == line.current_text:
            continue
        if _batch_text_edit_changes_module_structure(line.current_text, after):
            continue

        line.current_text = after
        line.tokens = parse_prompt(after)
        line.edited = True
        changed = True

    if changed:
        return build_graph(project)
    return project

def _token_base(token: str) -> str:
    return extract_node_metadata(token)["base_word"].strip()

def _find_source_token_context(project: Project, source_line_id: str, selected_node_ids: List[str]) -> Dict[str, Any]:
    source_line = next(
        (
            line
            for line in project.prompt_lines
            if line.id == source_line_id and not getattr(line, "deleted", False)
        ),
        None,
    )
    if not source_line:
        return {}

    selected_set = set(selected_node_ids or [])
    for idx, node_id in enumerate(getattr(source_line, "node_path", [])):
        if node_id not in selected_set:
            continue
        if idx >= len(source_line.tokens):
            continue
        token = source_line.tokens[idx]
        if is_structural_mod_marker(token) or not _is_neighbor_anchor_token(token):
            continue
        base = _token_base(token)
        if not base:
            continue

        left_token = ""
        right_token = ""
        if idx > 0 and not is_structural_mod_marker(source_line.tokens[idx - 1]) and _is_neighbor_anchor_token(source_line.tokens[idx - 1]):
            left_token = source_line.tokens[idx - 1]
        if idx + 1 < len(source_line.tokens) and not is_structural_mod_marker(source_line.tokens[idx + 1]) and _is_neighbor_anchor_token(source_line.tokens[idx + 1]):
            right_token = source_line.tokens[idx + 1]

        return {
            "token": token,
            "base": base,
            "left_token": left_token,
            "left_base": _token_base(left_token) if left_token else "",
            "right_token": right_token,
            "right_base": _token_base(right_token) if right_token else "",
        }

    return {}

def _find_token_index_by_base(tokens: List[str], target_base: str) -> int:
    for idx, token in enumerate(tokens):
        if is_structural_mod_marker(token) or not _is_neighbor_anchor_token(token):
            continue
        if _token_base(token) == target_base:
            return idx
    return -1

def _line_contains_token_base(tokens: List[str], token_base: str) -> bool:
    return _find_token_index_by_base(tokens, token_base) >= 0

def _insert_focus_token_near_context(text: str, insert_token: str, source_context: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    tokens = parse_prompt(text or "")
    insert_base = _token_base(insert_token)
    if not insert_base or _line_contains_token_base(tokens, insert_base):
        return text, {"placement": "already_present", "reason": "Skipped: token already exists in line."}

    anchor_options = [
        ("after_source", source_context.get("base", ""), "after", "Inserted after matching source token."),
        ("before_right_neighbor", source_context.get("right_base", ""), "before", "Inserted before matching right neighbor."),
        ("after_left_neighbor", source_context.get("left_base", ""), "after", "Inserted after matching left neighbor."),
    ]
    for placement_name, anchor_base, position, reason in anchor_options:
        if not anchor_base:
            continue
        anchor_index = _find_token_index_by_base(tokens, anchor_base)
        if anchor_index < 0:
            continue
        insert_index = anchor_index if position == "before" else anchor_index + 1
        result_tokens = list(tokens)
        result_tokens.insert(insert_index, insert_token)
        return ", ".join(result_tokens), {
            "placement": placement_name,
            "neighbor": tokens[anchor_index],
            "reason": reason,
        }

    result_tokens = list(tokens)
    result_tokens.append(insert_token)
    return ", ".join(result_tokens), {
        "placement": "fallback_end",
        "neighbor": "",
        "reason": "Fallback insertion: end of line.",
    }

def _replace_focus_token(text: str, replacement_token: str, source_context: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    tokens = parse_prompt(text or "")
    target_base = source_context.get("base", "")
    if not target_base or not _token_base(replacement_token):
        return text, {"placement": "no_source_token", "reason": "Skipped: no source token."}

    changed = False
    result_tokens = []
    for token in tokens:
        if is_structural_mod_marker(token) or not _is_neighbor_anchor_token(token):
            result_tokens.append(token)
            continue
        if _token_base(token) == target_base:
            result_tokens.append(_replacement_token(replacement_token, token, True))
            changed = True
        else:
            result_tokens.append(token)

    if not changed:
        return text, {"placement": "no_match", "reason": "Skipped: no matching source token."}
    return ", ".join(result_tokens), {"placement": "replace_token", "reason": "Replaced matching source token."}

def _focus_propagation_transform_text(
    text: str,
    operation: str,
    edit_token: str,
    source_context: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    edit_tokens = parse_prompt(edit_token or "")
    if len(edit_tokens) != 1 or is_structural_mod_marker(edit_tokens[0]):
        return text, {"placement": "invalid_token", "reason": "Skipped: propagation supports one non-module token."}
    if operation == "insert":
        return _insert_focus_token_near_context(text, edit_tokens[0], source_context)
    if operation == "replace":
        return _replace_focus_token(text, edit_tokens[0], source_context)
    return text, {"placement": "invalid_operation", "reason": "Skipped: invalid operation."}

def preview_focus_edit_propagation(
    project: Project,
    source_line_id: str,
    selected_node_ids: List[str],
    operation: str,
    edit_token: str,
    target_line_ids: List[str] = None,
    example_limit: int = 5,
) -> Dict[str, Any]:
    source_context = _find_source_token_context(project, source_line_id, selected_node_ids)
    target_line_count = 0
    affected_line_count = 0
    skipped_module_structure_count = 0
    examples = []

    if not source_context:
        return {
            "operation": operation,
            "target_line_count": 0,
            "affected_line_count": 0,
            "skipped_module_structure_count": 0,
            "source_context": {},
            "examples": [],
            "error": "Select one token from the focused line before propagating.",
        }

    for line in project.prompt_lines:
        if not _line_in_targets(line, target_line_ids):
            continue
        if line.id == source_line_id:
            continue
        target_line_count += 1
        after, placement = _focus_propagation_transform_text(
            line.current_text,
            operation,
            edit_token,
            source_context,
        )
        if after == line.current_text:
            continue
        if _batch_text_edit_changes_module_structure(line.current_text, after):
            skipped_module_structure_count += 1
            continue

        affected_line_count += 1
        if len(examples) < example_limit:
            examples.append({
                "line_id": line.id,
                "file": line.original_file_name,
                "line_number": line.original_index + 1,
                "before": line.current_text,
                "after": after,
                "placement": placement,
            })

    return {
        "operation": operation,
        "target_line_count": target_line_count,
        "affected_line_count": affected_line_count,
        "skipped_module_structure_count": skipped_module_structure_count,
        "source_context": source_context,
        "examples": examples,
        "error": "",
    }

def apply_focus_edit_propagation(
    project: Project,
    source_line_id: str,
    selected_node_ids: List[str],
    operation: str,
    edit_token: str,
    target_line_ids: List[str] = None,
) -> Project:
    source_context = _find_source_token_context(project, source_line_id, selected_node_ids)
    if not source_context:
        return project

    changed = False
    for line in project.prompt_lines:
        if not _line_in_targets(line, target_line_ids):
            continue
        if line.id == source_line_id:
            continue
        after, _placement = _focus_propagation_transform_text(
            line.current_text,
            operation,
            edit_token,
            source_context,
        )
        if after == line.current_text:
            continue
        if _batch_text_edit_changes_module_structure(line.current_text, after):
            continue

        line.current_text = after
        line.tokens = parse_prompt(after)
        line.edited = True
        changed = True

    if changed:
        return build_graph(project)
    return project

def get_display_tokens(line) -> List[str]:
    from core.parser import extract_mod_info
    tokens = []
    for t in line.tokens:
        info = extract_mod_info(t)
        if info["type"] == "inline":
            if info["content"].strip():
                tokens.append(info["content"].strip())
            continue
        if info["type"] in ("open", "close"):
            continue
        tokens.append(t)
    return tokens

def get_display_tokens_from_text(text: str) -> List[str]:
    from core.parser import parse_prompt, extract_mod_info
    tokens = parse_prompt(text)
    result = []
    for t in tokens:
        info = extract_mod_info(t)
        if info["type"] == "inline":
            if info["content"].strip():
                result.append(info["content"].strip())
            continue
        if info["type"] in ("open", "close"):
            continue
        result.append(t)
    return result

def _has_matching_module_close(tokens: List[str], start_idx: int, module_name: str) -> bool:
    for token in tokens[start_idx + 1:]:
        info = extract_mod_info(token)
        if info["type"] == "close" and info["name"] == module_name:
            return True
    return False

def _is_library_module_reference(tokens: List[str], idx: int, module_library: Dict[str, Any]) -> bool:
    module_library = normalize_module_library(module_library)
    info = extract_mod_info(tokens[idx])
    return (
        info["type"] == "open"
        and info["name"] in (module_library or {})
        and not _has_matching_module_close(tokens, idx, info["name"])
    )

def expand_module_library_tokens(
    tokens: List[str],
    module_library: Dict[str, Any] = None,
    disabled_modules: set = None,
    seen: Set[str] = None,
    max_depth: int = 20,
) -> List[str]:
    module_library = normalize_module_library(module_library or {})
    disabled_modules = disabled_modules or set()
    seen = seen or set()
    expanded = []

    if max_depth <= 0:
        logger.warning("Module library expansion depth limit reached.")
        return expanded

    for idx, token in enumerate(tokens):
        info = extract_mod_info(token)
        if _is_library_module_reference(tokens, idx, module_library):
            module_name = info["name"]
            if module_name in disabled_modules:
                continue
            if module_name in seen:
                logger.warning(f"Recursive module reference skipped: {module_name}")
                continue
            body_tokens = parse_prompt(get_module_body(module_library, module_name))
            expanded.extend(
                expand_module_library_tokens(
                    body_tokens,
                    module_library,
                    disabled_modules,
                    seen | {module_name},
                    max_depth - 1,
                )
            )
            continue
        expanded.append(token)

    return expanded

def validate_library_module_body(module_name: str, module_body: str) -> str:
    tokens = _parse_prompt_for_module_preset(module_body or "")
    for idx, token in enumerate(tokens):
        info = extract_mod_info(token)
        if info["type"] == "inline":
            return "Inline module tags are not supported in module library bodies for v1."
        if info["type"] == "close":
            return "Closing module tags are not supported in module library bodies for v1."
        if info["type"] == "open":
            if info["name"] == module_name:
                return "Module body cannot reference itself."
            if _has_matching_module_close(tokens, idx, info["name"]):
                return "Structural module ranges are not supported in module library bodies for v1."
    return ""

def extract_module_structure_from_text(text: str) -> List[tuple]:
    from core.parser import parse_prompt, extract_mod_info
    tokens = parse_prompt(text)
    structure = []
    for t in tokens:
        info = extract_mod_info(t)
        if info["type"] == "inline":
            structure.append(("inline", info["name"]))
        elif info["type"] == "open":
            structure.append(("open", info["name"]))
        elif info["type"] == "close":
            structure.append(("close", info["name"]))
    return structure

def get_active_tokens(line, disabled_modules: set = None, fallback_prompt: str = None, module_library: Dict[str, Any] = None) -> List[str]:
    from core.parser import extract_mod_info
    if disabled_modules is None:
        disabled_modules = set()
    module_library = normalize_module_library(module_library or {})
    active = []
    mod_stack = []
    
    for idx, t in enumerate(line.tokens):
        info = extract_mod_info(t)
        
        if info["type"] == "inline":
            if info["name"] not in disabled_modules:
                if info["content"].strip():
                    active.extend(expand_module_library_tokens(parse_prompt(info["content"]), module_library, disabled_modules))
            continue
            
        if info["type"] == "open":
            if _is_library_module_reference(line.tokens, idx, module_library):
                if info["name"] not in disabled_modules:
                    active.extend(
                        expand_module_library_tokens(
                            parse_prompt(get_module_body(module_library, info["name"])),
                            module_library,
                            disabled_modules,
                            {info["name"]},
                        )
                    )
                continue
            mod_stack.append(info["name"])
            continue
        elif info["type"] == "close":
            mod_id = info["name"]
            if mod_id in mod_stack:
                # Find last occurrence of this mod_id and slice up to it
                idx = len(mod_stack) - 1 - mod_stack[::-1].index(mod_id)
                mod_stack = mod_stack[:idx]
            else:
                logger.warning(f"Malformed module marker: closing tag </mod:{mod_id}> found without matching opening tag in line {line.id}.")
            continue
            
        # Normal token
        if any(m in disabled_modules for m in mod_stack):
            continue
            
        active.append(t)
        
    if mod_stack:
        logger.warning(f"Malformed module marker: unclosed tags {mod_stack} at end of line {line.id}.")
        
    if not active and fallback_prompt:
        active = [fallback_prompt]
        
    return active

def get_available_modules(project: Project) -> List[str]:
    from core.parser import extract_mod_info
    modules = set(get_project_module_library(project))
    for line in project.prompt_lines:
        for t in line.tokens:
            info = extract_mod_info(t)
            if info["name"]:
                modules.add(info["name"])
    return sorted(list(modules))

def _rename_module_token(token: str, old_name: str, new_name: str) -> tuple[str, str]:
    from core.parser import extract_mod_info

    info = extract_mod_info(token)
    if info["name"] != old_name:
        return token, "none"

    stripped = token.strip()
    leading_len = len(token) - len(token.lstrip())
    trailing_len = len(token) - len(token.rstrip())
    leading = token[:leading_len]
    trailing = token[len(token) - trailing_len:] if trailing_len else ""

    def with_original_padding(value: str) -> str:
        return f"{leading}{value}{trailing}"

    if info["type"] == "inline":
        expected = f"<mod:{old_name}>{info['content']}</mod:{old_name}>"
        if stripped != expected:
            return token, "none"
        return with_original_padding(f"<mod:{new_name}>{info['content']}</mod:{new_name}>"), "inline"
    if info["type"] == "open":
        if stripped != f"<mod:{old_name}>":
            return token, "none"
        return with_original_padding(f"<mod:{new_name}>"), "open"
    if info["type"] == "close":
        if stripped != f"</mod:{old_name}>":
            return token, "none"
        return with_original_padding(f"</mod:{new_name}>"), "close"
    return token, "none"

def _is_malformed_module_token(token: str, module_name: str) -> bool:
    from core.parser import extract_mod_info

    info = extract_mod_info(token)
    if info["name"] != module_name:
        return False
    renamed_token, rename_type = _rename_module_token(token, module_name, module_name)
    return info["type"] in ("inline", "open", "close") and rename_type == "none"

def preview_rename_module(
    project: Project,
    old_name: str,
    new_name: str,
    example_limit: int = 5
) -> Dict[str, Any]:
    from core.parser import extract_mod_info

    affected_line_count = 0
    marker_occurrence_count = 0
    inline_occurrence_count = 0
    open_marker_count = 0
    close_marker_count = 0
    malformed_marker_count = 0
    examples = []

    for line in project.prompt_lines:
        if line.deleted:
            continue

        after_tokens = list(line.tokens)
        changed = False
        mod_stack = []

        for idx, token in enumerate(line.tokens):
            info = extract_mod_info(token)

            if _is_malformed_module_token(token, old_name):
                malformed_marker_count += 1
                continue

            if info["type"] == "inline":
                if info["name"] == old_name:
                    marker_occurrence_count += 1
                    inline_occurrence_count += 1
                    after_tokens[idx], _ = _rename_module_token(token, old_name, new_name)
                    changed = True
                continue

            if info["type"] == "open":
                if info["name"] == old_name:
                    marker_occurrence_count += 1
                    open_marker_count += 1
                    after_tokens[idx], _ = _rename_module_token(token, old_name, new_name)
                    changed = True
                mod_stack.append(info["name"])
                continue

            if info["type"] == "close":
                if info["name"] == old_name:
                    marker_occurrence_count += 1
                    close_marker_count += 1
                    after_tokens[idx], _ = _rename_module_token(token, old_name, new_name)
                    changed = True

                if info["name"] in mod_stack:
                    stack_idx = len(mod_stack) - 1 - mod_stack[::-1].index(info["name"])
                    mod_stack = mod_stack[:stack_idx]
                elif info["name"] == old_name:
                    malformed_marker_count += 1

        malformed_marker_count += sum(1 for name in mod_stack if name == old_name)

        if changed:
            affected_line_count += 1
            if len(examples) < example_limit:
                examples.append({
                    "line_id": line.id,
                    "file": line.original_file_name,
                    "line_number": line.current_index + 1,
                    "before": line.current_text,
                    "after": ", ".join(after_tokens),
                })

    return {
        "old_name": old_name,
        "new_name": new_name,
        "affected_line_count": affected_line_count,
        "marker_occurrence_count": marker_occurrence_count,
        "inline_occurrence_count": inline_occurrence_count,
        "open_marker_count": open_marker_count,
        "close_marker_count": close_marker_count,
        "malformed_marker_count": malformed_marker_count,
        "examples": examples,
    }

def rename_module(project: Project, old_name: str, new_name: str) -> Project:
    changed = False

    for line in project.prompt_lines:
        if line.deleted:
            continue

        new_tokens = []
        line_changed = False
        for token in line.tokens:
            renamed_token, rename_type = _rename_module_token(token, old_name, new_name)
            new_tokens.append(renamed_token)
            if rename_type != "none":
                line_changed = True

        if line_changed:
            line.tokens = new_tokens
            _rebuild_text(line)
            changed = True

    if changed:
        return build_graph(project)
    return project

def _is_match(token: str, target_base: str, match_mode: str) -> bool:
    if is_structural_mod_marker(token):
        return False
        
    meta = extract_node_metadata(token)
    base = meta["base_word"].lower()
    
    if match_mode == "exact":
        return base == target_base
    elif match_mode == "contains":
        # Token-aware / true substring matching
        return target_base in base
    return False

def _preserve_weight(new_word: str, original_token: str) -> str:
    orig_meta = extract_node_metadata(original_token)
    if orig_meta["weight"] == 1.0:
        return new_word
        
    new_meta = extract_node_metadata(new_word)
    if new_meta["weight"] != 1.0:
        return new_word # User already supplied new weight
        
    return f"({new_word}:{orig_meta['weight']})"

def _replacement_token(new_word: str, original_token: str, preserve_weights: bool = True) -> str:
    if preserve_weights:
        return _preserve_weight(new_word, original_token)
    return new_word

def _is_safe_inline_module_content(content: str) -> bool:
    tokens = parse_prompt(content)
    if len(tokens) != 1 or tokens[0] != content.strip():
        return False

    meta = extract_node_metadata(tokens[0])
    if len(meta["phrase"]) != 1:
        return False

    return bool(meta["base_word"].strip())

def _replace_inline_module_content(token: str, module_name: str, new_content: str) -> str:
    from core.parser import extract_mod_info

    info = extract_mod_info(token)
    stripped = token.strip()
    expected = f"<mod:{module_name}>{info['content']}</mod:{module_name}>"
    if info["type"] != "inline" or info["name"] != module_name or stripped != expected:
        return token

    leading_len = len(token) - len(token.lstrip())
    trailing_len = len(token) - len(token.rstrip())
    leading = token[:leading_len]
    trailing = token[len(token) - trailing_len:] if trailing_len else ""
    return f"{leading}<mod:{module_name}>{new_content}</mod:{module_name}>{trailing}"

def _parse_prompt_for_module_preset(text: str) -> List[str]:
    tokens = []
    current = []
    paren_depth = 0
    inline_until = -1
    idx = 0

    while idx < len(text):
        if idx >= inline_until and text.startswith("<mod:", idx):
            tag_end = text.find(">", idx)
            if tag_end > idx:
                module_name = text[idx + len("<mod:"):tag_end]
                next_idx = tag_end + 1
                while next_idx < len(text) and text[next_idx].isspace():
                    next_idx += 1
                if next_idx < len(text) and text[next_idx] != ",":
                    close_tag = f"</mod:{module_name}>"
                    close_start = text.find(close_tag, tag_end + 1)
                    if close_start >= 0:
                        inline_until = close_start + len(close_tag)

        char = text[idx]
        if idx >= inline_until:
            if char == "(":
                paren_depth += 1
            elif char == ")" and paren_depth > 0:
                paren_depth -= 1
            elif char == "," and paren_depth == 0:
                token = "".join(current).strip()
                if token:
                    tokens.append(token)
                current = []
                idx += 1
                continue

        current.append(char)
        idx += 1

    token = "".join(current).strip()
    if token:
        tokens.append(token)
    return tokens

def _module_preset_structure_from_text(text: str) -> List[tuple]:
    structure = []
    for token in _parse_prompt_for_module_preset(text):
        info = extract_mod_info(token)
        if info["type"] == "inline":
            structure.append(("inline", info["name"]))
        elif info["type"] == "open":
            structure.append(("open", info["name"]))
        elif info["type"] == "close":
            structure.append(("close", info["name"]))
    return structure

def _module_preset_changes_module_structure(before: str, after: str) -> bool:
    return _module_preset_structure_from_text(before) != _module_preset_structure_from_text(after)

def _replacement_contains_module_markers(replacement_text: str) -> bool:
    for token in _parse_prompt_for_module_preset(replacement_text or ""):
        if extract_mod_info(token)["type"] in ("inline", "open", "close"):
            return True
    return False

def _replace_module_preset_in_text(text: str, module_name: str, replacement_text: str) -> tuple[str, bool, bool]:
    if _replacement_contains_module_markers(replacement_text):
        return text, False, False

    replacement_tokens = parse_prompt(replacement_text or "")
    replacement_content = ", ".join(replacement_tokens)
    tokens = _parse_prompt_for_module_preset(text)
    result_tokens = []
    changed = False
    idx = 0

    while idx < len(tokens):
        token = tokens[idx]
        info = extract_mod_info(token)

        if info["type"] == "inline" and info["name"] == module_name:
            new_token = _replace_inline_module_content(token, module_name, replacement_content)
            result_tokens.append(new_token)
            changed = changed or new_token != token
            idx += 1
            continue

        if info["type"] == "open" and info["name"] == module_name:
            close_idx = None
            malformed = False
            scan_idx = idx + 1

            while scan_idx < len(tokens):
                scan_info = extract_mod_info(tokens[scan_idx])
                if scan_info["type"] == "close" and scan_info["name"] == module_name:
                    close_idx = scan_idx
                    break
                if scan_info["type"] in ("inline", "open", "close"):
                    malformed = True
                    break
                scan_idx += 1

            if close_idx is None or malformed:
                return text, False, True

            result_tokens.append(token)
            result_tokens.extend(replacement_tokens)
            result_tokens.append(tokens[close_idx])
            changed = changed or tokens[idx + 1:close_idx] != replacement_tokens
            idx = close_idx + 1
            continue

        if info["type"] == "close" and info["name"] == module_name:
            return text, False, True

        result_tokens.append(token)
        idx += 1

    if not changed:
        return text, False, False
    return ", ".join(result_tokens), True, False

def preview_apply_module_preset(
    project: Project,
    module_name: str,
    replacement_text: str,
    target_line_ids: List[str] = None,
    example_limit: int = 5
) -> Dict[str, Any]:
    target_line_count = 0
    affected_line_count = 0
    skipped_malformed_count = 0
    skipped_module_structure_count = 0
    skipped_invalid_replacement_count = 0
    examples = []
    invalid_replacement = _replacement_contains_module_markers(replacement_text)

    for line in project.prompt_lines:
        if not _line_in_targets(line, target_line_ids):
            continue

        target_line_count += 1
        if invalid_replacement:
            skipped_invalid_replacement_count += 1
            continue

        after, changed, malformed = _replace_module_preset_in_text(
            line.current_text,
            module_name,
            replacement_text,
        )
        if malformed:
            skipped_malformed_count += 1
            continue
        if not changed:
            continue
        if _module_preset_changes_module_structure(line.current_text, after):
            skipped_module_structure_count += 1
            continue

        affected_line_count += 1
        if len(examples) < example_limit:
            examples.append({
                "line_id": line.id,
                "file": line.original_file_name,
                "line_number": line.original_index + 1,
                "before": line.current_text,
                "after": after,
            })

    return {
        "module_name": module_name,
        "replacement_text": replacement_text,
        "target_line_count": target_line_count,
        "affected_line_count": affected_line_count,
        "skipped_malformed_count": skipped_malformed_count,
        "skipped_module_structure_count": skipped_module_structure_count,
        "skipped_invalid_replacement_count": skipped_invalid_replacement_count,
        "examples": examples,
    }

def apply_module_preset(
    project: Project,
    module_name: str,
    replacement_text: str,
    target_line_ids: List[str] = None
) -> Project:
    if _replacement_contains_module_markers(replacement_text):
        return project

    changed_any = False

    for line in project.prompt_lines:
        if not _line_in_targets(line, target_line_ids):
            continue

        after, changed, malformed = _replace_module_preset_in_text(
            line.current_text,
            module_name,
            replacement_text,
        )
        if malformed or not changed:
            continue
        if _module_preset_changes_module_structure(line.current_text, after):
            continue

        line.current_text = after
        line.tokens = _parse_prompt_for_module_preset(after)
        line.edited = True
        changed_any = True

    if changed_any:
        return build_graph(project)
    return project

def _build_inline_module_token(module_name: str, module_body: str) -> str:
    body_tokens = parse_prompt(module_body or "")
    body_content = ", ".join(body_tokens)
    return f"<mod:{module_name}>{body_content}</mod:{module_name}>"

def build_module_reference_token(module_name: str) -> str:
    return f"<mod:{module_name}>"

def _build_module_reference_token(module_name: str) -> str:
    return build_module_reference_token(module_name)

def get_insert_module_reference_anchor_options(text: str) -> List[Dict[str, Any]]:
    options = []
    for idx, token in enumerate(_parse_prompt_for_module_preset(text or "")):
        if extract_mod_info(token)["type"] == "close":
            continue
        options.append({
            "index": idx,
            "token": token,
        })
    return options

def _is_neighbor_anchor_token(token: str) -> bool:
    info = extract_mod_info(token)
    return info["type"] not in ("inline", "open", "close")

def _module_range_depths(tokens: List[str]) -> List[int]:
    depths = []
    depth = 0
    for idx, token in enumerate(tokens):
        info = extract_mod_info(token)
        if info["type"] == "close" and depth > 0:
            depth -= 1
        depths.append(depth)
        if info["type"] == "open" and _has_matching_module_close(tokens, idx, info["name"]):
            depth += 1
    return depths

def collect_neighbor_patterns(project: Project, insert_token: str) -> Dict[str, Dict[str, int]]:
    patterns = {
        "before": {},
        "after": {},
    }

    for line in project.prompt_lines:
        if getattr(line, "deleted", False):
            continue
        tokens = _parse_prompt_for_module_preset(line.current_text)
        depths = _module_range_depths(tokens)
        for idx, token in enumerate(tokens):
            if token.strip() != insert_token:
                continue
            if idx > 0 and depths[idx - 1] == 0 and _is_neighbor_anchor_token(tokens[idx - 1]):
                left = tokens[idx - 1].strip()
                patterns["before"][left] = patterns["before"].get(left, 0) + 1
            if idx + 1 < len(tokens) and depths[idx + 1] == 0 and _is_neighbor_anchor_token(tokens[idx + 1]):
                right = tokens[idx + 1].strip()
                patterns["after"][right] = patterns["after"].get(right, 0) + 1

    return patterns

def infer_best_insert_position(tokens: List[str], patterns: Dict[str, Dict[str, int]]) -> tuple[int, Dict[str, Any]]:
    depths = _module_range_depths(tokens)
    best_after_neighbor = None
    for neighbor, count in sorted(patterns.get("after", {}).items(), key=lambda item: (-item[1], item[0])):
        for idx, token in enumerate(tokens):
            if depths[idx] == 0 and token.strip() == neighbor and _is_neighbor_anchor_token(token):
                best_after_neighbor = (idx, neighbor, count)
                break
        if best_after_neighbor:
            break

    if best_after_neighbor:
        idx, neighbor, count = best_after_neighbor
        return idx, {
            "placement": "before_neighbor",
            "neighbor": neighbor,
            "count": count,
            "reason": f"Inserted before: {neighbor}. Reason: learned token appeared before {neighbor} in {count} existing line(s).",
        }

    best_before_neighbor = None
    for neighbor, count in sorted(patterns.get("before", {}).items(), key=lambda item: (-item[1], item[0])):
        for idx, token in enumerate(tokens):
            if depths[idx] == 0 and token.strip() == neighbor and _is_neighbor_anchor_token(token):
                best_before_neighbor = (idx, neighbor, count)
                break
        if best_before_neighbor:
            break

    if best_before_neighbor:
        idx, neighbor, count = best_before_neighbor
        return idx + 1, {
            "placement": "after_neighbor",
            "neighbor": neighbor,
            "count": count,
            "reason": f"Inserted after: {neighbor}. Reason: learned token appeared after {neighbor} in {count} existing line(s).",
        }

    return len(tokens), {
        "placement": "fallback",
        "neighbor": "",
        "count": 0,
        "reason": "Fallback insertion: end of line. Reason: no matching learned neighbors found.",
    }

def _insert_token_in_text(
    text: str,
    insert_token: str,
    position: str,
    anchor_index: int = None,
    neighbor_patterns: Dict[str, Dict[str, int]] = None,
    learned_neighbor_fallback: str = "skip",
) -> tuple[str, bool, Dict[str, Any]]:
    tokens = _parse_prompt_for_module_preset(text or "")
    insert_idx = len(tokens)
    placement = {
        "placement": position,
        "neighbor": "",
        "count": 0,
        "reason": "",
    }

    if position == "learned_neighbor":
        insert_idx, placement = infer_best_insert_position(tokens, neighbor_patterns or {})
        if placement.get("placement") == "fallback" and learned_neighbor_fallback != "end":
            placement = {
                "placement": "skipped_no_neighbor",
                "neighbor": "",
                "count": 0,
                "reason": "Skipped: no matching learned neighbors found.",
            }
            return text, False, placement
    elif position == "start":
        insert_idx = 0
        placement["reason"] = "Inserted at start of line."
    elif position == "end":
        insert_idx = len(tokens)
        placement["reason"] = "Inserted at end of line."
    elif position in ("before", "after"):
        if anchor_index is None or anchor_index < 0 or anchor_index >= len(tokens):
            return text, False, placement
        insert_idx = anchor_index if position == "before" else anchor_index + 1
        placement["neighbor"] = tokens[anchor_index]
        placement["reason"] = f"Inserted {position} selected token: {tokens[anchor_index]}."
    else:
        return text, False, placement

    result_tokens = list(tokens)
    result_tokens.insert(insert_idx, insert_token)
    after = ", ".join(result_tokens)
    return after, after != text, placement

def _insert_module_reference_in_text(
    text: str,
    module_name: str,
    position: str,
    anchor_index: int = None,
    neighbor_patterns: Dict[str, Dict[str, int]] = None,
    learned_neighbor_fallback: str = "skip",
) -> tuple[str, bool, Dict[str, Any]]:
    return _insert_token_in_text(
        text,
        build_module_reference_token(module_name),
        position,
        anchor_index,
        neighbor_patterns,
        learned_neighbor_fallback,
    )

def _text_contains_module_reference(text: str, module_name: str) -> bool:
    module_reference = build_module_reference_token(module_name)
    return any(
        token.strip() == module_reference
        for token in _parse_prompt_for_module_preset(text or "")
    )

def preview_bulk_insert_module_reference(
    project: Project,
    module_name: str,
    position: str = "end",
    target_line_ids: List[str] = None,
    anchor_index: int = None,
    learned_neighbor_fallback: str = "skip",
    example_limit: int = 10,
) -> Dict[str, Any]:
    module_library = get_project_module_library(project)
    module_reference = build_module_reference_token(module_name)
    neighbor_patterns = collect_neighbor_patterns(project, module_reference) if position == "learned_neighbor" else {}
    target_line_count = 0
    affected_line_count = 0
    skipped_existing_count = 0
    skipped_no_neighbor_count = 0
    examples = []

    if module_name not in module_library:
        return {
            "module_name": module_name,
            "module_reference": module_reference,
            "target_line_count": 0,
            "affected_line_count": 0,
            "skipped_existing_count": 0,
            "skipped_no_neighbor_count": 0,
            "examples": [],
        }

    for line in project.prompt_lines:
        if not _line_in_targets(line, target_line_ids):
            continue

        target_line_count += 1
        if _text_contains_module_reference(line.current_text, module_name):
            skipped_existing_count += 1
            continue

        after, changed, placement = _insert_module_reference_in_text(
            line.current_text,
            module_name,
            position,
            anchor_index,
            neighbor_patterns,
            learned_neighbor_fallback,
        )
        if not changed:
            if placement.get("placement") == "skipped_no_neighbor":
                skipped_no_neighbor_count += 1
            continue

        affected_line_count += 1
        if len(examples) < example_limit:
            examples.append({
                "line_id": line.id,
                "file": line.original_file_name,
                "line_number": line.original_index + 1,
                "before": line.current_text,
                "after": after,
                "placement": placement,
            })

    return {
        "module_name": module_name,
        "module_reference": module_reference,
        "target_line_count": target_line_count,
        "affected_line_count": affected_line_count,
        "skipped_existing_count": skipped_existing_count,
        "skipped_no_neighbor_count": skipped_no_neighbor_count,
        "neighbor_patterns": neighbor_patterns,
        "examples": examples,
    }

def apply_bulk_insert_module_reference(
    project: Project,
    module_name: str,
    position: str = "end",
    target_line_ids: List[str] = None,
    anchor_index: int = None,
    learned_neighbor_fallback: str = "skip",
) -> Project:
    if module_name not in get_project_module_library(project):
        return project

    module_reference = build_module_reference_token(module_name)
    neighbor_patterns = collect_neighbor_patterns(project, module_reference) if position == "learned_neighbor" else {}
    changed_any = False
    for line in project.prompt_lines:
        if not _line_in_targets(line, target_line_ids):
            continue
        if _text_contains_module_reference(line.current_text, module_name):
            continue

        after, changed, _placement = _insert_module_reference_in_text(
            line.current_text,
            module_name,
            position,
            anchor_index,
            neighbor_patterns,
            learned_neighbor_fallback,
        )
        if not changed:
            continue

        line.current_text = after
        line.tokens = _parse_prompt_for_module_preset(after)
        line.edited = True
        changed_any = True

    if changed_any:
        return build_graph(project)
    return project

def preview_insert_module_reference(
    project: Project,
    line_id: str,
    module_name: str,
    position: str = "end",
    anchor_index: int = None,
    learned_neighbor_fallback: str = "skip",
) -> Dict[str, Any]:
    preview = preview_bulk_insert_module_reference(
        project,
        module_name,
        position=position,
        target_line_ids=[line_id],
        anchor_index=anchor_index,
        learned_neighbor_fallback=learned_neighbor_fallback,
        example_limit=1,
    )
    example = preview["examples"][0] if preview["examples"] else {}
    return {
        **preview,
        "line_id": line_id,
        "before": example.get("before", ""),
        "after": example.get("after", ""),
        "file": example.get("file", ""),
        "line_number": example.get("line_number"),
    }

def apply_insert_module_reference(
    project: Project,
    line_id: str,
    module_name: str,
    position: str = "end",
    anchor_index: int = None,
    learned_neighbor_fallback: str = "skip",
) -> Project:
    return apply_bulk_insert_module_reference(
        project,
        module_name,
        position=position,
        target_line_ids=[line_id],
        anchor_index=anchor_index,
        learned_neighbor_fallback=learned_neighbor_fallback,
    )

def _replace_create_module_targets_in_text(
    text: str,
    module_token: str,
    token_targets: Set[str],
    module_targets: Set[str],
    module_library: Dict[str, Any] = None,
) -> tuple[str, bool, bool]:
    tokens = _parse_prompt_for_module_preset(text)
    module_library = normalize_module_library(module_library or {})
    result_tokens = []
    changed = False
    idx = 0
    mod_stack = []

    while idx < len(tokens):
        token = tokens[idx]
        info = extract_mod_info(token)

        if info["type"] == "inline":
            if info["name"] in module_targets:
                result_tokens.append(module_token)
                changed = True
            else:
                result_tokens.append(token)
            idx += 1
            continue

        if info["type"] == "open":
            if info["name"] in module_targets:
                if _is_library_module_reference(tokens, idx, module_library):
                    result_tokens.append(module_token)
                    changed = True
                    idx += 1
                    continue
                if not _has_matching_module_close(tokens, idx, info["name"]):
                    return text, False, True

                close_idx = None
                malformed = False
                scan_idx = idx + 1
                while scan_idx < len(tokens):
                    scan_info = extract_mod_info(tokens[scan_idx])
                    if scan_info["type"] == "close" and scan_info["name"] == info["name"]:
                        close_idx = scan_idx
                        break
                    if scan_info["type"] in ("inline", "open", "close"):
                        malformed = True
                        break
                    scan_idx += 1

                if close_idx is None or malformed:
                    return text, False, True

                result_tokens.append(module_token)
                changed = True
                idx = close_idx + 1
                continue

            if _is_library_module_reference(tokens, idx, module_library):
                result_tokens.append(token)
                idx += 1
                continue

            mod_stack.append(info["name"])
            result_tokens.append(token)
            idx += 1
            continue

        if info["type"] == "close":
            if info["name"] in module_targets:
                return text, False, True
            if info["name"] in mod_stack:
                stack_idx = len(mod_stack) - 1 - mod_stack[::-1].index(info["name"])
                mod_stack = mod_stack[:stack_idx]
            result_tokens.append(token)
            idx += 1
            continue

        if not mod_stack and token in token_targets:
            result_tokens.append(module_token)
            changed = True
        else:
            result_tokens.append(token)
        idx += 1

    if not changed:
        return text, False, False
    return ", ".join(result_tokens), True, False

def preview_create_module_replace(
    project: Project,
    module_name: str,
    module_body: str,
    token_targets: List[str] = None,
    module_targets: List[str] = None,
    example_limit: int = 5,
) -> Dict[str, Any]:
    token_target_set = set(token_targets or [])
    module_target_set = set(module_targets or [])
    module_token = _build_module_reference_token(module_name)
    module_library = get_project_module_library(project)
    target_line_count = 0
    affected_line_count = 0
    skipped_malformed_count = 0
    examples = []
    invalid_module_body = _replacement_contains_module_markers(module_body)

    for line in project.prompt_lines:
        if line.deleted:
            continue
        target_line_count += 1
        if invalid_module_body:
            continue
        after, changed, malformed = _replace_create_module_targets_in_text(
            line.current_text,
            module_token,
            token_target_set,
            module_target_set,
            module_library,
        )
        if malformed:
            skipped_malformed_count += 1
            continue
        if not changed:
            continue

        affected_line_count += 1
        if len(examples) < example_limit:
            examples.append({
                "line_id": line.id,
                "file": line.original_file_name,
                "line_number": line.original_index + 1,
                "before": line.current_text,
                "after": after,
            })

    return {
        "module_name": module_name,
        "module_body": module_body,
        "module_token": module_token,
        "token_targets": sorted(token_target_set),
        "module_targets": sorted(module_target_set),
        "target_line_count": target_line_count,
        "affected_line_count": affected_line_count,
        "skipped_malformed_count": skipped_malformed_count,
        "examples": examples,
    }

def apply_create_module_replace(
    project: Project,
    module_name: str,
    module_body: str,
    module_type: str = DEFAULT_MODULE_TYPE,
    token_targets: List[str] = None,
    module_targets: List[str] = None,
) -> Project:
    token_target_set = set(token_targets or [])
    module_target_set = set(module_targets or [])
    module_token = _build_module_reference_token(module_name)
    module_library = get_project_module_library(project)
    if validate_library_module_body(module_name, module_body):
        return project
    if module_name in get_available_modules(project):
        return project
    set_module_entry(project, module_name, module_body, module_type)

    for line in project.prompt_lines:
        if line.deleted:
            continue
        after, changed, malformed = _replace_create_module_targets_in_text(
            line.current_text,
            module_token,
            token_target_set,
            module_target_set,
            module_library,
        )
        if malformed or not changed:
            continue
        line.current_text = after
        line.tokens = _parse_prompt_for_module_preset(after)
        line.edited = True

    return build_graph(project)

def preview_replace_with_module(
    project: Project,
    replacement_module_name: str,
    token_targets: List[str] = None,
    module_targets: List[str] = None,
    example_limit: int = 5,
) -> Dict[str, Any]:
    module_library = get_project_module_library(project)
    token_target_set = set(token_targets or [])
    module_target_set = set(module_targets or [])
    module_target_set.discard(replacement_module_name)
    module_token = _build_module_reference_token(replacement_module_name)
    target_line_count = 0
    affected_line_count = 0
    skipped_malformed_count = 0
    examples = []

    if replacement_module_name not in module_library:
        return {
            "replacement_module_name": replacement_module_name,
            "module_token": module_token,
            "token_targets": sorted(token_target_set),
            "module_targets": sorted(module_target_set),
            "target_line_count": 0,
            "affected_line_count": 0,
            "skipped_malformed_count": 0,
            "examples": [],
        }

    for line in project.prompt_lines:
        if line.deleted:
            continue
        target_line_count += 1
        after, changed, malformed = _replace_create_module_targets_in_text(
            line.current_text,
            module_token,
            token_target_set,
            module_target_set,
            module_library,
        )
        if malformed:
            skipped_malformed_count += 1
            continue
        if not changed or after == line.current_text:
            continue

        affected_line_count += 1
        if len(examples) < example_limit:
            examples.append({
                "line_id": line.id,
                "file": line.original_file_name,
                "line_number": line.original_index + 1,
                "before": line.current_text,
                "after": after,
            })

    return {
        "replacement_module_name": replacement_module_name,
        "module_token": module_token,
        "token_targets": sorted(token_target_set),
        "module_targets": sorted(module_target_set),
        "target_line_count": target_line_count,
        "affected_line_count": affected_line_count,
        "skipped_malformed_count": skipped_malformed_count,
        "examples": examples,
    }

def apply_replace_with_module(
    project: Project,
    replacement_module_name: str,
    token_targets: List[str] = None,
    module_targets: List[str] = None,
) -> Project:
    module_library = get_project_module_library(project)
    if replacement_module_name not in module_library:
        return project

    token_target_set = set(token_targets or [])
    module_target_set = set(module_targets or [])
    module_target_set.discard(replacement_module_name)
    if not token_target_set and not module_target_set:
        return project

    module_token = _build_module_reference_token(replacement_module_name)
    changed_any = False
    for line in project.prompt_lines:
        if line.deleted:
            continue
        after, changed, malformed = _replace_create_module_targets_in_text(
            line.current_text,
            module_token,
            token_target_set,
            module_target_set,
            module_library,
        )
        if malformed or not changed or after == line.current_text:
            continue
        line.current_text = after
        line.tokens = _parse_prompt_for_module_preset(after)
        line.edited = True
        changed_any = True

    if changed_any:
        return build_graph(project)
    return project

def _apply_weight_to_token(token: str, weight: float) -> str:
    base = get_base_word(token)
    if weight == 1.0:
        return base
    return f"({base}:{weight:.1f})"

def get_base_word(token: str) -> str:
    return extract_node_metadata(token)["base_word"]

def _matching_token_indexes(line, target_base: str, match_mode: str, exclude_module_contents: bool = False) -> List[tuple]:
    from core.parser import extract_mod_info

    indexes = []
    mod_stack = []
    for idx, token in enumerate(line.tokens):
        info = extract_mod_info(token)

        if info["type"] == "inline":
            if not exclude_module_contents and _is_match(token, target_base, match_mode):
                indexes.append((idx, True))
            continue

        if info["type"] == "open":
            mod_stack.append(info["name"])
            continue

        if info["type"] == "close":
            mod_id = info["name"]
            if mod_id in mod_stack:
                stack_idx = len(mod_stack) - 1 - mod_stack[::-1].index(mod_id)
                mod_stack = mod_stack[:stack_idx]
            continue

        in_module = bool(mod_stack)
        if exclude_module_contents and in_module:
            continue
        if _is_match(token, target_base, match_mode):
            indexes.append((idx, in_module))
    return indexes

def _matching_module_scope_token_indexes(line, target_base: str, match_mode: str, module_scope_name: str) -> List[tuple]:
    from core.parser import extract_mod_info

    indexes = []
    mod_stack = []
    for idx, token in enumerate(line.tokens):
        stripped = token.strip()
        if (
            stripped.startswith(f"<mod:{module_scope_name}>")
            and "</mod:" in stripped
            and not stripped.endswith(f"</mod:{module_scope_name}>")
        ):
            continue

        info = extract_mod_info(token)

        if info["type"] == "inline":
            if (
                info["name"] == module_scope_name
                and _is_safe_inline_module_content(info["content"])
                and _is_match(info["content"], target_base, match_mode)
            ):
                indexes.append((idx, "inline"))
            continue

        if info["type"] == "open":
            mod_stack.append(info["name"])
            continue

        if info["type"] == "close":
            mod_id = info["name"]
            if mod_id in mod_stack:
                stack_idx = len(mod_stack) - 1 - mod_stack[::-1].index(mod_id)
                mod_stack = mod_stack[:stack_idx]
            continue

        if module_scope_name in mod_stack and _is_match(token, target_base, match_mode):
            indexes.append((idx, "range"))
    return indexes

def _matching_module_scope_node_indexes(line, node_set: Set[str], module_scope_name: str) -> List[tuple]:
    from core.parser import extract_mod_info

    indexes = []
    mod_stack = []
    for idx, token in enumerate(line.tokens):
        stripped = token.strip()
        if (
            stripped.startswith(f"<mod:{module_scope_name}>")
            and "</mod:" in stripped
            and not stripped.endswith(f"</mod:{module_scope_name}>")
        ):
            continue

        info = extract_mod_info(token)
        nid = line.node_path[idx] if idx < len(line.node_path) else None

        if info["type"] == "inline":
            if (
                info["name"] == module_scope_name
                and nid in node_set
                and _is_safe_inline_module_content(info["content"])
            ):
                indexes.append((idx, "inline"))
            continue

        if info["type"] == "open":
            mod_stack.append(info["name"])
            continue

        if info["type"] == "close":
            mod_id = info["name"]
            if mod_id in mod_stack:
                stack_idx = len(mod_stack) - 1 - mod_stack[::-1].index(mod_id)
                mod_stack = mod_stack[:stack_idx]
            continue

        if module_scope_name in mod_stack and nid in node_set:
            indexes.append((idx, "range"))
    return indexes

def count_matches(project: Project, target_word: str, target_line_ids: List[str] = None, match_mode: str = "exact") -> int:
    target_base = extract_node_metadata(target_word)["base_word"].lower()
    count = 0
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
        for t in line.tokens:
            if _is_match(t, target_base, match_mode):
                count += 1
    return count

def preview_rename_word_global(
    project: Project,
    target_word: str,
    new_word: str,
    target_line_ids: List[str] = None,
    match_mode: str = "exact",
    preserve_weights: bool = True,
    exclude_module_contents: bool = False,
    example_limit: int = 5,
    module_scope_name: str = None
) -> Dict[str, Any]:
    from core.parser import extract_mod_info

    target_base = extract_node_metadata(target_word)["base_word"].lower()
    total_matches = 0
    weighted_matches = 0
    module_matches = 0
    affected_line_count = 0
    examples = []

    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue

        if module_scope_name:
            matches = _matching_module_scope_token_indexes(line, target_base, match_mode, module_scope_name)
            module_matches += len(matches)
        else:
            raw_module_matches = _matching_token_indexes(line, target_base, match_mode, False)
            module_matches += sum(1 for _, in_module in raw_module_matches if in_module)
            matches = _matching_token_indexes(line, target_base, match_mode, exclude_module_contents)
        if not matches:
            continue

        affected_line_count += 1
        total_matches += len(matches)
        weighted_matches += sum(
            1 for idx, match_kind in matches
            if extract_node_metadata(
                extract_mod_info(line.tokens[idx])["content"] if match_kind == "inline" else line.tokens[idx]
            )["weight"] != 1.0
        )

        if len(examples) < example_limit:
            after_tokens = list(line.tokens)
            for idx, match_kind in matches:
                if match_kind == "inline":
                    info = extract_mod_info(line.tokens[idx])
                    new_content = _replacement_token(new_word, info["content"], preserve_weights)
                    after_tokens[idx] = _replace_inline_module_content(line.tokens[idx], module_scope_name, new_content)
                else:
                    after_tokens[idx] = _replacement_token(new_word, line.tokens[idx], preserve_weights)
            examples.append({
                "line_id": line.id,
                "file": line.original_file_name,
                "line_number": line.original_index + 1,
                "before": line.current_text,
                "after": ", ".join(after_tokens),
            })

    return {
        "total_matches": total_matches,
        "affected_line_count": affected_line_count,
        "weighted_token_match_count": weighted_matches,
        "module_related_match_count": module_matches,
        "examples": examples,
    }

def rename_word_global(
    project: Project,
    target_word: str,
    new_word: str,
    target_line_ids: List[str] = None,
    match_mode: str = "exact",
    preserve_weights: bool = True,
    exclude_module_contents: bool = False,
    module_scope_name: str = None
) -> Project:
    from core.parser import extract_mod_info

    changed = False
    target_base = extract_node_metadata(target_word)["base_word"].lower()
    
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
        line_changed = False
        matches = (
            _matching_module_scope_token_indexes(line, target_base, match_mode, module_scope_name)
            if module_scope_name
            else _matching_token_indexes(line, target_base, match_mode, exclude_module_contents)
        )
        for i, match_kind in matches:
            if match_kind == "inline":
                info = extract_mod_info(line.tokens[i])
                new_content = _replacement_token(new_word, info["content"], preserve_weights)
                line.tokens[i] = _replace_inline_module_content(line.tokens[i], module_scope_name, new_content)
            else:
                line.tokens[i] = _replacement_token(new_word, line.tokens[i], preserve_weights)
            line_changed = True
            changed = True
        if line_changed:
            _rebuild_text(line)
    if changed:
        return build_graph(project)
    return project

def delete_word_global(project: Project, target_word: str, target_line_ids: List[str] = None, match_mode: str = "exact") -> Project:
    changed = False
    target_base = extract_node_metadata(target_word)["base_word"].lower()
    
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        original_len = len(line.tokens)
        line.tokens = [t for t in line.tokens if not _is_match(t, target_base, match_mode)]
        
        if len(line.tokens) != original_len:
            _rebuild_text(line)
            changed = True
            
    if changed:
        return build_graph(project)
    return project

def insert_word_global(project: Project, target_word: str, new_word: str, position: str = "after", target_line_ids: List[str] = None, match_mode: str = "exact") -> Project:
    changed = False
    target_base = extract_node_metadata(target_word)["base_word"].lower()
    
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        new_tokens = []
        line_changed = False
        for t in line.tokens:
            if _is_match(t, target_base, match_mode):
                if position == "before":
                    new_tokens.append(new_word)
                    new_tokens.append(t)
                else:
                    new_tokens.append(t)
                    new_tokens.append(new_word)
                line_changed = True
                changed = True
            else:
                new_tokens.append(t)
                
        if line_changed:
            line.tokens = new_tokens
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def rename_node(project: Project, node_id: str, new_word: str, target_line_ids: List[str] = None) -> Project:
    changed = False
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        line_changed = False
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            if nid == node_id:
                line.tokens[idx] = new_word
                line.node_path[idx] = "__pending__"
                line_changed = True
                changed = True
                
        if line_changed:
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def delete_nodes(
    project: Project,
    node_ids: List[str],
    target_line_ids: List[str] = None,
    module_scope_name: str = None
) -> Project:
    changed = False
    node_set = set(node_ids)
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue

        if module_scope_name:
            matches = _matching_module_scope_node_indexes(line, node_set, module_scope_name)
            if not matches:
                continue

            inline_indexes = {idx for idx, match_kind in matches if match_kind == "inline"}
            range_indexes = {idx for idx, match_kind in matches if match_kind == "range"}
            new_tokens = []
            new_node_path = []
            for idx, token in enumerate(line.tokens):
                nid = line.node_path[idx] if idx < len(line.node_path) else None
                if idx in inline_indexes:
                    new_tokens.append(_replace_inline_module_content(token, module_scope_name, ""))
                    new_node_path.append(nid)
                elif idx in range_indexes:
                    continue
                else:
                    new_tokens.append(token)
                    new_node_path.append(nid)

            line.tokens = new_tokens
            line.node_path = new_node_path
            _rebuild_text(line)
            changed = True
            continue
            
        new_tokens = []
        new_node_path = []
        line_changed = False
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            if nid in node_set:
                line_changed = True
                changed = True
                continue
            new_tokens.append(token)
            new_node_path.append(nid)
            
        if line_changed:
            line.tokens = new_tokens
            line.node_path = new_node_path
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def preview_delete_nodes(
    project: Project,
    node_ids: List[str],
    target_line_ids: List[str] = None,
    example_limit: int = 5,
    module_scope_name: str = None
) -> Dict[str, Any]:
    from core.parser import extract_mod_info

    node_set = set(node_ids)
    selected_node_count = sum(1 for nid in node_ids if nid in project.nodes)
    affected_line_count = 0
    tokens_to_delete_count = 0
    module_related_delete_count = 0
    examples = []

    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue

        delete_indexes = []
        inline_clear_indexes = []
        module_related_indexes = set()
        mod_stack = []

        if module_scope_name:
            for idx, match_kind in _matching_module_scope_node_indexes(line, node_set, module_scope_name):
                if match_kind == "inline":
                    inline_clear_indexes.append(idx)
                else:
                    delete_indexes.append(idx)
                module_related_indexes.add(idx)
        else:
            for idx, token in enumerate(line.tokens):
                info = extract_mod_info(token)
                token_in_module = bool(mod_stack) or info["type"] == "inline"
                nid = line.node_path[idx] if idx < len(line.node_path) else None

                if nid in node_set:
                    delete_indexes.append(idx)
                    if token_in_module:
                        module_related_indexes.add(idx)

                if info["type"] == "open":
                    mod_stack.append(info["name"])
                elif info["type"] == "close":
                    mod_id = info["name"]
                    if mod_id in mod_stack:
                        stack_idx = len(mod_stack) - 1 - mod_stack[::-1].index(mod_id)
                        mod_stack = mod_stack[:stack_idx]

        if not delete_indexes and not inline_clear_indexes:
            continue

        affected_line_count += 1
        tokens_to_delete_count += len(delete_indexes) + len(inline_clear_indexes)
        module_related_delete_count += len(module_related_indexes)

        if len(examples) < example_limit:
            delete_index_set = set(delete_indexes)
            inline_clear_index_set = set(inline_clear_indexes)
            after_tokens = []
            for idx, token in enumerate(line.tokens):
                if idx in delete_index_set:
                    continue
                if idx in inline_clear_index_set:
                    after_tokens.append(_replace_inline_module_content(token, module_scope_name, ""))
                else:
                    after_tokens.append(token)
            examples.append({
                "line_id": line.id,
                "file": line.original_file_name,
                "line_number": line.original_index + 1,
                "before": line.current_text,
                "after": ", ".join(after_tokens),
            })

    return {
        "selected_node_count": selected_node_count,
        "affected_line_count": affected_line_count,
        "tokens_to_delete_count": tokens_to_delete_count,
        "module_related_delete_count": module_related_delete_count,
        "examples": examples,
    }

def insert_node(project: Project, target_node_id: str, new_word: str, position: str = "after", target_line_ids: List[str] = None) -> Project:
    changed = False
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        new_tokens = []
        new_node_path = []
        line_changed = False
        
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            if nid == target_node_id:
                if position == "before":
                    new_tokens.append(new_word)
                    new_node_path.append("__pending__")
                    new_tokens.append(token)
                    new_node_path.append(nid)
                else:
                    new_tokens.append(token)
                    new_node_path.append(nid)
                    new_tokens.append(new_word)
                    new_node_path.append("__pending__")
                line_changed = True
                changed = True
            else:
                new_tokens.append(token)
                new_node_path.append(nid)
                
        if line_changed:
            line.tokens = new_tokens
            line.node_path = new_node_path
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def duplicate_nodes(project: Project, node_ids: List[str], target_line_ids: List[str] = None) -> Project:
    changed = False
    node_set = set(node_ids)
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        new_tokens = []
        new_node_path = []
        line_changed = False
        
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            new_tokens.append(token)
            new_node_path.append(nid)
            if nid in node_set:
                new_tokens.append(token)
                new_node_path.append("__pending__")
                line_changed = True
                changed = True
                
        if line_changed:
            line.tokens = new_tokens
            line.node_path = new_node_path
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def move_nodes(project: Project, node_ids: List[str], target_node_id: str, position: str = "after", target_line_ids: List[str] = None) -> Project:
    words_to_move = []
    for node_id in node_ids:
        if node_id in project.nodes:
            words_to_move.append(project.nodes[node_id].word)
            
    project = delete_nodes(project, node_ids, target_line_ids)
    
    if target_node_id in project.nodes:
        if position == "after":
            for w in reversed(words_to_move):
                project = insert_node(project, target_node_id, w, "after", target_line_ids)
        else:
            for w in words_to_move:
                project = insert_node(project, target_node_id, w, "before", target_line_ids)
                
    return project

def insert_subgraph(project: Project, target_node_id: str, words: List[str], position: str = "after", target_line_ids: List[str] = None) -> Project:
    changed = False
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        new_tokens = []
        new_node_path = []
        line_changed = False
        
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            if nid == target_node_id:
                if position == "before":
                    for w in words:
                        new_tokens.append(w)
                        new_node_path.append("__pending__")
                    new_tokens.append(token)
                    new_node_path.append(nid)
                else:
                    new_tokens.append(token)
                    new_node_path.append(nid)
                    for w in words:
                        new_tokens.append(w)
                        new_node_path.append("__pending__")
                line_changed = True
                changed = True
            else:
                new_tokens.append(token)
                new_node_path.append(nid)
                
        if line_changed:
            line.tokens = new_tokens
            line.node_path = new_node_path
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def replace_with_subgraph(project: Project, target_node_ids: List[str], words: List[str], target_line_ids: List[str] = None) -> Project:
    changed = False
    target_set = set(target_node_ids)
    
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        line_targets = [nid for nid in line.node_path if nid in target_set]
        if not line_targets:
            continue
            
        first_target_idx = -1
        for idx, nid in enumerate(line.node_path):
            if nid in target_set:
                first_target_idx = idx
                break
                
        new_tokens = []
        new_node_path = []
        
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            
            if idx == first_target_idx:
                for w in words:
                    new_tokens.append(w)
                    new_node_path.append("__pending__")
                    
            if nid in target_set:
                continue
                
            new_tokens.append(token)
            new_node_path.append(nid)
            
        line.tokens = new_tokens
        line.node_path = new_node_path
        _rebuild_text(line)
        changed = True
            
    if changed:
        return build_graph(project)
    return project

def merge_duplicates_in_line(project: Project, line_id: str) -> Project:
    target_line = project.line_map.get(line_id)
    if not target_line or target_line.deleted:
        return project

    word_indices = {}
    for i, word in enumerate(target_line.tokens):
        word_lower = word.lower()
        if word_lower not in word_indices:
            word_indices[word_lower] = []
        word_indices[word_lower].append(i)

    indices_to_remove = set()
    for word_lower, indices in word_indices.items():
        if len(indices) <= 1:
            continue
        
        max_score = -1
        best_index = -1
        for idx in indices:
            node_id = target_line.node_path[idx] if idx < len(target_line.node_path) else None
            degree = 0
            freq = 0
            if node_id and node_id in project.nodes:
                node = project.nodes[node_id]
                degree = len(node.prev_node_ids) + len(node.next_node_ids)
                freq = node.count
                
            score = (degree * 10000) + (freq * 100) - idx
            if score > max_score:
                max_score = score
                best_index = idx
        
        for idx in indices:
            if idx != best_index:
                indices_to_remove.add(idx)
                
    if indices_to_remove:
        new_tokens = [t for i, t in enumerate(target_line.tokens) if i not in indices_to_remove]
        target_line.current_text = ", ".join(new_tokens)
        target_line.tokens = parse_prompt(target_line.current_text)
        target_line.edited = True
        return build_graph(project)
        
    return project

def merge_duplicates_all_lines(project: Project) -> Project:
    changed_any = False
    for target_line in project.prompt_lines:
        if target_line.deleted:
            continue
            
        word_indices = {}
        for i, word in enumerate(target_line.tokens):
            word_lower = word.lower()
            if word_lower not in word_indices:
                word_indices[word_lower] = []
            word_indices[word_lower].append(i)

        indices_to_remove = set()
        for word_lower, indices in word_indices.items():
            if len(indices) <= 1:
                continue
            
            max_score = -1
            best_index = -1
            for idx in indices:
                node_id = target_line.node_path[idx] if idx < len(target_line.node_path) else None
                degree = 0
                freq = 0
                if node_id and node_id in project.nodes:
                    node = project.nodes[node_id]
                    degree = len(node.prev_node_ids) + len(node.next_node_ids)
                    freq = node.count
                    
                score = (degree * 10000) + (freq * 100) - idx
                if score > max_score:
                    max_score = score
                    best_index = idx
            
            for idx in indices:
                if idx != best_index:
                    indices_to_remove.add(idx)
                    
        if indices_to_remove:
            new_tokens = [t for i, t in enumerate(target_line.tokens) if i not in indices_to_remove]
            target_line.current_text = ", ".join(new_tokens)
            target_line.tokens = parse_prompt(target_line.current_text)
            target_line.edited = True
            changed_any = True
            
    if changed_any:
        return build_graph(project)
    return project

def apply_node_weight(
    project: Project,
    node_ids: list[str],
    weight: float,
    target_line_ids: list[str] = None,
    module_scope_name: str = None
) -> Project:
    target_words = []
    for nid in node_ids:
        if nid in project.nodes:
            target_words.append(get_base_word(project.nodes[nid].word).lower())
            
    if not target_words:
        return project
        
    changed_any = False
    for line in project.prompt_lines:
        if line.deleted:
            continue
        if target_line_ids and line.id not in target_line_ids:
            continue

        if module_scope_name:
            node_set = set(node_ids)
            matches = _matching_module_scope_node_indexes(line, node_set, module_scope_name)
            if not matches:
                continue

            new_tokens = list(line.tokens)
            line_changed = False
            for idx, match_kind in matches:
                if match_kind == "inline":
                    info = extract_mod_info(line.tokens[idx])
                    new_content = _apply_weight_to_token(info["content"], weight)
                    new_token = _replace_inline_module_content(line.tokens[idx], module_scope_name, new_content)
                else:
                    new_token = _apply_weight_to_token(line.tokens[idx], weight)

                if new_token != line.tokens[idx]:
                    new_tokens[idx] = new_token
                    line_changed = True

            if line_changed:
                line.current_text = ", ".join(new_tokens)
                line.tokens = new_tokens
                line.edited = True
                changed_any = True
            continue
            
        new_tokens = []
        line_changed = False
        for token in line.tokens:
            base = get_base_word(token)
            if base.lower() in target_words:
                new_token = _apply_weight_to_token(token, weight)
                if new_token != token:
                    new_tokens.append(new_token)
                    line_changed = True
                else:
                    new_tokens.append(token)
            else:
                new_tokens.append(token)
                
        if line_changed:
            line.current_text = ", ".join(new_tokens)
            line.tokens = parse_prompt(line.current_text)
            line.edited = True
            changed_any = True
            
    if changed_any:
        return build_graph(project)
    return project

def preview_apply_node_weight(
    project: Project,
    node_ids: list[str],
    weight: float,
    target_line_ids: list[str] = None,
    example_limit: int = 5,
    module_scope_name: str = None
) -> Dict[str, Any]:
    target_words = []
    for nid in node_ids:
        if nid in project.nodes:
            target_words.append(get_base_word(project.nodes[nid].word).lower())

    selected_node_count = len(target_words)
    affected_line_count = 0
    tokens_to_update_count = 0
    already_target_weight_count = 0
    weighted_token_before_count = 0
    examples = []

    if not target_words:
        return {
            "selected_node_count": selected_node_count,
            "affected_line_count": affected_line_count,
            "tokens_to_update_count": tokens_to_update_count,
            "already_target_weight_count": already_target_weight_count,
            "weighted_token_before_count": weighted_token_before_count,
            "examples": examples,
        }

    target_word_set = set(target_words)
    for line in project.prompt_lines:
        if line.deleted:
            continue
        if target_line_ids and line.id not in target_line_ids:
            continue

        new_tokens = []
        line_has_match = False
        line_changed = False

        if module_scope_name:
            matches = _matching_module_scope_node_indexes(line, set(node_ids), module_scope_name)
            if not matches:
                continue

            new_tokens = list(line.tokens)
            for idx, match_kind in matches:
                line_has_match = True
                source_token = line.tokens[idx]
                if match_kind == "inline":
                    info = extract_mod_info(source_token)
                    source_token = info["content"]

                if extract_node_metadata(source_token)["weight"] != 1.0:
                    weighted_token_before_count += 1

                new_content = _apply_weight_to_token(source_token, weight)
                if match_kind == "inline":
                    new_token = _replace_inline_module_content(line.tokens[idx], module_scope_name, new_content)
                else:
                    new_token = new_content

                if new_token != line.tokens[idx]:
                    tokens_to_update_count += 1
                    line_changed = True
                else:
                    already_target_weight_count += 1
                new_tokens[idx] = new_token
        else:
            for token in line.tokens:
                base = get_base_word(token)
                if base.lower() in target_word_set:
                    line_has_match = True
                    if extract_node_metadata(token)["weight"] != 1.0:
                        weighted_token_before_count += 1

                    new_token = _apply_weight_to_token(token, weight)

                    if new_token != token:
                        tokens_to_update_count += 1
                        line_changed = True
                    else:
                        already_target_weight_count += 1
                    new_tokens.append(new_token)
                else:
                    new_tokens.append(token)

        if not line_has_match:
            continue

        affected_line_count += 1
        if len(examples) < example_limit:
            examples.append({
                "line_id": line.id,
                "file": line.original_file_name,
                "line_number": line.original_index + 1,
                "before": line.current_text,
                "after": ", ".join(new_tokens) if line_changed else line.current_text,
            })

    return {
        "selected_node_count": selected_node_count,
        "affected_line_count": affected_line_count,
        "tokens_to_update_count": tokens_to_update_count,
        "already_target_weight_count": already_target_weight_count,
        "weighted_token_before_count": weighted_token_before_count,
        "examples": examples,
    }
