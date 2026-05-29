"""Classify CSE announcement posts into 5 canonical categories.

Based on the classification analysis in
``docs/superpowers/specs/2026-05-26-discord-calendar-design.md``:
a study of 161 PNU CSE board posts established a 5-category schema that
covers ~88% of posts cleanly via prefix tags, with keyword fallback for
the rest.

The five canonical categories:

- ``장학/등록``  scholarships, registration, tuition
- ``학업/수강``  classes, registration, exams, academic records
- ``졸업/진로``  graduation requirements, jobs, internships
- ``비교과/활동``  extracurricular: bootcamps, contests, seminars
- ``일반공지``    fallback for everything else

A separate ``is_important`` predicate flags time-sensitive deadlines
(course registration, national scholarships, contests, bootcamps, TOPCIT,
…) for visual emphasis on both the calendar and the Discord image.
"""
from __future__ import annotations

import re

# ─── Canonical 5-category palette ────────────────────────────────────────

CATEGORY_SCHOLARSHIP = "장학/등록"
CATEGORY_ACADEMIC = "학업/수강"
CATEGORY_CAREER = "졸업/진로"
CATEGORY_ACTIVITY = "비교과/활동"
CATEGORY_GENERAL = "일반공지"

ALL_CATEGORIES: tuple[str, ...] = (
    CATEGORY_SCHOLARSHIP,
    CATEGORY_ACADEMIC,
    CATEGORY_CAREER,
    CATEGORY_ACTIVITY,
    CATEGORY_GENERAL,
)

CLASSIFICATION_PALETTE: dict[str, tuple[int, int, int]] = {
    CATEGORY_SCHOLARSHIP: (139, 92, 246),  # purple — 💰
    CATEGORY_ACADEMIC:    (20, 184, 166),  # teal   — 📚
    CATEGORY_CAREER:      (236, 72, 153),  # pink   — 🎓 / 💼
    CATEGORY_ACTIVITY:    (245, 158, 11),  # amber  — 🏆
    CATEGORY_GENERAL:     (107, 114, 128), # gray   — 📢
}

DEFAULT_COLOR: tuple[int, int, int] = CLASSIFICATION_PALETTE[CATEGORY_GENERAL]

# Darker chip variants so white text passes WCAG AA (≥ 4.5:1) against the
# pill background. Used by both the PNG renderer (`calendar_renderer`) and
# the Discord embed accent (`notifier`). Mirrored in docs/calendar/style.css.
CHIP_TAG_PALETTE: dict[str, tuple[int, int, int]] = {
    CATEGORY_SCHOLARSHIP: (109, 63, 207),   # #6d3fcf
    CATEGORY_ACADEMIC:    (13, 138, 126),   # #0d8a7e
    CATEGORY_CAREER:      (201, 58, 127),   # #c93a7f
    CATEGORY_ACTIVITY:    (201, 125, 5),    # #c97d05
    CATEGORY_GENERAL:     (75, 85, 99),     # #4b5563
}
CHIP_TAG_DEFAULT: tuple[int, int, int] = CHIP_TAG_PALETTE[CATEGORY_GENERAL]

# Short labels used inside chip pills (PNG renderer + web `metaFor` map).
CATEGORY_SHORT: dict[str, str] = {
    CATEGORY_SCHOLARSHIP: "장학",
    CATEGORY_ACADEMIC:    "학업",
    CATEGORY_CAREER:      "졸업",
    CATEGORY_ACTIVITY:    "비교과",
    CATEGORY_GENERAL:     "공지",
}

# ─── Prefix → category mapping ───────────────────────────────────────────

_PREFIX_TO_CATEGORY: dict[str, str] = {
    "장학": CATEGORY_SCHOLARSHIP,
    "등록": CATEGORY_SCHOLARSHIP,

    "수업": CATEGORY_ACADEMIC,
    "학적": CATEGORY_ACADEMIC,
    "입시": CATEGORY_ACADEMIC,
    "도서관": CATEGORY_ACADEMIC,
    "입학처": CATEGORY_ACADEMIC,

    "졸업": CATEGORY_CAREER,
    "졸업요건": CATEGORY_CAREER,
    "취업": CATEGORY_CAREER,
    "취업전략과": CATEGORY_CAREER,
    "대학일자리플러스센터": CATEGORY_CAREER,

    "AI융합교육원": CATEGORY_ACTIVITY,
    "SW중심대학": CATEGORY_ACTIVITY,
    "RISE": CATEGORY_ACTIVITY,
    "국립대육성": CATEGORY_ACTIVITY,
    "국립대학육성사업": CATEGORY_ACTIVITY,
    "공학교육혁신센터": CATEGORY_ACTIVITY,
    "학생과": CATEGORY_ACTIVITY,
    "모집": CATEGORY_ACTIVITY,
    "학과활동": CATEGORY_ACTIVITY,
    "국제협력실": CATEGORY_ACTIVITY,
}

# Keyword fallback — when prefix tag is missing or unrecognized.
# Order matters: each tuple is checked in turn, first match wins.
_KEYWORD_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CATEGORY_SCHOLARSHIP, (
        "장학생", "근로봉사", "등록금", "납부", "조교 모집",
    )),
    (CATEGORY_ACADEMIC, (
        "휴복학", "수강신청", "수강정정", "계절수업", "도약수업",
        "폐강", "고사", "학위수여", "졸업식", "입학식",
    )),
    (CATEGORY_CAREER, (
        "영어인증", "영어 능력", "TOPCIT", "토익",
        "채용", "인턴십", "인턴", "현직자", "추천채용",
    )),
    (CATEGORY_ACTIVITY, (
        "선발", "캠프", "봉사단", "경진대회", "공모전",
        "특강", "세미나", "프로젝트", "동아리", "부트캠프",
        "모집",  # fallback for unprefixed "모집" posts
    )),
)

# ─── Important deadline keywords ─────────────────────────────────────────

# Highlighted with a gold ring (PNG) / ★ prefix (web) — time-sensitive
# events students typically need to act on.
IMPORTANT_KEYWORDS: tuple[str, ...] = (
    "수강신청", "수강정정", "폐강",
    "국가장학금", "주거안정장학금",
    "TOPCIT", "토익", "영어인증", "졸업요건",
    "경진대회", "공모전", "대회",
    "부트캠프", "AI Booster", "Booster",
    "채용박람회",
    "등록금 납부", "등록금납부",
)


# ─── Regex helpers ───────────────────────────────────────────────────────

_PREFIX_RE = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]")


def extract_category(title: str) -> str:
    """Return the bracketed prefix from *title* (e.g. ``"장학"``), or empty.

    This is the raw tag — useful for display in 1-line bullets where the
    operator wrote ``[장학]``. For *classifying* a post into one of the
    five canonical categories, use :func:`classify` instead.
    """
    m = _PREFIX_RE.match(title)
    return m.group(1).strip() if m else ""


def classify(title: str) -> str:
    """Map *title* to one of the five canonical category names.

    Lookup order:
        1. Bracketed prefix → known prefix mapping
        2. Keyword scan over the rest of the title
        3. ``일반공지`` fallback
    """
    prefix = extract_category(title)
    if prefix in _PREFIX_TO_CATEGORY:
        return _PREFIX_TO_CATEGORY[prefix]

    # Strip the prefix bracket so it doesn't double-match in keyword scan.
    rest = _PREFIX_RE.sub("", title)
    for category, keywords in _KEYWORD_BUCKETS:
        for kw in keywords:
            if kw in rest:
                return category
    return CATEGORY_GENERAL


def is_important(title: str) -> bool:
    """True if the title contains any time-sensitive deadline keyword.

    Used to add visual emphasis (gold ring on PNG, ⭐ prefix on web) for
    events students typically need to act on.
    """
    return any(kw in title for kw in IMPORTANT_KEYWORDS)


def classification_to_color(category: str) -> tuple[int, int, int]:
    """Look up the RGB color for one of the five canonical categories."""
    return CLASSIFICATION_PALETTE.get(category, DEFAULT_COLOR)
