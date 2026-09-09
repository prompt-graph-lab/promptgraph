"""Build grouped prompts while retaining legacy warning routing."""
import logging
logger = logging.getLogger("core.comfyui")

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
