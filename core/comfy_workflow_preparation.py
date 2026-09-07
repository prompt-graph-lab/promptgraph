"""Prepare a single ComfyUI workflow for a prompt line.

Workflow source selection, active-token expansion, settings/session state, and
submission remain owned by the app callers. The group-mapping path intentionally
delegates its existing grouped Module expansion here. This module only parses
the selected workflow text and applies the existing prompt-binding semantics.
"""

import json

from core.comfy_prompt_binding import _replace_clip_text_prompts
from core.comfyui import inject_prompt_to_workflow


def _build_line_workflow_from_text(workflow_text, line, settings, project=None, disabled_modules=None, image_metadata=None):
    line_prompt = getattr(line, "current_text", "") or ""
    mapping = settings.get("comfy_mapping")
    if mapping and "group_map" in mapping:
        workflow_json = json.loads(workflow_text)
        if project is not None:
            from core.comfyui import build_prompt_by_group
            grouped = build_prompt_by_group(project, line, disabled_modules or set())
        else:
            grouped = {"default": [line_prompt]}
        return inject_prompt_to_workflow(
            workflow_json,
            grouped,
            mapping,
            fallback_prompt=line_prompt,
        ), ""

    warning = ""
    if "__PROMPT__" in workflow_text:
        workflow_text = workflow_text.replace("__PROMPT__", json.dumps(line_prompt)[1:-1])
        return json.loads(workflow_text), warning

    workflow_json = json.loads(workflow_text)
    if _replace_clip_text_prompts(workflow_json, line, image_metadata=image_metadata) == 0:
        warning = "The workflow JSON does not contain '__PROMPT__'. The prompt may not be injected."
    return workflow_json, warning
