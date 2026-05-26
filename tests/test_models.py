"""Unit tests for data models."""
from dataclasses import FrozenInstanceError

import pytest

from cse_bot.models import BoardConfig, BoardState, Post


def test_post_is_frozen() -> None:
    post = Post(
        id=19234,
        title="공지 제목",
        author="홍길동",
        date="2026.04.30",
        url="https://cse.pusan.ac.kr/post/19234",
        category="일반공지",
        has_attachment=True,
    )
    with pytest.raises(FrozenInstanceError):
        post.id = 99999  # type: ignore[misc]


def test_post_equality_by_value() -> None:
    a = Post(
        id=1, title="t", author="a", date="d", url="u", category="c", has_attachment=False
    )
    b = Post(
        id=1, title="t", author="a", date="d", url="u", category="c", has_attachment=False
    )
    assert a == b


def test_board_config_defaults_enabled() -> None:
    cfg = BoardConfig(
        id="14221",
        name="일반공지",
        url="https://cse.pusan.ac.kr/cse/14221/subview.do",
        webhook_envs=["DISCORD_WEBHOOK_GENERAL"],
    )
    assert cfg.enabled is True


def test_board_state_baseline_when_none() -> None:
    state = BoardState(last_max_post_id=None, last_checked="2026-04-30T18:00:00+09:00")
    assert state.last_max_post_id is None
    assert state.empty_streak == 0


def test_post_cache_entry_defaults():
    from cse_bot.models import PostCacheEntry
    e = PostCacheEntry(
        title="t", url="u", content_hash="sha256:abc",
        summarized_at="2026-05-26T23:00:00+09:00",
        deadline="2026-06-22", category="장학/등록",
        summary="s", important=True,
        last_seen="2026-05-26T23:00:00+09:00",
    )
    assert e.deadline == "2026-06-22"
    assert e.important is True


def test_post_cache_entry_nullable_deadline():
    from cse_bot.models import PostCacheEntry
    e = PostCacheEntry(
        title="t", url="u", content_hash="",
        summarized_at="", deadline=None, category="",
        summary="", important=False, last_seen="",
    )
    assert e.deadline is None


def test_manual_override_frozen():
    from cse_bot.models import ManualOverride
    o = ManualOverride(
        id="m-1", title="수강신청", url="https://x", date="2026-08-19",
    )
    assert o.category == ""
    assert o.important is False
    assert o.expires_at is None
    import dataclasses
    assert dataclasses.is_dataclass(o)
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        o.title = "x"  # type: ignore[misc]
