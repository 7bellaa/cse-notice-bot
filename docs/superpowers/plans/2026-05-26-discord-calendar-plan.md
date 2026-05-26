# Discord 캘린더 — 구현 계획

> 설계 문서: [../specs/2026-05-26-discord-calendar-design.md](../specs/2026-05-26-discord-calendar-design.md)

순서를 정한 task 리스트. 의존성이 있는 step은 위/아래 관계로 표시.

## Phase 0 · 기반 (병렬 가능)

- [x] **1. `.gitignore`에 `.superpowers/` 추가** — 브레인스토밍 scratch 파일이 커밋되지 않게.
- [x] **2. `Pillow>=10` 의존성 + `uv sync --extra dev`** — `pyproject.toml`에 추가 후 dev extras까지 함께 sync.
- [x] **3. Pretendard-Medium 폰트 번들** — `assets/fonts/Pretendard-Medium.ttf` (OFL 라이선스). 한글 렌더 폴백.

## Phase 1 · 핵심 모듈 (TDD)

각 단계는 **테스트 먼저** → **구현** → **`.venv/bin/pytest tests/test_<module>.py -v`**.

- [x] **4. `src/cse_bot/category.py`** — `extract_category`, `category_to_color`, `CATEGORY_PALETTE`, `DEFAULT_COLOR`.
  - `tests/test_category.py`: 실제 학부 공지 제목 픽스처 + 카테고리 매핑 검증.
- [x] **5. `src/cse_bot/models.py` 확장** — `TrackedDeadline.category: str = ""` + `state.py` load/save에 필드 반영. 기존 state.json은 누락 시 기본값으로 흡수.
- [x] **6. `src/cse_bot/web_publisher.py`** — `write_events_json` (FullCalendar 포맷), `git_publish` (diff 없으면 skip).
  - `tests/test_web_publisher.py`: schema 일치, atomic write, git 호출 mocking.
- [x] **7. `src/cse_bot/calendar_renderer.py`** — `render_calendar_png` (Pillow 2개월 다크 톤온톤), `resolve_font_path`.
  - `tests/test_calendar_renderer.py`: 0/1/N건 입력 → PNG 유효성, 다크 배경 픽셀 검증, 한글 입력 무크래시.

## Phase 2 · 출력 (TDD)

- [ ] **8. `src/cse_bot/notifier.py`에 `send_daily_digest` 추가** — 단일 message payload (embed + content), 2000자 truncate, multi-webhook fanout.
  - `tests/test_daily_digest.py`: respx로 webhook HTTP mock, payload 구조 검증, fanout 호출 횟수, 새 공지 0건 시 content 생략.

## Phase 3 · 통합

- [ ] **9. `src/cse_bot/main.py` `run_cycle()` 재구성**
  - 기존 per-post `send_to_webhooks` 제거.
  - `new_posts`, `summaries` 누적.
  - 모든 보드 deadline 합쳐 캘린더 자산 생성.
  - `git_publish` 호출.
  - `send_daily_digest`로 fanout.
  - 실패 시 `_safe_alert`로 self-alert.
  - `last_max_post_id` 진행은 digest 성공 후에만.
  - `tests/test_main_calendar.py`: 모킹된 cycle 단일 message + 자산 파일 작성 + state 진행 검증.

- [ ] **10. `config/config.toml` + `src/cse_bot/config.py`** — `[calendar]` 섹션 추가 + `CalendarConfig` dataclass 로드.

- [ ] **11. `deploy/com.user.cse-bot.plist`** — `StartCalendarInterval` 단일 18:00. 운영자 한정 `launchctl` 리로드.

## Phase 4 · 정적 사이트 (테스트 X — 수동 검증)

- [ ] **12. `docs/calendar/index.html` + `docs/calendar/style.css`** — FullCalendar v6 CDN, 한국어 locale, click → 모달, 다크/모바일 반응형.

## Phase 5 · 검증 & 정리

- [ ] **13. 풀 회귀 테스트** — `.venv/bin/pytest tests/ -v` + `.venv/bin/ruff check src/ tests/`. 기존 테스트도 모두 green.

- [ ] **14. 마무리** — 사용자 메모리에서 `project_pending_schedule_change.md` 삭제 (every-2h 전환 계획은 이번 18시 단일화로 무효). 브라우저 컴패니언 정리. 변경 요약 작성.

## 운영자 1회성 셋업 (코드 외)

1. GitHub repo Settings → Pages: Source `Deploy from a branch` / Branch `main` / Folder `/docs`.
2. `https://7bellaa.github.io/cseDiscordBot/calendar/` 200 확인.
3. `launchctl unload ... && launchctl load ...` 로 plist 재로드 → 다음 18시에 첫 digest 발행.

## 수동 스모크 테스트 (push 후)

1. `.venv/bin/python -m cse_bot.main --config config/config.toml` 1회 실행.
2. `#공지일반` + `개백수방` 두 채널에 PNG 임베드 + bullet 메시지 도착 확인.
3. `docs/calendar/{current.png,events.json}` 갱신 + git log 1줄 추가.
4. 웹에서 `7bellaa.github.io/cseDiscordBot/calendar/` 이벤트 표시 확인.
5. 다음 날 같은 시각에 자동 재발행되며 중복 없음 확인.
