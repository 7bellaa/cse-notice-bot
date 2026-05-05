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

[gemini]
api_key_env = "GEMINI_API_KEY"
model = "gemini-2.5-flash-lite"
timeout_seconds = 10

[[boards]]
id = "14221"
name = "일반공지"
url = "https://example.com"
webhook_envs = ["WH_GEN"]
enabled = true
""",
    )
    monkeypatch.setenv("WH_GEN", "https://discord.com/api/webhooks/x/y")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    cfg = load_config(cfg_path)
    assert isinstance(cfg, Config)
    assert cfg.general.max_pages == 2
    assert cfg.notification.format == "medium"
    assert len(cfg.boards) == 1
    assert cfg.boards[0].id == "14221"
    assert cfg.webhook_urls("14221") == ["https://discord.com/api/webhooks/x/y"]
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

[gemini]
api_key_env = "GEMINI_API_KEY"
model = "gemini-2.5-flash-lite"
timeout_seconds = 10

[[boards]]
id = "14221"
name = "일반공지"
url = "https://example.com"
webhook_envs = ["WH_MISSING"]
enabled = true
""",
    )
    monkeypatch.delenv("WH_MISSING", raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setenv("GEMINI_API_KEY", "k")

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

[gemini]
api_key_env = "GEMINI_API_KEY"
model = "gemini-2.5-flash-lite"
timeout_seconds = 10

[[boards]]
id = "14221"
name = "일반공지"
url = "https://example.com"
webhook_envs = ["WH_GEN"]
enabled = true
""",
    )
    monkeypatch.setenv("WH_GEN", "x")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "y")
    monkeypatch.setenv("GEMINI_API_KEY", "k")

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

[gemini]
api_key_env = "GEMINI_API_KEY"
model = "gemini-2.5-flash-lite"
timeout_seconds = 10

[[boards]]
id = "99999"
name = "비활성"
url = "https://example.com"
webhook_envs = ["WH_NEVER"]
enabled = false
""",
    )
    monkeypatch.delenv("WH_NEVER", raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "y")
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    cfg = load_config(cfg_path)
    assert cfg.boards[0].enabled is False


def test_load_config_parses_gemini_section(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_A", "https://a")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://alert")
    monkeypatch.setenv("MY_GEMINI", "secret-key")
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(
        '[general]\n'
        'log_dir = "logs"\nstate_file = "data/state.json"\n'
        'max_pages = 1\nhttp_timeout_seconds = 5\nhttp_retries = 1\n'
        '[notification]\n'
        'format = "medium"\nself_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"\n'
        '[gemini]\n'
        'api_key_env = "MY_GEMINI"\n'
        'model = "gemini-2.5-flash-lite"\n'
        'timeout_seconds = 8\n'
        '[[boards]]\n'
        'id = "1"\nname = "n"\nurl = "https://x"\n'
        'webhook_envs = ["DISCORD_WEBHOOK_A"]\n',
        encoding="utf-8",
    )
    from cse_bot.config import load_config
    cfg = load_config(cfg_path)
    assert cfg.gemini.api_key == "secret-key"
    assert cfg.gemini.model == "gemini-2.5-flash-lite"
    assert cfg.gemini.timeout_seconds == 8


def test_load_config_missing_gemini_key_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_A", "https://a")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://alert")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(
        '[general]\n'
        'log_dir = "logs"\nstate_file = "data/state.json"\n'
        'max_pages = 1\nhttp_timeout_seconds = 5\nhttp_retries = 1\n'
        '[notification]\n'
        'format = "medium"\nself_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"\n'
        '[gemini]\n'
        'api_key_env = "GEMINI_API_KEY"\n'
        'model = "gemini-2.5-flash-lite"\n'
        'timeout_seconds = 10\n'
        '[[boards]]\n'
        'id = "1"\nname = "n"\nurl = "https://x"\n'
        'webhook_envs = ["DISCORD_WEBHOOK_A"]\n',
        encoding="utf-8",
    )
    from cse_bot.config import ConfigError, load_config
    import pytest
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_load_config_accepts_webhook_envs_list(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_A", "https://a")
    monkeypatch.setenv("DISCORD_WEBHOOK_B", "https://b")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://alert")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(
        '[general]\n'
        'log_dir = "logs"\nstate_file = "data/state.json"\n'
        'max_pages = 1\nhttp_timeout_seconds = 5\nhttp_retries = 1\n'
        '[notification]\n'
        'format = "medium"\nself_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"\n'
        '[gemini]\n'
        'api_key_env = "GEMINI_API_KEY"\n'
        'model = "gemini-2.5-flash-lite"\n'
        'timeout_seconds = 10\n'
        '[[boards]]\n'
        'id = "1"\nname = "n"\nurl = "https://x"\n'
        'webhook_envs = ["DISCORD_WEBHOOK_A", "DISCORD_WEBHOOK_B"]\n',
        encoding="utf-8",
    )
    from cse_bot.config import load_config
    cfg = load_config(cfg_path)
    assert cfg.webhook_urls("1") == ["https://a", "https://b"]


def test_load_config_rejects_empty_webhook_envs(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://alert")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(
        '[general]\n'
        'log_dir = "logs"\nstate_file = "data/state.json"\n'
        'max_pages = 1\nhttp_timeout_seconds = 5\nhttp_retries = 1\n'
        '[notification]\n'
        'format = "medium"\nself_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"\n'
        '[gemini]\n'
        'api_key_env = "GEMINI_API_KEY"\n'
        'model = "gemini-2.5-flash-lite"\n'
        'timeout_seconds = 10\n'
        '[[boards]]\n'
        'id = "1"\nname = "n"\nurl = "https://x"\nwebhook_envs = []\n',
        encoding="utf-8",
    )
    from cse_bot.config import ConfigError, load_config
    import pytest
    with pytest.raises(ConfigError):
        load_config(cfg_path)
