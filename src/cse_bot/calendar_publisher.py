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
from pathlib import Path

from cse_bot import article, summarizer
from cse_bot.article import ArticleContent
from cse_bot.category import classify, is_important
from cse_bot.manual_overrides import load_manual_overrides
from cse_bot.models import ManualOverride, Post, PostCacheEntry, TrackedDeadline
from cse_bot.post_cache import (
    PostCache,
    content_hash,
    load_post_cache,
    prune_stale,
    save_post_cache,
)
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
    board_posts = cache.boards.setdefault(board_id, {})

    for post in posts_in_list:
        key = str(post.id)
        cached = board_posts.get(key)
        # Bump last_seen BEFORE fetch — a transient fetch failure must not
        # leave the entry on a slide toward TTL eviction. The post is still
        # observed on the list page regardless of whether fetch succeeds.
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
            # Treat summarize failures as transient. Don't lock in a stub
            # (its content_hash would match the body next cycle and skip
            # the retry, freezing deadline=None) and don't refresh the
            # prior entry's hash (same trap). The existing entry — if any
            # — keeps its deadline; its last_seen was already bumped
            # above, so TTL is safe. Next cycle's hash mismatch triggers
            # a fresh attempt.
            log.warning(
                "calendar.summarize_failed board=%s post_id=%d (will retry next cycle)",
                board_id, post.id,
            )
            continue

        board_posts[key] = PostCacheEntry(
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


def run_calendar_publish(
    *,
    board_id: str,
    posts_in_list: list[Post],
    today: date,
    now_iso: str,
    cache_path: Path,
    manual_path: Path,
    ttl_days: int,
    gemini_api_key: str,
    gemini_model: str,
    gemini_timeout: float,
    http_timeout: float,
    http_retries: int,
) -> list[TrackedDeadline]:
    """Refresh the snapshot cache for *board_id* and return active events.

    Keyword-only API so the orchestrator (``main._emit_daily_digest``)
    passes config explicitly instead of importing :mod:`Config` here,
    keeping this module independent of the wider TOML schema.
    """
    cache = load_post_cache(cache_path)

    def _fetch_body(url: str):
        return article.fetch_article_content(
            url, timeout=http_timeout, retries=http_retries,
        )

    def _summarize(body: str, image_urls: list[str]):
        return summarizer.summarize(
            body,
            image_urls=image_urls,
            api_key=gemini_api_key,
            model=gemini_model,
            timeout=gemini_timeout,
        )

    update_cache_from_snapshot(
        cache, board_id, posts_in_list,
        now_iso=now_iso,
        fetch_body=_fetch_body,
        summarize_fn=_summarize,
    )

    pruned = prune_stale(cache, board_id, now_iso=now_iso, ttl_days=ttl_days)
    if pruned:
        log.info("calendar.cache_pruned board=%s count=%d", board_id, pruned)

    cache.updated_at = now_iso
    save_post_cache(cache_path, cache)

    overrides = load_manual_overrides(manual_path)
    return build_events(cache, overrides, today=today)
