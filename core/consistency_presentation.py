"""Coverage and source-label formatting for prompt consistency analysis."""


def _format_percent(value: float) -> str:
    return f"{float(value or 0.0) * 100:.1f}%"


def _compact_label_list(labels: list[str], limit: int = 4) -> str:
    labels = [str(label) for label in labels if str(label)]
    if len(labels) <= limit:
        return ", ".join(labels)
    return ", ".join(labels[:limit]) + f", +{len(labels) - limit} more"
