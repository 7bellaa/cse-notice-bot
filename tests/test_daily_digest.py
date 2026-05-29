"""Tests for cse_bot.notifier.send_daily_digest."""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
import respx

from cse_bot.models import Post, TrackedDeadline
from cse_bot.notifier import (
    DEFAULT_EMBED_HEX,
    NEAR_AMBER_HEX,
    URGENT_RED_HEX,
    send_daily_digest,
)

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
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=1,
    )

    assert ok == 1
    assert WEBHOOK_B in failed


@respx.mock
def test_fields_carry_clickable_links_per_deadline() -> None:
    """Each upcoming deadline appears as an embed field with a clickable URL."""
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    ok, _ = send_daily_digest(
        [WEBHOOK_A],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[],
        upcoming=[
            _dl(1, title="[비교과] 오픈소스SW특강", date_str="2026-05-27",
                category="비교과/활동"),
            _dl(2, title="[장학] 국가근로장학금", date_str="2026-05-29",
                category="장학/등록"),
        ],
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )
    assert ok == 1
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    embed = body["embeds"][0]
    fields = embed.get("fields") or []
    assert len(fields) == 2
    # Field naming follows "<emoji> <D-N> · <category>"
    assert "D-1" in fields[0]["name"]
    assert "비교과/활동" in fields[0]["name"]
    # Value contains the clickable hyperlink + canonical URL
    assert "원문 보기" in fields[0]["value"]
    assert "https://cse.pusan.ac.kr/post/1" in fields[0]["value"]
    # Category prefix stripped from the title in the value
    assert "**오픈소스SW특강**" in fields[0]["value"]


@respx.mock
def test_fields_omitted_when_no_upcoming() -> None:
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    send_daily_digest(
        [WEBHOOK_A],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[],
        upcoming=[],
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    embed = body["embeds"][0]
    assert "fields" not in embed or embed["fields"] == []


@respx.mock
def test_fields_cap_at_five() -> None:
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    many = [
        _dl(i, title=f"[학업] item {i}", date_str=f"2026-06-{i:02d}",
            category="학업/수강")
        for i in range(1, 11)
    ]
    send_daily_digest(
        [WEBHOOK_A],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[],
        upcoming=many,
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    fields = body["embeds"][0].get("fields") or []
    assert len(fields) == 5


@respx.mock
def test_color_urgent_red_when_d_minus_3_or_less() -> None:
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    send_daily_digest(
        [WEBHOOK_A],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[],
        upcoming=[_dl(1, date_str="2026-05-27")],  # tomorrow → D-1
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    assert body["embeds"][0]["color"] == URGENT_RED_HEX


@respx.mock
def test_color_amber_when_d_minus_7_window() -> None:
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    send_daily_digest(
        [WEBHOOK_A],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[],
        upcoming=[_dl(1, date_str="2026-06-02")],  # D-7 from 5/26
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    assert body["embeds"][0]["color"] == NEAR_AMBER_HEX


@respx.mock
def test_color_default_when_no_upcoming() -> None:
    route = respx.post(WEBHOOK_A).mock(return_value=httpx.Response(204))

    send_daily_digest(
        [WEBHOOK_A],
        calendar_png_url=PNG_URL,
        site_url=SITE_URL,
        new_posts=[],
        upcoming=[],
        today=date(2026, 5, 26),
        timeout=5.0,
        retries=3,
    )
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    assert body["embeds"][0]["color"] == DEFAULT_EMBED_HEX


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
