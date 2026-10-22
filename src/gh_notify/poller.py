"""Background polling of GitHub."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from gh_notify.config import Config
from gh_notify.events import Event, Kind, extract_events
from gh_notify.github import AuthError, GitHubClient, GitHubError, RateLimitError
from gh_notify.state import State, utcnow

log = logging.getLogger(__name__)

AUTH_RETRY_S = 300
MIN_RATE_LIMIT_WAIT_S = 60
MAX_BACKOFF_S = 900


@dataclass(frozen=True)
class PollResult:
    """What one successful poll found."""

    new_events: list[Event]
    outstanding_reviews: int
    checked_at: datetime
    login: str


class Poller(threading.Thread):
    """Polls on an interval, backing off on errors, and reports through callbacks."""

    def __init__(
        self,
        client: GitHubClient,
        state: State,
        load_config: Callable[[], Config],
        is_paused: Callable[[], bool],
        on_result: Callable[[PollResult], None],
        on_error: Callable[[str], None],
    ) -> None:
        super().__init__(daemon=True, name="poller")
        self._client = client
        self._state = state
        self._load_config = load_config
        self._is_paused = is_paused
        self._on_result = on_result
        self._on_error = on_error
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._failures = 0

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()

    def poll_now(self) -> None:
        """Skip the current wait and poll straight away."""
        self._wake.set()

    def poll_once(self, config: Config) -> PollResult:
        """Fetch, extract and record one round of events."""
        data = self._client.fetch_all(self._state.since())
        login = data["viewer"]["login"]
        events = extract_events(data, login, config)
        new = self._state.apply(events)
        outstanding = sum(1 for e in events if e.kind is Kind.REVIEW_REQUESTED)
        return PollResult(new, outstanding, utcnow(), login)

    def run(self) -> None:
        while not self._stop_event.is_set():
            config = self._load_config()
            delay = config.poll_interval
            if not self._is_paused():
                delay = self._poll_and_report(config)
            self._wake.wait(delay)
            self._wake.clear()

    def _poll_and_report(self, config: Config) -> float:
        """Poll once, report the outcome, and return how long to wait before the next."""
        try:
            result = self.poll_once(config)
        except AuthError as exc:
            self._on_error(str(exc))
            return AUTH_RETRY_S
        except RateLimitError as exc:
            self._on_error(f"{exc}; waiting")
            return max(exc.retry_after, MIN_RATE_LIMIT_WAIT_S)
        except GitHubError as exc:
            return self._backoff(config, str(exc))
        except Exception as exc:  # a parsing bug must not kill the polling thread
            log.exception("unexpected error while polling")
            return self._backoff(config, f"unexpected error: {exc}")
        self._failures = 0
        self._on_result(result)
        return config.poll_interval

    def _backoff(self, config: Config, message: str) -> float:
        self._failures += 1
        self._on_error(message)
        return min(config.poll_interval * 2**self._failures, MAX_BACKOFF_S)
