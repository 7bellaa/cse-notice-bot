# PNU CSE 마감 캘린더 — 데이터 무결성 사고 대응 스펙

- **문서 버전**: v0.1 (draft)
- **작성일**: 2026-05-26
- **대상 릴리스**: v1.3.0 (Data Integrity Patch)
- **선행 조건**: v1.1.0 (P0) + v1.2.0 (mobile) 위에서 동작
- **예상 소요**: 1 ~ 2 영업일 (Backend 1명 + 진단 0.5일)

---

## 0. 문제 요약

운영 중인 캘린더(`https://7bellaa.github.io/cse-notice-bot/calendar/`)의 `events.json` 12개 이벤트 중 **9개에 데이터 무결성 오류**가 확인되었다 (2026-05-26 22:00 KST 기준 수동 검증).

| 카테고리 | 건수 | 영향 |
|---|---|---|
| URL → 다른 글로 연결 | 7건 | 사용자가 칩 클릭 시 무관한 공지로 이동 |
| 마감일 오차 (글 수정 미반영) | 1건 | 4일 오차, 놓칠 위험 |
| 접근 불가 게시물 노출 | 1건 | "게시물을 찾을 수 없습니다" 에러 |
| 정상 | 3건 | — |

### 0.1 확인된 오류 사례
| ID (events.json) | events.json 제목 | 실제 게시글 제목 |
|---|---|---|
| 1441378 | [장학] 2026-2학기 국가장학금 1차 신청 | 부산대, '구조물 내진설계 경진대회' 개최 |
| 1441377 | [수업] 여름 계절수업 폐강 + 수강정정 | 학생 마음건강 설문 |
| 1441350 | [취업전략과] GLOBAL TALENT FAIR | (주)오뚜기 추천 채용 |
| 1441090 | [AI융합교육원] 해양AI 콘텐츠 경진대회 | 1학기 「성인지 교육」이수 안내 |
| 1441060 | [AI융합교육원] 여름계절학기 AI 부트캠프 | 2026학년도 1학기 성인지 교육 (재확인 필요) |
| 1441381 | IT관 학부생 공간 이용 안내 | 주거안정장학금 시행 계획 |
| 1441020 | TOPCIT 2026 정기 평가 응시 | 2026년 2학기 국가장학금 1차 신청 |
| 1441440 | AI Booster 2기 (start=05-27) | 동일 글 (마감 05-31로 수정됨) |
| 1441120 | 현장실습학기제 참여학생 | "게시물에 접근할 수 없습니다" |

### 0.2 영향
- **사용자 신뢰**: 캘린더가 게재하는 모든 항목의 신뢰도가 떨어짐.
- **Discord 채널**: 봇이 매일 18:00 KST에 같은 events.json 기반으로 다이제스트 + PNG를 보냄 → 잘못된 정보가 매일 재발송됨.
- **GitHub Pages**: 캘린더 페이지가 공개 상태이므로 외부에서 볼 수 있음.

---

## 1. 데이터 흐름 (현재 구조)

```
[ JW CMS 게시판 ]
  https://cse.pusan.ac.kr/cse/14221/subview.do (list)
  https://cse.pusan.ac.kr/bbs/cse/2055/<artclNo>/artclView.do (detail)
                │
                ▼
[ parser.py ] table.board-table tbody tr → Post(id, title, url, date, ...)
                │
                ▼
[ main.py _process_board ]
  - differ.diff(posts, watermark) → new_posts (id > last_max_post_id)
  - 각 신규 글:
      article.fetch_article_content(post.url) → body + images
      summarizer.summarize(body, …) → SummaryResult(summary, deadline, short_summary)
      (Gemini가 본문에서 deadline을 YYYY-MM-DD로 추출)
      ↓
      TrackedDeadline(
          post_id=post.id,        ← parser에서 온 ID
          title=post.title,       ← parser에서 온 제목
          url=post.url,           ← parser에서 온 URL
          date=result.deadline,   ← Gemini가 본문에서 추출
          category=classify(post.title),
          ...
      )
                │
                ▼
[ BoardState.deadlines ] (state.json에 누적 저장, 만료된 것만 prune)
                │
                ▼
[ _emit_daily_digest ]
  state_map의 모든 미만료 deadline 집계
  → render_calendar_png(deadlines, …)
  → write_events_json(deadlines, …)
  → git_publish([docs/calendar/])
```

**핵심 관찰**:
- `post.id`, `post.title`, `post.url`은 **동일한 list page row에서 한 번에 추출** (parser.py `_row_to_post`). 한 row 안에서의 mismatch 가능성은 매우 낮음.
- `TrackedDeadline`은 한 번 추가되면 만료될 때까지 `state.json`에 남아 매 cycle마다 publish됨.

---

## 2. 원인 가설 (사실 기반 진단 필요)

각 가설에 대해 **(확률, 검증 방법, 검증 결과)** 형식. 실제 fix 전에 적어도 가설 1·2·5를 검증해야 한다.

> **2026-05-26 22:50 KST 1차 진단 결과**:
> 게시판 list page(`/cse/14221/subview.do` 1페이지 15개)와 events.json 매핑 결과:
> - events.json의 정상 3건(1441440·1441380·1441379)과 1388562·1441440은 list에 동일 ID로 존재.
> - 나머지 잘못된 7건의 ID(1441378·1441377·1441350·1441120·1441090·1441060·1441381·1441020)는 **list page에 아예 존재하지 않음**.
> - 진짜 글들은 다른 ID(1441111·1441312·1441173 등)로 별도 게시 중.
>
> 결론: H1·H2 (사이트 측 ID 재할당 + 봇의 stale 누적)이 **결합된 시나리오**가 사실로 확인됨. 봇 parser 자체는 fetch 시점엔 정확했지만, 사이트 정책상 게시글 삭제+재게시가 빈번해 `state.json`이 stale 상태가 됨.

### H1. 사이트 측에서 `artclNo`가 재할당됨 (확률 高)
- **추정**: 봇이 fetch 했을 때 ID 1441378 = "국가장학금"이었으나, 그 후 글 삭제/수정으로 같은 artclNo가 다른 글에 재사용됨.
- **근거**: events.json의 모든 ID가 URL 패턴(`/bbs/cse/2055/<id>/artclView.do`)을 따르고 있어 봇 측 ID 추출 자체는 정상. 그런데 현재 그 URL이 다른 글을 반환.
- **검증**:
  1. `https://cse.pusan.ac.kr/cse/14221/subview.do?page=1`을 fetch → 현재 페이지의 각 row에서 `<a href=".../1441378/...">`이 어떤 글로 연결되는지 확인.
  2. 만약 list page에도 같은 ID가 "구조물 내진설계 경진대회"로 매핑되어 있으면 → 봇 잘못이 아님, 사이트 측 재할당.

### H2. 봇 BoardState (`data/state.json`)에 stale 데이터가 누적됨 (확률 高)
- **추정**: 봇이 처음 fetch한 시점의 (id, title, url, date) 튜플이 `deadlines`에 들어가서 만료까지 유지됨. 사이트 변경 후에도 봇이 *재검증하지 않으므로* events.json은 계속 옛 데이터를 publish.
- **근거**: `_prune_expired_deadlines`는 `date < today`만 제거. 데이터 정합성은 검사하지 않음.
- **검증**:
  1. 집 맥북 `/Users/<user>/cseDiscordBot/data/state.json`을 열어 `deadlines` 배열의 가장 오래된 항목 timestamp 확인.
  2. 그 timestamp에 fetch된 게시글의 현재 URL 응답과 events.json의 메타데이터가 일치하는지.

### H3. parser.py가 list page row 내에서 잘못된 td를 매핑 (확률 中→낮음으로 평가)
- **추정**: `_row_to_post`가 한 row 내 td.td-title (제목+href)과 다른 td.td-* (저자/날짜) 사이에 인덱스 mismatch.
- **검증**: parser.py의 단위 테스트가 이미 존재 (`tests/test_…`로 grep). 실제 list page HTML snapshot으로 재현되는지.
- **현재 평가**: row 내에서 a.href와 a.text는 같은 `<a>` 태그 안에서 추출되므로 mismatch가 발생하기 어려움. 그러나 다중 a 태그가 있는 경우를 점검.

### H4. Gemini summarizer가 본문을 hallucinate (확률 中)
- **추정**: `article.fetch_article_content`가 잘못된 본문을 반환했거나 (예: 빈 본문/오류 페이지), Gemini가 그것을 임의로 채워 넣음.
- **근거**: `result.deadline`이 일관되게 합리적인 날짜로 들어옴 → hallucinate라면 더 어색해야 함. 그러나 1441440 케이스(원본은 "기간 연장"이지만 봇은 옛 날짜)는 Gemini가 *옛 버전 본문*을 봤다는 신호.
- **검증**: 봇 로그에서 각 cycle의 `summarizer.invoke` payload 확인 → Gemini에 전달된 body 텍스트가 실제 글과 일치하는지.

### H5. events.json이 hand-crafted sample (확률 낮음)
- **추정**: 봇이 만든 게 아니라 사용자가 테스트용으로 작성한 데이터.
- **검증**: `git log -- docs/calendar/events.json`으로 commit 이력 확인 → "auto: calendar update" 메시지로 만든 commit이 있으면 봇 출력. 단일 hand commit만 있으면 sample.

### H6. 사이트의 reverse proxy / CDN cache pollution (확률 낮음)
- **추정**: cse.pusan.ac.kr의 캐시 레이어가 잘못된 응답을 반환.
- **검증**: 같은 URL을 다른 시간대/다른 client에서 여러 번 fetch했을 때 응답이 일관되는지.

---

## 3. 권장 진단 절차 (실행 순서)

```bash
# Step 1: list page에서 현재 ID 매핑 확인
WebFetch https://cse.pusan.ac.kr/cse/14221/subview.do?page=1 \
  "events.json의 각 ID(1441378 등)가 list 페이지에서 어떤 제목과 매핑되는지"

# Step 2: state.json에서 누적된 deadline 데이터 확인 (집 맥북에서)
python -c "
import json
state = json.load(open('data/state.json'))
for board_id, st in state.items():
    for d in st['deadlines']:
        print(d['post_id'], d['title'], d['date'], d.get('first_seen'))
"

# Step 3: events.json commit 이력 확인 (봇이 자동으로 만든 건지)
git log --oneline -- docs/calendar/events.json

# Step 4: 봇 로그에서 deadline.extracted 라인 확인
grep 'deadline=' logs/launchd.stderr.log | tail -30
```

진단 결과에 따라 H1~H6 중 어느 가설이 맞는지가 결정된다. 가장 가능성 높은 시나리오는 **H1 + H2 조합** (사이트가 ID를 재할당했고, 봇은 stale 데이터를 계속 publish 중) — 이 경우 fix는 *재검증 로직 도입*이다.

---

## 4. 해결 방안 (가설별 fix)

### 4.1 H1·H2 (재할당 + stale) — 권장 baseline fix
누구 잘못인지와 별개로 봇은 *publish 전*에 자신이 publish하려는 데이터가 여전히 유효한지 검증해야 한다.

**(a) publish 전 sanity check** — `_emit_daily_digest` 안, `write_events_json` 호출 직전에:
```python
def _validate_deadlines(deadlines: list[TrackedDeadline]) -> list[TrackedDeadline]:
    """Drop deadlines whose URL no longer resolves to the original post."""
    valid: list[TrackedDeadline] = []
    for d in deadlines:
        content = article.fetch_article_content(d.url, ...)
        if content is None:
            log.warning("validate.unreachable post_id=%d url=%s", d.post_id, d.url)
            continue
        # 제목이 처음 fetch했을 때와 크게 달라졌으면 (예: 70% 미만 일치) drop.
        if not _titles_match(d.title, content.title):
            log.warning(
                "validate.title_drift post_id=%d original=%r current=%r",
                d.post_id, d.title, content.title,
            )
            continue
        valid.append(d)
    return valid
```
- `_titles_match`: 공백/괄호 제거 후 자모 단위 ratio (예: `difflib.SequenceMatcher.ratio() > 0.5`).
- 매 cycle마다 모든 deadline에 대해 fetch가 발생하므로 비용 우려 → cycle당 12개면 충분히 감당 가능. 만약 100개를 넘으면 sample/age 기반 검증으로 전환.

**(b) drift 알림** — sanity check에서 drop된 항목이 N개 이상이면 `_safe_alert`로 운영자 채널에 통보:
```python
dropped = len(deadlines) - len(valid)
if dropped >= 1:
    _safe_alert(cfg, f"calendar drift: {dropped} deadlines dropped due to URL mismatch")
```

**(c) state pruning** — sanity check를 통과 못한 deadline은 BoardState에서도 제거해 누적되지 않도록:
```python
for board_state in state_map.values():
    board_state.deadlines = [d for d in board_state.deadlines if d in valid_set]
```

### 4.2 H4 (Gemini hallucination)
- summarizer 호출 전 body가 빈 문자열/오류 페이지 패턴이면 skip:
```python
if not body or _looks_like_error_page(body):
    log.warning("summarize.skip post_id=%d reason=empty_or_error_body", post.id)
    continue
```
- Gemini 응답의 `deadline` 형식을 strict하게 validate (이미 `date.fromisoformat`으로 일부 처리 중) + 본문에 그 날짜 문자열이 실제 등장하는지 grep으로 한 번 더 확인.

### 4.3 H3 (parser 버그) — 진단 후 필요시
- parser.py에 list page row의 제목 ↔ href ↔ ID 일관성 단위 테스트 추가.
- 실제 list page HTML을 `tests/fixtures/`에 snapshot으로 저장 + 회귀 테스트.

### 4.4 회귀 방지 — 발행 전 자동 검증
- `pre-publish hook` 추가: `write_events_json` 직전에 ≥ N% (예: 80%) 이벤트의 URL이 reachable이고 제목 일치인지 확인. 미달이면 publish 중단 + alert.
- Smoke test 추가: `tests/test_data_integrity.py` — 가짜 deadline + 가짜 fetch_article_content를 stub해서 sanity check 동작 검증.

---

## 5. 즉시 조치 (긴급, 코드 fix 이전)

1. **잘못된 events.json 정정**:
   - 검증된 3건(1441379, 1388562, 1441380)만 남기고 9건 제거.
   - 또는 전체 events.json을 빈 배열 `[]`로 초기화 (운영자가 다음 cycle을 신뢰할 때까지).
2. **다음 18:00 KST 자동 발사 일시 중단**:
   - 집 맥북에서 `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.user.cse-bot.plist`.
   - fix 후 재등록.
3. **GitHub link fix** (별개 사소 이슈): `docs/calendar/index.html`의 `↗ GitHub` 링크가 `cseDiscordBot`(존재 안 함)이라 404. `cse-notice-bot`로 수정. — *이미 본 패치 작업 중 수정 완료.*

---

## 6. 구현 범위 (v1.3.0)

| ID | 항목 | 우선순위 | 변경 파일 |
|---|---|---|---|
| INT-1 | 발행 전 sanity check (URL/제목 재검증) | Critical | `src/cse_bot/main.py`, `src/cse_bot/article.py` |
| INT-2 | drift 알림 (`_safe_alert` 호출) | Critical | `src/cse_bot/main.py` |
| INT-3 | BoardState에서 stale deadline 제거 | High | `src/cse_bot/main.py`, `src/cse_bot/state.py` |
| INT-4 | 빈/오류 본문 skip | Medium | `src/cse_bot/main.py` |
| INT-5 | parser list page snapshot 테스트 | High | `tests/test_parser_list_integrity.py` (신규) |
| INT-6 | sanity check 단위 테스트 (stub fetch) | High | `tests/test_data_integrity.py` (신규) |
| INT-7 | 즉시 events.json 정정 + state.json 클린업 도구 | Critical | `scripts/clean_state.py` (신규) |
| INT-8 | launchd 일시정지 절차 README 기재 | Low | `README.md` |

### 6.1 INT-1 ~ INT-3 의사 코드

```python
# main.py _emit_daily_digest 안

deadlines = _collect_all_deadlines(state_map, today=today)

# v1.3 NEW: publish 전 검증
validated, dropped_ids = _validate_deadlines(
    deadlines,
    timeout=cfg.general.http_timeout_seconds,
    retries=cfg.general.http_retries,
)

if dropped_ids:
    # BoardState에서도 제거 (다음 cycle에 같은 드리프트 다시 안 보내도록)
    for board_state in state_map.values():
        board_state.deadlines = [
            d for d in board_state.deadlines if d.post_id not in dropped_ids
        ]
    state.save_state(state_path, state_map)
    _safe_alert(
        cfg,
        f"calendar drift: {len(dropped_ids)} deadlines removed "
        f"(ids={sorted(dropped_ids)})",
    )

render_calendar_png(validated, today, png_path, …)
write_events_json(validated, events_path)
```

### 6.2 수용 기준
- [ ] 발행 직전 모든 deadline의 URL fetch 성공 + 제목 ratio > 0.5 통과한 것만 events.json 포함.
- [ ] 통과하지 못한 deadline은 BoardState에서도 제거되어 다음 cycle 재집계 안 됨.
- [ ] drift가 1건이라도 발생 시 `DISCORD_WEBHOOK_ALERT` 채널로 알림.
- [ ] `tests/test_data_integrity.py`: stub fetch가 (a) 모두 정상, (b) 일부 drift, (c) 전부 unreachable 3가지 시나리오에서 올바른 결과.
- [ ] 기존 회귀 0건 (`pytest -q` 전부 통과).

---

## 7. 비범위 (Out of Scope)
- 사이트 측 ID 재할당 정책 자체를 막을 방법 (사이트 운영 영역).
- Gemini 모델 변경/튜닝.
- 캘린더 UI/UX 변경 (v1.2.0에서 처리됨).

---

## 8. 일정 가이드
| Day | 작업 |
|---|---|
| D0 (오늘) | 본 스펙 확정, 즉시 조치(잘못된 events.json 정정 + launchd 정지) |
| D1 오전 | H1·H2 검증 (list page fetch + state.json 분석) |
| D1 오후 | INT-1, INT-2, INT-3 구현 + 단위 테스트 |
| D2 오전 | INT-5, INT-6, INT-7, INT-8 |
| D2 오후 | 통합 테스트 + 데이터 정정 + launchd 재등록 + 다음 cycle 모니터링 |

---

## 9. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| sanity check fetch가 게시판에 부하 | 사이트 측 차단 위험 | cycle 당 N개 deadline 기준 fetch 간격 sleep(0.5s) + retry 제한 |
| 제목 ratio threshold 잘못 잡으면 정상 글도 drop | 좋은 데이터 손실 | 초기 threshold 0.5, drift 알림으로 운영자가 false positive 확인 |
| 사이트가 일시적 점검 중이면 모든 deadline drop | 빈 events.json publish | 전체의 50% 이상 unreachable이면 publish 자체를 abort + alert |
| state.json에서 deadline 제거 후 다음 cycle에 다시 추가 | 무한 루프 | dropped_ids를 30일간 "blacklist"로 기록, watermark와 별도 |

---

## 10. 후속 개선 (v1.4+ 후보)
- 게시글 *수정* 추적: `last_modified` 헤더나 본문 hash로 변경 감지 → Gemini 재요약.
- 캘린더에 "최종 검증" timestamp 표시 (각 칩 hover/tap 시).
- 단위 테스트 커버리지 보고.

---

## 11. 추가 발견 — Baseline 정책 결함 (2026-05-26 23:00 KST)

새 코드 배포 후 봇이 정상 동작했지만, `events.json`이 **4건만 publish**하는 상황이 관찰됨. 게시판 list page에는 마감일이 명시된 글이 다수 존재함에도 봇 state.json에는 없음.

### 11.1 누락된 마감 글들 (관찰)
| artclNo | 제목 | 본문 명시 마감 | list page | state.json |
|---|---|---|---|---|
| 1441440 | AI Booster 2기 (기간 연장) | 2026-05-31 | ✓ | ✗ |
| 1441380 | 주거안정장학금 | 2026-06-22 | ✓ | ✗ |
| 1441312 | 계절수업 폐강 + 수강정정 | 미상 | ✓ | ✗ |
| 1441111 | 국가장학금 1차 | 2026-06-22 | ✓ | ✗ |
| 1440913 | 오픈소스SW특강 | 미상 | ✓ | ✗ |
| 1388562 | 졸업요건 서류 | 2026-07-10 | ✓ | ✗ |

state.json의 4건은 baseline 이후 게시되어 옛 코드가 본 글들. 위 6건은 baseline 이전이거나 옛 코드가 deadline 추출에 실패한 글.

### 11.2 근본 원인 — Watermark 첫 가동 정책

`src/cse_bot/main.py:158-163`:
```python
if board_state.last_max_post_id is None:
    board_state.last_max_post_id = page_max_id   # 첫 가동 = 현재 최신 ID로 baseline
    board_state.last_checked = _now_iso()
    state_map[board.id] = board_state
    log.info("baseline.recorded board=%s watermark=%d", board.id, page_max_id)
    return [], {}                                 # 신규 글 0개로 처리
```

봇이 처음 가동될 때 baseline = 현재 page의 최신 ID로 설정되고, 그 이후 새 글만 신규로 잡힘. 결과적으로 **첫 가동 시점에 이미 게시판에 있던 글들의 마감은 봇이 영원히 추적하지 못함**.

이건 단순한 버그가 아니라 **명시적 설계 결정**이지만, 실제 운영에서 큰 단점이 드러난 상황:
- 학사 일정상 *현재 진행 중인 마감*이 캘린더에서 누락
- 사용자(학생)가 그 마감을 놓칠 위험
- list page에는 분명히 보이는 글이 캘린더엔 없음 → 신뢰도 저하

### 11.3 해결 방안

**즉시 해결 — One-off backfill (선택 시점에 사용자가 실행)**
- `scripts/backfill_deadlines.py` 신규: state.json의 `last_max_post_id`를 임의의 더 낮은 값으로 떨어뜨림 → 다음 cycle에 그 사이 글들을 모두 새로 fetch + Gemini로 deadline 추출.
- 1회성 운영자 액션. 비용은 Gemini Flash Lite 30~50회 호출 (= 약 $0.01).
- 부작용: 그 사이 글 모두에 대해 article body fetch 발생 → 게시판 측 부하 (50회 * 1초 sleep = 약 1분).

**근본 해결 — INT-9 (v1.3.0 추가)**
첫 가동(baseline=None) 시 즉시 baseline만 기록하고 끝내는 게 아니라:
1. list page 1-2 페이지 *모두* fetch + summarize
2. deadline이 추출된 글만 TrackedDeadline로 추가
3. watermark는 page_max_id로 설정 (현재 그대로)
4. 다음 cycle부터는 기존 동작 (신규 글만)

또는 더 보수적:
- 첫 가동 시 사용자 의도를 묻는 dry-run mode (`--bootstrap`) 도입
- 사용자가 backfill을 원할 때만 그 모드로 1회 실행

### 11.4 INT-9 / INT-10 (v1.3.0 추가 작업)

| ID | 항목 | 우선순위 | 변경 파일 |
|---|---|---|---|
| INT-9 | 첫 가동 시 baseline backfill 옵션 | High | `src/cse_bot/main.py`, `src/cse_bot/config.py` |
| INT-10 | `scripts/backfill_deadlines.py` 운영자 도구 | High | `scripts/backfill_deadlines.py` (신규) |

#### INT-9 의사 코드
```python
# config.toml에 새 옵션
[calendar]
bootstrap_backfill = true   # 기본값 false (회귀 방지). true면 첫 가동 시 모든 보드 글 처리

# main.py _process_board
if board_state.last_max_post_id is None:
    if cfg.calendar.bootstrap_backfill:
        # 모든 page의 글을 신규 글로 취급해 처리
        new_posts = posts  # baseline 안 잡고 전체 처리
    else:
        board_state.last_max_post_id = page_max_id
        return [], {}
```

#### INT-10 — backfill 스크립트
일회용 운영 도구. state.json의 watermark를 사용자가 지정한 floor로 낮춤. 그 후 사용자가 launchd kickstart로 봇 실행하면 자동으로 fetch + summarize 됨. (별도 commit 무관, state.json은 git-ignored)

```bash
python3 scripts/backfill_deadlines.py 1388000   # floor 인자
# state.json의 last_max_post_id가 1388000으로 떨어짐
launchctl kickstart -k gui/$(id -u)/com.user.cse-bot
# 봇이 1388000 이상의 모든 글을 새 코드로 처리
```

### 11.5 즉시 조치 결정 — 2026-05-26 결정
- 사용자가 **C(자연 만료)** 선택했지만, baseline 결함으로 *현재 진행 중인 마감 6건*이 누락된 것이 별개로 확인됨
- 사용자 결정: **옵션 X (one-off backfill) 진행** — `scripts/backfill_deadlines.py` 작성 후 집 맥북에서 1회 실행
- 결과 확인 후 INT-9 (recurring fix)는 v1.3.0 본 작업에서 처리

---

## 12. 학습 사항 (post-mortem 요약)

1. **events.json과 state.json은 분리 관리** — 봇이 매 cycle 끝에 state로 events.json을 *덮어쓰는* 단방향이지만, 옛 events.json이 git에 남아 있으면 새 봇이 도착하기 전까지 그대로 노출됨.
2. **봇 production binary가 옛 코드일 수 있음** — 푸시 ≠ 배포. 집 맥북에 git pull이 필요. `install.sh`로 자동화하면 한 줄로 끝.
3. **watermark baseline은 큰 의사결정** — "첫 가동 시 모든 글을 backfill"이 직관적 기대인데, 실제 코드는 정반대로 동작. 사용자(운영자) 학습 비용 발생.
4. **Discord 알림과 캘린더 데이터가 분리된 정보 흐름** — Discord에 "0건" 다이제스트가 가도 캘린더는 stale data로 노출되는 모순. publish-time validation 필요.
5. **Public repo의 GitHub Pages는 즉시 외부 노출** — 데이터 정확성을 publish 직전에 검증해야 한다는 압박이 더 크다.
