"""Data classes used across the bot."""
from __future__ import annotations

from dataclasses import dataclass


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
    webhook_env: str
    enabled: bool = True


@dataclass
class BoardState:
    last_max_post_id: int | None
    last_checked: str
    empty_streak: int = 0
