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


def _row(post_id: int, num_label: str) -> str:
    href = f"https://cse.pusan.ac.kr/cse/14221/artclView.do?articleNo={post_id}"
    return f"""
        <tr>
            <td class="td-num">{num_label}</td>
            <td class="td-title">
                <a href="{href}">제목 {post_id}</a>
            </td>
            <td class="td-write">작성자</td>
            <td class="td-date">2026.04.30</td>
            <td class="td-file"></td>
        </tr>
        """


def _html_with_posts(ids: list[int]) -> str:
    """Build board HTML matching the parser's selectors (table.board-table, td.td-title a)."""
    rows = "".join(_row(i, "일반공지") for i in ids)
    return f"<html><body><table class='board-table'><tbody>{rows}</tbody></table></body></html>"


def _html_pinned_and_regular(pinned_ids: list[int], regular_ids: list[int]) -> str:
    """Board HTML where pinned ('일반공지') rows sit above regular numbered rows.

    Mirrors the live PNU CSE board: a freshly posted notice can appear BOTH as a
    pinned row at the top and as its own regular numbered row, so the same
    post id shows up twice on one page.
    """
    pinned = "".join(_row(i, "일반공지") for i in pinned_ids)
    regular = "".join(_row(i, str(seq)) for seq, i in enumerate(regular_ids, start=1))
    return (
        "<html><body><table class='board-table'><tbody>"
        f"{pinned}{regular}"
        "</tbody></table></body></html>"
    )


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

[gemini]
api_key_env = "GEMINI_API_KEY"
model = "gemini-2.5-flash-lite"
timeout_seconds = 10

[[boards]]
id = "14221"
name = "일반공지"
url = "{BOARD_URL}"
webhook_envs = ["WH_GEN"]
enabled = true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("WH_GEN", WEBHOOK)
    monkeypatch.setenv("WH_ALERT", ALERT)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
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
    # article fetch returns 404 (no body) — summarizer skipped, notification still sent
    respx.get(host="cse.pusan.ac.kr", path__startswith="/cse/14221/artclView.do").mock(
        return_value=httpx.Response(404)
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
def test_post_pinned_and_regular_is_notified_once(
    cfg_file: Path, tmp_path: Path
) -> None:
    """A new post that is also pinned shows twice in the listing — once as a
    '일반공지' row at the top, once as a regular numbered row. It must be
    notified exactly once.

    Regression for the 1441906 duplicate: post 1441906 was newly posted AND
    pinned, so it appeared in both the pinned and regular sections of page 1.
    """
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

    # id 19236 is pinned at the top AND present as a regular numbered row.
    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(
            200,
            text=_html_pinned_and_regular(
                pinned_ids=[19236],
                regular_ids=[19237, 19236, 19235, 19234, 19233],
            ),
        )
    )
    respx.get(host="cse.pusan.ac.kr", path__startswith="/cse/14221/artclView.do").mock(
        return_value=httpx.Response(404)
    )
    notify_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0

    # New posts above watermark 19234 are 19235, 19236, 19237 — three, not four.
    assert notify_route.call_count == 3
    bodies = "\n".join(c.request.content.decode() for c in notify_route.calls)
    assert bodies.count("제목 19236") == 1


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
    # article fetch returns 404 (no body) — summarizer skipped
    respx.get(host="cse.pusan.ac.kr", path__startswith="/cse/14221/artclView.do").mock(
        return_value=httpx.Response(404)
    )
    # First notify (id 19235) succeeds, second (19236) fails terminally with 404.
    respx.post(WEBHOOK).mock(
        side_effect=[httpx.Response(204), httpx.Response(404)]
    )
    respx.post(ALERT).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    # Cycle reports failure (non-zero) because one webhook failed.
    # Watermark advances to the highest processed post regardless — the post is
    # tracked in state even if its delivery failed, so we don't re-summarize it.
    # The operator gets a self-alert about the failed webhook.
    assert exit_code != 0

    final = json.loads(state_path.read_text(encoding="utf-8"))
    assert final["boards"]["14221"]["last_max_post_id"] == 19236


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
        if "artclView" in request.url.path:
            return httpx.Response(404)  # article fetch → no body, no summary
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


@respx.mock
def test_uncaught_exception_triggers_alert(
    cfg_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert_route = respx.post(ALERT).mock(return_value=httpx.Response(204))

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated catastrophic failure")

    # Force fetcher.fetch to blow up before any HTTP mock matches.
    monkeypatch.setattr("cse_bot.main.fetcher.fetch", boom)

    exit_code = run_cycle(cfg_file)
    assert exit_code != 0
    assert alert_route.called


def test_load_dotenv_populates_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cse_bot.main import _load_dotenv

    env_path = tmp_path / ".env"
    env_path.write_text(
        '# comment line\n'
        'DISCORD_WEBHOOK_GENERAL=https://discord.com/api/webhooks/1/aaa\n'
        'DISCORD_WEBHOOK_ALERT="https://discord.com/api/webhooks/2/bbb"\n'
        '\n'
        "EMPTY_VALUE=\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DISCORD_WEBHOOK_GENERAL", raising=False)
    monkeypatch.delenv("DISCORD_WEBHOOK_ALERT", raising=False)
    monkeypatch.delenv("EMPTY_VALUE", raising=False)

    _load_dotenv(env_path)

    import os
    assert os.environ["DISCORD_WEBHOOK_GENERAL"] == "https://discord.com/api/webhooks/1/aaa"
    assert os.environ["DISCORD_WEBHOOK_ALERT"] == "https://discord.com/api/webhooks/2/bbb"


def test_load_dotenv_does_not_override_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cse_bot.main import _load_dotenv

    env_path = tmp_path / ".env"
    env_path.write_text("DISCORD_WEBHOOK_GENERAL=from_dotenv\n", encoding="utf-8")
    monkeypatch.setenv("DISCORD_WEBHOOK_GENERAL", "from_shell")

    _load_dotenv(env_path)

    import os
    assert os.environ["DISCORD_WEBHOOK_GENERAL"] == "from_shell"


def test_load_dotenv_missing_file_is_no_op(tmp_path: Path) -> None:
    from cse_bot.main import _load_dotenv
    _load_dotenv(tmp_path / "does_not_exist.env")  # must not raise
