"""The `check` command: show what GitHub reports, without touching any state."""

from __future__ import annotations

from datetime import timedelta

from gh_notify import github
from gh_notify.config import load_config
from gh_notify.events import KIND_LABELS, Kind, extract_events
from gh_notify.state import iso, utcnow

RECENT = timedelta(days=7)


def run_check() -> int:
    """Fetch once and print every event, newest comment activity from the last week."""
    config = load_config()
    client = github.GitHubClient(lambda: github.token_from_gh(config.gh_path))
    now = utcnow()
    try:
        data = client.fetch_all(iso(now - RECENT))
    except github.GitHubError as exc:
        print(f"error: {exc}")
        return 1

    me = data["viewer"]["login"]
    events = extract_events(data, me, config)
    cutoff = iso(now - RECENT)
    print(f"Signed in as {me}. Poll interval {config.poll_interval}s.")
    for kind in Kind:
        shown = [
            e for e in events if e.kind is kind and (e.created_at or cutoff) >= cutoff
        ]
        print(f"\n{KIND_LABELS[kind]}: {len(shown)}")
        for event in shown:
            who = f" [{event.author}]" if event.author else ""
            when = f" {event.created_at}" if event.created_at else ""
            print(f"  {event.reference} {event.title[:60]}{who}{when}")
            if kind not in (Kind.REVIEW_REQUESTED, Kind.CI_FAILED):
                print(f"      {event.summary}")
    print("\n(Nothing was saved. Comments older than 7 days are hidden.)")
    return 0
