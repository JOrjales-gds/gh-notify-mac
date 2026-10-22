"""Remember what has been seen and what is still unread, on disk."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gh_notify.events import STATEFUL_KINDS, Event
from gh_notify.paths import STATE_PATH

log = logging.getLogger(__name__)

FRESH_WINDOW = timedelta(days=30)  # older comments never alert
SEARCH_WINDOW = timedelta(days=7)  # furthest back an 'updated since' search looks
SEEN_RETENTION = timedelta(days=120)
UNREAD_RETENTION = timedelta(days=30)


def iso(moment: datetime) -> str:
    """Format like GitHub does, so strings compare in time order."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow() -> datetime:
    return datetime.now(UTC)


class State:
    """Thread-safe store of seen event IDs and unread events."""

    def __init__(self, path: Path = STATE_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self.initialised = False
        self.started_at = ""
        self.last_success: str | None = None
        self._seen: dict[str, str] = {}
        self._unread: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text())
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError):
            log.warning("state file unreadable; starting fresh")
            return
        self.initialised = bool(data.get("initialised"))
        self.started_at = data.get("started_at", "")
        self.last_success = data.get("last_success")
        self._seen = dict(data.get("seen", {}))
        self._unread = dict(data.get("unread", {}))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "initialised": self.initialised,
            "started_at": self.started_at,
            "last_success": self.last_success,
            "seen": self._seen,
            "unread": self._unread,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=1))
        os.replace(tmp, self._path)

    def since(self, now: datetime | None = None) -> str:
        """Timestamp to use for 'updated since' searches."""
        now = now or utcnow()
        floor = now - SEARCH_WINDOW
        if self.last_success:
            last = datetime.strptime(self.last_success, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=UTC
            )
            return iso(max(last - timedelta(minutes=15), floor))
        return iso(floor)

    def apply(self, events: list[Event], now: datetime | None = None) -> list[Event]:
        """Record a poll's events and return the ones that are new and worth alerting.

        The first ever poll only records what exists, so you are not flooded at launch.
        """
        now = now or utcnow()
        stamp = iso(now)
        with self._lock:
            if not self.initialised:
                self.initialised = True
                self.started_at = stamp
                self._seen = {event.id: stamp for event in events}
                self._unread = {}
                self.last_success = stamp
                self._save()
                return []

            cutoff = max(self.started_at, iso(now - FRESH_WINDOW))
            new = []
            for event in events:
                if event.id in self._seen:
                    continue
                self._seen[event.id] = stamp
                if event.created_at is None or event.created_at > cutoff:
                    new.append(event)
                    self._unread[event.id] = {**event.to_dict(), "added_at": stamp}

            live = {e.id for e in events if e.kind in STATEFUL_KINDS}
            self._unread = {
                key: item
                for key, item in self._unread.items()
                if (item["kind"] not in STATEFUL_KINDS or key in live)
                and item["added_at"] > iso(now - UNREAD_RETENTION)
            }
            self._seen = {
                k: v for k, v in self._seen.items() if v > iso(now - SEEN_RETENTION)
            }
            self.last_success = stamp
            self._save()
            return new

    def unread(self) -> list[Event]:
        """Unread events, newest first."""
        with self._lock:
            items = sorted(
                self._unread.values(), key=lambda item: item["added_at"], reverse=True
            )
            return [Event.from_dict(item) for item in items]

    def mark_read(self, event_id: str) -> None:
        with self._lock:
            if self._unread.pop(event_id, None) is not None:
                self._save()

    def mark_all_read(self) -> None:
        with self._lock:
            self._unread = {}
            self._save()
