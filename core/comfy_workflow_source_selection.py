"""Pure embedded ComfyUI source selection and diagnostic classification.

Execution selection short-circuits at the first executable source. Diagnostics
intentionally parse both fields before checking either shape; the app reads its
force-shared setting only after that inspection.
"""

from core.comfy_workflow_metadata import _is_executable_comfy_workflow, _load_json_from_text


def select_embedded_workflow_source(raw_metadata, *, metadata_sources=None, force_shared=False) -> dict:
    """Select prompt before workflow without evaluating an unused workflow.

    Return the original text, its embedded source label (empty on fallback),
    and the same classification/reason used by diagnostics. No asset is read.
    """
    raw_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    lowered = {str(key).lower(): value for key, value in raw_metadata.items()}
    selected_text = ""
    selected_label = ""
    if not force_shared:
        for key in ("prompt", "workflow"):
            text = lowered.get(key)
            workflow = _load_json_from_text(text) if isinstance(text, str) else None
            if _is_executable_comfy_workflow(workflow):
                selected_text = text
                selected_label = f"line metadata `{key}`"
                break
    classification = classify_embedded_workflow_source(
        lowered.get("prompt"), lowered.get("workflow"),
        selected_label == "line metadata `prompt`",
        selected_label == "line metadata `workflow`",
        metadata_sources if isinstance(metadata_sources, list) else [],
        force_shared=force_shared,
    )
    return {"workflow_text": selected_text, "source_label": selected_label, **classification}


def inspect_embedded_workflow_sources(lowered_metadata, metadata_sources) -> dict:
    """Inspect already-lowercased fields in the legacy diagnostic order.

    Lowercasing precedes the app's metadata_sources lookup; keeping that small
    preparation in the wrapper preserves the lookup order as well.
    """
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
        "has_source_metadata": has_source_metadata,
        "prompt_text": prompt_text,
        "workflow_text": workflow_text,
        "has_prompt_metadata": "prompt" in lowered_metadata,
        "has_workflow_metadata": "workflow" in lowered_metadata,
        "executable_prompt": executable_prompt,
        "executable_workflow": executable_workflow,
    }


def classify_embedded_workflow_source(
    prompt_text, workflow_text, executable_prompt, executable_workflow,
    has_source_metadata, *, force_shared=False,
) -> dict:
    """Classify pre-inspected sources after the caller has read its setting."""
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
    return {"selected_source": selected_source, "fallback_reason": fallback_reason}
