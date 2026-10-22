"""Status bar application."""

from __future__ import annotations

import logging
import queue
import threading
import webbrowser
from datetime import datetime

import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSImage

from gh_notify import launchagent
from gh_notify.config import Config, load_config
from gh_notify.events import KIND_LABELS, Event, Kind
from gh_notify.github import GitHubClient, token_from_gh
from gh_notify.notifier import Notifier, has_app_identity
from gh_notify.poller import Poller, PollResult
from gh_notify.state import State

log = logging.getLogger(__name__)

APP_NAME = "GH Notify"
REVIEW_QUEUE_URL = "https://github.com/pulls/review-requested"
UI_TICK_S = 1.0
MAX_INDIVIDUAL_NOTIFICATIONS = 3
MAX_ITEMS_PER_GROUP = 8
TITLE_WIDTH = 70

ICON_IDLE = "bell"
ICON_UNREAD = "bell.badge.fill"
ICON_PAUSED = "pause.circle"
ICON_ERROR = "exclamationmark.triangle"

GROUP_ORDER = (
    Kind.REVIEW_REQUESTED,
    Kind.MENTION,
    Kind.PR_FEEDBACK,
    Kind.REPLY,
    Kind.CI_FAILED,
)


def _symbol(name: str) -> NSImage | None:
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, APP_NAME)
    if image is not None:
        image.setTemplate_(True)
    return image


def clip(text: str, width: int = TITLE_WIDTH) -> str:
    """Shorten text for a menu item."""
    return text if len(text) <= width else text[: width - 1] + "…"


def item_label(event: Event) -> str:
    """One-line menu label for an event."""
    if event.kind is Kind.REVIEW_REQUESTED:
        return clip(f"{event.reference} {event.title} ({event.author})")
    if event.kind is Kind.CI_FAILED:
        return clip(f"{event.reference} {event.title}")
    return clip(f"{event.reference} {event.author}: {event.summary}")


class GhNotifyApp(rumps.App):
    """Menu bar app that watches GitHub and posts native notifications."""

    def __init__(self) -> None:
        super().__init__(APP_NAME, title=None, quit_button=None)
        self.config: Config = load_config()
        self.state = State()
        self._lock = threading.Lock()
        self._paused = self.config.paused
        self._error: str | None = None
        self._last_checked: datetime | None = None
        self._outstanding = 0
        self._incoming: queue.Queue[Event] = queue.Queue()
        self._dirty = threading.Event()
        self._dirty.set()
        self._current_icon: tuple[str, str] | None = None
        self._has_identity = has_app_identity()

        self.notifier = Notifier(on_opened=self._on_opened)
        self.poller = Poller(
            client=GitHubClient(lambda: token_from_gh(load_config().gh_path)),
            state=self.state,
            load_config=load_config,
            is_paused=lambda: self._paused,
            on_result=self._on_result,
            on_error=self._on_error,
        )
        self._tick_timer = rumps.Timer(self._tick, UI_TICK_S)

    def run(self, **options) -> None:  # type: ignore[override]
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
        if not self._has_identity:
            log.warning(
                "not running inside the app bundle; notifications will not show"
            )
        elif not self.notifier.authorise():
            log.warning("notifications are not allowed; enable them in System Settings")
        self.poller.start()
        self._tick_timer.start()
        super().run(**options)

    # --- poller callbacks (background thread) ---------------------------------

    def _on_result(self, result: PollResult) -> None:
        with self._lock:
            self._error = None
            self._last_checked = result.checked_at
            self._outstanding = result.outstanding_reviews
        for event in result.new_events:
            self._incoming.put(event)
        self._dirty.set()

    def _on_error(self, message: str) -> None:
        log.warning("poll failed: %s", message)
        with self._lock:
            self._error = message
        self._dirty.set()

    def _on_opened(self, event_id: str) -> None:
        self.state.mark_read(event_id)
        self._dirty.set()

    # --- UI (main thread) --------------------------------------------------------

    def _tick(self, _timer=None) -> None:
        self._send_pending_notifications()
        if self._dirty.is_set():
            self._dirty.clear()
            self._rebuild()

    def _send_pending_notifications(self) -> None:
        events = []
        while not self._incoming.empty():
            events.append(self._incoming.get_nowait())
        for event in events[:MAX_INDIVIDUAL_NOTIFICATIONS]:
            self.notifier.notify_event(event)
        extra = len(events) - MAX_INDIVIDUAL_NOTIFICATIONS
        if extra > 0:
            self.notifier.notify("GitHub", f"{extra} more new items", REVIEW_QUEUE_URL)

    def _rebuild(self) -> None:
        unread = self.state.unread()
        with self._lock:
            error, paused = self._error, self._paused
            outstanding, checked = self._outstanding, self._last_checked

        items: list = [self._status_item(error, paused, checked)]
        if not self._has_identity:
            items.append(rumps.MenuItem("⚠ Notifications off: run 'gh-notify install'"))
        items.append(None)
        items += self._unread_items(unread)
        items += [
            None,
            rumps.MenuItem(
                "Mark all read", callback=self._mark_all_read if unread else None
            ),
            rumps.MenuItem(
                f"Review queue ({outstanding})" if outstanding else "Review queue",
                callback=lambda _: webbrowser.open(REVIEW_QUEUE_URL),
            ),
            rumps.MenuItem("Check now", callback=lambda _: self.poller.poll_now()),
            rumps.MenuItem("Send test notification", callback=self._send_test),
            self._toggle("Pause", paused, self._toggle_pause),
            self._toggle(
                "Start at login", launchagent.is_installed(), self._toggle_login
            ),
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]
        self.menu.clear()
        self.menu.update(items)

        if error:
            symbol = ICON_ERROR
        elif paused:
            symbol = ICON_PAUSED
        else:
            symbol = ICON_UNREAD if unread else ICON_IDLE
        self._set_icon(symbol, f" {len(unread)}" if unread else "")

    @staticmethod
    def _status_item(error: str | None, paused: bool, checked: datetime | None):
        if error:
            return rumps.MenuItem(clip(f"⚠ {error}"))
        if paused:
            return rumps.MenuItem("Paused")
        if checked:
            return rumps.MenuItem(f"Checked at {checked.astimezone():%H:%M}")
        return rumps.MenuItem("Checking…")

    @staticmethod
    def _toggle(title: str, on: bool, callback) -> rumps.MenuItem:
        item = rumps.MenuItem(title, callback=callback)
        item.state = on
        return item

    def _unread_items(self, unread: list[Event]) -> list:
        if not unread:
            return [rumps.MenuItem("Nothing new")]
        items: list = []
        for kind in GROUP_ORDER:
            group = [e for e in unread if e.kind is kind]
            if not group:
                continue
            items.append(rumps.MenuItem(f"{KIND_LABELS[kind]} ({len(group)})"))
            for event in group[:MAX_ITEMS_PER_GROUP]:
                # Titles are dict keys in rumps, so pad duplicates with invisible characters.
                label = item_label(event) + "\u200b" * len(items)
                items.append(rumps.MenuItem(label, callback=self._open_callback(event)))
            if len(group) > MAX_ITEMS_PER_GROUP:
                items.append(
                    rumps.MenuItem(f"…and {len(group) - MAX_ITEMS_PER_GROUP} more")
                )
        return items

    def _open_callback(self, event: Event):
        def callback(_sender) -> None:
            webbrowser.open(event.url)
            self._on_opened(event.id)

        return callback

    def _set_icon(self, symbol: str, title: str) -> None:
        if self._current_icon == (symbol, title):
            return
        status_item = getattr(getattr(self, "_nsapp", None), "nsstatusitem", None)
        if status_item is None:
            self._dirty.set()  # status bar not created yet; try again next tick
            return
        button = status_item.button()
        image = _symbol(symbol)
        button.setImage_(image)
        button.setTitle_(title or ("" if image else APP_NAME))
        self._current_icon = (symbol, title)

    def _send_test(self, _sender) -> None:
        self.notifier.notify(
            "Test notification",
            "If you can read this, GH Notify can reach you. Click to open GitHub.",
            "https://github.com/notifications",
        )

    def _mark_all_read(self, _sender) -> None:
        self.state.mark_all_read()
        self._dirty.set()

    def _toggle_pause(self, _sender) -> None:
        with self._lock:
            self._paused = not self._paused
        if not self._paused:
            self.poller.poll_now()
        self._dirty.set()

    def _toggle_login(self, _sender) -> None:
        """Add or remove the LaunchAgent plist; it takes effect from the next login."""
        try:
            if launchagent.is_installed():
                launchagent.remove_plist()
                self.notifier.notify(APP_NAME, "Start at login is off.")
            else:
                launchagent.write_plist()
                self.notifier.notify(APP_NAME, "Will start at next login.")
        except launchagent.LaunchAgentError as exc:
            self.notifier.notify(APP_NAME, f"Could not change start at login: {exc}")
        self._dirty.set()

    def _quit(self, _sender) -> None:
        self.poller.stop()
        rumps.quit_application()


def run_app() -> None:
    GhNotifyApp().run()
