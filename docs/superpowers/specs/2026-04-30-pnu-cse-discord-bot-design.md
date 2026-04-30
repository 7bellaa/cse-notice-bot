# PNU CSE Discord Notification Bot — Design Spec

- **작성일:** 2026-04-30
- **상태:** Draft (사용자 검토 대기)
- **목표:** 부산대학교 정보컴퓨터공학부 학부 공지사항 게시판에 새 글이 올라올 때마다 디스코드 채널로 알림을 보내는 자동화 봇

---

## 1. 개요 (Overview)

### 1.1 목적
부산대 정컴 학부 공지(`https://cse.pusan.ac.kr/cse/14221/subview.do`)를 정기적으로 점검하여 신규 게시글을 디스코드 채널로 알림한다.

### 1.2 범위
- **대상 사이트:** PNU CSE 일반공지 게시판 (board id `14221`) — 단일 게시판으로 시작, 다중 게시판 확장 가능 구조
- **점검 주기:** 매일 09:00, 18:00 (Asia/Seoul)
- **알림 채널:** 사용자가 운영하는 Discord 서버의 채널 (Webhook 기반)
- **실행 환경:** 사용자 로컬 macOS, launchd로 트리거

### 1.3 비목표 (Non-Goals)
- 양방향 봇 기능 (슬래시 커맨드, 사용자 명령 응답) — webhook 단방향 알림만
- 게시글 본문 미리보기 (1차 범위 제외, 향후 detailed 포맷에서 고려)
- 복수 디스코드 서버 지원 (1차 범위 제외)
- 클라우드 배포 (사용자가 명시적으로 로컬 맥 + launchd를 선택)

---

## 2. 기술 선택 (Technology Decisions)

### 2.1 채택 — Python + Discord Webhook + launchd
| 영역 | 선택 | 비고 |
|---|---|---|
| 언어 | Python 3.11+ | 사용자 선호, 풍부한 스크래핑/HTTP 생태계 |
| HTTP 클라이언트 | `httpx` | 모던, async 확장 여지 |
| HTML 파싱 | `BeautifulSoup4` + `lxml` | 안정적, 사이트 구조에 강건 |
| 디스코드 전송 | Webhook (POST 직접) | 봇 토큰/24/7 프로세스 불필요 |
| 상태 저장 | JSON 파일 | 단순, 사람이 읽을 수 있음 |
| 설정 | TOML + `.env` | 시크릿 분리 |
| 스케줄링 | launchd `.plist` | macOS 표준 |
| 테스트 | `pytest`, `respx`, `freezegun` | |
| 의존성 관리 | `pyproject.toml` (uv 또는 poetry) | |

### 2.2 검토하고 기각한 대안
- **Discord 봇 (`discord.py`)** — 24/7 프로세스 필요, 단방향 알림에 과도한 복잡성
- **GitHub Actions cron** — 클라우드 배포가 사용자 선호 위배
- **Node.js / Go** — Python 선호 명시

---

## 3. 아키텍처 (Architecture)

### 3.1 실행 모델
- **단일 실행 (one-shot)** — launchd가 매 트리거마다 새 프로세스 spawn, 한 사이클 후 종료
- **상태는 파일에 영속** — 메모리에 의존하지 않으므로 재부팅/launchd 재로드에 안전
- **순수 함수 + I/O 분리** — 파싱/diff는 결정론적 순수 함수, 외부 호출은 격리된 I/O 모듈

### 3.2 한 사이클의 데이터 플로우
1. `launchd` → `python -m cse_bot.main` 실행
2. `config.py` — `config/config.toml` + `.env` 로드/검증
3. `state.py` — `data/state.json` 로드 (없으면 베이스라인 모드)
4. 각 활성화된 게시판에 대해:
   1. `fetcher.py` — 게시판 page=1 HTML GET (재시도 포함)
   2. `parser.py` — HTML → `List[Post]`
   3. 만약 page=1의 `min(post_id) > last_max_post_id` (=페이지 1 안에 다 못 잡았을 가능성) → page=2 추가 fetch (상한 2페이지)
   4. `differ.py` — `last_max_post_id`보다 큰 post들 추출, 오름차순 정렬
   5. **베이스라인 모드면** 알림 생략하고 워터마크만 갱신 후 종료
   6. 신규 글 each → `notifier.py`가 webhook POST → 성공 응답 후 즉시 워터마크 갱신 (매 글마다)
5. `state.py` — 최종 상태 저장
6. 정상 종료 (`exit 0`) 또는 self-alert 후 비정상 종료

상세 다이어그램은 `docs/data-flow.md` 참조.

---

## 4. 모듈 구조 (Modules)

### 4.1 디렉토리 레이아웃
```
cseDiscordBot/
├── src/cse_bot/
│   ├── __init__.py
│   ├── main.py              # 엔트리포인트 / 오케스트레이터
│   ├── config.py            # 설정 로드 + 검증
│   ├── models.py            # Post, BoardConfig, BoardState 데이터클래스
│   ├── fetcher.py           # HTTP GET (재시도 포함)
│   ├── parser.py            # HTML → List[Post] (순수 함수)
│   ├── differ.py            # 신규 글 식별 (순수 함수)
│   ├── notifier.py          # Discord webhook POST
│   ├── state.py             # JSON 파일 read/write
│   └── logging_setup.py     # 로깅 설정
├── tests/
│   ├── fixtures/            # HTML 픽스처
│   ├── test_parser.py
│   ├── test_differ.py
│   ├── test_state.py
│   ├── test_config.py
│   ├── test_fetcher.py      # httpx mock
│   ├── test_notifier.py     # webhook mock
│   └── test_main.py         # 통합 테스트
├── config/
│   └── config.toml
├── deploy/
│   └── com.user.cse-bot.plist
├── scripts/
│   ├── gemini_review.sh
│   └── gemini_review_template.md
├── data/
│   └── state.json           # gitignore
├── logs/                    # gitignore
├── docs/
│   ├── data-flow.md
│   └── superpowers/specs/2026-04-30-pnu-cse-discord-bot-design.md
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

### 4.2 모듈별 책임

| 모듈 | 책임 | I/O? | 핵심 의존 |
|---|---|---|---|
| `config.py` | TOML/env 로드, 스키마 검증 | 파일 read | `tomllib`, `os.environ` |
| `models.py` | 데이터클래스 정의 | ❌ | `dataclasses` |
| `fetcher.py` | URL → HTML (지수 백오프 재시도) | HTTP | `httpx` |
| `parser.py` | HTML → `List[Post]` (순수 함수) | ❌ | `bs4`, `lxml` |
| `differ.py` | `(posts, watermark) → new_posts` (순수 함수) | ❌ | (없음) |
| `notifier.py` | `Post` → Discord webhook POST | HTTP | `httpx` |
| `state.py` | state.json load/save, 워터마크 갱신 | 파일 R/W | `json` |
| `main.py` | 위 모듈들 조합 | 위임 | 위 모듈들 |

---

## 5. 데이터 모델 (Data Model)

### 5.1 `Post` — 파싱된 게시글
```python
@dataclass(frozen=True)
class Post:
    id: int                     # post_id (monotonic, 워터마크의 기준)
    title: str
    author: str
    date: str                   # 'YYYY.MM.DD' 그대로 보존 (포맷팅은 notifier 책임)
    url: str                    # 게시글 상세 페이지 절대 URL
    category: str               # 예: '일반공지' (medium 포맷에선 미사용, detailed에서 사용)
    has_attachment: bool        # detailed 포맷에서 사용
```

### 5.2 `BoardConfig` — 게시판 설정
```python
@dataclass(frozen=True)
class BoardConfig:
    id: str                     # '14221'
    name: str                   # '정컴 일반공지'
    url: str                    # 목록 페이지 URL
    webhook_env: str            # 환경변수 이름 (e.g., 'DISCORD_WEBHOOK_GENERAL')
    enabled: bool = True
```

### 5.3 `BoardState` — 영속 상태
```python
@dataclass
class BoardState:
    last_max_post_id: int | None       # None == 베이스라인 모드
    last_checked: str                  # ISO8601
    empty_streak: int = 0              # 파싱 빈 결과 연속 카운트 (self-alert용)
```

### 5.4 `state.json` 스키마
```json
{
  "boards": {
    "14221": {
      "last_max_post_id": 19234,
      "last_checked": "2026-04-30T18:00:00+09:00",
      "empty_streak": 0
    }
  }
}
```

---

## 6. 핵심 알고리즘 — 워터마크 기반 Diff

### 6.1 의도
"이전 사이클에 본 가장 큰 post_id"보다 큰 post들만 새 글로 간주. 정수 1개로 상태 압축.

### 6.2 의사코드
```python
def process_board(board: BoardConfig, board_state: BoardState):
    last_max_id = board_state.last_max_post_id  # None이면 베이스라인

    # 1. fetch (필요 시 페이지 2까지)
    posts: list[Post] = []
    for page in range(1, MAX_PAGES + 1):  # MAX_PAGES = 2
        page_html = fetcher.get(build_url(board.url, page))
        page_posts = parser.parse(page_html)
        if not page_posts:
            raise ParseEmptyError(board.id)
        posts.extend(page_posts)

        if last_max_id is None:
            break  # 베이스라인 — 1페이지면 충분
        if min(p.id for p in page_posts) <= last_max_id:
            break  # 페이지 안에 cutoff 발견됨

    page_max_id = max(p.id for p in posts)  # 고정 공지 섞여 있어도 안전

    # 2. 베이스라인 모드: 알림 X, 워터마크만 저장
    if last_max_id is None:
        board_state.last_max_post_id = page_max_id
        board_state.last_checked = now_iso()
        return

    # 3. diff
    new_posts = sorted(
        [p for p in posts if p.id > last_max_id],
        key=lambda p: p.id  # 오름차순 (오래된 글부터 알림)
    )

    # 4. 알림 + 워터마크 매 성공마다 갱신
    for post in new_posts:
        notifier.send(post, webhook_url=resolve_webhook(board))  # 실패 시 raise
        board_state.last_max_post_id = post.id  # 즉시 갱신 (부분 실패 보존)
        state.save(state_path, all_board_states)  # 갱신을 디스크에 즉시 반영

    board_state.last_checked = now_iso()
    state.save(state_path, all_board_states)
```

### 6.3 불변식 (Invariants)
1. `last_max_post_id`는 **단조 증가**한다 (절대 감소 불가).
2. webhook POST 성공 응답 수신 후에만 워터마크를 갱신한다.
3. 신규 글은 항상 `id` 오름차순으로 전송한다 (오래된 글이 먼저).
4. 베이스라인 모드(첫 실행)에서는 알림 0건.
5. 한 사이클당 최대 2페이지까지만 fetch한다.
6. 부분 실패 시 이미 보낸 것까지 워터마크 반영, 실패 지점부터 다음 사이클 재시도.

---

## 7. 설정 & 시크릿 (Configuration)

### 7.1 `config/config.toml` (commit 함)
```toml
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 2
http_timeout_seconds = 15
http_retries = 3

[notification]
format = "medium"   # "minimal" | "medium" | "detailed"
self_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"

[[boards]]
id = "14221"
name = "정컴 일반공지"
url = "https://cse.pusan.ac.kr/cse/14221/subview.do"
webhook_env = "DISCORD_WEBHOOK_GENERAL"
enabled = true
```

### 7.2 `.env` (gitignore)
```
DISCORD_WEBHOOK_GENERAL=https://discord.com/api/webhooks/.../...
DISCORD_WEBHOOK_ALERT=https://discord.com/api/webhooks/.../...
```

### 7.3 `.env.example` (commit 함)
```
DISCORD_WEBHOOK_GENERAL=https://discord.com/api/webhooks/REPLACE_ME
DISCORD_WEBHOOK_ALERT=https://discord.com/api/webhooks/REPLACE_ME
```

### 7.4 핵심 결정
- 시크릿(webhook URL)은 환경변수에만, TOML/git에 절대 저장하지 않음
- 게시판마다 `webhook_env`로 다른 채널로 라우팅 가능 (확장성)
- `notification.format` 변경만으로 minimal/medium/detailed 전환

---

## 8. 알림 메시지 포맷

### 8.1 1차 (medium, 기본)
```
📢 **새 공지: {title}**
✍️ {author} · 📅 {date}
🔗 {url}
```

### 8.2 향후 옵션 (detailed)
```
📢 **새 공지: {title}**  `[{category}]`
✍️ {author} · 📅 {date} · 📎 {has_attachment ? "첨부 있음" : "첨부 없음"}
🔗 {url}
```

전환은 `config.toml`의 `format` 값만 변경. 코드에서는 formatter 함수 분기.

---

## 9. 에러 처리 (Error Handling)

### 9.1 실패 시나리오 매트릭스
| 단계 | 실패 원인 | 대응 | 재시도 |
|---|---|---|---|
| Config 로드 | TOML 오류, env 누락 | 로그 + `exit 1` | ❌ |
| State 로드 | JSON 손상 | `state.json.corrupt-{ts}`로 백업 후 베이스라인 진입 + self-alert | ❌ |
| HTTP GET | 네트워크/5xx/타임아웃 | 지수 백오프 1s→2s→4s, 최대 3회 | ✅ |
| HTTP GET | 4xx | 즉시 raise, 다음 사이클로 위임 | ❌ |
| HTML 파싱 | 빈 결과 | 빈 리스트 반환, `empty_streak` 증가; 3회 연속이면 self-alert | ❌ |
| Differ | (순수 함수, 실패 없음) | — | — |
| Webhook POST | 5xx/429/타임아웃 | 지수 백오프 1s→2s→4s, 최대 3회 | ✅ |
| Webhook POST | 4xx | 로그, 워터마크 갱신 X, 종료 | ❌ |
| State 저장 | 디스크/권한 | self-alert + `exit 2` | ❌ |
| 사이클 전체 예외 | — | self-alert + `exit 1` | ❌ |

### 9.2 Self-Monitoring
- 별도 webhook(`DISCORD_WEBHOOK_ALERT`) 사용 권장 — 알림 노이즈 분리
- 트리거 조건: 파싱 빈 결과 3회 연속, state 손상, 사이클 미캐치 예외

---

## 10. 테스트 전략 (Testing)

### 10.1 피라미드
- **순수 함수 (parser, differ):** 풍부하게, 15개+ 케이스, 95% 커버리지 목표
- **I/O 모듈 (fetcher, notifier, state):** mock 기반, 80% 커버리지
- **통합 (main.py):** 1~2개 시나리오 (베이스라인 / 정상 / 부분 실패)
- **전체 커버리지 목표:** 85%+

### 10.2 핵심 테스트 케이스

| 모듈 | 케이스 |
|---|---|
| `parser` | 정상 / 고정공지 섞임 / 첨부 아이콘 / 빈 페이지 (`ParseEmptyError`) / 사이트 구조 변경 시뮬 |
| `differ` | watermark=null → 빈 / watermark<max → 신규 / 모두 오래됨 → 빈 / 결과 오름차순 검증 |
| `state` | 첫 로드 / round-trip / 손상 JSON 백업 / 단조 증가 검증 |
| `config` | 정상 / env 누락 / 잘못된 TOML |
| `fetcher` | 200 / 5xx 후 성공 / 5xx 3회 raise / 4xx 즉시 raise / 타임아웃 |
| `notifier` | 정상 / 429 백오프 / 4xx raise |
| `main` | 베이스라인 모드 / 신규 2개 정상 / 두 번째 알림 실패 → 첫 번째까지 워터마크 / 페이지 2 fetch 발동 |

### 10.3 픽스처
- `tests/fixtures/sample_board.html` — 실제 페이지 스냅샷 (회귀 기반)
- `tests/fixtures/empty_board.html`, `pinned_only.html`, `single_page_overflow.html`
- 외부 호출은 절대 실제 사이트/Discord에 도달하지 않도록 mock 강제

### 10.4 도구
- `pytest` + `pytest-cov`
- `respx` 또는 `httpx.MockTransport`
- `freezegun` (시간 기반)
- `ruff check` (린트), `mypy --strict src/` (타입)
- 테스트 + 린트 + 타입 모두 통과해야 task "자가 검증 통과"

---

## 11. 메타 워크플로우 — Gemini CLI 검증

### 11.1 원칙
- Claude Code가 task를 구현하면, 매 task 완료 시 Gemini 3 Pro에게 텍스트 리뷰를 받음
- VERDICT가 PASS여야 다음 task로 진행
- 최대 10회 반복 후 PASS 못 하면 일시 중지 + 사용자 보고

### 11.2 Diff 범위
**옵션 A — uncommitted (`git diff HEAD`)** 채택. task가 끝나면 PASS 후에만 commit.

### 11.3 Gemini 호출
```bash
gemini -m gemini-3-pro < prompt.txt > response.txt
```
(실제 CLI 플래그 이름이 다르면 `gemini --help`로 확인 후 조정)

### 11.4 프롬프트 템플릿 (`scripts/gemini_review_template.md`)
```
You are a strict code reviewer. Review the following changes for the task below.

# Task
<task description>

# Acceptance criteria
<bullet list>

# Diff
<git diff HEAD>

# Test results (already passing)
- pytest: <output summary>
- ruff: clean
- mypy: clean

# Review checklist
1. Does the code satisfy the acceptance criteria?
2. Any logic bugs, race conditions, or unhandled edge cases?
3. Pure functions vs I/O separation respected?
4. Are tests adequate?
5. Naming, readability, dead code?

# Required response format (strict)
VERDICT: PASS | FAIL
ISSUES:
  - <severity: blocker|major|minor> <file:line> <description>
SUGGESTIONS:
  - ...
SUMMARY: <one-line>
```

### 11.5 자동화 스크립트 — `scripts/gemini_review.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail

TASK_FILE="$1"
DIFF_FILE="$(mktemp)"
PROMPT_FILE="$(mktemp)"
RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$DIFF_FILE" "$PROMPT_FILE" "$RESPONSE_FILE"' EXIT

git diff HEAD > "$DIFF_FILE"
TEST_SUMMARY=$(pytest -q 2>&1 | tail -3)

cat > "$PROMPT_FILE" <<EOF
$(cat scripts/gemini_review_template.md)

# Task
$(cat "$TASK_FILE")

# Diff
\`\`\`diff
$(cat "$DIFF_FILE")
\`\`\`

# Test results
$TEST_SUMMARY
EOF

gemini -m gemini-3-pro < "$PROMPT_FILE" > "$RESPONSE_FILE"
cat "$RESPONSE_FILE"

VERDICT=$(grep -E '^VERDICT:' "$RESPONSE_FILE" | head -1 | awk '{print $2}')
[[ "$VERDICT" == "PASS" ]] && exit 0 || exit 1
```

### 11.6 Claude의 task 루프
```
1. task 구현
2. 자가 검증 (pytest + ruff + mypy) — 실패 시 1
3. iteration_count = 0
4. while iteration_count < 10:
       run scripts/gemini_review.sh
       if exit 0: break (PASS → 다음 task)
       parse blocker/major issues
       apply fixes
       iteration_count += 1
       goto 2
5. iteration_count == 10:
       사용자에게 보고:
         - task ID/제목
         - 마지막 Gemini FAIL 응답 전문
         - 시도 변경 요약
         - 진행 결정 요청
       대기
```

### 11.7 사용자 보고 포맷 (10회 실패 시)
```
🛑 Task #N "<제목>" — Gemini 검증 10회 실패. 일시 중지합니다.

[마지막 Gemini 응답]
<전문>

[시도 요약]
- 시도 1: <변경 요지>
- ...
- 시도 10: <변경 요지>

[제안]
1. 사용자가 직접 가이드 제공
2. 일부 변경 되돌리고 다른 접근 재시도
3. acceptance criteria 완화/조정
4. 이 task를 더 작게 분해
```

---

## 12. 운영 (Operations)

### 12.1 launchd plist — `deploy/com.user.cse-bot.plist`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.cse-bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/7bellaa/cseDiscordBot/.venv/bin/python</string>
        <string>-m</string>
        <string>cse_bot.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/7bellaa/cseDiscordBot</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>/Users/7bellaa/cseDiscordBot/logs/launchd.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/7bellaa/cseDiscordBot/logs/launchd.stderr.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

### 12.2 설치
```bash
cp deploy/com.user.cse-bot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.cse-bot.plist
launchctl list | grep cse-bot
launchctl start com.user.cse-bot   # 즉시 1회 실행 (스모크 테스트)
```

### 12.3 운영 주의사항
- 맥이 절전/꺼짐 상태일 때 launchd 트리거를 놓칠 수 있음. 09:00, 18:00에 맥이 깨어 있어야 함
- 보장이 더 필요해지면 `StartInterval`(예: 30분)로 바꾸고 코드 안에서 윈도우 체크 — 1차 범위에서는 미적용

### 12.4 로깅
- 위치: `logs/cse_bot.log`
- 회전: `RotatingFileHandler`, 파일당 5MB, 최대 5개 (총 25MB 상한)
- 포맷: 구조화 key=value (`grep` 친화)
- 레벨 사용:
  - `INFO` — 사이클 시작/종료, fetch 결과, 알림 성공
  - `WARNING` — 재시도, 빈 파싱, 페이지 2 발동
  - `ERROR` — 재시도 실패, 4xx, 파일 I/O 오류
  - `CRITICAL` — 사이클 전체 실패, state 손상

---

## 13. 보안 (Security)

- Webhook URL은 `.env`에만, git에 절대 commit 금지 (`.gitignore`로 강제)
- `data/state.json`, `logs/`, `.env`, `.venv/` 모두 gitignore
- HTTP 요청 시 `User-Agent`를 명시적으로 설정해 식별 가능하게 (`cse-discord-bot/0.1`)
- 대상 사이트의 `robots.txt`를 확인하고 합리적인 호출 빈도(하루 2회)로 제한 — 이미 충족됨

---

## 14. 향후 확장 포인트 (Out of Scope, 시드만 심어둠)

- **다중 게시판** — `config.toml`에 `[[boards]]` 추가만으로 동작 (state.json도 자동 분리)
- **상세 포맷** — `notification.format = "detailed"`로 전환만 하면 본문 코드는 변경 없음
- **본문 미리보기** — 게시글 상세 페이지를 추가 fetch하는 새 모듈 (`detail_fetcher.py`) 추가
- **다중 Discord 채널** — `webhook_env`만 게시판마다 다르게 지정
- **양방향 봇** — 필요해질 때 Option B(`discord.py`)로 마이그레이션, 스크래핑/diff 로직은 그대로 재사용

---

## 15. 구현 순서 (참고)

상세 task 분해는 다음 단계(`writing-plans`)에서 작성. 대략적인 구현 순서:
1. 프로젝트 스캐폴드 (`pyproject.toml`, 디렉토리, `.gitignore`, `.env.example`)
2. `models.py` — 데이터클래스
3. `parser.py` + 단위 테스트 (실제 사이트 HTML 픽스처 수집)
4. `differ.py` + 단위 테스트
5. `state.py` + 단위 테스트
6. `config.py` + 단위 테스트
7. `fetcher.py` + 단위 테스트 (mock)
8. `notifier.py` + 단위 테스트 (mock)
9. `main.py` + 통합 테스트
10. 로깅 + self-alert
11. `gemini_review.sh` + 템플릿 (실제로는 task 1 직후부터 사용)
12. launchd plist + README 설치 가이드
13. 스모크 테스트 (실제 사이트 1회 fetch + 베이스라인 저장 확인)

각 단계 종료 시 Gemini PASS를 받고 다음으로 진행.

---

## 16. 수용 기준 (Acceptance Criteria for the whole project)

- [ ] launchd가 09:00/18:00에 봇을 트리거한다
- [ ] 첫 실행 시 알림은 0건, `state.json`에 워터마크가 저장된다
- [ ] 두 번째 이후 실행에서 새 글이 있으면 medium 포맷으로 디스코드에 알림이 전송된다
- [ ] 새 글이 없으면 알림 없이 정상 종료한다
- [ ] webhook이 일시 실패해도 다음 사이클이 누락된 글을 보낸다
- [ ] HTML 파싱이 3회 연속 빈 결과면 self-alert가 발송된다
- [ ] 모든 자동 테스트가 통과한다 (`pytest`, `ruff`, `mypy --strict`)
- [ ] 모든 task가 Gemini 3 Pro PASS를 받았다
- [ ] `.env`/`state.json`/`logs/`가 git에 들어가지 않는다
