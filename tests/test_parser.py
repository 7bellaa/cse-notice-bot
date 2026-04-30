"""Unit tests for the HTML parser."""
from pathlib import Path

import pytest

from cse_bot.models import Post
from cse_bot.parser import ParseEmptyError, extract_post_id, parse

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


def test_parse_handles_pinned_and_regular_rows() -> None:
    posts = parse(_load("sample_board.html"))
    # The captured fixture has 11 pinned rows + 10 regular rows = 21 total.
    assert len(posts) == 21
    # Pinned rows carry category '일반공지'; regular rows carry a numeric sequence string.
    pinned = [p for p in posts if p.category == "일반공지"]
    regular = [p for p in posts if p.category != "일반공지"]
    assert len(pinned) == 11
    assert len(regular) == 10
    assert all(p.category.isdigit() for p in regular)


def test_parse_attachment_flag_distinguishes_both_cases() -> None:
    posts = parse(_load("sample_board.html"))
    assert any(p.has_attachment for p in posts), "expected at least one attached post"
    assert any(not p.has_attachment for p in posts), "expected at least one unattached post"


def test_extract_post_id_rejects_zero() -> None:
    assert extract_post_id("https://cse.pusan.ac.kr/bbs/cse/2055/0/artclView.do") is None


def test_extract_post_id_rejects_zero_in_query_string() -> None:
    assert extract_post_id("https://cse.pusan.ac.kr/x?articleNo=0") is None


def test_extract_post_id_accepts_positive() -> None:
    got = extract_post_id("https://cse.pusan.ac.kr/bbs/cse/2055/1389652/artclView.do")
    assert got == 1389652
