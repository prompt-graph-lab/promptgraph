"""Read-only inspection of literal Module marker scopes in prompt lines."""

def preview_module_scope(project, module_name: str, example_limit: int = 10):
    from core.parser import extract_mod_info

    affected_line_count = 0
    token_count = 0
    inline_module_count = 0
    range_token_count = 0
    malformed_count = 0
    examples = []

    for line in project.prompt_lines:
        if getattr(line, "deleted", False):
            continue

        inline_contents = []
        range_tokens = []
        line_malformed = 0
        mod_stack = []

        for token in line.tokens:
            stripped_token = token.strip()
            if (
                stripped_token.startswith(f"<mod:{module_name}>")
                and "</mod:" in stripped_token
                and not stripped_token.endswith(f"</mod:{module_name}>")
            ):
                line_malformed += 1
                continue

            info = extract_mod_info(token)

            if info["type"] == "inline":
                if info["name"] == module_name:
                    inline_module_count += 1
                    inline_contents.append(info["content"])
                continue

            if info["type"] == "open":
                mod_stack.append(info["name"])
                continue

            if info["type"] == "close":
                if info["name"] in mod_stack:
                    idx = len(mod_stack) - 1 - mod_stack[::-1].index(info["name"])
                    mod_stack = mod_stack[:idx]
                elif info["name"] == module_name:
                    line_malformed += 1
                continue

            if module_name in mod_stack:
                range_token_count += 1
                range_tokens.append(token)

        if module_name in mod_stack:
            line_malformed += 1

        if inline_contents or range_tokens or line_malformed:
            affected_line_count += 1
            malformed_count += line_malformed
            if len(examples) < example_limit:
                examples.append({
                    "line_id": line.id,
                    "file": line.original_file_name,
                    "line_number": line.current_index + 1,
                    "inline_contents": inline_contents,
                    "range_tokens": range_tokens,
                    "raw_text": line.current_text,
                    "malformed_count": line_malformed,
                })

    token_count = inline_module_count + range_token_count

    return {
        "module_name": module_name,
        "affected_line_count": affected_line_count,
        "token_count": token_count,
        "inline_module_count": inline_module_count,
        "range_token_count": range_token_count,
        "malformed_count": malformed_count,
        "examples": examples,
    }
