from datetime import date

from cse_bot.models import BoardState, TrackedDeadline
from cse_bot.reminder import (
    collect_due_reminders,
    format_reminder,
    prune_expired,
)


def _state(deadlines: list[TrackedDeadline]) -> dict[str, BoardState]:
    return {
        "14221": BoardState(
            last_max_post_id=1, last_checked="x", empty_streak=0,
            deadlines=deadlines,
        ),
    }


def test_collect_due_reminders_d_minus_1_match():
    today = date(2026, 5, 13)
    d = TrackedDeadline(
        post_id=1, title="t", url="u", date="2026-05-14", reminded=False,
    )
    out = collect_due_reminders(_state([d]), today=today)
    assert out == [("14221", d)]


def test_collect_due_reminders_skips_when_reminded():
    today = date(2026, 5, 13)
    d = TrackedDeadline(
        post_id=1, title="t", url="u", date="2026-05-14", reminded=True,
    )
    assert collect_due_reminders(_state([d]), today=today) == []


def test_collect_due_reminders_skips_d_minus_2():
    today = date(2026, 5, 12)
    d = TrackedDeadline(
        post_id=1, title="t", url="u", date="2026-05-14", reminded=False,
    )
    assert collect_due_reminders(_state([d]), today=today) == []


def test_collect_due_reminders_skips_d_day():
    today = date(2026, 5, 14)
    d = TrackedDeadline(
        post_id=1, title="t", url="u", date="2026-05-14", reminded=False,
    )
    assert collect_due_reminders(_state([d]), today=today) == []


def test_collect_due_reminders_skips_past_deadline():
    today = date(2026, 5, 20)
    d = TrackedDeadline(
        post_id=1, title="t", url="u", date="2026-05-14", reminded=False,
    )
    assert collect_due_reminders(_state([d]), today=today) == []


def test_prune_expired_removes_past_deadlines():
    today = date(2026, 5, 15)
    d_past = TrackedDeadline(
        post_id=1, title="old", url="u", date="2026-05-14", reminded=True,
    )
    d_future = TrackedDeadline(
        post_id=2, title="next", url="u", date="2026-05-20", reminded=False,
    )
    state = _state([d_past, d_future])
    n = prune_expired(state, today=today)
    assert n == 1
    assert state["14221"].deadlines == [d_future]


def test_prune_expired_keeps_today_deadline():
    today = date(2026, 5, 14)
    d_today = TrackedDeadline(
        post_id=1, title="t", url="u", date="2026-05-14", reminded=False,
    )
    state = _state([d_today])
    assert prune_expired(state, today=today) == 0
    assert len(state["14221"].deadlines) == 1


def test_format_reminder_includes_title_date_url():
    d = TrackedDeadline(
        post_id=1, title="수강신청", url="https://x", date="2026-05-14", reminded=False,
    )
    msg = format_reminder(d)
    assert "수강신청" in msg
    assert "2026-05-14" in msg
    assert "https://x" in msg
    assert "내일 마감" in msg
