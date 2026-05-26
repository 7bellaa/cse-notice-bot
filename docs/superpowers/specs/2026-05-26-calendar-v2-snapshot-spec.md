# PNU CSE 마감 캘린더 — v2.0.0 Snapshot 아키텍처 스펙

- **문서 버전**: v0.1 (draft)
- **작성일**: 2026-05-26
- **대상 릴리스**: v2.0.0 (Snapshot-first Calendar)
- **선행 릴리스**: v1.3.0 (data integrity patch)
- **예상 소요**: 2 ~ 3 영업일 (Backend 1명) + 0.5일 QA

---

## 0. Context — 왜 v2.0.0이 필요한가

봇은 원래 "신규 공지 푸시 알림"만 제공했고, 그 모델에 맞춰 `state.json`에 watermark 기반 incremental 누적 구조를 사용해 왔다. v1.0.0에서 캘린더 기능을 더했지만 **동일한 incremental state를 캘린더 데이터 소스로 재사용**한 결과, 세 가지 구조적 문제가 발생했다:

1. **Baseline 이전 글 영구 누락**: 봇 첫 가동 시점에 이미 게시된 마감(졸업요건·국가장학금 등)은 watermark 정책상 평생 잡히지 않음
2. **Stale 누적**: 한 번 state에 들어간 마감은 만료까지 그대로 남음. 게시글이 수정·삭제되어도 events.json은 옛 정보를 publish
3. **ID 재할당·이동에 무방비**: 같은 글이 새 artclNo로 재게시되면 *둘 다*가 캘린더에 (잘못된 형태로) 노출

근본 원인 진단(`2026-05-26-calendar-data-integrity-spec.md` §11)에서 결론:
**캘린더는 "현재 게시판 상태(snapshot)"를 요구하는데 봇은 "incremental push"만 제공한다 — 두 모델의 불일치**.

v2.0.0은 캘린더의 데이터 흐름을 **snapshot 모델**로 전면 재설계한다. notifier(푸시 알림)는 기존 incremental 흐름을 그대로 유지하고, 캘린더는 별도 모듈로 분리한다.

---

## 1. 새 아키텍처 — Snapshot + Content Cache + Manual Override

### 1.1 단일 도식

```
┌──────────────────────────────────────────────────────────────────┐
│ cse.pusan.ac.kr/cse/14221/subview.do  (list page, truth-of-source) │
└──────────────────────────────────────────────────────────────────┘
              │ 매 cycle에 1-2 페이지 fetch
              │
              ├─→ [notifier]    incremental watermark 기반 새 글 알림 (기존)
              │                 → Discord 채널에 push
              │
              └─→ [calendar_publisher]   ← v2.0.0 신규 모듈
                         │
                         │ list의 각 글에 대해:
                         ↓
                  ┌─────────────────────────────────┐
                  │ post_cache (data/post_cache.json)│
                  │  {                              │
                  │    artclNo: {                   │
                  │      title,                     │
                  │      url,                       │
                  │      content_hash,              │
                  │      deadline,                  │
                  │      category,                  │
                  │      summary,                   │
                  │      important,                 │
                  │      last_seen,                 │
                  │      last_summarized            │
                  │    }                            │
                  │  }                              │
                  └─────────────────────────────────┘
                         │
                         │ ┌── cache hit + hash 동일 → LLM 호출 SKIP
                         │ │
                         │ ├── cache miss OR hash 변경 → 본문 fetch + Gemini summarize
                         │ │                          → cache 갱신
                         │ │
                         │ └── 모든 cache entry의 last_seen 갱신
                         ↓
                  ┌─────────────────────────────────┐
                  │ manual_deadlines.json (override) │
                  │  운영자가 디스코드에서 추가/수정  │
                  └─────────────────────────────────┘
                         │
                         │ merge: cache ∪ manual
                         │ filter: 미래 마감 + last_seen 30일 이내
                         ↓
                  render_calendar_png + write_events_json
                         │
                         ↓
                  git_publish → GitHub Pages
```

### 1.2 핵심 원칙

1. **list page가 truth-of-source**: 거기 있으면 캘린더에 있어야 하고, 없으면 캘린더에 없어야 한다.
2. **content_hash로 LLM 호출 최소화**: 같은 내용이면 다시 요약하지 않는다.
3. **last_seen TTL로 drift 방지**: 글이 list에서 사라진 지 N일 지나면 cache에서도 제거.
4. **Notifier와 Calendar는 같은 list fetch를 공유하지만 의존하지 않는다**: 한쪽이 실패해도 다른 쪽은 계속 동작.
5. **운영자가 수동으로 override 가능**: 자동 추출이 부정확한 케이스를 손으로 채운다.

---

## 2. 데이터 모델

### 2.1 PostCache (`data/post_cache.json`)
```jsonc
{
  "schema_version": 1,
  "updated_at": "2026-05-26T23:00:00+09:00",
  "boards": {
    "14221": {
      "posts": {
        "1441380": {
          "title": "[장학] 2026.2학기 주거안정장학금 신청 안내",
          "url": "https://cse.pusan.ac.kr/bbs/cse/2055/1441380/artclView.do",
          "content_hash": "sha256:abc...",
          "summarized_at": "2026-05-26T23:00:00+09:00",
          "deadline": "2026-06-22",
          "category": "장학/등록",
          "summary": "학과 거주 학생 대상 주거안정장학금 신청.",
          "important": true,
          "last_seen": "2026-05-26T23:00:00+09:00"
        }
        // ...
      }
    }
  }
}
```

**필드 설명**:
- `content_hash`: `sha256(body)`. body가 바뀌면 hash가 바뀌어 재요약 트리거
- `summarized_at`: 마지막 Gemini 호출 시각. 디버깅·비용 추적용
- `deadline`: null이면 마감일 없는 글로 캐시 (그래도 cache에는 남아 있음 — 매 cycle에 재요약 안 하기 위해)
- `last_seen`: 마지막으로 list page에서 본 시각. TTL 기준
- `important`: `is_important(title)` 결과

### 2.2 Manual Override (`data/manual_deadlines.json`)
```jsonc
{
  "schema_version": 1,
  "overrides": [
    {
      "id": "manual-1",                   // 자동 생성 또는 운영자 지정
      "title": "수강신청 (1·2학년)",
      "url": "https://cse.pusan.ac.kr/...",
      "date": "2026-08-19",
      "category": "학업/수강",
      "important": true,
      "added_at": "2026-05-26T23:00:00+09:00",
      "added_by": "operator",
      "expires_at": null                  // null = manual prune까지
    }
  ]
}
```

manual override는 cache와 *별도로 merge*되며 같은 URL이 있으면 manual이 우선.

### 2.3 State.json (기존 유지, notifier 전용)
- `last_max_post_id` (watermark)는 notifier만 사용
- `deadlines` 배열은 **deprecated** (v2.0.0에서 PostCache로 마이그레이션)

---

## 3. 새 흐름 — calendar_publisher

### 3.1 의사 코드
```python
# src/cse_bot/calendar_publisher.py (신규)

def run_calendar_publish(cfg, board, posts_in_list, *, today, project_root):
    """list page에서 가져온 posts를 캐시와 병합해 캘린더 publish."""
    cache = load_post_cache(project_root / "data" / "post_cache.json")
    overrides = load_manual_overrides(project_root / "data" / "manual_deadlines.json")
    now = _now_iso()

    seen_ids: set[int] = set()

    # 1) list에 있는 글들 처리
    for post in posts_in_list:
        seen_ids.add(post.id)
        cached = cache.get(board.id, {}).get(str(post.id))

        # 본문 fetch (cache hit 검증용)
        content = article.fetch_article_content(post.url, ...)
        if content is None:
            log.warning("calendar.fetch_failed post_id=%d", post.id)
            continue
        new_hash = _hash_content(content.body)

        if cached and cached["content_hash"] == new_hash:
            # 변경 없음 — last_seen만 갱신
            cached["last_seen"] = now
            continue

        # cache miss or content changed → Gemini 호출
        result = summarizer.summarize(content.body, image_urls=content.image_urls, ...)
        if result is None:
            # Gemini 실패 — 이전 캐시가 있으면 유지, 없으면 (제목만 cache에) 등록
            if cached is None:
                cache[board.id]["posts"][str(post.id)] = _stub_entry(post, new_hash, now)
            continue

        cache[board.id]["posts"][str(post.id)] = {
            "title": post.title,
            "url": post.url,
            "content_hash": new_hash,
            "summarized_at": now,
            "deadline": result.deadline,         # None이면 마감 없는 글
            "category": classify(post.title),
            "summary": result.short_summary,
            "important": is_important(post.title),
            "last_seen": now,
        }

    # 2) TTL prune — last_seen이 30일 이상된 항목 제거
    cutoff_ts = (now_kst() - timedelta(days=30)).isoformat()
    for pid in list(cache[board.id]["posts"].keys()):
        if cache[board.id]["posts"][pid]["last_seen"] < cutoff_ts:
            log.info("calendar.cache_evict post_id=%s reason=ttl", pid)
            del cache[board.id]["posts"][pid]

    save_post_cache(cache, ...)

    # 3) merge with manual overrides → events
    events = _build_event_list(cache, overrides, today=today)

    # 4) render + publish
    render_calendar_png(events, today, png_path, months=cfg.calendar.months_in_png)
    write_events_json(events, events_path)
    git_publish(...)
```

### 3.2 _build_event_list
```python
def _build_event_list(cache, overrides, *, today):
    events = []
    # cache의 미래 마감만
    for board in cache.values():
        for post_id, entry in board["posts"].items():
            dl = entry.get("deadline")
            if not dl:
                continue
            if dl < today.isoformat():
                continue  # 과거
            events.append(TrackedDeadline(post_id=int(post_id), ...))

    # manual overrides는 cache와 merge — 같은 URL이면 manual 우선
    cache_urls = {ev.url for ev in events}
    for ov in overrides:
        if ov.url in cache_urls:
            # 같은 URL — manual로 갱신
            for ev in events:
                if ev.url == ov.url:
                    ev.date = ov.date
                    ev.category = ov.category
                    ev.important = ov.important
                    break
        else:
            events.append(TrackedDeadline.from_override(ov))

    events.sort(key=lambda d: d.date)
    return events
```

### 3.3 main.py 통합
```python
# main.py _emit_daily_digest 안

# (1) notifier 흐름은 기존 그대로 — watermark 기반 새 글 처리
# (2) calendar_publisher는 별도 호출 — list page 전체 처리
posts_in_list = _fetch_list_page_full(board, cfg)  # 1-2 페이지 통합
calendar_publisher.run_calendar_publish(
    cfg, board, posts_in_list, today=today, project_root=project_root,
)
```

### 3.4 Notifier vs Calendar 의존성 분리
- `_process_board`(notifier)와 `run_calendar_publish`(calendar)는 *같은 list fetch 결과를 공유*하지만, 한쪽 실패가 다른 쪽을 중단시키지 않음
- Calendar가 실패해도 Notifier는 정상 발송 (역도 동일)
- 둘 다 `posts_in_list`를 받지만 cache/state는 완전 분리

---

## 4. 비용 분석 (Gemini Flash Lite)

### 4.1 정상 상태 (cache warm)
- list page에 평균 30개 글, 매 cycle 1회
- cache hit (content_hash 동일): LLM 호출 0회
- 신규 글 + 수정 글: 평균 2~5건 → Gemini 호출 2~5회/day
- 비용: ≈ $0.001/day (Flash Lite 가격 기준)

### 4.2 첫 마이그레이션
- post_cache 비어 있음 → 30개 모두 LLM 호출
- 1회성, ≈ $0.01

### 4.3 한도 초과 대응
- Gemini timeout/한도 초과 시:
  - 해당 글의 cache는 *기존 값 유지* (있다면)
  - 신규 글이면 stub entry만 (deadline=null) → 다음 cycle에 재시도
  - 모든 호출 실패해도 cache의 기존 데이터로 events.json publish

---

## 5. 운영자 인터페이스 (Manual Override)

### 5.1 디스코드 슬래시 커맨드 (v2.1+, 본 v2.0.0 비범위)
- `/cal add <url> <date>` — 마감 수동 추가
- `/cal remove <id>` — 제거
- `/cal list` — 현재 override 목록

### 5.2 v2.0.0 임시 인터페이스 — 파일 직접 편집
- `data/manual_deadlines.json`을 운영자가 직접 편집
- 봇이 매 cycle 시작 시 파일 reload
- 변경 사항은 다음 cycle부터 events.json에 반영

---

## 6. 마이그레이션 — v1.x → v2.0.0

### 6.1 데이터 마이그레이션 (1회성)
```python
# scripts/migrate_to_v2.py
"""state.json의 deadlines를 post_cache로 변환."""

state = load_state(...)
cache = {"schema_version": 1, "boards": {}}
for board_id, st in state["boards"].items():
    posts = {}
    for dl in st.get("deadlines", []):
        posts[str(dl["post_id"])] = {
            "title": dl["title"],
            "url": dl["url"],
            "content_hash": "",          # 빈 값 → 다음 cycle에서 새로 계산
            "summarized_at": dl.get("first_seen", ""),
            "deadline": dl["date"],
            "category": dl.get("category") or classify(dl["title"]),
            "summary": dl.get("summary", ""),
            "important": dl.get("important", is_important(dl["title"])),
            "last_seen": st["last_checked"],
        }
    cache["boards"][board_id] = {"posts": posts}

save_post_cache(cache, ...)

# state.json은 deadlines만 제거 (watermark 등은 그대로)
for board_id in state["boards"]:
    state["boards"][board_id].pop("deadlines", None)
save_state(state, ...)
```

### 6.2 코드 마이그레이션
- `state.deadlines`를 사용하는 모든 코드를 calendar_publisher로 이전
- notifier의 reminder 기능은 cache + manual overrides를 source로 변경
- v1 호환을 위해 1~2 cycle 동안 둘 다 유지하는 dual-write 옵션도 가능 (선택적)

### 6.3 회귀 방지
- 마이그레이션 직후 events.json snapshot 저장 → 다음 cycle 후 비교
- diff가 예상 이상이면 alert + rollback

---

## 7. 변경 범위

### 7.1 신규 파일
| 파일 | 책임 |
|---|---|
| `src/cse_bot/calendar_publisher.py` | snapshot+cache 흐름 |
| `src/cse_bot/post_cache.py` | PostCache load/save/hash |
| `src/cse_bot/manual_overrides.py` | Manual override 로드/merge |
| `scripts/migrate_to_v2.py` | 1회성 데이터 마이그레이션 |
| `tests/test_calendar_publisher.py` | 흐름 단위 테스트 |
| `tests/test_post_cache.py` | 캐시 hit/miss/TTL prune |
| `tests/test_manual_overrides.py` | merge 정책 |

### 7.2 수정 파일
| 파일 | 변경 |
|---|---|
| `src/cse_bot/main.py` | `_emit_daily_digest`에서 calendar_publisher 호출. notifier 흐름은 그대로 |
| `src/cse_bot/models.py` | `PostCacheEntry`, `ManualOverride` dataclass 추가. `TrackedDeadline.deadlines`는 deprecated 마킹 |
| `src/cse_bot/state.py` | deadlines 필드 제거 또는 deprecated (notifier 호환을 위해 watermark만) |
| `src/cse_bot/web_publisher.py` | `write_events_json`은 그대로, 입력만 변경 |
| `config/config.toml` | `[calendar] cache_path`, `cache_ttl_days` 등 추가 |

### 7.3 삭제 가능 (v1 잔존)
- `state.deadlines` 데이터 (마이그레이션 후)
- `scripts/backfill_deadlines.py` (v2에선 cache가 list snapshot 기반이라 불필요)

---

## 8. 수용 기준

- [ ] post_cache.json이 모든 cycle에서 list page에 있는 모든 글의 (id, hash, deadline, last_seen)을 반영
- [ ] 동일 cycle 재실행 시 LLM 호출 0회 (모든 content_hash 동일)
- [ ] 같은 글의 본문이 수정되면 다음 cycle에서 정확히 1회 재요약
- [ ] list에서 사라진 글의 cache entry는 30일 후 자동 prune
- [ ] manual_deadlines.json의 항목은 cache와 무관하게 events.json에 포함
- [ ] manual override와 cache가 같은 URL을 가지면 manual 우선
- [ ] Notifier 흐름 회귀 0건 (새 글 알림 정상)
- [ ] 마이그레이션 후 events.json이 v1 직전 cycle 결과의 *상위 집합* (이전 마감 모두 포함 + 추가 글)
- [ ] Gemini 호출이 일일 평균 < 10회 (warm cache 기준)
- [ ] 모든 단위 테스트 + 기존 회귀 통과

---

## 9. 일정 가이드

| Day | 작업 |
|---|---|
| **D1 오전** | post_cache.py + 단위 테스트 (load/save/hash) |
| **D1 오후** | calendar_publisher.py 흐름 작성 + 단위 테스트 |
| **D2 오전** | manual_overrides.py + merge 로직 + 테스트 |
| **D2 오후** | main.py 통합 + 통합 테스트. notifier 회귀 확인 |
| **D3 오전** | migrate_to_v2.py + 마이그레이션 검증 (집 맥북에서 실행) |
| **D3 오후** | 1회 cycle 실행 모니터링, events.json 비교, CHANGELOG + 릴리스 |

---

## 10. 리스크 & 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| list page 파싱이 변경되면 cache 전체가 stale로 평가됨 → 모든 글 재요약 → API 한도 초과 | 일시적 비용 spike | parser 변경 감지 후 알림. content_hash 계산 안정성 (whitespace normalize, HTML 태그 strip) 점검 |
| Gemini 응답에 ISO datetime / 시작일 오추출 | 잘못된 마감일 cache에 진입 | summarizer prompt 강화 + 응답 validation (regex 형식 체크) + manual override로 즉시 정정 |
| list page 1-2 페이지로는 부족한 보드 (수백 개 마감) | 누락 | `max_pages` 늘리기 + page traverse 정책 (마감 추출 끝나면 stop) |
| cache 파일 손상 (JSON 파싱 실패) | 캘린더 publish 중단 | atomic write + corruption 감지 시 빈 cache로 fallback + alert |
| 마이그레이션 후 캘린더에 *너무 많은* 잘못된 마감 (1441312=2026-05-22 같은 오추출) | 사용자 신뢰 ↓ | 마이그레이션 직후 dry-run 모드로 events.json diff 검토 → 운영자 승인 후 publish |
| Discord 다이제스트가 매번 다른 PNG로 발송됨 (수정 감지로 인해) | 노이즈 | digest 발송 정책: events.json hash 변경 시에만 발송. unchanged면 skip |
| manual_deadlines.json 운영자 실수 (잘못된 JSON) | publish 실패 | 파일 schema validate + 실패 시 manual 무시하고 cache만 사용 + alert |
| Notifier가 cache 모르고 동일 글에 대해 매 cycle 알림 발송 | 사용자 푸시 폭주 | notifier는 watermark만 의존 (cache에 의존 X) — 기존 동작 그대로 |

---

## 11. 비범위 (v2.0.0에서 다루지 않음)

- 디스코드 슬래시 커맨드 (`/cal add`) — v2.1+
- 캘린더 검색/필터 UI — 향후 별도
- 다중 게시판 통합 (현재 board 14221 단일)
- 게시판 외부 데이터 소스 (학사 일정 RSS 등)
- 사용자 개인화 (즐겨찾기·구독)
- AI 일관성 평가 (같은 글을 여러 번 요약했을 때 일관된 결과인지)

---

## 12. 후속 (v2.1+)

- **DATA-7**: Discord 슬래시 커맨드로 운영자 인터페이스 강화
- **DATA-8**: cache 변경 history 기록 (audit log) — 어떤 글의 deadline이 언제 어떻게 바뀌었는지
- **DATA-9**: 자동 anomaly detection — 같은 글의 deadline이 갑자기 멀리 점프하면 alert
- **DATA-10**: Multi-board snapshot (졸업/장학 등 여러 게시판 통합)
- **DATA-11**: 캘린더 페이지에 "마지막 갱신: YYYY-MM-DD HH:MM" 표시

---

## 13. 학습 (v1 post-mortem과 연결)

v1.x의 모든 데이터 무결성 문제는 결국 **데이터 모델 선택의 문제**였다. push 모델로 시작한 봇에 snapshot 요구가 추가되면서 부조화가 누적되어 결국 9/12 데이터 오류로 표면화. v2.0.0은 처음부터 *캘린더 ≠ 푸시 알림*임을 인정하고 별도 모듈로 분리한다.

**원칙**:
- 데이터 모델은 사용처에 맞춰 선택할 것
- 한 모듈이 두 패러다임을 섬기면 양쪽에서 결국 깨진다
- snapshot은 cache로, push는 watermark로 — 섞지 말 것
