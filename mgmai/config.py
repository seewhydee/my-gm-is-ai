from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

APP_NAME = "mgmai"
CONFIG_FILENAME = "config.json"
CREDENTIALS_FILENAME = "credentials.json"
SAVES_DIRNAME = "saves"


# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------


def _get_config_dir() -> Path:
    """Return the platform-appropriate config directory for mgmai.

    Linux:   ~/.config/mgmai
    macOS:   ~/Library/Preferences/mgmai
    Windows: %APPDATA%/mgmai
    """
    return Path(user_config_dir(APP_NAME))


def get_config_dir(config_dir_override: str | Path | None = None) -> Path:
    """Return the config directory, respecting an optional override."""
    if config_dir_override is not None:
        return Path(config_dir_override)
    return _get_config_dir()


def get_config_file(config_dir: str | Path | None = None) -> Path:
    return get_config_dir(config_dir) / CONFIG_FILENAME


def get_credentials_file(config_dir: str | Path | None = None) -> Path:
    return get_config_dir(config_dir) / CREDENTIALS_FILENAME


def get_saves_dir(
    adventure_name: str | None = None,
    config_dir: str | Path | None = None,
) -> Path:
    """Return the saves directory, optionally scoped to an adventure."""
    base = get_config_dir(config_dir) / SAVES_DIRNAME
    if adventure_name:
        return base / adventure_name
    return base


def get_autosave_path(
    adventure_name: str,
    config_dir: str | Path | None = None,
) -> Path:
    return get_saves_dir(adventure_name, config_dir) / "autosave.json"


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------


@dataclass
class AppConfig:
    """Persistent user configuration stored in config.json."""

    model_name: str = "deepseek-v4-flash"
    base_url: str | None = None
    ruling_temperature: float | None = None
    prose_temperature: float | None = None
    adventure_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.model_name:
            d["model_name"] = self.model_name
        if self.base_url is not None:
            d["base_url"] = self.base_url
        if self.ruling_temperature is not None:
            d["ruling_temperature"] = self.ruling_temperature
        if self.prose_temperature is not None:
            d["prose_temperature"] = self.prose_temperature
        if self.adventure_path is not None:
            d["adventure_path"] = self.adventure_path
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        return cls(
            model_name=data.get("model_name", "deepseek-v4-flash"),
            base_url=data.get("base_url"),
            ruling_temperature=data.get("ruling_temperature"),
            prose_temperature=data.get("prose_temperature"),
            adventure_path=data.get("adventure_path"),
        )


def load_app_config(config_dir: str | Path | None = None) -> AppConfig:
    """Load user config from config.json, returning defaults if missing."""
    path = get_config_file(config_dir)
    if not path.is_file():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return AppConfig()
    return AppConfig.from_dict(data)


def save_app_config(
    config: AppConfig,
    config_dir: str | Path | None = None,
) -> None:
    """Write user config to config.json, creating directories as needed."""
    path = get_config_file(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ------------------------------------------------------------------
# Credentials
# ------------------------------------------------------------------


@dataclass
class Credentials:
    """API credentials stored in credentials.json (separate from config for security)."""

    api_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"api_key": self.api_key}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Credentials:
        return cls(api_key=data.get("api_key", ""))


def load_credentials(config_dir: str | Path | None = None) -> Credentials:
    """Load API key from credentials.json, returning empty if missing."""
    path = get_credentials_file(config_dir)
    if not path.is_file():
        return Credentials()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Credentials()
    return Credentials.from_dict(data)


def save_credentials(
    credentials: Credentials,
    config_dir: str | Path | None = None,
) -> None:
    """Write credentials to credentials.json and set mode 0600.

    Creates the config directory if needed.  On platforms that do not
    support ``os.chmod`` the permission step is silently skipped.
    """
    path = get_credentials_file(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(credentials.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


# ------------------------------------------------------------------
# API key resolution
# ------------------------------------------------------------------


def resolve_api_key(
    *,
    cli_arg: str | None = None,
    env_var: str | None = None,
    credentials: Credentials | None = None,
) -> str:
    """Return the first non-empty API key from the given sources.

    Priority: *cli_arg* > *env_var* > *credentials*.
    Returns ``""`` if no key is found.
    """
    for source in (cli_arg, env_var, credentials.api_key if credentials else ""):
        if source:
            return source
    return ""
