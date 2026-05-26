"""Unit tests for snapshot-driven calendar publisher."""
from __future__ import annotations

from datetime import date

from cse_bot.article import ArticleContent
from cse_bot.calendar_publisher import build_events, update_cache_from_snapshot
from cse_bot.models import ManualOverride, Post, PostCacheEntry
from cse_bot.post_cache import PostCache
from cse_bot.summarizer import SummaryResult


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


# ─── update_cache_from_snapshot tests ────────────────────────────────────────


def _post(pid: int, title: str = "[장학] t") -> Post:
    return Post(
        id=pid, title=title, author="", date="2026-05-26",
        url=f"https://cse.pusan.ac.kr/.../{pid}",
        category="", has_attachment=False,
    )


def test_update_cache_miss_calls_summarize_and_inserts() -> None:
    cache = PostCache()
    calls: list[tuple[str, list[str]]] = []

    def fake_fetch(url: str) -> ArticleContent | None:
        return ArticleContent(body="hello", image_urls=[])

    def fake_summarize(body: str, image_urls: list[str]) -> SummaryResult | None:
        calls.append((body, image_urls))
        return SummaryResult(summary="long", deadline="2026-06-22", short_summary="short")

    update_cache_from_snapshot(
        cache, "14221", [_post(1441380)],
        now_iso="2026-05-26T23:00:00+09:00",
        fetch_body=fake_fetch,
        summarize_fn=fake_summarize,
    )
    assert len(calls) == 1
    entry = cache.boards["14221"]["1441380"]
    assert entry.deadline == "2026-06-22"
    assert entry.summary == "short"


def test_update_cache_hit_skips_summarize() -> None:
    """If content_hash matches the cached value, summarize is NOT called."""
    from cse_bot.post_cache import content_hash
    body = "stable body"
    cache = PostCache()
    cache.boards["14221"] = {
        "100": PostCacheEntry(
            title="cached", url="https://x/100", content_hash=content_hash(body),
            summarized_at="2026-05-01T00:00:00+09:00",
            deadline="2026-06-22", category="장학/등록",
            summary="cached", important=False,
            last_seen="2026-05-01T00:00:00+09:00",
        )
    }

    def fake_fetch(url: str) -> ArticleContent | None:
        return ArticleContent(body=body, image_urls=[])

    def fake_summarize(body: str, image_urls: list[str]) -> SummaryResult | None:
        raise AssertionError("summarize should not be called on cache hit")

    update_cache_from_snapshot(
        cache, "14221",
        [Post(id=100, title="t", author="", date="", url="https://x/100",
              category="", has_attachment=False)],
        now_iso="2026-05-26T23:00:00+09:00",
        fetch_body=fake_fetch,
        summarize_fn=fake_summarize,
    )
    # last_seen bumped to the current cycle
    assert cache.boards["14221"]["100"].last_seen == "2026-05-26T23:00:00+09:00"


def test_update_cache_changed_body_triggers_resummarize() -> None:
    from cse_bot.post_cache import content_hash
    cache = PostCache()
    cache.boards["14221"] = {
        "100": PostCacheEntry(
            title="cached", url="https://x/100",
            content_hash=content_hash("OLD body"),
            summarized_at="2026-05-01T00:00:00+09:00",
            deadline="2026-06-22", category="",
            summary="", important=False, last_seen="",
        )
    }
    fetched_body = "NEW body"

    def fake_fetch(url: str) -> ArticleContent | None:
        return ArticleContent(body=fetched_body, image_urls=[])

    def fake_summarize(body: str, image_urls: list[str]) -> SummaryResult | None:
        assert body == fetched_body
        return SummaryResult(summary="long", deadline="2026-07-01", short_summary="updated")

    update_cache_from_snapshot(
        cache, "14221",
        [Post(id=100, title="t", author="", date="", url="https://x/100",
              category="", has_attachment=False)],
        now_iso="2026-05-26T23:00:00+09:00",
        fetch_body=fake_fetch,
        summarize_fn=fake_summarize,
    )
    entry = cache.boards["14221"]["100"]
    assert entry.deadline == "2026-07-01"
    assert entry.summary == "updated"
    assert entry.content_hash == content_hash(fetched_body)


def test_update_cache_fetch_failure_bumps_last_seen_but_keeps_entry() -> None:
    cache = PostCache()
    cache.boards["14221"] = {
        "100": PostCacheEntry(
            title="cached", url="https://x/100", content_hash="sha256:old",
            summarized_at="2026-05-01T00:00:00+09:00",
            deadline="2026-06-22", category="장학/등록",
            summary="cached", important=False,
            last_seen="2026-05-01T00:00:00+09:00",
        )
    }

    def fake_fetch(url: str) -> ArticleContent | None:
        return None

    def fake_summarize(body: str, image_urls: list[str]) -> SummaryResult | None:
        raise AssertionError("should not be called when fetch fails")

    update_cache_from_snapshot(
        cache, "14221",
        [Post(id=100, title="t", author="", date="", url="https://x/100",
              category="", has_attachment=False)],
        now_iso="2026-05-26T23:00:00+09:00",
        fetch_body=fake_fetch,
        summarize_fn=fake_summarize,
    )
    entry = cache.boards["14221"]["100"]
    assert entry.deadline == "2026-06-22"  # preserved
    assert entry.last_seen == "2026-05-26T23:00:00+09:00"  # bumped


def test_update_cache_summarize_failure_creates_stub_when_no_prior_entry() -> None:
    cache = PostCache()

    def fake_fetch(url: str) -> ArticleContent | None:
        return ArticleContent(body="hello", image_urls=[])

    def fake_summarize(body: str, image_urls: list[str]) -> SummaryResult | None:
        return None

    update_cache_from_snapshot(
        cache, "14221", [_post(999)],
        now_iso="2026-05-26T23:00:00+09:00",
        fetch_body=fake_fetch,
        summarize_fn=fake_summarize,
    )
    # Stub entry exists with deadline=None so we don't keep summarising it
    entry = cache.boards["14221"]["999"]
    assert entry.deadline is None
    assert entry.title == "[장학] t"
