"""Deterministic image-record recognition, collection and extraction.

Preserves SaveImage-first precedence and legacy record compatibility.
History selection, polling, diagnostics and downloading remain in comfyui.
"""

import os

IMAGE_LIST_KEYS = {"images", "gifs"}


def _looks_like_comfy_image_record(value):
    if not isinstance(value, dict):
        return False
    filename = value.get("filename")
    if not isinstance(filename, str) or not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

def _collect_image_outputs(value, path=""):
    images = []
    image_like_paths = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = f"{path}.{key}" if path else str(key)
            if key in IMAGE_LIST_KEYS and isinstance(nested, list):
                for index, image_value in enumerate(nested):
                    item_path = f"{nested_path}[{index}]"
                    if not _looks_like_comfy_image_record(image_value):
                        continue
                    images.append({
                        "filename": image_value["filename"],
                        "subfolder": image_value.get("subfolder", ""),
                        "type": image_value.get("type", "output"),
                        "_debug_path": item_path,
                    })
                    image_like_paths.append(item_path)
            elif isinstance(nested, (dict, list)):
                nested_images, nested_paths = _collect_image_outputs(nested, nested_path)
                images.extend(nested_images)
                image_like_paths.extend(nested_paths)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested_images, nested_paths = _collect_image_outputs(item, f"{path}[{index}]")
            images.extend(nested_images)
            image_like_paths.extend(nested_paths)
    return images, image_like_paths

def _extract_history_images(outputs, save_image_node_ids):
    image_infos = []
    image_like_fields = []
    save_nodes_with_outputs = []
    save_node_output_keys = {}
    save_image_node_ids = [str(node_id) for node_id in save_image_node_ids or []]

    if not isinstance(outputs, dict):
        return {
            "images": [],
            "image_like_fields": [],
            "save_nodes_with_outputs": [],
            "save_node_output_keys": {},
            "output_node_ids": [],
            "output_keys_by_node": {},
        }

    output_node_ids = [str(node_id) for node_id in outputs.keys()]
    output_keys_by_node = {
        str(node_id): list(node_output.keys())
        for node_id, node_output in outputs.items()
        if isinstance(node_output, dict)
    }

    for node_id in save_image_node_ids:
        node_output = outputs.get(node_id)
        if not isinstance(node_output, dict):
            continue
        save_node_output_keys[node_id] = list(node_output.keys())
        node_images, node_image_paths = _collect_image_outputs(node_output, f"outputs.{node_id}")
        image_like_fields.extend(node_image_paths)
        if node_images:
            save_nodes_with_outputs.append(node_id)
        for image_info in node_images:
            image_info["_node_id"] = node_id
            image_infos.append(image_info)

    if not image_infos:
        for node_id, node_output in outputs.items():
            if not isinstance(node_output, dict):
                continue
            node_images, node_image_paths = _collect_image_outputs(node_output, f"outputs.{node_id}")
            image_like_fields.extend(node_image_paths)
            for image_info in node_images:
                image_info["_node_id"] = node_id
                image_infos.append(image_info)

    seen_images = set()
    unique_image_infos = []
    for image_info in image_infos:
        key = (
            image_info.get("filename"),
            image_info.get("subfolder", ""),
            image_info.get("type", "output"),
        )
        if not key[0] or key in seen_images:
            continue
        unique_image_infos.append(image_info)
        seen_images.add(key)

    return {
        "images": unique_image_infos,
        "image_like_fields": image_like_fields,
        "save_nodes_with_outputs": save_nodes_with_outputs,
        "save_node_output_keys": save_node_output_keys,
        "output_node_ids": output_node_ids,
        "output_keys_by_node": output_keys_by_node,
    }
