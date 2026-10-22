"""Talk to GitHub's GraphQL API using the token from the gh CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

GRAPHQL_URL = "https://api.github.com/graphql"
REQUEST_TIMEOUT_S = 30
GH_SEARCH_PATHS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")

COMMENT_FIELDS = "id url body createdAt author { login __typename }"
THREAD_FIELDS = f"""
    id number title url createdAt body
    repository {{ nameWithOwner }}
    author {{ login __typename }}
    comments(last: 10) {{ nodes {{ {COMMENT_FIELDS} }} }}
"""
PR_FIELDS = f"""
    isDraft
    reviews(last: 15) {{ nodes {{ id url body state submittedAt author {{ login __typename }} }} }}
    reviewThreads(last: 20) {{
        nodes {{ comments(last: 10) {{ nodes {{ {COMMENT_FIELDS} }} }} }}
    }}
    commits(last: 1) {{ nodes {{ commit {{ oid statusCheckRollup {{ state }} }} }} }}
"""


def _search(name: str, first: int, selection: str) -> str:
    return (
        f"query(${name}: String!) {{ viewer {{ login }} "
        f"{name}: search(query: ${name}, type: ISSUE, first: {first}) {{ nodes {{ {selection} }} }} }}"
    )


# One request per search keeps each one light; GitHub returns 502 for a single big query.
QUERIES = {
    "review": _search(
        "review", 50, f"... on PullRequest {{ {THREAD_FIELDS} isDraft }}"
    ),
    "mine": _search(
        "mine", 30, f"... on PullRequest {{ {THREAD_FIELDS} {PR_FIELDS} }}"
    ),
    "mentions": _search(
        "mentions",
        30,
        f"... on PullRequest {{ {THREAD_FIELDS} {PR_FIELDS} }} ... on Issue {{ {THREAD_FIELDS} }}",
    ),
    "replies": _search(
        "replies",
        30,
        f"... on PullRequest {{ {THREAD_FIELDS} {PR_FIELDS} }} ... on Issue {{ {THREAD_FIELDS} }}",
    ),
}
RETRY_DELAY_S = 2.0


class GitHubError(Exception):
    """A request failed in a way that is worth retrying later."""


class AuthError(GitHubError):
    """The token is missing or was rejected."""


class RateLimitError(GitHubError):
    """GitHub asked us to slow down."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def build_variables(since: str) -> dict[str, str]:
    """Search strings for each query. `since` is an ISO timestamp."""
    return {
        "review": "is:pr is:open review-requested:@me archived:false",
        "mine": "is:pr is:open author:@me archived:false",
        "mentions": f"mentions:@me updated:>={since} archived:false",
        "replies": f"commenter:@me -author:@me updated:>={since} archived:false",
    }


def find_gh(configured: str = "") -> str:
    """Locate the gh executable. launchd's PATH is minimal, so check common places."""
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("gh")
    if found:
        return found
    for directory in GH_SEARCH_PATHS:
        candidate = Path(directory) / "gh"
        if candidate.is_file():
            return str(candidate)
    raise AuthError("gh CLI not found. Install it and run 'gh auth login'.")


def token_from_gh(gh_path: str = "") -> str:
    """Ask the gh CLI for its current token."""
    try:
        result = subprocess.run(
            [find_gh(gh_path), "auth", "token"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitHubError("gh auth token timed out") from exc
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise AuthError("gh is not signed in. Run 'gh auth login'.")
    return token


class GitHubClient:
    """Minimal GraphQL client. Fetches the token lazily and refreshes it after a 401."""

    def __init__(self, token_provider: Callable[[], str]) -> None:
        self._token_provider = token_provider
        self._token: str | None = None

    def graphql(self, query: str, variables: dict) -> dict:
        """Run a query and return its `data`.

        Retries once with a fresh token on 401, and once after a pause on other
        transient errors. Rate limits are not retried here.
        """
        try:
            return self._post(query, variables)
        except AuthError:
            self._token = None
            return self._post(query, variables)
        except RateLimitError:
            raise
        except GitHubError:
            time.sleep(RETRY_DELAY_S)
            return self._post(query, variables)

    def fetch_all(self, since: str) -> dict:
        """Run every search and merge the results into one dict keyed by search name."""
        variables = build_variables(since)
        merged: dict = {}
        for name, query in QUERIES.items():
            part = self.graphql(query, {name: variables[name]})
            merged["viewer"] = part["viewer"]
            merged[name] = part[name]
        return merged

    def _post(self, query: str, variables: dict) -> dict:
        if self._token is None:
            self._token = self._token_provider()
        request = urllib.request.Request(
            GRAPHQL_URL,
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers={
                "Authorization": f"bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "gh-notify",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            raise _error_from_http(exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubError(f"network error: {exc}") from exc
        return _data_or_raise(payload)


def _error_from_http(exc: urllib.error.HTTPError) -> GitHubError:
    if exc.code == 401:
        return AuthError("GitHub rejected the token. Run 'gh auth login'.")
    retry_after = exc.headers.get("Retry-After")
    remaining = exc.headers.get("X-RateLimit-Remaining")
    if exc.code in (403, 429) and (retry_after or remaining == "0"):
        wait = float(retry_after) if retry_after else 300.0
        return RateLimitError("GitHub rate limit reached", wait)
    return GitHubError(f"GitHub returned HTTP {exc.code}")


def _data_or_raise(payload: dict) -> dict:
    errors = payload.get("errors") or []
    data = payload.get("data")
    if any(e.get("type") == "RATE_LIMITED" for e in errors):
        raise RateLimitError("GitHub rate limit reached", 300.0)
    if data is None:
        message = "; ".join(e.get("message", "unknown error") for e in errors)
        raise GitHubError(f"GraphQL error: {message or 'no data returned'}")
    return data
