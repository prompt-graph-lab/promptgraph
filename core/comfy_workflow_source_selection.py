"""Pure embedded workflow selection; acquisition and fallback I/O stay in app."""

from core.comfy_workflow_metadata import _load_json_from_text, _is_executable_comfy_workflow


def normalize_workflow_metadata(raw_metadata):
    """Lowercase keys in insertion order; the last colliding value wins."""
    raw_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    return {str(key).lower(): value for key, value in raw_metadata.items()}


def embedded_workflow_text(raw_metadata):
    """Select lazily for execution, stopping at the first executable source."""
    if not isinstance(raw_metadata, dict):
        return "", ""
    lowered_metadata = normalize_workflow_metadata(raw_metadata)
    for key in ("prompt", "workflow"):
        workflow_text = lowered_metadata.get(key)
        workflow_json = _load_json_from_text(workflow_text) if isinstance(workflow_text, str) else None
        if _is_executable_comfy_workflow(workflow_json):
            return workflow_text, f"line metadata `{key}`"
    return "", ""


def inspect_embedded_workflow_sources(lowered_metadata, *, metadata_sources=None):
    """Diagnose both sources eagerly, retaining parsing and shape-check order."""
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

    return (lowered_metadata, metadata_sources, has_a1111_parameters, has_novelai_exif,
            has_source_metadata, prompt_text, workflow_text, executable_prompt, executable_workflow)


def classify_embedded_workflow_source(inspection, *, force_shared=False) -> dict:
    """Classify an inspection after the caller has obtained its shared setting."""
    (lowered_metadata, metadata_sources, has_a1111_parameters, has_novelai_exif,
     has_source_metadata, prompt_text, workflow_text, executable_prompt, executable_workflow) = inspection
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
        if prompt_text or workflow_text:
            fallback_reason = "metadata workflow fields were found, but no executable ComfyUI API workflow was detected"
        elif has_source_metadata:
            fallback_reason = "source metadata was found, but it is not an executable ComfyUI workflow"
        else:
            fallback_reason = "no workflow metadata fields were found on this line"

    return {
        "metadata_sources": metadata_sources,
        "has_a1111_parameters": has_a1111_parameters,
        "has_novelai_exif": has_novelai_exif,
        "has_prompt_metadata": "prompt" in lowered_metadata,
        "has_workflow_metadata": "workflow" in lowered_metadata,
        "executable_prompt": executable_prompt,
        "executable_workflow": executable_workflow,
        "has_executable_workflow": executable_prompt or executable_workflow,
        "force_shared": force_shared,
        "selected_source": selected_source,
        "fallback_reason": fallback_reason,
    }


def select_embedded_workflow_source(raw_metadata, *, metadata_sources=None, force_shared=False) -> dict:
    """Return deterministic diagnostic flags and the selected source classification."""
    lowered_metadata = normalize_workflow_metadata(raw_metadata)
    inspection = inspect_embedded_workflow_sources(lowered_metadata, metadata_sources=metadata_sources)
    return classify_embedded_workflow_source(inspection, force_shared=force_shared)
