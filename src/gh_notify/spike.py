"""Spike: can desktop-notifier post a native notification with a click handler?"""

from __future__ import annotations

import asyncio
import sys
import webbrowser

from desktop_notifier import DesktopNotifier, DesktopNotifierSync

URL = "https://github.com/pulls/review-requested"
WAIT_S = 30


def open_url() -> None:
    print("CLICKED: opening", URL, flush=True)
    webbrowser.open(URL)


async def _terminal() -> None:
    notifier = DesktopNotifier(app_name="GH Notify Spike")
    print("authorised:", await notifier.request_authorisation(), flush=True)
    await notifier.send(
        title="Review requested",
        message="co-cddo/example #123 Add a thing",
        on_clicked=open_url,
        on_dispatched=lambda: print("dispatched", flush=True),
        on_dismissed=lambda: print("dismissed", flush=True),
    )
    print(f"Waiting {WAIT_S}s for a click...", flush=True)
    await asyncio.sleep(WAIT_S)


def terminal() -> None:
    # Click callbacks need a CFRunLoop, which the default asyncio loop does not run.
    from rubicon.objc.eventloop import EventLoopPolicy

    asyncio.set_event_loop_policy(EventLoopPolicy())
    asyncio.run(_terminal())


def in_rumps() -> None:
    import rumps

    notifier = DesktopNotifierSync(app_name="GH Notify Spike")

    def send(_sender) -> None:
        notifier.send(
            title="Review requested",
            message="co-cddo/example #123 Add a thing",
            on_clicked=open_url,
            on_dispatched=lambda: print("dispatched", flush=True),
        )

    app = rumps.App("spike", title="spike", quit_button="Quit")
    app.menu = [rumps.MenuItem("Send test notification", callback=send)]

    def auto(timer: rumps.Timer) -> None:
        timer.stop()
        send(None)

    rumps.Timer(auto, 3).start()
    print("authorised:", notifier.request_authorisation(), flush=True)
    app.run()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "terminal"
    {"terminal": terminal, "rumps": in_rumps}[mode]()
