"""Persist board watermark state to a JSON file.

Schema:
    {
      "boards": {
        "<board_id>": {
          "last_max_post_id": int | null,
          "last_checked": ISO8601 string,
          "empty_streak": int
        },
        ...
      }
    }
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

from cse_bot.models import BoardState, TrackedDeadline

log = logging.getLogger(__name__)

BoardStateMap = dict[str, BoardState]


def load_state(path: Path) -> BoardStateMap:
    """Load state from disk. Returns {} if missing.

    On corrupt JSON, the file is moved aside as `<name>.corrupt-<epoch>`
    and {} is returned (baseline-mode reset).
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        shutil.move(str(path), backup)
        log.warning("state.corrupt path=%s backup=%s", path, backup)
        return {}

    boards = raw.get("boards", {}) if isinstance(raw, dict) else {}
    result: BoardStateMap = {}
    for board_id, entry in boards.items():
        if not isinstance(entry, dict):
            continue
        deadlines_raw = entry.get("deadlines", [])
        deadlines = [
            TrackedDeadline(
                post_id=int(d["post_id"]),
                title=str(d["title"]),
                url=str(d["url"]),
                date=str(d["date"]),
                reminded=bool(d.get("reminded", False)),
            )
            for d in deadlines_raw
        ]
        result[board_id] = BoardState(
            last_max_post_id=entry.get("last_max_post_id"),
            last_checked=entry.get("last_checked", ""),
            empty_streak=int(entry.get("empty_streak", 0)),
            deadlines=deadlines,
        )
    return result


def save_state(path: Path, state: BoardStateMap) -> None:
    """Persist state to disk atomically. Enforces monotonic watermarks."""
    if path.exists():
        previous = load_state(path)
        for board_id, new in state.items():
            old = previous.get(board_id)
            if (
                old is not None
                and old.last_max_post_id is not None
                and new.last_max_post_id is not None
                and new.last_max_post_id < old.last_max_post_id
            ):
                raise ValueError(
                    f"watermark must be monotonic: board={board_id} "
                    f"old={old.last_max_post_id} new={new.last_max_post_id}"
                )

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "boards": {
            board_id: {
                "last_max_post_id": s.last_max_post_id,
                "last_checked": s.last_checked,
                "empty_streak": s.empty_streak,
                "deadlines": [
                    {
                        "post_id": d.post_id,
                        "title": d.title,
                        "url": d.url,
                        "date": d.date,
                        "reminded": d.reminded,
                    }
                    for d in s.deadlines
                ],
            }
            for board_id, s in state.items()
        }
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
