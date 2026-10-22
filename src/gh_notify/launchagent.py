"""Install the app as a macOS LaunchAgent so it starts at login and is kept alive."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from gh_notify import bundle
from gh_notify.paths import LOG_PATH

LABEL = "com.gillespied.gh-notify"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


class LaunchAgentError(Exception):
    """Raised when the LaunchAgent cannot be installed or removed."""


def build_plist(arguments: list[str], log_path: Path = LOG_PATH) -> dict:
    """Build the LaunchAgent definition.

    KeepAlive only restarts after a non-zero exit, so choosing Quit from the menu
    (exit code 0) stays quit until the next login.
    """
    return {
        "Label": LABEL,
        "ProgramArguments": arguments,
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }


def is_installed(path: Path = PLIST_PATH) -> bool:
    """Whether the LaunchAgent plist exists."""
    return path.exists()


def is_loaded() -> bool:
    """Whether launchd currently has the job loaded."""
    return _launchctl("print", _service_target(), check=False).returncode == 0


def write_plist(path: Path = PLIST_PATH) -> Path:
    """Build the app bundle and write the plist. Does not start the job."""
    try:
        launcher = bundle.build_bundle()
        runtime = bundle.current_runtime()
    except bundle.BundleError as exc:
        raise LaunchAgentError(str(exc)) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    arguments = bundle.program_arguments(launcher, runtime, "run")
    path.write_bytes(plistlib.dumps(build_plist(arguments)))
    return launcher


def remove_plist(path: Path = PLIST_PATH) -> None:
    """Delete the plist so the app no longer starts at login."""
    path.unlink(missing_ok=True)


def install() -> Path:
    """Write the plist and load it into launchd now, replacing any loaded copy."""
    launcher = write_plist()
    if is_loaded():
        _launchctl("bootout", _service_target())
    _launchctl("bootstrap", _domain(), str(PLIST_PATH))
    return launcher


def restart() -> None:
    """Restart the loaded job, for example to pick up a reinstall."""
    if not is_loaded():
        raise LaunchAgentError("not loaded; run 'gh-notify install' first")
    _launchctl("kickstart", "-k", _service_target())


def uninstall() -> None:
    """Stop the loaded job, if any, and delete the plist.

    The app bundle is kept so its notification permission survives a reinstall.
    """
    if is_loaded():
        _launchctl("bootout", _service_target())
    remove_plist()


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _service_target() -> str:
    return f"{_domain()}/{LABEL}"


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["launchctl", *args], check=False, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise LaunchAgentError(f"launchctl {args[0]} failed: {result.stderr.strip()}")
    return result
