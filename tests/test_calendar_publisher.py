"""Unit tests for snapshot-driven calendar publisher."""
from __future__ import annotations

from datetime import date

from cse_bot.calendar_publisher import build_events
from cse_bot.models import ManualOverride, PostCacheEntry
from cse_bot.post_cache import PostCache


def _cache_with(*entries: tuple[str, str, str, str]) -> PostCache:
    """Helper: build a cache populated with (post_id, deadline, url, title) tuples."""
    cache = PostCache()
    posts: dict[str, PostCacheEntry] = {}
    for post_id, deadline, url, title in entries:
        posts[post_id] = PostCacheEntry(
            title=title, url=url, content_hash="",
            summarized_at="", deadline=deadline or None,
            category="장학/등록", summary="", important=False,
            last_seen="2026-05-26T00:00:00+09:00",
        )
    cache.boards["14221"] = posts
    return cache


def test_build_events_filters_past_deadlines() -> None:
    cache = _cache_with(
        ("1", "2026-04-01", "u1", "past"),
        ("2", "2026-06-01", "u2", "future"),
    )
    events = build_events(cache, [], today=date(2026, 5, 26))
    assert [e.post_id for e in events] == [2]


def test_build_events_skips_entries_without_deadline() -> None:
    cache = _cache_with(
        ("1", "", "u1", "no-deadline"),
        ("2", "2026-06-01", "u2", "future"),
    )
    events = build_events(cache, [], today=date(2026, 5, 26))
    assert [e.post_id for e in events] == [2]


def test_build_events_sorts_by_date_ascending() -> None:
    cache = _cache_with(
        ("1", "2026-08-01", "u1", "later"),
        ("2", "2026-06-01", "u2", "earlier"),
        ("3", "2026-07-01", "u3", "middle"),
    )
    events = build_events(cache, [], today=date(2026, 5, 26))
    assert [e.date for e in events] == ["2026-06-01", "2026-07-01", "2026-08-01"]


def test_build_events_appends_manual_overrides_with_new_urls() -> None:
    cache = _cache_with(("1", "2026-06-01", "u1", "cache"))
    overrides = [
        ManualOverride(id="m-1", title="manual", url="u-manual", date="2026-07-01"),
    ]
    events = build_events(cache, overrides, today=date(2026, 5, 26))
    titles = [e.title for e in events]
    assert "cache" in titles
    assert "manual" in titles


def test_build_events_manual_override_wins_on_url_match() -> None:
    """Override on same URL replaces date/category/important from cache."""
    cache = _cache_with(("1", "2026-06-01", "u-shared", "cache-title"))
    overrides = [
        ManualOverride(
            id="m-1", title="manual-title", url="u-shared",
            date="2026-07-15", category="비교과/활동", important=True,
        ),
    ]
    events = build_events(cache, overrides, today=date(2026, 5, 26))
    assert len(events) == 1
    ev = events[0]
    assert ev.date == "2026-07-15"
    assert ev.category == "비교과/활동"
    assert ev.important is True
    # title from cache is kept (only date/category/important are overridden)
    assert ev.title == "cache-title"
