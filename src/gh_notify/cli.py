"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from gh_notify.launchagent import LaunchAgentError


def _check() -> int:
    from gh_notify.checker import run_check

    return run_check()


def _run() -> int:
    from gh_notify import instance
    from gh_notify.app import run_app

    try:
        lock = instance.acquire()
    except instance.AlreadyRunningError as exc:
        print(exc, file=sys.stderr)
        return 1
    run_app()
    del lock
    return 0


def _install() -> int:
    from gh_notify import bundle, launchagent
    from gh_notify.paths import LOG_PATH

    launcher = launchagent.install()
    print(f"Installed and started LaunchAgent {launchagent.LABEL}")
    print(f"  app:      {bundle.APP_PATH}")
    print(f"  launcher: {launcher}")
    print(f"  plist:    {launchagent.PLIST_PATH}")
    print(f"  log:      {LOG_PATH}")
    print()
    print("On first run macOS asks to allow notifications for GH Notify.")
    print("If it does not, enable it in System Settings > Notifications.")
    return 0


def _uninstall() -> int:
    from gh_notify import launchagent

    launchagent.uninstall()
    print("LaunchAgent removed.")
    return 0


def _restart() -> int:
    from gh_notify import launchagent

    launchagent.restart()
    print("Restarted.")
    return 0


def _status() -> int:
    from gh_notify import launchagent

    print(f"plist installed: {launchagent.is_installed()} ({launchagent.PLIST_PATH})")
    print(f"loaded in launchd: {launchagent.is_loaded()}")
    return 0


COMMANDS = {
    "run": _run,
    "check": _check,
    "install": _install,
    "uninstall": _uninstall,
    "restart": _restart,
    "status": _status,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="gh-notify")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="start the status bar app (default)")
    sub.add_parser("check", help="show what GitHub reports, without changing any state")
    sub.add_parser("install", help="start at login and keep alive (LaunchAgent)")
    sub.add_parser("uninstall", help="remove the LaunchAgent")
    sub.add_parser("restart", help="restart the LaunchAgent copy")
    sub.add_parser("status", help="show LaunchAgent state")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        code = COMMANDS[args.command or "run"]()
    except LaunchAgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = 1
    sys.exit(code)
