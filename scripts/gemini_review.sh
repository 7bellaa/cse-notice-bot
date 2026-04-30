#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <task-anchor>" >&2
    echo "example: $0 'docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md#task-3'" >&2
    exit 64
fi

TASK_ANCHOR="$1"
DIFF_FILE="$(mktemp)"
PROMPT_FILE="$(mktemp)"
RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$DIFF_FILE" "$PROMPT_FILE" "$RESPONSE_FILE"' EXIT

# 1. Diff scope: uncommitted changes (option A).
git diff HEAD > "$DIFF_FILE"

if ! [[ -s "$DIFF_FILE" ]]; then
    # No uncommitted changes → review the most recent commit instead, so we can
    # still verify a just-committed task.
    git diff HEAD~1 HEAD > "$DIFF_FILE"
fi

# 2. Test summary (assumes pytest already ran successfully before invocation).
TEST_SUMMARY="$(pytest -q 2>&1 | tail -3 || true)"
RUFF_SUMMARY="$(ruff check src/ tests/ 2>&1 | tail -3 || true)"
MYPY_SUMMARY="$(mypy src/ 2>&1 | tail -3 || true)"

# 3. Assemble prompt.
{
    cat scripts/gemini_review_template.md
    printf '\n# Task anchor\n%s\n' "$TASK_ANCHOR"
    printf '\n# Diff\n```diff\n'
    cat "$DIFF_FILE"
    printf '\n```\n'
    printf '\n# Test results\npytest:\n%s\nruff:\n%s\nmypy:\n%s\n' \
        "$TEST_SUMMARY" "$RUFF_SUMMARY" "$MYPY_SUMMARY"
} > "$PROMPT_FILE"

# 4. Call Gemini 3 Pro.
gemini -m gemini-3-pro -p "$(cat "$PROMPT_FILE")" > "$RESPONSE_FILE"

# 5. Echo response and parse VERDICT.
cat "$RESPONSE_FILE"
echo "----"
VERDICT="$(grep -E '^VERDICT:' "$RESPONSE_FILE" | head -1 | awk '{print $2}' || true)"

if [[ "$VERDICT" == "PASS" ]]; then
    echo "✅ Gemini PASS for $TASK_ANCHOR"
    exit 0
else
    echo "❌ Gemini FAIL for $TASK_ANCHOR (verdict='$VERDICT')"
    exit 1
fi
