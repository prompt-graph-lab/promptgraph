"""Read-only batch-edit preview calculations; rendering and edits stay in app."""

import html

from core.parser import parse_prompt


def _highlight_literal_matches(text, query, style="background-color:#ffb3b3;color:#7a0000;"):
    query = (query or "")
    if not query:
        return html.escape(text)

    parts = []
    start = 0
    while True:
        match_index = text.find(query, start)
        if match_index < 0:
            parts.append(html.escape(text[start:]))
            break
        parts.append(html.escape(text[start:match_index]))
        match_text = html.escape(text[match_index:match_index + len(query)])
        parts.append(f"<span style='{style}'>{match_text}</span>")
        start = match_index + len(query)
    return "".join(parts)


def _batch_token_query(search_text, match_mode):
    query = (search_text or "").strip()
    if match_mode != "exact_token":
        return query

    from core.parser import extract_node_metadata

    tokens = parse_prompt(search_text or "")
    if len(tokens) != 1:
        return ""
    return extract_node_metadata(tokens[0])["base_word"].strip()


def _highlight_token_matches(text, search_text, match_mode):
    query = _batch_token_query(search_text, match_mode)
    if not query:
        return html.escape(text)

    from core.parser import extract_node_metadata, is_structural_mod_marker

    rendered_tokens = []
    for token in parse_prompt(text):
        if is_structural_mod_marker(token):
            rendered_tokens.append(html.escape(token))
            continue

        token_base = extract_node_metadata(token)["base_word"].strip()
        matched = token_base == query if match_mode == "exact_token" else query in token_base
        if not matched:
            rendered_tokens.append(html.escape(token))
            continue

        token_html = html.escape(token)
        if match_mode == "contains_token":
            token_html = _highlight_literal_matches(token, query)
        rendered_tokens.append(f"<span style='background-color:#fff3a3;'>{token_html}</span>")

    return ", ".join(rendered_tokens)


def _highlight_replace_result_tokens(text, replace_text):
    tokens = parse_prompt(replace_text or "")
    if len(tokens) != 1:
        return html.escape(text)

    from core.parser import extract_node_metadata, is_structural_mod_marker

    replacement_base = extract_node_metadata(tokens[0])["base_word"].strip()
    if not replacement_base:
        return html.escape(text)

    rendered_tokens = []
    for token in parse_prompt(text):
        if is_structural_mod_marker(token):
            rendered_tokens.append(html.escape(token))
            continue

        token_html = html.escape(token)
        token_base = extract_node_metadata(token)["base_word"].strip()
        if token_base == replacement_base:
            token_html = f"<span style='background-color:#cfe8ff;color:#003b73;'>{token_html}</span>"
        rendered_tokens.append(token_html)

    return ", ".join(rendered_tokens)


def _highlight_duplicate_tokens(duplicate_token_marks):
    rendered_tokens = []
    for mark in duplicate_token_marks:
        token_html = html.escape(mark["token"])
        if mark["status"] == "remove":
            rendered_tokens.append(
                f"<span style='background-color:#ffd6a5;color:#7a0000;"
                f"border:1px solid #ff9f1c;'>{token_html}</span>"
            )
        elif mark["status"] == "preserve":
            rendered_tokens.append(
                f"<span style='background-color:#d8f3dc;color:#064e3b;"
                f"border:1px solid #95d5b2;'>{token_html}</span>"
            )
        else:
            rendered_tokens.append(token_html)
    return ", ".join(rendered_tokens)


def _shorten_preview_text(text: str, center_text: str = "", max_chars: int = 220) -> str:
    text = text or ""
    center_text = (center_text or "").strip()
    if len(text) <= max_chars:
        return text

    center_index = text.lower().find(center_text.lower()) if center_text else -1
    if center_index < 0:
        return text[:max_chars - 1].rstrip() + "..."

    half = max_chars // 2
    start = max(center_index - half, 0)
    end = min(start + max_chars, len(text))
    start = max(end - max_chars, 0)
    prefix = "... " if start > 0 else ""
    suffix = " ..." if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def _batch_preview_focus_text(example, operation, search_text, edit_text):
    if operation in ("replace", "remove"):
        return search_text
    if operation == "add":
        return edit_text
    if operation == "remove_duplicates":
        for mark in example.get("duplicate_token_marks") or []:
            if mark.get("status") == "remove":
                return mark.get("token", "")
    return ""


def _removed_marker_preview(before: str, after: str, search_text: str, match_mode: str) -> str:
    if match_mode == "literal":
        query = (search_text or "").strip()
        if query and query in before:
            return before.replace(query, f"<removed: {query}>", 1)
        return before

    query = _batch_token_query(search_text, match_mode)
    if not query:
        return before

    from core.parser import extract_node_metadata, is_structural_mod_marker

    rendered_tokens = []
    marked = False
    for token in parse_prompt(before):
        if is_structural_mod_marker(token):
            rendered_tokens.append(token)
            continue
        token_base = extract_node_metadata(token)["base_word"].strip()
        matched = token_base == query if match_mode == "exact_token" else query in token_base
        if matched and not marked:
            rendered_tokens.append(f"<removed: {token}>")
            marked = True
        else:
            rendered_tokens.append(token)
    return ", ".join(rendered_tokens)
