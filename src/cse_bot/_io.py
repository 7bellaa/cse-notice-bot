"""Shared filesystem helpers: atomic text writes and corrupt-file quarantine.

Both idioms are used by the JSON persistence layers (``state``,
``post_cache``) and the calendar publisher (``web_publisher``); keeping a
single implementation avoids the subtle drift that copy-pasted ``.tmp`` /
``.corrupt-<epoch>`` logic invites.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write *text* to *path* atomically via a sibling ``.tmp`` + replace.

    Parent directories are created as needed. The replace is atomic on the
    same filesystem, so a crash mid-write never leaves a partial file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


def quarantine_corrupt(path: Path) -> Path:
    """Move a corrupt file aside as ``<name>.corrupt-<epoch>``; return the backup path.

    The caller logs and returns its own empty value so the next cycle can
    rebuild from scratch.
    """
    backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    shutil.move(str(path), backup)
    return backup
