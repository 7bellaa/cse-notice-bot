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
