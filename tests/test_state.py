"""Unit tests for state persistence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cse_bot.models import BoardState
from cse_bot.state import load_state, save_state


def test_load_state_returns_empty_when_file_missing(tmp_path: Path) -> None:
    state = load_state(tmp_path / "state.json")
    assert state == {}


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    payload = {
        "14221": BoardState(
            last_max_post_id=19234,
            last_checked="2026-04-30T18:00:00+09:00",
            empty_streak=0,
        )
    }
    save_state(path, payload)
    loaded = load_state(path)
    assert loaded["14221"].last_max_post_id == 19234
    assert loaded["14221"].last_checked == "2026-04-30T18:00:00+09:00"
    assert loaded["14221"].empty_streak == 0


def test_load_state_with_corrupt_json_backs_up_and_returns_empty(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not valid json", encoding="utf-8")

    state = load_state(path)
    assert state == {}

    backups = list(tmp_path.glob("state.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not valid json"


def test_save_state_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "state.json"
    save_state(path, {})
    assert path.exists()


def test_save_state_writes_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    payload = {
        "14221": BoardState(
            last_max_post_id=1, last_checked="t", empty_streak=2
        )
    }
    save_state(path, payload)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["boards"]["14221"]["last_max_post_id"] == 1
    assert raw["boards"]["14221"]["empty_streak"] == 2


def test_save_state_rejects_non_monotonic_watermark(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state(path, {"14221": BoardState(last_max_post_id=10, last_checked="t")})
    with pytest.raises(ValueError, match="monotonic"):
        save_state(
            path, {"14221": BoardState(last_max_post_id=5, last_checked="t")}
        )
