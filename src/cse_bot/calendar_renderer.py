"""Render the upcoming-deadlines strip PNG embedded in the Discord digest.

Each future deadline gets a full-width card with a large D-N badge (left)
and category chip + title (right). Canvas width is fixed at
``STRIP_WIDTH`` so Discord's embed-image scaling preserves text
legibility.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from cse_bot.category import (
    CATEGORY_GENERAL,
    CATEGORY_SHORT,
    CHIP_TAG_DEFAULT,
    CHIP_TAG_PALETTE,
)
from cse_bot.models import TrackedDeadline, safe_iso_date, strip_category_prefix

log = logging.getLogger(__name__)

# ─── Color palette ───────────────────────────────────────────────────────
BG_COLOR: tuple[int, int, int] = (49, 51, 56)         # #313338 chat bg
HERO_TEXT: tuple[int, int, int] = (242, 243, 245)
HERO_TAG_TEXT: tuple[int, int, int] = (148, 155, 164)
HEADER_TEXT_MUTED: tuple[int, int, int] = (148, 155, 164)
IMPORTANT_RING: tuple[int, int, int] = (250, 204, 21)
WHITE: tuple[int, int, int] = (255, 255, 255)

CARD_BG: tuple[int, int, int] = (43, 45, 49)              # #2b2d31 embed bg
CARD_BORDER: tuple[int, int, int] = (30, 31, 34)          # #1e1f22
CARD_TEXT: tuple[int, int, int] = (242, 243, 245)         # light on dark
CARD_TEXT_SECONDARY: tuple[int, int, int] = (181, 186, 193)
CARD_TEXT_MUTED: tuple[int, int, int] = (148, 155, 164)

# ─── Strip layout ────────────────────────────────────────────────────────
STRIP_WIDTH = 880
STRIP_PADDING = 32
STRIP_HERO_HEIGHT = 80
STRIP_SUBTITLE_HEIGHT = 30
STRIP_CARD_HEIGHT = 112
STRIP_CARD_GAP = 10
STRIP_FOOTER_HEIGHT = 30
STRIP_EMPTY_HEIGHT = 120
STRIP_BADGE_WIDTH = 92

# Urgency band colors for the D-N badge + left card stripe.
URGENT_RED: tuple[int, int, int] = (220, 38, 38)
NEAR_AMBER: tuple[int, int, int] = (217, 119, 6)
SOFT_BLUE: tuple[int, int, int] = (88, 101, 242)


def resolve_font_path() -> str | None:
    """Return the best available font path for Korean rendering, or None."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "assets" / "fonts" / "Pretendard-Medium.ttf"
        if candidate.exists():
            return str(candidate)
        if (parent / "pyproject.toml").exists():
            break
    apple = Path("/System/Library/Fonts/Apple SD Gothic Neo.ttc")
    if apple.exists():
        return str(apple)
    return None


_Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


def _load_font(path: str | None, size: int) -> _Font:
    if path is None:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        log.warning("font.load_failed path=%s size=%d", path, size)
        return ImageFont.load_default()


def _text_w(font: _Font, text: str) -> int:
    if not text:
        return 0
    bbox = font.getbbox(text)
    return int(bbox[2] - bbox[0])


def _chip_tag_color(category: str) -> tuple[int, int, int]:
    return CHIP_TAG_PALETTE.get(category, CHIP_TAG_DEFAULT)


def _short_category(category: str) -> str:
    return CATEGORY_SHORT.get(category, CATEGORY_SHORT[CATEGORY_GENERAL])


def _d_urgency_color(delta: int) -> tuple[int, int, int]:
    """Return the band color for a D-N badge: red ≤3, amber ≤7, blue otherwise."""
    if delta <= 3:
        return URGENT_RED
    if delta <= 7:
        return NEAR_AMBER
    return SOFT_BLUE


def _d_label_text(delta: int) -> str:
    if delta == 0:
        return "오늘"
    if delta < 0:
        return "지남"
    return f"D-{delta}"


_KOREAN_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def _korean_weekday(d: date) -> str:
    return _KOREAN_WEEKDAYS[d.weekday()]


def render_upcoming_strip(
    deadlines: list[TrackedDeadline],
    today: date,
    output_path: Path,
    *,
    top_n: int = 5,
) -> None:
    """Render the upcoming-deadlines strip PNG used as the Discord embed image.

    Horizontal card layout — each future deadline gets a full-width card with
    a large D-N badge on the left and category chip + title on the right.
    Sized at ``STRIP_WIDTH`` so Discord's embed scaling preserves readability.
    Always produces a valid PNG, including when ``deadlines`` is empty.
    """
    font_path = resolve_font_path()
    hero_font = _load_font(font_path, 42)
    hero_tag_font = _load_font(font_path, 14)
    sub_font = _load_font(font_path, 15)
    d_label_font = _load_font(font_path, 34)
    d_label_sub_font = _load_font(font_path, 11)
    title_font = _load_font(font_path, 22)
    chip_font = _load_font(font_path, 13)
    meta_font = _load_font(font_path, 14)
    footer_font = _load_font(font_path, 13)

    # Filter to future-dated, parseable deadlines (already sorted by caller).
    valid: list[tuple[TrackedDeadline, int]] = []
    for d in deadlines:
        d_date = safe_iso_date(d.date)
        if d_date is None:
            continue
        delta = (d_date - today).days
        if delta < 0:
            continue
        valid.append((d, delta))
    visible = valid[:top_n]
    urgent_count = sum(1 for _, delta in valid if delta <= 3)

    cards_h = (
        STRIP_EMPTY_HEIGHT
        if not visible
        else len(visible) * STRIP_CARD_HEIGHT
        + max(0, len(visible) - 1) * STRIP_CARD_GAP
    )
    canvas_h = (
        STRIP_PADDING
        + STRIP_HERO_HEIGHT
        + STRIP_SUBTITLE_HEIGHT
        + cards_h
        + 16
        + STRIP_FOOTER_HEIGHT
        + STRIP_PADDING
    )

    img = Image.new("RGB", (STRIP_WIDTH, canvas_h), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    pad = STRIP_PADDING
    y = pad

    # ─── Hero ─────────────────────────────────────────────────────
    hero_text = "임박 마감"
    draw.text((pad, y), hero_text, fill=HERO_TEXT, font=hero_font)
    hero_bbox = hero_font.getbbox(hero_text)
    hero_w = hero_bbox[2] - hero_bbox[0]
    hero_bottom = hero_bbox[3]
    draw.text(
        (pad + hero_w + 18, y + hero_bottom - 24),
        "DEADLINE · 임박 일정",
        fill=HERO_TAG_TEXT,
        font=hero_tag_font,
    )
    accent_y = y + hero_bottom + 6
    draw.rectangle(
        [pad, accent_y, pad + hero_w, accent_y + 5],
        fill=IMPORTANT_RING,
    )
    y += STRIP_HERO_HEIGHT

    # ─── Subtitle ─────────────────────────────────────────────────
    sub_parts = [f"{today.isoformat()} 기준", f"마감 임박 {len(valid)}건"]
    if urgent_count:
        sub_parts.append(f"D-3 이내 {urgent_count}건")
    draw.text(
        (pad, y),
        " · ".join(sub_parts),
        fill=HEADER_TEXT_MUTED,
        font=sub_font,
    )
    y += STRIP_SUBTITLE_HEIGHT

    # ─── Cards (or empty state) ──────────────────────────────────
    if not visible:
        empty_text = "추적 중인 마감 일정이 없습니다."
        ew = _text_w(sub_font, empty_text)
        draw.text(
            ((STRIP_WIDTH - ew) // 2, y + (STRIP_EMPTY_HEIGHT - 20) // 2),
            empty_text,
            fill=CARD_TEXT_MUTED,
            font=sub_font,
        )
        y += STRIP_EMPTY_HEIGHT
    else:
        for i, (d, delta) in enumerate(visible):
            _draw_strip_card(
                draw,
                x=pad,
                y=y,
                width=STRIP_WIDTH - 2 * pad,
                height=STRIP_CARD_HEIGHT,
                deadline=d,
                delta=delta,
                d_label_font=d_label_font,
                d_label_sub_font=d_label_sub_font,
                title_font=title_font,
                chip_font=chip_font,
                meta_font=meta_font,
            )
            y += STRIP_CARD_HEIGHT
            if i < len(visible) - 1:
                y += STRIP_CARD_GAP

    # ─── Footer ───────────────────────────────────────────────────
    y += 16
    left_text = "매일 18:00 갱신 · 클릭하면 전체 캘린더로 이동 →"
    draw.text((pad, y), left_text, fill=HEADER_TEXT_MUTED, font=footer_font)
    right_text = "전체 마감일은 웹 캘린더에서"
    rw = _text_w(footer_font, right_text)
    draw.text(
        (STRIP_WIDTH - pad - rw, y),
        right_text,
        fill=HEADER_TEXT_MUTED,
        font=footer_font,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    img.save(tmp, format="PNG", optimize=True)
    tmp.replace(output_path)


def _draw_strip_card(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    deadline: TrackedDeadline,
    delta: int,
    d_label_font: _Font,
    d_label_sub_font: _Font,
    title_font: _Font,
    chip_font: _Font,
    meta_font: _Font,
) -> None:
    x0, y0 = x, y
    x1, y1 = x + width, y + height

    draw.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=10,
        fill=CARD_BG,
        outline=CARD_BORDER,
        width=1,
    )

    urgency = _d_urgency_color(delta)
    draw.rounded_rectangle(
        [x0, y0, x0 + 6, y1],
        radius=3,
        fill=urgency,
    )

    # D-N badge column
    draw.text(
        (x0 + 24, y0 + 26),
        _d_label_text(delta),
        fill=urgency,
        font=d_label_font,
    )
    draw.text(
        (x0 + 24, y0 + 72),
        "마감까지",
        fill=CARD_TEXT_MUTED,
        font=d_label_sub_font,
    )

    draw.line(
        [(x0 + STRIP_BADGE_WIDTH, y0 + 16), (x0 + STRIP_BADGE_WIDTH, y1 - 16)],
        fill=CARD_BORDER,
        width=1,
    )

    # Content column
    cx = x0 + STRIP_BADGE_WIDTH + 18
    cy = y0 + 16

    chip_color = _chip_tag_color(deadline.category)
    chip_text = _short_category(deadline.category)
    chip_w = _text_w(chip_font, chip_text) + 16
    chip_h = 22
    draw.rounded_rectangle(
        [cx, cy, cx + chip_w, cy + chip_h],
        radius=4,
        fill=chip_color,
    )
    draw.text((cx + 8, cy + 3), chip_text, fill=WHITE, font=chip_font)

    d_date = safe_iso_date(deadline.date)
    date_text = (
        f"{deadline.date} ({_korean_weekday(d_date)})" if d_date else deadline.date
    )
    draw.text(
        (cx + chip_w + 10, cy + 4),
        date_text,
        fill=CARD_TEXT_SECONDARY,
        font=meta_font,
    )

    title = strip_category_prefix(deadline.title)
    if deadline.important:
        title = "★ " + title
    title_max_w = (x1 - 18) - cx
    while _text_w(title_font, title) > title_max_w and len(title) > 8:
        title = title[:-2] + "…"
    title_color = IMPORTANT_RING if deadline.important else CARD_TEXT
    draw.text((cx, cy + 38), title, fill=title_color, font=title_font)

    if deadline.important:
        title_w = _text_w(title_font, title)
        draw.line(
            [(cx, cy + 70), (cx + min(title_w, title_max_w), cy + 70)],
            fill=IMPORTANT_RING,
            width=2,
        )
