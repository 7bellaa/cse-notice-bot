# PNU CSE Discord Notification Bot

부산대학교 정보컴퓨터공학부 학부 공지사항(`https://cse.pusan.ac.kr/cse/14221/subview.do`)을 매일 09:00, 18:00 KST에 점검하여 신규 게시글을 Discord webhook으로 알림합니다.

## Requirements
- macOS
- Python 3.11+
- Discord 서버 + 채널별 webhook URL
- Gemini API key (AI 요약용)
- (옵션) Gemini CLI — 개발 시 task 자동 리뷰용

## Setup

```bash
git clone <this repo> ~/cseDiscordBot
cd ~/cseDiscordBot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# .env 편집: DISCORD_WEBHOOK_GENERAL, DISCORD_WEBHOOK_ALERT, GEMINI_API_KEY 채우기

# 베이스라인 실행 (알림 없이 현재 상태만 저장)
set -a; source .env; set +a
python -m cse_bot.main --config config/config.toml
```

### Gemini API key (for AI summary)

1. Go to https://aistudio.google.com/ → "Get API key"
2. Add to `.env`:
   ```
   GEMINI_API_KEY=<your-key>
   ```
3. Free tier (Gemini 2.5 Flash-Lite, ~1,000 requests/day) is sufficient for this bot.

## launchd 등록

```bash
cp deploy/com.user.cse-bot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.cse-bot.plist
launchctl list | grep cse-bot
```

즉시 1회 실행으로 동작 확인:
```bash
launchctl start com.user.cse-bot
tail -f logs/cse_bot.log
```

## 설정 변경

`config/config.toml`에서:
- `notification.format` — `minimal` / `medium` / `detailed`
- `[[boards]]` 섹션 추가로 게시판 확장 가능 (각 게시판의 `webhook_envs` 는 환경변수 이름 목록 — 여러 채널 fan-out 지원)
- `[gemini]` 섹션: `api_key_env` (환경변수 이름), `model` (기본 `gemini-2.5-flash-lite`), `timeout_seconds`

## 운영 메모
- macOS가 절전/꺼짐일 때 launchd 트리거를 놓칠 수 있음 → 09:00, 18:00에는 깨어 있어야 함
- 로그: `logs/cse_bot.log` (회전 5MB×5)
- 상태: `data/state.json` (워터마크). 손상 시 자동 백업 + 베이스라인 재시작
- 사이트 구조 변경으로 파싱이 3회 연속 빈 결과면 `DISCORD_WEBHOOK_ALERT` 채널로 알림

## Development

```bash
pytest --cov=cse_bot          # 테스트 + 커버리지
ruff check src/ tests/         # 린트
mypy src/                      # 타입 체크
```

각 task 완료 시:
```bash
bash scripts/gemini_review.sh "docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md#task-N"
```
PASS 받으면 다음 task로 진행. 10회 실패 시 사용자에게 보고 후 일시 중지.

## 문서
- 디자인 스펙: `docs/superpowers/specs/2026-04-30-pnu-cse-discord-bot-design.md`
- 데이터 플로우 다이어그램: `docs/data-flow.md`
- 구현 계획: `docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md`

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.user.cse-bot.plist
rm ~/Library/LaunchAgents/com.user.cse-bot.plist
```
