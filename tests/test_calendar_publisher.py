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


# ─── run_calendar_publish tests ───────────────────────────────────────────────


def test_run_calendar_publish_creates_cache_and_returns_events(tmp_path, monkeypatch) -> None:
    """End-to-end-ish: feed a list, get events back, find cache on disk."""
    from cse_bot.calendar_publisher import run_calendar_publish

    # Stub article + summarizer so we don't hit the network.
    def fake_fetch(url, *, timeout, retries):
        return ArticleContent(body=f"body for {url}", image_urls=[])

    def fake_summarize(body, *, image_urls, api_key, model, timeout):
        return SummaryResult(summary="long", deadline="2026-06-22", short_summary="short")

    monkeypatch.setattr(
        "cse_bot.calendar_publisher.article.fetch_article_content", fake_fetch,
    )
    monkeypatch.setattr(
        "cse_bot.calendar_publisher.summarizer.summarize", fake_summarize,
    )

    cache_path = tmp_path / "post_cache.json"
    manual_path = tmp_path / "manual.json"

    events = run_calendar_publish(
        board_id="14221",
        posts_in_list=[_post(1441380, title="[장학] t1"), _post(1441381, title="[장학] t2")],
        today=date(2026, 5, 26),
        now_iso="2026-05-26T23:00:00+09:00",
        cache_path=cache_path,
        manual_path=manual_path,
        ttl_days=30,
        gemini_api_key="k",
        gemini_model="m",
        gemini_timeout=10,
        http_timeout=5,
        http_retries=2,
    )

    assert {e.post_id for e in events} == {1441380, 1441381}
    assert cache_path.exists()


def test_run_calendar_publish_warm_cache_does_not_call_gemini(tmp_path, monkeypatch) -> None:
    """Second invocation with same body must not call summarize."""
    from cse_bot.calendar_publisher import run_calendar_publish
    from cse_bot.post_cache import content_hash, save_post_cache

    cache_path = tmp_path / "post_cache.json"
    manual_path = tmp_path / "manual.json"

    body = "stable body"
    cache = PostCache()
    cache.boards["14221"] = {
        "100": PostCacheEntry(
            title="t", url="https://x/100",
            content_hash=content_hash(body),
            summarized_at="2026-05-01T00:00:00+09:00",
            deadline="2026-06-22", category="장학/등록",
            summary="s", important=False,
            last_seen="2026-05-01T00:00:00+09:00",
        )
    }
    save_post_cache(cache_path, cache)

    def fake_fetch(url, *, timeout, retries):
        return ArticleContent(body=body, image_urls=[])

    def fake_summarize(body, *, image_urls, api_key, model, timeout):
        raise AssertionError("warm cache should skip summarise")

    monkeypatch.setattr(
        "cse_bot.calendar_publisher.article.fetch_article_content", fake_fetch,
    )
    monkeypatch.setattr(
        "cse_bot.calendar_publisher.summarizer.summarize", fake_summarize,
    )

    events = run_calendar_publish(
        board_id="14221",
        posts_in_list=[Post(id=100, title="t", author="", date="", url="https://x/100",
                            category="", has_attachment=False)],
        today=date(2026, 5, 26),
        now_iso="2026-05-26T23:00:00+09:00",
        cache_path=cache_path,
        manual_path=manual_path,
        ttl_days=30,
        gemini_api_key="k", gemini_model="m", gemini_timeout=10,
        http_timeout=5, http_retries=2,
    )
    assert len(events) == 1
    assert events[0].date == "2026-06-22"


def test_run_calendar_publish_prunes_stale_entries(tmp_path, monkeypatch) -> None:
    """Entries with last_seen older than ttl_days are evicted."""
    from cse_bot.calendar_publisher import run_calendar_publish
    from cse_bot.post_cache import load_post_cache, save_post_cache

    cache_path = tmp_path / "post_cache.json"
    manual_path = tmp_path / "manual.json"

    cache = PostCache()
    cache.boards["14221"] = {
        "old": PostCacheEntry(
            title="old", url="https://x/old", content_hash="",
            summarized_at="", deadline="2026-12-31", category="",
            summary="", important=False,
            last_seen="2026-04-01T00:00:00+09:00",  # 55 days old
        )
    }
    save_post_cache(cache_path, cache)

    monkeypatch.setattr(
        "cse_bot.calendar_publisher.article.fetch_article_content",
        lambda url, *, timeout, retries: None,
    )

    run_calendar_publish(
        board_id="14221",
        posts_in_list=[],  # "old" no longer on list page
        today=date(2026, 5, 26),
        now_iso="2026-05-26T00:00:00+09:00",
        cache_path=cache_path,
        manual_path=manual_path,
        ttl_days=30,
        gemini_api_key="k", gemini_model="m", gemini_timeout=10,
        http_timeout=5, http_retries=2,
    )
    loaded = load_post_cache(cache_path)
    assert "old" not in loaded.boards.get("14221", {})
