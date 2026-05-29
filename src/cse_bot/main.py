"""Single-cycle orchestrator entry point.

Two output modes, selected by ``cfg.calendar.enabled``:

- **Digest mode** (new, default): a single Discord message per cycle bundles
  a rendered calendar PNG plus a 1-line bullet per new post. The PNG and an
  ``events.json`` are also published to ``docs/calendar/`` so a static
  FullCalendar site can render the same data.
- **Legacy mode**: per-post text webhooks (preserved for backward
  compatibility and tests). D-1 reminders are emitted as separate alerts.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from cse_bot import article, differ, fetcher, notifier, parser, reminder, state, summarizer
from cse_bot.calendar_renderer import render_upcoming_strip
from cse_bot.category import classify, is_important
from cse_bot.config import Config, ConfigError, load_config
from cse_bot.logging_setup import configure_logging
from cse_bot.models import BoardConfig, BoardState, Post, TrackedDeadline
from cse_bot.web_publisher import git_publish, write_events_json

log = logging.getLogger("cse_bot.main")

KST = ZoneInfo("Asia/Seoul")
EMPTY_STREAK_ALERT_THRESHOLD = 3


def _load_dotenv(env_path: Path) -> None:
    """Load KEY=VALUE pairs from *env_path* into os.environ.

    Existing environment variables are NOT overwritten — explicit env wins.
    Silently does nothing if the file is missing.
    """
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def run_cycle(config_path: Path) -> int:
    """Run one full check cycle. Returns exit code (0 = success, non-zero = error)."""
    project_root = config_path.resolve().parent.parent
    _load_dotenv(project_root / ".env")

    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        sys.stderr.write(f"CRITICAL config.error {e}\n")
        return 1

    configure_logging(Path(cfg.general.log_dir))
    log.info(
        "cycle.start config=%s calendar=%s",
        config_path,
        "enabled" if cfg.calendar.enabled else "disabled",
    )

    state_path = Path(cfg.general.state_file)
    state_map = state.load_state(state_path)
    today = datetime.now(KST).date()

    overall_ok = True
    per_board_full: list[
        tuple[BoardConfig, list[Post], list[Post], dict[int, str]]
    ] = []
    for board in cfg.boards:
        if not board.enabled:
            log.info("board.skip id=%s reason=disabled", board.id)
            continue
        try:
            posts, new_posts, summaries = _process_board(
                board, cfg, state_map, state_path, today=today,
            )
            per_board_full.append((board, posts, new_posts, summaries))
        except Exception as e:  # noqa: BLE001
            overall_ok = False
            log.exception("board.failed id=%s err=%s", board.id, e)
            _safe_alert(cfg, f"board {board.id} failed: {e}")

    # Drop expired deadlines so the calendar window stays current.
    pruned = reminder.prune_expired(state_map, today=today)
    if pruned:
        log.info("deadlines.pruned count=%d", pruned)

    if cfg.calendar.enabled:
        try:
            _emit_daily_digest(
                cfg, state_map, per_board_full, today=today, project_root=project_root,
            )
        except Exception as e:  # noqa: BLE001
            overall_ok = False
            log.exception("digest.failed err=%s", e)
            _safe_alert(cfg, f"daily digest failed: {e}")
    else:
        # Legacy per-post text webhook + separate D-1 alerts.
        if not _legacy_emit(cfg, state_map, per_board_full, today=today):
            overall_ok = False

    state.save_state(state_path, state_map)
    log.info("cycle.end ok=%s", overall_ok)
    return 0 if overall_ok else 2


def _process_board(
    board: BoardConfig,
    cfg: Config,
    state_map: dict[str, BoardState],
    state_path: Path,
    *,
    today: date,
) -> tuple[list[Post], list[Post], dict[int, str]]:
    """Fetch + summarize new posts for *board*, updating state in place.

    Does not send any Discord messages — the caller decides how to surface
    these (digest or legacy per-post). Returns a 3-tuple of:
    - all posts fetched from the list page (for the calendar snapshot)
    - new posts discovered this cycle (in ascending id order)
    - a map of post_id → 1-line summary preview
    """
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
        return [], [], {}

    board_state.empty_streak = 0
    page_max_id = max(p.id for p in posts)

    if board_state.last_max_post_id is None:
        board_state.last_max_post_id = page_max_id
        board_state.last_checked = _now_iso()
        state_map[board.id] = board_state
        log.info("baseline.recorded board=%s watermark=%d", board.id, page_max_id)
        return posts, [], {}

    new_posts: list[Post] = differ.diff(posts, watermark=board_state.last_max_post_id)
    log.info(
        "diff.computed board=%s watermark=%d new_count=%d",
        board.id, board_state.last_max_post_id, len(new_posts),
    )

    summaries: dict[int, str] = {}

    for post in new_posts:
        content = article.fetch_article_content(
            post.url,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        body = content.body if content else ""
        images = content.image_urls if content else []
        result = (
            summarizer.summarize(
                body,
                image_urls=images,
                api_key=cfg.gemini.api_key,
                model=cfg.gemini.model,
                timeout=cfg.gemini.timeout_seconds,
            )
            if (body or images)
            else None
        )
        if result and result.summary:
            summaries[post.id] = result.summary

        # BoardState.deadlines only drives legacy D-1 reminders. In v2 digest
        # mode the calendar reads from post_cache.json, so writing here would
        # bloat state.json with never-read entries (still pruned each cycle).
        if not cfg.calendar.enabled and result and result.deadline:
            try:
                d_date = date.fromisoformat(result.deadline)
                if d_date > today:
                    board_state.deadlines.append(
                        TrackedDeadline(
                            post_id=post.id,
                            title=post.title,
                            url=post.url,
                            date=result.deadline,
                            reminded=False,
                            category=classify(post.title),
                            summary=result.short_summary,
                            important=is_important(post.title),
                        )
                    )
            except ValueError:
                log.warning(
                    "deadline.invalid_format post_id=%d raw=%r",
                    post.id, result.deadline,
                )

        # Advance watermark per-post so a mid-batch crash doesn't re-process
        # already-summarized articles on the next cycle.
        board_state.last_max_post_id = post.id
        state_map[board.id] = board_state
        state.save_state(state_path, state_map)
        log.info(
            "post.processed board=%s post_id=%d summary=%s deadline=%s",
            board.id, post.id,
            "yes" if post.id in summaries else "no",
            result.deadline if (result and result.deadline) else "no",
        )

    board_state.last_checked = _now_iso()
    state_map[board.id] = board_state
    return posts, new_posts, summaries


# ─── Digest mode (calendar enabled) ──────────────────────────────────────


def _emit_daily_digest(
    cfg: Config,
    state_map: dict[str, BoardState],
    per_board_full: list[
        tuple[BoardConfig, list[Post], list[Post], dict[int, str]]
    ],
    *,
    today: date,
    project_root: Path,
) -> None:
    """Update snapshot cache, render calendar, send a single digest message."""
    from cse_bot import calendar_publisher

    now_iso = datetime.now(KST).isoformat(timespec="seconds")

    cache_path = project_root / cfg.calendar.cache_path
    manual_path = project_root / cfg.calendar.manual_overrides_path

    # per_board_full only contains enabled boards (filtered in run_cycle).
    all_events: list[TrackedDeadline] = []
    for board, posts, _new_posts, _summaries in per_board_full:
        events = calendar_publisher.run_calendar_publish(
            board_id=board.id,
            posts_in_list=posts,
            today=today,
            now_iso=now_iso,
            cache_path=cache_path,
            manual_path=manual_path,
            ttl_days=cfg.calendar.cache_ttl_days,
            gemini_api_key=cfg.gemini.api_key,
            gemini_model=cfg.gemini.model,
            gemini_timeout=cfg.gemini.timeout_seconds,
            http_timeout=cfg.general.http_timeout_seconds,
            http_retries=cfg.general.http_retries,
        )
        all_events.extend(events)
    all_events.sort(key=lambda d: d.date)

    out_dir = project_root / cfg.calendar.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "current.png"
    events_path = out_dir / "events.json"
    render_upcoming_strip(all_events, today, png_path, top_n=5)
    write_events_json(all_events, events_path)

    try:
        published = git_publish(
            [out_dir],
            message=f"auto: calendar update {today.isoformat()}",
            cwd=project_root,
        )
        if published:
            log.info("calendar.git_published path=%s", out_dir)
    except RuntimeError as e:
        # Don't abort the digest just because git push failed — log + alert.
        log.warning("calendar.git_publish_failed err=%s", e)
        _safe_alert(cfg, f"calendar git_publish failed: {e}")

    all_new_posts: list[Post] = []
    for _board, _posts, new_posts, _summaries in per_board_full:
        all_new_posts.extend(new_posts)

    webhook_urls = cfg.all_webhook_urls()
    if not webhook_urls:
        log.warning("digest.no_webhooks")
        return

    upcoming = all_events[:5]
    ok, failed = notifier.send_daily_digest(
        webhook_urls,
        calendar_png_url=f"{cfg.calendar.site_url}/current.png",
        site_url=cfg.calendar.site_url,
        new_posts=all_new_posts,
        upcoming=upcoming,
        today=today,
        timeout=cfg.general.http_timeout_seconds,
        retries=cfg.general.http_retries,
    )
    if failed:
        _safe_alert(
            cfg,
            f"daily digest: {len(failed)}/{ok + len(failed)} webhooks failed",
        )
    if ok == 0:
        raise RuntimeError("all webhooks failed for daily digest")


# ─── Legacy mode (calendar disabled) ─────────────────────────────────────


def _legacy_emit(
    cfg: Config,
    state_map: dict[str, BoardState],
    per_board_full: list[
        tuple[BoardConfig, list[Post], list[Post], dict[int, str]]
    ],
    *,
    today: date,
) -> bool:
    """Per-post text webhooks + separate D-1 alerts (pre-calendar behavior)."""
    ok_overall = True
    for board, _posts, new_posts, summaries in per_board_full:
        try:
            urls = cfg.webhook_urls(board.id)
        except ConfigError:
            log.warning("legacy.no_webhooks board=%s", board.id)
            continue
        for post in new_posts:
            ok_count, failed_urls = notifier.send_to_webhooks(
                post,
                webhook_urls=urls,
                summary=summaries.get(post.id),
                fmt=cfg.notification.format,
                timeout=cfg.general.http_timeout_seconds,
                retries=cfg.general.http_retries,
            )
            if ok_count == 0:
                ok_overall = False
                _safe_alert(cfg, f"post {post.id}: all webhooks failed")
            if failed_urls:
                _safe_alert(
                    cfg,
                    f"post {post.id}: {len(failed_urls)}/"
                    f"{ok_count + len(failed_urls)} webhooks failed",
                )
            log.info(
                "legacy.notify board=%s post_id=%d webhooks_ok=%d webhooks_failed=%d",
                board.id, post.id, ok_count, len(failed_urls),
            )

    # Existing D-1 reminder dispatch (kept only in legacy mode).
    due = reminder.collect_due_reminders(state_map, today=today)
    for board_id, deadline in due:
        try:
            urls = cfg.webhook_urls(board_id)
        except ConfigError:
            log.warning("reminder.no_webhooks board=%s", board_id)
            continue
        msg = reminder.format_reminder(deadline)
        ok, failed = notifier.send_alert_to_webhooks(
            msg,
            webhook_urls=urls,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        if ok > 0:
            deadline.reminded = True
            log.info(
                "reminder.sent board=%s post_id=%d webhooks_ok=%d webhooks_failed=%d",
                board_id, deadline.post_id, ok, len(failed),
            )
        if failed:
            _safe_alert(
                cfg,
                f"reminder for post {deadline.post_id}: "
                f"{len(failed)}/{ok + len(failed)} webhooks failed",
            )
    return ok_overall


# ─── Helpers ─────────────────────────────────────────────────────────────


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
