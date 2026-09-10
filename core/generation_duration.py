"""Format generation timing estimates without owning timing or execution state."""


def _format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "不明"
    seconds = int(round(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"約{hours}時間{minutes}分"
    if minutes:
        return f"約{minutes}分{secs:02d}秒"
    return f"約{secs}秒"
