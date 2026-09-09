from core.comfy_workflow_injection import inject_prompt_to_workflow
from core.comfy_group_prompt import build_prompt_by_group
from core.comfy_save_path import _unique_save_path
from core.comfy_output_diagnostics import _build_output_diagnostics, _format_output_diagnostics
from core.comfy_polling_policy import COMFY_OUTPUT_POLL_ATTEMPTS, COMFY_OUTPUT_POLL_INTERVAL_SECONDS
from core.comfy_status_interpretation import (_comfy_status_summary, _comfy_status_is_failure)
from core.comfy_workflow_outputs import (_workflow_output_nodes, _workflow_save_image_nodes)
from core.comfy_history_interpretation import (_history_outputs, _history_prompt_record, _history_prompt_ids_sample)
from core.comfy_history_fetch import fetch_comfy_history as _fetch_comfy_history
from core.comfy_image_download import download_image_to_path
from core.comfy_image_outputs import (IMAGE_LIST_KEYS, _looks_like_comfy_image_record, _collect_image_outputs, _extract_history_images)
from core.comfy_message_interpretation import interpret_progress_message
from core.comfy_websocket_setup import connect_progress_socket
from core.comfy_prompt_submission import submit_prompt_request
from core.comfy_prompt_request import prepare_prompt_request

import urllib.parse
import urllib.error
import time
import os
import uuid
import websocket
import random
import logging

logger = logging.getLogger(__name__)


class ComfyOutputError(Exception):
    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


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


def generate_image_with_progress(workflow_json: dict, server_address: str, output_dir: str, file_prefix: str, timeout: int = 300):
    """
    ComfyUIにプロンプトを投げ、WebSocketで進捗を監視するジェネレータ関数。
    進捗中は {"type": "...", "text": "...", "value": float} の辞書をyieldする。
    完了時に保存された画像のパスを返す（ジェネレータの戻り値、または最終yieldの特別な形式で）。
    """
    server_address, client_id, req = prepare_prompt_request(workflow_json, server_address)

    yield {"type": "status", "text": "Connecting to ComfyUI...", "value": 0.0}
    
    prompt_id = submit_prompt_request(req, server_address)

    yield {"type": "status", "text": "Prompt queued. Waiting for execution...", "value": 0.0}

    ws = connect_progress_socket(server_address, client_id)

    image_infos = []
    start_time = time.time()
    
    while True:
        if time.time() - start_time > timeout:
            ws.close()
            raise Exception(f"ComfyUI execution timeout ({timeout}s exceeded)")
            
        try:
            out = ws.recv()
            completed, event = interpret_progress_message(out, prompt_id)
            if completed:
                break
            if event is not None:
                yield event
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
            download_image_to_path(image_url, save_path)
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
