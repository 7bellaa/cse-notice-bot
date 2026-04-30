"""Pure-function diff: identify new posts strictly above a watermark."""
from __future__ import annotations

from cse_bot.models import Post


def diff(posts: list[Post], watermark: int | None) -> list[Post]:
    """Return posts whose id is strictly greater than watermark, ascending.

    If watermark is None (baseline mode), returns []. The caller is
    responsible for the baseline behaviour (storing max id without notifying).
    """
    if watermark is None:
        return []
    return sorted((p for p in posts if p.id > watermark), key=lambda p: p.id)
