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

from cse_bot._io import atomic_write_text
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

    atomic_write_text(output_path, json.dumps(events, ensure_ascii=False, indent=2))


def git_publish(
    paths: list[Path], *, message: str, cwd: Path | None = None,
) -> bool:
    """Add/commit/push *paths* to the current git branch.

    Returns ``True`` if a commit was created, ``False`` if there were no
    changes to publish. Raises :class:`RuntimeError` if any git command
    fails (other than ``diff --quiet`` indicating a change).

    Before pushing, the function rebases onto the configured upstream so a
    fast-forward succeeds even when another machine pushed in between
    cycles. On any failure after the commit is made, the commit is rolled
    back with ``git reset --mixed`` so the working tree keeps the new
    artifacts (the next cycle re-tries) and stale local commits do not
    accumulate.
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

    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd, capture_output=True, text=True,
    )
    if head_before.returncode != 0:
        raise RuntimeError(
            f"git_publish: cannot read HEAD (rc={head_before.returncode}): "
            f"{head_before.stderr.strip()}"
        )
    pre_commit_sha = head_before.stdout.strip()

    def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *cmd], cwd=cwd, capture_output=True, text=True,
        )

    def _rollback_commit() -> None:
        """Undo the commit we just made; keep working tree intact."""
        reset = _run(["reset", "--mixed", pre_commit_sha])
        if reset.returncode != 0:
            log.warning(
                "git_publish.rollback_failed sha=%s stderr=%s",
                pre_commit_sha, reset.stderr.strip(),
            )

    # add + commit first so the new artifacts are captured as a single
    # commit on top of HEAD; subsequent rebase/push will move it onto the
    # current upstream tip.
    for step in (["add", "--", *str_paths], ["commit", "-m", message]):
        r = _run(step)
        if r.returncode != 0:
            # No commit yet → nothing to roll back beyond the index entries
            # added by `git add`. Reset --mixed clears those.
            _run(["reset", "--mixed", pre_commit_sha])
            raise RuntimeError(
                f"git_publish: 'git {' '.join(step)}' failed "
                f"(rc={r.returncode}): {r.stderr.strip()}"
            )

    pull = _run(["pull", "--rebase", "--autostash"])
    if pull.returncode != 0:
        # Abort an in-progress rebase before resetting; ignore errors from
        # abort itself (it's a best-effort cleanup).
        _run(["rebase", "--abort"])
        _rollback_commit()
        raise RuntimeError(
            f"git_publish: 'git pull --rebase' failed "
            f"(rc={pull.returncode}): {pull.stderr.strip()}"
        )

    push = _run(["push"])
    if push.returncode != 0:
        _rollback_commit()
        raise RuntimeError(
            f"git_publish: 'git push' failed "
            f"(rc={push.returncode}): {push.stderr.strip()}"
        )

    log.info("git_publish.ok paths=%s", str_paths)
    return True
