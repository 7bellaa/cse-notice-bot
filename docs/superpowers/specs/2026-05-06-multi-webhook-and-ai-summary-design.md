# Multi-Webhook Fan-out + Gemini AI 요약 — Design Spec

- **작성일:** 2026-05-06
- **상태:** Draft (사용자 검토 대기)
- **목표:** 게시판 새 글을 여러 Discord 웹훅에 동시 전송하고, Gemini 2.5 Flash-Lite로 본문을 5줄 이내 핵심 요약하여 알림에 포함한다.
- **선행:** `2026-04-30-pnu-cse-discord-bot-design.md` (1차 봇 설계)

---

## 1. 개요 (Overview)

### 1.1 목적
1차 봇은 게시판당 단일 웹훅으로 제목/작성자/날짜/URL만 전송한다. 본 설계는 두 가지를 추가한다.

1. **Fan-out** — 한 게시판의 새 글 1개를 N개 Discord 웹훅에 동시 전송 (예: 본인 서버 + 친구 서버 + 단톡방용 채널 등).
2. **AI 요약** — 게시물 상세 페이지 본문을 Gemini 2.5 Flash-Lite로 5줄 이내 핵심 정보(날짜·시간·대상·방법) 위주 불릿 요약하여 알림 메시지에 추가.

### 1.2 범위
- 모든 활성화된 보드에 적용 (현재는 `14221` 정컴 일반공지 1개)
- 요약은 한국어
- 무료 티어 (Google AI Studio API key, 약 1,000 RPD for Flash-Lite) 내 운영 가정

### 1.3 비목표 (Non-Goals)
- 요약 결과 캐싱 (글당 1회만 호출하므로 캐시 의미 없음)
- API 비용 한도 가드 / 사용량 추적 (무료 티어 내 가정)
- 비동기/병렬 웹훅 전송 (백그라운드 작업이라 속도 차이 무의미)
- 웹훅별 개별 재시도 추적 (best-effort 정책 채택)
- Gemini 응답 스트리밍

---

## 2. 정책 결정 (Decisions)

| 항목 | 선택 | 근거 |
|---|---|---|
| Fan-out 방식 | 게시판당 N개 웹훅 (`webhook_envs: list[str]`) | 사용자 의도가 "같은 글을 여러 채널로" |
| 전송 동시성 | **순차 (sync)** | 새 글 빈도 낮고 실행 주기 길어 async 도입은 과도 |
| 부분 실패 정책 | **best-effort** — 1개라도 성공하면 워터마크 전진, 실패 웹훅은 alert 웹훅으로 통보 | 중복 전송 방지 우선, Discord 웹훅이 실질적으로 죽으면 사용자가 새로 발급 필요 |
| 모두 실패 정책 | **워터마크 미전진** → 다음 사이클 재시도 | 알림 손실 방지 |
| 요약 모델 | `gemini-2.5-flash-lite` | 무료 티어 한도 가장 후함 (1,000 RPD), 짧은 요약에 충분 |
| 요약 길이 | **5줄 이내 불릿, 한국어** | 사용자 지정 — 핵심(날짜·시간·대상·방법) 위주 |
| 요약 실패 처리 | **알림은 그대로 발송 (현재 포맷으로 fallback)** | 알림 봇의 1순위 목적은 "새 글 났음" 전달 |
| API 호출 방식 | `httpx`로 REST 직접 호출 | `google-genai` SDK는 무거움, 의존성 추가 불필요 |
| Config 하위 호환 | **클린 변경 (호환 없음)** | 개인 봇이고 config 1개만 존재 |

---

## 3. Config 변경 (`config/config.toml`)

### 3.1 새 섹션
```toml
[gemini]
api_key_env = "GEMINI_API_KEY"
model = "gemini-2.5-flash-lite"
timeout_seconds = 10
```

### 3.2 보드 스키마 변경
```toml
[[boards]]
id = "14221"
name = "정컴 일반공지"
url = "https://cse.pusan.ac.kr/cse/14221/subview.do"
webhook_envs = ["DISCORD_WEBHOOK_GENERAL"]   # ← 단일 문자열에서 리스트로
enabled = true
```

- `webhook_env: str` → `webhook_envs: list[str]`
- 빈 리스트는 `ConfigError`
- 환경변수 미정의 시 기존과 동일하게 fail-fast

### 3.3 환경변수
- `GEMINI_API_KEY` — Google AI Studio에서 발급, `.env`에 추가
- `gemini.api_key_env`로 가리키는 변수가 미정의면 `ConfigError`

---

## 4. 모듈 구조

### 4.1 신규 모듈

#### `src/cse_bot/article.py`
```python
def fetch_article_body(post_url: str, *, timeout: float, retries: int) -> str | None
```
- 게시물 상세 페이지 GET → BeautifulSoup으로 본문 영역 텍스트 추출
- 성공: 정제된 본문 텍스트 반환
- 실패 (HTTP 오류, 파싱 실패, 빈 본문): `None`
- 셀렉터는 구현 단계에서 실제 article HTML을 보고 결정 (`#article` / `.view_cont` 등 후보)
- `fetcher.fetch`와 동일한 retry/UA 정책 재사용

#### `src/cse_bot/summarizer.py`
```python
def summarize(body: str, *, api_key: str, model: str, timeout: float) -> str | None
```
- Gemini REST API (`generativelanguage.googleapis.com`) 호출
- 프롬프트(상수):
  > 다음은 부산대학교 컴퓨터공학과 공지사항이다. 학생 입장에서 알아야 할 핵심 정보(날짜·시간·대상·방법)를 한국어 불릿 5줄 이내로 요약해라. 군더더기 인사말 금지.
- 성공: 요약 텍스트
- 실패 (HTTP 오류, timeout, 빈 응답, rate limit, 무료 한도 초과): `None`
- 호출자가 `None`을 받으면 fallback 처리

### 4.2 변경 모듈

#### `src/cse_bot/models.py`
- `BoardConfig.webhook_env: str` → `webhook_envs: list[str]`

#### `src/cse_bot/config.py`
- `Config._webhook_urls: dict[str, str]` → `dict[str, list[str]]`
- `Config.webhook_url(board_id) -> str` → `Config.webhook_urls(board_id) -> list[str]`
- 새 `GeminiConfig(api_key: str, model: str, timeout_seconds: float)` 데이터클래스
- `Config.gemini: GeminiConfig` 필드 추가
- `_load_boards`가 `webhook_envs` 리스트 파싱 (빈 리스트는 에러)

#### `src/cse_bot/notifier.py`
- `format_message(post, fmt, summary: str | None = None)` — `summary`가 truthy이면 메시지 끝에 다음 블록 추가:
  ```
  📝 요약:
  <Gemini 출력 그대로 (이미 불릿 형식)>
  ```
  - Gemini가 자체적으로 불릿(`-`/`•`/`*`)을 포함하므로 호출 측에서 추가 가공 없이 그대로 삽입
  - Discord 메시지 한도(2000자) 초과 시 잘라서 전송 (안전장치)
- 새 `send_to_webhooks(post, *, webhook_urls, summary, fmt, timeout, retries) -> tuple[int, list[str]]`
  - 순차 POST. `(성공_개수, 실패_url_리스트)` 반환
  - 각 호출은 기존 `send` 재사용
- 기존 `send`는 단일 웹훅 함수로 유지 (테스트/단순성)

#### `src/cse_bot/main.py` — `_process_board` 내부
```
for new_post in new_posts:
    body = article.fetch_article_body(new_post.url, ...)
    summary = (
        summarizer.summarize(body, api_key=cfg.gemini.api_key, ...)
        if body else None
    )
    ok_count, failed_urls = notifier.send_to_webhooks(
        new_post,
        webhook_urls=cfg.webhook_urls(board.id),
        summary=summary,
        fmt=cfg.notification.format,
        timeout=cfg.general.http_timeout_seconds,
        retries=cfg.general.http_retries,
    )
    if ok_count == 0:
        raise NotifyError(f"all webhooks failed for post {new_post.id}")
    if failed_urls:
        _safe_alert(
            cfg,
            f"post {new_post.id}: {len(failed_urls)}/{ok_count + len(failed_urls)} webhooks failed",
        )
    board_state.last_max_post_id = new_post.id
    state_map[board.id] = board_state
    state.save_state(state_path, state_map)
    log.info("notify.ok board=%s post_id=%d webhooks_ok=%d webhooks_failed=%d",
             board.id, new_post.id, ok_count, len(failed_urls))
```

---

## 5. 데이터 플로우 (변경분)

```
... (기존 1차 흐름) ...
4-vi. 신규 글 each:
   a. article.fetch_article_body(post.url) → body | None
   b. body 있으면 summarizer.summarize(body) → summary | None
   c. notifier.send_to_webhooks(post, webhook_urls=[...], summary=summary)
      → 순차 POST, 각 결과 집계
   d. 0개 성공 → NotifyError raise (워터마크 미전진)
   e. 일부 실패 → alert 웹훅에 통보, 워터마크 전진
   f. 전부 성공 → 워터마크 전진
```

---

## 6. 에러 처리 매트릭스

| 시나리오 | 동작 |
|---|---|
| article fetch 실패 | summary=None, 알림은 기존 포맷으로 발송 |
| article 본문 셀렉터 미스 (빈 텍스트) | summary=None, 알림은 기존 포맷으로 발송 |
| Gemini API timeout | summary=None, fallback |
| Gemini 5xx / 429 | summary=None, fallback (재시도 X — 다음 글에 영향 주지 않기 위해) |
| Gemini 무료 한도 초과 | summary=None, fallback. 한도 초과 자체를 alert으로 통보? → **out of scope (1차 적용 시 관찰 후 결정)** |
| 웹훅 1개 실패, 나머지 성공 | best-effort 전진 + alert 통보 |
| 웹훅 전부 실패 | NotifyError raise, 워터마크 미전진 |

---

## 7. 테스트 전략

### 7.1 신규 테스트
- `tests/test_summarizer.py` — `respx`로 Gemini API mock
  - 정상 응답
  - 5xx → None
  - 429 → None
  - timeout → None
  - 빈 candidates → None
- `tests/test_article.py` — 샘플 article HTML 픽스처(`tests/fixtures/article_*.html`)
  - 본문 추출 성공
  - 본문 영역 누락 → None

### 7.2 기존 테스트 확장
- `tests/test_notifier.py` — `send_to_webhooks` 케이스
  - 전부 성공 → `(N, [])`
  - 일부 실패 → `(k, [...])`
  - 전부 실패 → `(0, [...])`
  - `format_message`에 summary 포함 시 출력 검증
- `tests/test_config.py`
  - `webhook_envs` 리스트 파싱
  - 빈 리스트 → ConfigError
  - `[gemini]` 섹션 누락 → ConfigError
  - `GEMINI_API_KEY` 미정의 → ConfigError

### 7.3 통합 / E2E
- main 사이클 단위 테스트가 있다면 fallback 시나리오(요약 None) 추가
- 실제 Gemini 호출은 CI에서 안 함 (mock으로만)

---

## 8. 마이그레이션 / 운영

- `.env`에 `GEMINI_API_KEY=...` 추가 필요 (Google AI Studio에서 발급)
- 기존 `config.toml`에서 `webhook_env = "DISCORD_WEBHOOK_GENERAL"` →
  `webhook_envs = ["DISCORD_WEBHOOK_GENERAL"]`로 1줄 수정
- `[gemini]` 섹션 추가
- 1차 배포 후 launchd로 다음 사이클 트리거 시 정상 동작 확인

---

## 9. Out of Scope (재확인)

- 요약 캐싱
- API 사용량 모니터링/한도 가드
- async 동시 전송
- 웹훅별 개별 재시도 추적
- 다국어 요약
- 이미지/첨부 본문 분석
