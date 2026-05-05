"""Send post notifications to a Discord webhook."""
from __future__ import annotations

import logging
from typing import Literal

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from cse_bot.models import Post

log = logging.getLogger(__name__)

USER_AGENT = "cse-discord-bot/0.1"

Format = Literal["minimal", "medium", "detailed"]


class NotifyError(Exception):
    """Raised when sending a Discord webhook fails terminally."""


class _RetryableNotifyError(Exception):
    pass


DISCORD_MAX = 2000


def format_message(post: Post, fmt: Format, summary: str | None = None) -> str:
    if fmt == "minimal":
        base = f"📢 **새 공지: {post.title}**\n🔗 {post.url}"
    elif fmt == "medium":
        base = (
            f"📢 **새 공지: {post.title}**\n"
            f"✍️ {post.author} · 📅 {post.date}\n"
            f"🔗 {post.url}"
        )
    elif fmt == "detailed":
        attached = "첨부 있음" if post.has_attachment else "첨부 없음"
        base = (
            f"📢 **새 공지: {post.title}**  `[{post.category}]`\n"
            f"✍️ {post.author} · 📅 {post.date} · 📎 {attached}\n"
            f"🔗 {post.url}"
        )
    else:
        raise ValueError(f"unknown format: {fmt}")

    msg = f"{base}\n📝 요약:\n{summary}" if summary else base

    if len(msg) > DISCORD_MAX:
        msg = msg[: DISCORD_MAX - 1] + "…"
    return msg


def send(
    post: Post,
    *,
    webhook_url: str,
    fmt: Format,
    timeout: float,
    retries: int,
    summary: str | None = None,
) -> None:
    """POST a notification to the Discord webhook. Raises NotifyError on terminal failure."""
    content = format_message(post, fmt, summary=summary)
    payload = {"content": content}

    @retry(
        stop=stop_after_attempt(max(1, retries)),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(_RetryableNotifyError),
        reraise=True,
    )
    def _do() -> None:
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    webhook_url, json=payload, headers={"User-Agent": USER_AGENT}
                )
        except httpx.HTTPError as e:
            log.warning("notify.network_error err=%s", e)
            raise _RetryableNotifyError(str(e)) from e

        if resp.status_code in (429,) or 500 <= resp.status_code < 600:
            log.warning("notify.retryable status=%d", resp.status_code)
            raise _RetryableNotifyError(f"status={resp.status_code}")
        if resp.status_code >= 400:
            raise NotifyError(
                f"discord error: status={resp.status_code} body={resp.text[:200]}"
            )
        # 2xx (Discord webhooks usually return 204).

    try:
        _do()
    except _RetryableNotifyError as e:
        raise NotifyError(f"retries exhausted: {e}") from e
    except RetryError as e:
        raise NotifyError(f"retries exhausted: {e}") from e


def send_to_webhooks(
    post: Post,
    *,
    webhook_urls: list[str],
    summary: str | None,
    fmt: Format,
    timeout: float,
    retries: int,
) -> tuple[int, list[str]]:
    """Sequentially POST to each webhook. Returns (success_count, failed_urls).

    Each webhook is independent — one failure does not abort the others.
    """
    ok = 0
    failed: list[str] = []
    for url in webhook_urls:
        try:
            send(
                post,
                webhook_url=url,
                fmt=fmt,
                timeout=timeout,
                retries=retries,
                summary=summary,
            )
            ok += 1
        except NotifyError as e:
            log.warning("send_to_webhooks.failed url=%s err=%s", url, e)
            failed.append(url)
    return ok, failed


def send_alert(message: str, *, webhook_url: str, timeout: float = 5.0) -> None:
    """Best-effort alert to the self-alert webhook. Never raises."""
    try:
        with httpx.Client(timeout=timeout) as client:
            client.post(
                webhook_url,
                json={"content": message[:1900]},
                headers={"User-Agent": USER_AGENT},
            )
    except httpx.HTTPError as e:
        log.error("alert.failed err=%s", e)
