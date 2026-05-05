"""Summarize an article via Google Gemini multimodal REST API.

Returns SummaryResult on success or None on any failure so the caller can
fall back to title-only notification.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "cse-discord-bot/0.1"

PROMPT_TEMPLATE = (
    "다음은 부산대학교 컴퓨터공학과 공지사항이다. "
    "본문 텍스트와 첨부 이미지(있으면 OCR 활용)를 종합해 학생 입장에서 알아야 할 "
    "핵심 정보(날짜·시간·대상·방법)를 한국어 불릿 5줄 이내로 요약해라. "
    "본문에 신청·접수·제출 마감일이 명시되어 있으면 deadline 필드에 "
    "YYYY-MM-DD 형식으로 포함해라. 마감이 없거나 모호하면 null. "
    "마감이 여러 개면 가장 빠른 것.\n\n"
    "공지 본문:\n{body}"
)

ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

GENERATION_CONFIG = {
    "responseMimeType": "application/json",
    "responseSchema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "deadline": {"type": "string", "nullable": True},
        },
        "required": ["summary"],
    },
}


@dataclass(frozen=True)
class SummaryResult:
    summary: str
    deadline: str | None


def _guess_mime_type(url: str) -> str:
    lower = url.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def summarize(
    body: str,
    *,
    image_urls: Sequence[str] = (),
    api_key: str,
    model: str,
    timeout: float,
) -> SummaryResult | None:
    body = body.strip()
    if not body and not image_urls:
        return None

    parts: list[dict] = [
        {"text": PROMPT_TEMPLATE.format(body=body or "(본문 텍스트 없음)")}
    ]
    for url in image_urls:
        parts.append(
            {"fileData": {"mimeType": _guess_mime_type(url), "fileUri": url}}
        )

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": GENERATION_CONFIG,
    }
    endpoint = ENDPOINT_TEMPLATE.format(model=model)

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                endpoint,
                params={"key": api_key},
                json=payload,
                headers={"User-Agent": USER_AGENT},
            )
    except httpx.HTTPError as e:
        log.warning("summarize.network_error err=%s", e)
        return None

    if resp.status_code != 200:
        log.warning(
            "summarize.http_error status=%d body=%s",
            resp.status_code, resp.text[:200],
        )
        return None

    try:
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        text_parts = candidates[0].get("content", {}).get("parts") or []
        raw_text = "".join(p.get("text", "") for p in text_parts).strip()
        if not raw_text:
            return None
        parsed = json.loads(raw_text)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        log.warning("summarize.parse_error err=%s", e)
        return None

    summary = str(parsed.get("summary", "")).strip()
    if not summary:
        return None
    deadline_raw = parsed.get("deadline")
    deadline = str(deadline_raw).strip() if deadline_raw else None
    return SummaryResult(summary=summary, deadline=deadline)
