"""Publish calendar data to the static FullCalendar site under ``docs/calendar/``.

Two responsibilities:

1. Serialize :class:`TrackedDeadline` instances to FullCalendar's event JSON
   so the static site can render them client-side.
2. Push the generated assets (``current.png``, ``events.json``, …) to git so
   GitHub Pages picks them up.

Both functions are intentionally side-effect-light — the caller decides
where output goes and whether the bot has permission to push.
"""
from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Iterable
from pathlib import Path

from cse_bot.category import classification_to_color
from cse_bot.models import TrackedDeadline

log = logging.getLogger(__name__)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def write_events_json(deadlines: Iterable[TrackedDeadline], output_path: Path) -> None:
    """Serialize *deadlines* to a FullCalendar-compatible JSON array.

    Atomic via tmp-file + replace. Korean characters are emitted as UTF-8
    rather than ``\\uXXXX`` escapes.
    """
    events: list[dict[str, object]] = []
    for d in deadlines:
        events.append(
            {
                "id": str(d.post_id),
                "title": d.title,
                "start": d.date,
                "url": d.url,
                "color": _rgb_to_hex(classification_to_color(d.category)),
                "extendedProps": {
                    "category": d.category,
                    "summary": d.summary,
                    "important": d.important,
                },
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(output_path)


def git_publish(
    paths: list[Path], *, message: str, cwd: Path | None = None,
) -> bool:
    """Add/commit/push *paths* to the current git branch.

    Returns ``True`` if a commit was created, ``False`` if there were no
    changes to publish. Raises :class:`RuntimeError` if any git command
    fails (other than ``diff --quiet`` indicating a change).
    """
    str_paths = [str(p) for p in paths]

    # 1) `git diff --quiet --` short-circuits when nothing changed.
    diff = subprocess.run(
        ["git", "diff", "--quiet", "--", *str_paths],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    cached = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *str_paths],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if diff.returncode == 0 and cached.returncode == 0:
        # Also check for untracked files in the publish set.
        ls = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "--", *str_paths],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if not ls.stdout.strip():
            log.info("git_publish.skip reason=no_changes paths=%s", str_paths)
            return False

    for step in (
        ["git", "add", "--", *str_paths],
        ["git", "commit", "-m", message],
        ["git", "push"],
    ):
        result = subprocess.run(step, cwd=cwd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"git_publish: '{' '.join(step)}' failed "
                f"(rc={result.returncode}): {result.stderr.strip()}"
            )

    log.info("git_publish.ok paths=%s", str_paths)
    return True
