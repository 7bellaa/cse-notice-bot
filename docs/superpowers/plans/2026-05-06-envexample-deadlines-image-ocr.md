# `.env.example` + Deadline Reminders + Image OCR — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three small features bundled: (1) add `GEMINI_API_KEY` to `.env.example`; (2) extract a deadline alongside the summary in a single Gemini JSON call and emit one D-1 reminder per tracked deadline; (3) always include up to 3 article images in the multimodal Gemini call so image-only notices still summarize.

**Architecture:** Extend `summarizer.py` to use Gemini's structured JSON output (`responseMimeType: "application/json"`) returning `{summary, deadline}` and to accept `image_urls`. Extend `article.py` with `fetch_article_content` returning body + image URLs. New `reminder.py` module computes due reminders from `BoardState.deadlines`. `main.py` wires it all together: per new post → multimodal summarize → track deadline → send alert; per cycle → prune expired + dispatch D-1 reminders.

**Tech Stack:** Python 3.11, httpx, BeautifulSoup4 + lxml, pytest + respx + freezegun (already deps).

**Spec:** `docs/superpowers/specs/2026-05-06-envexample-deadlines-image-ocr-design.md`

---

## File Structure

| 파일 | 역할 | 상태 |
|---|---|---|
| `.env.example` | 새 `GEMINI_API_KEY` 라인 + 주석 | Modify |
| `src/cse_bot/models.py` | `TrackedDeadline` dataclass, `BoardState.deadlines` field | Modify |
| `src/cse_bot/state.py` | `deadlines` 직렬화/역직렬화 (없으면 빈 리스트) | Modify |
| `src/cse_bot/article.py` | `ArticleContent`, `fetch_article_content`, `extract_image_urls` | Modify |
| `src/cse_bot/summarizer.py` | `SummaryResult`, JSON response schema, `image_urls` 파라미터 | Modify |
| `src/cse_bot/reminder.py` | `collect_due_reminders`, `prune_expired`, `format_reminder` | **Create** |
| `src/cse_bot/notifier.py` | `send_alert_to_webhooks` helper | Modify |
| `src/cse_bot/main.py` | image_urls 전달, deadline 트래킹, 리마인더 발송 | Modify |
| `tests/test_state.py` | `deadlines` 라운드트립 + 구버전 호환 | Modify (or create if missing) |
| `tests/test_article.py` | `extract_image_urls`, `fetch_article_content` | Modify |
| `tests/test_summarizer.py` | JSON 응답, deadline, image_urls | Modify |
| `tests/test_reminder.py` | due/prune 로직 | **Create** |
| `tests/test_notifier.py` | `send_alert_to_webhooks` | Modify |

---

## Task 1: Update `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Append GEMINI_API_KEY line**

Replace `.env.example` content with:
```
DISCORD_WEBHOOK_GENERAL=https://discord.com/api/webhooks/REPLACE_ME
DISCORD_WEBHOOK_ALERT=https://discord.com/api/webhooks/REPLACE_ME

# Get a free key from https://aistudio.google.com/
GEMINI_API_KEY=AIza...REPLACE_ME
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(env): add GEMINI_API_KEY to .env.example"
```

---

## Task 2: `BoardState.deadlines` + `TrackedDeadline` model

**Files:**
- Modify: `src/cse_bot/models.py`
- Modify: `src/cse_bot/state.py`
- Modify (or Create): `tests/test_state.py`

- [ ] **Step 1: Write failing tests**

Find or create `tests/test_state.py`. Add:

```python
from datetime import datetime
from pathlib import Path

from cse_bot.models import BoardState, TrackedDeadline
from cse_bot.state import load_state, save_state


def test_state_roundtrip_with_deadlines(tmp_path: Path):
    p = tmp_path / "s.json"
    s = {
        "14221": BoardState(
            last_max_post_id=100,
            last_checked="2026-05-06T09:00:00+09:00",
            empty_streak=0,
            deadlines=[
                TrackedDeadline(
                    post_id=42, title="t", url="https://x",
                    date="2026-05-14", reminded=False,
                )
            ],
        ),
    }
    save_state(p, s)
    loaded = load_state(p)
    assert loaded["14221"].deadlines == s["14221"].deadlines


def test_state_load_legacy_without_deadlines_field(tmp_path: Path):
    p = tmp_path / "s.json"
    p.write_text(
        '{"14221":{"last_max_post_id":100,"last_checked":"x","empty_streak":0}}',
        encoding="utf-8",
    )
    loaded = load_state(p)
    assert loaded["14221"].deadlines == []


def test_state_save_omits_deadlines_when_empty_list_is_fine(tmp_path: Path):
    """Empty deadlines list is still persisted, just as []."""
    p = tmp_path / "s.json"
    save_state(p, {
        "14221": BoardState(
            last_max_post_id=1, last_checked="x", empty_streak=0, deadlines=[]
        )
    })
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["14221"]["deadlines"] == []
```

- [ ] **Step 2: Verify tests fail**

```
.venv/bin/pytest tests/test_state.py -v
```
Expected: FAIL (`TrackedDeadline` import / `deadlines` field missing).

- [ ] **Step 3: Add `TrackedDeadline` to `models.py`**

In `src/cse_bot/models.py`, add (after `BoardConfig`):

```python
from dataclasses import field


@dataclass
class TrackedDeadline:
    post_id: int
    title: str
    url: str
    date: str        # ISO YYYY-MM-DD
    reminded: bool = False
```

Update `BoardState`:

```python
@dataclass
class BoardState:
    last_max_post_id: int | None
    last_checked: str
    empty_streak: int = 0
    deadlines: list[TrackedDeadline] = field(default_factory=list)
```

- [ ] **Step 4: Update `state.py` serialization**

Open `src/cse_bot/state.py`. The current `load_state` constructs `BoardState` from a dict. Update it to also handle `deadlines`:

```python
# In load_state, when constructing BoardState from per-board dict:
deadlines_raw = b.get("deadlines", [])
deadlines = [
    TrackedDeadline(
        post_id=int(d["post_id"]),
        title=str(d["title"]),
        url=str(d["url"]),
        date=str(d["date"]),
        reminded=bool(d.get("reminded", False)),
    )
    for d in deadlines_raw
]
state[board_id] = BoardState(
    last_max_post_id=...,
    last_checked=...,
    empty_streak=...,
    deadlines=deadlines,
)
```

In `save_state`, serialize `deadlines` to list of dicts:

```python
"deadlines": [
    {
        "post_id": d.post_id, "title": d.title, "url": d.url,
        "date": d.date, "reminded": d.reminded,
    }
    for d in board_state.deadlines
],
```

(Read the current `state.py` first to see exact structure — adapt these fragments to the existing helper.)

- [ ] **Step 5: Verify tests pass**

```
.venv/bin/pytest tests/test_state.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/cse_bot/models.py src/cse_bot/state.py tests/test_state.py
git commit -m "feat(state): TrackedDeadline + BoardState.deadlines field"
```

---

## Task 3: Article — `fetch_article_content` with images

**Files:**
- Modify: `src/cse_bot/article.py`
- Modify: `tests/test_article.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_article.py`:

```python
from cse_bot.article import (
    ArticleContent, extract_image_urls, fetch_article_content,
)


def test_extract_image_urls_finds_first_three_in_body():
    html = """
    <html><body>
      <div class="board-view">
        <div class="title"><img src="/icon.png"></div>
        <div class="txt">
          <img src="/upload/a.jpg">
          <img src="https://x/b.png">
          <img src="/upload/c.gif">
          <img src="/upload/d.jpg">
        </div>
      </div>
    </body></html>
    """
    urls = extract_image_urls(html, base_url="https://cse.pusan.ac.kr/x", limit=3)
    assert len(urls) == 3
    assert urls[0] == "https://cse.pusan.ac.kr/upload/a.jpg"
    assert urls[1] == "https://x/b.png"
    assert urls[2] == "https://cse.pusan.ac.kr/upload/c.gif"
    # icon.png is in .title (not .txt) → excluded


def test_extract_image_urls_returns_empty_when_no_images():
    html = '<div class="board-view"><div class="txt">no images here</div></div>'
    assert extract_image_urls(html, base_url="https://x/y", limit=3) == []


@respx.mock
def test_fetch_article_content_returns_body_and_images():
    html = """
    <div class="board-view"><div class="txt">
      <p>hello world</p><img src="/u/a.jpg">
    </div></div>
    """
    respx.get("https://cse.pusan.ac.kr/p").mock(
        return_value=httpx.Response(200, text=html)
    )
    content = fetch_article_content(
        "https://cse.pusan.ac.kr/p", timeout=2.0, retries=1,
    )
    assert isinstance(content, ArticleContent)
    assert "hello world" in content.body
    assert content.image_urls == ["https://cse.pusan.ac.kr/u/a.jpg"]


@respx.mock
def test_fetch_article_content_returns_none_on_5xx():
    respx.get("https://x/y").mock(return_value=httpx.Response(503))
    assert fetch_article_content("https://x/y", timeout=1.0, retries=1) is None
```

- [ ] **Step 2: Verify tests fail**

```
.venv/bin/pytest tests/test_article.py -v
```
Expected: FAIL (`ArticleContent` / `extract_image_urls` / `fetch_article_content` missing).

- [ ] **Step 3: Implement in `article.py`**

Add to `src/cse_bot/article.py` (keep existing `extract_body` / `fetch_article_body`):

```python
from dataclasses import dataclass
from urllib.parse import urljoin


@dataclass(frozen=True)
class ArticleContent:
    body: str
    image_urls: list[str]


def extract_image_urls(html: str, *, base_url: str, limit: int = 3) -> list[str]:
    """Return absolute URLs of the first `limit` <img> tags inside `.board-view .txt`."""
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one(".board-view .txt")
    if container is None:
        return []
    urls: list[str] = []
    for img in container.find_all("img"):
        src = img.get("src", "")
        if not isinstance(src, str) or not src:
            continue
        urls.append(urljoin(base_url, src))
        if len(urls) >= limit:
            break
    return urls


def fetch_article_content(
    url: str, *, timeout: float, retries: int,
) -> ArticleContent | None:
    """GET the article and return body + first 3 image URLs, or None on failure."""
    attempts = max(1, retries)
    html: str | None = None
    for i in range(attempts):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            log.warning("article.network_error url=%s err=%s", url, e)
            if i == attempts - 1:
                return None
            continue
        if 500 <= resp.status_code < 600:
            log.warning("article.retryable status=%d", resp.status_code)
            if i == attempts - 1:
                return None
            continue
        if resp.status_code >= 400:
            log.warning("article.client_error status=%d", resp.status_code)
            return None
        html = resp.text
        break
    if html is None:
        return None
    body = extract_body(html) or ""
    images = extract_image_urls(html, base_url=url, limit=3)
    if not body and not images:
        return None
    return ArticleContent(body=body, image_urls=images)
```

Existing `fetch_article_body` stays for back-compat / its own tests.

The test file imports `httpx` and `respx` — make sure those imports already exist at the top (they do, from earlier tests).

- [ ] **Step 4: Verify tests pass**

```
.venv/bin/pytest tests/test_article.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/article.py tests/test_article.py
git commit -m "feat(article): extract image URLs alongside body via fetch_article_content"
```

---

## Task 4: Summarizer — JSON output + multimodal `image_urls`

**Files:**
- Modify: `src/cse_bot/summarizer.py`
- Modify: `tests/test_summarizer.py`

- [ ] **Step 1: Replace tests in `test_summarizer.py`**

The existing tests assume `summarize` returns `str | None`. Rewrite all of them for the new `SummaryResult` shape. Replace the entire content of `tests/test_summarizer.py` with:

```python
import httpx
import respx

from cse_bot.summarizer import SummaryResult, summarize

ENDPOINT_RE = (
    r"https://generativelanguage\.googleapis\.com/v1beta/models/"
    r"gemini-2\.5-flash-lite:generateContent.*"
)


def _gemini_response(payload_text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": payload_text}]}}]},
    )


@respx.mock
def test_summarize_parses_json_with_summary_and_deadline():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=_gemini_response(
            '{"summary": "- 5/12 시작\\n- 학년별 차등", "deadline": "2026-05-14"}'
        )
    )
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=2.0)
    assert isinstance(out, SummaryResult)
    assert out.summary == "- 5/12 시작\n- 학년별 차등"
    assert out.deadline == "2026-05-14"


@respx.mock
def test_summarize_handles_null_deadline():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=_gemini_response('{"summary": "- bullet", "deadline": null}')
    )
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=2.0)
    assert out is not None
    assert out.summary == "- bullet"
    assert out.deadline is None


@respx.mock
def test_summarize_handles_missing_deadline_key():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=_gemini_response('{"summary": "- bullet"}')
    )
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=2.0)
    assert out is not None
    assert out.summary == "- bullet"
    assert out.deadline is None


@respx.mock
def test_summarize_returns_none_on_429():
    respx.post(url__regex=ENDPOINT_RE).mock(return_value=httpx.Response(429))
    assert summarize("b", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


@respx.mock
def test_summarize_returns_none_on_5xx():
    respx.post(url__regex=ENDPOINT_RE).mock(return_value=httpx.Response(500))
    assert summarize("b", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


@respx.mock
def test_summarize_returns_none_on_timeout():
    respx.post(url__regex=ENDPOINT_RE).mock(side_effect=httpx.TimeoutException("t"))
    assert summarize("b", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


@respx.mock
def test_summarize_returns_none_when_text_is_not_json():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=_gemini_response("this is not JSON at all")
    )
    assert summarize("b", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


@respx.mock
def test_summarize_returns_none_on_empty_candidates():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=httpx.Response(200, json={"candidates": []})
    )
    assert summarize("b", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


def test_summarize_returns_none_for_empty_body_and_no_images():
    assert summarize("", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


@respx.mock
def test_summarize_includes_image_urls_in_payload():
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json
        captured["body"] = json.loads(request.content)
        return _gemini_response('{"summary": "- s", "deadline": null}')

    respx.post(url__regex=ENDPOINT_RE).mock(side_effect=_capture)

    out = summarize(
        "body text",
        image_urls=["https://x/a.jpg", "https://x/b.png"],
        api_key="k", model="gemini-2.5-flash-lite", timeout=2.0,
    )
    assert out is not None
    parts = captured["body"]["contents"][0]["parts"]
    file_parts = [p for p in parts if "fileData" in p or "file_data" in p]
    assert len(file_parts) == 2


@respx.mock
def test_summarize_calls_api_with_image_only_input():
    """Even with empty body, if image_urls are given, summarize should still call API."""
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json
        captured["body"] = json.loads(request.content)
        return _gemini_response('{"summary": "- image content", "deadline": null}')

    respx.post(url__regex=ENDPOINT_RE).mock(side_effect=_capture)
    out = summarize(
        "",
        image_urls=["https://x/a.jpg"],
        api_key="k", model="gemini-2.5-flash-lite", timeout=2.0,
    )
    assert out is not None
    assert out.summary == "- image content"
```

- [ ] **Step 2: Verify tests fail**

```
.venv/bin/pytest tests/test_summarizer.py -v
```
Expected: FAIL (`SummaryResult` doesn't exist; current `summarize` returns string).

- [ ] **Step 3: Rewrite `summarizer.py`**

Replace `src/cse_bot/summarizer.py` with:

```python
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
```

> Note on Gemini `fileData` for external URLs: at the time of writing, `fileData.fileUri` accepts external HTTPS URLs for public images on Gemini 2.5 Flash-Lite. If smoke tests later show the API rejects external URLs, switch to inline base64 (`inlineData.data` + `inlineData.mimeType`) by downloading the image first. This is a runtime-discoverable concern, not blocking the plan.

- [ ] **Step 4: Verify all tests pass**

```
.venv/bin/pytest tests/test_summarizer.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/summarizer.py tests/test_summarizer.py
git commit -m "feat(summarizer): JSON output with deadline + multimodal image_urls"
```

---

## Task 5: `reminder.py` module

**Files:**
- Create: `src/cse_bot/reminder.py`
- Create: `tests/test_reminder.py`

DEPENDS ON Task 2 (uses `TrackedDeadline`, `BoardState`).

- [ ] **Step 1: Write failing tests**

`tests/test_reminder.py`:

```python
from datetime import date

from cse_bot.models import BoardState, TrackedDeadline
from cse_bot.reminder import (
    collect_due_reminders, format_reminder, prune_expired,
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
```

- [ ] **Step 2: Verify tests fail**

```
.venv/bin/pytest tests/test_reminder.py -v
```

- [ ] **Step 3: Implement `reminder.py`**

`src/cse_bot/reminder.py`:

```python
"""Compute and format due deadline reminders.

A deadline is "due" if today + 1 day == deadline.date and `reminded` is False.
Past deadlines are pruned at the start of each cycle.
"""
from __future__ import annotations

from datetime import date, timedelta

from cse_bot.models import BoardState, TrackedDeadline


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
            try:
                d_date = date.fromisoformat(d.date)
            except ValueError:
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
            try:
                d_date = date.fromisoformat(d.date)
            except ValueError:
                # Drop unparseable dates as well.
                removed += 1
                continue
            if d_date < today:
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
```

- [ ] **Step 4: Verify tests pass**

```
.venv/bin/pytest tests/test_reminder.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/reminder.py tests/test_reminder.py
git commit -m "feat(reminder): D-1 deadline reminder collection + pruning"
```

---

## Task 6: Notifier — `send_alert_to_webhooks`

**Files:**
- Modify: `src/cse_bot/notifier.py`
- Modify: `tests/test_notifier.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_notifier.py`:

```python
from cse_bot.notifier import send_alert_to_webhooks


@respx.mock
def test_send_alert_to_webhooks_all_success():
    respx.post("https://a").mock(return_value=httpx.Response(204))
    respx.post("https://b").mock(return_value=httpx.Response(204))
    ok, failed = send_alert_to_webhooks(
        "⏰ 내일 마감: t",
        webhook_urls=["https://a", "https://b"],
        timeout=2.0, retries=1,
    )
    assert ok == 2 and failed == []


@respx.mock
def test_send_alert_to_webhooks_partial_failure():
    respx.post("https://a").mock(return_value=httpx.Response(204))
    respx.post("https://b").mock(return_value=httpx.Response(403))
    ok, failed = send_alert_to_webhooks(
        "msg",
        webhook_urls=["https://a", "https://b"],
        timeout=2.0, retries=1,
    )
    assert ok == 1 and failed == ["https://b"]


@respx.mock
def test_send_alert_to_webhooks_truncates_long_content():
    captured: dict = {}

    def _cap(request: httpx.Request) -> httpx.Response:
        import json
        captured["json"] = json.loads(request.content)
        return httpx.Response(204)

    respx.post("https://a").mock(side_effect=_cap)
    huge = "x" * 5000
    send_alert_to_webhooks(huge, webhook_urls=["https://a"], timeout=2.0, retries=1)
    assert len(captured["json"]["content"]) <= 2000
```

- [ ] **Step 2: Verify tests fail**

```
.venv/bin/pytest tests/test_notifier.py -v
```

- [ ] **Step 3: Add `send_alert_to_webhooks` to `notifier.py`**

```python
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
```

- [ ] **Step 4: Verify tests pass**

```
.venv/bin/pytest tests/test_notifier.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/notifier.py tests/test_notifier.py
git commit -m "feat(notifier): send_alert_to_webhooks for non-post messages"
```

---

## Task 7: Wire everything into `main.py`

**Files:**
- Modify: `src/cse_bot/main.py`
- Modify: `tests/test_main.py` (if it exists and breaks)

DEPENDS ON Tasks 2, 3, 4, 5, 6.

- [ ] **Step 1: Verify all 6 prior commits exist**

```
git log --oneline -10
```
Confirm the last 6 feature commits from Tasks 1-6 are present.

- [ ] **Step 2: Update imports**

In `src/cse_bot/main.py`, update top-of-file imports:

```python
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from cse_bot import (
    article, differ, fetcher, notifier, parser, reminder, state, summarizer,
)
from cse_bot.models import BoardConfig, BoardState, Post, TrackedDeadline
```

Add a constant near the top:

```python
KST = ZoneInfo("Asia/Seoul")
```

- [ ] **Step 3: Replace per-post block in `_process_board`**

Locate the per-post block written in the previous feature plan (Task 6 of the multi-webhook plan). Replace it with:

```python
    webhook_urls = cfg.webhook_urls(board.id)
    today = datetime.now(KST).date()

    for post in new_posts:
        content = article.fetch_article_content(
            post.url,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        body = content.body if content else ""
        images = content.image_urls if content else []
        result = (
            summarizer.summarize(
                body,
                image_urls=images,
                api_key=cfg.gemini.api_key,
                model=cfg.gemini.model,
                timeout=cfg.gemini.timeout_seconds,
            )
            if (body or images)
            else None
        )
        summary = result.summary if result else None

        ok_count, failed_urls = notifier.send_to_webhooks(
            post,
            webhook_urls=webhook_urls,
            summary=summary,
            fmt=cfg.notification.format,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        if ok_count == 0:
            raise notifier.NotifyError(
                f"all webhooks failed for post {post.id}"
            )
        if failed_urls:
            _safe_alert(
                cfg,
                f"post {post.id}: {len(failed_urls)}/"
                f"{ok_count + len(failed_urls)} webhooks failed",
            )

        if result and result.deadline:
            try:
                d_date = date.fromisoformat(result.deadline)
                if d_date > today:
                    board_state.deadlines.append(
                        TrackedDeadline(
                            post_id=post.id, title=post.title, url=post.url,
                            date=result.deadline, reminded=False,
                        )
                    )
            except ValueError:
                log.warning(
                    "deadline.invalid_format post_id=%d raw=%r",
                    post.id, result.deadline,
                )

        board_state.last_max_post_id = post.id
        state_map[board.id] = board_state
        state.save_state(state_path, state_map)
        log.info(
            "notify.ok board=%s post_id=%d webhooks_ok=%d webhooks_failed=%d "
            "summary=%s deadline=%s",
            board.id, post.id, ok_count, len(failed_urls),
            "yes" if summary else "no",
            result.deadline if (result and result.deadline) else "no",
        )
```

- [ ] **Step 4: Add reminder dispatch at end of `run_cycle`**

In `run_cycle`, BEFORE the final `state.save_state(state_path, state_map)`, add:

```python
    # Deadline reminders: prune expired, then send any D-1 reminders for today.
    today = datetime.now(KST).date()
    pruned = reminder.prune_expired(state_map, today=today)
    if pruned:
        log.info("deadlines.pruned count=%d", pruned)
    due = reminder.collect_due_reminders(state_map, today=today)
    for board_id, deadline in due:
        try:
            urls = cfg.webhook_urls(board_id)
        except ConfigError:
            log.warning("reminder.no_webhooks board=%s", board_id)
            continue
        msg = reminder.format_reminder(deadline)
        ok, failed = notifier.send_alert_to_webhooks(
            msg,
            webhook_urls=urls,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        if ok > 0:
            deadline.reminded = True
            log.info(
                "reminder.sent board=%s post_id=%d webhooks_ok=%d webhooks_failed=%d",
                board_id, deadline.post_id, ok, len(failed),
            )
        if failed:
            _safe_alert(
                cfg,
                f"reminder for post {deadline.post_id}: "
                f"{len(failed)}/{ok + len(failed)} webhooks failed",
            )
```

Make sure `ConfigError` is imported in main.py (it already is via `from cse_bot.config import Config, ConfigError, load_config`).

- [ ] **Step 5: Run full suite + ruff**

```
.venv/bin/pytest -q
.venv/bin/ruff check .
```

If any test in `tests/test_main.py` exists and references the old `summarizer.summarize → str` shape, update it to `SummaryResult`. If `tests/test_main.py` references `article.fetch_article_body`, change to `article.fetch_article_content` returning `ArticleContent`.

- [ ] **Step 6: Commit**

```bash
git add src/cse_bot/main.py tests/test_main.py
git commit -m "feat(main): multimodal summarize + deadline tracking + D-1 reminder dispatch"
```

(If `tests/test_main.py` was untouched, just stage `main.py`.)

---

## Self-Review (writer-side, completed)

- **Spec coverage:** §3 → Task 1; §4.1-4.2 → Tasks 2 (state), 4 (summarizer JSON+deadline); §4.3 → Task 5; §4.4 → Task 7; §4.5 → encoded in `reminded` flag check (Task 5) + Task 7 mark-after-send; §4.6 KST → Task 7 (`KST` const + `today`); §5 → Tasks 3 (article images) + 4 (multimodal payload) + 7 (wiring); §6 error matrix → Tasks 4-7 (None fallback, invalid date guard, legacy state field default).
- **Placeholder scan:** none — every step has concrete code, file paths, and expected pytest output.
- **Type consistency:** `SummaryResult.deadline: str | None` (Task 4) ↔ `result.deadline` consumed in main.py with `try: date.fromisoformat()` (Task 7). `ArticleContent` (Task 3) ↔ `content.body / content.image_urls` (Task 7). `TrackedDeadline.reminded: bool` (Task 2) ↔ `deadline.reminded = True` after send (Task 7) ↔ `if d.reminded: continue` (Task 5). All names align.

## Out of Scope (re-confirmed)
- D-3 / D-day reminders, multiple deadlines, backfill of historical posts, OCR caching, image download, PDF/attachment OCR.
