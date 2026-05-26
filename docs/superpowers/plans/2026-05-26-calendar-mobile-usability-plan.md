# PNU CSE 캘린더 — 모바일 사용성 패치 (v1.2.0) 구현 계획

## Context

PNU CSE 마감 캘린더는 데스크톱(1080+) 중심으로 진화해 왔고, P0 패치(v1.1.0)에서 일부 모바일 대응이 들어갔다. 그러나 360 / 390 / 414 / 768px 실측에서 여전히 *남은 사용성 결손*이 존재한다 — 특히 (a) 좁은 셀에 욱여넣는 월 뷰 이벤트 칩, (b) 360px에서의 hero·헤더 안정성, (c) iPhone 노치/홈 인디케이터, (d) 모바일 전용 짧은 서브카피의 부재. 본 패치는 v1.2.0으로 이 결손을 닫는다.

작성한 새 스펙(MOB-1 ~ MOB-9, 9항목)을 정식 문서로 저장하고, **현재 코드 베이스를 실제로 읽어 본 결과 약 60%는 이미 P0에서 구현되어 있다**는 사실에 기반해 *진짜 갭만* 좁히는 형태로 작업을 진행한다 (사용자 확인 완료: "갭만 구현 + 기존 검증").

## 0. 스펙 문서 저장

지정 경로:
- **`docs/superpowers/specs/2026-05-26-calendar-mobile-usability-spec.md`** — 본 대화에 첨부된 9항목 스펙 전문(verbatim)을 그대로 저장. 표/코드 블록 포함.
- 명명 규칙은 같은 디렉터리의 `2026-05-26-calendar-p0-improvements-spec.md`를 따른다.

저장 후 `git status`에서 untracked로 잡혀야 한다 (커밋은 별도).

## 1. 현재 상태 매핑 (실측 → 코드)

| 스펙 ID | 항목 | 현재 상태 | 액션 |
|---|---|---|---|
| MOB-1 | 모바일 기본 = 목록 뷰 | ✅ `index.html:116-120 preferredInitialView()` + sessionStorage | **검증만** (TC1~TC4) |
| MOB-2 | 월 뷰 Bottom Sheet | ❌ 부재 | **신규 구현** |
| MOB-3a | 헤더 세로 스택 | ✅ `style.css:751-766` | **검증만** |
| MOB-3b | 툴바 2행 | ✅ `style.css:795-819` | **검증만** |
| MOB-3c | "마감일" 히어로 워드 | ⚠️ 의도된 디자인(640px→64px, 480px→48px) | **유지 + 360px 미세조정(40px)** |
| MOB-4 | 단어 단위 줄바꿈(keep-all) | △ chip-title에만 적용 (`style.css:656`) | **전역 base + 안전 회귀 점검** |
| MOB-5a | 버튼 44pt | ✅ `style.css:812-814` | **검증만** |
| MOB-5b | chip 44pt / 셀 56pt | ❌ 미적용 | **신규 추가** |
| MOB-6 | 범례 상단 + 가로 스크롤 | ✅ `index.html:31-58` 마크업 상단, `style.css:770-791` 스크롤 | **검증만** |
| MOB-7 | 가로 스크롤 차단 | ✅ `style.css:730 html, body { overflow-x: hidden }` | **검증만** (scrollWidth 측정) |
| MOB-8 | safe-area-inset | ❌ 부재 | **신규 추가** |
| MOB-9 | 모바일 단축 서브카피 + ⓘ | ❌ `index.html:15`은 풀 카피 그대로 | **신규 추가** |

## 2. 신규 구현 — 최소 변경

### 2.1 `docs/calendar/style.css`

**(a) 360px 추가 브레이크포인트 (MOB-3c)**
```css
@media (max-width: 360px) {
  .hero-word { font-size: 40px; border-bottom-width: 3px; }
  .site-head { padding: 12px 14px; }
  .brand { font-size: 13px; }
}
```

**(b) 전역 keep-all 베이스 (MOB-4)**
파일 상단 `:root` 직후 또는 `html, body` 룰셋 안에 추가:
```css
html { word-break: keep-all; overflow-wrap: anywhere; }
```
범례·툴바·badge·github-link 등의 영문 단어는 이미 `white-space: nowrap` 또는 짧으므로 회귀 위험 낮음. 그러나 `chip-tag`(영문 카테고리 토큰)는 보존되어야 하므로 `white-space: nowrap` 유지(line 635, 이미 있음).

**(c) 터치 타깃 보정 (MOB-5b)**
`@media (max-width: 768px)` 블록에 추가:
```css
@media (max-width: 768px) {
  .fc .fc-daygrid-event { min-height: 44px; padding: 8px 10px; }
  .fc .fc-daygrid-day-frame { min-height: 64px; }
  .fc .fc-daygrid-day-number { padding: 10px 12px 6px; }
  .legend-chip { min-height: 36px; padding: 4px 8px; }
}
```
주의: 월 뷰가 Bottom Sheet로 전환되면 `.fc-daygrid-event`는 사실상 표시되지 않으므로 충돌 없음. 단 사용자가 모바일에서 명시적으로 월 뷰를 선택할 때만 활성.

**(d) safe-area-inset (MOB-8)**
```css
body {
  padding-top: env(safe-area-inset-top);
  padding-bottom: env(safe-area-inset-bottom);
}
.day-sheet {
  padding-bottom: max(env(safe-area-inset-bottom), 16px);
}
```
또한 `index.html:5` 메타 태그에 `viewport-fit=cover` 추가.

**(e) Bottom Sheet 컴포넌트 (MOB-2)**
새 블록을 파일 하단에 추가:
```css
.day-sheet { position: fixed; inset: auto 0 0 0; z-index: 200; max-height: 70vh;
  background: var(--bg-card); border-top: 1px solid var(--border);
  border-radius: var(--r-lg) var(--r-lg) 0 0; box-shadow: var(--shadow-popover);
  transform: translateY(100%); transition: transform 0.22s ease-out;
  display: flex; flex-direction: column; }
.day-sheet[data-open="true"] { transform: translateY(0); }
.day-sheet__handle { width: 36px; height: 4px; background: var(--border);
  border-radius: 2px; margin: 8px auto 4px; }
.day-sheet__header { padding: 4px 20px 12px; font-weight: 600; font-size: 15px; }
.day-sheet__list { padding: 0 16px 16px; overflow-y: auto; }
.day-sheet__backdrop { position: fixed; inset: 0; z-index: 199; background: rgba(15,23,42,0.32);
  backdrop-filter: blur(3px); opacity: 0; transition: opacity 0.22s; pointer-events: none; }
.day-sheet__backdrop[data-open="true"] { opacity: 1; pointer-events: auto; }
@media (min-width: 769px) { .day-sheet, .day-sheet__backdrop { display: none !important; } }
```

**(f) 모바일 월 뷰 셀 — 이벤트 칩 숨기고 dot 마커만 (MOB-2)**
```css
@media (max-width: 768px) {
  body[data-view="dayGridMonth"] .fc-daygrid-event-harness { display: none; }
  body[data-view="dayGridMonth"] .fc-daygrid-day-events { padding: 0 6px 4px; min-height: 12px; }
  .day-dots { display: flex; gap: 3px; padding: 0 4px 4px; }
  .day-dot { width: 6px; height: 6px; border-radius: 50%; }
  .day-dots__more { font-size: 9px; color: var(--text-tertiary); }
}
```
점 색상은 카테고리 팔레트 재사용.

### 2.2 `docs/calendar/index.html`

**(a) 메타 태그 보강 (MOB-8)**
```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
```

**(b) 모바일 단축 카피 + ⓘ (MOB-9)**
현재 `index.html:15`의 `<div class="brand-subtitle">`를 다음과 같이 분리:
```html
<div class="brand-subtitle brand-subtitle--full">각 일정은 해당 날짜에 마감되는 공지입니다 (공지 게시일 아님)</div>
<div class="brand-subtitle brand-subtitle--short">마감일 기준 캘린더입니다.
  <button class="info-pop" type="button" aria-label="자세히 보기" data-info-toggle>ⓘ</button>
</div>
```
CSS 측에서 `@media (max-width: 768px)`로 `--full`은 숨기고 `--short`만 노출. 데스크톱은 반대. ⓘ 클릭 시 작은 토스트/팝오버(기존 `event-tooltip` 패턴 재사용)로 풀 카피 노출.

**(c) Bottom Sheet DOM (MOB-2)**
`<main>` 직후, `</body>` 직전에 추가:
```html
<div id="day-sheet-backdrop" class="day-sheet__backdrop" data-close-sheet></div>
<aside id="day-sheet" class="day-sheet" role="dialog" aria-modal="true" aria-labelledby="day-sheet-title" hidden>
  <div class="day-sheet__handle" aria-hidden="true"></div>
  <header class="day-sheet__header"><span id="day-sheet-title">2026년 5월 27일</span>
    <button class="modal-close" data-close-sheet aria-label="닫기">×</button>
  </header>
  <div id="day-sheet-list" class="day-sheet__list"></div>
</aside>
```

**(d) JS — 모바일 월 뷰 인터셉트 (MOB-2)**
인라인 `<script>` 내부에 다음 로직 추가:
- `datesSet` 콜백에서 `document.body.dataset.view = info.view.type` 세팅 → CSS가 `body[data-view="dayGridMonth"]` 셀렉터로 칩 숨김.
- `dateClick` 핸들러를 추가하여 모바일 + 월 뷰일 때 해당 날짜의 이벤트를 모아 Bottom Sheet 오픈.
- `dayCellDidMount`에서 일정 수에 따라 dot 마커(최대 3 + `+N`)를 셀 내부에 삽입.
- 스와이프 다운 닫기는 `touchstart/touchmove/touchend`로 간단히 (라이브러리 없이, gzip 예산 6KB 이내).
- ESC, 배경 탭 닫기 동일.

**(e) 매직 키: 1회성 토스트 (MOB-2 리스크 완화)**
첫 모바일 진입 시 sessionStorage 키 `mobile.hint.seen`이 없으면 "📅 모바일에서는 목록 뷰가 기본입니다 (월 ↻ 가능)" 토스트 2.5초.

## 3. 검증 항목 (기존 구현)

신규 작업 전에 다음 회귀 점검을 1회 수행:
1. Chrome DevTools 디바이스 모드: 360 / 375 / 390 / 414 / 768px.
2. 각 폭에서 `document.documentElement.scrollWidth === window.innerWidth` 확인 (MOB-7).
3. 모바일에서 첫 진입 시 listMonth가 자동 노출되는지 (MOB-1).
4. 월 선택 → 새로고침 후 dayGridMonth 유지 (MOB-1).
5. 범례 가로 스크롤 동작 (MOB-6).
6. 헤더 요소 겹침/줄바꿈 없음 (MOB-3).

회귀 발견 시 별도 P0 핫픽스로 분리, v1.2.0과 묶지 않는다.

## 4. 신규 테스트 (`tests/test_calendar_renderer.py` 외)

PNG 렌더러는 모바일과 무관하므로 신규 테스트는 다음과 같이 분리:

- `tests/test_calendar_web_assets.py` (신규):
  - `docs/calendar/index.html`에 `viewport-fit=cover`가 포함되어 있는지 텍스트 어서션.
  - `<div id="day-sheet">`, `<button data-info-toggle>`가 마크업에 존재하는지.
  - `docs/calendar/style.css`에 `safe-area-inset`, `.day-sheet`, `@media (max-width: 360px)` 룰셋이 존재하는지 grep 어서션.

이 정적 어서션은 Playwright 도입 없이 빠르게 회귀를 막는다. 실제 모바일 인터랙션은 수동 QA로 검증.

## 5. 비범위

- PWA / 오프라인 캐싱.
- 푸시 알림.
- 검색/필터.
- PNG 렌더러(`src/cse_bot/calendar_renderer.py`) — 본 패치는 웹 HTML만 대상.

## 6. 변경 파일 목록

| 파일 | 변경 종류 |
|---|---|
| `docs/superpowers/specs/2026-05-26-calendar-mobile-usability-spec.md` | 신규 (스펙 전문) |
| `docs/superpowers/plans/2026-05-26-calendar-mobile-usability-plan.md` | 신규 (본 문서 사본을 프로젝트에 보관) |
| `docs/calendar/index.html` | viewport-fit, brand-subtitle 분리, day-sheet DOM, JS 로직 추가 |
| `docs/calendar/style.css` | 360px 브레이크포인트, 전역 keep-all, chip 44pt, safe-area, day-sheet 스타일, 모바일 월 뷰 dot 마커 |
| `tests/test_calendar_web_assets.py` | 신규 (정적 어서션) |
| `CHANGELOG.md` | v1.2.0 항목 추가 |

## 7. 검증(Verification)

작업 완료 시:
1. `./.venv/bin/python -m pytest -x -q` — 전체 통과.
2. `ruff check` — 0건 위반.
3. 로컬 정적 서버(`python -m http.server -d docs/calendar 8765`) 띄우고 5개 디바이스 폭(360/375/390/414/768/1280)에서:
   - 첫 진입 뷰가 폭별로 올바른가.
   - 월 선택 후 dateClick → Bottom Sheet 노출.
   - 일정 없는 날짜 탭 → empty state.
   - ⓘ 클릭 → 풀 카피 토스트.
   - 가로 스크롤바 부재.
   - 모달은 기존대로 단일 이벤트 상세에 유지.
4. 데스크톱(1280px) 스모크: 기존 동작 100% 유지(회귀 없음).
5. `CHANGELOG.md` 갱신 + 스크린샷 첨부.

## 8. 일정 가이드 (3영업일)

| Day | 작업 |
|---|---|
| D1 | 스펙 파일 저장, 기존 구현 회귀 점검(섹션 3), 전역 keep-all + 360px 브레이크포인트 + safe-area |
| D2 | Bottom Sheet 컴포넌트(CSS + DOM + JS), 모바일 월 뷰 셀 dot 마커, 1회성 토스트 |
| D3 | MOB-9 단축 카피 + ⓘ, chip 44pt, `tests/test_calendar_web_assets.py`, 디바이스 매트릭스 수동 QA, CHANGELOG |

## 9. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| 전역 `word-break: keep-all` 적용으로 영문 단어가 의도와 달리 한 줄 강제 | 영문 카피 회귀 | `overflow-wrap: anywhere` 동시 적용으로 길이 초과 시 줄바꿈 허용. `chip-tag` 등 nowrap 유지 부위만 화이트리스트. |
| `body[data-view]` 전역 셀렉터가 다른 뷰(목록)에 영향 | 목록 뷰 회귀 | 셀렉터 범위 `body[data-view="dayGridMonth"] .fc-daygrid-event-harness`로 한정 — 목록 뷰는 `data-view="listMonth"`이므로 영향 0. |
| Bottom Sheet 스와이프 핸들러 라이브러리 도입 유혹 | 번들 증가 | 순수 touch event 30~50줄로 직접 구현. gzip 예산 6KB 이내. |
| 사용자가 모바일 월 뷰를 선호하는데 셀에 일정이 안 보이면 불만 | 학습 비용 | 1회성 안내 토스트 + dot 마커로 일정 유무는 즉시 가시화. |
| safe-area 패딩이 PC 브라우저(env 미지원)에서 0으로 무시되는지 확인 | 데스크톱 회귀 | `env()`는 미지원 환경에서 0 fallback. 영향 없음. |
