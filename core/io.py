import copy
import dataclasses
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from core.graph_builder import build_graph
from core.generation_settings_analysis import extract_generation_settings_from_metadata
from core.negative_prompt_analysis import get_metadata_negative_prompt
from core.parser import parse_prompt
from core.project import Project, PromptLine, PromptNode

logger = logging.getLogger(__name__)

SPECIAL_GALLERY_LINE_TYPES = {"separator", "workbench"}
FINAL_EXPORT_MANIFEST_VERSION = 2
FINAL_EXPORT_PATH_CONTRACT = "portable-relative-v1"

IMAGE_METADATA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_NATURAL_SORT_SPLIT_RE = re.compile(r"(\d+)")
PROMPT_METADATA_KEYS = {
    "parameters",
    "prompt",
    "positive",
    "positive_prompt",
    "description",
    "caption",
}

A1111_PARAM_START_KEYS = (
    "Steps",
    "Sampler",
    "Schedule type",
    "CFG scale",
    "Seed",
    "Size",
    "Model hash",
    "Model",
    "Denoising strength",
    "Clip skip",
    "RNG",
    "Hires Module 1",
    "Hires CFG Scale",
    "Hires upscale",
    "Hires steps",
    "Hires upscaler",
    "Lora hashes",
    "Version",
    "Module 1",
)


def natural_sort_key(text) -> list[tuple[int, object]]:
    """Return a case-insensitive natural sort key for human filename ordering."""
    key = []
    for part in _NATURAL_SORT_SPLIT_RE.split(str(text or "")):
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.casefold()))
    return key


def _default_project_metadata() -> dict:
    return {
        "image_imports": [],
        "comfyui_workflows": [],
        "generation_jobs": [],
        "candidate_images": [],
    }


def _normalize_project_metadata(metadata) -> dict:
    normalized = _default_project_metadata()
    if isinstance(metadata, dict):
        normalized.update(metadata)
    return normalized


def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def _short_metadata_preview(value, limit: int = 240) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _stringify_metadata_value(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _json_safe_source_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes omitted>"
    if isinstance(value, dict):
        return {str(key): _json_safe_source_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_source_value(item) for item in value]
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def _decode_exif_user_comment(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, (bytes, bytearray)):
        return value

    data = bytes(value)
    prefixes = {
        b"ASCII\x00\x00\x00": "ascii",
        b"UNICODE\x00": "utf-16-be",
        b"JIS\x00\x00\x00\x00\x00": "shift_jis",
    }
    for prefix, encoding in prefixes.items():
        if data.startswith(prefix):
            data = data[len(prefix):]
            try:
                return data.decode(encoding, errors="replace").rstrip("\x00")
            except LookupError:
                break
    return data.decode("utf-8", errors="replace").rstrip("\x00")


def _read_exif_metadata(image) -> dict:
    try:
        from PIL import ExifTags
    except Exception:
        return {}

    try:
        exif = image.getexif()
    except Exception:
        return {}
    if not exif:
        return {}

    metadata = {}
    for tag_id, value in exif.items():
        tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
        if tag_name not in {"ImageDescription", "UserComment", "Software"}:
            continue
        if tag_name == "UserComment":
            value = _decode_exif_user_comment(value)
        if isinstance(value, (str, int, float, bool)):
            metadata[tag_name] = value
    return metadata


def _read_image_metadata(file_path: str) -> tuple[int | None, int | None, dict]:
    try:
        from PIL import Image
    except Exception:
        return None, None, {}

    try:
        with Image.open(file_path) as image:
            width, height = image.size
            metadata = {
                str(key): value
                for key, value in getattr(image, "info", {}).items()
                if isinstance(value, (str, int, float, bool))
            }
            metadata.update(_read_exif_metadata(image))
            return width, height, metadata
    except Exception as exc:
        logger.warning(f"Could not read image metadata from {file_path}: {exc}")
        raise


def _find_prompt_preview(metadata: dict) -> str:
    for key, value in metadata.items():
        key_lower = key.lower()
        if key_lower in PROMPT_METADATA_KEYS or "prompt" in key_lower:
            if _is_workflow_json_prompt_text(value):
                continue
            return _short_metadata_preview(value)
    return ""


def _api_workflow_nodes(value):
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("prompt"), dict):
        return value["prompt"]
    if isinstance(value.get("nodes"), dict):
        return value["nodes"]
    return value


def _looks_like_comfy_api_workflow(value) -> bool:
    nodes = _api_workflow_nodes(value)
    if not isinstance(nodes, dict) or not nodes:
        return False
    return any(
        isinstance(node, dict)
        and ("class_type" in node or "inputs" in node)
        and isinstance(node.get("inputs", {}), dict)
        for node in nodes.values()
    )


def _parse_metadata_json(value):
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped[0] not in ("{", "["):
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _is_workflow_json_prompt_text(value) -> bool:
    return _looks_like_comfy_api_workflow(_parse_metadata_json(value))


def _has_comfy_workflow_metadata(metadata: dict) -> bool:
    lowered_metadata = {key.lower(): value for key, value in metadata.items()}
    workflow_value = lowered_metadata.get("workflow")
    if workflow_value is not None and _parse_metadata_json(workflow_value) is not None:
        return True
    return _is_workflow_json_prompt_text(lowered_metadata.get("prompt"))


def _looks_like_a1111_param_line(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(f"{key}:") for key in A1111_PARAM_START_KEYS)


def _split_a1111_sections(parameters: str) -> tuple[str, str, str]:
    text = parameters.replace("\r\n", "\n").replace("\r", "\n")
    marker = "\nNegative prompt:"
    if marker in text:
        positive, remainder = text.split(marker, 1)
        remainder_lines = remainder.split("\n")
        params_index = next(
            (index for index, line in enumerate(remainder_lines) if _looks_like_a1111_param_line(line)),
            None,
        )
        if params_index is None:
            return positive.strip(), remainder.strip(), ""
        negative = "\n".join(remainder_lines[:params_index]).strip()
        raw_generation_params = "\n".join(remainder_lines[params_index:]).strip()
        return positive.strip(), negative, raw_generation_params

    lines = text.split("\n")
    params_index = next(
        (index for index, line in enumerate(lines) if _looks_like_a1111_param_line(line)),
        None,
    )
    if params_index is None:
        return text.strip(), "", ""
    positive = "\n".join(lines[:params_index]).strip()
    raw_generation_params = "\n".join(lines[params_index:]).strip()
    return positive, "", raw_generation_params


def _split_a1111_param_chunks(raw_generation_params: str) -> list[str]:
    chunks = []
    current = []
    quote_char = ""
    escape_next = False
    for char in raw_generation_params.replace("\n", ", "):
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


def _parse_a1111_generation_params(raw_generation_params: str) -> dict:
    params = {}
    current_key = ""
    for chunk in _split_a1111_param_chunks(raw_generation_params):
        if ":" not in chunk:
            if current_key:
                params[current_key] = f"{params[current_key]}, {chunk}".strip()
            continue
        key, value = chunk.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            if current_key:
                params[current_key] = f"{params[current_key]}, {chunk}".strip()
            continue
        params[key] = value
        current_key = key
    return params


def _parse_a1111_parameters(parameters: str) -> dict:
    if not isinstance(parameters, str) or not parameters.strip():
        return {}
    prompt_text, negative_prompt, raw_generation_params = _split_a1111_sections(parameters)
    return {
        "source_engine": "webui_a1111",
        "raw_parameters": parameters,
        "prompt_text": prompt_text,
        "negative_prompt": negative_prompt,
        "raw_generation_params": raw_generation_params,
        "generation_params": _parse_a1111_generation_params(raw_generation_params),
    }


def _extract_a1111_prompt_fields(parameters: str) -> tuple[str, str]:
    parsed = _parse_a1111_parameters(parameters)
    return parsed.get("prompt_text", ""), parsed.get("negative_prompt", "")


def _metadata_value_by_key(metadata: dict, *keys: str):
    lowered = {str(key).lower(): value for key, value in metadata.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _node_link_id(value) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, dict) and value.get("node_id") is not None:
        return str(value.get("node_id"))
    return None


def _safe_comfy_prompt_text(value) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    parsed = _parse_metadata_json(text)
    if isinstance(parsed, (dict, list)):
        return ""
    return text


def _is_text_concat_node(class_type: str, inputs: dict) -> bool:
    lowered = str(class_type or "").lower()
    if "concat" in lowered and "text" in lowered:
        return True
    text_slot_count = sum(1 for key in inputs if str(key).lower().startswith("text_"))
    return text_slot_count >= 2


def _is_schedule_prompt_node(class_type: str) -> bool:
    lowered = str(class_type or "").lower()
    return "schedule" in lowered and ("prompt" in lowered or "text" in lowered)


def _input_sort_key(key) -> tuple[int, str, str]:
    key_text = str(key)
    lowered = key_text.lower()
    priority = {
        "text": 0,
        "prompt": 1,
        "value": 2,
        "string": 3,
        "positive": 4,
        "negative": 5,
    }.get(lowered, 10)
    return priority, lowered, key_text


def _text_input_keys(inputs: dict, include_conditioning: bool = False) -> list[str]:
    if not isinstance(inputs, dict):
        return []
    keys = []
    for key in inputs:
        lowered = str(key).lower()
        if lowered in {"text", "prompt", "value", "string"}:
            keys.append(key)
        elif lowered.startswith("text_") or lowered.startswith("prompt_"):
            keys.append(key)
        elif include_conditioning and lowered in {"positive", "negative"}:
            keys.append(key)
    return sorted(keys, key=_input_sort_key)


def _concat_input_keys(inputs: dict) -> list[str]:
    keys = [
        key
        for key in inputs
        if str(key).lower() == "text" or str(key).lower().startswith(("text_", "prompt_"))
    ]
    return sorted(keys, key=_input_sort_key)


def _concat_delimiter(inputs: dict) -> str:
    for key in ("delimiter", "separator", "sep", "joiner"):
        value = inputs.get(key)
        if isinstance(value, str):
            return value
    return "\n"


def _resolve_comfy_text_value(value, nodes: dict, visited: set[str]) -> str:
    direct_text = _safe_comfy_prompt_text(value)
    if direct_text:
        return direct_text
    return _resolve_comfy_text_node(_node_link_id(value), nodes, visited)


def _resolve_comfy_text_node(node_id: str | None, nodes: dict, visited: set[str] | None = None) -> str:
    if not node_id or node_id not in nodes:
        return ""
    visited = set(visited or set())
    if node_id in visited:
        return ""
    visited.add(node_id)

    node = nodes.get(node_id) or {}
    if not isinstance(node, dict):
        return ""
    inputs = node.get("inputs", {})
    if not isinstance(inputs, dict):
        return ""
    class_type = str(node.get("class_type") or node.get("type") or "")

    text_value = inputs.get("text")
    text = _resolve_comfy_text_value(text_value, nodes, visited)
    if text:
        return text

    if _is_text_concat_node(class_type, inputs):
        parts = []
        for key in _concat_input_keys(inputs):
            part = _resolve_comfy_text_value(inputs.get(key), nodes, visited)
            if part:
                parts.append(part)
        if parts:
            return _concat_delimiter(inputs).join(parts).strip()

    include_conditioning = _is_schedule_prompt_node(class_type)
    for key in _text_input_keys(inputs, include_conditioning=include_conditioning):
        if key == "text":
            continue
        text = _resolve_comfy_text_value(inputs.get(key), nodes, visited)
        if text:
            return text

    return ""


def _extract_comfy_prompt_fields(prompt_json) -> tuple[str, str]:
    if not isinstance(prompt_json, dict):
        return "", ""

    nodes = _api_workflow_nodes(prompt_json)
    if not isinstance(nodes, dict):
        return "", ""

    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        if "KSampler" not in class_type:
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        positive = _resolve_comfy_text_node(_node_link_id(inputs.get("positive")), nodes)
        negative = _resolve_comfy_text_node(_node_link_id(inputs.get("negative")), nodes)
        if positive or negative:
            return positive.strip(), negative.strip()

    clip_texts = []
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        if "CLIPTextEncode" not in class_type:
            continue
        inputs = node.get("inputs", {})
        if isinstance(inputs, dict) and isinstance(inputs.get("text"), str):
            clip_texts.append(inputs["text"].strip())

    if not clip_texts:
        return "", ""
    if len(clip_texts) == 1:
        return clip_texts[0], ""
    return "", ""


def _extract_image_prompt_fields(metadata: dict) -> dict:
    fields = {
        "source_engine": "",
        "metadata_sources": [],
        "raw_parameters": "",
        "prompt_text": "",
        "negative_prompt": "",
        "raw_generation_params": "",
        "generation_params": {},
        "workflow_metadata_keys": [],
    }

    parameters = _metadata_value_by_key(metadata, "parameters")
    if isinstance(parameters, str):
        a1111_fields = _parse_a1111_parameters(parameters)
        if a1111_fields:
            fields.update(a1111_fields)
            fields["metadata_sources"].append("a1111_parameters")

    software = _metadata_value_by_key(metadata, "Software")
    image_description = _metadata_value_by_key(metadata, "ImageDescription")
    user_comment = _metadata_value_by_key(metadata, "UserComment")
    has_exif_generation_metadata = any(
        isinstance(value, str) and value.strip()
        for value in (software, image_description, user_comment)
    )
    if has_exif_generation_metadata:
        fields["metadata_sources"].append("exif")
    if isinstance(software, str) and software.strip().lower() == "novelai":
        fields["source_engine"] = "novelai"
        fields["metadata_sources"].append("novelai_exif")
    if isinstance(image_description, str) and image_description.strip() and not fields["prompt_text"]:
        fields["prompt_text"] = image_description.strip()
        fields["raw_parameters"] = image_description
    if isinstance(user_comment, str) and user_comment.strip():
        fields.setdefault("exif_user_comment", user_comment)

    explicit_positive = _metadata_value_by_key(metadata, "positive_prompt", "positive")
    if isinstance(explicit_positive, str) and explicit_positive.strip():
        fields["prompt_text"] = explicit_positive.strip()

    explicit_negative = _metadata_value_by_key(metadata, "negative_prompt", "negative")
    if isinstance(explicit_negative, str) and explicit_negative.strip():
        fields["negative_prompt"] = explicit_negative.strip()

    prompt_value = _metadata_value_by_key(metadata, "prompt")
    prompt_json = _parse_metadata_json(prompt_value)
    if _looks_like_comfy_api_workflow(prompt_json):
        fields["workflow_metadata_keys"].append("prompt")
        fields["metadata_sources"].append("comfy_prompt")
        comfy_positive, comfy_negative = _extract_comfy_prompt_fields(prompt_json)
        if comfy_positive and not fields["prompt_text"]:
            fields["prompt_text"] = comfy_positive
        if comfy_negative and not fields["negative_prompt"]:
            fields["negative_prompt"] = comfy_negative
    elif prompt_json is not None:
        fields["metadata_sources"].append("json_prompt_metadata")
    elif isinstance(prompt_value, str) and prompt_value.strip() and not fields["prompt_text"]:
        fields["prompt_text"] = prompt_value.strip()

    workflow_value = _metadata_value_by_key(metadata, "workflow")
    if _parse_metadata_json(workflow_value) is not None:
        fields["workflow_metadata_keys"].append("workflow")
        fields["metadata_sources"].append("comfy_workflow")

    if not fields["prompt_text"]:
        for key in ("description", "caption"):
            value = _metadata_value_by_key(metadata, key)
            if isinstance(value, str) and value.strip():
                fields["prompt_text"] = value.strip()
                break

    fields["metadata_sources"] = list(dict.fromkeys(fields["metadata_sources"]))
    return fields


def extract_image_metadata_for_path(image_path: str) -> dict:
    if not image_path:
        return {}

    image_path = os.path.abspath(os.path.expanduser(str(image_path)))
    extension = os.path.splitext(image_path)[1].lower()
    if extension not in IMAGE_METADATA_EXTENSIONS or not os.path.exists(image_path):
        return {}

    warning = ""
    width = None
    height = None
    metadata = {}
    try:
        stat = os.stat(image_path)
        width, height, metadata = _read_image_metadata(image_path)
    except Exception as exc:
        warning = _short_metadata_preview(exc, limit=160)
        try:
            stat = os.stat(image_path)
        except OSError:
            return {}

    metadata_keys = sorted(metadata.keys())
    raw_metadata = {
        key: _stringify_metadata_value(metadata[key])
        for key in metadata_keys
    }
    prompt_fields = _extract_image_prompt_fields(metadata)
    image_info = {
        "path": image_path,
        "filename": os.path.basename(image_path),
        "extension": extension,
        "size_bytes": stat.st_size,
        "modified_at": _iso_from_timestamp(stat.st_mtime),
        "width": width,
        "height": height,
        "has_metadata": bool(metadata_keys),
        "metadata_keys": metadata_keys,
        "has_comfy_workflow": _has_comfy_workflow_metadata(metadata),
        "prompt_preview": _find_prompt_preview(metadata),
        "source_engine": prompt_fields["source_engine"],
        "metadata_sources": prompt_fields["metadata_sources"],
        "raw_parameters": prompt_fields["raw_parameters"],
        "prompt_text": prompt_fields["prompt_text"],
        "negative_prompt": prompt_fields["negative_prompt"],
        "raw_generation_params": prompt_fields["raw_generation_params"],
        "generation_params": prompt_fields["generation_params"],
        "workflow_metadata_keys": prompt_fields["workflow_metadata_keys"],
        "raw_metadata": raw_metadata,
    }
    if warning:
        image_info["warning"] = warning
    return image_info


def scan_image_directory_metadata(source_directory: str) -> dict:
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    images = []

    if not os.path.isdir(source_directory):
        return {
            "source_directory": source_directory,
            "imported_at": imported_at,
            "image_count": 0,
            "metadata_count": 0,
            "comfy_workflow_count": 0,
            "images": [],
            "warnings": [f"Directory not found: {source_directory}"],
        }

    for root, dirs, files in os.walk(source_directory):
        dirs.sort(key=natural_sort_key)
        for file_name in sorted(files, key=natural_sort_key):
            extension = os.path.splitext(file_name)[1].lower()
            if extension not in IMAGE_METADATA_EXTENSIONS:
                continue

            image_path = os.path.abspath(os.path.join(root, file_name))
            warning = ""
            width = None
            height = None
            metadata = {}
            try:
                stat = os.stat(image_path)
                width, height, metadata = _read_image_metadata(image_path)
            except Exception as exc:
                warning = _short_metadata_preview(exc, limit=160)
                try:
                    stat = os.stat(image_path)
                except OSError:
                    continue

            metadata_keys = sorted(metadata.keys())
            raw_metadata = {
                key: _stringify_metadata_value(metadata[key])
                for key in metadata_keys
            }
            prompt_fields = _extract_image_prompt_fields(metadata)
            has_comfy_workflow = _has_comfy_workflow_metadata(metadata)
            image_info = {
                "path": image_path,
                "filename": file_name,
                "extension": extension,
                "size_bytes": stat.st_size,
                "modified_at": _iso_from_timestamp(stat.st_mtime),
                "width": width,
                "height": height,
                "has_metadata": bool(metadata_keys),
                "metadata_keys": metadata_keys,
                "has_comfy_workflow": has_comfy_workflow,
                "prompt_preview": _find_prompt_preview(metadata),
                "source_engine": prompt_fields["source_engine"],
                "metadata_sources": prompt_fields["metadata_sources"],
                "raw_parameters": prompt_fields["raw_parameters"],
                "prompt_text": prompt_fields["prompt_text"],
                "negative_prompt": prompt_fields["negative_prompt"],
                "raw_generation_params": prompt_fields["raw_generation_params"],
                "generation_params": prompt_fields["generation_params"],
                "workflow_metadata_keys": prompt_fields["workflow_metadata_keys"],
                "raw_metadata": raw_metadata,
            }
            if warning:
                image_info["warning"] = warning
            images.append(image_info)

    metadata_count = sum(1 for image in images if image["has_metadata"])
    comfy_workflow_count = sum(1 for image in images if image["has_comfy_workflow"])
    return {
        "source_directory": os.path.abspath(source_directory),
        "imported_at": imported_at,
        "image_count": len(images),
        "metadata_count": metadata_count,
        "comfy_workflow_count": comfy_workflow_count,
        "images": images,
        "warnings": [image["warning"] for image in images if image.get("warning")],
    }


def add_image_metadata_import(project: Project, source_directory: str) -> dict:
    project.project_metadata = _normalize_project_metadata(getattr(project, "project_metadata", None))
    import_summary = scan_image_directory_metadata(source_directory)
    project.project_metadata.setdefault("image_imports", []).append(import_summary)
    return import_summary


def find_image_metadata_for_line(project: Project, line: PromptLine) -> dict | None:
    image_path = getattr(line, "image_path", None)
    if not image_path:
        return None

    target_path = os.path.normcase(os.path.abspath(image_path))
    project.project_metadata = _normalize_project_metadata(getattr(project, "project_metadata", None))
    for image_import in reversed(project.project_metadata.get("image_imports", [])):
        if not isinstance(image_import, dict):
            continue
        for image_info in reversed(image_import.get("images", [])):
            if not isinstance(image_info, dict) or not image_info.get("path"):
                continue
            image_info_path = os.path.normcase(os.path.abspath(image_info["path"]))
            if image_info_path == target_path:
                return image_info
    return None


def _latest_image_metadata_import(project: Project) -> dict | None:
    project.project_metadata = _normalize_project_metadata(getattr(project, "project_metadata", None))
    image_imports = project.project_metadata.get("image_imports", [])
    if not image_imports:
        return None
    latest_import = image_imports[-1]
    return latest_import if isinstance(latest_import, dict) else None


def _image_import_prompt_text(image_info: dict) -> str:
    return str(image_info.get("prompt_text") or "").strip()


def _image_import_should_create_line(image_info: dict) -> bool:
    return bool(
        _image_import_prompt_text(image_info)
        or image_info.get("negative_prompt")
        or image_info.get("has_comfy_workflow")
    )


def build_source_generation_info_from_image_metadata(image_info: dict, prompt_text: str | None = None) -> dict:
    if not isinstance(image_info, dict):
        return {}

    source_prompt = str(prompt_text or image_info.get("prompt_text") or "").strip()
    source_negative_prompt = get_metadata_negative_prompt(image_info)
    source_generation_settings = extract_generation_settings_from_metadata(image_info)
    raw_metadata = image_info.get("raw_metadata")
    raw_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}

    source_info = {}
    if source_prompt:
        source_info["source_prompt"] = source_prompt
    if source_negative_prompt:
        source_info["source_negative_prompt"] = source_negative_prompt
    if source_generation_settings:
        source_info["source_generation_settings"] = _json_safe_source_value(source_generation_settings)
    if raw_metadata:
        source_info["source_raw_metadata"] = _json_safe_source_value(raw_metadata)

    source_image_path = image_info.get("path") or image_info.get("image_path")
    if source_image_path:
        source_info["source_image_path"] = str(source_image_path)

    source_metadata_id = image_info.get("source_metadata_id") or image_info.get("image_metadata_id") or image_info.get("metadata_id")
    if source_metadata_id:
        source_info["source_metadata_id"] = str(source_metadata_id)

    if source_info:
        source_info["source_kind"] = "imported_image_metadata"
    return source_info


def _metadata_text_value(metadata: dict, *keys: str) -> str:
    if not isinstance(metadata, dict):
        return ""
    lowered = {str(key).casefold(): value for key, value in metadata.items()}
    for key in keys:
        value = lowered.get(str(key).casefold())
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def build_source_generation_info_from_candidate(
    source_line: PromptLine,
    candidate_image_path: str,
    candidate_metadata: dict | None = None,
) -> dict:
    candidate_metadata = candidate_metadata if isinstance(candidate_metadata, dict) else {}

    source_prompt = _metadata_text_value(
        candidate_metadata,
        "source_prompt",
        "prompt_text",
        "prompt",
        "positive_prompt",
        "positive",
    ) or str(getattr(source_line, "current_text", "") or "").strip()
    source_negative_prompt = _metadata_text_value(
        candidate_metadata,
        "source_negative_prompt",
        "negative_prompt",
        "negative",
    ) or str(getattr(source_line, "negative_prompt", "") or "").strip()
    source_generation_settings = extract_generation_settings_from_metadata(candidate_metadata)

    source_info = {
        "source_kind": "derived_candidate",
        "source_image_path": str(candidate_image_path),
    }
    if source_prompt:
        source_info["source_prompt"] = source_prompt
    if source_negative_prompt:
        source_info["source_negative_prompt"] = source_negative_prompt
    if source_generation_settings:
        source_info["source_generation_settings"] = _json_safe_source_value(source_generation_settings)
    if candidate_metadata:
        source_info["source_raw_metadata"] = _json_safe_source_value(candidate_metadata)
    return source_info


def build_lineage_info_from_candidate(
    source_line: PromptLine,
    candidate_image_path: str,
    candidate_metadata: dict | None = None,
) -> dict:
    candidate_metadata = candidate_metadata if isinstance(candidate_metadata, dict) else {}
    lineage_info = {
        "lineage_kind": "candidate_insert",
        "parent_line_id": str(getattr(source_line, "id", "") or ""),
        "candidate_image_path": str(candidate_image_path),
    }

    parent_index = getattr(source_line, "current_index", None)
    if parent_index is not None:
        lineage_info["parent_line_index"] = parent_index
    parent_label = getattr(source_line, "original_file_name", "") or getattr(source_line, "id", "")
    if parent_label:
        lineage_info["parent_line_label"] = str(parent_label)
    parent_image_path = (
        getattr(source_line, "selected_candidate_path", None)
        or getattr(source_line, "generated_image_path", None)
        or getattr(source_line, "image_path", None)
    )
    if parent_image_path:
        lineage_info["parent_image_path"] = str(parent_image_path)

    optional_candidate_keys = {
        "origin_line_id": "candidate_origin_line_id",
        "origin_line_index": "candidate_origin_line_index",
        "source": "created_from",
        "created_at": "candidate_created_at",
        "run_index": "candidate_run_index",
    }
    for source_key, target_key in optional_candidate_keys.items():
        value = candidate_metadata.get(source_key)
        if value not in (None, ""):
            lineage_info[target_key] = _json_safe_source_value(value)
    return lineage_info


def summarize_image_metadata_line_import(project: Project) -> dict:
    latest_import = _latest_image_metadata_import(project)
    images = latest_import.get("images", []) if latest_import else []
    prompt_count = 0
    skipped_count = 0
    for image_info in images:
        if not isinstance(image_info, dict):
            skipped_count += 1
        elif _image_import_should_create_line(image_info):
            prompt_count += 1
        else:
            skipped_count += 1
    return {
        "has_import": latest_import is not None,
        "line_count": prompt_count,
        "skipped_count": skipped_count,
    }


def _next_image_metadata_line_id(existing_ids: set[str], sequence: int) -> tuple[str, int]:
    while True:
        line_id = f"imgmeta_{sequence:04d}"
        sequence += 1
        if line_id not in existing_ids:
            existing_ids.add(line_id)
            return line_id, sequence


def create_prompt_lines_from_latest_image_import(project: Project, replace: bool = False) -> tuple[Project, dict]:
    latest_import = _latest_image_metadata_import(project)
    if not latest_import:
        return project, {"created_count": 0, "skipped_count": 0, "has_import": False}

    if replace:
        project.prompt_lines = []
        project.line_groups = {}
        start_index = 0
    else:
        start_index = max((line.current_index for line in project.prompt_lines), default=-1) + 1

    existing_ids = {line.id for line in project.prompt_lines}
    sequence = 1
    created_count = 0
    skipped_count = 0

    for image_info in latest_import.get("images", []):
        if not isinstance(image_info, dict):
            skipped_count += 1
            continue

        if not _image_import_should_create_line(image_info):
            skipped_count += 1
            continue
        prompt_text = _image_import_prompt_text(image_info)
        negative_prompt = get_metadata_negative_prompt(image_info)

        line_index = start_index + created_count
        line_id, sequence = _next_image_metadata_line_id(existing_ids, sequence)
        project.prompt_lines.append(PromptLine(
            id=line_id,
            original_file_name=str(image_info.get("filename") or os.path.basename(image_info.get("path", "")) or "image"),
            original_index=line_index,
            current_index=line_index,
            original_text=prompt_text,
            current_text=prompt_text,
            tokens=parse_prompt(prompt_text),
            negative_prompt=negative_prompt,
            source_generation_info=build_source_generation_info_from_image_metadata(image_info, prompt_text),
            image_path=image_info.get("path"),
        ))
        created_count += 1

    project = build_graph(project)
    return project, {
        "created_count": created_count,
        "skipped_count": skipped_count,
        "has_import": True,
    }


def _find_sidecar_image(source_dir: str, base_name: str) -> str | None:
    for ext in [".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"]:
        img_cand = os.path.join(source_dir, base_name + ext)
        if os.path.exists(img_cand):
            return img_cand
    return None


def _find_generated_image(source_dir: str, line_id: str) -> str | None:
    output_dir = os.path.join(source_dir, "generated")
    if not os.path.exists(output_dir):
        return None

    cands = glob.glob(os.path.join(output_dir, f"gen_{line_id}_*.png"))
    if not cands:
        return None

    cands.sort(key=os.path.getmtime, reverse=True)
    return cands[0]


def _read_prompt_records(file_path: str) -> List[Tuple[str, str]]:
    records = []
    pending_positive = None

    with open(file_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            text = raw_line.strip()
            if not text:
                continue

            lower_text = text.lower()
            if lower_text.startswith("positive:"):
                if pending_positive is not None:
                    records.append((pending_positive, ""))
                pending_positive = text.split(":", 1)[1].strip()
                continue

            if lower_text.startswith("negative:") and pending_positive is not None:
                records.append((pending_positive, text.split(":", 1)[1].strip()))
                pending_positive = None
                continue

            if pending_positive is not None:
                records.append((pending_positive, ""))
                pending_positive = None
            records.append((text, ""))

    if pending_positive is not None:
        records.append((pending_positive, ""))

    return records


def _append_prompt_file(project: Project, file_path: str, source_dir: str, line_index: int) -> int:
    file_name = os.path.basename(file_path)
    base_name = os.path.splitext(file_name)[0]
    image_path = _find_sidecar_image(source_dir, base_name)

    try:
        records = _read_prompt_records(file_path)
    except Exception as e:
        logger.error(f"Error reading {file_name}: {e}")
        return line_index

    for text, negative_prompt in records:
        tokens = parse_prompt(text)
        if not tokens:
            continue

        line_id = f"line_{line_index}"
        prompt_line = PromptLine(
            id=line_id,
            original_file_name=file_name,
            original_index=line_index,
            current_index=line_index,
            original_text=text,
            current_text=text,
            tokens=tokens,
            negative_prompt=negative_prompt,
            image_path=image_path,
            generated_image_path=_find_generated_image(source_dir, line_id),
        )
        project.prompt_lines.append(prompt_line)
        line_index += 1

    return line_index


def load_prompt_file(file_path: str, max_depth: int = None) -> Project:
    source_dir = os.path.dirname(file_path) or "."
    project = Project(source_directory=source_dir)
    _append_prompt_file(project, file_path, source_dir, 0)
    return build_graph(project, max_depth=max_depth)


def load_directory(dir_path: str, max_depth: int = None) -> Project:
    project = Project(source_directory=dir_path)
    txt_files = sorted(
        glob.glob(os.path.join(dir_path, "*.txt")),
        key=lambda path: natural_sort_key(os.path.basename(path)),
    )

    line_index = 0
    for file_path in txt_files:
        line_index = _append_prompt_file(project, file_path, dir_path, line_index)

    return build_graph(project, max_depth=max_depth)


def _write_prompt_record(f, positive_prompt: str, negative_prompt: str = ""):
    if negative_prompt:
        f.write(f"Positive: {positive_prompt}\n")
        f.write(f"Negative: {negative_prompt}\n")
    else:
        f.write(f"{positive_prompt}\n")


def _safe_export_stem(file_name: str) -> str:
    stem = os.path.splitext(os.path.basename(file_name or "prompt"))[0].strip() or "prompt"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)


def export_to_txt(
    project: Project,
    output_path: str,
    include_comments: bool = False,
    disabled_modules: set = None,
):
    if disabled_modules is None:
        disabled_modules = set()

    from core.operations import get_active_tokens

    valid_lines = [
        line for line in project.prompt_lines
        if not line.deleted and getattr(line, "line_type", None) not in SPECIAL_GALLERY_LINE_TYPES
    ]

    with open(output_path, "w", encoding="utf-8") as f:
        current_file = ""
        for line in valid_lines:
            if include_comments and line.original_file_name != current_file:
                if current_file:
                    f.write("\n")
                f.write(f"# {line.original_file_name}\n")
                current_file = line.original_file_name

            active = get_active_tokens(
                line,
                disabled_modules,
                module_library=getattr(project, "module_library", {}),
            )
            _write_prompt_record(f, ", ".join(active), getattr(line, "negative_prompt", "") or "")


def export_to_prompt_files(project: Project, output_dir: str, disabled_modules: set = None) -> List[str]:
    if disabled_modules is None:
        disabled_modules = set()

    from core.operations import get_active_tokens

    os.makedirs(output_dir, exist_ok=True)
    exported_paths = []
    valid_lines = [
        line for line in project.prompt_lines
        if not line.deleted and getattr(line, "line_type", None) not in SPECIAL_GALLERY_LINE_TYPES
    ]

    for index, line in enumerate(valid_lines, start=1):
        active = get_active_tokens(
            line,
            disabled_modules,
            module_library=getattr(project, "module_library", {}),
        )
        file_name = f"{index:04d}_{_safe_export_stem(line.original_file_name)}.txt"
        output_path = os.path.join(output_dir, file_name)
        with open(output_path, "w", encoding="utf-8") as f:
            _write_prompt_record(f, ", ".join(active), getattr(line, "negative_prompt", "") or "")
        exported_paths.append(output_path)

    return exported_paths


def _ordered_export_lines(project: Project) -> List[PromptLine]:
    indexed_lines = []
    for fallback_index, line in enumerate(getattr(project, "prompt_lines", [])):
        if getattr(line, "deleted", False) or getattr(line, "line_type", None) in SPECIAL_GALLERY_LINE_TYPES:
            continue
        line_index = getattr(line, "current_index", None)
        sort_index = line_index if isinstance(line_index, int) else fallback_index
        indexed_lines.append((sort_index, fallback_index, line))
    return [line for _, _, line in sorted(indexed_lines, key=lambda item: (item[0], item[1]))]


def _resolve_image_export_source(project: Project, image_path: str, project_path: str = "") -> str:
    if not image_path:
        return ""

    candidates = []
    raw_path = str(image_path).strip()
    expanded_path = os.path.expanduser(raw_path)
    is_relative_path = bool(expanded_path and not os.path.isabs(expanded_path))
    if project_path and is_relative_path:
        candidates.append(resolve_project_asset_path(expanded_path, project_path))
    candidates.append(expanded_path)
    if project_path and not is_relative_path:
        candidates.append(resolve_project_asset_path(expanded_path, project_path))
    candidates.append(os.path.abspath(expanded_path))

    source_directory = getattr(project, "source_directory", "") if project else ""
    if source_directory and not os.path.isabs(expanded_path):
        candidates.append(os.path.abspath(os.path.join(os.path.expanduser(source_directory), expanded_path)))
        candidates.append(os.path.abspath(os.path.join(os.path.expanduser(source_directory), os.path.basename(expanded_path))))

    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(os.path.expanduser(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.exists(normalized):
            return normalized
    return ""


def _candidate_export_path_matches(project: Project, candidate_path: str, image_path: str, project_path: str = "") -> bool:
    candidate_path = str(candidate_path or "").strip()
    image_path = str(image_path or "").strip()
    if not candidate_path or not image_path:
        return False
    if candidate_path == image_path:
        return True
    candidate_resolved = _resolve_image_export_source(project, candidate_path, project_path)
    image_resolved = _resolve_image_export_source(project, image_path, project_path)
    if not candidate_resolved or not image_resolved:
        return False
    try:
        return os.path.samefile(candidate_resolved, image_resolved)
    except OSError:
        return os.path.abspath(candidate_resolved) == os.path.abspath(image_resolved)


def _line_candidate_path_is_trashed(project: Project, line: PromptLine, image_path: str, project_path: str = "") -> bool:
    for candidate in getattr(line, "generated_candidates", None) or []:
        if not isinstance(candidate, dict) or not candidate.get("trashed"):
            continue
        if _candidate_export_path_matches(project, candidate.get("path"), image_path, project_path):
            return True
    return False


def _line_linked_image_paths(project: Project, line: PromptLine, project_path: str = "") -> List[str]:
    linked_paths = []
    for attr_name in ("selected_candidate_path", "generated_image_path", "image_path"):
        resolved_path = _resolve_image_export_source(project, getattr(line, attr_name, None), project_path)
        if resolved_path:
            linked_paths.append(resolved_path)
    for candidate in getattr(line, "generated_candidates", None) or []:
        candidate_path = candidate.get("path") if isinstance(candidate, dict) else candidate
        resolved_path = _resolve_image_export_source(project, candidate_path, project_path)
        if resolved_path:
            linked_paths.append(resolved_path)
    for variant in getattr(line, "gallery_variants", None) or []:
        variant_path = variant.get("path") if isinstance(variant, dict) else ""
        resolved_path = _resolve_image_export_source(project, variant_path, project_path)
        if resolved_path:
            linked_paths.append(resolved_path)
    return linked_paths


def _selected_final_image_reference(project: Project, line: PromptLine, project_path: str = "") -> dict:
    for attr_name in ("selected_candidate_path", "generated_image_path", "image_path"):
        image_path = getattr(line, attr_name, None)
        if _line_candidate_path_is_trashed(project, line, image_path, project_path):
            continue
        resolved_path = _resolve_image_export_source(project, image_path, project_path)
        if resolved_path:
            return {"path": resolved_path, "field": attr_name}
    return {}


def _selected_final_image_path(project: Project, line: PromptLine, project_path: str = "") -> str:
    return str(_selected_final_image_reference(project, line, project_path).get("path") or "")


def _same_existing_file(path_a: str, path_b: str) -> bool:
    try:
        return os.path.exists(path_a) and os.path.exists(path_b) and os.path.samefile(path_a, path_b)
    except OSError:
        return os.path.abspath(path_a) == os.path.abspath(path_b)


def _sanitize_export_base_filename(base_filename: str) -> str:
    base_name = os.path.basename(str(base_filename or "").strip())
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in base_name)
    return safe_name.strip("_")


def _safe_export_digits(digits: int) -> int:
    try:
        return max(1, min(8, int(digits)))
    except (TypeError, ValueError):
        return 4


def _safe_export_start_index(start_index: int) -> int:
    try:
        return max(1, int(start_index))
    except (TypeError, ValueError):
        return 1


def _final_export_file_name(base_filename: str, export_index: int, digits: int, extension: str) -> str:
    safe_base_filename = _sanitize_export_base_filename(base_filename)
    clean_extension = (extension or ".png").lower()
    if not clean_extension.startswith("."):
        clean_extension = f".{clean_extension}"
    numbered = f"{int(export_index):0{_safe_export_digits(digits)}d}{clean_extension}"
    return f"{safe_base_filename}_{numbered}" if safe_base_filename else numbered


def _route_context_by_line_id(project: Project) -> dict:
    route_context = {}
    current_route = {}
    route_order = -1
    route_line_order = 0
    for project_order, line in enumerate(getattr(project, "prompt_lines", []) or []):
        if getattr(line, "deleted", False):
            continue
        if getattr(line, "line_type", None) == "separator":
            route_order += 1
            current_route = {
                "route_id": getattr(line, "id", ""),
                "route_label": getattr(line, "separator_label", None) or getattr(line, "current_text", "") or "",
                "route_order": route_order,
            }
            route_line_order = 0
            continue
        if getattr(line, "line_type", None) in SPECIAL_GALLERY_LINE_TYPES:
            continue
        route_context[getattr(line, "id", "")] = {
            **current_route,
            "project_order": project_order,
            "route_line_order": route_line_order,
        }
        route_line_order += 1
    return route_context


def _normalized_final_export_path(path: str) -> str:
    raw_path = str(path or "").strip()
    if not raw_path or "\x00" in raw_path:
        return ""
    try:
        return os.path.realpath(
            os.path.normpath(
                os.path.abspath(os.path.expanduser(raw_path))
            )
        )
    except (OSError, TypeError, ValueError):
        return ""


def _final_export_path_is_within(path: str, parent: str) -> Optional[bool]:
    if not path or not parent:
        return None
    try:
        normalized_path = os.path.normcase(path)
        normalized_parent = os.path.normcase(parent)
        return (
            os.path.commonpath([normalized_path, normalized_parent])
            == normalized_parent
        )
    except (OSError, TypeError, ValueError):
        return None


def _portable_final_export_basename(path) -> str:
    """Return one filename component without retaining host path hierarchy."""

    try:
        raw_path = os.fspath(path)
    except (TypeError, ValueError):
        return ""
    if not isinstance(raw_path, str):
        return ""
    clean_path = raw_path.strip()
    if not clean_path or "\x00" in clean_path:
        return ""
    filename = clean_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    drive_relative = re.fullmatch(r"[A-Za-z]:(.*)", filename)
    if drive_relative:
        filename = drive_relative.group(1)
    if filename in ("", ".", ".."):
        return ""
    return filename


def _portable_final_export_project_file(project_path) -> str:
    """Project provenance is filename-only in the public Final Export manifest."""

    return _portable_final_export_basename(project_path)


def _portable_final_export_output_path(
    output_path,
    export_dir,
    *,
    output_filename="",
) -> str:
    """Return a verified manifest-relative path for one exported file."""

    normalized_output = _normalized_final_export_path(output_path)
    normalized_export_dir = _normalized_final_export_path(export_dir)
    if (
        not normalized_output
        or not normalized_export_dir
        or not os.path.isfile(normalized_output)
        or _final_export_path_is_within(
            normalized_output,
            normalized_export_dir,
        )
        is not True
    ):
        raise ValueError(
            "Final Export output is not a regular file inside the export directory."
        )
    try:
        relative_path = os.path.relpath(
            normalized_output,
            normalized_export_dir,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(
            "Final Export output could not be made manifest-relative."
        ) from exc
    portable_path = relative_path.replace("\\", "/")
    portable_parts = [part for part in portable_path.split("/") if part]
    expected_filename = _portable_final_export_basename(output_filename)
    if (
        not portable_parts
        or any(part in (".", "..") for part in portable_parts)
        or os.path.isabs(portable_path)
        or (expected_filename and portable_parts[-1] != expected_filename)
        or (expected_filename and portable_path != expected_filename)
    ):
        raise ValueError(
            "Final Export output path does not match its exported filename."
        )
    return "/".join(portable_parts)


def _portable_final_export_source_reference(
    source_path,
    project_path,
) -> dict:
    """Project-relative or basename-only provenance for one exported source."""

    normalized_source = _normalized_final_export_path(source_path)
    if not normalized_source or not os.path.isfile(normalized_source):
        return {"source_image_path": "", "source_image_scope": "unknown"}

    normalized_project_path = _normalized_final_export_path(project_path)
    project_root = (
        os.path.dirname(normalized_project_path)
        if normalized_project_path
        else ""
    )
    if (
        project_root
        and _final_export_path_is_within(
            normalized_source,
            project_root,
        )
        is True
    ):
        try:
            relative_path = os.path.relpath(
                normalized_source,
                project_root,
            )
        except (OSError, TypeError, ValueError):
            relative_path = ""
        portable_path = relative_path.replace("\\", "/")
        portable_parts = [part for part in portable_path.split("/") if part]
        if (
            portable_parts
            and not any(part in (".", "..") for part in portable_parts)
            and not os.path.isabs(portable_path)
        ):
            return {
                "source_image_path": "/".join(portable_parts),
                "source_image_scope": "project",
            }

    external_filename = _portable_final_export_basename(source_path)
    if external_filename:
        return {
            "source_image_path": external_filename,
            "source_image_scope": "external",
        }
    return {"source_image_path": "", "source_image_scope": "unknown"}


def _build_portable_final_export_manifest(
    *,
    preview: dict,
    exported_items: List[dict],
    export_dir: str,
    project_path: str,
    strip_metadata: bool,
    metadata_stripped_count: int,
    skipped_line_ids: List[str],
    warnings: List[str],
    exported_at: str,
) -> dict:
    """Build the public manifest without mutating the internal export plan."""

    project_file = _portable_final_export_project_file(project_path)
    portable_items = []
    for item in exported_items:
        source_reference = _portable_final_export_source_reference(
            item.get("source_image_path", ""),
            project_path,
        )
        portable_items.append(
            {
                "output_filename": item.get("output_filename", ""),
                "source_line_id": item.get("line_id", ""),
                "source_line_index": item.get("line_index", None),
                "project_order": item.get(
                    "project_order",
                    item.get("line_index", None),
                ),
                "source_original_filename": _portable_final_export_basename(
                    item.get("source_original_filename", "")
                ),
                **source_reference,
                "source_image_field": item.get("source_image_field", ""),
                "output_path": _portable_final_export_output_path(
                    item.get("output_path", ""),
                    export_dir,
                    output_filename=item.get("output_filename", ""),
                ),
                "route": copy.deepcopy(item.get("route", {})),
                "route_id": item.get("route_id", ""),
                "route_label": item.get("route_label", ""),
                "route_order": item.get("route_order"),
                "route_line_order": item.get("route_line_order"),
                "prompt_text": item.get("prompt_text", ""),
                "negative_prompt": item.get("negative_prompt", ""),
            }
        )

    portable_skipped_items = []
    for item in preview.get("skipped_items", []):
        portable_item = copy.deepcopy(item)
        portable_item["source_original_filename"] = (
            _portable_final_export_basename(
                item.get("source_original_filename", "")
            )
        )
        portable_skipped_items.append(portable_item)

    return {
        "manifest_version": FINAL_EXPORT_MANIFEST_VERSION,
        "path_contract": FINAL_EXPORT_PATH_CONTRACT,
        "exported_at": exported_at,
        "project_path": project_file,
        "project_name": project_file,
        "output_dir": ".",
        "total_exported_count": len(exported_items),
        "skipped_count": len(skipped_line_ids),
        "base_filename": preview["base_filename"],
        "start_index": preview["start_index"],
        "digits": preview["digits"],
        "export_scope": preview.get("export_scope", "all_lines"),
        "route_id": preview.get("route_id", ""),
        "route_label": preview.get("route_label", ""),
        "route_line_count": preview.get("route_line_count"),
        "selected_route_handles": list(
            preview.get("selected_route_handles", [])
        ),
        "selected_route_labels": list(
            preview.get("selected_route_labels", [])
        ),
        "selected_route_count": preview.get("selected_route_count", 0),
        "route_summaries": copy.deepcopy(
            preview.get("route_summaries", [])
        ),
        "metadata_stripped": bool(strip_metadata),
        "metadata_stripped_count": metadata_stripped_count,
        "items": portable_items,
        "skipped_items": portable_skipped_items,
        "warnings": list(warnings),
    }


def _nearest_existing_final_export_parent(path: str) -> str:
    current = str(path or "")
    while current:
        try:
            if os.path.isdir(current):
                return current
        except (OSError, TypeError, ValueError):
            return ""
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    return ""


def _final_export_source_size(source_path: str) -> dict:
    try:
        source_stat = os.stat(source_path)
        if not stat.S_ISREG(source_stat.st_mode):
            raise OSError("source is not a regular file")
        return {
            "source_size_bytes": int(source_stat.st_size),
            "source_size_available": True,
            "source_size_error": "",
        }
    except (OSError, TypeError, ValueError) as exc:
        return {
            "source_size_bytes": None,
            "source_size_available": False,
            "source_size_error": str(exc),
        }


def profile_final_export_destination(
    output_dir: str,
    *,
    project_path: str = "",
    planned_items: Optional[List[dict]] = None,
    use_timestamp_subfolder: Optional[bool] = None,
) -> dict:
    """Read-only destination/capacity profile for a planned Final Export."""

    items = list(planned_items or [])
    normalized_output = _normalized_final_export_path(output_dir)
    normalized_project_path = _normalized_final_export_path(project_path)
    project_root = (
        os.path.dirname(normalized_project_path)
        if normalized_project_path
        else ""
    )
    expected_final_root = (
        _normalized_final_export_path(
            os.path.join(project_root, "exports", "final")
        )
        if project_root
        else ""
    )
    warnings = []
    inside_project = _final_export_path_is_within(
        normalized_output,
        project_root,
    )
    inside_final_root = _final_export_path_is_within(
        normalized_output,
        expected_final_root,
    )
    is_final_root = bool(
        normalized_output
        and expected_final_root
        and os.path.normcase(normalized_output)
        == os.path.normcase(expected_final_root)
    )

    destination_kind = "unknown"
    if normalized_output and expected_final_root:
        if inside_project is None or inside_final_root is None:
            warnings.append("Destination path comparison is unavailable.")
        elif is_final_root:
            destination_kind = "final_root"
        elif inside_final_root:
            folder_name = os.path.basename(normalized_output)
            looks_timestamped = bool(
                re.match(r"^\d{4}-\d{2}-\d{2}_\d{4}", folder_name)
            )
            if use_timestamp_subfolder is True or (
                use_timestamp_subfolder is None and looks_timestamped
            ):
                destination_kind = "timestamp_subfolder"
            else:
                destination_kind = "final_subfolder"
        else:
            destination_kind = "outside_final_root"
    elif not normalized_output:
        warnings.append("Destination path is unavailable.")
    elif not normalized_project_path:
        warnings.append("Saved Project path is unavailable.")

    destination_labels = {
        "timestamp_subfolder": "Project-local timestamp folder",
        "final_root": "Shared exports/final root",
        "final_subfolder": "Project-local Final Export subfolder",
        "outside_final_root": "Outside Project exports/final",
        "unknown": "Unavailable / unknown",
    }

    try:
        destination_exists = bool(
            normalized_output and os.path.isdir(normalized_output)
        )
    except (OSError, TypeError, ValueError):
        destination_exists = False
        warnings.append("Destination existence could not be checked.")

    nearest_existing_parent = _nearest_existing_final_export_parent(
        normalized_output
    )
    disk_usage_available = False
    disk_total_bytes = None
    disk_used_bytes = None
    disk_free_bytes = None
    if nearest_existing_parent:
        try:
            usage = shutil.disk_usage(nearest_existing_parent)
            disk_total_bytes = int(usage.total)
            disk_used_bytes = int(usage.used)
            disk_free_bytes = int(usage.free)
            disk_usage_available = True
        except (OSError, TypeError, ValueError) as exc:
            warnings.append(f"Destination disk usage unavailable: {exc}")
    else:
        warnings.append("Nearest existing destination filesystem unavailable.")

    existing_output_count = 0
    existing_output_bytes = 0
    for item in items:
        output_path = str(item.get("output_path") or "")
        if not output_path:
            continue
        try:
            output_stat = os.stat(output_path)
            if stat.S_ISREG(output_stat.st_mode):
                existing_output_count += 1
                existing_output_bytes += int(output_stat.st_size)
        except FileNotFoundError:
            continue
        except (OSError, TypeError, ValueError) as exc:
            warnings.append(
                "Existing output size unavailable for "
                f"{item.get('output_filename', '')}: {exc}"
            )

    manifest_exists = False
    if normalized_output:
        manifest_path = os.path.join(
            normalized_output,
            "export_manifest.json",
        )
        try:
            manifest_stat = os.stat(manifest_path)
            manifest_exists = stat.S_ISREG(manifest_stat.st_mode)
            if not manifest_exists:
                warnings.append(
                    "Existing export_manifest.json is not a regular file."
                )
        except FileNotFoundError:
            pass
        except (OSError, TypeError, ValueError) as exc:
            warnings.append(f"Manifest status unavailable: {exc}")

    source_total_bytes = sum(
        int(item.get("source_size_bytes") or 0)
        for item in items
        if item.get("source_size_available")
    )
    source_size_unknown_count = sum(
        1 for item in items if not item.get("source_size_available")
    )
    if source_size_unknown_count or not disk_usage_available:
        capacity_status = "unknown"
    elif int(disk_free_bytes or 0) < source_total_bytes:
        capacity_status = "insufficient"
    else:
        capacity_status = "sufficient"

    return {
        "output_dir": str(output_dir or ""),
        "normalized_output_dir": (
            os.path.normcase(normalized_output)
            if normalized_output
            else ""
        ),
        "expected_final_root": (
            os.path.normcase(expected_final_root)
            if expected_final_root
            else ""
        ),
        "destination_kind": destination_kind,
        "destination_label": destination_labels[destination_kind],
        "inside_project": bool(inside_project),
        "inside_final_root": bool(inside_final_root),
        "is_final_root": is_final_root,
        "destination_exists": destination_exists,
        "nearest_existing_parent": nearest_existing_parent,
        "disk_usage_available": disk_usage_available,
        "disk_total_bytes": disk_total_bytes,
        "disk_used_bytes": disk_used_bytes,
        "disk_free_bytes": disk_free_bytes,
        "planned_output_count": len(items),
        "existing_output_count": existing_output_count,
        "existing_output_bytes": existing_output_bytes,
        "manifest_exists": manifest_exists,
        "capacity_status": capacity_status,
        "warnings": warnings,
    }


def preview_final_image_export(
    project: Project,
    output_dir: str = "",
    *,
    project_path: str = "",
    base_filename: str = "final",
    start_index: int = 1,
    digits: int = 4,
    target_line_ids: List[str] = None,
    export_scope: str = "all_lines",
    route_id: str = "",
    route_label: str = "",
    route_line_count: int = None,
    selected_route_handles: List[str] = None,
    selected_route_labels: List[str] = None,
    selected_route_count: int = None,
    route_summaries: List[dict] = None,
    use_timestamp_subfolder: Optional[bool] = None,
) -> dict:
    valid_lines = _ordered_export_lines(project)
    if export_scope == "selected_routes" and target_line_ids is not None:
        valid_lines_by_id = {
            str(getattr(line, "id", "") or ""): line
            for line in valid_lines
            if str(getattr(line, "id", "") or "")
        }
        valid_lines = [
            valid_lines_by_id[clean_line_id]
            for raw_line_id in target_line_ids
            for clean_line_id in [str(raw_line_id or "")]
            if clean_line_id in valid_lines_by_id
        ]
    target_line_id_set = None
    if target_line_ids is not None:
        target_line_id_set = {str(line_id) for line_id in target_line_ids if str(line_id or "").strip()}
    export_dir = os.path.abspath(os.path.expanduser(str(output_dir or ""))) if output_dir else ""
    route_context = _route_context_by_line_id(project)
    exportable_items = []
    skipped_items = []
    warnings = []
    safe_digits = _safe_export_digits(digits)
    next_export_index = _safe_export_start_index(start_index)

    for line in valid_lines:
        line_id = getattr(line, "id", "")
        if target_line_id_set is not None and line_id not in target_line_id_set:
            continue
        source_reference = _selected_final_image_reference(project, line, project_path)
        source_path = str(source_reference.get("path") or "")
        line_route = route_context.get(line_id, {})
        base_item = {
            "line_id": line_id,
            "line_index": getattr(line, "current_index", None),
            "project_order": line_route.get("project_order"),
            "source_original_filename": getattr(line, "original_file_name", "") or "",
            "prompt_text": getattr(line, "current_text", "") or "",
            "negative_prompt": getattr(line, "negative_prompt", "") or "",
            "route": line_route,
            "route_id": line_route.get("route_id", ""),
            "route_label": line_route.get("route_label", ""),
            "route_order": line_route.get("route_order"),
            "route_line_order": line_route.get("route_line_order"),
        }
        if not source_path:
            skipped_items.append({**base_item, "reason": "no exportable image"})
            continue

        extension = os.path.splitext(source_path)[1] or ".png"
        output_filename = _final_export_file_name(base_filename, next_export_index, safe_digits, extension)
        output_path = os.path.join(export_dir, output_filename) if export_dir else ""
        if output_path and os.path.exists(output_path):
            warnings.append(f"Output will overwrite existing file: {output_filename}")
        source_size = _final_export_source_size(source_path)

        exportable_items.append({
            **base_item,
            "export_index": next_export_index,
            "source_image_path": source_path,
            "source_image_field": str(source_reference.get("field") or ""),
            "output_filename": output_filename,
            "output_path": output_path,
            **source_size,
        })
        next_export_index += 1

    source_total_bytes = sum(
        int(item.get("source_size_bytes") or 0)
        for item in exportable_items
        if item.get("source_size_available")
    )
    source_size_known_count = sum(
        1
        for item in exportable_items
        if item.get("source_size_available")
    )
    source_size_unknown_count = (
        len(exportable_items) - source_size_known_count
    )
    destination_profile = profile_final_export_destination(
        export_dir,
        project_path=project_path,
        planned_items=exportable_items,
        use_timestamp_subfolder=use_timestamp_subfolder,
    )

    return {
        "output_dir": export_dir,
        "exportable_count": len(exportable_items),
        "skipped_count": len(skipped_items),
        "total_line_count": len(valid_lines),
        "target_line_count": len(exportable_items) + len(skipped_items),
        "export_scope": export_scope or "all_lines",
        "route_id": route_id or "",
        "route_label": route_label or "",
        "route_line_count": route_line_count,
        "selected_route_handles": list(selected_route_handles or []),
        "selected_route_labels": list(selected_route_labels or []),
        "selected_route_count": int(selected_route_count or 0),
        "route_summaries": list(route_summaries or []),
        "base_filename": _sanitize_export_base_filename(base_filename),
        "start_index": _safe_export_start_index(start_index),
        "digits": safe_digits,
        "items": exportable_items,
        "skipped_items": skipped_items,
        "warnings": warnings,
        "source_total_bytes": source_total_bytes,
        "source_size_known_count": source_size_known_count,
        "source_size_unknown_count": source_size_unknown_count,
        "destination_profile": destination_profile,
    }


def _copy_image_without_metadata(source_path: str, output_path: str) -> str:
    if os.path.splitext(source_path)[1].lower() != ".png" or os.path.splitext(output_path)[1].lower() != ".png":
        shutil.copy2(source_path, output_path)
        return "copied"

    try:
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
    except ImportError:
        shutil.copy2(source_path, output_path)
        return "metadata_unavailable"

    with Image.open(source_path) as image:
        image.load()
        clean_image = image.convert("RGBA") if image.mode == "P" and "transparency" in image.info else image.copy()
        clean_image.info.clear()
        clean_image.save(output_path, format="PNG", pnginfo=PngInfo())
    return "stripped"


def export_final_images(
    project: Project,
    output_dir: str,
    *,
    project_path: str = "",
    strip_metadata: bool = False,
    base_filename: str = "final",
    start_index: int = 1,
    digits: int = 4,
    target_line_ids: List[str] = None,
    export_scope: str = "all_lines",
    route_id: str = "",
    route_label: str = "",
    route_line_count: int = None,
    selected_route_handles: List[str] = None,
    selected_route_labels: List[str] = None,
    selected_route_count: int = None,
    route_summaries: List[dict] = None,
    write_manifest: bool = True,
) -> dict:
    exported_paths = []
    warnings = []
    metadata_stripped_count = 0
    export_dir_input = str(output_dir or "").strip()
    preview = preview_final_image_export(
        project,
        export_dir_input,
        project_path=project_path,
        base_filename=base_filename,
        start_index=start_index,
        digits=digits,
        target_line_ids=target_line_ids,
        export_scope=export_scope,
        route_id=route_id,
        route_label=route_label,
        route_line_count=route_line_count,
        selected_route_handles=selected_route_handles,
        selected_route_labels=selected_route_labels,
        selected_route_count=selected_route_count,
        route_summaries=route_summaries,
    )

    if not export_dir_input:
        return {
            "output_dir": "",
            "exported_count": 0,
            "skipped_count": preview["skipped_count"] + preview["exportable_count"],
            "metadata_stripping_enabled": bool(strip_metadata),
            "metadata_stripped_count": 0,
            "exported_paths": [],
            "skipped_line_ids": [item.get("line_id", "") for item in preview["items"] + preview["skipped_items"]],
            "warnings": ["Output folder is required. No images were exported."],
            "manifest_path": "",
            "preview": preview,
        }

    export_dir = preview["output_dir"]
    os.makedirs(export_dir, exist_ok=True)
    warnings.extend(preview.get("warnings", []))
    linked_source_paths = []
    for line in _ordered_export_lines(project):
        linked_source_paths.extend(_line_linked_image_paths(project, line, project_path))

    exported_items = []
    skipped_line_ids = [item.get("line_id", "") for item in preview["skipped_items"]]

    for item in preview["items"]:
        source_path = item["source_image_path"]
        output_path = item["output_path"]
        if any(_same_existing_file(linked_source_path, output_path) for linked_source_path in linked_source_paths):
            skipped_line_ids.append(item.get("line_id", ""))
            warnings.append(f"Skipped {item['output_filename']}: output path matches a project-linked source image.")
            continue

        if strip_metadata:
            export_mode = _copy_image_without_metadata(source_path, output_path)
            if export_mode == "stripped":
                metadata_stripped_count += 1
            elif export_mode == "metadata_unavailable":
                warnings.append(f"Copied {item['output_filename']} as-is because Pillow is unavailable for metadata stripping.")
            elif os.path.splitext(source_path)[1].lower() != ".png":
                warnings.append(f"Copied {item['output_filename']} as-is because metadata stripping only supports PNG.")
        else:
            shutil.copy2(source_path, output_path)

        exported_paths.append(output_path)
        exported_items.append({**item, "output_path": output_path})

    manifest_path = ""
    if write_manifest:
        manifest_path = os.path.join(export_dir, "export_manifest.json")
        manifest = _build_portable_final_export_manifest(
            preview=preview,
            exported_items=exported_items,
            export_dir=export_dir,
            project_path=project_path,
            strip_metadata=strip_metadata,
            metadata_stripped_count=metadata_stripped_count,
            skipped_line_ids=skipped_line_ids,
            warnings=warnings,
            exported_at=datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
        )
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)

    return {
        "output_dir": export_dir,
        "exported_count": len(exported_paths),
        "skipped_count": len(skipped_line_ids),
        "metadata_stripping_enabled": bool(strip_metadata),
        "metadata_stripped_count": metadata_stripped_count,
        "exported_paths": exported_paths,
        "skipped_line_ids": skipped_line_ids,
        "warnings": warnings,
        "manifest_path": manifest_path,
        "preview": preview,
    }


class SetEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return json.JSONEncoder.default(self, obj)


def _normalize_candidate_record(candidate):
    if isinstance(candidate, dict):
        path = str(candidate.get("path") or "")
        if not path:
            return None
        record = dict(candidate)
        record["path"] = path
        return record

    path = str(candidate) if candidate else ""
    if not path:
        return None
    return {"path": path}


def _normalize_generated_candidates(candidates) -> List[dict]:
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


def _normalize_gallery_variants(variants) -> List[dict]:
    normalized = []
    seen = set()
    for variant in variants or []:
        if not isinstance(variant, dict):
            continue
        record = dict(variant)
        path = str(record.get("path") or "").strip()
        if not path:
            continue
        record["path"] = path
        variant_key = str(record.get("id") or path)
        if variant_key in seen:
            continue
        normalized.append(record)
        seen.add(variant_key)
    return normalized


def ensure_project_folder_layout(project_path: str) -> dict:
    if not project_path:
        return {}

    project_dir = project_dir_from_path(project_path)
    folders = {}
    for folder_name in ("refs", "candidates", "routes", "exports", "workflows"):
        folder_path = os.path.join(project_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        folders[folder_name] = folder_path
    return folders


def project_dir_from_path(project_path: str) -> str:
    return os.path.dirname(os.path.abspath(project_path)) if project_path else ""


def is_project_relative_path(path: str) -> bool:
    return bool(path) and not os.path.isabs(path)


def resolve_project_asset_path(path: str, project_path: str) -> str:
    if not path or os.path.isabs(path) or not project_path:
        return path
    return os.path.abspath(os.path.join(project_dir_from_path(project_path), path))


def make_project_relative_path(path: str, project_path: str) -> str:
    if not path or not os.path.isabs(path) or not project_path:
        return path.replace(os.sep, "/") if path and is_project_relative_path(path) else path

    project_dir = project_dir_from_path(project_path)
    if not _is_inside_directory(path, project_dir):
        return path
    return os.path.relpath(path, project_dir).replace(os.sep, "/")


def _safe_asset_file_name(file_name: str) -> str:
    base_name = os.path.basename(file_name or "candidate")
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in base_name)
    return safe_name or "candidate"


class ProjectAssetsPreviewStaleError(RuntimeError):
    """Raised when Project Assets inputs no longer match a confirmed preview."""


def _normalized_asset_path_key(path: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(path))
    except (OSError, TypeError, ValueError):
        return str(path or "")


def _unique_copy_path(
    target_dir: str,
    file_name: str,
    *,
    reserved_paths: set[str] | None = None,
) -> str:
    safe_name = _safe_asset_file_name(file_name)
    stem, ext = os.path.splitext(safe_name)
    candidate_path = os.path.join(target_dir, safe_name)
    suffix = 1
    reserved = reserved_paths if reserved_paths is not None else set()
    while (
        os.path.exists(candidate_path)
        or _normalized_asset_path_key(candidate_path) in reserved
    ):
        candidate_path = os.path.join(target_dir, f"{stem}_{suffix}{ext}")
        suffix += 1
    return candidate_path


def _candidate_line_folder_name(line: PromptLine) -> str:
    line_index = getattr(line, "current_index", None)
    if isinstance(line_index, int) and line_index >= 0:
        return f"line_{line_index + 1:04d}"
    return _safe_asset_file_name(getattr(line, "id", "") or "line_unknown")


def _is_inside_directory(path: str, directory: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(directory)]) == os.path.abspath(directory)
    except ValueError:
        return False


def _paths_match_for_project(path_a: str, path_b: str, project_path: str) -> bool:
    if not path_a or not path_b:
        return False
    if str(path_a) == str(path_b):
        return True
    resolved_a = resolve_project_asset_path(str(path_a), project_path)
    resolved_b = resolve_project_asset_path(str(path_b), project_path)
    try:
        return os.path.normcase(os.path.abspath(resolved_a)) == os.path.normcase(os.path.abspath(resolved_b))
    except (OSError, ValueError):
        return False


def _update_lineage_candidate_path(project: Project, old_path: str, new_path: str, project_path: str):
    if not old_path or not new_path:
        return
    for line in getattr(project, "prompt_lines", []):
        lineage_info = getattr(line, "lineage_info", None)
        if isinstance(lineage_info, dict):
            for field_name in ("candidate_image_path", "parent_image_path"):
                lineage_path = lineage_info.get(field_name)
                if _paths_match_for_project(lineage_path, old_path, project_path):
                    lineage_info[field_name] = new_path
        source_info = getattr(line, "source_generation_info", None)
        if isinstance(source_info, dict):
            source_image_path = source_info.get("source_image_path")
            if _paths_match_for_project(source_image_path, old_path, project_path):
                source_info["source_image_path"] = new_path
        for variant in getattr(line, "gallery_variants", None) or []:
            if not isinstance(variant, dict):
                continue
            if _paths_match_for_project(variant.get("path"), old_path, project_path):
                variant["path"] = new_path
            variant_lineage = variant.get("lineage_info")
            if isinstance(variant_lineage, dict):
                lineage_candidate_path = variant_lineage.get("candidate_image_path")
                if _paths_match_for_project(lineage_candidate_path, old_path, project_path):
                    variant_lineage["candidate_image_path"] = new_path
                parent_image_path = variant_lineage.get("parent_image_path")
                if _paths_match_for_project(parent_image_path, old_path, project_path):
                    variant_lineage["parent_image_path"] = new_path
            variant_source = variant.get("source_generation_info")
            if isinstance(variant_source, dict):
                source_image_path = variant_source.get("source_image_path")
                if _paths_match_for_project(source_image_path, old_path, project_path):
                    variant_source["source_image_path"] = new_path


def _project_asset_source_records(project: Project) -> list[dict]:
    records = []
    for line_position, line in enumerate(getattr(project, "prompt_lines", [])):
        if getattr(line, "deleted", False) or getattr(line, "line_type", None) == "separator":
            continue
        for kind, values in (
            (
                "candidate",
                _normalize_generated_candidates(
                    getattr(line, "generated_candidates", None)
                ),
            ),
            (
                "variant",
                _normalize_gallery_variants(
                    getattr(line, "gallery_variants", None)
                ),
            ),
        ):
            for record_position, record in enumerate(values):
                records.append(
                    {
                        "line_position": line_position,
                        "line_id": str(getattr(line, "id", "") or ""),
                        "kind": kind,
                        "record_position": record_position,
                        "path": str(record.get("path") or "").strip(),
                    }
                )
    return records


def _resolve_project_asset_source(path: str, project_path: str) -> dict:
    try:
        resolved_path = resolve_project_asset_path(path, project_path)
        normalized_path = _normalized_asset_path_key(resolved_path)
    except (OSError, TypeError, ValueError) as exc:
        return {
            "resolved_path": "",
            "normalized_path": "",
            "exists": False,
            "readable": False,
            "size": 0,
            "mtime_ns": None,
            "error": str(exc),
        }

    if not resolved_path:
        return {
            "resolved_path": "",
            "normalized_path": normalized_path,
            "exists": False,
            "readable": False,
            "size": 0,
            "mtime_ns": None,
            "error": "source path is empty",
        }

    try:
        stat_result = os.stat(resolved_path)
        if not os.path.isfile(resolved_path):
            return {
                "resolved_path": resolved_path,
                "normalized_path": normalized_path,
                "exists": True,
                "readable": False,
                "size": 0,
                "mtime_ns": getattr(stat_result, "st_mtime_ns", None),
                "error": "source is not a regular file",
            }
        with open(resolved_path, "rb"):
            pass
        return {
            "resolved_path": resolved_path,
            "normalized_path": normalized_path,
            "exists": True,
            "readable": True,
            "size": int(stat_result.st_size),
            "mtime_ns": getattr(stat_result, "st_mtime_ns", None),
            "error": "",
        }
    except FileNotFoundError:
        return {
            "resolved_path": resolved_path,
            "normalized_path": normalized_path,
            "exists": False,
            "readable": False,
            "size": 0,
            "mtime_ns": None,
            "error": "source file is missing",
        }
    except (OSError, TypeError, ValueError) as exc:
        return {
            "resolved_path": resolved_path,
            "normalized_path": normalized_path,
            "exists": os.path.exists(resolved_path),
            "readable": False,
            "size": 0,
            "mtime_ns": None,
            "error": str(exc),
        }


def _project_assets_signature(
    project: Project,
    project_path: str,
    entries: list[dict],
) -> str:
    payload = {
        "project_path": _normalized_asset_path_key(project_path),
        "project_references": [
            {
                "id": str(getattr(line, "id", "") or ""),
                "current_index": getattr(line, "current_index", None),
                "deleted": bool(getattr(line, "deleted", False)),
                "line_type": getattr(line, "line_type", None),
                "generated_image_path": getattr(
                    line,
                    "generated_image_path",
                    None,
                ),
                "selected_candidate_path": getattr(
                    line,
                    "selected_candidate_path",
                    None,
                ),
                "generated_candidates": getattr(
                    line,
                    "generated_candidates",
                    None,
                ),
                "gallery_variants": getattr(line, "gallery_variants", None),
                "lineage_info": getattr(line, "lineage_info", None),
                "source_generation_info": getattr(
                    line,
                    "source_generation_info",
                    None,
                ),
            }
            for line in getattr(project, "prompt_lines", [])
        ],
        "entries": [
            {
                "line_position": entry.get("line_position"),
                "line_id": entry.get("line_id"),
                "kind": entry.get("kind"),
                "record_position": entry.get("record_position"),
                "source_path": entry.get("source_path"),
                "resolved_source_path": entry.get("resolved_source_path"),
                "source_size": entry.get("source_size"),
                "source_mtime_ns": entry.get("source_mtime_ns"),
                "status": entry.get("status"),
                "target_path": entry.get("target_path"),
            }
            for entry in entries
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def preview_copy_candidates_to_project(project: Project, project_path: str) -> dict:
    """Build a mutation-free preview of the existing Project Assets operation."""

    summary = {
        "valid": bool(project is not None and project_path),
        "reason": "",
        "reference_count": 0,
        "unique_source_count": 0,
        "planned_copy_count": 0,
        "copy_not_needed_count": 0,
        "already_local_count": 0,
        "reused_reference_count": 0,
        "project_inside_source_count": 0,
        "project_outside_source_count": 0,
        "estimated_copy_bytes": 0,
        "readable_source_count": 0,
        "missing_source_count": 0,
        "unreadable_source_count": 0,
        "collision_count": 0,
        "entries": [],
        "signature": "",
    }
    if project is None:
        summary["reason"] = "Project is missing."
        return summary
    if not project_path:
        summary["reason"] = "Save the Project before previewing Candidate / Variant copies."
        return summary

    project_dir = project_dir_from_path(project_path)
    candidates_root = os.path.join(project_dir, "candidates")
    source_records = _project_asset_source_records(project)
    summary["reference_count"] = len(source_records)

    unique_sources: dict[str, dict] = {}
    original_records = {}
    for record in source_records:
        source = _resolve_project_asset_source(record["path"], project_path)
        key = source["normalized_path"] or f"invalid:{record['path']}"
        original_records[
            (
                record["line_position"],
                record["kind"],
                record["record_position"],
            )
        ] = {
            **record,
            **source,
        }
        unique_sources.setdefault(key, source)

    summary["unique_source_count"] = len(unique_sources)
    summary["readable_source_count"] = sum(
        1 for source in unique_sources.values() if source["readable"]
    )
    summary["missing_source_count"] = sum(
        1 for source in unique_sources.values() if not source["exists"]
    )
    summary["unreadable_source_count"] = sum(
        1
        for source in unique_sources.values()
        if source["exists"] and not source["readable"]
    )
    summary["project_inside_source_count"] = sum(
        1
        for source in unique_sources.values()
        if source["resolved_path"]
        and _is_inside_directory(source["resolved_path"], project_dir)
    )
    summary["project_outside_source_count"] = (
        summary["unique_source_count"]
        - summary["project_inside_source_count"]
    )

    working_project = project.clone()
    reserved_paths: set[str] = set()

    def plan_record(
        line,
        line_position: int,
        kind: str,
        record_position: int,
        record: dict,
        line_folder: str,
        generated_path: str,
        selected_path: str,
    ) -> None:
        source_path = str(record.get("path") or "").strip()
        original = original_records.get(
            (line_position, kind, record_position),
            {"path": source_path, "resolved_path": ""},
        )
        source = _resolve_project_asset_source(source_path, project_path)
        source_will_exist_from_preview = (
            source["normalized_path"] in reserved_paths
        )
        entry = {
            "line_position": line_position,
            "line_id": str(getattr(line, "id", "") or ""),
            "kind": kind,
            "record_position": record_position,
            "source_path": str(original.get("path") or source_path),
            "resolved_source_path": str(
                original.get("resolved_path") or source["resolved_path"]
            ),
            "effective_source_path": source_path,
            "source_size": int(source["size"]),
            "source_mtime_ns": source["mtime_ns"],
            "inside_project": bool(
                source["resolved_path"]
                and _is_inside_directory(source["resolved_path"], project_dir)
            ),
            "target_path": "",
            "status": "",
            "error": source["error"],
        }

        if source_will_exist_from_preview:
            entry["status"] = "reused_prior_copy"
            summary["reused_reference_count"] += 1
        elif not source["exists"]:
            entry["status"] = "missing"
        elif not source["readable"]:
            entry["status"] = "unreadable"
        elif _is_inside_directory(source["resolved_path"], candidates_root):
            original_resolved = str(original.get("resolved_path") or "")
            if (
                original_resolved
                and not _is_inside_directory(original_resolved, candidates_root)
            ):
                entry["status"] = "reused_prior_copy"
                summary["reused_reference_count"] += 1
            else:
                entry["status"] = "already_local"
                summary["already_local_count"] += 1
        else:
            target_path = _unique_copy_path(
                line_folder,
                os.path.basename(source["resolved_path"]),
                reserved_paths=reserved_paths,
            )
            reserved_paths.add(_normalized_asset_path_key(target_path))
            entry["target_path"] = target_path
            entry["status"] = "copy"
            summary["planned_copy_count"] += 1
            summary["estimated_copy_bytes"] += int(source["size"])
            if os.path.basename(target_path) != _safe_asset_file_name(
                os.path.basename(source["resolved_path"])
            ):
                summary["collision_count"] += 1

            relative_target = make_project_relative_path(target_path, project_path)
            record["path"] = relative_target
            _update_lineage_candidate_path(
                working_project,
                source_path,
                relative_target,
                project_path,
            )
            if generated_path == source_path:
                line.generated_image_path = relative_target
            if selected_path == source_path:
                line.selected_candidate_path = relative_target

        summary["entries"].append(entry)

    for line_position, line in enumerate(
        getattr(working_project, "prompt_lines", [])
    ):
        if getattr(line, "deleted", False) or getattr(line, "line_type", None) == "separator":
            continue

        line_folder = os.path.join(
            candidates_root,
            _candidate_line_folder_name(line),
        )
        generated_path = getattr(line, "generated_image_path", None)
        selected_path = getattr(line, "selected_candidate_path", None)

        candidates = _normalize_generated_candidates(
            getattr(line, "generated_candidates", None)
        )
        for record_position, candidate in enumerate(candidates):
            plan_record(
                line,
                line_position,
                "candidate",
                record_position,
                candidate,
                line_folder,
                generated_path,
                selected_path,
            )
        line.generated_candidates = candidates

        variants = _normalize_gallery_variants(
            getattr(line, "gallery_variants", None)
        )
        for record_position, variant in enumerate(variants):
            plan_record(
                line,
                line_position,
                "variant",
                record_position,
                variant,
                line_folder,
                generated_path,
                selected_path,
            )
        line.gallery_variants = variants

    summary["copy_not_needed_count"] = (
        summary["already_local_count"]
        + summary["reused_reference_count"]
    )
    summary["signature"] = _project_assets_signature(
        project,
        project_path,
        summary["entries"],
    )
    return summary


def _copy_candidates_to_project_in_place(
    project: Project,
    project_path: str,
    *,
    created_paths: list[str],
) -> dict:
    if not project_path:
        return {"copied": 0, "skipped": 0, "missing": 0}

    folders = ensure_project_folder_layout(project_path)
    candidates_root = folders["candidates"]
    summary = {"copied": 0, "skipped": 0, "missing": 0, "unreadable": 0}

    for line in getattr(project, "prompt_lines", []):
        if getattr(line, "deleted", False) or getattr(line, "line_type", None) == "separator":
            continue

        line_folder = os.path.join(candidates_root, _candidate_line_folder_name(line))
        os.makedirs(line_folder, exist_ok=True)
        generated_path = getattr(line, "generated_image_path", None)
        selected_path = getattr(line, "selected_candidate_path", None)

        candidates = _normalize_generated_candidates(getattr(line, "generated_candidates", None))
        for candidate in candidates:
            source_path = candidate.get("path")
            if not source_path:
                summary["skipped"] += 1
                continue
            resolved_source_path = resolve_project_asset_path(source_path, project_path)
            source = _resolve_project_asset_source(source_path, project_path)
            if not source["exists"]:
                summary["missing"] += 1
                continue
            if not source["readable"]:
                summary["unreadable"] += 1
                summary["skipped"] += 1
                continue
            if _is_inside_directory(resolved_source_path, candidates_root):
                summary["skipped"] += 1
                continue

            target_path = _unique_copy_path(line_folder, os.path.basename(resolved_source_path))
            shutil.copy2(resolved_source_path, target_path)
            created_paths.append(target_path)
            candidate["path"] = make_project_relative_path(target_path, project_path)
            _update_lineage_candidate_path(project, source_path, candidate["path"], project_path)
            if generated_path == source_path:
                line.generated_image_path = candidate["path"]
            if selected_path == source_path:
                line.selected_candidate_path = candidate["path"]
            summary["copied"] += 1

        line.generated_candidates = candidates

        variants = _normalize_gallery_variants(getattr(line, "gallery_variants", None))
        for variant in variants:
            source_path = variant.get("path")
            if not source_path:
                summary["skipped"] += 1
                continue
            resolved_source_path = resolve_project_asset_path(source_path, project_path)
            source = _resolve_project_asset_source(source_path, project_path)
            if not source["exists"]:
                summary["missing"] += 1
                continue
            if not source["readable"]:
                summary["unreadable"] += 1
                summary["skipped"] += 1
                continue
            if _is_inside_directory(resolved_source_path, candidates_root):
                summary["skipped"] += 1
                continue

            target_path = _unique_copy_path(line_folder, os.path.basename(resolved_source_path))
            shutil.copy2(resolved_source_path, target_path)
            created_paths.append(target_path)
            variant["path"] = make_project_relative_path(target_path, project_path)
            _update_lineage_candidate_path(project, source_path, variant["path"], project_path)
            summary["copied"] += 1

        line.gallery_variants = variants

    return summary


def copy_candidates_to_project(
    project: Project,
    project_path: str,
    *,
    expected_signature: str = "",
) -> dict:
    """Copy Candidate / Variant assets after revalidating an optional preview."""

    preview = preview_copy_candidates_to_project(project, project_path)
    if expected_signature and preview.get("signature") != expected_signature:
        raise ProjectAssetsPreviewStaleError(
            "Project Assets preview is stale. Refresh the preview and confirm again."
        )

    working_project = project.clone()
    created_paths: list[str] = []
    try:
        summary = _copy_candidates_to_project_in_place(
            working_project,
            project_path,
            created_paths=created_paths,
        )
    except Exception:
        for created_path in reversed(created_paths):
            try:
                if os.path.isfile(created_path):
                    os.remove(created_path)
            except OSError:
                logger.warning(
                    "Could not remove partial Project Assets copy: %s",
                    created_path,
                    exc_info=True,
                )
        raise

    if summary.get("copied") != preview.get("planned_copy_count"):
        for created_path in reversed(created_paths):
            try:
                if os.path.isfile(created_path):
                    os.remove(created_path)
            except OSError:
                logger.warning(
                    "Could not remove stale Project Assets copy: %s",
                    created_path,
                    exc_info=True,
                )
        raise ProjectAssetsPreviewStaleError(
            "Project Assets inputs changed during Apply. Refresh the preview."
        )

    project.__dict__.clear()
    project.__dict__.update(working_project.__dict__)
    return {
        **summary,
        "signature": preview.get("signature", ""),
        "estimated_copy_bytes": preview.get("estimated_copy_bytes", 0),
        "_created_paths": list(created_paths),
    }


def save_project_to_json_atomically(project: Project, project_path: str) -> None:
    """Compatibility alias for the safe normal Project JSON writer."""

    _save_project_to_json_atomically(project, project_path)


def copy_candidates_to_project_and_save_atomically(
    project: Project,
    project_path: str,
    *,
    expected_signature: str = "",
) -> dict:
    """Apply Project Assets and preserve Project/files/JSON on any save failure."""

    previous_project = project.clone()
    summary = {}
    try:
        summary = copy_candidates_to_project(
            project,
            project_path,
            expected_signature=expected_signature,
        )
        save_project_to_json_atomically(project, project_path)
    except Exception:
        for created_path in reversed(summary.get("_created_paths", [])):
            try:
                if os.path.isfile(created_path):
                    os.remove(created_path)
            except OSError:
                logger.warning(
                    "Could not roll back Project Assets copy after save failure: %s",
                    created_path,
                    exc_info=True,
                )
        project.__dict__.clear()
        project.__dict__.update(previous_project.__dict__)
        raise
    return summary


def _relativize_project_candidate_paths(data: dict, project_path: str) -> dict:
    for line_data in data.get("prompt_lines", []):
        if line_data.get("line_type") == "separator":
            continue
        for candidate in line_data.get("generated_candidates", []) or []:
            if isinstance(candidate, dict):
                candidate["path"] = make_project_relative_path(candidate.get("path") or "", project_path)
        for variant in line_data.get("gallery_variants", []) or []:
            if not isinstance(variant, dict):
                continue
            if variant.get("path"):
                variant["path"] = make_project_relative_path(variant["path"], project_path)
            lineage_info = variant.get("lineage_info")
            if isinstance(lineage_info, dict):
                for field_name in ("candidate_image_path", "parent_image_path"):
                    if lineage_info.get(field_name):
                        lineage_info[field_name] = make_project_relative_path(lineage_info[field_name], project_path)
            source_info = variant.get("source_generation_info")
            if isinstance(source_info, dict) and source_info.get("source_image_path"):
                source_info["source_image_path"] = make_project_relative_path(source_info["source_image_path"], project_path)
        for field_name in ("selected_candidate_path", "generated_image_path"):
            if line_data.get(field_name):
                line_data[field_name] = make_project_relative_path(line_data[field_name], project_path)
        lineage_info = line_data.get("lineage_info")
        if isinstance(lineage_info, dict):
            for field_name in ("candidate_image_path", "parent_image_path"):
                if lineage_info.get(field_name):
                    lineage_info[field_name] = make_project_relative_path(lineage_info[field_name], project_path)
    return data


def _project_to_serializable_data(project: Project, output_path: str) -> dict:
    from core.operations import get_node_attribute_labels, get_project_attribute_groups, get_project_attribute_label_usage_counts, get_project_custom_attribute_labels, normalize_module_library

    normalize_module_library(project)
    get_node_attribute_labels(project)
    get_project_custom_attribute_labels(project)
    get_project_attribute_label_usage_counts(project)
    get_project_attribute_groups(project)
    for line in getattr(project, "prompt_lines", []):
        if getattr(line, "line_type", None) == "separator":
            continue
        line.generated_candidates = _normalize_generated_candidates(
            getattr(line, "generated_candidates", None)
        )
        line.gallery_variants = _normalize_gallery_variants(
            getattr(line, "gallery_variants", None)
        )
    data = asdict(project)
    data = _relativize_project_candidate_paths(data, output_path)
    data["project_metadata"] = _normalize_project_metadata(getattr(project, "project_metadata", None))
    return data


def _write_project_json(project: Project, output_path: str, handle) -> None:
    data = _project_to_serializable_data(project, output_path)
    json.dump(data, handle, cls=SetEncoder, indent=2, ensure_ascii=False)


def _save_project_to_json_atomically(project: Project, output_path: str) -> None:
    output_path = os.path.abspath(os.fspath(output_path))
    output_dir = os.path.dirname(output_path)
    file_name = os.path.basename(output_path) or "project.json"
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_dir,
            prefix=f".{file_name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            _write_project_json(project, output_path, temporary_file)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, output_path)
        temporary_path = ""
    except Exception:
        if temporary_path:
            try:
                if os.path.isfile(temporary_path):
                    os.remove(temporary_path)
            except OSError:
                logger.warning(
                    "Could not remove temporary Project JSON: %s",
                    temporary_path,
                    exc_info=True,
                )
        raise


def save_project_to_json(project: Project, output_path: str) -> None:
    """Serialize and atomically replace a normal Project JSON destination."""

    _save_project_to_json_atomically(project, output_path)


def _canonicalize_project_digest_value(value):
    if isinstance(value, dict):
        return {
            str(key): _canonicalize_project_digest_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize_project_digest_value(item) for item in value]
    if isinstance(value, set):
        normalized_items = [
            _canonicalize_project_digest_value(item)
            for item in value
        ]
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                default=str,
            ),
        )
    return value


def _stable_project_digest(value) -> str:
    encoded = json.dumps(
        _canonicalize_project_digest_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_real_path(path: str) -> str:
    return os.path.normcase(
        os.path.realpath(
            os.path.abspath(
                os.path.expanduser(str(path or ""))
            )
        )
    )


def _is_inside_real_directory(path: str, directory: str) -> bool:
    try:
        normalized_path = _normalized_real_path(path)
        normalized_directory = _normalized_real_path(directory)
        return (
            os.path.commonpath([normalized_path, normalized_directory])
            == normalized_directory
        )
    except (OSError, TypeError, ValueError):
        return False


def _normalize_serialized_project_asset_reference(
    value: str,
    *,
    project_root: str,
    generated_root: str,
    candidates_root: str,
) -> str:
    raw_value = str(value or "").strip()
    if not raw_value or "\0" in raw_value:
        return ""
    try:
        portable_value = raw_value.replace("\\", os.sep).replace("/", os.sep)
        if os.path.isabs(portable_value):
            resolved = _normalized_real_path(portable_value)
        else:
            resolved = _normalized_real_path(
                os.path.join(project_root, portable_value)
            )
    except (OSError, TypeError, ValueError):
        return ""

    if not _is_inside_real_directory(resolved, project_root):
        return ""
    if not (
        _is_inside_real_directory(resolved, generated_root)
        or _is_inside_real_directory(resolved, candidates_root)
    ):
        return ""
    return resolved


def collect_project_serialized_path_references(
    project: Project,
    *,
    project_root: str,
) -> dict:
    """Collect Project-local asset paths from the normal serialized form."""

    normalized_root = _normalized_real_path(project_root)
    generated_root = _normalized_real_path(
        os.path.join(normalized_root, "generated")
    )
    candidates_root = _normalized_real_path(
        os.path.join(normalized_root, "candidates")
    )
    serialization_path = os.path.join(normalized_root, "project.json")
    serializable_data = _project_to_serializable_data(
        project.clone(),
        serialization_path,
    )
    references: dict[str, list[dict]] = {}

    def visit(value, location: str) -> None:
        if isinstance(value, str):
            normalized_path = _normalize_serialized_project_asset_reference(
                value,
                project_root=normalized_root,
                generated_root=generated_root,
                candidates_root=candidates_root,
            )
            if normalized_path:
                references.setdefault(normalized_path, []).append(
                    {
                        "location": location,
                        "raw_path": value,
                    }
                )
            return
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, f"{location}.{key}")
            return
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                visit(item, f"{location}[{index}]")
            return
        if isinstance(value, set):
            normalized_items = sorted(
                value,
                key=lambda item: json.dumps(
                    _canonicalize_project_digest_value(item),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    default=str,
                ),
            )
            for index, item in enumerate(normalized_items):
                visit(item, f"{location}[{index}]")

    visit(serializable_data, "$")
    reference_payload = [
        {
            "path": path,
            "references": sorted(
                entries,
                key=lambda entry: (
                    str(entry.get("location") or ""),
                    str(entry.get("raw_path") or ""),
                ),
            ),
        }
        for path, entries in sorted(references.items())
    ]
    return {
        "project_root": normalized_root,
        "generated_root": generated_root,
        "candidates_root": candidates_root,
        "references": references,
        "reference_count": sum(len(items) for items in references.values()),
        "unique_path_count": len(references),
        "reference_digest": _stable_project_digest(reference_payload),
        "serialization_digest": _stable_project_digest(serializable_data),
    }


def _cleanup_relative_path(path: str, project_root: str) -> str:
    try:
        return os.path.relpath(path, project_root).replace(os.sep, "/")
    except (OSError, TypeError, ValueError):
        return str(path or "")


def _cleanup_file_snapshot(path: str, expected_root: str) -> dict:
    normalized_path = _normalized_real_path(path)
    snapshot = {
        "path": normalized_path,
        "size": 0,
        "mtime_ns": None,
        "sha256": "",
        "error": "",
    }
    try:
        if os.path.islink(path):
            snapshot["error"] = "symlink"
            return snapshot
        if not _is_inside_real_directory(path, expected_root):
            snapshot["error"] = "outside project root"
            return snapshot
        before = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            snapshot["error"] = "not a regular file"
            return snapshot
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = os.stat(path, follow_symlinks=False)
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            snapshot["error"] = "file changed during scan"
            return snapshot
        snapshot.update(
            {
                "size": int(after.st_size),
                "mtime_ns": int(after.st_mtime_ns),
                "sha256": digest.hexdigest(),
            }
        )
    except FileNotFoundError:
        snapshot["error"] = "missing"
    except (OSError, TypeError, ValueError) as exc:
        snapshot["error"] = f"unreadable: {exc}"
    return snapshot


def _enumerate_cleanup_images(
    root: str,
    *,
    project_root: str,
    label: str,
) -> tuple[list[dict], list[dict], list[str]]:
    records = []
    skipped = []
    warnings = []
    if not os.path.exists(root):
        warnings.append(f"{label} directory missing")
        return records, skipped, warnings
    if os.path.islink(root) or not _is_inside_real_directory(root, project_root):
        warnings.append(f"{label} directory is unsafe")
        skipped.append(
            {
                "path": root,
                "relative_path": _cleanup_relative_path(root, project_root),
                "status": "skipped",
                "reason": "symlink or outside project root",
            }
        )
        return records, skipped, warnings
    if not os.path.isdir(root):
        warnings.append(f"{label} path is not a directory")
        return records, skipped, warnings

    for current_root, dir_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        safe_dirs = []
        for dir_name in sorted(dir_names):
            dir_path = os.path.join(current_root, dir_name)
            if os.path.islink(dir_path) or not _is_inside_real_directory(
                dir_path,
                root,
            ):
                skipped.append(
                    {
                        "path": dir_path,
                        "relative_path": _cleanup_relative_path(
                            dir_path,
                            project_root,
                        ),
                        "status": "skipped",
                        "reason": "symlink or outside project root",
                    }
                )
                continue
            safe_dirs.append(dir_name)
        dir_names[:] = safe_dirs

        for file_name in sorted(file_names):
            extension = os.path.splitext(file_name)[1].lower()
            if extension not in IMAGE_METADATA_EXTENSIONS:
                continue
            file_path = os.path.join(current_root, file_name)
            relative_path = _cleanup_relative_path(file_path, project_root)
            if os.path.islink(file_path):
                skipped.append(
                    {
                        "path": file_path,
                        "relative_path": relative_path,
                        "status": "skipped",
                        "reason": "symlink",
                    }
                )
                continue
            if not _is_inside_real_directory(file_path, root):
                skipped.append(
                    {
                        "path": file_path,
                        "relative_path": relative_path,
                        "status": "skipped",
                        "reason": "outside project root",
                    }
                )
                continue
            try:
                file_stat = os.stat(file_path, follow_symlinks=False)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise OSError("not a regular file")
                with open(file_path, "rb"):
                    pass
            except (OSError, TypeError, ValueError) as exc:
                skipped.append(
                    {
                        "path": file_path,
                        "relative_path": relative_path,
                        "status": "skipped",
                        "reason": f"unreadable: {exc}",
                    }
                )
                continue
            records.append(
                {
                    "path": _normalized_real_path(file_path),
                    "relative_path": relative_path,
                    "size": int(file_stat.st_size),
                    "mtime_ns": int(file_stat.st_mtime_ns),
                    "sha256": "",
                }
            )
    records.sort(key=lambda item: item["relative_path"])
    return records, skipped, warnings


def _cleanup_preview_signature(
    *,
    project_path: str,
    references: dict,
    generated_files: list[dict],
    candidate_files: list[dict],
    eligible_items: list[dict],
) -> str:
    payload = {
        "project_path": _normalized_real_path(project_path),
        "project_serialization_digest": references.get(
            "serialization_digest",
            "",
        ),
        "project_reference_digest": references.get("reference_digest", ""),
        "generated_files": [
            {
                key: item.get(key)
                for key in (
                    "path",
                    "relative_path",
                    "size",
                    "mtime_ns",
                    "sha256",
                )
            }
            for item in generated_files
        ],
        "candidate_files": [
            {
                key: item.get(key)
                for key in (
                    "path",
                    "relative_path",
                    "size",
                    "mtime_ns",
                    "sha256",
                )
            }
            for item in candidate_files
        ],
        "eligible_order": [
            {
                "source_path": item.get("source_path"),
                "retained_paths": item.get("retained_paths", []),
                "size_bytes": item.get("size_bytes"),
                "sha256": item.get("sha256"),
            }
            for item in eligible_items
        ],
    }
    return _stable_project_digest(payload)


def preview_verified_project_asset_duplicate_cleanup(
    project: Project,
    project_path: str,
) -> dict:
    """Preview only verified generated/ duplicates retained in candidates/."""

    summary = {
        "valid": False,
        "reason": "",
        "project_path": "",
        "project_root": "",
        "generated_root": "",
        "candidates_root": "",
        "eligible_items": [],
        "protected_items": [],
        "skipped_items": [],
        "eligible_count": 0,
        "eligible_bytes": 0,
        "protected_count": 0,
        "skipped_count": 0,
        "duplicate_group_count": 0,
        "scan_file_count": 0,
        "scanned_generated_count": 0,
        "scanned_candidate_count": 0,
        "retained_copy_count": 0,
        "signature": "",
        "warnings": [],
    }
    if project is None:
        summary["reason"] = "Project is missing."
        return summary
    if not project_path:
        summary["reason"] = "Project not saved."
        return summary

    try:
        normalized_project_path = _normalized_real_path(project_path)
    except (OSError, TypeError, ValueError):
        summary["reason"] = "Project path invalid."
        return summary
    if not os.path.isfile(normalized_project_path):
        summary["reason"] = "Project not saved."
        return summary

    project_root = _normalized_real_path(
        os.path.dirname(normalized_project_path)
    )
    generated_root = _normalized_real_path(
        os.path.join(project_root, "generated")
    )
    candidates_root = _normalized_real_path(
        os.path.join(project_root, "candidates")
    )
    summary.update(
        {
            "valid": True,
            "project_path": normalized_project_path,
            "project_root": project_root,
            "generated_root": generated_root,
            "candidates_root": candidates_root,
        }
    )

    try:
        reference_summary = collect_project_serialized_path_references(
            project,
            project_root=project_root,
        )
    except Exception as exc:
        summary["valid"] = False
        summary["reason"] = f"Project serialization failed: {exc}"
        return summary

    generated_files, generated_skipped, generated_warnings = (
        _enumerate_cleanup_images(
            generated_root,
            project_root=project_root,
            label="generated",
        )
    )
    candidate_files, candidate_skipped, candidate_warnings = (
        _enumerate_cleanup_images(
            candidates_root,
            project_root=project_root,
            label="candidates",
        )
    )
    summary["skipped_items"].extend(generated_skipped)
    summary["skipped_items"].extend(candidate_skipped)
    summary["warnings"].extend(generated_warnings)
    summary["warnings"].extend(candidate_warnings)
    summary["scanned_generated_count"] = len(generated_files)
    summary["scanned_candidate_count"] = len(candidate_files)
    summary["scan_file_count"] = len(generated_files) + len(candidate_files)

    candidate_by_size: dict[int, list[dict]] = {}
    for candidate in candidate_files:
        candidate_by_size.setdefault(candidate["size"], []).append(candidate)
    reference_map = reference_summary["references"]
    scanned_or_skipped_paths = {
        str(item.get("path") or "")
        for item in (
            generated_files
            + candidate_files
            + summary["skipped_items"]
        )
        if item.get("path")
    }
    for referenced_path in sorted(reference_map):
        if referenced_path in scanned_or_skipped_paths:
            continue
        if not (
            _is_inside_real_directory(referenced_path, generated_root)
            or _is_inside_real_directory(referenced_path, candidates_root)
        ):
            continue
        if not os.path.exists(referenced_path):
            summary["skipped_items"].append(
                {
                    "path": referenced_path,
                    "relative_path": _cleanup_relative_path(
                        referenced_path,
                        project_root,
                    ),
                    "status": "skipped",
                    "reason": "missing",
                }
            )
    duplicate_groups = set()
    retained_paths = set()

    for source in generated_files:
        same_size_candidates = candidate_by_size.get(source["size"], [])
        source_reference_count = len(reference_map.get(source["path"], []))
        if not same_size_candidates:
            summary["protected_items"].append(
                {
                    "source_path": source["path"],
                    "source_relative_path": source["relative_path"],
                    "retained_paths": [],
                    "retained_relative_paths": [],
                    "size_bytes": source["size"],
                    "sha256": "",
                    "source_reference_count": source_reference_count,
                    "retained_reference_count": 0,
                    "status": "protected",
                    "reason": "no referenced retained candidate copy",
                }
            )
            continue

        source_snapshot = _cleanup_file_snapshot(
            source["path"],
            generated_root,
        )
        if source_snapshot["error"]:
            summary["skipped_items"].append(
                {
                    "path": source["path"],
                    "relative_path": source["relative_path"],
                    "status": "skipped",
                    "reason": source_snapshot["error"],
                }
            )
            continue
        source.update(source_snapshot)

        identical_candidates = []
        for candidate in same_size_candidates:
            if not candidate.get("sha256"):
                candidate_snapshot = _cleanup_file_snapshot(
                    candidate["path"],
                    candidates_root,
                )
                if candidate_snapshot["error"]:
                    summary["skipped_items"].append(
                        {
                            "path": candidate["path"],
                            "relative_path": candidate["relative_path"],
                            "status": "skipped",
                            "reason": candidate_snapshot["error"],
                        }
                    )
                    candidate["hash_error"] = candidate_snapshot["error"]
                    continue
                candidate.update(candidate_snapshot)
            if (
                not candidate.get("hash_error")
                and candidate.get("sha256") == source["sha256"]
            ):
                identical_candidates.append(candidate)

        if not identical_candidates:
            summary["protected_items"].append(
                {
                    "source_path": source["path"],
                    "source_relative_path": source["relative_path"],
                    "retained_paths": [],
                    "retained_relative_paths": [],
                    "size_bytes": source["size"],
                    "sha256": source["sha256"],
                    "source_reference_count": source_reference_count,
                    "retained_reference_count": 0,
                    "status": "protected",
                    "reason": "hash mismatch",
                }
            )
            continue

        duplicate_groups.add((source["size"], source["sha256"]))
        referenced_candidates = [
            candidate
            for candidate in identical_candidates
            if reference_map.get(candidate["path"])
        ]
        retained_reference_count = sum(
            len(reference_map.get(candidate["path"], []))
            for candidate in referenced_candidates
        )
        item = {
            "source_path": source["path"],
            "source_relative_path": source["relative_path"],
            "retained_paths": [
                candidate["path"]
                for candidate in referenced_candidates
            ],
            "retained_relative_paths": [
                candidate["relative_path"]
                for candidate in referenced_candidates
            ],
            "retained_files": [
                {
                    "path": candidate["path"],
                    "relative_path": candidate["relative_path"],
                    "size": candidate["size"],
                    "mtime_ns": candidate["mtime_ns"],
                    "sha256": candidate["sha256"],
                }
                for candidate in referenced_candidates
            ],
            "size_bytes": source["size"],
            "source_mtime_ns": source["mtime_ns"],
            "sha256": source["sha256"],
            "source_reference_count": source_reference_count,
            "retained_reference_count": retained_reference_count,
            "status": "protected",
            "reason": "",
        }
        if source_reference_count:
            item["reason"] = "source is still referenced"
            summary["protected_items"].append(item)
        elif not referenced_candidates:
            item["reason"] = "no referenced retained candidate copy"
            summary["protected_items"].append(item)
        else:
            item["status"] = "eligible"
            item["reason"] = (
                "byte-identical retained Project reference exists"
            )
            summary["eligible_items"].append(item)
            retained_paths.update(item["retained_paths"])

    summary["eligible_items"].sort(
        key=lambda item: item["source_relative_path"]
    )
    summary["protected_items"].sort(
        key=lambda item: item["source_relative_path"]
    )
    summary["skipped_items"].sort(
        key=lambda item: str(item.get("relative_path") or item.get("path") or "")
    )
    summary["eligible_count"] = len(summary["eligible_items"])
    summary["eligible_bytes"] = sum(
        int(item["size_bytes"])
        for item in summary["eligible_items"]
    )
    summary["protected_count"] = len(summary["protected_items"])
    summary["skipped_count"] = len(summary["skipped_items"])
    summary["duplicate_group_count"] = len(duplicate_groups)
    summary["retained_copy_count"] = len(retained_paths)
    summary["signature"] = _cleanup_preview_signature(
        project_path=normalized_project_path,
        references=reference_summary,
        generated_files=generated_files,
        candidate_files=candidate_files,
        eligible_items=summary["eligible_items"],
    )
    return summary


def _cleanup_file_metadata_matches(
    path: str,
    expected_root: str,
    *,
    size: int,
    mtime_ns: int,
) -> bool:
    """Cheap fail-closed check after the authoritative fresh hash Preview."""

    try:
        if os.path.islink(path):
            return False
        if not _is_inside_real_directory(path, expected_root):
            return False
        file_stat = os.stat(path, follow_symlinks=False)
        return bool(
            stat.S_ISREG(file_stat.st_mode)
            and int(file_stat.st_size) == int(size)
            and int(file_stat.st_mtime_ns) == int(mtime_ns)
        )
    except (OSError, TypeError, ValueError):
        return False


def _cleanup_item_metadata_error(
    item: dict,
    *,
    generated_root: str,
    candidates_root: str,
) -> str:
    if not _cleanup_file_metadata_matches(
        item["source_path"],
        generated_root,
        size=item["size_bytes"],
        mtime_ns=item["source_mtime_ns"],
    ):
        return "A generated source changed after preview."
    for retained in item.get("retained_files", []):
        if not _cleanup_file_metadata_matches(
            retained["path"],
            candidates_root,
            size=retained["size"],
            mtime_ns=retained["mtime_ns"],
        ):
            return "A retained candidate copy changed after preview."
    return ""


def delete_verified_project_asset_source_duplicates(
    project: Project,
    project_path: str,
    stored_preview: dict,
) -> dict:
    """Delete only source files from a fresh, fully matching cleanup preview."""

    if not isinstance(stored_preview, dict) or not stored_preview.get(
        "signature"
    ):
        raise ProjectAssetsPreviewStaleError(
            "Duplicate cleanup preview is missing."
        )
    if not stored_preview.get("eligible_count"):
        raise ProjectAssetsPreviewStaleError(
            "Duplicate cleanup preview has no eligible files."
        )

    fresh_preview = preview_verified_project_asset_duplicate_cleanup(
        project,
        project_path,
    )
    if (
        not fresh_preview.get("valid")
        or fresh_preview.get("signature") != stored_preview.get("signature")
    ):
        raise ProjectAssetsPreviewStaleError(
            "Duplicate cleanup preview is stale. Scan again before deleting."
        )

    generated_root = fresh_preview["generated_root"]
    candidates_root = fresh_preview["candidates_root"]
    eligible_items = list(fresh_preview["eligible_items"])
    for item in eligible_items:
        metadata_error = _cleanup_item_metadata_error(
            item,
            generated_root=generated_root,
            candidates_root=candidates_root,
        )
        if metadata_error:
            raise ProjectAssetsPreviewStaleError(metadata_error)

    deleted_files = []
    deleted_bytes = 0
    for index, item in enumerate(eligible_items):
        metadata_error = _cleanup_item_metadata_error(
            item,
            generated_root=generated_root,
            candidates_root=candidates_root,
        )
        if metadata_error:
            return {
                "status": (
                    "partial_stale" if deleted_files else "stale"
                ),
                "deleted_files": deleted_files,
                "deleted_count": len(deleted_files),
                "deleted_bytes": deleted_bytes,
                "failed_file": item["source_relative_path"],
                "error": metadata_error,
                "remaining_eligible_files": [
                    remaining["source_relative_path"]
                    for remaining in eligible_items[index:]
                ],
                "retained_copy_count": fresh_preview[
                    "retained_copy_count"
                ],
                "project_json_unchanged": True,
                "candidates_unchanged": True,
            }
        try:
            os.remove(item["source_path"])
        except OSError as exc:
            return {
                "status": "partial_failure",
                "deleted_files": deleted_files,
                "deleted_count": len(deleted_files),
                "deleted_bytes": deleted_bytes,
                "failed_file": item["source_relative_path"],
                "error": str(exc),
                "remaining_eligible_files": [
                    remaining["source_relative_path"]
                    for remaining in eligible_items[index:]
                ],
                "retained_copy_count": fresh_preview[
                    "retained_copy_count"
                ],
                "project_json_unchanged": True,
                "candidates_unchanged": True,
            }
        deleted_files.append(item["source_relative_path"])
        deleted_bytes += int(item["size_bytes"])

    return {
        "status": "success",
        "deleted_files": deleted_files,
        "deleted_count": len(deleted_files),
        "deleted_bytes": deleted_bytes,
        "failed_file": "",
        "error": "",
        "remaining_eligible_files": [],
        "retained_copy_count": fresh_preview["retained_copy_count"],
        "project_json_unchanged": True,
        "candidates_unchanged": True,
    }


def get_global_module_library_path(settings: dict = None) -> str:
    from core.settings import DEFAULT_GLOBAL_MODULE_LIBRARY_DIR

    settings = settings or {}
    module_dir = settings.get("global_module_library_dir") or DEFAULT_GLOBAL_MODULE_LIBRARY_DIR
    module_dir = os.path.abspath(os.path.expanduser(module_dir))
    return os.path.join(module_dir, "global_modules.json")


def load_global_module_library(settings: dict = None) -> dict:
    from core.operations import normalize_module_library

    library_path = get_global_module_library_path(settings)
    if not os.path.exists(library_path):
        return {}
    try:
        with open(library_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    if isinstance(data, dict) and isinstance(data.get("module_library"), dict):
        data = data["module_library"]
    if not isinstance(data, dict):
        return {}
    return normalize_module_library(data)


def save_global_module_library(module_library: dict, settings: dict = None) -> str:
    from core.operations import normalize_module_library

    library_path = get_global_module_library_path(settings)
    library_dir = os.path.dirname(library_path)
    os.makedirs(library_dir, exist_ok=True)
    normalized_library = normalize_module_library(module_library or {})
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=library_dir,
            prefix=f".{os.path.basename(library_path)}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            json.dump(
                normalized_library,
                temporary_file,
                cls=SetEncoder,
                indent=2,
                ensure_ascii=False,
            )
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, library_path)
        temporary_path = ""
    except Exception:
        if temporary_path:
            try:
                if os.path.isfile(temporary_path):
                    os.remove(temporary_path)
            except OSError:
                logger.warning(
                    "Could not remove temporary Global Module Library: %s",
                    temporary_path,
                    exc_info=True,
                )
        raise
    return library_path


def load_project_from_json(json_path: str) -> Project:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    project = Project(source_directory=data.get("source_directory", ""))
    project.merge_by_word_only = bool(data.get("merge_by_word_only", True))
    project.project_metadata = _normalize_project_metadata(data.get("project_metadata"))
    project.route_snapshots = data.get("route_snapshots") if isinstance(data.get("route_snapshots"), list) else []
    project.line_groups = {
        str(name): [str(line_id) for line_id in line_ids]
        for name, line_ids in data.get("line_groups", {}).items()
        if isinstance(line_ids, list)
    }
    project.module_library = data.get("module_library", {}) or {}
    from core.operations import get_node_attribute_labels, get_project_attribute_groups, get_project_attribute_label_usage_counts, get_project_custom_attribute_labels, normalize_module_library

    normalize_module_library(project)
    raw_attribute_labels = data.get("node_attribute_labels", {})
    project.node_attribute_labels = raw_attribute_labels if isinstance(raw_attribute_labels, dict) else {}
    get_node_attribute_labels(project)
    raw_custom_attribute_labels = data.get("custom_attribute_labels", [])
    project.custom_attribute_labels = raw_custom_attribute_labels if isinstance(raw_custom_attribute_labels, list) else []
    get_project_custom_attribute_labels(project)
    raw_attribute_label_usage_counts = data.get("attribute_label_usage_counts", {})
    project.attribute_label_usage_counts = raw_attribute_label_usage_counts if isinstance(raw_attribute_label_usage_counts, dict) else {}
    get_project_attribute_label_usage_counts(project)
    raw_attribute_groups = data.get("attribute_groups", {})
    project.attribute_groups = raw_attribute_groups if isinstance(raw_attribute_groups, dict) else {}
    get_project_attribute_groups(project)

    valid_pl_keys = {f.name for f in dataclasses.fields(PromptLine)}
    for line_data in data.get("prompt_lines", []):
        filtered_data = {k: v for k, v in line_data.items() if k in valid_pl_keys}
        filtered_data["negative_prompt"] = filtered_data.get("negative_prompt") or ""
        source_generation_info = filtered_data.get("source_generation_info")
        filtered_data["source_generation_info"] = source_generation_info if isinstance(source_generation_info, dict) else {}
        lineage_info = filtered_data.get("lineage_info")
        filtered_data["lineage_info"] = lineage_info if isinstance(lineage_info, dict) else {}
        filtered_data["generated_candidates"] = _normalize_generated_candidates(
            filtered_data.get("generated_candidates")
        )
        filtered_data["gallery_variants"] = _normalize_gallery_variants(
            filtered_data.get("gallery_variants")
        )
        if not filtered_data.get("selected_candidate_path"):
            generated_image_path = filtered_data.get("generated_image_path")
            if generated_image_path and any(
                candidate.get("path") == generated_image_path
                for candidate in filtered_data["generated_candidates"]
            ):
                filtered_data["selected_candidate_path"] = generated_image_path
        prompt_line = PromptLine(**filtered_data)
        project.prompt_lines.append(prompt_line)

    valid_pn_keys = {f.name for f in dataclasses.fields(PromptNode)}
    for node_id, node_data in data.get("nodes", {}).items():
        node_data["prompt_line_ids"] = set(node_data.get("prompt_line_ids", []))
        node_data["prev_node_ids"] = set(node_data.get("prev_node_ids", []))
        node_data["next_node_ids"] = set(node_data.get("next_node_ids", []))
        filtered_data = {k: v for k, v in node_data.items() if k in valid_pn_keys}
        project.nodes[node_id] = PromptNode(**filtered_data)

    project.edges = [tuple(edge) for edge in data.get("edges", [])]
    project.line_map = {line.id: line for line in project.prompt_lines}

    return project
