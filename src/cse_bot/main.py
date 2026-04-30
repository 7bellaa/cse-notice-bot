"""Single-cycle orchestrator entry point."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from cse_bot import differ, fetcher, notifier, parser, state
from cse_bot.config import Config, ConfigError, load_config
from cse_bot.logging_setup import configure_logging
from cse_bot.models import BoardConfig, BoardState, Post

log = logging.getLogger("cse_bot.main")

EMPTY_STREAK_ALERT_THRESHOLD = 3


def run_cycle(config_path: Path) -> int:
    """Run one full check cycle. Returns exit code (0 = success, non-zero = error)."""
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        # Logging may not yet be configured; fall back to stderr.
        sys.stderr.write(f"CRITICAL config.error {e}\n")
        return 1

    configure_logging(Path(cfg.general.log_dir))
    log.info("cycle.start config=%s", config_path)

    state_path = Path(cfg.general.state_file)
    state_map = state.load_state(state_path)

    overall_ok = True
    for board in cfg.boards:
        if not board.enabled:
            log.info("board.skip id=%s reason=disabled", board.id)
            continue
        try:
            _process_board(board, cfg, state_map, state_path)
        except Exception as e:  # noqa: BLE001
            overall_ok = False
            log.exception("board.failed id=%s err=%s", board.id, e)
            _safe_alert(cfg, f"board {board.id} failed: {e}")

    state.save_state(state_path, state_map)
    log.info("cycle.end ok=%s", overall_ok)
    return 0 if overall_ok else 2


def _process_board(
    board: BoardConfig,
    cfg: Config,
    state_map: dict[str, BoardState],
    state_path: Path,
) -> None:
    board_state = state_map.get(
        board.id, BoardState(last_max_post_id=None, last_checked="", empty_streak=0)
    )

    posts = _fetch_posts_until_cutoff(board, cfg, board_state.last_max_post_id)

    if not posts:
        board_state.empty_streak += 1
        log.warning("parse.empty board=%s streak=%d", board.id, board_state.empty_streak)
        if board_state.empty_streak >= EMPTY_STREAK_ALERT_THRESHOLD:
            _safe_alert(
                cfg,
                f"board {board.id} parsing returned empty {board_state.empty_streak} times"
                " -- site structure may have changed",
            )
        state_map[board.id] = board_state
        return

    board_state.empty_streak = 0
    page_max_id = max(p.id for p in posts)

    if board_state.last_max_post_id is None:
        board_state.last_max_post_id = page_max_id
        board_state.last_checked = _now_iso()
        state_map[board.id] = board_state
        log.info("baseline.recorded board=%s watermark=%d", board.id, page_max_id)
        return

    new_posts: list[Post] = differ.diff(posts, watermark=board_state.last_max_post_id)
    log.info(
        "diff.computed board=%s watermark=%d new_count=%d",
        board.id,
        board_state.last_max_post_id,
        len(new_posts),
    )

    webhook_url = cfg.webhook_url(board.id)
    for post in new_posts:
        notifier.send(
            post,
            webhook_url=webhook_url,
            fmt=cfg.notification.format,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        board_state.last_max_post_id = post.id
        state_map[board.id] = board_state
        state.save_state(state_path, state_map)
        log.info("notify.ok board=%s post_id=%d", board.id, post.id)

    board_state.last_checked = _now_iso()
    state_map[board.id] = board_state


def _fetch_posts_until_cutoff(
    board: BoardConfig, cfg: Config, watermark: int | None
) -> list[Post]:
    posts: list[Post] = []
    for page in range(1, cfg.general.max_pages + 1):
        url = _with_page(board.url, page)
        html = fetcher.fetch(
            url,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        try:
            page_posts = parser.parse(html)
        except parser.ParseEmptyError:
            # Page 1 empty -> genuine empty/structure change. Page >1 empty ->
            # treat as end of pagination and use what we already have.
            if page == 1:
                return []
            break
        posts.extend(page_posts)

        if watermark is None:
            break
        if min(p.id for p in page_posts) <= watermark:
            break
    return posts


def _with_page(url: str, page: int) -> str:
    if page == 1:
        return url
    parsed = urlparse(url)
    qs = dict(parse_qsl(parsed.query))
    qs["page"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(qs)))


def _safe_alert(cfg: Config, message: str) -> None:
    try:
        notifier.send_alert(message, webhook_url=cfg.alert_webhook_url)
    except Exception:  # noqa: BLE001
        log.exception("alert.send_failed")


def _now_iso() -> str:
    return datetime.now(tz=UTC).astimezone().isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cse_bot")
    p.add_argument(
        "--config",
        type=Path,
        default=Path("config/config.toml"),
        help="Path to config.toml",
    )
    args = p.parse_args(argv)
    try:
        return run_cycle(args.config)
    except Exception as e:  # noqa: BLE001
        # Last-line defence: log and try to alert.
        log.exception("cycle.unhandled err=%s", e)
        try:
            cfg = load_config(args.config)
            notifier.send_alert(
                f"❌ cse_bot cycle crashed: {e}", webhook_url=cfg.alert_webhook_url
            )
        except Exception:  # noqa: BLE001
            log.exception("alert.unreachable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
