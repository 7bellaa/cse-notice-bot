"""Compute and format due deadline reminders.

A deadline is "due" if today + 1 day == deadline.date and `reminded` is False.
Past deadlines are pruned at the start of each cycle.
"""
from __future__ import annotations

from datetime import date, timedelta

from cse_bot.models import BoardState, TrackedDeadline, safe_iso_date


def collect_due_reminders(
    state_map: dict[str, BoardState], *, today: date,
) -> list[tuple[str, TrackedDeadline]]:
    """Return (board_id, deadline) tuples whose D-1 reminder should fire today."""
    out: list[tuple[str, TrackedDeadline]] = []
    target = today + timedelta(days=1)
    for board_id, board_state in state_map.items():
        for d in board_state.deadlines:
            if d.reminded:
                continue
            d_date = safe_iso_date(d.date)
            if d_date is None:
                continue
            if d_date == target:
                out.append((board_id, d))
    return out


def prune_expired(state_map: dict[str, BoardState], *, today: date) -> int:
    """Drop deadlines whose date is strictly before today. Returns count removed."""
    removed = 0
    for board_state in state_map.values():
        kept: list[TrackedDeadline] = []
        for d in board_state.deadlines:
            d_date = safe_iso_date(d.date)
            if d_date is None or d_date < today:
                removed += 1
                continue
            kept.append(d)
        board_state.deadlines = kept
    return removed


def format_reminder(d: TrackedDeadline) -> str:
    return (
        f"⏰ 내일 마감: {d.title}\n"
        f"📅 마감일: {d.date}\n"
        f"🔗 {d.url}"
    )
