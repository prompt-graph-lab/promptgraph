"""Literal comma-separated tag formatting and parsing for metadata editors."""


def _format_comma_tags(tags) -> str:
    if not isinstance(tags, list):
        return ""
    return ", ".join(str(tag).strip() for tag in tags if str(tag).strip())


def _parse_comma_tags(text: str) -> list[str]:
    tags = []
    seen = set()
    for part in str(text or "").split(","):
        tag = part.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags
