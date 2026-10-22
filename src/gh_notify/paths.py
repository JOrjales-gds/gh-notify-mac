"""Filesystem locations used by the app."""

from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "gh-notify"
CONFIG_PATH = CONFIG_DIR / "config.toml"
STATE_PATH = CONFIG_DIR / "state.json"
LOCK_PATH = CONFIG_DIR / "app.lock"
LOG_PATH = Path.home() / "Library" / "Logs" / "gh-notify.log"
