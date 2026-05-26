"""Snapshot-driven calendar pipeline (v2.0.0).

Replaces the watermark-driven ``state.deadlines`` flow with a cache that
mirrors the current list page. The cache, manual overrides, and event
list builder live here; the orchestrator ``run_calendar_publish``
composes them and is what ``main._emit_daily_digest`` calls.
"""
from __future__ import annotations

import logging
from datetime import date

from cse_bot.models import ManualOverride, TrackedDeadline
from cse_bot.post_cache import PostCache

log = logging.getLogger(__name__)


def build_events(
    cache: PostCache,
    overrides: list[ManualOverride],
    *,
    today: date,
) -> list[TrackedDeadline]:
    """Return future-dated events from *cache* merged with *overrides*.

    Manual overrides take precedence on URL collision: the cache entry's
    date / category / important fields are replaced by the override's
    values. Otherwise the override is appended as a fresh event.
    """
    events: list[TrackedDeadline] = []
    today_iso = today.isoformat()

    for _board_id, posts in cache.boards.items():
        for post_id, entry in posts.items():
            dl = entry.deadline
            if not dl or dl < today_iso:
                continue
            try:
                pid_int = int(post_id)
            except ValueError:
                continue
            events.append(
                TrackedDeadline(
                    post_id=pid_int,
                    title=entry.title,
                    url=entry.url,
                    date=dl,
                    category=entry.category,
                    summary=entry.summary,
                    important=entry.important,
                )
            )

    # Manual overrides: same URL → patch fields; new URL → append.
    url_to_event: dict[str, TrackedDeadline] = {e.url: e for e in events}
    for ov in overrides:
        if ov.url in url_to_event:
            ev = url_to_event[ov.url]
            ev.date = ov.date
            if ov.category:
                ev.category = ov.category
            if ov.important:
                ev.important = ov.important
        else:
            events.append(
                TrackedDeadline(
                    post_id=0,
                    title=ov.title,
                    url=ov.url,
                    date=ov.date,
                    category=ov.category,
                    summary="",
                    important=ov.important,
                )
            )

    events.sort(key=lambda d: d.date)
    return events
