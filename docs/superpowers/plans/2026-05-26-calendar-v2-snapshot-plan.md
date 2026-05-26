# Calendar v2.0.0 Snapshot Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the calendar's `state.deadlines` incremental data source with a snapshot-driven `post_cache.json` + `manual_deadlines.json` pipeline so the published events.json always reflects current list-page state instead of accumulating stale data.

**Architecture:** A new `calendar_publisher` module owns the snapshot flow: for every cycle it walks the entire list page, content-hashes each article body, only invokes Gemini when the hash changes, prunes entries that haven't been seen for 30 days, and merges in operator-edited overrides. Notifier keeps its watermark-based incremental flow unchanged — both modules share the same list fetch but their state files are fully separated, so one failing does not block the other.

**Tech Stack:** Python 3.11+, dataclasses, pytest + respx + freezegun + monkeypatch, sha256 from hashlib, atomic JSON writes (tmp + replace), existing httpx/Gemini/Pillow chain.

**Spec reference:** `docs/superpowers/specs/2026-05-26-calendar-v2-snapshot-spec.md`

---

## File Structure

### Files to Create

| Path | Responsibility |
|---|---|
| `src/cse_bot/post_cache.py` | PostCache JSON I/O, content hashing, TTL prune |
| `src/cse_bot/manual_overrides.py` | manual_deadlines.json loader with schema validation |
| `src/cse_bot/calendar_publisher.py` | Snapshot-driven cache update + event list build |
| `scripts/migrate_to_v2.py` | One-off migration: state.deadlines → post_cache |
| `tests/test_post_cache.py` | Unit tests for cache I/O, hash stability, TTL prune |
| `tests/test_manual_overrides.py` | Loader + corrupt-file fallback tests |
| `tests/test_calendar_publisher.py` | Cache hit/miss/stub flow + merge tests |
| `tests/test_migrate_to_v2.py` | Migration script idempotence + content tests |

### Files to Modify

| Path | Change |
|---|---|
| `src/cse_bot/models.py` | Add `PostCacheEntry` and `ManualOverride` dataclasses |
| `src/cse_bot/config.py` | Add `cache_path`, `manual_overrides_path`, `cache_ttl_days` to `CalendarConfig` |
| `src/cse_bot/main.py` | Extract list fetch from `_process_board`, share posts with `calendar_publisher`, swap data source in `_emit_daily_digest` |
| `config/config.toml` | New keys under `[calendar]` |
| `tests/test_models.py` | New dataclass tests |
| `tests/test_config.py` | New calendar field tests |
| `tests/test_main_calendar.py` | Updated assertions for snapshot-driven path |

### Files to Delete

| Path | Reason |
|---|---|
| `scripts/backfill_deadlines.py` | Snapshot model makes the watermark-rewind workaround obsolete |

---

## Conventions

- All Korean log strings and error messages match the existing codebase style (`module.event key=value`).
- Tests use `tmp_path`, `monkeypatch`, `respx`, and `freezegun` per existing patterns in `tests/test_*.py`.
- `now()` always returns KST via `datetime.now(ZoneInfo("Asia/Seoul"))`. ISO format uses `isoformat()` (with seconds resolution to match `state.py`).
- JSON files are written atomically via `tmp = path.with_suffix(path.suffix + ".tmp"); tmp.write_text(...); tmp.replace(path)`.
- Korean characters are written with `ensure_ascii=False`.
- Run all tests with: `.venv/bin/python -m pytest -q`

---

## Task 1: Add PostCacheEntry and ManualOverride dataclasses

**Files:**
- Modify: `src/cse_bot/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_models.py`:

```python
def test_post_cache_entry_defaults():
    from cse_bot.models import PostCacheEntry
    e = PostCacheEntry(
        title="t", url="u", content_hash="sha256:abc",
        summarized_at="2026-05-26T23:00:00+09:00",
        deadline="2026-06-22", category="장학/등록",
        summary="s", important=True,
        last_seen="2026-05-26T23:00:00+09:00",
    )
    assert e.deadline == "2026-06-22"
    assert e.important is True


def test_post_cache_entry_nullable_deadline():
    from cse_bot.models import PostCacheEntry
    e = PostCacheEntry(
        title="t", url="u", content_hash="",
        summarized_at="", deadline=None, category="",
        summary="", important=False, last_seen="",
    )
    assert e.deadline is None


def test_manual_override_frozen():
    from cse_bot.models import ManualOverride
    o = ManualOverride(
        id="m-1", title="수강신청", url="https://x", date="2026-08-19",
    )
    assert o.category == ""
    assert o.important is False
    assert o.expires_at is None
    import dataclasses
    assert dataclasses.is_dataclass(o)
    # frozen dataclass — assignment should raise
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        o.title = "x"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_models.py -q`
Expected: 3 FAIL with `ImportError: cannot import name 'PostCacheEntry'` / `'ManualOverride'`.

- [ ] **Step 3: Add dataclasses to models.py**

Append to `src/cse_bot/models.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_models.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/models.py tests/test_models.py
git commit -m "feat(calendar): add PostCacheEntry and ManualOverride dataclasses"
```

---

## Task 2: post_cache.py — load/save with atomic write

**Files:**
- Create: `src/cse_bot/post_cache.py`
- Create: `tests/test_post_cache.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_post_cache.py`:

```python
"""Unit tests for the v2 post-snapshot cache."""
from __future__ import annotations

import json
from pathlib import Path

from cse_bot.models import PostCacheEntry
from cse_bot.post_cache import PostCache, load_post_cache, save_post_cache


def test_load_returns_empty_cache_when_file_missing(tmp_path: Path) -> None:
    cache = load_post_cache(tmp_path / "post_cache.json")
    assert cache.schema_version == 1
    assert cache.boards == {}


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "post_cache.json"
    cache = PostCache(schema_version=1, updated_at="2026-05-26T23:00:00+09:00")
    cache.boards["14221"] = {
        "1441380": PostCacheEntry(
            title="[장학] 주거안정장학금",
            url="https://cse.pusan.ac.kr/.../1441380",
            content_hash="sha256:abc",
            summarized_at="2026-05-26T23:00:00+09:00",
            deadline="2026-06-22",
            category="장학/등록",
            summary="요약",
            important=True,
            last_seen="2026-05-26T23:00:00+09:00",
        )
    }
    save_post_cache(path, cache)

    loaded = load_post_cache(path)
    assert "14221" in loaded.boards
    assert "1441380" in loaded.boards["14221"]
    entry = loaded.boards["14221"]["1441380"]
    assert entry.deadline == "2026-06-22"
    assert entry.important is True


def test_load_with_corrupt_json_backs_up_and_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "post_cache.json"
    path.write_text("{not valid", encoding="utf-8")
    cache = load_post_cache(path)
    assert cache.boards == {}
    backups = list(tmp_path.glob("post_cache.json.corrupt-*"))
    assert len(backups) == 1


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "post_cache.json"
    save_post_cache(path, PostCache())
    assert path.exists()


def test_saved_file_has_non_ascii_korean(tmp_path: Path) -> None:
    path = tmp_path / "post_cache.json"
    cache = PostCache()
    cache.boards["14221"] = {
        "1": PostCacheEntry(
            title="장학", url="u", content_hash="",
            summarized_at="", deadline=None,
            category="장학/등록", summary="요약",
            important=False, last_seen="",
        )
    }
    save_post_cache(path, cache)
    raw = path.read_text(encoding="utf-8")
    assert "장학" in raw  # not \uXXXX escaped
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_post_cache.py -q`
Expected: ImportError — `cse_bot.post_cache` does not yet exist.

- [ ] **Step 3: Create post_cache.py with load/save**

Create `src/cse_bot/post_cache.py`:

```python
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

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

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
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        shutil.move(str(path), backup)
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
    path.parent.mkdir(parents=True, exist_ok=True)
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
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_post_cache.py -q`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/post_cache.py tests/test_post_cache.py
git commit -m "feat(calendar): add PostCache load/save with atomic write + corrupt fallback"
```

---

## Task 3: post_cache.py — content_hash helper

**Files:**
- Modify: `src/cse_bot/post_cache.py`
- Modify: `tests/test_post_cache.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_post_cache.py`:

```python
def test_content_hash_is_stable_for_same_body():
    from cse_bot.post_cache import content_hash
    assert content_hash("hello world") == content_hash("hello world")


def test_content_hash_differs_for_different_body():
    from cse_bot.post_cache import content_hash
    assert content_hash("a") != content_hash("b")


def test_content_hash_prefix_is_sha256():
    from cse_bot.post_cache import content_hash
    h = content_hash("x")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64  # hex digest


def test_content_hash_normalises_whitespace():
    """Trailing whitespace and collapsed runs must not change the hash."""
    from cse_bot.post_cache import content_hash
    assert content_hash("hello   world") == content_hash("hello world")
    assert content_hash("hello world\n\n") == content_hash("hello world")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_post_cache.py -q`
Expected: 4 FAIL with `ImportError: cannot import name 'content_hash'`.

- [ ] **Step 3: Add content_hash function**

Append to `src/cse_bot/post_cache.py`:

```python
import hashlib
import re

_WHITESPACE_RE = re.compile(r"\s+")


def content_hash(body: str) -> str:
    """Return a stable sha256: prefixed hash of *body* after whitespace normalisation.

    ``article.extract_body`` already collapses whitespace, but we re-normalise
    defensively so the hash stays stable even if the parser changes.
    """
    normalised = _WHITESPACE_RE.sub(" ", body).strip()
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
```

Add `import hashlib` and `import re` near the existing imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_post_cache.py -q`
Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/post_cache.py tests/test_post_cache.py
git commit -m "feat(calendar): add content_hash helper with whitespace normalisation"
```

---

## Task 4: post_cache.py — prune_stale (TTL eviction)

**Files:**
- Modify: `src/cse_bot/post_cache.py`
- Modify: `tests/test_post_cache.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_post_cache.py`:

```python
def _entry(last_seen: str):
    return PostCacheEntry(
        title="t", url="u", content_hash="",
        summarized_at="", deadline="2026-12-31", category="",
        summary="", important=False, last_seen=last_seen,
    )


def test_prune_stale_removes_old_entries():
    from cse_bot.post_cache import PostCache, prune_stale
    cache = PostCache()
    cache.boards["14221"] = {
        "1": _entry("2026-04-01T00:00:00+09:00"),  # 55d old
        "2": _entry("2026-05-25T00:00:00+09:00"),  # 1d old
    }
    removed = prune_stale(cache, "14221", now_iso="2026-05-26T00:00:00+09:00", ttl_days=30)
    assert removed == 1
    assert "1" not in cache.boards["14221"]
    assert "2" in cache.boards["14221"]


def test_prune_stale_skips_unknown_board():
    from cse_bot.post_cache import PostCache, prune_stale
    cache = PostCache()
    removed = prune_stale(cache, "doesnotexist", now_iso="2026-05-26T00:00:00+09:00", ttl_days=30)
    assert removed == 0


def test_prune_stale_keeps_boundary_entry():
    """Entries exactly at the TTL boundary are NOT pruned (strict <)."""
    from cse_bot.post_cache import PostCache, prune_stale
    cache = PostCache()
    cache.boards["14221"] = {
        "1": _entry("2026-04-26T00:00:00+09:00"),  # exactly 30d
    }
    removed = prune_stale(cache, "14221", now_iso="2026-05-26T00:00:00+09:00", ttl_days=30)
    assert removed == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_post_cache.py -q`
Expected: 3 FAIL with `ImportError: cannot import name 'prune_stale'`.

- [ ] **Step 3: Add prune_stale function**

Append to `src/cse_bot/post_cache.py`:

```python
from datetime import datetime, timedelta


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_post_cache.py -q`
Expected: 12 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/post_cache.py tests/test_post_cache.py
git commit -m "feat(calendar): add TTL-based prune_stale to PostCache"
```

---

## Task 5: manual_overrides.py — load with schema fallback

**Files:**
- Create: `src/cse_bot/manual_overrides.py`
- Create: `tests/test_manual_overrides.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_manual_overrides.py`:

```python
"""Unit tests for operator-supplied calendar override loader."""
from __future__ import annotations

import json
from pathlib import Path

from cse_bot.manual_overrides import load_manual_overrides
from cse_bot.models import ManualOverride


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_load_returns_empty_when_file_missing(tmp_path: Path) -> None:
    assert load_manual_overrides(tmp_path / "manual.json") == []


def test_load_parses_valid_overrides(tmp_path: Path) -> None:
    path = tmp_path / "manual.json"
    _write(path, {
        "schema_version": 1,
        "overrides": [
            {
                "id": "m-1",
                "title": "수강신청",
                "url": "https://cse.pusan.ac.kr/...",
                "date": "2026-08-19",
                "category": "학업/수강",
                "important": True,
                "added_at": "2026-05-26T00:00:00+09:00",
                "added_by": "operator",
                "expires_at": None,
            }
        ],
    })
    overrides = load_manual_overrides(path)
    assert len(overrides) == 1
    o = overrides[0]
    assert isinstance(o, ManualOverride)
    assert o.id == "m-1"
    assert o.date == "2026-08-19"
    assert o.important is True


def test_load_returns_empty_on_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "manual.json"
    path.write_text("{not valid", encoding="utf-8")
    assert load_manual_overrides(path) == []


def test_load_skips_entries_missing_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "manual.json"
    _write(path, {
        "schema_version": 1,
        "overrides": [
            {"id": "ok", "title": "t", "url": "https://x", "date": "2026-08-19"},
            {"id": "bad-no-date", "title": "t", "url": "https://x"},
            {"id": "bad-no-url", "title": "t", "date": "2026-08-19"},
        ],
    })
    overrides = load_manual_overrides(path)
    assert [o.id for o in overrides] == ["ok"]


def test_load_uses_defaults_for_optional_fields(tmp_path: Path) -> None:
    path = tmp_path / "manual.json"
    _write(path, {
        "schema_version": 1,
        "overrides": [
            {"id": "m-1", "title": "t", "url": "https://x", "date": "2026-08-19"},
        ],
    })
    o = load_manual_overrides(path)[0]
    assert o.category == ""
    assert o.important is False
    assert o.expires_at is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_manual_overrides.py -q`
Expected: ImportError — module doesn't exist yet.

- [ ] **Step 3: Create manual_overrides.py**

Create `src/cse_bot/manual_overrides.py`:

```python
"""Load operator-supplied calendar overrides.

The file is optional: missing or malformed files return an empty list
so the calendar still publishes from the cache alone. Each entry must
have ``id``, ``title``, ``url`` and ``date``; everything else is
defaulted from :class:`ManualOverride`.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from cse_bot.models import ManualOverride

log = logging.getLogger(__name__)


def load_manual_overrides(path: Path) -> list[ManualOverride]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("manual_overrides.corrupt path=%s — ignoring", path)
        return []

    items = raw.get("overrides", []) if isinstance(raw, dict) else []
    overrides: list[ManualOverride] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        try:
            overrides.append(
                ManualOverride(
                    id=str(entry["id"]),
                    title=str(entry["title"]),
                    url=str(entry["url"]),
                    date=str(entry["date"]),
                    category=str(entry.get("category", "")),
                    important=bool(entry.get("important", False)),
                    added_at=str(entry.get("added_at", "")),
                    added_by=str(entry.get("added_by", "")),
                    expires_at=(
                        str(entry["expires_at"]) if entry.get("expires_at") else None
                    ),
                )
            )
        except KeyError as e:
            log.warning(
                "manual_overrides.skip_entry id=%s missing=%s",
                entry.get("id", "<?>"), e.args[0],
            )
    return overrides
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_manual_overrides.py -q`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/manual_overrides.py tests/test_manual_overrides.py
git commit -m "feat(calendar): add manual_overrides loader with schema fallback"
```

---

## Task 6: calendar_publisher.py — build_events (pure merge)

**Files:**
- Create: `src/cse_bot/calendar_publisher.py`
- Create: `tests/test_calendar_publisher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_calendar_publisher.py`:

```python
"""Unit tests for snapshot-driven calendar publisher."""
from __future__ import annotations

from datetime import date

from cse_bot.calendar_publisher import build_events
from cse_bot.models import ManualOverride, PostCacheEntry
from cse_bot.post_cache import PostCache


def _cache_with(*entries: tuple[str, str, str, str]) -> PostCache:
    """Helper: build a cache populated with (post_id, deadline, url, title) tuples."""
    cache = PostCache()
    posts: dict[str, PostCacheEntry] = {}
    for post_id, deadline, url, title in entries:
        posts[post_id] = PostCacheEntry(
            title=title, url=url, content_hash="",
            summarized_at="", deadline=deadline or None,
            category="장학/등록", summary="", important=False,
            last_seen="2026-05-26T00:00:00+09:00",
        )
    cache.boards["14221"] = posts
    return cache


def test_build_events_filters_past_deadlines():
    cache = _cache_with(
        ("1", "2026-04-01", "u1", "past"),
        ("2", "2026-06-01", "u2", "future"),
    )
    events = build_events(cache, [], today=date(2026, 5, 26))
    assert [e.post_id for e in events] == [2]


def test_build_events_skips_entries_without_deadline():
    cache = _cache_with(
        ("1", "", "u1", "no-deadline"),
        ("2", "2026-06-01", "u2", "future"),
    )
    events = build_events(cache, [], today=date(2026, 5, 26))
    assert [e.post_id for e in events] == [2]


def test_build_events_sorts_by_date_ascending():
    cache = _cache_with(
        ("1", "2026-08-01", "u1", "later"),
        ("2", "2026-06-01", "u2", "earlier"),
        ("3", "2026-07-01", "u3", "middle"),
    )
    events = build_events(cache, [], today=date(2026, 5, 26))
    assert [e.date for e in events] == ["2026-06-01", "2026-07-01", "2026-08-01"]


def test_build_events_appends_manual_overrides_with_new_urls():
    cache = _cache_with(("1", "2026-06-01", "u1", "cache"))
    overrides = [
        ManualOverride(id="m-1", title="manual", url="u-manual", date="2026-07-01"),
    ]
    events = build_events(cache, overrides, today=date(2026, 5, 26))
    titles = [e.title for e in events]
    assert "cache" in titles
    assert "manual" in titles


def test_build_events_manual_override_wins_on_url_match():
    """Override on same URL replaces date/category/important from cache."""
    cache = _cache_with(("1", "2026-06-01", "u-shared", "cache-title"))
    overrides = [
        ManualOverride(
            id="m-1", title="manual-title", url="u-shared",
            date="2026-07-15", category="비교과/활동", important=True,
        ),
    ]
    events = build_events(cache, overrides, today=date(2026, 5, 26))
    assert len(events) == 1
    ev = events[0]
    assert ev.date == "2026-07-15"
    assert ev.category == "비교과/활동"
    assert ev.important is True
    # title from cache is kept (only date/category/important are overridden)
    assert ev.title == "cache-title"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_calendar_publisher.py -q`
Expected: ImportError on `calendar_publisher`.

- [ ] **Step 3: Create calendar_publisher.py with build_events**

Create `src/cse_bot/calendar_publisher.py`:

```python
"""Snapshot-driven calendar pipeline (v2.0.0).

Replaces the watermark-driven ``state.deadlines`` flow with a cache that
mirrors the current list page. The cache, manual overrides, and event
list builder live here; the orchestrator ``run_calendar_publish``
composes them and is what ``main._emit_daily_digest`` calls.
"""
from __future__ import annotations

import logging
from datetime import date

from cse_bot.models import ManualOverride, TrackedDeadline
from cse_bot.post_cache import PostCache

log = logging.getLogger(__name__)


def build_events(
    cache: PostCache,
    overrides: list[ManualOverride],
    *,
    today: date,
) -> list[TrackedDeadline]:
    """Return future-dated events from *cache* merged with *overrides*.

    Manual overrides take precedence on URL collision: the cache entry's
    date / category / important fields are replaced by the override's
    values. Otherwise the override is appended as a fresh event.
    """
    events: list[TrackedDeadline] = []
    today_iso = today.isoformat()

    for board_id, posts in cache.boards.items():
        for post_id, entry in posts.items():
            dl = entry.deadline
            if not dl or dl < today_iso:
                continue
            try:
                pid_int = int(post_id)
            except ValueError:
                continue
            events.append(
                TrackedDeadline(
                    post_id=pid_int,
                    title=entry.title,
                    url=entry.url,
                    date=dl,
                    category=entry.category,
                    summary=entry.summary,
                    important=entry.important,
                )
            )

    # Manual overrides: same URL → patch fields; new URL → append.
    url_to_event: dict[str, TrackedDeadline] = {e.url: e for e in events}
    for ov in overrides:
        if ov.url in url_to_event:
            ev = url_to_event[ov.url]
            ev.date = ov.date
            if ov.category:
                ev.category = ov.category
            if ov.important:
                ev.important = ov.important
        else:
            events.append(
                TrackedDeadline(
                    post_id=0,
                    title=ov.title,
                    url=ov.url,
                    date=ov.date,
                    category=ov.category,
                    summary="",
                    important=ov.important,
                )
            )

    events.sort(key=lambda d: d.date)
    return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_calendar_publisher.py -q`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/calendar_publisher.py tests/test_calendar_publisher.py
git commit -m "feat(calendar): add build_events merge for cache + manual overrides"
```

---

## Task 7: calendar_publisher.py — update_cache_from_snapshot

**Files:**
- Modify: `src/cse_bot/calendar_publisher.py`
- Modify: `tests/test_calendar_publisher.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_calendar_publisher.py`:

```python
from cse_bot.article import ArticleContent
from cse_bot.calendar_publisher import update_cache_from_snapshot
from cse_bot.models import Post
from cse_bot.summarizer import SummaryResult


def _post(pid: int, title: str = "[장학] t") -> Post:
    return Post(
        id=pid, title=title, author="", date="2026-05-26",
        url=f"https://cse.pusan.ac.kr/.../{pid}",
        category="", has_attachment=False,
    )


def test_update_cache_miss_calls_summarize_and_inserts():
    cache = PostCache()
    calls: list[tuple[str, list[str]]] = []

    def fake_fetch(url):
        return ArticleContent(body="hello", image_urls=[])

    def fake_summarize(body, image_urls):
        calls.append((body, image_urls))
        return SummaryResult(summary="long", deadline="2026-06-22", short_summary="short")

    update_cache_from_snapshot(
        cache, "14221", [_post(1441380)],
        now_iso="2026-05-26T23:00:00+09:00",
        fetch_body=fake_fetch,
        summarize_fn=fake_summarize,
    )
    assert len(calls) == 1
    entry = cache.boards["14221"]["1441380"]
    assert entry.deadline == "2026-06-22"
    assert entry.summary == "short"


def test_update_cache_hit_skips_summarize():
    """If content_hash matches the cached value, summarize is NOT called."""
    from cse_bot.post_cache import content_hash
    body = "stable body"
    cache = PostCache()
    cache.boards["14221"] = {
        "100": PostCacheEntry(
            title="cached", url="https://x/100", content_hash=content_hash(body),
            summarized_at="2026-05-01T00:00:00+09:00",
            deadline="2026-06-22", category="장학/등록",
            summary="cached", important=False,
            last_seen="2026-05-01T00:00:00+09:00",
        )
    }
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return ArticleContent(body=body, image_urls=[])

    summarized = []

    def fake_summarize(body, image_urls):
        summarized.append(body)
        raise AssertionError("summarize should not be called on cache hit")

    update_cache_from_snapshot(
        cache, "14221",
        [Post(id=100, title="t", author="", date="", url="https://x/100",
              category="", has_attachment=False)],
        now_iso="2026-05-26T23:00:00+09:00",
        fetch_body=fake_fetch,
        summarize_fn=fake_summarize,
    )
    assert summarized == []
    # last_seen bumped to the current cycle
    assert cache.boards["14221"]["100"].last_seen == "2026-05-26T23:00:00+09:00"


def test_update_cache_changed_body_triggers_resummarize():
    from cse_bot.post_cache import content_hash
    cache = PostCache()
    cache.boards["14221"] = {
        "100": PostCacheEntry(
            title="cached", url="https://x/100",
            content_hash=content_hash("OLD body"),
            summarized_at="2026-05-01T00:00:00+09:00",
            deadline="2026-06-22", category="",
            summary="", important=False, last_seen="",
        )
    }
    fetched_body = "NEW body"

    def fake_fetch(url):
        return ArticleContent(body=fetched_body, image_urls=[])

    def fake_summarize(body, image_urls):
        assert body == fetched_body
        return SummaryResult(summary="long", deadline="2026-07-01", short_summary="updated")

    update_cache_from_snapshot(
        cache, "14221",
        [Post(id=100, title="t", author="", date="", url="https://x/100",
              category="", has_attachment=False)],
        now_iso="2026-05-26T23:00:00+09:00",
        fetch_body=fake_fetch,
        summarize_fn=fake_summarize,
    )
    entry = cache.boards["14221"]["100"]
    assert entry.deadline == "2026-07-01"
    assert entry.summary == "updated"
    assert entry.content_hash == content_hash(fetched_body)


def test_update_cache_fetch_failure_bumps_last_seen_but_keeps_entry():
    cache = PostCache()
    cache.boards["14221"] = {
        "100": PostCacheEntry(
            title="cached", url="https://x/100", content_hash="sha256:old",
            summarized_at="2026-05-01T00:00:00+09:00",
            deadline="2026-06-22", category="장학/등록",
            summary="cached", important=False,
            last_seen="2026-05-01T00:00:00+09:00",
        )
    }

    def fake_fetch(url):
        return None

    def fake_summarize(body, image_urls):
        raise AssertionError("should not be called when fetch fails")

    update_cache_from_snapshot(
        cache, "14221",
        [Post(id=100, title="t", author="", date="", url="https://x/100",
              category="", has_attachment=False)],
        now_iso="2026-05-26T23:00:00+09:00",
        fetch_body=fake_fetch,
        summarize_fn=fake_summarize,
    )
    entry = cache.boards["14221"]["100"]
    assert entry.deadline == "2026-06-22"  # preserved
    assert entry.last_seen == "2026-05-26T23:00:00+09:00"  # bumped


def test_update_cache_summarize_failure_creates_stub_when_no_prior_entry():
    cache = PostCache()

    def fake_fetch(url):
        return ArticleContent(body="hello", image_urls=[])

    def fake_summarize(body, image_urls):
        return None

    update_cache_from_snapshot(
        cache, "14221", [_post(999)],
        now_iso="2026-05-26T23:00:00+09:00",
        fetch_body=fake_fetch,
        summarize_fn=fake_summarize,
    )
    # Stub entry exists with deadline=None so we don't keep summarising it
    entry = cache.boards["14221"]["999"]
    assert entry.deadline is None
    assert entry.title == "[장학] t"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_calendar_publisher.py -q`
Expected: ImportError on `update_cache_from_snapshot`.

- [ ] **Step 3: Implement update_cache_from_snapshot**

Append to `src/cse_bot/calendar_publisher.py`:

```python
from collections.abc import Callable

from cse_bot.article import ArticleContent
from cse_bot.category import classify, is_important
from cse_bot.models import Post, PostCacheEntry
from cse_bot.post_cache import content_hash
from cse_bot.summarizer import SummaryResult

FetchFn = Callable[[str], ArticleContent | None]
SummarizeFn = Callable[[str, list[str]], SummaryResult | None]


def update_cache_from_snapshot(
    cache: PostCache,
    board_id: str,
    posts_in_list: list[Post],
    *,
    now_iso: str,
    fetch_body: FetchFn,
    summarize_fn: SummarizeFn,
) -> None:
    """Update *cache* in place to match the current list-page snapshot.

    Per post:

    1. Bump ``last_seen`` so a transient fetch failure does not trigger
       TTL eviction.
    2. Fetch the article body. On failure, keep the existing cache entry
       and move on.
    3. Compare ``content_hash`` against the cached value. On match, skip
       Gemini entirely — that is the warm-cache path.
    4. On cache miss or content change, call ``summarize_fn``. If it
       returns ``None``, keep the previous cache entry (or write a stub
       so we don't re-summarise an unsummarisable post each cycle).
    """
    posts = cache.boards.setdefault(board_id, {})

    for post in posts_in_list:
        key = str(post.id)
        cached = posts.get(key)
        if cached is not None:
            cached.last_seen = now_iso

        content = fetch_body(post.url)
        if content is None:
            log.warning("calendar.fetch_failed post_id=%d", post.id)
            continue

        new_hash = content_hash(content.body)
        if cached is not None and cached.content_hash == new_hash:
            continue  # warm cache — already bumped last_seen

        result = summarize_fn(content.body, list(content.image_urls))
        if result is None:
            if cached is None:
                # Stub so we don't try to summarise this post every cycle.
                posts[key] = PostCacheEntry(
                    title=post.title,
                    url=post.url,
                    content_hash=new_hash,
                    summarized_at="",
                    deadline=None,
                    category=classify(post.title),
                    summary="",
                    important=is_important(post.title),
                    last_seen=now_iso,
                )
            else:
                # Keep prior cache values; just refresh the hash so we don't loop.
                cached.content_hash = new_hash
            continue

        posts[key] = PostCacheEntry(
            title=post.title,
            url=post.url,
            content_hash=new_hash,
            summarized_at=now_iso,
            deadline=result.deadline,
            category=classify(post.title),
            summary=result.short_summary or result.summary,
            important=is_important(post.title),
            last_seen=now_iso,
        )
        log.info(
            "calendar.cache_update board=%s post_id=%d deadline=%s",
            board_id, post.id, result.deadline or "none",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_calendar_publisher.py -q`
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/calendar_publisher.py tests/test_calendar_publisher.py
git commit -m "feat(calendar): add update_cache_from_snapshot with hit/miss/stub logic"
```

---

## Task 8: calendar_publisher.py — run_calendar_publish orchestrator

**Files:**
- Modify: `src/cse_bot/calendar_publisher.py`
- Modify: `tests/test_calendar_publisher.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_calendar_publisher.py`:

```python
def test_run_calendar_publish_creates_cache_and_returns_events(tmp_path, monkeypatch):
    """End-to-end-ish: feed a list, get events back, find cache on disk."""
    from cse_bot.calendar_publisher import run_calendar_publish

    # Stub article + summarizer so we don't hit the network.
    def fake_fetch(url, *, timeout, retries):
        return ArticleContent(body=f"body for {url}", image_urls=[])

    def fake_summarize(body, *, image_urls, api_key, model, timeout):
        return SummaryResult(summary="long", deadline="2026-06-22", short_summary="short")

    monkeypatch.setattr(
        "cse_bot.calendar_publisher.article.fetch_article_content", fake_fetch,
    )
    monkeypatch.setattr(
        "cse_bot.calendar_publisher.summarizer.summarize", fake_summarize,
    )

    cache_path = tmp_path / "post_cache.json"
    manual_path = tmp_path / "manual.json"

    events = run_calendar_publish(
        board_id="14221",
        posts_in_list=[_post(1441380, title="[장학] t1"), _post(1441381, title="[장학] t2")],
        today=date(2026, 5, 26),
        now_iso="2026-05-26T23:00:00+09:00",
        cache_path=cache_path,
        manual_path=manual_path,
        ttl_days=30,
        gemini_api_key="k",
        gemini_model="m",
        gemini_timeout=10,
        http_timeout=5,
        http_retries=2,
    )

    assert {e.post_id for e in events} == {1441380, 1441381}
    assert cache_path.exists()


def test_run_calendar_publish_warm_cache_does_not_call_gemini(tmp_path, monkeypatch):
    """Second invocation with same body must not call summarize."""
    from cse_bot.calendar_publisher import run_calendar_publish
    from cse_bot.post_cache import content_hash, load_post_cache, save_post_cache

    cache_path = tmp_path / "post_cache.json"
    manual_path = tmp_path / "manual.json"

    body = "stable body"
    cache = PostCache()
    cache.boards["14221"] = {
        "100": PostCacheEntry(
            title="t", url="https://x/100",
            content_hash=content_hash(body),
            summarized_at="2026-05-01T00:00:00+09:00",
            deadline="2026-06-22", category="장학/등록",
            summary="s", important=False,
            last_seen="2026-05-01T00:00:00+09:00",
        )
    }
    save_post_cache(cache_path, cache)

    def fake_fetch(url, *, timeout, retries):
        return ArticleContent(body=body, image_urls=[])

    summarise_calls: list[str] = []

    def fake_summarize(body, *, image_urls, api_key, model, timeout):
        summarise_calls.append(body)
        raise AssertionError("warm cache should skip summarise")

    monkeypatch.setattr(
        "cse_bot.calendar_publisher.article.fetch_article_content", fake_fetch,
    )
    monkeypatch.setattr(
        "cse_bot.calendar_publisher.summarizer.summarize", fake_summarize,
    )

    events = run_calendar_publish(
        board_id="14221",
        posts_in_list=[Post(id=100, title="t", author="", date="", url="https://x/100",
                            category="", has_attachment=False)],
        today=date(2026, 5, 26),
        now_iso="2026-05-26T23:00:00+09:00",
        cache_path=cache_path,
        manual_path=manual_path,
        ttl_days=30,
        gemini_api_key="k", gemini_model="m", gemini_timeout=10,
        http_timeout=5, http_retries=2,
    )
    assert summarise_calls == []
    assert len(events) == 1
    assert events[0].date == "2026-06-22"


def test_run_calendar_publish_prunes_stale_entries(tmp_path, monkeypatch):
    """Entries with last_seen older than ttl_days are evicted."""
    from cse_bot.calendar_publisher import run_calendar_publish
    from cse_bot.post_cache import load_post_cache, save_post_cache

    cache_path = tmp_path / "post_cache.json"
    manual_path = tmp_path / "manual.json"

    cache = PostCache()
    cache.boards["14221"] = {
        "old": PostCacheEntry(
            title="old", url="https://x/old", content_hash="",
            summarized_at="", deadline="2026-12-31", category="",
            summary="", important=False,
            last_seen="2026-04-01T00:00:00+09:00",  # 55 days old
        )
    }
    save_post_cache(cache_path, cache)

    monkeypatch.setattr(
        "cse_bot.calendar_publisher.article.fetch_article_content",
        lambda url, *, timeout, retries: None,
    )

    run_calendar_publish(
        board_id="14221",
        posts_in_list=[],  # "old" no longer on list page
        today=date(2026, 5, 26),
        now_iso="2026-05-26T00:00:00+09:00",
        cache_path=cache_path,
        manual_path=manual_path,
        ttl_days=30,
        gemini_api_key="k", gemini_model="m", gemini_timeout=10,
        http_timeout=5, http_retries=2,
    )
    loaded = load_post_cache(cache_path)
    assert "old" not in loaded.boards.get("14221", {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_calendar_publisher.py -q`
Expected: ImportError on `run_calendar_publish`.

- [ ] **Step 3: Implement run_calendar_publish**

Append to `src/cse_bot/calendar_publisher.py`:

```python
from pathlib import Path

from cse_bot import article, summarizer
from cse_bot.manual_overrides import load_manual_overrides
from cse_bot.post_cache import (
    PostCache, load_post_cache, prune_stale, save_post_cache,
)


def run_calendar_publish(
    *,
    board_id: str,
    posts_in_list: list[Post],
    today: date,
    now_iso: str,
    cache_path: Path,
    manual_path: Path,
    ttl_days: int,
    gemini_api_key: str,
    gemini_model: str,
    gemini_timeout: float,
    http_timeout: float,
    http_retries: int,
) -> list[TrackedDeadline]:
    """Refresh the snapshot cache for *board_id* and return active events.

    Keyword-only API so the orchestrator (``main._emit_daily_digest``)
    passes config explicitly instead of importing :mod:`Config` here,
    keeping this module independent of the wider TOML schema.
    """
    cache = load_post_cache(cache_path)

    def _fetch_body(url: str):
        return article.fetch_article_content(
            url, timeout=http_timeout, retries=http_retries,
        )

    def _summarize(body: str, image_urls: list[str]):
        return summarizer.summarize(
            body,
            image_urls=image_urls,
            api_key=gemini_api_key,
            model=gemini_model,
            timeout=gemini_timeout,
        )

    update_cache_from_snapshot(
        cache, board_id, posts_in_list,
        now_iso=now_iso,
        fetch_body=_fetch_body,
        summarize_fn=_summarize,
    )

    pruned = prune_stale(cache, board_id, now_iso=now_iso, ttl_days=ttl_days)
    if pruned:
        log.info("calendar.cache_pruned board=%s count=%d", board_id, pruned)

    cache.updated_at = now_iso
    save_post_cache(cache_path, cache)

    overrides = load_manual_overrides(manual_path)
    return build_events(cache, overrides, today=today)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_calendar_publisher.py -q`
Expected: 13 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/calendar_publisher.py tests/test_calendar_publisher.py
git commit -m "feat(calendar): add run_calendar_publish orchestrator with TTL + merge"
```

---

## Task 9: Config — add cache_path / manual_overrides_path / cache_ttl_days

**Files:**
- Modify: `src/cse_bot/config.py`
- Modify: `tests/test_config.py`
- Modify: `config/config.toml`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_config.py`:

```python
def test_calendar_config_has_v2_cache_paths(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("""
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 1
http_timeout_seconds = 5
http_retries = 1

[notification]
format = "medium"
self_alert_webhook_env = "WH_ALERT"

[gemini]
api_key_env = "GEMINI_API_KEY"
model = "m"
timeout_seconds = 10

[calendar]
enabled = true
output_dir = "docs/calendar"
site_url = "https://example.com"
months_in_png = 2
cache_path = "data/post_cache.json"
manual_overrides_path = "data/manual_deadlines.json"
cache_ttl_days = 30

[[boards]]
id = "14221"
name = "x"
url = "https://x"
webhook_envs = ["WH_GEN"]
enabled = true
""", encoding="utf-8")
    monkeypatch.setenv("WH_GEN", "https://discord/x")
    monkeypatch.setenv("WH_ALERT", "https://discord/a")
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    from cse_bot.config import load_config
    cfg = load_config(cfg_path)
    assert cfg.calendar.cache_path == "data/post_cache.json"
    assert cfg.calendar.manual_overrides_path == "data/manual_deadlines.json"
    assert cfg.calendar.cache_ttl_days == 30


def test_calendar_config_defaults_when_v2_keys_missing(tmp_path: Path, monkeypatch):
    """Old configs without v2 keys still load (with sensible defaults)."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("""
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 1
http_timeout_seconds = 5
http_retries = 1

[notification]
format = "medium"
self_alert_webhook_env = "WH_ALERT"

[gemini]
api_key_env = "GEMINI_API_KEY"
model = "m"
timeout_seconds = 10

[calendar]
enabled = true
output_dir = "docs/calendar"
site_url = "https://example.com"
months_in_png = 2

[[boards]]
id = "14221"
name = "x"
url = "https://x"
webhook_envs = ["WH_GEN"]
enabled = true
""", encoding="utf-8")
    monkeypatch.setenv("WH_GEN", "https://discord/x")
    monkeypatch.setenv("WH_ALERT", "https://discord/a")
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    from cse_bot.config import load_config
    cfg = load_config(cfg_path)
    assert cfg.calendar.cache_path == "data/post_cache.json"
    assert cfg.calendar.manual_overrides_path == "data/manual_deadlines.json"
    assert cfg.calendar.cache_ttl_days == 30
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_calendar_config_has_v2_cache_paths tests/test_config.py::test_calendar_config_defaults_when_v2_keys_missing -q`
Expected: 2 FAIL with `AttributeError: 'CalendarConfig' object has no attribute 'cache_path'`.

- [ ] **Step 3: Extend CalendarConfig**

In `src/cse_bot/config.py`, replace the `CalendarConfig` dataclass and `_load_calendar`:

```python
@dataclass(frozen=True)
class CalendarConfig:
    enabled: bool
    output_dir: str
    site_url: str
    months_in_png: int
    font_path: str | None
    cache_path: str
    manual_overrides_path: str
    cache_ttl_days: int


def _load_calendar(raw: dict[str, Any]) -> CalendarConfig:
    section = raw.get("calendar")
    if section is None:
        return CalendarConfig(
            enabled=False,
            output_dir="docs/calendar",
            site_url="",
            months_in_png=2,
            font_path=None,
            cache_path="data/post_cache.json",
            manual_overrides_path="data/manual_deadlines.json",
            cache_ttl_days=30,
        )
    c: dict[str, Any] = section
    enabled = bool(c.get("enabled", True))
    output_dir = str(c.get("output_dir", "docs/calendar"))
    site_url = str(c.get("site_url", "")).rstrip("/")
    if enabled and not site_url:
        raise ConfigError("[calendar].site_url is required when calendar.enabled = true")
    months_in_png = int(c.get("months_in_png", 2))
    if months_in_png < 1 or months_in_png > 6:
        raise ConfigError("[calendar].months_in_png must be between 1 and 6")
    font_path_raw = c.get("font_path")
    font_path = str(font_path_raw) if font_path_raw else None
    cache_path = str(c.get("cache_path", "data/post_cache.json"))
    manual_overrides_path = str(
        c.get("manual_overrides_path", "data/manual_deadlines.json")
    )
    cache_ttl_days = int(c.get("cache_ttl_days", 30))
    if cache_ttl_days < 1:
        raise ConfigError("[calendar].cache_ttl_days must be >= 1")
    return CalendarConfig(
        enabled=enabled,
        output_dir=output_dir,
        site_url=site_url,
        months_in_png=months_in_png,
        font_path=font_path,
        cache_path=cache_path,
        manual_overrides_path=manual_overrides_path,
        cache_ttl_days=cache_ttl_days,
    )
```

- [ ] **Step 4: Update config/config.toml**

Two edits to `config/config.toml`:

(a) Bump list-page coverage in `[general]` from 2 → 3 pages so long-running non-sticky posts have more time to stay tracked before the 30-day TTL kicks in:

```toml
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 3
http_timeout_seconds = 15
http_retries = 3
```

(b) Replace the `[calendar]` section with the v2 keys:

```toml
[calendar]
enabled = true
output_dir = "docs/calendar"
site_url = "https://7bellaa.github.io/cse-notice-bot/calendar"
months_in_png = 2
font_path = "assets/fonts/Pretendard-Medium.ttf"
cache_path = "data/post_cache.json"
manual_overrides_path = "data/manual_deadlines.json"
cache_ttl_days = 30
```

The `max_pages = 3` choice is deliberate: most PNU CSE deadlines are
2–6 weeks out and posts stay on pages 1–2 for 4–8 weeks, so 3 pages of
coverage gives a comfortable safety margin without doubling the
per-cycle fetch cost. Sticky posts (졸업요건·영어인증·필독 공지) are
unaffected either way — the board pins them onto every page.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cse_bot/config.py tests/test_config.py config/config.toml
git commit -m "feat(calendar): wire v2 cache config + bump max_pages to 3"
```

---

## Task 10: main.py — share list fetch and call calendar_publisher

**Files:**
- Modify: `src/cse_bot/main.py`
- Modify: `tests/test_main_calendar.py`

This task replaces the data source of `_emit_daily_digest` from `state.deadlines` to `calendar_publisher.run_calendar_publish`. The notifier flow (`_process_board`) stays — only its return shape changes so the digest can reuse its already-fetched list.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_main_calendar.py`:

```python
@respx.mock
def test_v2_digest_writes_post_cache_with_list_snapshot(
    cfg_file: Path, tmp_path: Path
) -> None:
    """After a cycle, data/post_cache.json must contain an entry per list-page post."""
    _seed_state(tmp_path / "state.json", last_max=19234)

    # 3 posts on the list page — only 19235/19236 are above the watermark
    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(200, text=_html_with_posts([19236, 19235, 19234]))
    )
    # Articles for ALL 3 (calendar inspects every list-page post)
    article_html = (
        "<html><body><div class='board-view'><div class='txt'>"
        "본문 — 마감일은 2026-12-31</div></div></body></html>"
    )
    respx.get(host="cse.pusan.ac.kr", path__startswith="/cse/14221/artclView.do").mock(
        return_value=httpx.Response(200, text=article_html)
    )
    # Gemini call — return the deadline
    respx.post(host="generativelanguage.googleapis.com").mock(
        return_value=httpx.Response(200, json={
            "candidates": [{
                "content": {"parts": [{"text": (
                    '{"summary": "본문 요약", '
                    '"short_summary": "12월 31일 마감", '
                    '"deadline": "2026-12-31"}'
                )}]}
            }]
        })
    )
    respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0

    # post_cache.json should exist and contain all 3 list-page posts
    cache_path = tmp_path / "post_cache.json"
    assert cache_path.exists()
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    posts = cache["boards"]["14221"]["posts"]
    assert set(posts.keys()) == {"19234", "19235", "19236"}
    assert posts["19234"]["deadline"] == "2026-12-31"


@respx.mock
def test_v2_warm_cache_skips_gemini_calls(
    cfg_file: Path, tmp_path: Path
) -> None:
    """With a pre-populated cache whose content_hash matches, Gemini is not called."""
    from cse_bot.post_cache import PostCache, content_hash, save_post_cache
    from cse_bot.models import PostCacheEntry

    _seed_state(tmp_path / "state.json", last_max=19236)

    body = "본문 — 마감일은 2026-12-31"
    article_html = (
        f"<html><body><div class='board-view'><div class='txt'>{body}</div></div></body></html>"
    )
    cache = PostCache()
    cache.boards["14221"] = {
        "19235": PostCacheEntry(
            title="[장학] 제목 19235", url="https://cse.pusan.ac.kr/cse/14221/artclView.do?articleNo=19235",
            content_hash=content_hash(body),
            summarized_at="2026-05-01T00:00:00+09:00",
            deadline="2026-12-31", category="장학/등록",
            summary="cached", important=False,
            last_seen="2026-05-25T00:00:00+09:00",
        )
    }
    save_post_cache(tmp_path / "post_cache.json", cache)

    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(200, text=_html_with_posts([19235]))
    )
    respx.get(host="cse.pusan.ac.kr", path__startswith="/cse/14221/artclView.do").mock(
        return_value=httpx.Response(200, text=article_html)
    )
    gemini_route = respx.post(host="generativelanguage.googleapis.com").mock(
        return_value=httpx.Response(200, json={
            "candidates": [{
                "content": {"parts": [{"text": '{"summary": "x"}'}]}
            }]
        })
    )
    respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    assert gemini_route.call_count == 0  # warm cache hit


@respx.mock
def test_v2_manual_overrides_appear_in_events_json(
    cfg_file: Path, tmp_path: Path
) -> None:
    """A manual_deadlines.json entry shows up in events.json even with empty cache."""
    _seed_state(tmp_path / "state.json", last_max=19234)

    (tmp_path / "manual_deadlines.json").write_text(
        json.dumps({
            "schema_version": 1,
            "overrides": [
                {
                    "id": "m-1",
                    "title": "수강신청 (1·2학년)",
                    "url": "https://cse.pusan.ac.kr/manual-1",
                    "date": "2026-08-19",
                    "category": "학업/수강",
                    "important": True,
                },
            ],
        }),
        encoding="utf-8",
    )

    # List is empty — only the manual override should surface
    respx.get(BOARD_URL).mock(return_value=httpx.Response(200, text=_html_with_posts([])))
    respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    events = json.loads(
        (tmp_path / "docs/calendar/events.json").read_text(encoding="utf-8")
    )
    titles = [e["title"] for e in events]
    assert "수강신청 (1·2학년)" in titles
```

Also update `cfg_file` fixture to point at the per-test cache and manual paths:

```python
# ...inside cfg_file fixture, add to [calendar] section:
cache_path = "{tmp_path / 'post_cache.json'}"
manual_overrides_path = "{tmp_path / 'manual_deadlines.json'}"
cache_ttl_days = 30
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_main_calendar.py -q`
Expected: failures around missing cache file and the new flow.

- [ ] **Step 3: Refactor _process_board to return the full list**

Edit `src/cse_bot/main.py`. Change `_process_board` signature to also return the full list of fetched posts and update `run_cycle`:

```python
# In _process_board, replace the trailing return with:
return posts, new_posts, summaries
```

Update the type annotation:

```python
def _process_board(
    board: BoardConfig,
    cfg: Config,
    state_map: dict[str, BoardState],
    state_path: Path,
    *,
    today: date,
) -> tuple[list[Post], list[Post], dict[int, str]]:
```

Also update the early-return for empty posts: `return [], [], {}`. And the baseline path: `return posts, [], {}` (so the calendar still sees the snapshot on the first cycle).

Update `run_cycle` to collect the new tuple shape:

```python
per_board_full: list[
    tuple[BoardConfig, list[Post], list[Post], dict[int, str]]
] = []
for board in cfg.boards:
    ...
    posts, new_posts, summaries = _process_board(
        board, cfg, state_map, state_path, today=today,
    )
    per_board_full.append((board, posts, new_posts, summaries))
```

And pass it onward:

```python
_emit_daily_digest(
    cfg, state_map, per_board_full,
    today=today, project_root=project_root,
)
```

- [ ] **Step 4: Rewrite _emit_daily_digest to call calendar_publisher**

Replace the body of `_emit_daily_digest` with:

```python
def _emit_daily_digest(
    cfg: Config,
    state_map: dict[str, BoardState],
    per_board_full: list[
        tuple[BoardConfig, list[Post], list[Post], dict[int, str]]
    ],
    *,
    today: date,
    project_root: Path,
) -> None:
    """Update snapshot cache, render calendar, send a single digest message."""
    from cse_bot import calendar_publisher

    now_iso = datetime.now(KST).isoformat(timespec="seconds")

    cache_path = project_root / cfg.calendar.cache_path
    manual_path = project_root / cfg.calendar.manual_overrides_path

    all_events: list[TrackedDeadline] = []
    for board, posts, _new_posts, _summaries in per_board_full:
        if not board.enabled:
            continue
        events = calendar_publisher.run_calendar_publish(
            board_id=board.id,
            posts_in_list=posts,
            today=today,
            now_iso=now_iso,
            cache_path=cache_path,
            manual_path=manual_path,
            ttl_days=cfg.calendar.cache_ttl_days,
            gemini_api_key=cfg.gemini.api_key,
            gemini_model=cfg.gemini.model,
            gemini_timeout=cfg.gemini.timeout_seconds,
            http_timeout=cfg.general.http_timeout_seconds,
            http_retries=cfg.general.http_retries,
        )
        all_events.extend(events)
    all_events.sort(key=lambda d: d.date)

    out_dir = project_root / cfg.calendar.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "current.png"
    events_path = out_dir / "events.json"
    render_calendar_png(
        all_events, today, png_path, months=cfg.calendar.months_in_png,
    )
    write_events_json(all_events, events_path)

    try:
        published = git_publish(
            [out_dir],
            message=f"auto: calendar update {today.isoformat()}",
            cwd=project_root,
        )
        if published:
            log.info("calendar.git_published path=%s", out_dir)
    except RuntimeError as e:
        log.warning("calendar.git_publish_failed err=%s", e)
        _safe_alert(cfg, f"calendar git_publish failed: {e}")

    all_new_posts: list[Post] = []
    all_summaries: dict[int, str] = {}
    for _board, _posts, new_posts, summaries in per_board_full:
        all_new_posts.extend(new_posts)
        all_summaries.update(summaries)

    webhook_urls = cfg.all_webhook_urls()
    if not webhook_urls:
        log.warning("digest.no_webhooks")
        return

    upcoming = all_events[:3]
    ok, failed = notifier.send_daily_digest(
        webhook_urls,
        calendar_png_url=f"{cfg.calendar.site_url}/current.png",
        site_url=cfg.calendar.site_url,
        new_posts=all_new_posts,
        upcoming=upcoming,
        summaries=all_summaries,
        today=today,
        timeout=cfg.general.http_timeout_seconds,
        retries=cfg.general.http_retries,
    )
    if failed:
        _safe_alert(
            cfg,
            f"daily digest: {len(failed)}/{ok + len(failed)} webhooks failed",
        )
    if ok == 0:
        raise RuntimeError("all webhooks failed for daily digest")
```

Update the `_legacy_emit` call site too — it still uses the 3-tuple but the new shape is 4-tuple; adjust the for-loop unpacking:

```python
for board, _posts, new_posts, summaries in per_board_full:
```

(Inside `_legacy_emit`'s loop.) Update its signature to `list[tuple[BoardConfig, list[Post], list[Post], dict[int, str]]]`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_main_calendar.py tests/test_main.py -q`
Expected: all PASS.

- [ ] **Step 6: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/cse_bot/main.py tests/test_main_calendar.py
git commit -m "feat(calendar): wire calendar_publisher into run_cycle (snapshot-driven digest)"
```

---

## Task 11: scripts/migrate_to_v2.py — one-off data migration

**Files:**
- Create: `scripts/migrate_to_v2.py`
- Create: `tests/test_migrate_to_v2.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_migrate_to_v2.py`:

```python
"""Tests for the v1 → v2 data migration script."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def repo_root_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "state.json").write_text(
        json.dumps({
            "boards": {
                "14221": {
                    "last_max_post_id": 1441380,
                    "last_checked": "2026-05-26T09:00:00+09:00",
                    "empty_streak": 0,
                    "deadlines": [
                        {
                            "post_id": 1441380,
                            "title": "[장학] 주거안정장학금",
                            "url": "https://cse.pusan.ac.kr/.../1441380",
                            "date": "2026-06-22",
                            "reminded": False,
                            "category": "장학/등록",
                            "summary": "summary",
                            "important": True,
                        }
                    ],
                }
            }
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    return tmp_path


def test_migration_writes_post_cache(repo_root_layout: Path):
    import migrate_to_v2  # type: ignore[import-not-found]
    rc = migrate_to_v2.main([])
    assert rc == 0

    cache_path = repo_root_layout / "data" / "post_cache.json"
    assert cache_path.exists()
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["schema_version"] == 1
    posts = cache["boards"]["14221"]["posts"]
    assert "1441380" in posts
    entry = posts["1441380"]
    assert entry["deadline"] == "2026-06-22"
    # content_hash is intentionally empty so the next cycle re-summarises
    assert entry["content_hash"] == ""


def test_migration_clears_state_deadlines(repo_root_layout: Path):
    import migrate_to_v2  # type: ignore[import-not-found]
    migrate_to_v2.main([])
    state = json.loads(
        (repo_root_layout / "data" / "state.json").read_text(encoding="utf-8")
    )
    # Watermark preserved, deadlines emptied
    assert state["boards"]["14221"]["last_max_post_id"] == 1441380
    assert state["boards"]["14221"].get("deadlines", []) == []


def test_migration_dry_run_writes_nothing(repo_root_layout: Path):
    import migrate_to_v2  # type: ignore[import-not-found]
    rc = migrate_to_v2.main(["--dry-run"])
    assert rc == 0
    assert not (repo_root_layout / "data" / "post_cache.json").exists()


def test_migration_idempotent(repo_root_layout: Path):
    import migrate_to_v2  # type: ignore[import-not-found]
    migrate_to_v2.main([])
    rc = migrate_to_v2.main([])
    assert rc == 0
    # Re-running does not corrupt the cache
    cache = json.loads(
        (repo_root_layout / "data" / "post_cache.json").read_text(encoding="utf-8")
    )
    assert "1441380" in cache["boards"]["14221"]["posts"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_migrate_to_v2.py -q`
Expected: ImportError on `migrate_to_v2`.

- [ ] **Step 3: Create the migration script**

Create `scripts/migrate_to_v2.py`:

```python
#!/usr/bin/env python3
"""One-off migration: convert v1 ``state.deadlines`` into v2 ``post_cache.json``.

The v2 snapshot architecture (see
``docs/superpowers/specs/2026-05-26-calendar-v2-snapshot-spec.md``)
moves the calendar's data source from incremental watermark state to a
list-page snapshot cache. This script seeds that cache from existing
``state.deadlines`` so the first v2 cycle does not regress the calendar.

Important: ``content_hash`` is intentionally left empty. The next cycle
will detect "hash changed" for every migrated entry and re-summarise via
Gemini once. After that, warm-cache behaviour kicks in and Gemini calls
drop to near zero per cycle.

Usage (run from repo root, in the same venv as the bot):

    python3 scripts/migrate_to_v2.py
    python3 scripts/migrate_to_v2.py --dry-run

Safe to re-run: the script merges into any existing cache rather than
overwriting it, so an accidental second invocation is a no-op for
unchanged entries.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_STATE_PATH = Path("data/state.json")
DEFAULT_CACHE_PATH = Path("data/post_cache.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.state.exists():
        print(f"ERROR: state file not found: {args.state}", file=sys.stderr)
        return 1

    state = json.loads(args.state.read_text(encoding="utf-8"))
    boards = state.get("boards", {})

    # Start from any existing cache so re-running merges instead of overwriting.
    if args.cache.exists():
        cache = json.loads(args.cache.read_text(encoding="utf-8"))
    else:
        cache = {"schema_version": 1, "updated_at": "", "boards": {}}

    migrated = 0
    for board_id, st in boards.items():
        last_checked = st.get("last_checked", "")
        deadlines = st.get("deadlines", [])
        if not deadlines:
            continue
        board_cache = cache["boards"].setdefault(board_id, {"posts": {}})
        posts = board_cache["posts"]
        for d in deadlines:
            pid = str(d["post_id"])
            if pid in posts:
                continue
            posts[pid] = {
                "title": d["title"],
                "url": d["url"],
                "content_hash": "",  # forces re-summarise on next cycle
                "summarized_at": last_checked,
                "deadline": d.get("date"),
                "category": d.get("category") or "",
                "summary": d.get("summary", ""),
                "important": bool(d.get("important", False)),
                "last_seen": last_checked,
            }
            migrated += 1

    if args.dry_run:
        print(f"[DRY RUN] would migrate {migrated} deadline(s) into {args.cache}")
        return 0

    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.cache.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # Clear state.deadlines (watermark is preserved for notifier flow).
    for st in boards.values():
        st.pop("deadlines", None)
    args.state.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    print(f"✓ migrated {migrated} deadline(s) → {args.cache}")
    print("Next: run one cycle so warm cache populates content_hash.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_migrate_to_v2.py -q`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_to_v2.py tests/test_migrate_to_v2.py
git commit -m "feat(calendar): add scripts/migrate_to_v2.py for v1.x state→post_cache migration"
```

---

## Task 12: Delete scripts/backfill_deadlines.py and its docs reference

The snapshot model fetches the entire list page every cycle, so the watermark-rewind workaround is obsolete (spec §7.3).

**Files:**
- Delete: `scripts/backfill_deadlines.py`

- [ ] **Step 1: Verify nothing imports backfill_deadlines**

Run: `grep -rn "backfill_deadlines" /Users/7bellaa/cseDiscordBot/src /Users/7bellaa/cseDiscordBot/tests 2>/dev/null`
Expected: no matches.

- [ ] **Step 2: Delete the script**

Run: `git rm scripts/backfill_deadlines.py`

- [ ] **Step 3: Update docs that reference it**

Search for references:

Run: `grep -rn "backfill_deadlines\|backfill-deadlines" /Users/7bellaa/cseDiscordBot/docs 2>/dev/null`

For any matches in docs that *describe* the script as a workaround, append a short note that v2.0.0 supersedes it. Do not delete the historical incident specs — those are post-mortems and stay accurate as historical record. Add to each match one line:

```markdown
> Superseded by the v2.0.0 snapshot architecture (see `2026-05-26-calendar-v2-snapshot-spec.md`). The backfill script no longer exists.
```

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(calendar): remove backfill_deadlines.py (superseded by v2 snapshot model)"
```

---

## Task 13: Visual verification on a populated cache

Before declaring v2.0.0 done, render the calendar PNG against the real `docs/calendar/events.json` to confirm the visual output matches v1.3.0 (no regressions in chip layout / dark theme / important ring).

**Files:**
- None modified — read-only smoke check.

- [ ] **Step 1: Render the PNG using current events.json**

Run the inline smoke recipe from project memory:

```bash
.venv/bin/python -m pytest tests/test_calendar_renderer.py -q
.venv/bin/python -c "
import json
from datetime import date
from pathlib import Path
from cse_bot.calendar_renderer import render_calendar_png
from cse_bot.models import TrackedDeadline

events = json.loads(Path('docs/calendar/events.json').read_text())
deadlines = [
    TrackedDeadline(
        post_id=int(e['id']),
        title=e['title'],
        url=e['url'],
        date=e['start'],
        category=e['extendedProps'].get('category', ''),
        important=e['extendedProps'].get('important', False),
    )
    for e in events
]
render_calendar_png(
    deadlines, date.today(), Path('/tmp/v2_smoke.png'), months=2,
)
print('rendered /tmp/v2_smoke.png')
"
```

Expected: PNG renders, no exception.

- [ ] **Step 2: Compare to docs/calendar/current.png**

Run: `ls -lh docs/calendar/current.png /tmp/v2_smoke.png`
Expected: both files exist, sizes are within ~10% of each other.

- [ ] **Step 3: No commit needed**

This task is a verification step. If anything fails, file a new task — do not silently move on.

---

## Task 14: Run migration locally and capture a baseline snapshot

This is a manual step the operator performs once on the production machine. It is documented here so the agent does not skip it.

**Files:**
- Modify (runtime, not source): `data/state.json`, `data/post_cache.json`

- [ ] **Step 1: Dry-run the migration**

Run: `.venv/bin/python scripts/migrate_to_v2.py --dry-run`
Expected output: `[DRY RUN] would migrate N deadline(s) into data/post_cache.json` for non-zero N.

- [ ] **Step 2: Capture baseline events.json**

Run: `cp docs/calendar/events.json /tmp/events_pre_v2.json`

- [ ] **Step 3: Apply migration**

Run: `.venv/bin/python scripts/migrate_to_v2.py`
Expected: `✓ migrated N deadline(s) → data/post_cache.json`.

- [ ] **Step 4: Run one cycle**

Run: `launchctl kickstart -k gui/$(id -u)/com.user.cse-bot && sleep 30 && tail -50 logs/launchd.stderr.log`
Expected: `calendar.cache_update` log lines and a successful digest.

- [ ] **Step 5: Diff events.json**

Run: `diff <(jq -S . /tmp/events_pre_v2.json) <(jq -S . docs/calendar/events.json) | head -50`
Expected: v2 events.json is a superset (new entries OK, no missing entries that were active in v1).

- [ ] **Step 6: Commit baseline if happy**

If the diff is acceptable:

```bash
git add docs/calendar/events.json data/post_cache.json data/state.json
git commit -m "chore(calendar): baseline post_cache after v2.0.0 migration"
```

If the diff shows regressions, **STOP** and investigate before committing. Roll back by restoring `data/state.json` from git history and removing `data/post_cache.json`.

---

## Task 15: CHANGELOG and release notes

**Files:**
- Modify: `CHANGELOG.md` (create if missing)

- [ ] **Step 1: Check whether CHANGELOG.md exists**

Run: `ls CHANGELOG.md 2>/dev/null || echo missing`

- [ ] **Step 2: Add the v2.0.0 entry**

If missing, create with:

```markdown
# Changelog

## v2.0.0 — 2026-05-26 — Snapshot Calendar

### Breaking
- Calendar data source moves from `state.deadlines` (incremental) to
  `data/post_cache.json` (snapshot). Run `scripts/migrate_to_v2.py` once
  before the first v2 cycle.

### Added
- `src/cse_bot/post_cache.py` — PostCache I/O, content_hash, TTL prune.
- `src/cse_bot/manual_overrides.py` — operator-edited
  `data/manual_deadlines.json` loader.
- `src/cse_bot/calendar_publisher.py` — snapshot-driven cache update +
  event list builder.
- `scripts/migrate_to_v2.py` — one-off v1 → v2 data migration.
- `[calendar].cache_path`, `[calendar].manual_overrides_path`,
  `[calendar].cache_ttl_days` config keys (defaults preserve back-compat).

### Removed
- `scripts/backfill_deadlines.py` — superseded by snapshot model.

### Background
- See `docs/superpowers/specs/2026-05-26-calendar-v2-snapshot-spec.md`.
- v1.x suffered from baseline-blindness, stale accumulation, and
  ID-reassignment double-counting. v2 fixes all three by mirroring the
  list page each cycle instead of accumulating.
```

If it exists, prepend this entry at the top.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: v2.0.0 changelog entry"
```

---

## Acceptance Criteria Map (from spec §8)

| Criterion | Verified by |
|---|---|
| post_cache reflects all list-page posts | Task 10 `test_v2_digest_writes_post_cache_with_list_snapshot` |
| Same cycle re-run → 0 LLM calls | Task 10 `test_v2_warm_cache_skips_gemini_calls` |
| Body modification → exactly 1 re-summarize | Task 7 `test_update_cache_changed_body_triggers_resummarize` |
| Post disappearance → 30d TTL prune | Task 4 `test_prune_stale_removes_old_entries` + Task 8 `test_run_calendar_publish_prunes_stale_entries` |
| Manual override present regardless of cache | Task 10 `test_v2_manual_overrides_appear_in_events_json` |
| Manual wins on URL collision | Task 6 `test_build_events_manual_override_wins_on_url_match` |
| Notifier flow regression-free | Task 10 step 6 (full suite) |
| Migration yields superset events.json | Task 11 + Task 14 step 5 |
| Gemini ≤ 10 calls/day warm | Task 10 `test_v2_warm_cache_skips_gemini_calls` (indirect, plus operational observation) |
| All tests pass | Task 10 step 6 + Task 12 step 4 |

---

## Risks revisited

| Risk | Where the plan handles it |
|---|---|
| Parser change → all hashes invalidate | `content_hash` normalises whitespace defensively (Task 3); alert wiring already present via `_safe_alert` |
| Gemini misreads deadline date | Cache stores the value verbatim; manual overrides (Task 5) let operator patch fast |
| List page truncated to ≤1-2 pages | `general.max_pages` already configurable; spec §10 calls this out as a known boundary |
| post_cache JSON corruption | Atomic write + corruption fallback (Task 2) |
| Migration regresses events | Task 14 step 5 captures baseline before applying |
| Operator edits manual_deadlines incorrectly | Schema validation + skip-on-error (Task 5) |
| Notifier still hits double-cycle for new posts | Accepted in v2.0.0; future v2.1 can share fetched bodies between notifier and calendar_publisher |

---

## Out of scope (deferred to v2.1+)

- Discord slash commands (`/cal add`, `/cal remove`).
- Cache change history / audit log.
- Anomaly detection on deadline jumps.
- Multi-board snapshot.
- "마지막 갱신: HH:MM" footer on the web calendar page.
- Sharing fetched article bodies between notifier and calendar_publisher.

---

## DRY / YAGNI / TDD reminders

- Every task starts with a failing test.
- No placeholder strings (`TBD`, "handle later") anywhere in this plan.
- Type signatures stay consistent across tasks: `update_cache_from_snapshot`, `build_events`, `run_calendar_publish` keep their names from declaration through the orchestrator wiring.
- Commit cadence: 14 commits across 15 tasks (Task 13 has none — verification only).
