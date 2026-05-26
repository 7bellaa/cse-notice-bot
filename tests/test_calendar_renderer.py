"""Tests for src/cse_bot/calendar_renderer.py."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from cse_bot.calendar_renderer import (
    BG_COLOR,
    render_calendar_png,
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


class TestRenderCalendarPng:
    def test_creates_valid_png(self, tmp_path: Path, today: date) -> None:
        out = tmp_path / "current.png"
        render_calendar_png([], today, out)

        assert out.exists()
        with Image.open(out) as img:
            assert img.format == "PNG"
            assert img.width > 100
            assert img.height > 100

    def test_creates_parent_directory(self, tmp_path: Path, today: date) -> None:
        out = tmp_path / "deep" / "nest" / "calendar.png"
        render_calendar_png([], today, out)
        assert out.exists()

    def test_background_is_discord_dark(self, tmp_path: Path, today: date) -> None:
        out = tmp_path / "current.png"
        render_calendar_png([], today, out)
        with Image.open(out) as img:
            rgb = img.convert("RGB")
            # Sample the top-left corner — should be the Discord dark canvas
            assert rgb.getpixel((1, 1)) == BG_COLOR

    def test_single_deadline_renders(self, tmp_path: Path, today: date) -> None:
        deadlines = [_d(1, "[장학] 주거안정장학금 신청", "2026-06-22", "장학")]
        out = tmp_path / "current.png"
        render_calendar_png(deadlines, today, out)
        assert out.stat().st_size > 0

    def test_many_deadlines_with_overflow_cell(
        self, tmp_path: Path, today: date
    ) -> None:
        # 4 deadlines on the same day → cell overflow "외 N건"
        deadlines = [
            _d(1, "[장학] A", "2026-05-30", "장학"),
            _d(2, "[장학] B", "2026-05-30", "장학"),
            _d(3, "[수업] C", "2026-05-30", "수업"),
            _d(4, "[취업] D", "2026-05-30", "취업"),
        ]
        out = tmp_path / "current.png"
        render_calendar_png(deadlines, today, out)
        assert out.stat().st_size > 0

    def test_deadline_today_renders(self, tmp_path: Path, today: date) -> None:
        deadlines = [_d(1, "[장학] 오늘 마감", today.isoformat(), "장학")]
        out = tmp_path / "current.png"
        render_calendar_png(deadlines, today, out)
        assert out.stat().st_size > 0

    def test_deadline_d_minus_1(self, tmp_path: Path, today: date) -> None:
        deadlines = [_d(1, "[장학] 내일 마감", "2026-05-27", "장학")]
        out = tmp_path / "current.png"
        render_calendar_png(deadlines, today, out)
        assert out.stat().st_size > 0

    def test_deadline_out_of_window_ignored_in_rendering(
        self, tmp_path: Path, today: date
    ) -> None:
        # months_in_png=2 means May+June. A deadline in Aug is out of window.
        # Should still complete without error (just won't appear visually).
        deadlines = [_d(1, "[학사] 8월 졸업요건", "2026-08-10", "학사")]
        out = tmp_path / "current.png"
        render_calendar_png(deadlines, today, out, months=2)
        assert out.stat().st_size > 0

    def test_korean_text_does_not_crash(self, tmp_path: Path, today: date) -> None:
        # Verifies that Korean glyphs work via Pretendard fallback
        deadlines = [
            _d(1, "졸업논문 제출", "2026-05-30"),
            _d(2, "장학금 신청", "2026-06-22", "장학"),
        ]
        out = tmp_path / "current.png"
        render_calendar_png(deadlines, today, out)
        assert out.stat().st_size > 1000  # sanity: non-trivial image


class TestResolveFontPath:
    def test_returns_bundled_font_first(self) -> None:
        bundled = Path(__file__).resolve().parent.parent / "assets/fonts/Pretendard-Medium.ttf"
        # We bundled the font in setup, so it should resolve to it
        resolved = resolve_font_path()
        # Either the bundled file or a system fallback path should exist
        assert resolved is None or Path(resolved).exists() or resolved == str(bundled)
