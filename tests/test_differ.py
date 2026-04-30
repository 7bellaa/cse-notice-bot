"""Unit tests for the differ."""
from cse_bot.differ import diff
from cse_bot.models import Post


def _post(id_: int) -> Post:
    return Post(
        id=id_,
        title=f"title-{id_}",
        author="author",
        date="2026.04.30",
        url=f"https://example.com/{id_}",
        category="일반공지",
        has_attachment=False,
    )


def test_diff_returns_empty_when_no_new() -> None:
    posts = [_post(10), _post(11), _post(12)]
    assert diff(posts, watermark=12) == []


def test_diff_returns_only_greater_than_watermark() -> None:
    posts = [_post(10), _post(13), _post(11), _post(14), _post(12)]
    result = diff(posts, watermark=12)
    assert [p.id for p in result] == [13, 14]


def test_diff_returns_ascending_order() -> None:
    posts = [_post(20), _post(15), _post(18)]
    result = diff(posts, watermark=10)
    assert [p.id for p in result] == [15, 18, 20]


def test_diff_baseline_returns_empty() -> None:
    posts = [_post(10), _post(11)]
    # When watermark is None, the bot is in baseline mode — caller handles it.
    # diff() is still defined to return [] for this case.
    assert diff(posts, watermark=None) == []


def test_diff_with_strict_inequality_excludes_equal() -> None:
    posts = [_post(10), _post(11)]
    assert diff(posts, watermark=11) == []
