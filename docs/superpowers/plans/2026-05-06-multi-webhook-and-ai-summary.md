# Multi-Webhook Fan-out + Gemini AI Summary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 게시판 새 글 1건을 N개 Discord 웹훅에 fan-out하고, Gemini 2.5 Flash-Lite로 본문을 5줄 이내 한국어 불릿 요약하여 알림에 포함한다. 요약/일부 웹훅 실패 시 best-effort fallback.

**Architecture:** 신규 모듈 2개 (`article.py` 본문 추출, `summarizer.py` Gemini 호출) + `notifier.py`에 fan-out 함수 추가 + `config.py`/`models.py` 스키마 확장. main.py는 각 새 글마다 본문→요약→fan-out 순으로 호출. 모든 외부 호출 실패는 `None` 또는 부분실패로 흡수해 알림 자체는 끊기지 않게 한다.

**Tech Stack:** Python 3.11, httpx, BeautifulSoup4 + lxml, tenacity (이미 설치됨), pytest + respx (이미 설치됨).

**Spec:** `docs/superpowers/specs/2026-05-06-multi-webhook-and-ai-summary-design.md`

---

## File Structure

| 파일 | 역할 | 상태 |
|---|---|---|
| `src/cse_bot/models.py` | `BoardConfig.webhook_envs: list[str]` | Modify |
| `src/cse_bot/config.py` | `GeminiConfig`, `Config.webhook_urls()`, `[gemini]` 파싱 | Modify |
| `src/cse_bot/article.py` | 게시물 상세 페이지 → 본문 텍스트 | **Create** |
| `src/cse_bot/summarizer.py` | Gemini REST 호출 → 요약 또는 None | **Create** |
| `src/cse_bot/notifier.py` | `send_to_webhooks` fan-out + summary 렌더링 | Modify |
| `src/cse_bot/main.py` | `_process_board` 안에서 article→summarize→fan-out 와이어링 | Modify |
| `config/config.toml` | `[gemini]` 섹션 + `webhook_envs` 변경 | Modify |
| `tests/test_article.py` | 본문 추출 검증 | **Create** |
| `tests/test_summarizer.py` | Gemini API mock 케이스 | **Create** |
| `tests/test_notifier.py` | `send_to_webhooks`, summary 포맷 | Modify |
| `tests/test_config.py` | webhook_envs 리스트, gemini 섹션 | Modify |
| `tests/fixtures/article_sample.html` | 실제 article HTML 픽스처 | **Create** |

---

## Task 1: Config schema — `webhook_envs: list[str]`

**Files:**
- Modify: `src/cse_bot/models.py`
- Modify: `src/cse_bot/config.py`
- Modify: `tests/test_config.py`
- Modify: `config/config.toml`

- [ ] **Step 1: Write failing tests for `webhook_envs` list parsing**

`tests/test_config.py`에 추가 (기존 import는 그대로 활용):

```python
def test_load_config_accepts_webhook_envs_list(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_A", "https://a")
    monkeypatch.setenv("DISCORD_WEBHOOK_B", "https://b")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://alert")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(
        '[general]\n'
        'log_dir = "logs"\nstate_file = "data/state.json"\n'
        'max_pages = 1\nhttp_timeout_seconds = 5\nhttp_retries = 1\n'
        '[notification]\n'
        'format = "medium"\nself_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"\n'
        '[gemini]\n'
        'api_key_env = "GEMINI_API_KEY"\n'
        'model = "gemini-2.5-flash-lite"\n'
        'timeout_seconds = 10\n'
        '[[boards]]\n'
        'id = "1"\nname = "n"\nurl = "https://x"\n'
        'webhook_envs = ["DISCORD_WEBHOOK_A", "DISCORD_WEBHOOK_B"]\n',
        encoding="utf-8",
    )
    from cse_bot.config import load_config
    cfg = load_config(cfg_path)
    assert cfg.webhook_urls("1") == ["https://a", "https://b"]


def test_load_config_rejects_empty_webhook_envs(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://alert")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(
        '[general]\n'
        'log_dir = "logs"\nstate_file = "data/state.json"\n'
        'max_pages = 1\nhttp_timeout_seconds = 5\nhttp_retries = 1\n'
        '[notification]\n'
        'format = "medium"\nself_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"\n'
        '[gemini]\n'
        'api_key_env = "GEMINI_API_KEY"\n'
        'model = "gemini-2.5-flash-lite"\n'
        'timeout_seconds = 10\n'
        '[[boards]]\n'
        'id = "1"\nname = "n"\nurl = "https://x"\nwebhook_envs = []\n',
        encoding="utf-8",
    )
    from cse_bot.config import ConfigError, load_config
    import pytest
    with pytest.raises(ConfigError):
        load_config(cfg_path)
```

(기존 `test_config.py`에 단일 `webhook_env` 테스트가 있다면 삭제 — 스키마가 바뀜.)

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest tests/test_config.py -v
```
Expected: FAIL (`webhook_envs` not handled, `Config.webhook_urls` doesn't exist)

- [ ] **Step 3: Update `BoardConfig` in `models.py`**

`src/cse_bot/models.py` 수정:

```python
@dataclass(frozen=True)
class BoardConfig:
    id: str
    name: str
    url: str
    webhook_envs: list[str]
    enabled: bool = True
```

- [ ] **Step 4: Update `Config` dataclass and loader in `config.py`**

`src/cse_bot/config.py` 변경 사항:

```python
@dataclass(frozen=True)
class Config:
    general: GeneralConfig
    notification: NotificationConfig
    boards: list[BoardConfig]
    _webhook_urls: dict[str, list[str]]
    alert_webhook_url: str

    def webhook_urls(self, board_id: str) -> list[str]:
        try:
            return self._webhook_urls[board_id]
        except KeyError as e:
            raise ConfigError(f"no webhook resolved for board {board_id}") from e
```

`load_config`의 webhook 해석 부분:

```python
    webhook_urls: dict[str, list[str]] = {}
    for b in boards:
        if not b.enabled:
            continue
        urls: list[str] = []
        for env_name in b.webhook_envs:
            url = os.environ.get(env_name)
            if not url:
                raise ConfigError(
                    f"environment variable {env_name} is required for board {b.id}"
                )
            urls.append(url)
        webhook_urls[b.id] = urls
```

`_load_boards` 수정:

```python
def _load_boards(raw: dict[str, Any]) -> list[BoardConfig]:
    items: list[Any] = raw.get("boards") or []
    if not items:
        raise ConfigError("at least one [[boards]] entry is required")
    boards: list[BoardConfig] = []
    for i, b in enumerate(items):
        try:
            envs = b["webhook_envs"]
        except KeyError as e:
            raise ConfigError(f"[[boards]] index {i}: missing key {e.args[0]}") from e
        if not isinstance(envs, list) or not all(isinstance(x, str) for x in envs):
            raise ConfigError(f"[[boards]] index {i}: webhook_envs must be a list of strings")
        if not envs:
            raise ConfigError(f"[[boards]] index {i}: webhook_envs must not be empty")
        try:
            boards.append(
                BoardConfig(
                    id=str(b["id"]),
                    name=str(b["name"]),
                    url=str(b["url"]),
                    webhook_envs=list(envs),
                    enabled=bool(b.get("enabled", True)),
                )
            )
        except KeyError as e:
            raise ConfigError(f"[[boards]] index {i}: missing key {e.args[0]}") from e
    return boards
```

- [ ] **Step 5: Update `config/config.toml`**

```toml
[[boards]]
id = "14221"
name = "정컴 일반공지"
url = "https://cse.pusan.ac.kr/cse/14221/subview.do"
webhook_envs = ["DISCORD_WEBHOOK_GENERAL"]
enabled = true
```

- [ ] **Step 6: Run config tests, verify pass**

```
.venv/bin/pytest tests/test_config.py -v
```
Expected: PASS for both new tests. Other config tests unchanged should still pass.

- [ ] **Step 7: Commit**

```bash
git add src/cse_bot/models.py src/cse_bot/config.py tests/test_config.py config/config.toml
git commit -m "refactor(config): webhook_envs as list to support fan-out"
```

---

## Task 2: Add `[gemini]` config section + `GeminiConfig`

**Files:**
- Modify: `src/cse_bot/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

`tests/test_config.py`에 추가:

```python
def test_load_config_parses_gemini_section(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_A", "https://a")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://alert")
    monkeypatch.setenv("MY_GEMINI", "secret-key")
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(
        '[general]\n'
        'log_dir = "logs"\nstate_file = "data/state.json"\n'
        'max_pages = 1\nhttp_timeout_seconds = 5\nhttp_retries = 1\n'
        '[notification]\n'
        'format = "medium"\nself_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"\n'
        '[gemini]\n'
        'api_key_env = "MY_GEMINI"\n'
        'model = "gemini-2.5-flash-lite"\n'
        'timeout_seconds = 8\n'
        '[[boards]]\n'
        'id = "1"\nname = "n"\nurl = "https://x"\n'
        'webhook_envs = ["DISCORD_WEBHOOK_A"]\n',
        encoding="utf-8",
    )
    from cse_bot.config import load_config
    cfg = load_config(cfg_path)
    assert cfg.gemini.api_key == "secret-key"
    assert cfg.gemini.model == "gemini-2.5-flash-lite"
    assert cfg.gemini.timeout_seconds == 8


def test_load_config_missing_gemini_key_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_A", "https://a")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://alert")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(
        '[general]\n'
        'log_dir = "logs"\nstate_file = "data/state.json"\n'
        'max_pages = 1\nhttp_timeout_seconds = 5\nhttp_retries = 1\n'
        '[notification]\n'
        'format = "medium"\nself_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"\n'
        '[gemini]\n'
        'api_key_env = "GEMINI_API_KEY"\n'
        'model = "gemini-2.5-flash-lite"\n'
        'timeout_seconds = 10\n'
        '[[boards]]\n'
        'id = "1"\nname = "n"\nurl = "https://x"\n'
        'webhook_envs = ["DISCORD_WEBHOOK_A"]\n',
        encoding="utf-8",
    )
    from cse_bot.config import ConfigError, load_config
    import pytest
    with pytest.raises(ConfigError):
        load_config(cfg_path)
```

- [ ] **Step 2: Verify tests fail**

```
.venv/bin/pytest tests/test_config.py::test_load_config_parses_gemini_section tests/test_config.py::test_load_config_missing_gemini_key_env -v
```
Expected: FAIL (`Config.gemini` doesn't exist)

- [ ] **Step 3: Add `GeminiConfig` and parsing**

`src/cse_bot/config.py`에 추가:

```python
@dataclass(frozen=True)
class GeminiConfig:
    api_key: str
    model: str
    timeout_seconds: float
```

`Config`에 필드 추가:

```python
@dataclass(frozen=True)
class Config:
    general: GeneralConfig
    notification: NotificationConfig
    gemini: GeminiConfig
    boards: list[BoardConfig]
    _webhook_urls: dict[str, list[str]]
    alert_webhook_url: str

    def webhook_urls(self, board_id: str) -> list[str]: ...  # unchanged
```

`load_config`에서 호출 (기존 alert 검증 다음에):

```python
    gemini = _load_gemini(raw)
    ...
    return Config(
        general=general,
        notification=notification,
        gemini=gemini,
        boards=boards,
        _webhook_urls=webhook_urls,
        alert_webhook_url=alert_url,
    )
```

새 함수:

```python
def _load_gemini(raw: dict[str, Any]) -> GeminiConfig:
    g: dict[str, Any] = raw.get("gemini") or {}
    if not g:
        raise ConfigError("[gemini] section is required")
    try:
        api_key_env = str(g["api_key_env"])
        model = str(g["model"])
        timeout = float(g["timeout_seconds"])
    except KeyError as e:
        raise ConfigError(f"missing [gemini] key: {e.args[0]}") from e
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise ConfigError(f"environment variable {api_key_env} is required (gemini)")
    return GeminiConfig(api_key=api_key, model=model, timeout_seconds=timeout)
```

- [ ] **Step 4: Update `config/config.toml`**

```toml
[gemini]
api_key_env = "GEMINI_API_KEY"
model = "gemini-2.5-flash-lite"
timeout_seconds = 10
```

- [ ] **Step 5: Verify all config tests pass**

```
.venv/bin/pytest tests/test_config.py -v
```

Other tests in `test_config.py` may need their toml fixtures updated to include the `[gemini]` section + `GEMINI_API_KEY` env. Update them in this step.

- [ ] **Step 6: Commit**

```bash
git add src/cse_bot/config.py tests/test_config.py config/config.toml
git commit -m "feat(config): add [gemini] section with api_key_env/model/timeout"
```

---

## Task 3: Article body fetcher (`article.py`)

**Files:**
- Create: `src/cse_bot/article.py`
- Create: `tests/fixtures/article_sample.html`
- Create: `tests/test_article.py`

The body selector inside the rendered article page is `.board-view .txt` (verified against a real PNU CSE post). Title/metadata/attachment are siblings under `.view.viewCont` and must be excluded.

- [ ] **Step 1: Capture a real article HTML fixture**

```bash
curl -s -A "cse-discord-bot/0.1" \
  "https://cse.pusan.ac.kr/bbs/cse/2055/1389652/artclView.do" \
  -o tests/fixtures/article_sample.html
test -s tests/fixtures/article_sample.html
```

- [ ] **Step 2: Write failing tests**

`tests/test_article.py`:

```python
from pathlib import Path

import httpx
import pytest
import respx

from cse_bot.article import extract_body, fetch_article_body

FIXTURE = Path(__file__).parent / "fixtures" / "article_sample.html"


def test_extract_body_returns_text_only_from_txt_block():
    html = FIXTURE.read_text(encoding="utf-8")
    body = extract_body(html)
    assert body is not None
    # Body content must appear
    assert "국제처" in body or "해외파견" in body
    # Header metadata labels must NOT appear (they live in .title, not .txt)
    assert "조회수" not in body
    assert "URL 복사" not in body
    # No "첨부파일이(가) 없습니다" — that lives in .attachment
    assert "첨부파일이(가) 없습니다" not in body


def test_extract_body_returns_none_for_missing_block():
    html = "<html><body><div>nothing relevant</div></body></html>"
    assert extract_body(html) is None


def test_extract_body_collapses_whitespace():
    html = '<div class="board-view"><div class="txt">  hello\n\n\nworld   </div></div>'
    body = extract_body(html)
    assert body == "hello world" or body == "hello\nworld"  # impl chooses


@respx.mock
def test_fetch_article_body_success():
    html = FIXTURE.read_text(encoding="utf-8")
    respx.get("https://cse.pusan.ac.kr/bbs/cse/2055/1389652/artclView.do").mock(
        return_value=httpx.Response(200, text=html)
    )
    body = fetch_article_body(
        "https://cse.pusan.ac.kr/bbs/cse/2055/1389652/artclView.do",
        timeout=5.0,
        retries=1,
    )
    assert body is not None
    assert "국제처" in body or "해외파견" in body


@respx.mock
def test_fetch_article_body_returns_none_on_5xx():
    respx.get("https://x/y").mock(return_value=httpx.Response(503))
    body = fetch_article_body("https://x/y", timeout=1.0, retries=1)
    assert body is None


@respx.mock
def test_fetch_article_body_returns_none_on_network_error():
    respx.get("https://x/y").mock(side_effect=httpx.ConnectError("boom"))
    body = fetch_article_body("https://x/y", timeout=1.0, retries=1)
    assert body is None
```

- [ ] **Step 3: Verify tests fail**

```
.venv/bin/pytest tests/test_article.py -v
```
Expected: FAIL (module doesn't exist)

- [ ] **Step 4: Implement `article.py`**

`src/cse_bot/article.py`:

```python
"""Fetch a PNU CSE article detail page and extract the body text."""
from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

USER_AGENT = "cse-discord-bot/0.1"


def fetch_article_body(url: str, *, timeout: float, retries: int) -> str | None:
    """GET the article page and return body text, or None on any failure."""
    attempts = max(1, retries)
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
            log.warning("article.retryable status=%d url=%s", resp.status_code, url)
            if i == attempts - 1:
                return None
            continue
        if resp.status_code >= 400:
            log.warning("article.client_error status=%d url=%s", resp.status_code, url)
            return None
        return extract_body(resp.text)
    return None


def extract_body(html: str) -> str | None:
    """Extract body text from `.board-view .txt`. Returns None if missing/empty."""
    soup = BeautifulSoup(html, "lxml")
    el = soup.select_one(".board-view .txt")
    if el is None:
        return None
    text = el.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None
```

- [ ] **Step 5: Verify tests pass**

```
.venv/bin/pytest tests/test_article.py -v
```

(Note: `test_extract_body_collapses_whitespace` accepts either "hello world" or "hello\nworld"; impl uses single-space joining.)

- [ ] **Step 6: Commit**

```bash
git add src/cse_bot/article.py tests/test_article.py tests/fixtures/article_sample.html
git commit -m "feat(article): fetch and extract body text from article detail pages"
```

---

## Task 4: Gemini summarizer (`summarizer.py`)

**Files:**
- Create: `src/cse_bot/summarizer.py`
- Create: `tests/test_summarizer.py`

Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}` (POST, JSON).

Request body:
```json
{ "contents": [ { "parts": [ { "text": "<prompt>" } ] } ] }
```

Response:
```json
{ "candidates": [ { "content": { "parts": [ { "text": "..." } ] } } ] }
```

- [ ] **Step 1: Write failing tests**

`tests/test_summarizer.py`:

```python
import httpx
import respx

from cse_bot.summarizer import summarize

ENDPOINT_RE = (
    r"https://generativelanguage\.googleapis\.com/v1beta/models/"
    r"gemini-2\.5-flash-lite:generateContent.*"
)


@respx.mock
def test_summarize_returns_text_on_success():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "- 5/12 09:00 시작\n- 학년별 차등"}]}}
                ]
            },
        )
    )
    out = summarize(
        "본문 내용...",
        api_key="k",
        model="gemini-2.5-flash-lite",
        timeout=5.0,
    )
    assert out == "- 5/12 09:00 시작\n- 학년별 차등"


@respx.mock
def test_summarize_returns_none_on_429():
    respx.post(url__regex=ENDPOINT_RE).mock(return_value=httpx.Response(429))
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None


@respx.mock
def test_summarize_returns_none_on_5xx():
    respx.post(url__regex=ENDPOINT_RE).mock(return_value=httpx.Response(500))
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None


@respx.mock
def test_summarize_returns_none_on_timeout():
    respx.post(url__regex=ENDPOINT_RE).mock(side_effect=httpx.TimeoutException("t"))
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None


@respx.mock
def test_summarize_returns_none_on_empty_candidates():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=httpx.Response(200, json={"candidates": []})
    )
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None


@respx.mock
def test_summarize_returns_none_on_malformed_response():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None


def test_summarize_returns_none_for_empty_body():
    # No HTTP call should be made
    out = summarize("", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None
```

- [ ] **Step 2: Verify tests fail**

```
.venv/bin/pytest tests/test_summarizer.py -v
```
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement `summarizer.py`**

`src/cse_bot/summarizer.py`:

```python
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
```

- [ ] **Step 4: Verify tests pass**

```
.venv/bin/pytest tests/test_summarizer.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/summarizer.py tests/test_summarizer.py
git commit -m "feat(summarizer): Gemini REST client returning None on any failure"
```

---

## Task 5: Notifier — `format_message(summary)` + `send_to_webhooks`

**Files:**
- Modify: `src/cse_bot/notifier.py`
- Modify: `tests/test_notifier.py`

- [ ] **Step 1: Write failing tests**

`tests/test_notifier.py`에 추가 (기존 테스트는 그대로):

```python
import httpx
import pytest
import respx

from cse_bot.models import Post
from cse_bot.notifier import (
    NotifyError,
    format_message,
    send_to_webhooks,
)


def _post() -> Post:
    return Post(
        id=1, title="t", author="a", date="2026-05-06",
        url="https://x", category="c", has_attachment=False,
    )


def test_format_message_appends_summary_block_when_present():
    msg = format_message(_post(), "medium", summary="- bullet 1\n- bullet 2")
    assert "📝 요약" in msg
    assert "- bullet 1" in msg
    assert "- bullet 2" in msg


def test_format_message_omits_summary_block_when_none():
    msg = format_message(_post(), "medium", summary=None)
    assert "📝 요약" not in msg


def test_format_message_omits_summary_block_when_empty_string():
    msg = format_message(_post(), "medium", summary="")
    assert "📝 요약" not in msg


def test_format_message_truncates_when_exceeds_discord_limit():
    huge = "x" * 5000
    msg = format_message(_post(), "medium", summary=huge)
    assert len(msg) <= 2000


@respx.mock
def test_send_to_webhooks_all_success():
    respx.post("https://a").mock(return_value=httpx.Response(204))
    respx.post("https://b").mock(return_value=httpx.Response(204))
    ok, failed = send_to_webhooks(
        _post(),
        webhook_urls=["https://a", "https://b"],
        summary=None, fmt="medium", timeout=2.0, retries=1,
    )
    assert ok == 2
    assert failed == []


@respx.mock
def test_send_to_webhooks_partial_failure():
    respx.post("https://a").mock(return_value=httpx.Response(204))
    respx.post("https://b").mock(return_value=httpx.Response(403))
    ok, failed = send_to_webhooks(
        _post(),
        webhook_urls=["https://a", "https://b"],
        summary=None, fmt="medium", timeout=2.0, retries=1,
    )
    assert ok == 1
    assert failed == ["https://b"]


@respx.mock
def test_send_to_webhooks_all_failure():
    respx.post("https://a").mock(return_value=httpx.Response(403))
    respx.post("https://b").mock(return_value=httpx.Response(403))
    ok, failed = send_to_webhooks(
        _post(),
        webhook_urls=["https://a", "https://b"],
        summary=None, fmt="medium", timeout=2.0, retries=1,
    )
    assert ok == 0
    assert sorted(failed) == ["https://a", "https://b"]
```

- [ ] **Step 2: Verify tests fail**

```
.venv/bin/pytest tests/test_notifier.py -v
```
Expected: FAIL (`format_message` lacks `summary` param, `send_to_webhooks` undefined)

- [ ] **Step 3: Update `notifier.py`**

Edit `format_message`:

```python
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

    if summary:
        msg = f"{base}\n📝 요약:\n{summary}"
    else:
        msg = base

    if len(msg) > DISCORD_MAX:
        msg = msg[: DISCORD_MAX - 1] + "…"
    return msg
```

Add `send_to_webhooks`:

```python
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
```

Also add `summary` param to `send` (passed through to `format_message`):

```python
def send(
    post: Post,
    *,
    webhook_url: str,
    fmt: Format,
    timeout: float,
    retries: int,
    summary: str | None = None,
) -> None:
    content = format_message(post, fmt, summary=summary)
    ...
```

- [ ] **Step 4: Verify all notifier tests pass**

```
.venv/bin/pytest tests/test_notifier.py -v
```

If older `test_notifier.py` tests call `send` without `summary`, the new optional default keeps them passing.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/notifier.py tests/test_notifier.py
git commit -m "feat(notifier): summary block + send_to_webhooks fan-out helper"
```

---

## Task 6: Wire into `main.py`

**Files:**
- Modify: `src/cse_bot/main.py`

- [ ] **Step 1: Update imports**

Top of `src/cse_bot/main.py`, replace the existing imports row that includes `notifier, parser, state` with:

```python
from cse_bot import article, differ, fetcher, notifier, parser, state, summarizer
```

- [ ] **Step 2: Replace the per-post send block in `_process_board`**

Locate this block in `_process_board` (currently lines ~124–136):

```python
    webhook_url = cfg.webhook_url(board.id)
    for post in new_posts:
        notifier.send(
            post,
            webhook_url=webhook_url,
            fmt=cfg.notification.format,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        board_state.last_max_post_id = post.id
        state_map[board.id] = board_state
        state.save_state(state_path, state_map)
        log.info("notify.ok board=%s post_id=%d", board.id, post.id)
```

Replace with:

```python
    webhook_urls = cfg.webhook_urls(board.id)
    for post in new_posts:
        body = article.fetch_article_body(
            post.url,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        summary = (
            summarizer.summarize(
                body,
                api_key=cfg.gemini.api_key,
                model=cfg.gemini.model,
                timeout=cfg.gemini.timeout_seconds,
            )
            if body
            else None
        )

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

        board_state.last_max_post_id = post.id
        state_map[board.id] = board_state
        state.save_state(state_path, state_map)
        log.info(
            "notify.ok board=%s post_id=%d webhooks_ok=%d webhooks_failed=%d "
            "summary=%s",
            board.id,
            post.id,
            ok_count,
            len(failed_urls),
            "yes" if summary else "no",
        )
```

- [ ] **Step 3: Run the full test suite, verify pass**

```
.venv/bin/pytest -q
```

If any existing test in `tests/test_main.py` (if present) referenced `cfg.webhook_url` (singular), update it to `cfg.webhook_urls` returning a list.

- [ ] **Step 4: Run ruff lint**

```
.venv/bin/ruff check .
```
Fix any issues.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/main.py
git commit -m "feat(main): per-post article fetch + Gemini summary + webhook fan-out"
```

---

## Task 7: Manual smoke test (real Gemini + sandbox webhook)

**Files:** none — operational verification.

This task does **not** make code changes. It exercises the real integrations end-to-end.

- [ ] **Step 1: Confirm `GEMINI_API_KEY` is in `.env`**

```bash
grep -q '^GEMINI_API_KEY=' .env || echo "MISSING — add GEMINI_API_KEY=<key> to .env"
```
If missing, the user must obtain a key from https://aistudio.google.com/ and add it.

- [ ] **Step 2: Force a re-baseline so the next run finds a "new" post**

```bash
# Backup current state
cp data/state.json data/state.json.bak
# Set watermark to a value lower than the most recent post id so one new post triggers
.venv/bin/python -c "
import json
p = 'data/state.json'
s = json.load(open(p))
for k in s: s[k]['last_max_post_id'] = max(0, s[k]['last_max_post_id'] - 1)
json.dump(s, open(p,'w'), ensure_ascii=False, indent=2)
print(s)
"
```

- [ ] **Step 3: Run one cycle**

```bash
set -a; source .env; set +a
.venv/bin/python -m cse_bot.main --config config/config.toml
```

Expected:
- Discord channel(s) receive a notification with `📝 요약:` block
- `logs/cse_bot.log` shows `summary=yes` and `webhooks_ok=N`

- [ ] **Step 4: Restore state**

```bash
mv data/state.json.bak data/state.json
```

- [ ] **Step 5: No commit** (no file changes)

---

## Task 8: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Gemini setup to README**

In the Setup / Environment section, add:

```markdown
### Gemini API key (for AI summary)

1. Go to https://aistudio.google.com/ → "Get API key"
2. Add to `.env`:
   ```
   GEMINI_API_KEY=<your-key>
   ```
3. Free tier (Gemini 2.5 Flash-Lite, ~1,000 requests/day) is sufficient for this bot.
```

In the configuration section, document `webhook_envs` as a list and note the `[gemini]` section.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add Gemini API key setup and webhook_envs list"
```

---

## Self-Review Checklist (writer-side, completed)

- **Spec coverage:** §3 config → Tasks 1–2; §4.1 article → Task 3; §4.1 summarizer → Task 4; §4.2 notifier → Task 5; §4.2 main → Task 6; §6 error matrix → Tasks 3–5 (None fallback) + 6 (raise on all-fail); §7 tests → Tasks 1–5; §8 migration → Task 7 + 8.
- **Placeholders:** none. All code, commands, expected outputs are concrete.
- **Type consistency:** `webhook_envs: list[str]` (models) ↔ `webhook_urls: list[str]` (Config method) ↔ `send_to_webhooks(webhook_urls=...)` — names align. `summarize` returns `str | None`, consumed at main.py with truthy check. `send_to_webhooks` returns `tuple[int, list[str]]` — consumed identically at main.py.

## Out-of-Scope (re-confirmed)
- Caching, async, per-webhook retry tracking, rate-limit gauge — all deferred.
