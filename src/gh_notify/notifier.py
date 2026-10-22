"""Native macOS notifications."""

from __future__ import annotations

import logging
import webbrowser
from collections.abc import Callable

from Foundation import NSBundle

from gh_notify.events import Event, notification_text

log = logging.getLogger(__name__)


def has_app_identity() -> bool:
    """Whether this process runs inside an app bundle. Without one, macOS drops notifications."""
    return NSBundle.mainBundle().bundleIdentifier() is not None


class Notifier:
    """Posts notifications that open a URL when clicked."""

    def __init__(self, on_opened: Callable[[str], None]) -> None:
        from desktop_notifier import DesktopNotifierSync

        self._notifier = DesktopNotifierSync(app_name="GH Notify")
        self._on_opened = on_opened

    def authorise(self) -> bool:
        """Ask macOS for permission. Shows the system prompt the first time."""
        try:
            return bool(self._notifier.request_authorisation())
        except Exception:
            log.exception("could not request notification permission")
            return False

    def notify_event(self, event: Event) -> None:
        title, message = notification_text(event)
        self.notify(
            title, message, event.url, thread=event.reference, event_id=event.id
        )

    def notify(
        self,
        title: str,
        message: str,
        url: str | None = None,
        thread: str | None = None,
        event_id: str | None = None,
    ) -> None:
        def clicked() -> None:
            if url:
                webbrowser.open(url)
            if event_id:
                self._on_opened(event_id)

        try:
            self._notifier.send(
                title=title, message=message, on_clicked=clicked, thread=thread
            )
        except Exception:
            log.exception("could not send notification")
