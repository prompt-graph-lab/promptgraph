"""Read-only prompt diagnostics shared by editing and metadata previews.

Keep the existing comparison semantics: the source/current diff splits literal
commas, while syntax diagnostics and structural statistics use the prompt parser.
No Project mutation, persistence, or Streamlit session state belongs here.
"""

from collections import Counter

from core.parser import parse_prompt, extract_mod_info


def get_structural_stats(old_text, new_text):
    from core.parser import parse_prompt, extract_node_metadata
    from core.operations import get_display_tokens_from_text

    old_display_tokens = get_display_tokens_from_text(old_text)
    new_display_tokens = get_display_tokens_from_text(new_text)

    # We still want to count modules from the raw tokens
    raw_new_tokens = parse_prompt(new_text)

    token_delta = len(new_display_tokens) - len(old_display_tokens)
    mod_count = sum(1 for t in raw_new_tokens if t.startswith("<mod:"))
    has_weights = any(extract_node_metadata(t)["weight"] != 1.0 for t in new_display_tokens)

    change_ratio = 0
    if old_display_tokens:
        import difflib
        sm = difflib.SequenceMatcher(None, old_display_tokens, new_display_tokens)
        change_ratio = 1.0 - sm.ratio()

    return {
        "token_delta": token_delta,
        "mod_count": mod_count,
        "has_weights": has_weights,
        "change_ratio": change_ratio
    }


def extract_module_reference_names_from_text(text: str) -> list[str]:
    names = []
    seen = set()
    for token in parse_prompt(text or ""):
        info = extract_mod_info(token)
        name = (info.get("name") or "").strip()
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
    return names


def detect_novelai_syntax_fragments(prompt_text: str) -> list[str]:
    fragments = []
    seen = set()
    for token in parse_prompt(prompt_text or ""):
        fragment = token.strip()
        if "::" not in fragment:
            continue
        if fragment in seen:
            continue
        fragments.append(fragment)
        seen.add(fragment)
    return fragments


def _split_prompt_for_diff(text: str) -> list[str]:
    return [part.strip() for part in str(text or "").split(",") if part.strip()]


def _prompt_token_diff(source_prompt: str, current_prompt: str) -> dict:
    source_tokens = _split_prompt_for_diff(source_prompt)
    current_tokens = _split_prompt_for_diff(current_prompt)
    source_counts = Counter(source_tokens)
    current_counts = Counter(current_tokens)

    removed = []
    remaining_current = current_counts.copy()
    for token in source_tokens:
        if remaining_current[token] > 0:
            remaining_current[token] -= 1
        else:
            removed.append(token)

    added = []
    remaining_source = source_counts.copy()
    for token in current_tokens:
        if remaining_source[token] > 0:
            remaining_source[token] -= 1
        else:
            added.append(token)

    return {
        "source_tokens": source_tokens,
        "current_tokens": current_tokens,
        "removed": removed,
        "added": added,
        "shared_count": len(source_tokens) - len(removed),
    }
