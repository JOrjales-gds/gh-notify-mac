"""Ensure only one copy of the app runs at a time."""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import IO

from gh_notify.paths import LOCK_PATH


class AlreadyRunningError(Exception):
    """Raised when another copy of the app holds the lock."""


def acquire(path: Path = LOCK_PATH) -> IO[str]:
    """Take an exclusive lock, returning the open file. Keep it referenced while running.

    The OS drops the lock when the process exits, even after a crash.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise AlreadyRunningError("GH Notify is already running.") from exc
    return handle
