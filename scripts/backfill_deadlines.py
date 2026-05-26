#!/usr/bin/env python3
"""One-off backfill: lower the bot's watermark so it re-fetches older posts.

The bot records "current latest post ID" as baseline on first startup
(see src/cse_bot/main.py _process_board), and only treats posts ABOVE
that baseline as new. As a result, posts already on the board at first
startup never get summarized — their deadlines never enter the calendar.

This script is the operator escape hatch: pass an artclNo floor (e.g.
1388000) and it rewrites data/state.json so the next cycle treats every
post above that floor as newly-discovered. The bot will then fetch their
bodies, run them through Gemini, and add any with a deadline to
state.deadlines.

Usage (run from repo root, in the same venv as the bot):

    python3 scripts/backfill_deadlines.py                # floor = 1388000 (default)
    python3 scripts/backfill_deadlines.py 1430000        # custom floor
    python3 scripts/backfill_deadlines.py --board 14221  # specific board
    python3 scripts/backfill_deadlines.py --dry-run      # show what would change

After running, kickstart the bot so the next cycle picks up the change:

    launchctl kickstart -k gui/$(id -u)/com.user.cse-bot
    tail -f logs/launchd.stderr.log

The fetch + Gemini summarize step costs roughly one Gemini Flash Lite
call per post in the range (typically 30-50 posts, ~$0.01 total) and
adds ~30-60 seconds to the cycle.

Safe to re-run: it only writes a single integer field in state.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_FLOOR = 1388000
DEFAULT_BOARD = "14221"
DEFAULT_STATE_PATH = Path("data/state.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "floor",
        type=int,
        nargs="?",
        default=DEFAULT_FLOOR,
        help=f"new watermark floor (default: {DEFAULT_FLOOR})",
    )
    parser.add_argument(
        "--board",
        default=DEFAULT_BOARD,
        help=f"board id in state.json (default: {DEFAULT_BOARD})",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help=f"state.json path (default: {DEFAULT_STATE_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would change without writing",
    )
    args = parser.parse_args(argv)

    if not args.state.exists():
        print(f"ERROR: state file not found: {args.state}", file=sys.stderr)
        print("Run this from the repo root, where data/state.json lives.", file=sys.stderr)
        return 1

    raw = args.state.read_text(encoding="utf-8")
    state = json.loads(raw)

    boards = state.get("boards", {})
    board = boards.get(args.board)
    if board is None:
        print(f"ERROR: board {args.board!r} not found in state. Existing boards: {list(boards)}", file=sys.stderr)
        return 1

    old_watermark = board.get("last_max_post_id")
    if old_watermark is None:
        print(f"board {args.board} watermark is None — bot has never recorded a baseline. Nothing to backfill.")
        return 0

    if args.floor >= old_watermark:
        print(
            f"floor {args.floor} >= current watermark {old_watermark}. "
            f"This would skip MORE posts, not fewer. Aborting.",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        print(f"[DRY RUN] board {args.board}: watermark {old_watermark} → {args.floor}")
        print(f"[DRY RUN] would write {args.state}")
        return 0

    board["last_max_post_id"] = args.floor
    args.state.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"✓ board {args.board}: watermark {old_watermark} → {args.floor}")
    print()
    print("Next step:")
    print(f"  launchctl kickstart -k gui/$(id -u)/com.user.cse-bot")
    print(f"  tail -f logs/launchd.stderr.log")
    print()
    print(f"The next cycle will fetch every post with artclNo > {args.floor},")
    print(f"summarize them via Gemini, and add deadlines to state.json.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
