"""Tests for cse_bot.notifier.send_daily_digest."""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
import respx

from cse_bot.models import Post, TrackedDeadline
from cse_bot.notifier import send_daily_digest

WEBHOOK_A = "https://discord.com/api/webhooks/111/aaa"
WEBHOOK_B = "https://discord.com/api/webhooks/222/bbb"

PNG_URL = "https://example.com/calendar/current.png"
SITE_URL = "https://example.com/calendar"


def _post(id_: int = 1, title: str = "[장학] 주거안정장학금 신청") -> Post:
    return Post(
        id=id_,
        title=title,
        author="학과사무실",
        date="2026.05.22",
        url=f"https://cse.pusan.ac.kr/post/{id_}",
        category="5719",
        has_attachment=False,
    )


def _dl(
    post_id: int = 1,
    title: str = "[장학] 주거안정장학금 신청",
    date_str: str = "2026-06-22",
    category: str = "장학",
) -> TrackedDeadline:
    return TrackedDeadline(
        post_id=post_id,
        title=title,
        url=f"https://cse.pusan.ac.kr/post/{post_id}",
        date=date_str,
        category=category,
    )


@respx.mock
def test_posts_single_message_with_embed_and_content() -> None:
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    ok, failed = send_daily_digest(
        [WEBHOOK_A],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[_post(1)],
        upcoming=[_dl(1)],
        summaries={1: "주거안정장학금 신청 마감 6/22"},
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )

    assert (ok, failed) == (1, [])
    body = json.loads(route.calls.last.request.content.decode("utf-8"))

    # Embed structure
    assert len(body["embeds"]) == 1
    embed = body["embeds"][0]
    assert "PNU CSE" in embed["title"]
    assert "2026-05-26" in embed["title"]
    assert embed["image"]["url"].startswith(PNG_URL)
    assert "?t=" in embed["image"]["url"]
    assert embed["url"] == SITE_URL

    # Content (1-line bullet)
    assert "🆕" in body["content"]
    assert "주거안정장학금 신청" in body["content"]


@respx.mock
def test_fanout_to_multiple_webhooks() -> None:
    route_a = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))
    route_b = respx.post(WEBHOOK_B).mock(return_value=httpx.Response(204))

    ok, failed = send_daily_digest(
        [WEBHOOK_A, WEBHOOK_B],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[_post(1)],
        upcoming=[_dl(1)],
        summaries={},
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )

    assert (ok, failed) == (2, [])
    assert route_a.called and route_b.called


@respx.mock
def test_no_new_posts_omits_content_field() -> None:
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    ok, failed = send_daily_digest(
        [WEBHOOK_A],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[],
        upcoming=[_dl(1)],
        summaries={},
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )

    assert (ok, failed) == (1, [])
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    # When no new posts, content should be a brief placeholder or empty
    assert body.get("content", "") == "" or "오늘" in body.get("content", "")


@respx.mock
def test_d_minus_1_count_in_description() -> None:
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    ok, failed = send_daily_digest(
        [WEBHOOK_A],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[],
        upcoming=[_dl(1, date_str="2026-05-27")],  # tomorrow → D-1
        summaries={},
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )

    assert ok == 1
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    desc = body["embeds"][0].get("description", "")
    # D-1 reminder folded into description
    assert "내일" in desc or "D-1" in desc


@respx.mock
def test_content_truncated_when_too_long() -> None:
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    # 50 long posts → guaranteed to exceed 2000 chars
    many_posts = [
        _post(i, title=f"[장학] 매우 긴 공지 제목 {i} " + "X" * 80)
        for i in range(1, 51)
    ]
    ok, failed = send_daily_digest(
        [WEBHOOK_A],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=many_posts,
        upcoming=[],
        summaries={},
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )

    assert ok == 1
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    assert len(body.get("content", "")) <= 2000
    # Overflow note should be present
    assert "외" in body.get("content", "") or "…" in body.get("content", "")


@respx.mock
def test_partial_failure_reports_failed_url() -> None:
    respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))
    # Use 400-level which is NON-retryable client error
    respx.post(WEBHOOK_B).mock(return_value=httpx.Response(404))

    ok, failed = send_daily_digest(
        [WEBHOOK_A, WEBHOOK_B],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[],
        upcoming=[],
        summaries={},
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=1,
    )

    assert ok == 1
    assert WEBHOOK_B in failed


@respx.mock
def test_cache_bust_timestamp_changes_between_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    timestamps = iter([1000, 2000])
    monkeypatch.setattr("cse_bot.notifier._epoch_now", lambda: next(timestamps))

    for _ in range(2):
        send_daily_digest(
            [WEBHOOK_A],
            calendar_png_url=PNG_URL,
            site_url=SITE_URL,
            new_posts=[],
            upcoming=[],
            summaries={},
            today=date(2026, 5, 26),
            timeout=5.0,
            retries=3,
        )

    bodies = [json.loads(c.request.content.decode("utf-8")) for c in route.calls]
    url1 = bodies[0]["embeds"][0]["image"]["url"]
    url2 = bodies[1]["embeds"][0]["image"]["url"]
    assert "t=1000" in url1
    assert "t=2000" in url2
    assert url1 != url2
