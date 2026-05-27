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

from cse_bot._http import USER_AGENT
from cse_bot.calendar_renderer import NEAR_AMBER, SOFT_BLUE, URGENT_RED
from cse_bot.category import CHIP_TAG_PALETTE, extract_category, is_important
from cse_bot.models import Post, TrackedDeadline, safe_iso_date, strip_category_prefix

log = logging.getLogger(__name__)

Format = Literal["minimal", "medium", "detailed"]


def _epoch_now() -> int:
    """Wallclock epoch in seconds (extracted for monkeypatching in tests)."""
    return int(time.time())


class NotifyError(Exception):
    """Raised when sending a Discord webhook fails terminally."""


class _RetryableNotifyError(Exception):
    pass


DISCORD_MAX = 2000


def _rgb_to_int(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return (r << 16) | (g << 8) | b


# Discord embed accent colors derived from the canonical RGB palette in
# calendar_renderer so the embed sidebar matches the strip PNG and chip tags.
URGENT_RED_HEX = _rgb_to_int(URGENT_RED)
NEAR_AMBER_HEX = _rgb_to_int(NEAR_AMBER)
DEFAULT_EMBED_HEX = _rgb_to_int(SOFT_BLUE)  # Discord blurple

CATEGORY_COLOR_HEX: dict[str, int] = {
    category: _rgb_to_int(rgb) for category, rgb in CHIP_TAG_PALETTE.items()
}

# Max upcoming deadlines surfaced as embed fields. Discord allows 25 max;
# we cap lower to keep the message compact and stay under embed total
# character limits.
MAX_DEADLINE_FIELDS = 5


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


def _pick_accent_color(upcoming: list[TrackedDeadline], today: date) -> int:
    """Pick an embed color signaling urgency at-a-glance in the channel list."""
    if not upcoming:
        return DEFAULT_EMBED_HEX
    first = upcoming[0]
    d_date = safe_iso_date(first.date)
    if d_date is None:
        return DEFAULT_EMBED_HEX
    delta = (d_date - today).days
    if delta <= 3:
        return URGENT_RED_HEX
    if delta <= 7:
        return NEAR_AMBER_HEX
    return CATEGORY_COLOR_HEX.get(first.category, DEFAULT_EMBED_HEX)


def _build_deadline_fields(
    upcoming: list[TrackedDeadline], today: date,
) -> list[dict[str, object]]:
    """Return Discord embed fields with clickable per-deadline links.

    Each field is full-width (``inline=False``) so the link line stays
    readable on mobile. The PNG strip above the fields already provides
    the at-a-glance scan; fields exist to make each title clickable.
    """
    fields: list[dict[str, object]] = []
    for d in upcoming[:MAX_DEADLINE_FIELDS]:
        d_date = safe_iso_date(d.date)
        if d_date is None:
            continue
        delta = (d_date - today).days
        if delta < 0:
            continue
        prefix = "🔥" if delta <= 3 else "📌"
        if delta == 0:
            d_tag = "오늘 마감"
        elif delta == 1:
            d_tag = "D-1"
        else:
            d_tag = f"D-{delta}"
        title = strip_category_prefix(d.title)
        if d.important:
            title = f"★ {title}"
        category_label = d.category or "일반공지"
        fields.append({
            "name": f"{prefix} {d_tag} · {category_label}",
            "value": (
                f"**{title}**\n"
                f"📅 {d.date} · [원문 보기 →]({d.url})"
            ),
            "inline": False,
        })
    return fields


def _format_upcoming_description(
    upcoming: list[TrackedDeadline], today: date
) -> str:
    """Concise embed description — counts only.

    Per-deadline detail lives in embed fields (with clickable links) and
    the strip PNG above; the description just surfaces the headline so
    the channel feed reveals urgency without an open-message scan.
    """
    if not upcoming:
        return "_추적 중인 마감 없음._"

    tomorrow = today + timedelta(days=1)
    d_minus_1_count = sum(1 for d in upcoming if d.date == tomorrow.isoformat())
    week_count = 0
    for d in upcoming:
        d_date = safe_iso_date(d.date)
        if d_date is None:
            continue
        delta = (d_date - today).days
        if 0 <= delta <= 7:
            week_count += 1

    parts: list[str] = []
    if d_minus_1_count:
        parts.append(f"⏰ **내일 마감 (D-1) {d_minus_1_count}건**")
    parts.append(
        f"📌 D-7 이내 {week_count}건" if week_count else "이번 주 마감 없음"
    )
    return " · ".join(parts)


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
        clean_title = strip_category_prefix(post.title)
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

    embed: dict[str, object] = {
        "title": f"📅 PNU CSE 마감일 캘린더 · {today.isoformat()}",
        "url": site_url,
        "color": _pick_accent_color(upcoming, today),
        "image": {"url": f"{calendar_png_url}?t={_epoch_now()}"},
        "description": _format_upcoming_description(upcoming, today),
        "footer": {
            "text": "매일 18:00 갱신 · 클릭하면 웹 캘린더로 이동",
        },
    }
    fields = _build_deadline_fields(upcoming, today)
    if fields:
        embed["fields"] = fields

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
