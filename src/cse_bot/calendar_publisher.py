"""Snapshot-driven calendar pipeline (v2.0.0).

Replaces the watermark-driven ``state.deadlines`` flow with a cache that
mirrors the current list page. The cache, manual overrides, and event
list builder live here; the orchestrator ``run_calendar_publish``
composes them and is what ``main._emit_daily_digest`` calls.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

from cse_bot.article import ArticleContent
from cse_bot.category import classify, is_important
from cse_bot.models import ManualOverride, Post, PostCacheEntry, TrackedDeadline
from cse_bot.post_cache import PostCache, content_hash
from cse_bot.summarizer import SummaryResult

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


FetchFn = Callable[[str], ArticleContent | None]
SummarizeFn = Callable[[str, list[str]], SummaryResult | None]


def update_cache_from_snapshot(
    cache: PostCache,
    board_id: str,
    posts_in_list: list[Post],
    *,
    now_iso: str,
    fetch_body: FetchFn,
    summarize_fn: SummarizeFn,
) -> None:
    """Update *cache* in place to match the current list-page snapshot.

    Per post:

    1. Bump ``last_seen`` so a transient fetch failure does not trigger
       TTL eviction.
    2. Fetch the article body. On failure, keep the existing cache entry
       and move on.
    3. Compare ``content_hash`` against the cached value. On match, skip
       Gemini entirely — that is the warm-cache path.
    4. On cache miss or content change, call ``summarize_fn``. If it
       returns ``None``, keep the previous cache entry (or write a stub
       so we don't re-summarise an unsummarisable post each cycle).
    """
    posts = cache.boards.setdefault(board_id, {})

    for post in posts_in_list:
        key = str(post.id)
        cached = posts.get(key)
        if cached is not None:
            cached.last_seen = now_iso

        content = fetch_body(post.url)
        if content is None:
            log.warning("calendar.fetch_failed post_id=%d", post.id)
            continue

        new_hash = content_hash(content.body)
        if cached is not None and cached.content_hash == new_hash:
            continue  # warm cache — already bumped last_seen

        result = summarize_fn(content.body, list(content.image_urls))
        if result is None:
            if cached is None:
                # Stub so we don't try to summarise this post every cycle.
                posts[key] = PostCacheEntry(
                    title=post.title,
                    url=post.url,
                    content_hash=new_hash,
                    summarized_at="",
                    deadline=None,
                    category=classify(post.title),
                    summary="",
                    important=is_important(post.title),
                    last_seen=now_iso,
                )
            else:
                # Keep prior cache values; just refresh the hash so we don't loop.
                cached.content_hash = new_hash
            continue

        posts[key] = PostCacheEntry(
            title=post.title,
            url=post.url,
            content_hash=new_hash,
            summarized_at=now_iso,
            deadline=result.deadline,
            category=classify(post.title),
            summary=result.short_summary or result.summary,
            important=is_important(post.title),
            last_seen=now_iso,
        )
        log.info(
            "calendar.cache_update board=%s post_id=%d deadline=%s",
            board_id, post.id, result.deadline or "none",
        )
