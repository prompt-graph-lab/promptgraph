"""Lossless, operation-only projection for a deliberately small tag grammar.

The persisted parser is intentionally not used or changed here. A boundary is
accepted only in a comma-bearing prompt, between short lowercase ASCII word
fragments (or a standalone Module reference), outside all groups and Module
blocks. Capitals, sentence pronouns/finite verbs, abbreviations, digits and
internal punctuation make a fragment ineligible. This is lexical, not prose
understanding; unsupported text retains the legacy interpretation.
"""
import difflib
import re

_WORDS = re.compile(r"[a-z]+(?:[ -][a-z]+){0,4}\Z")
_REFERENCE = re.compile(r"<mod:[^<>]+>\Z")
_AMBIGUOUS = {'i', 'we', 'you', 'he', 'she', 'it', 'they', 'this', 'that', 'these', 'those', 'is', 'are', 'was', 'were', 'am', 'has', 'have', 'had', 'will', 'would', 'can', 'could', 'should', 'must', 'does', 'did', 'said', 'says', 'dr', 'mr', 'mrs', 'ms', 'prof', 'sr', 'jr', 'etc', 'vs', 'st', 'no', 'fig', 'inc', 'ltd', 'e', 'g', 'a', 'm', 'p'}


def _tag(fragment):
    return bool(_REFERENCE.fullmatch(fragment) or (
        _WORDS.fullmatch(fragment) and not set(fragment.replace('-', ' ').split()) & _AMBIGUOUS))


def project_period_spans(text, legacy_tokens):
    """Return exact token spans, plus whether the period grammar was activated."""
    protected = []
    stack = []
    for marker in re.finditer(r"</?mod:([^<>]+)>", text):
        if marker.group().startswith("</"):
            if stack and stack[-1][0] == marker.group(1):
                _, opening = stack.pop()
                protected.append((opening, marker.end()))
            else:
                # Orphan/mismatched closing syntax is structurally ambiguous.
                return [], False
        else:
            stack.append((marker.group(1), marker.start()))
    protected.extend((opening, len(text)) for _, opening in stack)
    # Track all bracket kinds across legacy comma tokens; a comma inside []
    # must never make its later period look top level.
    depth_at = []
    groups = []
    for char in text:
        depth_at.append(len(groups))
        if char in "([{":
            groups.append(char)
        elif char in ")]}":
            if groups and groups[-1] == {")": "(", "]": "[", "}": "{"}[char]:
                groups.pop()
    # The persistence-oriented Module parser historically protects only ().
    # For an activated projection, coalesce its artificial []/{} comma pieces
    # into exact original group spans before exposing selectable fragments.
    grouped = []
    cursor = 0
    previous_end = 0
    for token in legacy_tokens:
        start = text.find(token, cursor)
        if start < 0:
            return [], False
        end = start + len(token)
        gap_comma = text.find(",", previous_end, start)
        if grouped and gap_comma >= 0 and depth_at[gap_comma] > 0:
            group_start, _ = grouped[-1]
            grouped[-1] = (group_start, end)
        else:
            grouped.append((start, end))
        cursor = end
        previous_end = end
    legacy_tokens = [text[start:end] for start, end in grouped]
    spans = []
    cursor = 0
    activated = False
    for token in legacy_tokens:
        start = text.find(token, cursor)
        if start < 0:
            return [], False
        end = start + len(token)
        cursor = end
        # Module bodies/ranges and any nested syntax are opaque. A lone ref
        # following the boundary is allowed, but never an inline/range block.
        candidates = list(re.finditer(r'\.\s+', token)) if ',' in text else []
        pieces = re.split(r'\.\s+', token)
        safe = (bool(candidates) and len(pieces) > 1 and all(_tag(piece) for piece in pieces)
                and all(depth_at[start + boundary.start()] == 0
                        and not any(a <= start + boundary.start() < b for a, b in protected)
                        for boundary in candidates))
        if safe:
            activated = True
            offset = 0
            for boundary in candidates:
                spans.append((start + offset, start + boundary.start()))
                offset = boundary.end()
            spans.append((start + offset, end))
        else:
            spans.append((start, end))
    return spans, activated


def projected_tokens(text, legacy_tokens):
    spans, active = project_period_spans(text, legacy_tokens)
    return [text[start:end] for start, end in spans] if active else legacy_tokens


def rewrite_projected_tokens(text, legacy_tokens, after_tokens, *, whole_tokens=False):
    """Replay token edits into original spans. Refuse lossy period deletion.

    None means an unsafe edit; callers must retain the original prompt.
    Legacy comma-only operations keep their established serializer.
    """
    spans, active = project_period_spans(text, legacy_tokens)
    if not active and not re.search(r'\.\s', text):
        return ', '.join(after_tokens)
    if whole_tokens or not active:
        spans = []
        cursor = 0
        for token in legacy_tokens:
            start = text.find(token, cursor)
            spans.append((start, start + len(token)))
            cursor = start + len(token)
    before_tokens = [text[start:end] for start, end in spans]
    edits = []
    for kind, a, b, c, d in difflib.SequenceMatcher(a=before_tokens, b=after_tokens, autojunk=False).get_opcodes():
        if kind == 'equal':
            continue
        if a == b:
            # Insertion ownership is ambiguous across an original delimiter.
            return None
        start, end = spans[a][0], spans[b - 1][1]
        if b - a > 1 and any('.' in text[spans[i][1]:spans[i+1][0]] for i in range(a, b-1)):
            return None
        replacement = ', '.join(after_tokens[c:d])
        if not replacement:
            if b < len(spans):
                gap = text[end:spans[b][0]]
                if '.' in gap:
                    return None
                end = spans[b][0]
            elif a > 0:
                gap = text[spans[a-1][1]:start]
                if '.' in gap:
                    return None
                start = spans[a-1][1]
        edits.append((start, end, replacement))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text

def projected_selection_tokens(text, legacy_tokens, stored_tokens):
    """Keep old whole-token choices beside their projected descendants in order.

    Source containment, rather than a global union, keeps Module range ownership
    intact even when the same word also occurs elsewhere in the prompt.
    """
    spans, active = project_period_spans(text, legacy_tokens)
    if not active:
        return stored_tokens
    whole_spans = []
    cursor = 0
    for token in legacy_tokens:
        start = text.find(token, cursor)
        end = start + len(token)
        cursor = end
        if token in stored_tokens and '<mod:' not in token and '</mod:' not in token:
            whole_spans.append((start, end, token))
    result = []
    inserted = set()
    for start, end in spans:
        result.append(text[start:end])
        for whole_start, whole_end, token in whole_spans:
            if whole_start <= start and end <= whole_end and (whole_start, whole_end) != (start, end):
                if (whole_start, whole_end) not in inserted:
                    result.append(token)
                    inserted.add((whole_start, whole_end))
    return result
