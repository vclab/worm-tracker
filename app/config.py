"""
WormTracker application configuration.

Config is stored at a platform-appropriate location:
  macOS   : ~/Library/Application Support/WormTracker/config.json
  Windows : %APPDATA%/WormTracker/config.json
  Linux   : ~/.config/WormTracker/config.json

The outputs directory is user-configurable. The SQLite database lives
inside the outputs directory (one DB per outputs folder), making each
outputs folder fully self-contained and portable.
"""

import json
import platform
from pathlib import Path

_APP_NAME = "WormTracker"


def get_config_dir() -> Path:
    """Return the platform-appropriate app config directory (created if absent)."""
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        import os
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path.home() / ".config"
    config_dir = base / _APP_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_default_outputs_dir() -> Path:
    return Path.home() / "Documents" / _APP_NAME


def load_config() -> dict:
    """Load config from disk, filling in defaults for any missing keys."""
    config_file = get_config_dir() / "config.json"
    defaults = {"outputs_dir": str(get_default_outputs_dir())}
    if not config_file.exists():
        return defaults
    try:
        with open(config_file) as f:
            data = json.load(f)
        return {**defaults, **data}
    except Exception:
        return defaults


def save_config(config: dict) -> None:
    """Persist config to disk."""
    config_file = get_config_dir() / "config.json"
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)
