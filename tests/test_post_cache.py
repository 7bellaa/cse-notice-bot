"""Unit tests for the v2 post-snapshot cache."""
from __future__ import annotations

import json
from pathlib import Path

from cse_bot.models import PostCacheEntry
from cse_bot.post_cache import PostCache, load_post_cache, save_post_cache


def test_load_returns_empty_cache_when_file_missing(tmp_path: Path) -> None:
    cache = load_post_cache(tmp_path / "post_cache.json")
    assert cache.schema_version == 1
    assert cache.boards == {}


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "post_cache.json"
    cache = PostCache(schema_version=1, updated_at="2026-05-26T23:00:00+09:00")
    cache.boards["14221"] = {
        "1441380": PostCacheEntry(
            title="[장학] 주거안정장학금",
            url="https://cse.pusan.ac.kr/.../1441380",
            content_hash="sha256:abc",
            summarized_at="2026-05-26T23:00:00+09:00",
            deadline="2026-06-22",
            category="장학/등록",
            summary="요약",
            important=True,
            last_seen="2026-05-26T23:00:00+09:00",
        )
    }
    save_post_cache(path, cache)

    loaded = load_post_cache(path)
    assert "14221" in loaded.boards
    assert "1441380" in loaded.boards["14221"]
    entry = loaded.boards["14221"]["1441380"]
    assert entry.deadline == "2026-06-22"
    assert entry.important is True


def test_load_with_corrupt_json_backs_up_and_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "post_cache.json"
    path.write_text("{not valid", encoding="utf-8")
    cache = load_post_cache(path)
    assert cache.boards == {}
    backups = list(tmp_path.glob("post_cache.json.corrupt-*"))
    assert len(backups) == 1


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "post_cache.json"
    save_post_cache(path, PostCache())
    assert path.exists()


def test_saved_file_has_non_ascii_korean(tmp_path: Path) -> None:
    path = tmp_path / "post_cache.json"
    cache = PostCache()
    cache.boards["14221"] = {
        "1": PostCacheEntry(
            title="장학", url="u", content_hash="",
            summarized_at="", deadline=None,
            category="장학/등록", summary="요약",
            important=False, last_seen="",
        )
    }
    save_post_cache(path, cache)
    raw = path.read_text(encoding="utf-8")
    assert "장학" in raw  # not \uXXXX escaped


def test_content_hash_is_stable_for_same_body() -> None:
    from cse_bot.post_cache import content_hash
    assert content_hash("hello world") == content_hash("hello world")


def test_content_hash_differs_for_different_body() -> None:
    from cse_bot.post_cache import content_hash
    assert content_hash("a") != content_hash("b")


def test_content_hash_prefix_is_sha256() -> None:
    from cse_bot.post_cache import content_hash
    h = content_hash("x")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64  # hex digest


def test_content_hash_normalises_whitespace() -> None:
    """Trailing whitespace and collapsed runs must not change the hash."""
    from cse_bot.post_cache import content_hash
    assert content_hash("hello   world") == content_hash("hello world")
    assert content_hash("hello world\n\n") == content_hash("hello world")


def _entry(last_seen: str) -> PostCacheEntry:
    return PostCacheEntry(
        title="t", url="u", content_hash="",
        summarized_at="", deadline="2026-12-31", category="",
        summary="", important=False, last_seen=last_seen,
    )


def test_prune_stale_removes_old_entries() -> None:
    from cse_bot.post_cache import PostCache, prune_stale
    cache = PostCache()
    cache.boards["14221"] = {
        "1": _entry("2026-04-01T00:00:00+09:00"),  # 55d old
        "2": _entry("2026-05-25T00:00:00+09:00"),  # 1d old
    }
    removed = prune_stale(cache, "14221", now_iso="2026-05-26T00:00:00+09:00", ttl_days=30)
    assert removed == 1
    assert "1" not in cache.boards["14221"]
    assert "2" in cache.boards["14221"]


def test_prune_stale_skips_unknown_board() -> None:
    from cse_bot.post_cache import PostCache, prune_stale
    cache = PostCache()
    removed = prune_stale(cache, "doesnotexist", now_iso="2026-05-26T00:00:00+09:00", ttl_days=30)
    assert removed == 0


def test_prune_stale_keeps_boundary_entry() -> None:
    """Entries exactly at the TTL boundary are NOT pruned (strict <)."""
    from cse_bot.post_cache import PostCache, prune_stale
    cache = PostCache()
    cache.boards["14221"] = {
        "1": _entry("2026-04-26T00:00:00+09:00"),  # exactly 30d
    }
    removed = prune_stale(cache, "14221", now_iso="2026-05-26T00:00:00+09:00", ttl_days=30)
    assert removed == 0
