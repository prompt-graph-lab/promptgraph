"""Read-only PromptCloud word normalization, membership and frequencies."""

from core.parser import parse_prompt
from core.prompt_line_selection import is_gallery_operation_prompt_line


def sanitize_promptcloud_word(word) -> str:
    return " ".join(str(word or "").split())


def sanitize_promptcloud_frequencies(freq: dict) -> tuple[dict, int, int]:
    sanitized_freq = {}
    sanitized_count = 0
    dropped_count = 0
    for raw_word, count in (freq or {}).items():
        clean_word = sanitize_promptcloud_word(raw_word)
        if not clean_word:
            dropped_count += 1
            continue
        if clean_word != str(raw_word or ""):
            sanitized_count += 1
        sanitized_freq[clean_word] = sanitized_freq.get(clean_word, 0) + count
    return sanitized_freq, sanitized_count, dropped_count


def line_ids_containing_word(project, word: str):
    from core.parser import extract_node_metadata, is_structural_mod_marker

    target = (word or "").strip()
    if not project or not target:
        return []
    target_promptcloud_key = sanitize_promptcloud_word(target)

    result = []
    for line in project.prompt_lines:
        if not is_gallery_operation_prompt_line(line):
            continue
        line_tokens = [
            str(token or "").strip()
            for token in (getattr(line, "tokens", []) or [])
        ]
        line_promptcloud_keys = [sanitize_promptcloud_word(token) for token in line_tokens]
        if target in line_tokens or target_promptcloud_key in line_promptcloud_keys:
            result.append(line.id)
            continue

        matched = False
        for token in parse_prompt(line.current_text):
            if is_structural_mod_marker(token):
                continue
            token_base = extract_node_metadata(token)["base_word"].strip()
            if (
                token == target
                or token_base == target
                or sanitize_promptcloud_word(token) == target_promptcloud_key
                or sanitize_promptcloud_word(token_base) == target_promptcloud_key
            ):
                matched = True
                break
        if matched:
            result.append(line.id)
    return result


def build_promptcloud_token_frequencies(project):
    from core.parser import extract_node_metadata, is_structural_mod_marker

    token_freq = {}
    token_group_freq = {}
    if not project:
        return token_freq, token_group_freq

    for line in getattr(project, "prompt_lines", []):
        if not is_gallery_operation_prompt_line(line):
            continue
        for token in getattr(line, "tokens", []) or []:
            token_key = str(token or "").strip()
            if not token_key or is_structural_mod_marker(token_key):
                continue
            meta = extract_node_metadata(token_key)
            group = meta.get("group", "default")
            token_freq[token_key] = token_freq.get(token_key, 0) + 1
            token_group_freq.setdefault(group, {})
            token_group_freq[group][token_key] = token_group_freq[group].get(token_key, 0) + 1

    return token_freq, token_group_freq
