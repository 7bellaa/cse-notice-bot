"""Unit tests for config loading."""
from __future__ import annotations

from pathlib import Path

import pytest

from cse_bot.config import Config, ConfigError, load_config


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_load_config_parses_general_and_boards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    _write(
        cfg_path,
        """
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 2
http_timeout_seconds = 15
http_retries = 3

[notification]
format = "medium"
self_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"

[[boards]]
id = "14221"
name = "일반공지"
url = "https://example.com"
webhook_env = "WH_GEN"
enabled = true
""",
    )
    monkeypatch.setenv("WH_GEN", "https://discord.com/api/webhooks/x/y")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://discord.com/api/webhooks/a/b")

    cfg = load_config(cfg_path)
    assert isinstance(cfg, Config)
    assert cfg.general.max_pages == 2
    assert cfg.notification.format == "medium"
    assert len(cfg.boards) == 1
    assert cfg.boards[0].id == "14221"
    assert cfg.webhook_url("14221") == "https://discord.com/api/webhooks/x/y"
    assert cfg.alert_webhook_url == "https://discord.com/api/webhooks/a/b"


def test_missing_webhook_env_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    _write(
        cfg_path,
        """
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 2
http_timeout_seconds = 15
http_retries = 3

[notification]
format = "medium"
self_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"

[[boards]]
id = "14221"
name = "일반공지"
url = "https://example.com"
webhook_env = "WH_MISSING"
enabled = true
""",
    )
    monkeypatch.delenv("WH_MISSING", raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://discord.com/api/webhooks/a/b")

    with pytest.raises(ConfigError, match="WH_MISSING"):
        load_config(cfg_path)


def test_invalid_format_value_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    _write(
        cfg_path,
        """
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 2
http_timeout_seconds = 15
http_retries = 3

[notification]
format = "fancy"
self_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"

[[boards]]
id = "14221"
name = "일반공지"
url = "https://example.com"
webhook_env = "WH_GEN"
enabled = true
""",
    )
    monkeypatch.setenv("WH_GEN", "x")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "y")

    with pytest.raises(ConfigError, match="format"):
        load_config(cfg_path)


def test_disabled_board_skips_webhook_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    _write(
        cfg_path,
        """
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 2
http_timeout_seconds = 15
http_retries = 3

[notification]
format = "medium"
self_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"

[[boards]]
id = "99999"
name = "비활성"
url = "https://example.com"
webhook_env = "WH_NEVER"
enabled = false
""",
    )
    monkeypatch.delenv("WH_NEVER", raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "y")

    cfg = load_config(cfg_path)
    assert cfg.boards[0].enabled is False
