"""Integration tests for the orchestrator."""
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
    """Build board HTML matching the parser's selectors (table.board-table, td.td-title a)."""
    rows = "".join(
        f"""
        <tr>
            <td class="td-num">일반공지</td>
            <td class="td-title">
                <a href="https://cse.pusan.ac.kr/cse/14221/artclView.do?articleNo={i}">제목 {i}</a>
            </td>
            <td class="td-write">작성자</td>
            <td class="td-date">2026.04.30</td>
            <td class="td-file"></td>
        </tr>
        """
        for i in ids
    )
    return f"<html><body><table class='board-table'><tbody>{rows}</tbody></table></body></html>"


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"""
[general]
log_dir = "{tmp_path / 'logs'}"
state_file = "{tmp_path / 'state.json'}"
max_pages = 2
http_timeout_seconds = 5
http_retries = 2

[notification]
format = "medium"
self_alert_webhook_env = "WH_ALERT"

[[boards]]
id = "14221"
name = "일반공지"
url = "{BOARD_URL}"
webhook_env = "WH_GEN"
enabled = true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("WH_GEN", WEBHOOK)
    monkeypatch.setenv("WH_ALERT", ALERT)
    return cfg


@respx.mock
def test_baseline_mode_sends_no_notifications(cfg_file: Path, tmp_path: Path) -> None:
    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(200, text=_html_with_posts([19234, 19233, 19232]))
    )
    notify_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    assert notify_route.call_count == 0

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["boards"]["14221"]["last_max_post_id"] == 19234


@respx.mock
def test_new_posts_are_notified_in_ascending_order(
    cfg_file: Path, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "boards": {
                    "14221": {
                        "last_max_post_id": 19234,
                        "last_checked": "2026-04-30T09:00:00+09:00",
                        "empty_streak": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(
            200, text=_html_with_posts([19237, 19236, 19235, 19234, 19233])
        )
    )
    notify_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    assert notify_route.call_count == 3

    bodies = [json.loads(c.request.content) for c in notify_route.calls]
    titles_in_order = [b["content"] for b in bodies]
    assert "제목 19235" in titles_in_order[0]
    assert "제목 19236" in titles_in_order[1]
    assert "제목 19237" in titles_in_order[2]

    final = json.loads(state_path.read_text(encoding="utf-8"))
    assert final["boards"]["14221"]["last_max_post_id"] == 19237


@respx.mock
def test_partial_failure_preserves_progress(cfg_file: Path, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "boards": {
                    "14221": {
                        "last_max_post_id": 19234,
                        "last_checked": "t",
                        "empty_streak": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(
            200, text=_html_with_posts([19236, 19235, 19234])
        )
    )
    # First notify (id 19235) succeeds, second (19236) fails terminally with 404.
    respx.post(WEBHOOK).mock(
        side_effect=[httpx.Response(204), httpx.Response(404)]
    )
    respx.post(ALERT).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    # Cycle reports failure (non-zero), but state was advanced for the successful send.
    assert exit_code != 0

    final = json.loads(state_path.read_text(encoding="utf-8"))
    assert final["boards"]["14221"]["last_max_post_id"] == 19235


@respx.mock
def test_page_2_fetched_when_first_page_all_new(
    cfg_file: Path, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "boards": {
                    "14221": {
                        "last_max_post_id": 19000,
                        "last_checked": "t",
                        "empty_streak": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    page1_ids = list(range(19200, 19220))  # 20 posts, all > watermark 19000
    page2_ids = list(range(19180, 19200))  # 20 posts, partly above watermark

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        if page == "2":
            return httpx.Response(200, text=_html_with_posts(page2_ids))
        return httpx.Response(200, text=_html_with_posts(page1_ids))

    respx.get(host="cse.pusan.ac.kr").mock(side_effect=handler)
    notify_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    # All 40 posts have ids > 19000, so all 40 are notified.
    assert notify_route.call_count == 40
