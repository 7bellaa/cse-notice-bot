"""Send post notifications to a Discord webhook."""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Literal

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from cse_bot.category import extract_category, is_important
from cse_bot.models import Post, TrackedDeadline

log = logging.getLogger(__name__)

USER_AGENT = "cse-discord-bot/0.1"

Format = Literal["minimal", "medium", "detailed"]


def _epoch_now() -> int:
    """Wallclock epoch in seconds (extracted for monkeypatching in tests)."""
    return int(time.time())


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


def send_alert_to_webhooks(
    content: str,
    *,
    webhook_urls: list[str],
    timeout: float,
    retries: int,
) -> tuple[int, list[str]]:
    """POST a plain content message to each webhook (no Post envelope).

    Used for deadline reminders and other non-post notifications. Sequential,
    best-effort. Returns (success_count, failed_urls).
    """
    if len(content) > DISCORD_MAX:
        content = content[: DISCORD_MAX - 1] + "…"
    payload = {"content": content}
    ok = 0
    failed: list[str] = []
    for url in webhook_urls:
        attempts = max(1, retries)
        success = False
        for i in range(attempts):
            try:
                with httpx.Client(timeout=timeout) as client:
                    resp = client.post(
                        url, json=payload, headers={"User-Agent": USER_AGENT},
                    )
            except httpx.HTTPError as e:
                log.warning("alert_to.network url=%s err=%s", url, e)
                if i == attempts - 1:
                    break
                continue
            if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                if i == attempts - 1:
                    break
                continue
            if resp.status_code >= 400:
                log.warning("alert_to.client_error url=%s status=%d", url, resp.status_code)
                break
            success = True
            break
        if success:
            ok += 1
        else:
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


# ─── Daily digest (calendar + 1-line new posts) ──────────────────────────


def _format_upcoming_description(
    upcoming: list[TrackedDeadline], today: date
) -> str:
    """Format embed description: 임박 마감 top 3 + D-1 reminder line."""
    if not upcoming:
        return "_추적 중인 마감 없음._"

    lines: list[str] = []
    tomorrow = today + timedelta(days=1)
    d_minus_1 = [d for d in upcoming if d.date == tomorrow.isoformat()]
    if d_minus_1:
        lines.append(f"⏰ **내일 마감 (D-1) {len(d_minus_1)}건**")

    for d in upcoming[:3]:
        try:
            d_date = date.fromisoformat(d.date)
        except ValueError:
            continue
        delta = (d_date - today).days
        if delta == 0:
            tag = "**오늘 마감**"
        elif delta == 1:
            tag = "**D-1**"
        elif delta < 0:
            tag = "지남"
        else:
            tag = f"D-{delta}"
        prefix = "🔥" if delta <= 3 else "📌"
        lines.append(f"{prefix} {d.date} ({tag}) — {d.title}")
    return "\n".join(lines)


def _format_new_posts_content(
    new_posts: list[Post], today: date, *, max_chars: int = 1900,
) -> str:
    """Format the content text block: '🆕 오늘 새 공지 N건' + 1-line bullets.

    Returns an empty string if there are no new posts. The output is capped
    at ``max_chars`` and replaces tail bullets with '... 외 K건 (웹에서 확인)'
    if necessary.
    """
    if not new_posts:
        return ""

    header = f"🆕 오늘 새 공지 {len(new_posts)}건"
    rendered: list[str] = [header]
    used = len(header) + 1  # +1 for newline join

    for i, post in enumerate(new_posts):
        category = extract_category(post.title) or "공지"
        clean_title = post.title
        # Strip the [category] prefix from the displayed title to reduce noise
        if clean_title.startswith("[") and "]" in clean_title:
            clean_title = clean_title[clean_title.index("]") + 1:].strip()
        marker = "★ " if is_important(post.title) else ""
        line = f"· {marker}[{category}] {clean_title} — {post.url}"

        # Reserve some room for the overflow indicator
        remaining = max_chars - used - 1
        overflow_note = f"\n… 외 {len(new_posts) - i}건 (웹에서 확인)"
        if remaining - len(line) - len(overflow_note) < 0 and i < len(new_posts) - 1:
            rendered.append(f"… 외 {len(new_posts) - i}건 (웹에서 확인)")
            break
        rendered.append(line)
        used += len(line) + 1

    return "\n".join(rendered)


def send_daily_digest(
    webhook_urls: list[str],
    *,
    calendar_png_url: str,
    site_url: str,
    new_posts: list[Post],
    upcoming: list[TrackedDeadline],
    summaries: dict[int, str],  # currently unused; reserved for future expansion
    today: date,
    timeout: float,
    retries: int,
) -> tuple[int, list[str]]:
    """Post a single daily digest message to each webhook in *webhook_urls*.

    The payload bundles the calendar PNG as an embed image plus a compact
    1-line bullet for each new post discovered this cycle. Returns
    ``(success_count, failed_urls)``. Per-webhook independent — one failure
    does not abort the others.
    """
    del summaries  # not used yet; deadlines already cover the calendar story

    embed = {
        "title": f"📅 PNU CSE 마감일 캘린더 · {today.isoformat()}",
        "url": site_url,
        "color": 0x5865F2,
        "image": {"url": f"{calendar_png_url}?t={_epoch_now()}"},
        "description": _format_upcoming_description(upcoming, today),
        "footer": {
            "text": (
                "각 칸 = 해당 날짜에 마감되는 공지 (공지 게시일 아님)"
                " · 매일 18:00 갱신 · 클릭하면 웹 캘린더로 이동"
            ),
        },
    }

    content = _format_new_posts_content(new_posts, today)
    payload: dict[str, object] = {"embeds": [embed]}
    if content:
        payload["content"] = content

    ok = 0
    failed: list[str] = []
    for url in webhook_urls:
        if _post_digest_with_retry(url, payload, timeout=timeout, retries=retries):
            ok += 1
        else:
            failed.append(url)
    log.info(
        "daily_digest.sent webhooks_ok=%d webhooks_failed=%d new_posts=%d upcoming=%d",
        ok, len(failed), len(new_posts), len(upcoming),
    )
    return ok, failed


def _post_digest_with_retry(
    webhook_url: str,
    payload: dict[str, object],
    *,
    timeout: float,
    retries: int,
) -> bool:
    """POST *payload* to *webhook_url* with the standard retry policy.

    Returns True on success, False on terminal failure (any 4xx other than
    429, or retries exhausted).
    """

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
                    webhook_url, json=payload, headers={"User-Agent": USER_AGENT},
                )
        except httpx.HTTPError as e:
            log.warning("digest.network_error url=%s err=%s", webhook_url, e)
            raise _RetryableNotifyError(str(e)) from e

        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            log.warning("digest.retryable url=%s status=%d", webhook_url, resp.status_code)
            raise _RetryableNotifyError(f"status={resp.status_code}")
        if resp.status_code >= 400:
            raise NotifyError(
                f"discord error: status={resp.status_code} body={resp.text[:200]}"
            )

    try:
        _do()
        return True
    except (NotifyError, _RetryableNotifyError, RetryError) as e:
        log.warning("digest.failed url=%s err=%s", webhook_url, e)
        return False
