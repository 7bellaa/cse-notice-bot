# PNU CSE Discord Notification Bot

부산대학교 정보컴퓨터공학부 학부 공지([`cse.pusan.ac.kr/cse/14221`](https://cse.pusan.ac.kr/cse/14221/subview.do))를 매일 18:00 KST에 점검해, **신규 공지 1줄 알림 + 마감 캘린더 PNG**를 하나의 Discord 메시지로 발송합니다. 같은 데이터는 GitHub Pages에 인터랙티브 캘린더로도 공개됩니다.

- **Discord 채널**: `DISCORD_WEBHOOK_GENERAL`, `DISCORD_WEBHOOK_JOBLESS` 동시 fan-out
- **웹 캘린더**: <https://7bellaa.github.io/cse-notice-bot/calendar/>
- **알림 트리거**: launchd `StartCalendarInterval` 18:00, KST

## Architecture

매 사이클이 두 흐름을 공유 fetch에서 분기:

```
list page (cse.pusan.ac.kr/cse/14221)
   ├─→ notifier         watermark 기반 신규 공지 → Discord 메시지
   └─→ calendar_publisher (v2.0.0+)
         ├─ post_cache.json   list snapshot + content_hash + 30d TTL
         ├─ manual_deadlines.json   운영자 수동 override
         └─ build_events → calendar PNG + events.json → GitHub Pages
```

- v1 (~v1.3): incremental watermark 단일 모델 — baseline 누락 + stale 누적 + ID 재할당에 취약 (v2 spec §0 참고).
- v2.0.0+: 캘린더는 snapshot 모델로 분리. notifier 흐름은 v1 그대로.

자세한 설계: `docs/superpowers/specs/2026-05-26-calendar-v2-snapshot-spec.md`.

## Requirements

- macOS (launchd 사용)
- Python 3.11+ + [`uv`](https://docs.astral.sh/uv/) (의존성 관리)
- Discord 서버 + webhook URL 2개 + alert용 별도 webhook
- Gemini API key (무료 티어로 충분)

## Setup

```bash
git clone https://github.com/7bellaa/cse-notice-bot.git ~/cseDiscordBot
cd ~/cseDiscordBot
uv sync                              # 의존성 설치 (.venv 자동 생성)

cp .env.example .env
# .env 편집: DISCORD_WEBHOOK_GENERAL, DISCORD_WEBHOOK_JOBLESS,
#           DISCORD_WEBHOOK_ALERT, GEMINI_API_KEY 채우기

# 1회 베이스라인 실행 (알림 없이 watermark만 기록)
set -a; source .env; set +a
.venv/bin/python -m cse_bot.main --config config/config.toml
```

### Gemini API key

1. <https://aistudio.google.com/> → "Get API key" → 새 프로젝트 생성
2. `.env`에 `GEMINI_API_KEY=AIza...` 추가
3. 기본 모델은 **Gemini 2.5 Flash** (이미지 OCR 강함, 포스터에 박힌 마감일 정확 추출). 일일 ~5건 호출 기준 paid tier 월 ~$0.30. 무료 티어 RPD 한도가 빠듯하면 `[gemini].model = "gemini-2.5-flash-lite"`로 내려서 일일 1,000건까지 가능 (텍스트 마감 추출은 거의 동일, OCR만 약함)

### launchd 등록

```bash
bash deploy/install.sh           # 첫 설치 + 1회 즉시 실행
bash deploy/install.sh --no-run  # 18:00까지 대기
```

`deploy/install.sh`는 idempotent — 매 `git pull` 후 다시 실행해 plist를 갱신해도 안전.

## Calendar

- **PNG**: 매일 18:00 cycle에서 Pillow로 2개월 다크 톤온톤 렌더, `docs/calendar/current.png` 갱신 후 git push → GitHub Pages.
- **웹 사이트**: `docs/calendar/` 안의 정적 FullCalendar v6. `events.json`을 fetch해서 모달/카테고리 토글/모바일 list 뷰 지원.
- **카테고리** (`category.py`): 장학/등록, 학업/수강, 졸업/진로, 비교과/활동, 일반공지 — 제목 prefix 매칭 + 키워드 fallback.
- **마감 강조**: D-3 옅은 빨강, 당일 옅은 노랑, 오늘 셀 indigo 링, 중요 일정(수강신청·국가장학금 등) 골드 링.

## 운영자 수동 override

자동 추출이 잘못된 마감이나 게시판에 없는 일정을 캘린더에 강제로 넣고 싶을 때 `data/manual_deadlines.json` 편집:

```json
{
  "schema_version": 1,
  "overrides": [
    {
      "id": "manual-1",
      "title": "수강신청 (1·2학년)",
      "url": "https://cse.pusan.ac.kr/...",
      "date": "2026-08-19",
      "category": "학업/수강",
      "important": true
    }
  ]
}
```

같은 URL이 cache에도 있으면 manual override의 `date`/`category`/`important`가 우선합니다. 잘못된 JSON이면 자동 무시 + warning 로그.

## v1.x → v2.0.0 마이그레이션

v1 봇이 돌던 머신에서 처음 v2를 띄울 때만 1회 필요. 절차는 [`docs/MIGRATION_v2.md`](docs/MIGRATION_v2.md) 참고. v2로 새로 설치한 머신은 이 단계 무시.

## 설정

`config/config.toml`:

| 키 | 설명 | 기본 |
|---|---|---|
| `[general].max_pages` | 매 cycle list fetch 페이지 수 | `3` |
| `[notification].format` | 텍스트 알림 포맷 (`minimal`/`medium`/`detailed`) — legacy 모드에서만 사용 | `medium` |
| `[gemini].model` | Gemini 모델 (`gemini-2.5-flash` 또는 `gemini-2.5-flash-lite`) | `gemini-2.5-flash` |
| `[calendar].enabled` | 캘린더+digest 모드 켜기 | `true` |
| `[calendar].cache_ttl_days` | list에서 사라진 글의 cache 보존 기간 | `30` |
| `[calendar].months_in_png` | PNG에 그릴 월 수 | `2` |
| `[[boards]]` 배열 | 게시판별 webhook 환경변수 fan-out | — |

## 운영 메모

- **로그**: `logs/cse_bot.log` (5MB×5 회전), launchd stdout/stderr 별도.
- **State**: `data/state.json` (watermark; notifier 전용), `data/post_cache.json` (캘린더 snapshot), `data/manual_deadlines.json` (override).
- **자동 알람**: parse 빈 결과 3회 연속 → `DISCORD_WEBHOOK_ALERT`로 알림. cache 손상 JSON → 자동 백업 후 빈 cache로 fallback + alert.
- **절전 주의**: 맥북이 18:00에 깨어 있어야 launchd 트리거가 작동.

## Development

```bash
.venv/bin/python -m pytest -q            # 테스트 (현 238개)
.venv/bin/python -m pytest --cov=cse_bot # 커버리지
.venv/bin/python -m ruff check src/ tests/ scripts/
.venv/bin/python -m mypy src/
```

설계/구현 문서:
- `docs/superpowers/specs/` — 디자인 스펙 (v1 ~ v2.0.0)
- `docs/superpowers/plans/` — task별 TDD 구현 계획
- `CHANGELOG.md` — 릴리스 히스토리 + 마이그레이션 runbook

## Uninstall

```bash
launchctl bootout gui/$(id -u)/com.user.cse-bot
rm ~/Library/LaunchAgents/com.user.cse-bot.plist
```
