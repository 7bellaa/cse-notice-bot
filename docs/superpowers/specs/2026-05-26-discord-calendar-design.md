# Discord 캘린더 업그레이드 — 설계 문서

> 작성일 2026-05-26 · 합의된 사용자 결정 반영본 (v2)

## 1. Context

현재 PNU CSE Discord 봇은 새 공지가 올 때마다 webhook으로 다중 줄 평문 메시지를 채널(`#공지일반`, `개백수방`)에 누적시킨다. 텍스트가 쌓이면서 가독성이 떨어지고, "이번 주 마감이 뭐지?" 같은 한눈 조회가 어렵다. 다행히 Gemini가 본문/이미지에서 `deadline` 필드를 JSON으로 추출하고 `TrackedDeadline`을 `state.json`에 보관하기 시작했기에, 캘린더 시각화의 데이터 레이어는 이미 존재한다.

**실데이터 분석** (학부 공지 1~2페이지, 2026-05-26 기준):

- 일반 게시글 20건 중 ~17건이 마감/신청형 (제목 또는 본문에 마감일).
- 마감 키워드 없는 7건도 4건은 부트캠프/특강/모집/재입학 → 본문에 마감일 있음.
- **진짜 마감 없는 공지**: 출석인정원 위조 안내, 효원브릿지 운영 안내 정도 (≤10%).
- 제목 75%가 `[장학]`, `[수업]`, `[AI융합교육원]` 같은 prefix → 카테고리 추출 가능.
- 마감일이 게시 다음 달로 넘어가는 케이스 잦음 (예: 5/22 게시, 6/22 마감) → PNG에 2개월 표시 필요.

**목표**: 하루 1회(18:00)에 기존 채널로 *통합 메시지*를 발행한다 — 캘린더 PNG 임베드 + 그 밑에 새 공지 1줄 요약. 기존 다중 줄 webhook 메시지는 폐기. 같은 데이터를 GitHub Pages의 정적 웹 캘린더(FullCalendar)로 인터랙티브하게 탐색 가능.

## 2. 합의된 결정

| 항목 | 결정 |
|------|------|
| 1차 뷰 | Pillow로 렌더한 PNG (May+Jun 2개월) |
| 디테일 뷰 | GitHub Pages 정적 사이트 (FullCalendar.io) |
| 콘텐츠 범위 | `deadline != None`인 공지만, **마감일 기준** 표시 (게시일 X) |
| **채널 전략** | **기존 채널 통합** — `DISCORD_WEBHOOK_GENERAL`, `DISCORD_WEBHOOK_JOBLESS`에 동일 메시지 fanout. 새 채널·새 webhook env 없음 |
| **업데이트 주기** | **하루 1회 18:00** — launchd plist를 18:00 단일 항목으로 수정 |
| **메시지 포맷** | **한 메시지에 통합**: ① 캘린더 PNG 임베드 (제목+image+임박 요약) → ② 그 밑에 "🆕 오늘 새 공지 N건" + 공지별 **딱 1줄** bullet |
| **iCal 구독** | **제외** (v1에서 빠짐) |
| 카테고리 | 제목 prefix `^\[([^\]]+)\]` 정규식 추출. 매핑: 장학→보라, 수업/학사/졸업→청록, 취업/취업전략과→초록, AI/모집/국제/국립대학→파랑, (없음)→회색 |
| 마감 강조 | D-3 이내 셀 옅은 빨강, 당일 셀 옅은 노랑, 오늘 셀 indigo ring |
| **PNG 배경** | **Discord 다크 톤온톤** — 채팅 배경 `#313338` + 셀 `#2b2d31`. 흰 배경 PNG는 임베드와 부조화 |
| 이미지 전달 | PNG를 GitHub Pages publish → Discord embed의 `image.url`로 참조 |
| D-1 알림 | **별도 알림 폐기** → 캘린더 임베드 description에 "⏰ 내일 마감 N건" 형태로 흡수 |
| 메시지 수명 | **매일 새 메시지** (편집 X). 채널 히스토리가 일자별 스냅샷이 됨 |
| 추가 의존성 | `Pillow>=10` 1개만. `.ics`는 작성 X |

## 3. Architecture

```
[launchd 18:00] → main.run_cycle()
       │
       ▼
fetch → parse → article → summarizer(Gemini) → state.json
       │                          (TrackedDeadlines, last_max_post_id)
       │
       │  (new_posts, summaries dict, 활성 deadlines 보유)
       ▼
calendar_renderer.render_calendar_png(deadlines) → docs/calendar/current.png
web_publisher.write_events_json(deadlines)       → docs/calendar/events.json
web_publisher.git_publish(["docs/calendar/"])    → GitHub Pages 갱신
       │
       ▼
notifier.send_daily_digest(webhooks, calendar_url, png_url, new_posts, upcoming)
       │  → fanout to DISCORD_WEBHOOK_GENERAL + DISCORD_WEBHOOK_JOBLESS
       ▼
[Discord 메시지 1개 — embed(이미지+임박 요약) + content text(1줄 N건)]
       │
       ▼ 성공 시
last_max_post_id 진행 + state.json save
```

**기존 흐름과의 차이:**

- **삭제**: per-post `send_to_webhooks` 호출. 함수는 보존하되 main.py에서 호출 제거.
- **삭제**: `reminder.collect_due_reminders` 기반 D-1 alert 발행. 결과는 캘린더 임베드 description으로 흡수.
- **추가**: 18시 1회 통합 digest 발행.

## 4. 데이터 모델 변경

`src/cse_bot/models.py`:

```python
@dataclass
class TrackedDeadline:
    post_id: int
    title: str
    url: str
    date: str               # ISO YYYY-MM-DD
    reminded: bool = False
    category: str = ""      # NEW — 제목 prefix에서 추출
```

`BoardState`는 추가 필드 없음 (매일 새 메시지 → `calendar_message_id` 불필요).

`state.json` 호환: `category` 누락 시 기본값(`""`)으로 로드.

## 5. 모듈 명세

### `src/cse_bot/category.py`

```python
CATEGORY_PALETTE: dict[str, tuple[int, int, int]]
extract_category(title: str) -> str
category_to_color(category: str) -> tuple[int, int, int]
```

매핑:

| 카테고리 | 색상 (RGB) |
|----------|-----------|
| 장학 | `(139, 92, 246)` 보라 |
| 수업·학사·졸업 | `(20, 184, 166)` 청록 |
| 취업·취업전략과 | `(16, 185, 129)` 초록 |
| AI융합교육원·모집·국제협력실·국립대학육성사업 | `(59, 130, 246)` 파랑 |
| (그 외) | `(107, 114, 128)` 회색 |

### `src/cse_bot/calendar_renderer.py`

```python
render_calendar_png(
    deadlines: list[TrackedDeadline],
    today: date,
    output_path: Path,
    months: int = 2,
) -> None
```

- Pillow `Image.new()` + `ImageDraw` 기반. 캔버스 900×N px.
- 다크 톤온톤 배경: `#313338`(canvas) + `#2b2d31`(card) + `#1e1f22`(border).
- 한글 폰트 탐색: `assets/fonts/Pretendard-Medium.ttf` → `/System/Library/Fonts/Apple SD Gothic Neo.ttc` → PIL 기본.
- 셀당 이벤트 최대 2개 + "외 N건" 압축.
- 오늘 셀 indigo 링, D-3 이내 옅은 빨강, 당일 옅은 노랑.
- 이벤트 chip: 카테고리 색 배경 + 흰 텍스트, 제목은 prefix 제거 + 9자 truncate.

### `src/cse_bot/web_publisher.py`

```python
write_events_json(deadlines, output_path: Path) -> None
git_publish(paths: list[Path], *, message: str, cwd: Path | None = None) -> bool
```

`write_events_json` 출력 형식 (FullCalendar v6):

```json
[
  {
    "id": "5719",
    "title": "[장학] 주거안정장학금 신청",
    "start": "2026-06-22",
    "url": "https://...",
    "color": "#8b5cf6",
    "extendedProps": {"category": "장학"}
  }
]
```

`git_publish`는 `git diff --quiet`로 변경 없으면 `False`(skip), 변경 있으면 add/commit/push 후 `True`.

### `src/cse_bot/notifier.py` 추가 함수

```python
def send_daily_digest(
    webhook_urls: list[str],
    *,
    calendar_png_url: str,
    site_url: str,
    new_posts: list[Post],
    upcoming: list[TrackedDeadline],
    summaries: dict[int, str],
    today: date,
    timeout: float,
    retries: int,
) -> tuple[int, list[str]]
```

페이로드:

- `embeds[0]`:
  - `title`: `📅 PNU CSE · {today}`
  - `image.url`: `{calendar_png_url}?t={epoch}` (캐시버스트)
  - `url`: `{site_url}` (제목 클릭 시 사이트로)
  - `description`: 임박 top 3 + "⏰ 내일 마감 N건"
- `content`: `🆕 오늘 새 공지 N건\n· [카테고리] 제목 — URL` (없으면 omit). 2000자 초과 시 잘라내고 "외 N건 (웹에서 확인)" 추가.

기존 `_post_with_retry` 패턴(tenacity) 재사용. 각 webhook URL로 동일 페이로드 sequential fanout.

## 6. main.py 통합

```python
def run_cycle(config_path):
    cfg, state_map = load(...)
    today = date.today()
    new_posts: list[Post] = []
    summaries: dict[int, str] = {}

    for board in cfg.boards:
        # 기존 fetch + parse + 새 공지 식별
        # 변경: send_to_webhooks 호출 제거
        # 변경: 새 공지를 new_posts에 누적, summary는 summaries[post.id]에
        # 변경: deadline 있으면 TrackedDeadline 생성 (category = extract_category 포함)
        ...

    deadlines = [
        d for b in state_map.values() for d in b.deadlines
        if d.date >= today.isoformat()
    ]
    out_dir = repo_root / "docs/calendar"
    render_calendar_png(deadlines, today, out_dir / "current.png", months=2)
    write_events_json(deadlines, out_dir / "events.json")
    git_publish([out_dir], message=f"auto: calendar update {today.isoformat()}")

    upcoming = sorted(deadlines, key=lambda d: d.date)[:3]
    webhook_urls = resolve_all_webhooks(cfg)
    send_daily_digest(
        webhook_urls,
        calendar_png_url=f"{cfg.calendar.site_url}/current.png",
        site_url=cfg.calendar.site_url,
        new_posts=new_posts,
        upcoming=upcoming,
        summaries=summaries,
        today=today,
        timeout=cfg.general.http_timeout_seconds,
        retries=cfg.general.http_retries,
    )

    save_state(state_path, state_map)  # last_max_post_id 진행 포함
```

오류 발생 시 `send_alert_to_webhooks`로 `DISCORD_WEBHOOK_ALERT`에 self-alert. `last_max_post_id`는 digest 성공 후에만 진행.

## 7. Configuration

`config/config.toml`:

```toml
[calendar]
enabled = true
output_dir = "docs/calendar"
site_url = "https://7bellaa.github.io/cseDiscordBot/calendar"
months_in_png = 2
font_path = "assets/fonts/Pretendard-Medium.ttf"
```

`.env`/.env.example은 변경 없음.

`pyproject.toml`에 `Pillow>=10` 추가.

## 8. 정적 웹사이트

`docs/calendar/index.html`:

- FullCalendar.io v6 CDN, 빌드 단계 없음.
- 한국어 로케일, 월/주/목록 뷰 토글.
- `fetch('./events.json')` → FullCalendar 이벤트 소스.
- 이벤트 클릭 → 모달: 제목, 카테고리 뱃지, D-N, 원문 링크 버튼.

`docs/calendar/style.css`: 다크 모드 + 모바일 반응형 + 카테고리별 색.

## 9. launchd

`deploy/com.user.cse-bot.plist`의 `StartCalendarInterval`을 **18:00 단일 항목**으로 변경:

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>18</integer>
    <key>Minute</key>
    <integer>0</integer>
</dict>
```

`launchctl unload` → `launchctl load`로 재로드.

## 10. 운영자 1회성 셋업

1. GitHub 리포 Settings → Pages → Source: `Deploy from a branch` → Branch: `main` → Folder: `/docs`
2. ~1분 후 `https://7bellaa.github.io/cseDiscordBot/calendar/` 200 확인
3. `launchctl unload ... && launchctl load ...` 로 plist 18시 단일 스케줄 적용

## 11. Out of Scope (v1)

- iCal(.ics) 구독 — 명시적 제외
- 다일 기간 이벤트 (예: `5/10~5/15`) — v1은 종료일 기준 단일 이벤트
- Discord 봇 slash command — 디테일은 웹 캘린더로
- 사용자별 구독·필터 — 웹 캘린더 카테고리 토글로 갈음
- Gemini 기반 정교한 카테고리 — title prefix 정규식만으로 v1 충분
- 과거 월 보관 뷰 — 웹은 navigation 제공, PNG는 현재+다음 달만

## 12. 예상 작업 규모

| 항목 | 추정 |
|------|------|
| 신규 코드 | ~400~600 LOC (모듈 3개 + 정적 사이트 + 테스트) |
| 기존 파일 수정 | ~80 LOC (main.py 재구성이 가장 큼) |
| 신규 의존성 | 1개 (Pillow) |
| 폰트 파일 | ~2.6MB (Pretendard-Medium, OFL) |
