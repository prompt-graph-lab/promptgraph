"""Construct and format existing Comfy output diagnostics."""
from core.comfy_status_interpretation import _comfy_status_summary
from core.comfy_history_interpretation import _history_prompt_ids_sample
from core.comfy_workflow_outputs import _workflow_save_image_nodes, _workflow_output_nodes
from core.comfy_polling_policy import COMFY_OUTPUT_POLL_ATTEMPTS

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
