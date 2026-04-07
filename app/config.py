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


def _is_writable_dir(path: Path) -> bool:
    """Return True if *path* can be created (or already exists) and is writable."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".wormtracker_write_test"
        probe.touch()
        probe.unlink()
        return True
    except Exception:
        return False


def load_config() -> dict:
    """Load config from disk, filling in defaults for any missing keys.

    If the stored outputs_dir is not writable (e.g. an external drive that is
    no longer mounted), the default outputs directory is used instead and a
    warning is logged.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    config_file = get_config_dir() / "config.json"
    defaults = {"outputs_dir": str(get_default_outputs_dir())}
    if not config_file.exists():
        return defaults
    try:
        with open(config_file, encoding="utf-8") as f:
            data = json.load(f)
        config = {**defaults, **data}
    except Exception as exc:
        _log.warning(
            "Failed to load config from %s: %s — using defaults", config_file, exc
        )
        return defaults

    outputs_dir = Path(config["outputs_dir"])
    if not _is_writable_dir(outputs_dir):
        _log.warning(
            "Configured outputs_dir %s is not writable — falling back to default %s",
            outputs_dir,
            defaults["outputs_dir"],
        )
        config["outputs_dir"] = defaults["outputs_dir"]

    return config


def save_config(config: dict) -> None:
    """Persist config to disk."""
    config_file = get_config_dir() / "config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
