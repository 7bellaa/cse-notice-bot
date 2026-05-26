"""Load and validate runtime configuration from TOML + environment."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from cse_bot.models import BoardConfig

VALID_FORMATS: tuple[str, ...] = ("minimal", "medium", "detailed")


class ConfigError(Exception):
    """Raised on any configuration validation error."""


@dataclass(frozen=True)
class GeneralConfig:
    log_dir: str
    state_file: str
    max_pages: int
    http_timeout_seconds: float
    http_retries: int


@dataclass(frozen=True)
class NotificationConfig:
    format: Literal["minimal", "medium", "detailed"]
    self_alert_webhook_env: str


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str
    model: str
    timeout_seconds: float


@dataclass(frozen=True)
class CalendarConfig:
    enabled: bool
    output_dir: str
    site_url: str
    months_in_png: int
    font_path: str | None


@dataclass(frozen=True)
class Config:
    general: GeneralConfig
    notification: NotificationConfig
    gemini: GeminiConfig
    calendar: CalendarConfig
    boards: list[BoardConfig]
    _webhook_urls: dict[str, list[str]]
    alert_webhook_url: str

    def webhook_urls(self, board_id: str) -> list[str]:
        try:
            return self._webhook_urls[board_id]
        except KeyError as e:
            raise ConfigError(f"no webhook resolved for board {board_id}") from e

    def all_webhook_urls(self) -> list[str]:
        """Return every distinct webhook URL across all boards (preserves order)."""
        seen: set[str] = set()
        out: list[str] = []
        for urls in self._webhook_urls.values():
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    out.append(url)
        return out


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))

    general = _load_general(raw)
    notification = _load_notification(raw)
    gemini = _load_gemini(raw)
    calendar = _load_calendar(raw)
    boards = _load_boards(raw)

    webhook_urls: dict[str, list[str]] = {}
    for b in boards:
        if not b.enabled:
            continue
        urls: list[str] = []
        for env_name in b.webhook_envs:
            url = os.environ.get(env_name)
            if not url:
                raise ConfigError(
                    f"environment variable {env_name} is required for board {b.id}"
                )
            urls.append(url)
        webhook_urls[b.id] = urls

    alert_env = notification.self_alert_webhook_env
    alert_url = os.environ.get(alert_env)
    if not alert_url:
        raise ConfigError(f"environment variable {alert_env} is required (alert webhook)")

    return Config(
        general=general,
        notification=notification,
        gemini=gemini,
        calendar=calendar,
        boards=boards,
        _webhook_urls=webhook_urls,
        alert_webhook_url=alert_url,
    )


def _load_general(raw: dict[str, Any]) -> GeneralConfig:
    g: dict[str, Any] = raw.get("general") or {}
    try:
        return GeneralConfig(
            log_dir=str(g["log_dir"]),
            state_file=str(g["state_file"]),
            max_pages=int(g["max_pages"]),
            http_timeout_seconds=float(g["http_timeout_seconds"]),
            http_retries=int(g["http_retries"]),
        )
    except KeyError as e:
        raise ConfigError(f"missing [general] key: {e.args[0]}") from e


def _load_notification(raw: dict[str, Any]) -> NotificationConfig:
    n: dict[str, Any] = raw.get("notification") or {}
    fmt = str(n.get("format", ""))
    if fmt not in VALID_FORMATS:
        raise ConfigError(
            f"invalid notification.format={fmt!r}; expected one of {VALID_FORMATS}"
        )
    alert = str(n.get("self_alert_webhook_env", ""))
    if not alert:
        raise ConfigError("notification.self_alert_webhook_env is required")
    return NotificationConfig(format=fmt, self_alert_webhook_env=alert)  # type: ignore[arg-type]


def _load_boards(raw: dict[str, Any]) -> list[BoardConfig]:
    items: list[Any] = raw.get("boards") or []
    if not items:
        raise ConfigError("at least one [[boards]] entry is required")
    boards: list[BoardConfig] = []
    for i, b in enumerate(items):
        try:
            envs = b["webhook_envs"]
        except KeyError as e:
            raise ConfigError(f"[[boards]] index {i}: missing key {e.args[0]}") from e
        if not isinstance(envs, list) or not all(isinstance(x, str) for x in envs):
            raise ConfigError(f"[[boards]] index {i}: webhook_envs must be a list of strings")
        if not envs:
            raise ConfigError(f"[[boards]] index {i}: webhook_envs must not be empty")
        try:
            boards.append(
                BoardConfig(
                    id=str(b["id"]),
                    name=str(b["name"]),
                    url=str(b["url"]),
                    webhook_envs=list(envs),
                    enabled=bool(b.get("enabled", True)),
                )
            )
        except KeyError as e:
            raise ConfigError(f"[[boards]] index {i}: missing key {e.args[0]}") from e
    return boards


def _load_calendar(raw: dict[str, Any]) -> CalendarConfig:
    # Missing [calendar] section → disabled by default (backward compatible).
    section = raw.get("calendar")
    if section is None:
        return CalendarConfig(
            enabled=False,
            output_dir="docs/calendar",
            site_url="",
            months_in_png=2,
            font_path=None,
        )
    c: dict[str, Any] = section
    enabled = bool(c.get("enabled", True))
    output_dir = str(c.get("output_dir", "docs/calendar"))
    site_url = str(c.get("site_url", "")).rstrip("/")
    if enabled and not site_url:
        raise ConfigError("[calendar].site_url is required when calendar.enabled = true")
    months_in_png = int(c.get("months_in_png", 2))
    if months_in_png < 1 or months_in_png > 6:
        raise ConfigError("[calendar].months_in_png must be between 1 and 6")
    font_path_raw = c.get("font_path")
    font_path = str(font_path_raw) if font_path_raw else None
    return CalendarConfig(
        enabled=enabled,
        output_dir=output_dir,
        site_url=site_url,
        months_in_png=months_in_png,
        font_path=font_path,
    )


def _load_gemini(raw: dict[str, Any]) -> GeminiConfig:
    g: dict[str, Any] = raw.get("gemini") or {}
    if not g:
        raise ConfigError("[gemini] section is required")
    try:
        api_key_env = str(g["api_key_env"])
        model = str(g["model"])
        timeout = float(g["timeout_seconds"])
    except KeyError as e:
        raise ConfigError(f"missing [gemini] key: {e.args[0]}") from e
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise ConfigError(f"environment variable {api_key_env} is required (gemini)")
    return GeminiConfig(api_key=api_key, model=model, timeout_seconds=timeout)
