import json
import urllib.request
import urllib.parse
import urllib.error
import time
import os
import uuid
import websocket
import random
import logging

logger = logging.getLogger(__name__)

IMAGE_LIST_KEYS = {"images", "gifs"}
COMFY_OUTPUT_POLL_ATTEMPTS = 8
COMFY_OUTPUT_POLL_INTERVAL_SECONDS = 0.75


class ComfyOutputError(Exception):
    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}

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

def _history_outputs(history, prompt_id):
    if not isinstance(history, dict):
        return {}
    prompt_history = history.get(prompt_id)
    if not isinstance(prompt_history, dict) and len(history) == 1:
        prompt_history = next(iter(history.values()))
    if not isinstance(prompt_history, dict):
        return {}
    outputs = prompt_history.get("outputs", {})
    return outputs if isinstance(outputs, dict) else {}

def _history_prompt_record(history, prompt_id):
    if not isinstance(history, dict):
        return {}
    prompt_history = history.get(prompt_id)
    if not isinstance(prompt_history, dict) and len(history) == 1:
        prompt_history = next(iter(history.values()))
    return prompt_history if isinstance(prompt_history, dict) else {}

def _history_prompt_ids_sample(history, limit=8):
    if not isinstance(history, dict):
        return []
    return [str(prompt_id) for prompt_id in list(history.keys())[:limit]]

def _workflow_output_nodes(workflow_json):
    node_ids = []
    if not isinstance(workflow_json, dict):
        return node_ids
    target_nodes = workflow_json.get("nodes", workflow_json)
    if not isinstance(target_nodes, dict):
        return node_ids
    for node_id, node_data in target_nodes.items():
        if not isinstance(node_data, dict):
            continue
        class_type = str(node_data.get("class_type") or node_data.get("type") or "")
        if class_type in {"SaveImage", "PreviewImage"} or class_type.endswith(".SaveImage") or class_type.endswith(".PreviewImage"):
            node_ids.append(str(node_id))
    return node_ids

def _workflow_save_image_nodes(workflow_json):
    node_ids = []
    if not isinstance(workflow_json, dict):
        return node_ids
    target_nodes = workflow_json.get("nodes", workflow_json)
    if not isinstance(target_nodes, dict):
        return node_ids
    for node_id, node_data in target_nodes.items():
        if not isinstance(node_data, dict):
            continue
        class_type = str(node_data.get("class_type") or node_data.get("type") or "")
        if class_type == "SaveImage" or class_type.endswith(".SaveImage"):
            node_ids.append(str(node_id))
    return node_ids

def _comfy_status_summary(prompt_history):
    status = prompt_history.get("status", {}) if isinstance(prompt_history, dict) else {}
    if isinstance(status, dict):
        status_value = status.get("status_str")
        if status_value is None and "completed" in status:
            status_value = "completed" if status.get("completed") else "not_completed"
        messages = status.get("messages", [])
        return str(status_value or "unknown"), messages if isinstance(messages, list) else []
    if status:
        return str(status), []
    return "unknown", []

def _comfy_status_is_failure(prompt_history):
    status_value, messages = _comfy_status_summary(prompt_history)
    lowered = status_value.lower()
    if lowered in {"error", "failed", "failure"}:
        return True
    for message in messages:
        if not isinstance(message, (list, tuple)) or not message:
            continue
        if str(message[0]).lower() in {"execution_error", "error", "failed"}:
            return True
    return False

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

def _fetch_comfy_history(server_address, prompt_id):
    with urllib.request.urlopen(f"http://{server_address}/history/{prompt_id}") as response:
        return json.loads(response.read())

def _build_output_diagnostics(
    *,
    prompt_id,
    history,
    prompt_history,
    outputs,
    workflow_json,
    save_image_node_ids,
    extraction,
    attempt_count,
    attempt_logs,
    last_history_fetch_error,
):
    status, status_messages = _comfy_status_summary(prompt_history)
    workflow_nodes = workflow_json.get("nodes", workflow_json) if isinstance(workflow_json, dict) else {}
    return {
        "queued_prompt_id": prompt_id,
        "history_prompt_ids_sample": _history_prompt_ids_sample(history),
        "target_history_found": bool(prompt_history),
        "target_status": status,
        "target_status_messages": status_messages[:5],
        "target_outputs_keys": list(outputs.keys()) if isinstance(outputs, dict) else [],
        "save_image_node_ids": save_image_node_ids,
        "save_image_outputs_found": bool(extraction.get("save_nodes_with_outputs")),
        "save_image_nodes_with_outputs": extraction.get("save_nodes_with_outputs", []),
        "save_image_node_output_keys": extraction.get("save_node_output_keys", {}),
        "workflow_node_count": len(workflow_nodes) if isinstance(workflow_nodes, dict) else 0,
        "workflow_save_image_node_ids": _workflow_save_image_nodes(workflow_json),
        "workflow_output_node_ids": _workflow_output_nodes(workflow_json),
        "attempt_count": attempt_count,
        "last_history_fetch_error": last_history_fetch_error or "none",
        "attempts": attempt_logs[-COMFY_OUTPUT_POLL_ATTEMPTS:],
    }

def _format_output_diagnostics(diagnostics):
    return (
        "No image was output by the workflow after polling Comfy history.\n"
        f"prompt_id: {diagnostics.get('queued_prompt_id')}\n"
        f"attempts: {diagnostics.get('attempt_count')}\n"
        f"history found: {'yes' if diagnostics.get('target_history_found') else 'no'}\n"
        f"status: {diagnostics.get('target_status')}\n"
        f"outputs keys: {diagnostics.get('target_outputs_keys')}\n"
        f"SaveImage nodes in workflow: {diagnostics.get('workflow_save_image_node_ids')}\n"
        f"SaveImage nodes with image outputs: {diagnostics.get('save_image_nodes_with_outputs')}\n"
        f"SaveImage output keys: {diagnostics.get('save_image_node_output_keys')}\n"
        f"last history fetch error: {diagnostics.get('last_history_fetch_error')}"
    )

def _poll_comfy_output_history(
    server_address,
    prompt_id,
    workflow_json,
    *,
    max_attempts=COMFY_OUTPUT_POLL_ATTEMPTS,
    interval_seconds=COMFY_OUTPUT_POLL_INTERVAL_SECONDS,
):
    save_image_node_ids = _workflow_save_image_nodes(workflow_json)
    history = {}
    prompt_history = {}
    outputs = {}
    extraction = {
        "images": [],
        "image_like_fields": [],
        "save_nodes_with_outputs": [],
        "save_node_output_keys": {},
        "output_node_ids": [],
        "output_keys_by_node": {},
    }
    attempt_logs = []
    last_history_fetch_error = ""

    for attempt in range(1, max_attempts + 1):
        try:
            history = _fetch_comfy_history(server_address, prompt_id)
            last_history_fetch_error = ""
        except Exception as e:
            last_history_fetch_error = str(e)
            history = {}
            logger.debug("Comfy history fetch failed for prompt %s on attempt %s: %s", prompt_id, attempt, e)

        prompt_history = _history_prompt_record(history, prompt_id)
        outputs = _history_outputs(history, prompt_id)
        extraction = _extract_history_images(outputs, save_image_node_ids)
        attempt_log = {
            "attempt": attempt,
            "history_found": bool(prompt_history),
            "outputs_keys": extraction.get("output_node_ids", []),
            "save_image_nodes_with_outputs": extraction.get("save_nodes_with_outputs", []),
        }
        attempt_logs.append(attempt_log)
        logger.debug("Comfy output polling attempt for prompt %s: %s", prompt_id, attempt_log)

        if extraction.get("images"):
            break

        if prompt_history and _comfy_status_is_failure(prompt_history):
            break

        if attempt < max_attempts:
            time.sleep(interval_seconds)

    return {
        "history": history,
        "prompt_history": prompt_history,
        "outputs": outputs,
        "extraction": extraction,
        "image_infos": extraction.get("images", []),
        "attempt_logs": attempt_logs,
        "last_history_fetch_error": last_history_fetch_error,
        "save_image_node_ids": save_image_node_ids,
    }

def _unique_save_path(output_dir, file_name):
    base_name = os.path.basename(file_name or "comfy_output.png")
    candidate_path = os.path.join(output_dir, base_name)
    stem, ext = os.path.splitext(candidate_path)
    suffix = 1
    while os.path.exists(candidate_path):
        candidate_path = f"{stem}_{suffix}{ext}"
        suffix += 1
    return candidate_path

def build_prompt_by_group(project, prompt_line, disabled_modules=None):
    if disabled_modules is None:
        disabled_modules = set()
        
    grouped = {}
    mod_stack = []
    
    for idx, node_id in enumerate(prompt_line.node_path):
        token = prompt_line.tokens[idx] if idx < len(prompt_line.tokens) else ""
        
        if token.startswith("<mod:"):
            mod_stack.append(token[5:-1])
            continue
        elif token.startswith("</mod:"):
            mod_id = token[6:-1]
            if mod_id in mod_stack:
                i = len(mod_stack) - 1 - mod_stack[::-1].index(mod_id)
                mod_stack = mod_stack[:i]
            else:
                logger.warning(f"Malformed module marker: closing tag </mod:{mod_id}> found without matching opening tag in line {prompt_line.id}.")
            continue
            
        if any(m in disabled_modules for m in mod_stack):
            continue
            
        if node_id in project.nodes:
            node = project.nodes[node_id]
            group = getattr(node, "group", "default")
            val = getattr(node, "original", node.word)
            if group not in grouped:
                grouped[group] = []
            grouped[group].append(val)
            
    if mod_stack:
        logger.warning(f"Malformed module marker: unclosed tags {mod_stack} at end of line {prompt_line.id}.")
        
    return grouped

def inject_prompt_to_workflow(workflow_json, grouped_prompt, mapping, fallback_prompt=None):
    group_map = mapping.get("group_map", {})
    group_order = mapping.get("group_order")
    merge_mode = mapping.get("merge_mode", "merge")
    
    if group_order:
        ordered_groups = [(g, grouped_prompt[g]) for g in group_order if g in grouped_prompt]
        ordered_groups += [(g, grouped_prompt[g]) for g in grouped_prompt if g not in group_order]
    else:
        ordered_groups = list(grouped_prompt.items())
    
    dest_texts = {}
    for group, tokens in ordered_groups:
        if group not in group_map:
            logger.info(f"Unmapped group '{group}' -> defaulting to positive")
            dest_key = "positive"
        else:
            dest_key = group_map.get(group, "positive")
            
        if dest_key not in mapping:
            continue
            
        if dest_key not in dest_texts:
            dest_texts[dest_key] = []
        dest_texts[dest_key].extend(tokens)
        
    # Ensure all mapped targets exist even if empty
    for k in mapping.keys():
        if k not in ["group_map", "group_order", "merge_mode"] and k not in dest_texts:
            dest_texts[k] = []
            
    if fallback_prompt and "positive" in dest_texts and not dest_texts["positive"]:
        dest_texts["positive"] = [fallback_prompt]
        
    for dest_key, tokens in dest_texts.items():
            
        dest_config = mapping.get(dest_key)
        if not dest_config:
            continue
        
        node_id = str(dest_config.get("node_id"))
        input_key = dest_config.get("input_key")
        
        try:
            # Handle both raw API format and {"nodes": ...} format
            target_nodes = workflow_json.get("nodes", workflow_json) if isinstance(workflow_json, dict) else workflow_json
            
            if node_id not in target_nodes:
                logger.warning(f"Node {node_id} not found in workflow")
                continue
                
            inputs = target_nodes[node_id].get("inputs", {})
            if input_key not in inputs:
                logger.warning(f"input_key '{input_key}' not found in node {node_id}")
                continue
            
            tokens = list(dict.fromkeys(tokens))
            
            existing = target_nodes[node_id]["inputs"].get(input_key, "")
            if isinstance(existing, str):
                existing = existing.strip().rstrip(",")
            
            if merge_mode == "overwrite":
                merged = ", ".join(tokens)
            else:
                existing_tokens = [t.strip() for t in existing.split(",") if t.strip()] if isinstance(existing, str) else []
                for t in tokens:
                    if t not in existing_tokens:
                        existing_tokens.append(t)
                merged = ", ".join(existing_tokens)
            
            target_nodes[node_id]["inputs"][input_key] = merged
        except Exception as e:
            logger.warning(f"Failed to inject prompt to node {node_id}: {e}")
            pass
            
    return workflow_json

def generate_image_with_progress(workflow_json: dict, server_address: str, output_dir: str, file_prefix: str, timeout: int = 300):
    """
    ComfyUIにプロンプトを投げ、WebSocketで進捗を監視するジェネレータ関数。
    進捗中は {"type": "...", "text": "...", "value": float} の辞書をyieldする。
    完了時に保存された画像のパスを返す（ジェネレータの戻り値、または最終yieldの特別な形式で）。
    """
    server_address = server_address.replace("http://", "").replace("https://", "").strip("/")
    client_id = str(uuid.uuid4())
    
    # シード値をランダム化してComfyUIのキャッシュを回避する
    for node_id, node_data in workflow_json.items():
        if isinstance(node_data, dict) and "inputs" in node_data:
            inputs = node_data["inputs"]
            for seed_key in ["seed", "noise_seed"]:
                if seed_key in inputs and isinstance(inputs[seed_key], (int, float)):
                    # 一般的な最大値 (2^64 - 1) までの範囲で乱数を生成
                    inputs[seed_key] = random.randint(0, 0xffffffffffffffff)
                    
    p = {"prompt": workflow_json, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data)
    
    yield {"type": "status", "text": "Connecting to ComfyUI...", "value": 0.0}
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read())
            prompt_id = result.get("prompt_id")
    except urllib.error.URLError as e:
        raise Exception(f"Failed to connect to ComfyUI at {server_address}. Is it running? Error: {e}")

    if not prompt_id:
        raise Exception("Failed to get prompt_id from ComfyUI.")

    yield {"type": "status", "text": "Prompt queued. Waiting for execution...", "value": 0.0}

    ws = websocket.WebSocket()
    try:
        ws.connect(f"ws://{server_address}/ws?clientId={client_id}")
        ws.settimeout(1.0)
    except Exception as e:
        raise Exception(f"Failed to connect to ComfyUI WebSocket: {e}")
        
    image_infos = []
    start_time = time.time()
    
    while True:
        if time.time() - start_time > timeout:
            ws.close()
            raise Exception(f"ComfyUI execution timeout ({timeout}s exceeded)")
            
        try:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                msg_type = message.get("type")
                data = message.get("data", {})
                
                if msg_type == "execution_start":
                    yield {"type": "status", "text": "Execution started", "value": 0.05}
                elif msg_type == "executing":
                    node = data.get("node")
                    if node is None and data.get("prompt_id") == prompt_id:
                        # 完了
                        break
                elif msg_type == "progress":
                    value = data.get("value", 0)
                    max_val = data.get("max", 1)
                    if max_val > 0:
                        progress = value / max_val
                        # 10% ~ 90% の範囲にスケーリング
                        scaled_progress = 0.1 + (progress * 0.8)
                        yield {"type": "progress", "text": f"Sampling... {value}/{max_val}", "value": scaled_progress}
                elif msg_type == "execution_success" and data.get("prompt_id") == prompt_id:
                    break
                elif msg_type == "execution_error":
                    error_msg = data.get("exception_message", "Unknown error")
                    node_id = data.get("node_id", "")
                    node_type = data.get("node_type", "")
                    raise Exception(f"ComfyUI Execution Error in node {node_id} ({node_type}): {error_msg}")
        except websocket.WebSocketTimeoutException:
            continue
        except Exception as e:
            # タイムアウト等の場合はループを抜けるかエラーにする
            raise Exception(f"WebSocket error or execution failed: {e}")
            
    ws.close()
    
    yield {"type": "status", "text": "Execution done. Fetching image...", "value": 0.95}
    
    poll_result = _poll_comfy_output_history(server_address, prompt_id, workflow_json)
    history = poll_result["history"]
    prompt_history = poll_result["prompt_history"]
    outputs = poll_result["outputs"]
    extraction = poll_result["extraction"]
    image_infos = poll_result["image_infos"]
    attempt_logs = poll_result["attempt_logs"]
    last_history_fetch_error = poll_result["last_history_fetch_error"]
    save_image_node_ids = poll_result["save_image_node_ids"]

    output_node_ids = extraction.get("output_node_ids", [])
    output_keys_by_node = extraction.get("output_keys_by_node", {})
    image_like_fields = extraction.get("image_like_fields", [])

    if not image_infos:
        diagnostics = _build_output_diagnostics(
            prompt_id=prompt_id,
            history=history,
            prompt_history=prompt_history,
            outputs=outputs,
            workflow_json=workflow_json,
            save_image_node_ids=save_image_node_ids,
            extraction=extraction,
            attempt_count=len(attempt_logs),
            attempt_logs=attempt_logs,
            last_history_fetch_error=last_history_fetch_error,
        )
        logger.warning("Comfy output missing after polling: %s", diagnostics)
        raise ComfyOutputError(_format_output_diagnostics(diagnostics), diagnostics)

    os.makedirs(output_dir, exist_ok=True)
    saved_paths = []
    download_errors = []
    attempted_view_urls = []

    for image_info in image_infos:
        filename = image_info["filename"]
        subfolder = image_info.get("subfolder", "")
        folder_type = image_info.get("type", "output")
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = urllib.parse.urlencode(data)
        image_url = f"http://{server_address}/view?{url_values}"
        attempted_view_urls.append(image_url)
        save_path = _unique_save_path(output_dir, f"{file_prefix}_{filename}")

        try:
            with urllib.request.urlopen(image_url) as response:
                image_data = response.read()
                with open(save_path, "wb") as f:
                    f.write(image_data)
            saved_paths.append(save_path)
        except Exception as e:
            error_text = f"Failed to download image {filename}: {e}"
            download_errors.append(error_text)
            logger.warning(error_text)
            yield {"type": "warning", "text": error_text, "value": 0.95}

    if not saved_paths:
        raise Exception(
            "No ComfyUI image outputs could be downloaded. "
            f"Prompt id: {prompt_id}. "
            f"Output node ids seen: {output_node_ids}. "
            f"Output keys by node: {output_keys_by_node}. "
            f"Image-like fields seen: {image_like_fields}. "
            f"Attempted /view URLs: {attempted_view_urls}. "
            f"Attempted {len(image_infos)} image record(s). "
            f"Download errors: {download_errors}"
        )

    yield {
        "type": "done",
        "text": "Completed!",
        "value": 1.0,
        "path": saved_paths[0],
        "paths": saved_paths,
        "prompt_id": prompt_id,
        "output_node_ids": output_node_ids,
        "output_keys_by_node": output_keys_by_node,
        "image_like_fields": image_like_fields,
        "comfy_output_diagnostics": {
            "attempt_count": len(attempt_logs),
            "attempts": attempt_logs,
            "save_image_node_ids": save_image_node_ids,
            "save_image_nodes_with_outputs": extraction.get("save_nodes_with_outputs", []),
        },
        "images": image_infos,
        "attempted_view_urls": attempted_view_urls,
        "saved_paths": saved_paths,
        "download_errors": download_errors,
    }
