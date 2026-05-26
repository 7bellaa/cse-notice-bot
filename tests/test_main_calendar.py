"""End-to-end tests for run_cycle with calendar (digest) mode enabled."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from cse_bot.main import run_cycle

BOARD_URL = "https://cse.pusan.ac.kr/cse/14221/subview.do"
WEBHOOK = "https://discord.com/api/webhooks/x/y"
ALERT = "https://discord.com/api/webhooks/a/alert"


def _html_with_posts(ids: list[int]) -> str:
    artcl = "https://cse.pusan.ac.kr/cse/14221/artclView.do"
    rows = "".join(
        f"""
        <tr>
            <td class="td-num">{i}</td>
            <td class="td-title">
                <a href="{artcl}?articleNo={i}">[장학] 제목 {i}</a>
            </td>
            <td class="td-write">학과사무실</td>
            <td class="td-date">2026.05.26</td>
            <td class="td-file"></td>
        </tr>
        """
        for i in ids
    )
    return (
        "<html><body><table class='board-table'><tbody>"
        f"{rows}</tbody></table></body></html>"
    )


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"""
[general]
log_dir = "{tmp_path / 'logs'}"
state_file = "{tmp_path / 'state.json'}"
max_pages = 1
http_timeout_seconds = 5
http_retries = 2

[notification]
format = "medium"
self_alert_webhook_env = "WH_ALERT"

[gemini]
api_key_env = "GEMINI_API_KEY"
model = "gemini-2.5-flash-lite"
timeout_seconds = 10

[calendar]
enabled = true
output_dir = "{tmp_path / 'docs/calendar'}"
site_url = "https://example.com/calendar"
months_in_png = 2

[[boards]]
id = "14221"
name = "테스트보드"
url = "{BOARD_URL}"
webhook_envs = ["WH_GEN"]
enabled = true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("WH_GEN", WEBHOOK)
    monkeypatch.setenv("WH_ALERT", ALERT)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    # Don't actually run git in tests
    monkeypatch.setattr(
        "cse_bot.main.git_publish",
        lambda *_a, **_kw: False,
    )
    return cfg


def _seed_state(state_path: Path, last_max: int) -> None:
    state_path.write_text(
        json.dumps(
            {
                "boards": {
                    "14221": {
                        "last_max_post_id": last_max,
                        "last_checked": "2026-05-26T09:00:00+09:00",
                        "empty_streak": 0,
                        "deadlines": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )


@respx.mock
def test_digest_mode_posts_single_message_with_embed(
    cfg_file: Path, tmp_path: Path
) -> None:
    _seed_state(tmp_path / "state.json", last_max=19234)

    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(200, text=_html_with_posts([19236, 19235, 19234]))
    )
    # article fetch returns 404 → no summarization, no deadlines
    respx.get(host="cse.pusan.ac.kr", path__startswith="/cse/14221/artclView.do").mock(
        return_value=httpx.Response(404)
    )
    digest_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    # Exactly ONE digest message (not 2 per-post)
    assert digest_route.call_count == 1

    body = json.loads(digest_route.calls.last.request.content.decode("utf-8"))
    # Should be a digest payload, not legacy "content" only
    assert "embeds" in body
    assert len(body["embeds"]) == 1
    embed = body["embeds"][0]
    assert "PNU CSE" in embed["title"]
    assert embed["image"]["url"].startswith("https://example.com/calendar/current.png")
    # Content should list the 2 new posts in 1-line form
    assert "제목 19235" in body["content"]
    assert "제목 19236" in body["content"]


@respx.mock
def test_digest_mode_writes_png_and_events_json(
    cfg_file: Path, tmp_path: Path
) -> None:
    _seed_state(tmp_path / "state.json", last_max=19234)

    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(200, text=_html_with_posts([19235, 19234]))
    )
    respx.get(host="cse.pusan.ac.kr", path__startswith="/cse/14221/artclView.do").mock(
        return_value=httpx.Response(404)
    )
    respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0

    out_dir = tmp_path / "docs/calendar"
    assert (out_dir / "current.png").exists()
    assert (out_dir / "events.json").exists()
    events = json.loads((out_dir / "events.json").read_text(encoding="utf-8"))
    assert isinstance(events, list)


@respx.mock
def test_digest_mode_baseline_skips_digest(
    cfg_file: Path, tmp_path: Path
) -> None:
    # No state.json → baseline mode for the first run
    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(200, text=_html_with_posts([19234, 19233]))
    )
    digest_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    # The digest still fires (calendar always updates), but with 0 new posts.
    # The PNG embed is the heartbeat.
    assert digest_route.call_count == 1
    body = json.loads(digest_route.calls.last.request.content.decode("utf-8"))
    # No new posts → content should be omitted entirely
    assert "content" not in body or body["content"] == ""


@respx.mock
def test_digest_mode_no_new_posts_still_sends_calendar(
    cfg_file: Path, tmp_path: Path
) -> None:
    # Watermark already at the max → no new posts this cycle
    _seed_state(tmp_path / "state.json", last_max=19234)

    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(200, text=_html_with_posts([19234, 19233, 19232]))
    )
    digest_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    # Still post the daily heartbeat
    assert digest_route.call_count == 1
    body = json.loads(digest_route.calls.last.request.content.decode("utf-8"))
    assert "embeds" in body
    assert "content" not in body or body["content"] == ""
