"""Unit tests for operator-supplied calendar override loader."""
from __future__ import annotations

import json
from pathlib import Path

from cse_bot.manual_overrides import load_manual_overrides
from cse_bot.models import ManualOverride


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_load_returns_empty_when_file_missing(tmp_path: Path) -> None:
    assert load_manual_overrides(tmp_path / "manual.json") == []


def test_load_parses_valid_overrides(tmp_path: Path) -> None:
    path = tmp_path / "manual.json"
    _write(path, {
        "schema_version": 1,
        "overrides": [
            {
                "id": "m-1",
                "title": "수강신청",
                "url": "https://cse.pusan.ac.kr/...",
                "date": "2026-08-19",
                "category": "학업/수강",
                "important": True,
                "added_at": "2026-05-26T00:00:00+09:00",
                "added_by": "operator",
                "expires_at": None,
            }
        ],
    })
    overrides = load_manual_overrides(path)
    assert len(overrides) == 1
    o = overrides[0]
    assert isinstance(o, ManualOverride)
    assert o.id == "m-1"
    assert o.date == "2026-08-19"
    assert o.important is True


def test_load_returns_empty_on_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "manual.json"
    path.write_text("{not valid", encoding="utf-8")
    assert load_manual_overrides(path) == []


def test_load_skips_entries_missing_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "manual.json"
    _write(path, {
        "schema_version": 1,
        "overrides": [
            {"id": "ok", "title": "t", "url": "https://x", "date": "2026-08-19"},
            {"id": "bad-no-date", "title": "t", "url": "https://x"},
            {"id": "bad-no-url", "title": "t", "date": "2026-08-19"},
        ],
    })
    overrides = load_manual_overrides(path)
    assert [o.id for o in overrides] == ["ok"]


def test_load_uses_defaults_for_optional_fields(tmp_path: Path) -> None:
    path = tmp_path / "manual.json"
    _write(path, {
        "schema_version": 1,
        "overrides": [
            {"id": "m-1", "title": "t", "url": "https://x", "date": "2026-08-19"},
        ],
    })
    o = load_manual_overrides(path)[0]
    assert o.category == ""
    assert o.important is False
    assert o.expires_at is None
