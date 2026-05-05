# 배포 머신 업그레이드 절차 — Multi-webhook + Gemini 요약

- **대상:** 봇이 실제로 돌고 있는 맥북 (launchd로 09:00 / 18:00 실행)
- **변경 요약:**
  - `webhook_env` (단일) → `webhook_envs` (리스트)로 스키마 변경 → 한 게시판을 N개 Discord 웹훅에 fan-out 가능
  - 새 `[gemini]` config 섹션 + `GEMINI_API_KEY` 환경변수 필수 → 본문 5줄 이내 한국어 요약을 알림에 포함
  - 본문 fetch + 요약 실패 시 기존 포맷으로 fallback (알림은 끊기지 않음)
- **breaking change:** `config.toml`의 `webhook_env` 줄과 `.env`의 `GEMINI_API_KEY` 누락 시 startup에서 `ConfigError`로 즉시 죽음

---

## 사전 점검 (1분)

```bash
# 봇 디렉토리로 이동 (실제 경로 확인 — plist의 WorkingDirectory와 일치해야 함)
cd /Users/<USER>/cseDiscordBot
pwd
# 현재 launchd 등록 상태
launchctl list | grep com.user.cse-bot
```

`launchctl list`에 항목이 보여야 함. 안 보이면 plist가 로드 안 된 상태 — 마지막 단계에서 다시 로드.

---

## Step 1. Gemini API 키 발급

브라우저에서:

1. https://aistudio.google.com/ 접속 (Google 계정 로그인)
2. **"Get API key"** 클릭
3. **"Create API key in new project"** (또는 기존 프로젝트 선택)
4. 생성된 키 복사 (`AIza...` 형태)

**비용:** Google AI Pro 구독과 무관한 별도 종량제. 무료 티어 (Gemini 2.5 Flash-Lite, 약 1,000 RPD)로 봇 사용량은 충분히 커버됨. 카드 등록 불필요.

---

## Step 2. 코드 업데이트 (git pull)

```bash
cd /Users/<USER>/cseDiscordBot
git status                    # 로컬 변경사항 없는지 확인
git pull origin main          # 9개 신규 커밋 ('feat(article)..feat(main)' 등)
git log --oneline -10         # 최신 커밋이 'feat(main): per-post article fetch...' 인지 확인
```

기대 결과 (마지막 commit):
```
231cc3e feat(main): per-post article fetch + Gemini summary + webhook fan-out
```

로컬 수정 충돌 시: `git stash` → `git pull` → `git stash pop` 후 충돌 해소.

---

## Step 3. `.env`에 Gemini 키 추가

```bash
# 현재 .env 백업
cp .env .env.bak.$(date +%Y%m%d)

# Gemini 키 줄 추가 (이미 있으면 건너뜀)
grep -q '^GEMINI_API_KEY=' .env || echo 'GEMINI_API_KEY=AIza...붙여넣기' >> .env

# 확인
grep '^GEMINI_API_KEY=' .env
```

> ⚠️ `.env`는 `.gitignore`에 들어 있어야 함. 절대 커밋 금지.

---

## Step 4. (선택) Fan-out용 추가 웹훅 등록

같은 게시판의 새 글을 **여러 Discord 채널/서버**로 동시 전송하고 싶을 때만 진행. 기존 1개 채널만 쓰려면 **Step 5로 점프**.

1. Discord에서 추가 대상 채널 → 채널 설정 → 연동 → 웹훅 → 새 웹훅 → URL 복사
2. `.env`에 추가:

```bash
echo 'DISCORD_WEBHOOK_FRIENDS=https://discord.com/api/webhooks/...' >> .env
echo 'DISCORD_WEBHOOK_GROUPCHAT=https://discord.com/api/webhooks/...' >> .env
```

3. `config/config.toml`의 보드 섹션을 편집:

```toml
[[boards]]
id = "14221"
name = "정컴 일반공지"
url = "https://cse.pusan.ac.kr/cse/14221/subview.do"
webhook_envs = [
  "DISCORD_WEBHOOK_GENERAL",
  "DISCORD_WEBHOOK_FRIENDS",
  "DISCORD_WEBHOOK_GROUPCHAT",
]
enabled = true
```

> 주의: 이 단계 빼먹어도 안전 — `config.toml`은 이미 `webhook_envs = ["DISCORD_WEBHOOK_GENERAL"]`로 git에 들어 있어 단일 채널로 그대로 동작.

---

## Step 5. 테스트 스위트 통과 확인

```bash
.venv/bin/pytest -q
```

기대: `71 passed`. 1개라도 실패하면 멈추고 원인 확인 (의존성 미설치 등).

```bash
.venv/bin/ruff check .
```

기대: 출력 없음 (clean).

---

## Step 6. 수동 스모크 테스트 (1 사이클 직접 실행)

> 이 단계는 **실제 Discord 채널에 알림을 보내고** Gemini API를 호출함. 테스트 채널을 쓰거나, 새 글이 없으면 그냥 종료됨.

```bash
# state 백업 (이전 워터마크 보존)
cp data/state.json data/state.json.bak

# 한 사이클 실행
set -a; source .env; set +a
.venv/bin/python -m cse_bot.main --config config/config.toml
echo "exit code: $?"
```

기대 동작:
- 새 글이 있으면 Discord 채널에 `📢 새 공지: ...` + `📝 요약:` 블록(불릿 5줄)으로 알림 도착
- 새 글이 없으면 조용히 exit 0
- `logs/cse_bot.log`에 `notify.ok board=14221 post_id=... webhooks_ok=N webhooks_failed=0 summary=yes` 라인 기록

알림이 안 왔다면 (그리고 실제로 새 글이 있다면):
```bash
tail -50 logs/cse_bot.log
```
에러 라인 (`summarize.http_error`, `notify.failed` 등) 확인.

문제 없으면 state 복원은 자동으로 진행되었으므로 `data/state.json.bak`은 그대로 두거나 삭제.

---

## Step 7. launchd 재로드 (코드만 바뀐 경우 보통 불필요)

`.plist` 자체를 수정한 게 아니면 **재로드 불필요** — launchd는 매 트리거마다 새 프로세스를 spawn하면서 최신 코드/`.env`를 읽음. 다음 09:00 또는 18:00에 자동으로 새 코드가 돈다.

`.plist`를 수정한 경우에만:

```bash
launchctl unload ~/Library/LaunchAgents/com.user.cse-bot.plist
cp deploy/com.user.cse-bot.plist ~/Library/LaunchAgents/com.user.cse-bot.plist
launchctl load ~/Library/LaunchAgents/com.user.cse-bot.plist
launchctl list | grep com.user.cse-bot
```

---

## Step 8. 다음 트리거 시점에 로그 확인

다음 09:00 또는 18:00 (KST) 직후:

```bash
tail -30 logs/cse_bot.log
tail -10 logs/launchd.stdout.log
tail -10 logs/launchd.stderr.log
```

확인 포인트:
- `cycle.start` → `cycle.end ok=True`
- 새 글이 있었다면 `summary=yes`와 `webhooks_ok=N`
- stderr.log가 비어 있거나 깨끗

---

## 롤백 (문제 발생 시)

```bash
cd /Users/<USER>/cseDiscordBot
git log --oneline -10                    # 이전 안정 커밋 확인 (예: 7b7a6a8)
git checkout 7b7a6a8 -- config/config.toml src/cse_bot
# 또는 git revert로 새 커밋 만들기
git revert 231cc3e d6e4766 2d93286 99fd7a5 9e143b2 29c3ce2
```

이전 `webhook_env` (단수) 스키마로 돌아가면 `.env`의 `GEMINI_API_KEY`는 무시됨 — 그대로 둬도 OK.

---

## 자주 묻는 문제

| 증상 | 원인 / 해결 |
|---|---|
| `ConfigError: environment variable GEMINI_API_KEY is required (gemini)` | Step 3 누락 — `.env`에 키 추가 |
| `ConfigError: [[boards]] index 0: missing key webhook_envs` | `config.toml`이 옛 `webhook_env` (단수) 그대로임 — `webhook_envs = [...]` 리스트로 변경 |
| 알림은 오는데 `📝 요약:` 블록이 없음 | 정상 fallback. 본문이 짧거나 Gemini 한도/오류 시 발생. `logs/cse_bot.log`에서 `summary=no` 라인 확인 |
| `429` 또는 `RESOURCE_EXHAUSTED` (Gemini) | 무료 일일 한도(1,000 RPD) 초과 — 거의 안 일어남. 발생 시 다음 날 PT 자정(KST 16~17시) 리셋까지 요약은 fallback |
| 같은 글이 두 번 알림 옴 | state.json 손상. `git log --oneline data/state.json` 확인 후 직전 정상 버전으로 복원 |
