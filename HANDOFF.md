# Handoff notes

Context for picking this up later. Delete once merged and anything useful is in the README.

## State: built, installed, being trialled

The author is living with it for a while to see whether the notifications are useful.
The LaunchAgent is installed and running. Nothing is merged: all work is on `build-app`
(pushed), branched from `notification-spike`, which is branched from `main`.

## What it does

Menu bar app that polls GitHub (token from `gh auth token`) and posts native macOS
notifications for: review requested, comments/reviews on my PRs, replies to my comments,
@mentions, CI failures on my PRs. Bell icon with unread count; menu lists unread items.

## Modules (`src/gh_notify/`)

- `github.py`: GraphQL client. Four separate searches (`QUERIES`), merged by `fetch_all`.
- `events.py`: pure functions, response to `Event` list. Most of the logic and tests.
- `state.py`: `state.json` with seen IDs and unread events; first poll only baselines.
- `poller.py`: background thread, back-off, auth and rate-limit handling.
- `notifier.py`: `desktop-notifier` (UNUserNotificationCenter via rubicon-objc).
- `app.py`: rumps menu bar UI. `config.py`, `paths.py`, `cli.py`, `checker.py`.
- `bundle.py`, `launchagent.py`, `instance.py`: app bundle, LaunchAgent, single-instance lock.

## Decisions and why

- **Native notifications need an app identity.** A bare venv Python has no bundle
  identifier, so macOS drops notifications silently. The mouse-app trick (launcher forks
  Python as a child) does not work: the child has no identity. So `launcher.c` (embedded
  in `bundle.py`) `dlopen`s `libpython` and calls `Py_BytesMain` in its own process.
  Verified: `NSBundle.mainBundle().bundleIdentifier()` returns the bundle ID.
- **Notification permission is per-bundle and only applies to processes started after the
  grant.** Always `gh-notify restart` after allowing it.
- **Click callbacks need a CFRunLoop.** Inside rumps this works. In a plain asyncio script
  you need `rubicon.objc.eventloop.EventLoopPolicy`. (Found in the spike.)
- **Four small queries, not one.** One combined GraphQL query returned HTTP 502. Each
  search alone is fine. A full poll takes about 12s sequentially.
- **First poll baselines silently** (otherwise ~18 alerts at launch). Comments older than
  the baseline never alert (`created_at > started_at`).
- **One comment, one alert.** Event IDs are the comment node ID, so a comment that is both
  a mention and PR feedback alerts once, with the highest-priority kind (`Kind` order).
- **Review requests and CI failures are "stateful"**: they leave the unread list when no
  longer true. Comments stay until clicked or marked read (30 day retention).
- **Bots are detected by GraphQL `__typename == "Bot"`**, not by a login suffix
  (Dependabot's login has no `[bot]` in GraphQL).
- **KeepAlive `SuccessfulExit=false`**: crash restarts, Quit stays quit. A test checks the
  launcher passes exit codes through.
- **`uninstall` keeps the app bundle** so the notification permission survives.

## Verified

- `gh-notify check` against the real account: 11 review requests, 1 failing PR, 1 mention;
  Dependabot filtered. Extraction on a 30-day window found 5 comments and 5 mentions.
- Spike: notifications appear from the signed bundle, clicks open the URL, standalone and
  inside rumps.
- Install via LaunchAgent: running, first poll baselined 18 items, 0 alerts.
- Injected a "new" review request by deleting it from `seen`: it appeared in `unread`, and
  the notification permission error no longer appeared in the log.
- 41 tests pass, `ruff check` clean.

## Not verified (ask the author what they saw)

- That the banner actually appeared and looked right (the agent cannot see the screen).
- The bell badge count and menu layout, click-to-open and mark-read.
- Reply and CI-failure alerts on live data (unit tests only).
- Quit staying quit; Start at login toggle; a real logout/login; sleep and wake.
- What happens when `gh` is signed out (warning triangle), and rate limiting.
- Menu items with identical labels (padded with zero-width spaces; untested visually).

## Known quirks and risks

- The launcher bakes in the Python home and site-packages paths. After `uv tool install
  --reinstall` or a uv Python upgrade, re-run `gh-notify install`.
- `ProcessType=Interactive` and `LSUIElement` are set; there is no Dock icon.
- Search uses `updated:>=` with a 15 minute overlap, capped at 7 days back.
- Only the last 10 comments per conversation, 15 reviews and 20 threads are fetched, so a
  burst on a very busy PR could be missed.
- `rumps` is old (0.4.0) and the icon uses private `_nsapp` access, as in the mouse app.
- The notification icon is a generic one. No custom icon has been made.
- Test bundle in `test_install.py` compiles C and runs Python, so it needs `clang`.

## Ideas

- Run the four searches concurrently to cut poll time.
- Custom app icon; notification actions (Mark read, Open).
- Group notifications per PR; quiet hours.
- Share `panel`, `bundle` and `launchagent` code with `logi-mac-mouse-map` if a third app appears.
- Escalate or re-alert on review requests that stay unread for a day.

## Branches

`main` (scaffold only) < `notification-spike` < `build-app`. No PR opened yet. The agent's
rules block non-draft PRs, so open a draft: `gh pr create --draft --base main --head build-app`.

## Handy commands

```sh
uv run pytest && uv run ruff check .
gh-notify check
uv tool install . --reinstall && gh-notify install
gh-notify restart
tail -f ~/Library/Logs/gh-notify.log
python3 -c "import json;print(json.load(open('$HOME/.config/gh-notify/state.json'))['unread'])"
```
