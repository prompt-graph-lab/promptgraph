"""Read-only token rules shared by Module editing and match previews.

Rule text deduplicates literal spellings case-insensitively. Inspector token
matching instead uses the parser's base word, so differently weighted forms
can match. Keep those existing semantics separate. Formatting and body parsing
preserve order and duplicates.

Callers own Project changes, draft/session state, history, and persistence.
"""

from core.parser import extract_node_metadata, parse_prompt


def _parse_module_rule_text(value: str) -> list[str]:
    tokens = []
    seen = set()
    for line in str(value or "").splitlines():
        for token in parse_prompt(line):
            token_text = str(token).strip()
            token_key = token_text.lower()
            if not token_text or token_key in seen:
                continue
            seen.add(token_key)
            tokens.append(token_text)
    return tokens


def _format_module_rule_text(tokens) -> str:
    return "\n".join(str(token).strip() for token in tokens or [] if str(token).strip())


def _module_body_from_tokens(tokens) -> str:
    return ", ".join(str(token).strip() for token in tokens or [] if str(token).strip())


def _module_tokens_from_body(body: str) -> list[str]:
    return [str(token).strip() for token in parse_prompt(body or "") if str(token).strip()]


def _dedupe_prompt_tokens(tokens) -> list[str]:
    deduped = []
    seen = set()
    for token in tokens or []:
        token_text = str(token).strip()
        token_key = _prompt_token_match_key(token_text)
        if not token_text or not token_key or token_key in seen:
            continue
        seen.add(token_key)
        deduped.append(token_text)
    return deduped


def _prompt_token_match_key(token: str) -> str:
    metadata = extract_node_metadata(token or "")
    return str(metadata.get("base_word") or token or "").strip().lower()


def _prompt_token_match_key_set(tokens) -> set[str]:
    keys = set()
    for token in tokens or []:
        token_key = _prompt_token_match_key(token)
        if token_key:
            keys.add(token_key)
    return keys
