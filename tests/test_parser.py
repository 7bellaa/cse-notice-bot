"""Unit tests for the HTML parser."""
from pathlib import Path

import pytest

from cse_bot.models import Post
from cse_bot.parser import ParseEmptyError, parse

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_returns_list_of_posts() -> None:
    posts = parse(_load("sample_board.html"))
    assert len(posts) > 0
    assert all(isinstance(p, Post) for p in posts)


def test_parse_post_has_required_fields() -> None:
    posts = parse(_load("sample_board.html"))
    p = posts[0]
    assert p.id > 0
    assert p.title.strip()
    assert p.author.strip()
    assert p.date.strip()
    assert p.url.startswith("http")
    assert isinstance(p.has_attachment, bool)


def test_parse_post_ids_are_unique_within_page() -> None:
    posts = parse(_load("sample_board.html"))
    ids = [p.id for p in posts]
    assert len(ids) == len(set(ids))


def test_parse_empty_board_raises() -> None:
    with pytest.raises(ParseEmptyError):
        parse(_load("empty_board.html"))
