"""Prepare the detached prompt line used by single-line ComfyUI generation.

The caller owns workflow selection, settings/session lookup, binding and execution.
Token expansion stays in core.operations; this boundary owns expansion-before-copy
and replacement of only the copied line's current text, including for preview.
"""

import copy

from core.operations import get_active_tokens


def prepare_generation_injection_line(line, disabled_modules, *, fallback_prompt, module_library):
    """Expand the source line before copying it; leave its stored fields intact."""
    active_tokens = get_active_tokens(
        line,
        disabled_modules,
        fallback_prompt=fallback_prompt,
        module_library=module_library,
    )
    injection_line = copy.deepcopy(line)
    injection_line.current_text = ", ".join(active_tokens)
    return injection_line
