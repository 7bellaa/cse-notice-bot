#!/usr/bin/env bash
# Install / refresh the cse-bot launchd agent on macOS.
#
# Idempotent: safe to re-run after every `git pull`. Auto-detects the repo
# path and current user so the same script works across machines without
# hard-coding /Users/7bellaa.
#
# Usage:
#   bash deploy/install.sh           # full install + immediate one-shot run
#   bash deploy/install.sh --no-run  # install only, wait for the 18:00 KST schedule

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LABEL="com.user.cse-bot"
PLIST_SRC="$ROOT/deploy/${LABEL}.plist"
PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PLIST_TMP="$(mktemp -t cse-bot-plist).plist"
UID_NUM="$(id -u)"
SERVICE_TARGET="gui/${UID_NUM}/${LABEL}"

KICKSTART=1
for arg in "$@"; do
    case "$arg" in
        --no-run) KICKSTART=0 ;;
        -h|--help)
            grep -E '^# ' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
    esac
done

echo "▸ root       = $ROOT"
echo "▸ user       = $(whoami) (uid=$UID_NUM)"
echo "▸ plist dst  = $PLIST_DST"

# ─── 1. .env sanity check ────────────────────────────────────────────────
if [ ! -f "$ROOT/.env" ]; then
    cat <<EOF >&2
✗ $ROOT/.env not found.
  cse-bot loads webhooks + API keys from this file at startup. Copy
  .env.example to .env and fill in the actual values before installing:

      cp .env.example .env
      \$EDITOR .env

EOF
    exit 1
fi

# ─── 2. Dependency sync via uv ───────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
    echo "✗ uv is not on PATH. Install with: brew install uv" >&2
    exit 1
fi
echo "▸ uv sync"
uv sync

# ─── 3. Build plist with this machine's paths ────────────────────────────
# The committed plist references /Users/7bellaa/cseDiscordBot. Rewrite
# every occurrence to point at the actual repo root on this machine.
echo "▸ rewriting plist paths → $ROOT"
sed -e "s|/Users/7bellaa/cseDiscordBot|$ROOT|g" "$PLIST_SRC" > "$PLIST_TMP"

mkdir -p "$HOME/Library/LaunchAgents"

# ─── 4. Reload the agent (unload-if-present, then bootstrap) ─────────────
if launchctl print "$SERVICE_TARGET" >/dev/null 2>&1; then
    echo "▸ bootout existing $LABEL"
    launchctl bootout "$SERVICE_TARGET" 2>/dev/null || true
fi

echo "▸ installing plist + bootstrap"
mv "$PLIST_TMP" "$PLIST_DST"
launchctl bootstrap "gui/${UID_NUM}" "$PLIST_DST"
launchctl enable "$SERVICE_TARGET"

# ─── 5. Optional immediate one-shot ──────────────────────────────────────
if [ "$KICKSTART" -eq 1 ]; then
    echo "▸ kickstart (one-shot now)"
    launchctl kickstart -k "$SERVICE_TARGET"
    sleep 2
    echo ""
    echo "── recent stderr ──"
    tail -n 20 "$ROOT/logs/launchd.stderr.log" 2>/dev/null || echo "(log not produced yet)"
    echo ""
fi

# ─── 6. Summary ──────────────────────────────────────────────────────────
echo ""
echo "✓ deploy complete"
echo "  service  : $LABEL"
echo "  schedule : daily 18:00 KST"
echo "  log      : $ROOT/logs/launchd.stderr.log"
echo ""
echo "verify:"
echo "  launchctl list | grep cse-bot"
echo "  tail -f $ROOT/logs/launchd.stderr.log"
