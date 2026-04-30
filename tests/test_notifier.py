"""Unit tests for the Discord notifier."""
from __future__ import annotations

import httpx
import pytest
import respx

from cse_bot.models import Post
from cse_bot.notifier import NotifyError, format_message, send

WEBHOOK = "https://discord.com/api/webhooks/123/abc"


def _post(id_: int = 19234) -> Post:
    return Post(
        id=id_,
        title="국제처 해외파견 안내",
        author="홍길동",
        date="2026.04.30",
        url=f"https://cse.pusan.ac.kr/post/{id_}",
        category="일반공지",
        has_attachment=True,
    )


def test_format_medium_includes_required_fields() -> None:
    msg = format_message(_post(), fmt="medium")
    assert "국제처 해외파견 안내" in msg
    assert "홍길동" in msg
    assert "2026.04.30" in msg
    assert "https://cse.pusan.ac.kr/post/19234" in msg


def test_format_detailed_includes_category_and_attachment() -> None:
    msg = format_message(_post(), fmt="detailed")
    assert "일반공지" in msg
    assert "첨부 있음" in msg


@respx.mock
def test_send_posts_to_webhook() -> None:
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    send(_post(), webhook_url=WEBHOOK, fmt="medium", timeout=5.0, retries=3)
    assert route.called
    body = route.calls.last.request.content.decode("utf-8")
    assert "국제처 해외파견 안내" in body


@respx.mock
def test_send_retries_on_429_then_succeeds() -> None:
    route = respx.post(WEBHOOK).mock(
        side_effect=[
            httpx.Response(429, json={"retry_after": 0.01}),
            httpx.Response(204),
        ]
    )
    send(_post(), webhook_url=WEBHOOK, fmt="medium", timeout=5.0, retries=3)
    assert route.call_count == 2


@respx.mock
def test_send_raises_on_4xx_other_than_429() -> None:
    respx.post(WEBHOOK).mock(return_value=httpx.Response(404))
    with pytest.raises(NotifyError, match="404"):
        send(_post(), webhook_url=WEBHOOK, fmt="medium", timeout=5.0, retries=3)


@respx.mock
def test_send_raises_after_5xx_retries_exhausted() -> None:
    respx.post(WEBHOOK).mock(return_value=httpx.Response(500))
    with pytest.raises(NotifyError):
        send(_post(), webhook_url=WEBHOOK, fmt="medium", timeout=5.0, retries=3)
