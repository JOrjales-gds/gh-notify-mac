"""Load user settings from TOML."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from gh_notify.paths import CONFIG_PATH

MIN_POLL_INTERVAL_S = 30
DEFAULT_POLL_INTERVAL_S = 90
EVENT_FLAGS = ("review_requested", "pr_feedback", "ci_failures", "mentions", "replies")


@dataclass
class Config:
    """User settings. Every event type can be switched off."""

    poll_interval: int = DEFAULT_POLL_INTERVAL_S
    review_requested: bool = True
    pr_feedback: bool = True
    ci_failures: bool = True
    mentions: bool = True
    replies: bool = True
    include_drafts: bool = True
    ignore_bots: bool = True
    ignore_authors: list[str] = field(default_factory=list)
    gh_path: str = ""
    paused: bool = False


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read the config file, ignoring missing, malformed or wrongly typed values."""
    try:
        data = tomllib.loads(path.read_text())
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return Config()

    config = Config()
    interval = data.get("poll_interval")
    if isinstance(interval, int) and not isinstance(interval, bool):
        config.poll_interval = max(interval, MIN_POLL_INTERVAL_S)
    for name in (*EVENT_FLAGS, "include_drafts", "ignore_bots", "paused"):
        value = data.get(name)
        if isinstance(value, bool):
            setattr(config, name, value)
    authors = data.get("ignore_authors")
    if isinstance(authors, list) and all(isinstance(a, str) for a in authors):
        config.ignore_authors = [a.lower() for a in authors]
    gh_path = data.get("gh_path")
    if isinstance(gh_path, str):
        config.gh_path = gh_path
    return config
