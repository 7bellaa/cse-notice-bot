"""Summarize article body via Google Gemini REST API.

Returns None on any failure so the caller can fall back to title-only notification.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "cse-discord-bot/0.1"

PROMPT_TEMPLATE = (
    "다음은 부산대학교 컴퓨터공학과 공지사항이다. "
    "학생 입장에서 알아야 할 핵심 정보(날짜·시간·대상·방법)를 한국어 불릿 5줄 이내로 요약해라. "
    "군더더기 인사말이나 도입 문구 없이 불릿만 출력해라.\n\n"
    "공지 본문:\n{body}"
)

ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def summarize(
    body: str,
    *,
    api_key: str,
    model: str,
    timeout: float,
) -> str | None:
    body = body.strip()
    if not body:
        return None

    url = ENDPOINT_TEMPLATE.format(model=model)
    payload = {
        "contents": [
            {"parts": [{"text": PROMPT_TEMPLATE.format(body=body)}]}
        ]
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                url,
                params={"key": api_key},
                json=payload,
                headers={"User-Agent": USER_AGENT},
            )
    except httpx.HTTPError as e:
        log.warning("summarize.network_error err=%s", e)
        return None

    if resp.status_code != 200:
        log.warning("summarize.http_error status=%d body=%s",
                    resp.status_code, resp.text[:200])
        return None

    try:
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except (ValueError, KeyError, IndexError, TypeError) as e:
        log.warning("summarize.parse_error err=%s", e)
        return None
