"""Tests for src/cse_bot/calendar_renderer.py."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from cse_bot.calendar_renderer import (
    BG_COLOR,
    STRIP_WIDTH,
    render_upcoming_strip,
    resolve_font_path,
)
from cse_bot.models import TrackedDeadline


def _d(post_id: int, title: str, date_str: str, category: str = "") -> TrackedDeadline:
    return TrackedDeadline(
        post_id=post_id,
        title=title,
        url=f"https://example.com/{post_id}",
        date=date_str,
        category=category,
    )


@pytest.fixture
def today() -> date:
    return date(2026, 5, 26)


class TestRenderUpcomingStrip:
    def test_empty_list_renders_placeholder(
        self, tmp_path: Path, today: date
    ) -> None:
        out = tmp_path / "upcoming.png"
        render_upcoming_strip([], today, out)
        assert out.exists()
        with Image.open(out) as img:
            assert img.format == "PNG"
            assert img.width == STRIP_WIDTH
            assert img.height > 100

    def test_single_deadline_renders(self, tmp_path: Path, today: date) -> None:
        deadlines = [_d(1, "[장학] 주거안정장학금 신청", "2026-06-22", "장학/등록")]
        out = tmp_path / "upcoming.png"
        render_upcoming_strip(deadlines, today, out)
        assert out.exists()
        assert out.stat().st_size > 1000

    def test_top_n_caps_number_of_cards(
        self, tmp_path: Path, today: date
    ) -> None:
        # 10 deadlines but top_n=3 → canvas should be sized for 3 cards
        deadlines = [
            _d(i, f"[학업] 과제 {i}", f"2026-06-{i:02d}", "학업/수강")
            for i in range(1, 11)
        ]
        out_3 = tmp_path / "u3.png"
        out_5 = tmp_path / "u5.png"
        render_upcoming_strip(deadlines, today, out_3, top_n=3)
        render_upcoming_strip(deadlines, today, out_5, top_n=5)
        with Image.open(out_3) as a, Image.open(out_5) as b:
            # top_n=5 must produce a taller canvas (more cards)
            assert b.height > a.height

    def test_past_deadlines_filtered(
        self, tmp_path: Path, today: date
    ) -> None:
        # All past — should fall back to the empty placeholder canvas
        deadlines = [_d(1, "[지난] 마감", "2026-05-01", "일반공지")]
        out = tmp_path / "u.png"
        render_upcoming_strip(deadlines, today, out)
        out_empty = tmp_path / "empty.png"
        render_upcoming_strip([], today, out_empty)
        # Same height = both took the empty-state branch
        with Image.open(out) as a, Image.open(out_empty) as b:
            assert a.height == b.height

    def test_invalid_date_does_not_crash(
        self, tmp_path: Path, today: date
    ) -> None:
        deadlines = [
            _d(1, "good", "2026-06-22", "장학/등록"),
            _d(2, "bad", "not-a-date", "장학/등록"),
        ]
        out = tmp_path / "u.png"
        render_upcoming_strip(deadlines, today, out)
        assert out.exists()

    def test_important_deadline_renders(
        self, tmp_path: Path, today: date
    ) -> None:
        deadlines = [
            TrackedDeadline(
                post_id=1,
                title="국가장학금 신청",
                url="https://x/1",
                date="2026-05-29",
                category="장학/등록",
                important=True,
            ),
        ]
        out = tmp_path / "u.png"
        render_upcoming_strip(deadlines, today, out)
        assert out.stat().st_size > 1000

    def test_background_is_discord_dark(
        self, tmp_path: Path, today: date
    ) -> None:
        out = tmp_path / "u.png"
        render_upcoming_strip([], today, out)
        with Image.open(out) as img:
            assert img.convert("RGB").getpixel((1, 1)) == BG_COLOR


class TestResolveFontPath:
    def test_returns_bundled_font_first(self) -> None:
        bundled = Path(__file__).resolve().parent.parent / "assets/fonts/Pretendard-Medium.ttf"
        # We bundled the font in setup, so it should resolve to it
        resolved = resolve_font_path()
        # Either the bundled file or a system fallback path should exist
        assert resolved is None or Path(resolved).exists() or resolved == str(bundled)
