"""Snapshot-driven post cache for the v2 calendar.

Schema:
    {
      "schema_version": 1,
      "updated_at": ISO8601,
      "boards": {
        "<board_id>": {
          "posts": {
            "<post_id>": { ...PostCacheEntry... }
          }
        }
      }
    }

On corrupt JSON the file is moved aside as
``<name>.corrupt-<epoch>`` and an empty cache is returned — the next
cycle will rebuild from the list page.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from cse_bot._io import atomic_write_text, quarantine_corrupt
from cse_bot.models import PostCacheEntry

log = logging.getLogger(__name__)


@dataclass
class PostCache:
    schema_version: int = 1
    updated_at: str = ""
    boards: dict[str, dict[str, PostCacheEntry]] = field(default_factory=dict)


def load_post_cache(path: Path) -> PostCache:
    if not path.exists():
        return PostCache()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = quarantine_corrupt(path)
        log.warning("post_cache.corrupt path=%s backup=%s", path, backup)
        return PostCache()

    cache = PostCache(
        schema_version=int(raw.get("schema_version", 1)),
        updated_at=str(raw.get("updated_at", "")),
    )
    boards_raw = raw.get("boards", {}) if isinstance(raw, dict) else {}
    for board_id, board_entry in boards_raw.items():
        if not isinstance(board_entry, dict):
            continue
        posts_raw = board_entry.get("posts", {})
        if not isinstance(posts_raw, dict):
            continue
        posts: dict[str, PostCacheEntry] = {}
        for post_id, p in posts_raw.items():
            if not isinstance(p, dict):
                continue
            posts[str(post_id)] = PostCacheEntry(
                title=str(p.get("title", "")),
                url=str(p.get("url", "")),
                content_hash=str(p.get("content_hash", "")),
                summarized_at=str(p.get("summarized_at", "")),
                deadline=p.get("deadline") if p.get("deadline") else None,
                category=str(p.get("category", "")),
                summary=str(p.get("summary", "")),
                important=bool(p.get("important", False)),
                last_seen=str(p.get("last_seen", "")),
            )
        cache.boards[str(board_id)] = posts
    return cache


def save_post_cache(path: Path, cache: PostCache) -> None:
    payload = {
        "schema_version": cache.schema_version,
        "updated_at": cache.updated_at,
        "boards": {
            board_id: {
                "posts": {
                    post_id: {
                        "title": e.title,
                        "url": e.url,
                        "content_hash": e.content_hash,
                        "summarized_at": e.summarized_at,
                        "deadline": e.deadline,
                        "category": e.category,
                        "summary": e.summary,
                        "important": e.important,
                        "last_seen": e.last_seen,
                    }
                    for post_id, e in posts.items()
                }
            }
            for board_id, posts in cache.boards.items()
        },
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


_WHITESPACE_RE = re.compile(r"\s+")


def content_hash(body: str) -> str:
    """Return a stable sha256: prefixed hash of *body* after whitespace normalisation.

    ``article.extract_body`` already collapses whitespace, but we re-normalise
    defensively so the hash stays stable even if the parser changes.
    """
    normalised = _WHITESPACE_RE.sub(" ", body).strip()
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def prune_stale(cache: PostCache, board_id: str, *, now_iso: str, ttl_days: int) -> int:
    """Drop entries whose ``last_seen`` is older than ``ttl_days``.

    ISO timestamps are sortable as strings when normalised to the same
    timezone offset, so comparison stays O(n) and avoids parsing every
    entry. Returns the number of evicted entries.
    """
    if board_id not in cache.boards:
        return 0
    now = datetime.fromisoformat(now_iso)
    cutoff_iso = (now - timedelta(days=ttl_days)).isoformat()
    posts = cache.boards[board_id]
    removed = 0
    for post_id in list(posts.keys()):
        if posts[post_id].last_seen < cutoff_iso:
            log.info(
                "post_cache.evict board=%s post_id=%s reason=ttl",
                board_id, post_id,
            )
            del posts[post_id]
            removed += 1
    return removed
