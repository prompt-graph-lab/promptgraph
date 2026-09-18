"""Pure embedded ComfyUI source selection and diagnostic decisions.

Selection stops at the first executable source. Diagnostic inspection deliberately
parses both fields before checking either shape; callers own settings and I/O.
"""

from core.comfy_workflow_metadata import (
    _load_json_from_text,
    _is_executable_comfy_workflow,
)


def select_embedded_workflow_source(raw_metadata, *, metadata_sources=None, force_shared=False) -> dict:
    """Select executable embedded text without inspecting later sources on success."""
    if force_shared:
        return {"workflow_text": "", **classify_embedded_workflow_source({}, force_shared=True)}
    if not isinstance(raw_metadata, dict):
        raw_metadata = {}
    lowered_metadata = {str(key).lower(): value for key, value in raw_metadata.items()}
    for key in ("prompt", "workflow"):
        workflow_text = lowered_metadata.get(key)
        workflow_json = _load_json_from_text(workflow_text) if isinstance(workflow_text, str) else None
        if _is_executable_comfy_workflow(workflow_json):
            return {
                "workflow_text": workflow_text,
                "selected_source": f"line metadata `{key}`",
                "fallback_reason": "",
                "force_shared": False,
            }
    metadata_sources = metadata_sources if isinstance(metadata_sources, list) else []
    status = {
        "prompt_text": lowered_metadata.get("prompt"),
        "workflow_text": lowered_metadata.get("workflow"),
        "has_source_metadata": bool(metadata_sources),
    }
    return {"workflow_text": "", **classify_embedded_workflow_source(status)}


def inspect_embedded_workflow_sources(raw_metadata, *, metadata_sources=None) -> dict:
    """Collect diagnostics eagerly, before caller-owned force-shared settings lookup."""
    raw_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    lowered_metadata = {str(key).lower(): value for key, value in raw_metadata.items()}
    metadata_sources = metadata_sources if isinstance(metadata_sources, list) else []
    has_a1111_parameters = "a1111_parameters" in metadata_sources
    has_novelai_exif = "novelai_exif" in metadata_sources
    has_source_metadata = bool(metadata_sources)

    prompt_text = lowered_metadata.get("prompt")
    workflow_text = lowered_metadata.get("workflow")
    prompt_json = _load_json_from_text(prompt_text) if isinstance(prompt_text, str) else None
    workflow_json = _load_json_from_text(workflow_text) if isinstance(workflow_text, str) else None
    executable_prompt = _is_executable_comfy_workflow(prompt_json)
    executable_workflow = _is_executable_comfy_workflow(workflow_json)

    return {
        "metadata_sources": metadata_sources,
        "has_a1111_parameters": has_a1111_parameters,
        "has_novelai_exif": has_novelai_exif,
        "has_prompt_metadata": "prompt" in lowered_metadata,
        "has_workflow_metadata": "workflow" in lowered_metadata,
        "executable_prompt": executable_prompt,
        "executable_workflow": executable_workflow,
        "has_executable_workflow": executable_prompt or executable_workflow,
        "prompt_text": prompt_text,
        "workflow_text": workflow_text,
        "has_source_metadata": has_source_metadata,
    }


def classify_embedded_workflow_source(status, *, force_shared=False) -> dict:
    """Classify inspected sources without acquiring metadata or reading settings."""
    executable_prompt = status.get("executable_prompt", False)
    executable_workflow = status.get("executable_workflow", False)
    selected_source = ""
    fallback_reason = ""
    if force_shared:
        selected_source = "shared workflow JSON fallback (forced)"
        fallback_reason = "embedded workflow metadata is ignored by setting"
    elif executable_prompt:
        selected_source = "line metadata `prompt`"
    elif executable_workflow:
        selected_source = "line metadata `workflow`"
    else:
        selected_source = "shared workflow JSON fallback"
        if status.get("prompt_text") or status.get("workflow_text"):
            fallback_reason = "metadata workflow fields were found, but no executable ComfyUI API workflow was detected"
        elif status.get("has_source_metadata", False):
            fallback_reason = "source metadata was found, but it is not an executable ComfyUI workflow"
        else:
            fallback_reason = "no workflow metadata fields were found on this line"

    return {
        "force_shared": force_shared,
        "selected_source": selected_source,
        "fallback_reason": fallback_reason,
    }
