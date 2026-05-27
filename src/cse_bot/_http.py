"""Shared HTTP constants used by every outbound call.

Single source for the ``User-Agent`` header so PNU CSE / Discord / Gemini
all see the same identity string and an admin trying to track a misbehaving
client lands on the GitHub repo instead of guessing.
"""
from __future__ import annotations

USER_AGENT = "cse-discord-bot/0.1 (+https://github.com/7bellaa/cse-notice-bot)"
