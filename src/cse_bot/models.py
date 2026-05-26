"""Data classes used across the bot, plus tiny string helpers for their fields."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


def safe_iso_date(s: str) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` string, returning ``None`` on failure."""
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def strip_category_prefix(title: str) -> str:
    """Drop a leading ``[카테고리]`` tag so the display chip doesn't double up."""
    if title.startswith("[") and "]" in title:
        return title[title.index("]") + 1:].strip()
    return title


@dataclass(frozen=True)
class Post:
    id: int
    title: str
    author: str
    date: str
    url: str
    category: str
    has_attachment: bool


@dataclass(frozen=True)
class BoardConfig:
    id: str
    name: str
    url: str
    webhook_envs: list[str]
    enabled: bool = True


@dataclass
class TrackedDeadline:
    post_id: int
    title: str
    url: str
    date: str        # ISO YYYY-MM-DD
    reminded: bool = False
    category: str = ""   # 5대 분류 중 하나 (장학/등록, 학업/수강, 졸업/진로, 비교과/활동, 일반공지)
    summary: str = ""    # Gemini가 추출한 1~2문장 요약 (모달 미리보기용)
    important: bool = False  # 수강신청·국가장학금·대회·부트캠프·TOPCIT 등 중요 일정 강조


@dataclass
class BoardState:
    last_max_post_id: int | None
    last_checked: str
    empty_streak: int = 0
    deadlines: list[TrackedDeadline] = field(default_factory=list)


@dataclass
class PostCacheEntry:
    """One post's cached snapshot — last seen body hash + extracted fields."""
    title: str
    url: str
    content_hash: str
    summarized_at: str
    deadline: str | None
    category: str
    summary: str
    important: bool
    last_seen: str


@dataclass(frozen=True)
class ManualOverride:
    """Operator-supplied deadline entry. Wins over cache on URL collision."""
    id: str
    title: str
    url: str
    date: str
    category: str = ""
    important: bool = False
    added_at: str = ""
    added_by: str = ""
    expires_at: str | None = None
