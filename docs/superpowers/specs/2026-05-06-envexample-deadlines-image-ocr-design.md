# `.env.example` + 마감일 리마인더 + 이미지 OCR — Design Spec

- **작성일:** 2026-05-06
- **상태:** Draft (사용자 검토 대기)
- **선행:** `2026-05-06-multi-webhook-and-ai-summary-design.md` (Gemini 통합 1차)
- **목표:** 작은 기능 3개 묶음 — 신규 가입자 setup 마찰 제거, 마감일 자동 리마인더, 이미지 공지 OCR 지원.

---

## 1. 개요

### 1.1 세 가지 변경
1. **`.env.example`에 `GEMINI_API_KEY` 줄 추가** — 현재 누락 → 신규 setup 시 `ConfigError` 만나기 전에 미리 인지
2. **마감일 추출 + 리마인더** — Gemini 요약 호출 시 같은 응답에서 `deadline` 필드 추출 → 같은 launchd 사이클에서 D-1 시점에 자동 리마인드
3. **이미지 공지 OCR** — Article 페이지의 이미지(첫 3장)를 항상 Gemini multimodal 호출에 포함 → 이미지로만 된 공지도 본문 요약 가능

### 1.2 비목표
- 마감 D-3, D-day 리마인드 (D-1 한 번만 — 사용자 결정)
- 백필 (이미 알림 보낸 과거 글에 마감일 추출 안 함)
- OCR 결과 캐싱 (글당 1회 호출 가정)
- 이미지 다운로드 (URL을 Gemini에 전달 → Gemini가 fetch)
- 이미지 OCR 실패 시 별도 fallback 채널 (기존 정책: 요약 None → 제목+URL만 전송)

---

## 2. 정책 결정

| 항목 | 선택 | 근거 |
|---|---|---|
| 리마인더 시점 | **마감 1일 전 1회만** | 사용자 지정 |
| 리마인더 트리거 | **기존 09/18 launchd 사이클에 통합** | 별도 plist 도입 비용 회피 |
| 마감일 저장 | **`data/state.json` 안 `boards[].deadlines: { post_id: {date, sent} }`** | 단일 state 파일 유지, 단순함 |
| 마감 추출 방식 | **Gemini 요약 호출에서 JSON 응답으로 `{summary, deadline}` 동시 반환** | 호출 1회로 통합, 비용 절감 |
| 한 글 다중 마감 | **가장 빠른 1개만 트래킹** | 단순화, 다수 마감은 첫 마감 알림이면 충분 |
| 백필 | **하지 않음** (활성화 이후 새 글부터) | 기존 알림 발송된 글의 본문을 다시 fetch하기 부적절 |
| 이미지 포함 조건 | **항상** (이미지가 있으면 첨부) | 사용자 지정 — 텍스트만 있어도 그림이 있으면 보충 정보 |
| 이미지 개수 상한 | **첫 3장** | 토큰 비용 통제 |
| 이미지 전송 방식 | **URL passthrough** (Gemini가 fetch) | 간단·토큰 절약. PNU 사이트는 공개 이미지 |
| 이미지 OCR 실패 | **기존 fallback** (요약 None → 제목+URL) | 메인 기능 회귀 방지 |

---

## 3. `.env.example` 변경

```
DISCORD_WEBHOOK_GENERAL=https://discord.com/api/webhooks/REPLACE_ME
DISCORD_WEBHOOK_ALERT=https://discord.com/api/webhooks/REPLACE_ME
GEMINI_API_KEY=AIza...REPLACE_ME
```

(주석 한 줄 추가 권장: `# Get a free key from https://aistudio.google.com/`)

---

## 4. 마감일 리마인더

### 4.1 데이터 모델 변경 (`models.py`)

```python
@dataclass
class TrackedDeadline:
    post_id: int
    title: str
    url: str
    date: str          # ISO YYYY-MM-DD
    reminded: bool     # D-1 리마인더 발송 완료 여부

@dataclass
class BoardState:
    last_max_post_id: int | None
    last_checked: str
    empty_streak: int = 0
    deadlines: list[TrackedDeadline] = field(default_factory=list)
```

`state.json` 직렬화 형식 (보드 1개 예):
```json
{
  "14221": {
    "last_max_post_id": 1389700,
    "last_checked": "2026-05-06T09:00:00+09:00",
    "empty_streak": 0,
    "deadlines": [
      {"post_id": 1389652, "title": "수강신청 안내", "url": "https://...", "date": "2026-05-14", "reminded": false}
    ]
  }
}
```

기존 state.json 파일과의 호환성: `deadlines` 키 없으면 빈 리스트로 로드 (`state.load_state` 보강).

### 4.2 Summarizer 응답 스키마 변경 (`summarizer.py`)

기존: `summarize(...) -> str | None` (요약 텍스트)
신규: `summarize(...) -> SummaryResult | None`

```python
@dataclass(frozen=True)
class SummaryResult:
    summary: str
    deadline: str | None  # ISO YYYY-MM-DD or None
```

Gemini 호출 시 `responseMimeType: "application/json"` + 명시적 `responseSchema`로 구조화 응답 강제:

```python
GENERATION_CONFIG = {
    "responseMimeType": "application/json",
    "responseSchema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "deadline": {"type": "string", "nullable": True},  # YYYY-MM-DD or null
        },
        "required": ["summary"],
    },
}
```

프롬프트 보강:
> ... 한국어 불릿 5줄 이내로 요약하고, 본문에 명시된 신청·접수·제출 마감일이 있으면 `deadline` 필드에 `YYYY-MM-DD` 형식으로 포함하라. 마감이 없거나 모호하면 `null`. 마감이 여러 개면 가장 빠른 것.

응답 파싱 실패(JSON 파싱 에러 / 스키마 불일치 / `deadline`이 잘못된 포맷) → 호출자에게 `SummaryResult(summary=원래_문자열_파싱_시도, deadline=None)` 또는 전체 None.

### 4.3 새 모듈 `reminder.py`

```python
def collect_due_reminders(
    state_map: dict[str, BoardState],
    *,
    today: date,
) -> list[tuple[str, TrackedDeadline]]:
    """Return (board_id, deadline) tuples that should be reminded now.

    A deadline is due iff today == deadline.date - 1 day and not deadline.reminded.
    Past deadlines (deadline.date < today) are pruned by the caller.
    """
```

```python
def format_reminder(d: TrackedDeadline) -> str:
    return (
        f"⏰ 내일 마감: {d.title}\n"
        f"📅 마감일: {d.date}\n"
        f"🔗 {d.url}"
    )


def prune_expired(state_map: dict[str, BoardState], *, today: date) -> int:
    """Remove deadlines where date < today. Returns count removed."""
```

리마인더는 **Discord 웹훅 별도 메시지**로 발송 (요약 알림과는 분리). 동일 `webhook_envs` 사용. 부분 실패 시 best-effort + alert (기존 정책 동일).

### 4.4 main.py 흐름 변경

`run_cycle` 끝부분 (모든 보드 처리 후, state 저장 직전):

```python
# 1. 새 글 처리하면서 deadline 발견 시 board_state.deadlines에 추가
#    (summarize() 결과의 deadline 필드 사용)
# 2. 모든 보드 처리 끝나면 만료된 deadline 제거
# 3. 오늘 발송해야 할 리마인더 수집 → 각 보드의 webhook_urls로 발송 → sent 태그 추가
```

새 글 처리 시 (Task 6의 main.py 흐름 안):
```python
result = summarizer.summarize(body, ...)
summary = result.summary if result else None
if result and result.deadline:
    try:
        d = date.fromisoformat(result.deadline)
        if d > today:  # 이미 지난 마감은 무시
            board_state.deadlines.append(TrackedDeadline(
                post_id=post.id, title=post.title, url=post.url,
                date=result.deadline, sent=[],
            ))
    except ValueError:
        pass  # invalid date format
```

cycle 끝부분:
```python
prune_expired(state_map, today=today)
due = collect_due_reminders(state_map, today=today)
for board_id, deadline in due:
    msg = format_reminder(deadline)
    webhook_urls = cfg.webhook_urls(board_id)
    ok, failed = notifier.send_alert_to_webhooks(msg, webhook_urls=webhook_urls, ...)
    if ok > 0:
        deadline.reminded = True
```

`notifier`에 새 헬퍼 추가:
```python
def send_alert_to_webhooks(
    content: str, *, webhook_urls: list[str], timeout: float, retries: int,
) -> tuple[int, list[str]]:
    """Send a plain content message (no Post envelope) to multiple webhooks."""
```

### 4.5 중복 발송 방지

같은 날 같은 사이클이 두 번 트리거되거나 (09 + 18) 사용자가 수동 실행 시:
- `reminded` 플래그가 가드 — 한 번 True가 되면 다시 안 보냄
- 09시 사이클이 D-1 리마인더 보내면 18시엔 `reminded=True`라 skip
- D-1 사이클에 봇이 한 번도 안 돌면 알림 누락 (의도된 동작 — D-day나 D+1에는 안 보냄)

### 4.6 시간대

`today`는 KST 기준 (`zoneinfo.ZoneInfo("Asia/Seoul")`). UTC 사용 시 자정 부근 보드 글의 deadline이 하루 어긋날 위험 있음.

---

## 5. 이미지 OCR

### 5.1 Article 모듈 확장

기존 `article.py`:
- `fetch_article_body(url) -> str | None`

신규 추가:
```python
@dataclass(frozen=True)
class ArticleContent:
    body: str            # 텍스트 본문 (빈 문자열일 수 있음)
    image_urls: list[str]  # 절대 URL, 최대 3개

def fetch_article_content(url, *, timeout, retries) -> ArticleContent | None:
    """Returns body + first 3 image URLs from .board-view .txt img tags."""
```

`extract_body`는 그대로 두고 이미지 추출 로직 추가:
```python
def extract_image_urls(html: str, base_url: str, *, limit: int = 3) -> list[str]:
    """Extract first N image URLs from .board-view .txt area, absolute URLs."""
```

본문 셀렉터(`.board-view .txt`) 안의 `img[src]`만 — 사이드바 광고/아이콘 배제.

### 5.2 Summarizer multimodal 호출

```python
def summarize(
    body: str,
    *,
    image_urls: list[str] = (),
    api_key: str, model: str, timeout: float,
) -> SummaryResult | None:
    ...
```

Gemini 페이로드 구조 (이미지 있을 때):
```json
{
  "contents": [{
    "parts": [
      {"text": "<프롬프트 + 본문>"},
      {"fileData": {"mimeType": "image/jpeg", "fileUri": "https://..."}},
      {"fileData": {"mimeType": "image/png", "fileUri": "https://..."}}
    ]
  }],
  "generationConfig": {...}
}
```

프롬프트 보강: 본문이 짧을 때 "이미지에 적힌 텍스트를 우선 활용해 요약해라" 한 줄 추가.

> ⚠️ Gemini의 `fileData`는 일부 모델/엔드포인트에서 Cloud Storage URL만 허용. 외부 HTTPS URL을 직접 받는 경우 `fileData` 대신 inline_data (base64)를 써야 할 수 있음 — **구현 단계에서 endpoint 동작 확인 후, 외부 URL 미지원이면 base64로 fallback** (이 spec의 implementation note).

### 5.3 main.py 와이어링 변경

```python
content = article.fetch_article_content(post.url, ...)
body = content.body if content else ""
images = content.image_urls if content else []
result = summarizer.summarize(body, image_urls=images, ...) if (body or images) else None
```

(기존 `body or None` 가드 → `(body or images) or None` 으로 확장. 이미지만 있어도 호출.)

---

## 6. 에러 처리 매트릭스 (변경분만)

| 시나리오 | 동작 |
|---|---|
| Gemini가 deadline 필드를 잘못된 포맷으로 반환 | `date.fromisoformat()` 실패 → deadline 트래킹 안 함, 요약은 정상 사용 |
| Gemini 응답이 JSON 스키마 위반 | `SummaryResult` 파싱 실패 → 호출자 None 받음, 요약 fallback |
| 이미지 URL이 404 / Gemini가 못 fetch | Gemini 응답에 반영 (이미지 무시하고 텍스트만으로 요약) — 우리 코드 변경 없음 |
| `state.json`에 `deadlines` 키 없는 (이전 버전) 파일 로드 | 빈 리스트로 초기화 |
| 사용자가 시간대 수동 변경(KST → UTC 등) | KST를 강제 사용 (코드에 hard-code) |
| 마감 후에 사용자가 봇 며칠 안 돌림 | `prune_expired`가 다음 사이클에 정리 — 누락은 의도된 동작 |

---

## 7. 테스트 전략

### 7.1 신규 테스트
- `tests/test_reminder.py`
  - `collect_due_reminders` D-1 매칭 (today + 1 == deadline.date)
  - D-2, D-day, 과거 deadline은 매칭 안 됨
  - `reminded=True`면 skip
  - `prune_expired` 만료 항목 제거 (today > deadline.date)
- `tests/test_article.py` 확장
  - `extract_image_urls` 첫 3장 제한, 절대 URL 변환, 본문 외 이미지 배제
  - `fetch_article_content` 통합

### 7.2 기존 테스트 수정
- `tests/test_summarizer.py`
  - 응답이 JSON 스키마 따르는 신규 형식
  - `deadline=null` 케이스
  - `deadline` 잘못된 포맷
  - `image_urls` 파라미터 페이로드에 반영되는지
- `tests/test_main.py` (있다면)
  - deadline 트래킹/리마인더 발송 시나리오 — `freezegun`으로 날짜 고정

### 7.3 통합
- 기존 cycle 통합 테스트가 있다면 마감일 1건 누적 → 다음날(D-3) 사이클 → 리마인더 발송 시뮬레이션

---

## 8. 마이그레이션

- `.env.example` 업데이트는 영향 없음 (새 setup만 영향)
- `state.json` 구버전 자동 호환 (deadlines 빈 리스트로 로드)
- 사용자 액션: 없음. 코드 pull + 다음 launchd 사이클부터 자동 작동.

---

## 9. Out of Scope (재확인)

- 마감 D-3, D-day, 다회 리마인드 (D-1 1회만)
- 마감 backfill (이미 발송된 글)
- 다중 마감 트래킹
- OCR 결과 캐싱
- 이미지 다운로드/저장
- 이미지가 없는 PDF 첨부 OCR (별도 기능)
