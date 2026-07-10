"""
ParaTracker application configuration.

Config is stored at a platform-appropriate location:
  macOS   : ~/Library/Application Support/ParaTracker/config.json
  Windows : %APPDATA%/ParaTracker/config.json
  Linux   : ~/.config/ParaTracker/config.json

The outputs directory is user-configurable. The SQLite database lives
inside the outputs directory (one DB per outputs folder), making each
outputs folder fully self-contained and portable.

Legacy WormTracker paths (from v1.3.0 and earlier) are auto-migrated to
the new ParaTracker locations on first launch. See _migrate_legacy_*.
"""

import json
import logging
import platform
from pathlib import Path

_APP_NAME = "ParaTracker"

# Prior name used through v1.3.0. Kept only for one-shot migration so
# upgrading users keep their config and job history without manual work.
_LEGACY_APP_NAME = "WormTracker"

_log = logging.getLogger(__name__)


def _config_base_dir() -> Path:
    """Return the platform-appropriate parent directory for the app config folder.

    Does NOT create anything on disk.
    """
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support"
    if system == "Windows":
        import os
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    return Path.home() / ".config"


def get_config_dir() -> Path:
    """Return the app config directory (created if absent).

    Migrates the legacy WormTracker directory in place if the new
    ParaTracker directory does not yet exist. The rename is atomic on
    POSIX and preserves config.json.
    """
    base = _config_base_dir()
    config_dir = base / _APP_NAME
    legacy_dir = base / _LEGACY_APP_NAME
    if not config_dir.exists() and legacy_dir.exists():
        try:
            legacy_dir.rename(config_dir)
            _log.info("Migrated legacy config directory %s -> %s", legacy_dir, config_dir)
        except OSError as exc:
            _log.warning(
                "Failed to migrate legacy config directory %s -> %s: %s; "
                "creating fresh ParaTracker config",
                legacy_dir, config_dir, exc,
            )
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_default_outputs_dir() -> Path:
    return Path.home() / "Documents" / _APP_NAME


def _legacy_default_outputs_dir() -> Path:
    return Path.home() / "Documents" / _LEGACY_APP_NAME


def _is_writable_dir(path: Path) -> bool:
    """Return True if *path* can be created (or already exists) and is writable."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".paratracker_write_test"
        probe.touch()
        probe.unlink()
        return True
    except Exception:
        return False


def _migrate_legacy_outputs_dir(config: dict) -> bool:
    """If the user was still on the legacy default outputs path
    (~/Documents/WormTracker) and no ParaTracker outputs dir exists yet,
    rename it and update the config in place. Returns True if the config
    was mutated.

    A user who set a custom outputs_dir via Settings is never touched.
    """
    legacy = _legacy_default_outputs_dir()
    new = get_default_outputs_dir()
    if config.get("outputs_dir") != str(legacy):
        return False
    if not legacy.exists() or new.exists():
        return False
    try:
        legacy.rename(new)
        config["outputs_dir"] = str(new)
        _log.info("Migrated legacy outputs directory %s -> %s", legacy, new)
        return True
    except OSError as exc:
        _log.warning(
            "Failed to migrate legacy outputs directory %s -> %s: %s; "
            "leaving outputs_dir unchanged",
            legacy, new, exc,
        )
        return False


def load_config() -> dict:
    """Load config from disk, filling in defaults for any missing keys.

    If the stored outputs_dir is not writable (e.g. an external drive that is
    no longer mounted), the default outputs directory is used instead and a
    warning is logged.
    """
    config_file = get_config_dir() / "config.json"
    defaults = {"outputs_dir": str(get_default_outputs_dir()), "model_path": ""}
    if not config_file.exists():
        # Fresh install (or migration case where a legacy dir was renamed
        # but had no config.json). Try the outputs migration once so a user
        # who never opened Settings still keeps their old jobs.
        config = dict(defaults)
        if _migrate_legacy_outputs_dir(config):
            save_config(config)
        return config

    try:
        with open(config_file, encoding="utf-8") as f:
            data = json.load(f)
        config = {**defaults, **data}
    except Exception as exc:
        _log.warning(
            "Failed to load config from %s: %s - using defaults", config_file, exc
        )
        return defaults

    if _migrate_legacy_outputs_dir(config):
        save_config(config)

    outputs_dir = Path(config["outputs_dir"])
    if not _is_writable_dir(outputs_dir):
        _log.warning(
            "Configured outputs_dir %s is not writable - falling back to default %s",
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
