"""Tests for the v1 → v2 data migration script."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def repo_root_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "state.json").write_text(
        json.dumps({
            "boards": {
                "14221": {
                    "last_max_post_id": 1441380,
                    "last_checked": "2026-05-26T09:00:00+09:00",
                    "empty_streak": 0,
                    "deadlines": [
                        {
                            "post_id": 1441380,
                            "title": "[장학] 주거안정장학금",
                            "url": "https://cse.pusan.ac.kr/.../1441380",
                            "date": "2026-06-22",
                            "reminded": False,
                            "category": "장학/등록",
                            "summary": "summary",
                            "important": True,
                        }
                    ],
                }
            }
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    return tmp_path


def test_migration_writes_post_cache(repo_root_layout: Path) -> None:
    import migrate_to_v2  # type: ignore[import-not-found]
    rc = migrate_to_v2.main([])
    assert rc == 0

    cache_path = repo_root_layout / "data" / "post_cache.json"
    assert cache_path.exists()
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["schema_version"] == 1
    posts = cache["boards"]["14221"]["posts"]
    assert "1441380" in posts
    entry = posts["1441380"]
    assert entry["deadline"] == "2026-06-22"
    # content_hash is intentionally empty so the next cycle re-summarises
    assert entry["content_hash"] == ""


def test_migration_clears_state_deadlines(repo_root_layout: Path) -> None:
    import migrate_to_v2  # type: ignore[import-not-found]
    migrate_to_v2.main([])
    state = json.loads(
        (repo_root_layout / "data" / "state.json").read_text(encoding="utf-8")
    )
    # Watermark preserved, deadlines emptied
    assert state["boards"]["14221"]["last_max_post_id"] == 1441380
    assert state["boards"]["14221"].get("deadlines", []) == []


def test_migration_dry_run_writes_nothing(repo_root_layout: Path) -> None:
    import migrate_to_v2  # type: ignore[import-not-found]
    rc = migrate_to_v2.main(["--dry-run"])
    assert rc == 0
    assert not (repo_root_layout / "data" / "post_cache.json").exists()


def test_migration_idempotent(repo_root_layout: Path) -> None:
    import migrate_to_v2  # type: ignore[import-not-found]
    migrate_to_v2.main([])
    rc = migrate_to_v2.main([])
    assert rc == 0
    # Re-running does not corrupt the cache
    cache = json.loads(
        (repo_root_layout / "data" / "post_cache.json").read_text(encoding="utf-8")
    )
    assert "1441380" in cache["boards"]["14221"]["posts"]
