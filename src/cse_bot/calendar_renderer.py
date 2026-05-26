"""Render a 2-month deadline calendar to PNG for embedding in Discord.

The PNG keeps the Discord dark chat background as its outer canvas, but the
date cells themselves are rendered as clean white cards — mirroring the web
calendar design where the colored category chip is the only colored accent
(the body is a white card with dark text).

Layout (top → bottom):
    [Hero]                     마감일 + DEADLINE tag + gold underline
    [Title bar]                PNU CSE 마감 캘린더
    [Subtitle / helper]
    [Month #1 header]          2026년 5월
    [Weekday header row]       월 화 수 목 금 토 일
    [Date grid (5–6 rows)]     white card cells with colored chip-tag prefix
    [Month #2 header]          2026년 6월
    [Weekday header row]
    [Date grid]
    [Legend]                   chip-tag swatches + ★ 중요 일정
    [Footer]                   helper line

Outer background stays Discord dark to blend with embeds; cards are bright
to match the web look. Category color appears ONLY in the chip-tag prefix.
"""
from __future__ import annotations

import calendar
import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from cse_bot.category import (
    CATEGORY_ACADEMIC,
    CATEGORY_ACTIVITY,
    CATEGORY_CAREER,
    CATEGORY_GENERAL,
    CATEGORY_SCHOLARSHIP,
)
from cse_bot.models import TrackedDeadline

log = logging.getLogger(__name__)

# ─── Color palette ───────────────────────────────────────────────────────
# Outer canvas: Discord chat dark (unchanged) so the PNG blends into embeds.
BG_COLOR: tuple[int, int, int] = (49, 51, 56)         # #313338 chat bg
HERO_TEXT: tuple[int, int, int] = (242, 243, 245)
HERO_TAG_TEXT: tuple[int, int, int] = (148, 155, 164)
HEADER_TEXT_PRIMARY: tuple[int, int, int] = (242, 243, 245)
HEADER_TEXT_SECONDARY: tuple[int, int, int] = (181, 186, 193)
HEADER_TEXT_MUTED: tuple[int, int, int] = (148, 155, 164)
SUNDAY_ACCENT: tuple[int, int, int] = (237, 66, 69)
IMPORTANT_RING: tuple[int, int, int] = (250, 204, 21)
WHITE: tuple[int, int, int] = (255, 255, 255)

# Card surface — dark variant of the web card so it blends with Discord
# embeds. We translate the web's "white card on warm-gray page" into
# "dark surface on Discord chat bg" while keeping the same chip-tag
# accent system. Cards sit slightly darker than the outer canvas so the
# grid reads as an inset surface.
CARD_BG: tuple[int, int, int] = (43, 45, 49)              # #2b2d31 embed bg
CARD_BORDER: tuple[int, int, int] = (30, 31, 34)          # #1e1f22
CARD_TEXT: tuple[int, int, int] = (242, 243, 245)         # light on dark
CARD_TEXT_SECONDARY: tuple[int, int, int] = (181, 186, 193)
CARD_TEXT_MUTED: tuple[int, int, int] = (148, 155, 164)
CARD_TEXT_DISABLED: tuple[int, int, int] = (107, 114, 128)

# Tinted card states (subtle on dark — keep the card readable)
TODAY_CARD_BG: tuple[int, int, int] = (38, 47, 78)        # dim blurple tint
TODAY_CARD_BORDER: tuple[int, int, int] = (88, 101, 242)  # discord blurple
DUE_CARD_BG: tuple[int, int, int] = (78, 58, 15)          # dim amber
URGENT_CARD_BG: tuple[int, int, int] = (78, 31, 31)       # dim red

# Chip-tag colors — darker variants of the canonical palette so white text
# passes WCAG AA (≥ 4.5:1) against them. Mirrors docs/calendar/style.css.
CHIP_TAG_PALETTE: dict[str, tuple[int, int, int]] = {
    CATEGORY_SCHOLARSHIP: (109, 63, 207),   # #6d3fcf
    CATEGORY_ACADEMIC:    (13, 138, 126),   # #0d8a7e
    CATEGORY_CAREER:      (201, 58, 127),   # #c93a7f
    CATEGORY_ACTIVITY:    (201, 125, 5),    # #c97d05
    CATEGORY_GENERAL:     (75, 85, 99),     # #4b5563
}
CHIP_TAG_DEFAULT: tuple[int, int, int] = CHIP_TAG_PALETTE[CATEGORY_GENERAL]

# Short labels used inside the chip-tag pill (mirrors web `metaFor` map).
CATEGORY_SHORT: dict[str, str] = {
    CATEGORY_SCHOLARSHIP: "장학",
    CATEGORY_ACADEMIC:    "학업",
    CATEGORY_CAREER:      "졸업",
    CATEGORY_ACTIVITY:    "비교과",
    CATEGORY_GENERAL:     "공지",
}

# ─── Layout constants (pixels) ───────────────────────────────────────────
CANVAS_WIDTH = 1200
PADDING = 32
HERO_HEIGHT = 96
TITLE_HEIGHT = 60
SUBTITLE_HEIGHT = 24
HELPER_HEIGHT = 22
MONTH_HEADER_HEIGHT = 36
WEEKDAY_ROW_HEIGHT = 28
CELL_HEIGHT = 150
CELL_GAP = 4
MONTH_GAP = 24
LEGEND_HEIGHT = 28
FOOTER_HEIGHT = 28

LEGEND_CATEGORIES: tuple[str, ...] = (
    CATEGORY_SCHOLARSHIP,
    CATEGORY_ACADEMIC,
    CATEGORY_CAREER,
    CATEGORY_ACTIVITY,
    CATEGORY_GENERAL,
)

WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]


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


def _load_font(path: str | None, size: int) -> ImageFont.ImageFont:
    if path is None:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        log.warning("font.load_failed path=%s size=%d", path, size)
        return ImageFont.load_default()


def _week_rows_for_month(year: int, month: int) -> list[list[date | None]]:
    cal = calendar.Calendar(firstweekday=calendar.MONDAY)
    weeks: list[list[date | None]] = []
    for week in cal.monthdatescalendar(year, month):
        row: list[date | None] = []
        for day in week:
            row.append(day if day.month == month else None)
        weeks.append(row)
    return weeks


def _deadlines_by_date(
    deadlines: Iterable[TrackedDeadline],
) -> dict[str, list[TrackedDeadline]]:
    bucket: dict[str, list[TrackedDeadline]] = defaultdict(list)
    for d in deadlines:
        bucket[d.date].append(d)
    return bucket


def _add_months(d: date, months: int) -> date:
    new_month = d.month - 1 + months
    new_year = d.year + new_month // 12
    new_month = new_month % 12 + 1
    return date(new_year, new_month, 1)


def _strip_prefix(title: str) -> str:
    """Strip leading [category] tag for chip display."""
    if title.startswith("["):
        end = title.find("]")
        if end != -1:
            return title[end + 1:].strip()
    return title


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _text_w(font: ImageFont.ImageFont, text: str) -> int:
    if not text:
        return 0
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _wrap_two_lines(
    text: str,
    font: ImageFont.ImageFont,
    line1_max_w: int,
    line2_max_w: int,
) -> list[str]:
    """Wrap *text* into up to 2 lines fitting the given widths.

    Returns ``[line1]`` if it fits on one line, or ``[line1, line2]`` with
    line2 truncated with an ellipsis if necessary. Prefers breaking at a
    space when one is close to the chosen split point.
    """
    if _text_w(font, text) <= line1_max_w:
        return [text]

    # Greedy: longest prefix of *text* that fits in line1_max_w
    line1_end = len(text)
    while line1_end > 0 and _text_w(font, text[:line1_end]) > line1_max_w:
        line1_end -= 1
    if line1_end == 0:
        return [text[:1], ""]

    # Prefer breaking at a space within the last 6 chars of line 1.
    space_at = text.rfind(" ", 0, line1_end)
    if space_at > 0 and space_at >= line1_end - 6:
        line1_end = space_at

    line1 = text[:line1_end].rstrip()
    rest = text[line1_end:].lstrip()
    # Line 2: truncate with … if still too wide.
    while len(rest) > 1 and _text_w(font, rest) > line2_max_w:
        rest = rest[:-2] + "…"
    return [line1, rest]


def _chip_tag_color(category: str) -> tuple[int, int, int]:
    return CHIP_TAG_PALETTE.get(category, CHIP_TAG_DEFAULT)


def _short_category(category: str) -> str:
    return CATEGORY_SHORT.get(category, CATEGORY_SHORT[CATEGORY_GENERAL])


def render_calendar_png(
    deadlines: list[TrackedDeadline],
    today: date,
    output_path: Path,
    months: int = 2,
) -> None:
    """Render the deadline calendar to *output_path* as a PNG."""
    font_path = resolve_font_path()
    hero_font = _load_font(font_path, 64)
    hero_tag_font = _load_font(font_path, 16)
    title_font = _load_font(font_path, 22)
    subtitle_font = _load_font(font_path, 13)
    month_font = _load_font(font_path, 18)
    weekday_font = _load_font(font_path, 13)
    day_font = _load_font(font_path, 14)
    chip_tag_font = _load_font(font_path, 10)
    chip_title_font = _load_font(font_path, 11)
    footer_font = _load_font(font_path, 11)

    cell_width = (CANVAS_WIDTH - 2 * PADDING - 6 * CELL_GAP) // 7

    month_starts = [_add_months(today.replace(day=1), i) for i in range(months)]
    month_grids = [_week_rows_for_month(m.year, m.month) for m in month_starts]

    month_block_h = sum(
        MONTH_HEADER_HEIGHT
        + WEEKDAY_ROW_HEIGHT
        + len(g) * CELL_HEIGHT
        + (len(g) - 1) * CELL_GAP
        for g in month_grids
    )
    canvas_height = (
        PADDING
        + HERO_HEIGHT
        + TITLE_HEIGHT
        + SUBTITLE_HEIGHT
        + HELPER_HEIGHT
        + 16
        + month_block_h
        + (months - 1) * MONTH_GAP
        + LEGEND_HEIGHT
        + FOOTER_HEIGHT
        + PADDING
    )

    img = Image.new("RGB", (CANVAS_WIDTH, canvas_height), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    # ─── Hero banner ─────────────────────────────────────────────────────
    y = PADDING
    draw.text((PADDING, y), "마감일", fill=HERO_TEXT, font=hero_font)
    hero_bbox = hero_font.getbbox("마감일")
    hero_w = hero_bbox[2] - hero_bbox[0]
    hero_bottom = hero_bbox[3]
    tag_x = PADDING + hero_w + 16
    tag_y = y + hero_bottom - 24
    draw.text(
        (tag_x, tag_y),
        "DEADLINE · 마감 캘린더",
        fill=HERO_TAG_TEXT,
        font=hero_tag_font,
    )
    accent_y = y + hero_bottom + 6
    draw.rectangle(
        [PADDING, accent_y, PADDING + hero_w, accent_y + 5],
        fill=IMPORTANT_RING,
    )
    y += HERO_HEIGHT

    # ─── Title row ───────────────────────────────────────────────────────
    draw.text(
        (PADDING, y),
        "PNU CSE 마감 캘린더",
        fill=HEADER_TEXT_PRIMARY,
        font=title_font,
    )
    y += TITLE_HEIGHT - 20

    visible_count = sum(
        1
        for d in deadlines
        if any(d.date.startswith(m.strftime("%Y-%m")) for m in month_starts)
    )
    urgent_count = sum(
        1
        for d in deadlines
        if _safe_iso(d.date) is not None
        and 0 <= (_safe_iso(d.date) - today).days <= 3  # type: ignore[operator]
    )
    subtitle = (
        f"{today.isoformat()} · 마감 예정 {visible_count}건"
        + (f" · D-3 이내 {urgent_count}건" if urgent_count else "")
    )
    draw.text((PADDING, y), subtitle, fill=HEADER_TEXT_MUTED, font=subtitle_font)
    y += SUBTITLE_HEIGHT + 4

    helper = "※ 각 일정은 해당 날짜에 마감되는 공지입니다 (공지 게시일 아님)"
    draw.text(
        (PADDING, y), helper, fill=HEADER_TEXT_SECONDARY, font=subtitle_font,
    )
    y += HELPER_HEIGHT + 12

    bucketed = _deadlines_by_date(deadlines)

    # ─── Month blocks ────────────────────────────────────────────────────
    for i, (m_start, grid) in enumerate(zip(month_starts, month_grids, strict=True)):
        if i > 0:
            y += MONTH_GAP
        draw.text(
            (PADDING, y),
            f"{m_start.year}년 {m_start.month}월",
            fill=HEADER_TEXT_SECONDARY,
            font=month_font,
        )
        y += MONTH_HEADER_HEIGHT

        for col, label in enumerate(WEEKDAY_LABELS):
            x = PADDING + col * (cell_width + CELL_GAP)
            fill = SUNDAY_ACCENT if col == 6 else HEADER_TEXT_MUTED
            draw.text((x + 6, y + 6), label, fill=fill, font=weekday_font)
        y += WEEKDAY_ROW_HEIGHT

        for row_idx, week in enumerate(grid):
            for col, day in enumerate(week):
                x = PADDING + col * (cell_width + CELL_GAP)
                _draw_cell(
                    draw,
                    x,
                    y,
                    cell_width,
                    CELL_HEIGHT,
                    day=day,
                    today=today,
                    deadlines_for_day=(
                        bucketed.get(day.isoformat(), []) if day else []
                    ),
                    day_font=day_font,
                    chip_tag_font=chip_tag_font,
                    chip_title_font=chip_title_font,
                    is_sunday=(col == 6),
                )
            y += CELL_HEIGHT
            if row_idx < len(grid) - 1:
                y += CELL_GAP

    # ─── Legend ──────────────────────────────────────────────────────────
    y += 18
    legend_x = PADDING
    for category in LEGEND_CATEGORIES:
        chip_color = _chip_tag_color(category)
        short = _short_category(category)
        # Render a mini chip-tag pill so legend matches the cell visual.
        bbox = footer_font.getbbox(short)
        text_w = bbox[2] - bbox[0]
        pill_w = text_w + 14
        pill_h = 18
        draw.rounded_rectangle(
            [legend_x, y, legend_x + pill_w, y + pill_h],
            radius=3,
            fill=chip_color,
        )
        draw.text(
            (legend_x + 7, y + 2),
            short,
            fill=WHITE,
            font=footer_font,
        )
        label_x = legend_x + pill_w + 6
        draw.text(
            (label_x, y + 2), category, fill=HEADER_TEXT_SECONDARY, font=footer_font,
        )
        cat_bbox = footer_font.getbbox(category)
        legend_x = label_x + (cat_bbox[2] - cat_bbox[0]) + 18

    # Important marker
    star_label = "★ 중요 일정"
    draw.text(
        (legend_x, y + 2), star_label, fill=IMPORTANT_RING, font=footer_font,
    )

    # ─── Footer ──────────────────────────────────────────────────────────
    y += 24
    draw.text(
        (PADDING, y),
        "각 칸 = 해당 날짜에 마감되는 공지 · 웹 캘린더에서 자세히 보기 · 매일 18:00 갱신",
        fill=HEADER_TEXT_MUTED,
        font=footer_font,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    img.save(tmp, format="PNG", optimize=True)
    tmp.replace(output_path)


def _draw_cell(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    day: date | None,
    today: date,
    deadlines_for_day: list[TrackedDeadline],
    day_font: ImageFont.ImageFont,
    chip_tag_font: ImageFont.ImageFont,
    chip_title_font: ImageFont.ImageFont,
    is_sunday: bool,
) -> None:
    # Adjacent-month cell: leave dark canvas visible (matches web's faded
    # fc-day-other — no card, dim date number we skip entirely).
    if day is None:
        return

    # Card fill — soft tint when this day has urgent/due deadlines.
    card_fill = CARD_BG
    if deadlines_for_day:
        days_until = (day - today).days
        if days_until == 0:
            card_fill = DUE_CARD_BG
        elif 0 < days_until <= 3:
            card_fill = URGENT_CARD_BG

    if day == today:
        card_fill = TODAY_CARD_BG

    draw.rounded_rectangle(
        [x, y, x + width, y + height],
        radius=6,
        fill=card_fill,
        outline=CARD_BORDER,
        width=1,
    )

    # Today: stronger blue ring on top of tint
    if day == today:
        draw.rounded_rectangle(
            [x, y, x + width, y + height],
            radius=6,
            outline=TODAY_CARD_BORDER,
            width=2,
        )

    # Date number top-left
    day_color = TODAY_CARD_BORDER if day == today else (
        SUNDAY_ACCENT if is_sunday else CARD_TEXT_SECONDARY
    )
    draw.text((x + 8, y + 6), str(day.day), fill=day_color, font=day_font)

    # Event chips (max 2, then "+N"). Each event = chip-tag pill on line 1
    # followed by the title text, which wraps to a second line if needed.
    chip_y = y + 30
    visible = deadlines_for_day[:2]
    inner_left = x + 6
    inner_right = x + width - 6
    line_h = 14  # title line-height for 11px font
    for d in visible:
        chip_color = _chip_tag_color(d.category)
        short = _short_category(d.category)

        # chip-tag pill (colored, white text)
        tag_text_w = _text_w(chip_tag_font, short)
        tag_pill_w = tag_text_w + 12
        tag_pill_h = 16
        tag_x = inner_left
        draw.rounded_rectangle(
            [tag_x, chip_y, tag_x + tag_pill_w, chip_y + tag_pill_h],
            radius=3,
            fill=chip_color,
        )
        draw.text(
            (tag_x + 6, chip_y + 2),
            short,
            fill=WHITE,
            font=chip_tag_font,
        )

        # Title text — wraps to a second line if needed.
        title = _strip_prefix(d.title)
        if d.important:
            title = "★ " + title
        line1_max_w = inner_right - (tag_x + tag_pill_w + 6)
        line2_max_w = inner_right - inner_left
        lines = _wrap_two_lines(title, chip_title_font, line1_max_w, line2_max_w)

        draw.text(
            (tag_x + tag_pill_w + 6, chip_y + 2),
            lines[0],
            fill=CARD_TEXT,
            font=chip_title_font,
        )
        if len(lines) > 1 and lines[1]:
            draw.text(
                (inner_left, chip_y + tag_pill_h + 2),
                lines[1],
                fill=CARD_TEXT,
                font=chip_title_font,
            )

        # Important marker — gold underline under the chip-tag.
        if d.important:
            draw.line(
                [
                    (tag_x, chip_y + tag_pill_h + 1),
                    (tag_x + tag_pill_w, chip_y + tag_pill_h + 1),
                ],
                fill=IMPORTANT_RING,
                width=2,
            )

        # Advance y by tag_pill height + (line2 if present) + spacing.
        block_h = tag_pill_h + (line_h if len(lines) > 1 else 0) + 6
        chip_y += block_h

    overflow = len(deadlines_for_day) - len(visible)
    if overflow > 0:
        draw.text(
            (inner_left, chip_y),
            f"+ 외 {overflow}건",
            fill=CARD_TEXT_MUTED,
            font=chip_title_font,
        )


def _safe_iso(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None
