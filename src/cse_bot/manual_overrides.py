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
