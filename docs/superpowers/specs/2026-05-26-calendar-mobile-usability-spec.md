# PNU CSE 마감 캘린더 — 모바일 사용성 개선 스펙

- **문서 버전**: v1.0
- **작성일**: 2026-05-26
- **대상 릴리스**: v1.2.0 (Mobile Usability Patch)
- **타깃 환경**: iOS Safari 16+, Android Chrome 최근 2버전, 360 ~ 768px
- **선행 조건**: P0 스펙(v1.1.0) 반영 여부와 무관하게 적용 가능. 단, 디자인 토큰/카테고리 색상 시스템은 기존 유지.
- **예상 소요**: 2 ~ 3 영업일 (Frontend 1명)

---

## 0. 개요

본 문서는 360 / 390 / 768px 모바일 환경에서 관찰된 실측 문제(월 뷰 가로 스크롤, 단어 단위 줄바꿈, 헤더 겹침/줄바꿈, 작은 터치 타깃, 범례 위치, 의도치 않은 "마감일" 텍스트 노출 등)를 해결하기 위한 구현 스펙이다. 데스크톱 동작은 회귀 없이 유지되어야 한다.

### 0.1 항목 목록
| ID | 제목 | 우선순위 |
|---|---|---|
| MOB-1 | 모바일 기본 뷰 자동 전환 (월 → 목록) | Critical |
| MOB-2 | 월 뷰 모바일 폴백 (날짜+점 마커 + Bottom Sheet) | High |
| MOB-3 | 헤더/툴바 세로 스택 레이아웃 | Critical |
| MOB-4 | 텍스트 줄바꿈 정책 정상화 (`break-all` 제거) | Critical |
| MOB-5 | 터치 타깃 44pt 보정 | High |
| MOB-6 | 범례 상단 배치 + 가로 스크롤 chips | Medium |
| MOB-7 | 가로 스크롤 차단 및 뷰포트 안정화 | Critical |
| MOB-8 | 안전 영역(safe-area) 및 상태바 대응 | Medium |
| MOB-9 | 모바일 마이크로카피/단축 카피 | Low |

---

## 1. MOB-1 · 모바일 기본 뷰 자동 전환 (월 → 목록)

### 1.1 배경
실측 결과 모바일 폭에서 월 뷰는 사실상 사용 불가능한 반면, 목록 뷰는 이미 모바일에서도 잘 동작한다. 가장 적은 비용으로 사용성을 회복하는 길은 모바일에서 목록을 기본으로 노출하는 것이다.

### 1.2 목표
- ≤ 768px 첫 진입 시 목록 뷰가 기본 노출.
- 사용자가 명시적으로 "월"을 선택하면 같은 세션 내 유지.

### 1.3 범위
- `useDefaultView` 훅/유틸 신규.
- 페이지 진입 시 1회 결정. 이후는 사용자 선택 우선.

### 1.4 구현 상세
```ts
// view-preference.ts
const KEY = 'cal.view.session';

export function resolveInitialView(): 'month' | 'list' {
  const stored = sessionStorage.getItem(KEY);
  if (stored === 'month' || stored === 'list') return stored;
  const isMobile = window.matchMedia('(max-width: 768px)').matches;
  return isMobile ? 'list' : 'month';
}

export function persistView(view: 'month' | 'list') {
  sessionStorage.setItem(KEY, view);
}
```
- 토글 클릭 시 `persistView` 호출.
- 페이지 새로고침 시 `sessionStorage`가 우선, 없으면 폭 기반 결정.
- `localStorage`가 아닌 `sessionStorage`를 사용해 탭을 닫으면 다음 진입 시 다시 폭 기반으로 결정한다(첫 사용자 경험 보장).

### 1.5 수용 기준
- [ ] 모바일 폭에서 첫 진입 시 목록 뷰가 기본으로 표시된다.
- [ ] 모바일에서 "월"을 클릭한 뒤 새로고침해도 같은 세션 동안 월 뷰가 유지된다.
- [ ] 데스크톱에서는 기존과 동일하게 월 뷰가 기본이다.

### 1.6 테스트 케이스
| TC | 조건 | 기대 |
|---|---|---|
| TC1 | 360px, sessionStorage 비어 있음 | 목록 뷰 |
| TC2 | 1280px, sessionStorage 비어 있음 | 월 뷰 |
| TC3 | 360px에서 월 선택 → 새로고침 | 월 뷰 유지 |
| TC4 | 탭 닫고 다시 모바일 진입 | 목록 뷰 |

---

## 2. MOB-2 · 월 뷰 모바일 폴백 (Bottom Sheet 패턴)

### 2.1 배경
사용자가 모바일에서 굳이 월 뷰를 선택했을 때, 좁은 셀에 이벤트 칩을 그대로 욱여넣으면 가독성이 깨진다. 셀에서는 "일정 유무"만 표시하고 상세는 별도 영역에서 보여주는 방식이 표준 패턴이다.

### 2.2 목표
- ≤ 768px에서 월 뷰의 셀은 날짜 + 점 마커만 표시.
- 날짜 탭 시 하단 시트로 해당 날짜 일정 목록 표시.

### 2.3 구현 상세
- 셀 마크업:
  ```html
  <button class="cell" aria-label="5월 27일, 1건 일정">
    <span class="day-num">27</span>
    <span class="dots">
      <span class="dot dot--extra" aria-hidden="true"></span>
    </span>
  </button>
  ```
- 점 마커는 최대 3개 + `+N` 텍스트.
- Bottom Sheet:
  - 위치: `position: fixed; left:0; right:0; bottom:0;`
  - 높이: `max-height: 70vh`, 내용 스크롤.
  - 드래그/스와이프로 닫기, 배경 탭 시 닫기, ESC 닫기.
  - 첫 포커스는 시트 내부 첫 일정으로 이동.
- 시트 내부는 P0의 카테고리 칩 + 2줄 라벨 + 외부 링크 아이콘 패턴을 그대로 재사용.

### 2.4 수용 기준
- [ ] 모바일 월 뷰의 셀에서 이벤트 칩 텍스트가 노출되지 않는다.
- [ ] 일정이 있는 날짜는 점 마커(최대 3 + `+N`)로 표시된다.
- [ ] 날짜 탭 → 0.2s 이내 Bottom Sheet 오픈.
- [ ] 시트는 스와이프 다운/배경 탭/ESC로 닫힌다.

### 2.5 테스트 케이스
| TC | 시나리오 | 기대 |
|---|---|---|
| TC1 | 5/27 탭 | "AI Booster" 1건 노출 시트 |
| TC2 | 일정 없는 5/15 탭 | "이 날짜에 마감 일정이 없습니다" empty state |
| TC3 | 시트 열린 상태에서 외부 링크 탭 | 새 탭 열림, 본 페이지는 시트 유지 |

---

## 3. MOB-3 · 헤더/툴바 세로 스택 레이아웃

### 3.1 배경
실측에서 헤더 메타("0건 마감 예정", "↗ GitHub")가 가로 정렬 강제로 줄바꿈/겹침이 발생. 또한 의도치 않게 큰 "마감일" 텍스트가 모바일에서만 노출됨(원인: 폴백/오버라이드 CSS 추정).

### 3.2 구현 상세
- ≤ 768px:
  ```css
  .header { flex-direction: column; align-items: flex-start; gap: 6px; }
  .header .meta { gap: 10px; font-size: 12px; }
  .header .meta a { white-space: nowrap; }
  /* 의도치 않은 모바일 전용 큰 텍스트 제거 */
  .legacy-mobile-title { display: none !important; }
  ```
- 툴바:
  - 1행: ← → 오늘 / 월/목록 토글 (양끝 정렬).
  - 2행: "2026년 5월" (중앙, 17px bold).
- 안전 폭: 모든 헤더 텍스트는 `min-width: 0`을 가지며 ellipsis 적용.

### 3.3 수용 기준
- [ ] 360/390/414px에서 헤더 요소 겹침/줄바꿈 없음.
- [ ] "마감일" 큰 텍스트가 모바일에서 더 이상 표시되지 않는다.
- [ ] "0건 마감 예정"이 한 줄에 표시된다.

---

## 4. MOB-4 · 텍스트 줄바꿈 정책 정상화

### 4.1 배경
이벤트 라벨/날짜 라벨이 글자 단위로 줄바꿈("야/룸/장/학/금")되어 한국어 가독성이 0에 가까움. `word-break: break-all`이 광범위하게 적용된 것으로 추정.

### 4.2 구현 상세
- 글로벌 베이스:
  ```css
  :root { word-break: keep-all; overflow-wrap: anywhere; }
  ```
- 한국어 친화 정책:
  - 일반 텍스트: `word-break: keep-all; overflow-wrap: anywhere;`
  - 긴 URL/영문 일련: 필요 시 컴포넌트 레벨에서 `break-word` 허용.
- `.day-num`: 한 줄 강제 `white-space: nowrap;`
- `.event-chip__title`: `line-clamp: 2`, `keep-all`.

### 4.3 수용 기준
- [ ] 768px에서 칩 텍스트가 어절 기준으로 줄바꿈된다.
- [ ] 날짜 숫자가 "27 / 일" 식으로 두 줄로 나뉘지 않는다.
- [ ] 영문 단어가 단일 줄에서 의도와 다르게 잘리는 회귀가 없다.

---

## 5. MOB-5 · 터치 타깃 44pt 보정

### 5.1 배경
이전/다음/오늘 버튼, 일정 칩 등이 터치 권장 크기(44×44pt, Apple HIG / 48dp Android) 미달.

### 5.2 구현 상세
```css
@media (max-width: 768px) {
  .btn, .view button { min-height: 44px; min-width: 44px; }
  .chip { min-height: 44px; padding: 10px 12px; }
  .day-cell { min-height: 56px; }
  .icon-link { padding: 12px; }
}
```
- 아이콘만 있는 버튼은 `aria-label` 필수.
- 시각 크기와 hit-area 분리: 시각적으로 작게 보이고 싶은 경우 `::before` 확장 영역 사용.

### 5.3 수용 기준
- [ ] 모든 인터랙티브 요소의 hit-area ≥ 44×44px.
- [ ] 인접 요소 간 간격 ≥ 8px(우발 탭 방지).
- [ ] axe-core "target-size" 위반 0건.

---

## 6. MOB-6 · 범례 상단 배치 + 가로 스크롤 chips

### 6.1 배경
모바일에서 범례가 화면 맨 아래에 있어 색-의미 매핑 파악이 어렵다.

### 6.2 구현 상세
- 위치: 툴바 바로 아래.
- 마크업:
  ```html
  <div class="legend-row" role="list">
    <span class="legend-chip" role="listitem">🟪 장학</span>
    ...
  </div>
  ```
- 스타일:
  ```css
  .legend-row {
    display: flex; gap: 8px; overflow-x: auto;
    scroll-snap-type: x mandatory;
    padding: 8px 16px;
    scrollbar-width: none;
  }
  .legend-row::-webkit-scrollbar { display: none; }
  .legend-chip { scroll-snap-align: start; flex: none; }
  ```
- 가로 스크롤만 허용, 페이지 가로 스크롤은 차단(MOB-7).

### 6.3 수용 기준
- [ ] 첫 페인트에서 범례가 viewport 내에 보인다(360px 기준).
- [ ] 범례 chips는 가로로 스와이프 가능, 페이지 자체는 가로 스크롤되지 않는다.

---

## 7. MOB-7 · 가로 스크롤 차단 및 뷰포트 안정화

### 7.1 배경
360/390px에서 `<body>`가 뷰포트를 초과하여 의도치 않은 가로 스크롤 발생.

### 7.2 구현 상세
- 메타 태그 확인/추가:
  ```html
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  ```
- 글로벌:
  ```css
  html, body { max-width: 100%; overflow-x: hidden; }
  img, svg, table { max-width: 100%; }
  .calendar-grid { min-width: 0; }
  ```
- 디버깅용 가드: 개발 환경에서만 `* { outline: 1px solid rgba(255,0,0,.05); }` 옵션 토글로 overflow 원인 확인 가능하도록.

### 7.3 수용 기준
- [ ] 360/375/390/414/768px 어느 폭에서도 가로 스크롤바가 나타나지 않는다.
- [ ] DevTools에서 `document.documentElement.scrollWidth <= window.innerWidth`.

---

## 8. MOB-8 · 안전 영역(safe-area) 및 상태바 대응

### 8.1 배경
iPhone Notch/Dynamic Island 환경에서 헤더가 노치 아래로 잘리거나, 하단 홈 인디케이터에 Bottom Sheet가 가려질 수 있다.

### 8.2 구현 상세
```css
.app {
  padding-top: env(safe-area-inset-top);
  padding-bottom: env(safe-area-inset-bottom);
}
.bottom-sheet {
  padding-bottom: max(env(safe-area-inset-bottom), 16px);
}
```
- viewport-fit=cover가 메타에 포함됨을 확인(MOB-7).

### 8.3 수용 기준
- [ ] iPhone 시뮬레이터 또는 실기에서 헤더가 노치에 가려지지 않는다.
- [ ] Bottom Sheet 하단 콘텐츠가 홈 인디케이터에 가려지지 않는다.

---

## 9. MOB-9 · 모바일 마이크로카피/단축 카피

### 9.1 배경
서브카피 "각 일정은 해당 날짜에 마감되는 공지입니다 (공지 게시일 아님)"가 좁은 폭에서 3줄로 늘어남.

### 9.2 구현 상세
- 모바일 전용 짧은 카피: "마감일 기준 캘린더입니다."
- 자세한 설명은 헤더 옆 ⓘ 버튼 탭 시 토스트/팝오버로 표시.
- 마크업:
  ```html
  <p class="subtitle subtitle--mobile">마감일 기준 캘린더입니다.
    <button aria-label="자세히 보기">ⓘ</button>
  </p>
  ```

### 9.3 수용 기준
- [ ] 모바일에서 서브카피가 1줄에 표시된다.
- [ ] ⓘ 탭 시 원문 설명이 토스트/팝오버로 노출된다.

---

## 10. 공통 요구사항

### 10.1 브레이크포인트
| 토큰 | 값 | 기준 |
|---|---|---|
| `--bp-sm` | 480px | 소형 폰 |
| `--bp-md` | 768px | 대형 폰 / 소형 태블릿 |
| `--bp-lg` | 1024px | 태블릿 가로 / 데스크톱 |

### 10.2 접근성
- `aria-label`은 모든 아이콘 전용 버튼에 부착.
- Bottom Sheet 오픈 시 background에 `aria-hidden="true"` + 포커스 트랩.
- VoiceOver(iOS), TalkBack(Android) 기본 검증.

### 10.3 성능 예산
- 추가 JS gzip ≤ 6KB.
- Bottom Sheet 애니메이션은 transform/opacity만 사용, 60fps 유지.
- 모바일 LCP < 2.5s (Slow 4G 시뮬레이션 기준).

### 10.4 비범위 (Out of Scope)
- PWA / 오프라인 캐싱.
- 푸시 알림.
- 검색/필터(P1에서 별도 처리).

### 10.5 테스트 매트릭스
| 디바이스/폭 | 브라우저 |
|---|---|
| iPhone SE (375px) | iOS Safari 16 |
| iPhone 14 (390px) | iOS Safari 17 |
| Pixel 7 (412px) | Android Chrome |
| Galaxy S22 (360px) | Android Chrome |
| iPad mini (768px) | iOS Safari |

각 환경에서 다음을 수동 점검:
1. 첫 진입 시 기본 뷰가 목록인지.
2. 가로 스크롤 발생 여부.
3. 월 뷰에서 날짜 탭 → Bottom Sheet 정상 오픈.
4. 외부 공지 링크 새 탭 이동.
5. 헤더/툴바/범례 가독성.

### 10.6 일정 (3영업일 가이드)
| Day | 작업 |
|---|---|
| D1 | MOB-7 가로 스크롤 차단, MOB-3 헤더 스택, MOB-4 줄바꿈 정책 |
| D2 | MOB-1 기본 뷰 전환, MOB-6 범례 상단, MOB-5 터치 타깃 |
| D3 | MOB-2 월 뷰 폴백(Bottom Sheet), MOB-8 safe-area, MOB-9 카피, QA & 회귀 |

### 10.7 릴리스 체크리스트
- [ ] MOB-1 ~ MOB-9 수용 기준 충족
- [ ] 테스트 매트릭스 5개 환경에서 수동 시연 영상/스크린샷
- [ ] axe-core 검사 통과 (target-size, contrast, name-role-value)
- [ ] Lighthouse 모바일 Performance ≥ 90, Accessibility ≥ 95
- [ ] 데스크톱 회귀 없음(1280px 스모크 테스트)
- [ ] `CHANGELOG.md`에 v1.2.0 추가, 스크린샷 첨부

---

## 11. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| Bottom Sheet 도입으로 번들 증가 | LCP 회귀 | 라이브러리 없이 순수 CSS/JS 구현, dynamic import |
| 사용자가 모바일에서 월 뷰를 기대 | 학습 비용 | 첫 진입 시 "📅 모바일에서는 목록 뷰가 기본입니다 (월 ↻ 가능)" 1회성 토스트 |
| `word-break` 변경이 다른 페이지에 영향 | 회귀 | 글로벌 변경은 보수적으로, 컴포넌트 레벨 override 우선 |
| 가로 스크롤 차단이 내부 가로 스와이프(범례)와 충돌 | UX | `overflow-x: hidden`은 `body`/`html`에만, 범례는 자체 컨테이너에서 `overflow-x: auto` |

---

이 스펙을 그대로 진행하면 3영업일 안에 모바일 점수를 "사용 불가" → "정상 사용 가능"으로 끌어올릴 수 있고, P0 스펙(v1.1.0)과도 충돌 없이 통합됩니다.
