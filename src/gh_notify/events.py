"""Turn GitHub's response into a list of events. Pure functions, no I/O."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from gh_notify.config import Config

SNIPPET_LENGTH = 120
GHOST = "ghost"  # GitHub shows deleted accounts as "ghost"


class Kind(StrEnum):
    """What happened. Order here is also the priority when one comment fits several."""

    REVIEW_REQUESTED = "review_requested"
    CI_FAILED = "ci_failed"
    MENTION = "mention"
    PR_FEEDBACK = "pr_feedback"
    REPLY = "reply"


KIND_LABELS = {
    Kind.REVIEW_REQUESTED: "Review requested",
    Kind.CI_FAILED: "Checks failed on your PR",
    Kind.MENTION: "Mentioned you",
    Kind.PR_FEEDBACK: "Activity on your PR",
    Kind.REPLY: "Reply to you",
}

# These describe a current situation, so they disappear once it is no longer true.
STATEFUL_KINDS = frozenset({Kind.REVIEW_REQUESTED, Kind.CI_FAILED})


@dataclass(frozen=True)
class Event:
    """Something worth telling the user about."""

    id: str
    kind: Kind
    repo: str
    number: int
    title: str
    url: str
    author: str
    summary: str
    created_at: str | None = None  # None for events that describe a current state
    is_bot: bool = False

    @property
    def reference(self) -> str:
        return f"{self.repo}#{self.number}"

    def to_dict(self) -> dict:
        return {**self.__dict__, "kind": self.kind.value}

    @classmethod
    def from_dict(cls, data: dict) -> Event:
        fields = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        fields["kind"] = Kind(fields["kind"])
        return cls(**fields)


def notification_text(event: Event) -> tuple[str, str]:
    """Return the (title, message) for a native notification."""
    title = KIND_LABELS[event.kind]
    detail = (
        f"{event.author}: {event.summary}"
        if event.author and event.summary
        else (event.summary or event.author)
    )
    return title, f"{event.reference} {event.title}\n{detail}".rstrip()


def snippet(body: str | None) -> str:
    """First non-empty line of a comment, shortened."""
    for line in (body or "").splitlines():
        line = " ".join(line.split())
        if line:
            return (
                line
                if len(line) <= SNIPPET_LENGTH
                else line[: SNIPPET_LENGTH - 1] + "…"
            )
    return ""


def extract_events(data: dict, me: str, config: Config) -> list[Event]:
    """Return every event the response describes, whether or not it was seen before."""
    candidates: list[Event] = []
    if config.review_requested:
        candidates += _review_requests(data, me, config)
    if config.ci_failures:
        candidates += _ci_failures(data)
    if config.mentions:
        candidates += _mentions(data, me)
    if config.pr_feedback:
        candidates += _pr_feedback(data, me)
    if config.replies:
        candidates += _replies(data, me)

    unique: dict[str, Event] = {}
    for event in candidates:
        if not _ignored(event, config):
            unique.setdefault(
                event.id, event
            )  # earlier candidates have higher priority
    return list(unique.values())


def _ignored(event: Event, config: Config) -> bool:
    return event.author.lower() in config.ignore_authors or (
        config.ignore_bots and event.is_bot
    )


def _login(node: dict) -> str:
    return (node.get("author") or {}).get("login") or GHOST


def _is_bot(node: dict) -> bool:
    author = node.get("author") or {}
    return author.get("__typename") == "Bot" or (author.get("login") or "").endswith(
        "[bot]"
    )


def _nodes(data: dict, key: str) -> Iterator[dict]:
    yield from (n for n in data.get(key, {}).get("nodes", []) if n)


def _event(
    node: dict,
    kind: Kind,
    event_id: str,
    url: str,
    author: str,
    summary: str,
    created_at: str | None = None,
    is_bot: bool = False,
) -> Event:
    return Event(
        id=event_id,
        kind=kind,
        repo=node["repository"]["nameWithOwner"],
        number=node["number"],
        title=node["title"],
        url=url,
        author=author,
        summary=summary,
        created_at=created_at,
        is_bot=is_bot,
    )


def _review_requests(data: dict, me: str, config: Config) -> list[Event]:
    events = []
    for node in _nodes(data, "review"):
        if node.get("isDraft") and not config.include_drafts:
            continue
        author = _login(node)
        if author != me:
            events.append(
                _event(
                    node,
                    Kind.REVIEW_REQUESTED,
                    f"review:{node['id']}",
                    node["url"],
                    author,
                    "wants your review",
                    is_bot=_is_bot(node),
                )
            )
    return events


def _ci_failures(data: dict) -> list[Event]:
    events = []
    for node in _nodes(data, "mine"):
        for commit_node in (node.get("commits") or {}).get("nodes", []):
            commit = commit_node["commit"]
            state = (commit.get("statusCheckRollup") or {}).get("state")
            if state in ("FAILURE", "ERROR"):
                events.append(
                    _event(
                        node,
                        Kind.CI_FAILED,
                        f"ci:{node['id']}:{commit['oid']}",
                        node["url"],
                        "",
                        "checks failed",
                    )
                )
    return events


def _comment_groups(node: dict) -> list[list[dict]]:
    """Conversations on an item: its plain comments, then each review thread."""
    groups = [(node.get("comments") or {}).get("nodes", [])]
    for thread in (node.get("reviewThreads") or {}).get("nodes", []):
        groups.append((thread.get("comments") or {}).get("nodes", []))
    return groups


def _review_comments(node: dict) -> Iterator[dict]:
    """Submitted reviews, shaped like comments. Empty 'commented' wrappers are skipped."""
    for review in (node.get("reviews") or {}).get("nodes", []):
        body = (review.get("body") or "").strip()
        if not review.get("submittedAt"):
            continue
        if review["state"] == "COMMENTED" and not body:
            continue
        verb = {"APPROVED": "approved", "CHANGES_REQUESTED": "requested changes"}.get(
            review["state"]
        )
        yield {
            "id": review["id"],
            "url": review["url"],
            "body": body or verb or "reviewed",
            "createdAt": review["submittedAt"],
            "author": review["author"],
        }


def _all_comments(node: dict) -> Iterator[dict]:
    for group in _comment_groups(node):
        yield from group
    yield from _review_comments(node)


def _comment_event(node: dict, kind: Kind, comment: dict) -> Event:
    return _event(
        node,
        kind,
        comment["id"],
        comment["url"],
        _login(comment),
        snippet(comment["body"]),
        comment["createdAt"],
        _is_bot(comment),
    )


def _pr_feedback(data: dict, me: str) -> list[Event]:
    return [
        _comment_event(node, Kind.PR_FEEDBACK, comment)
        for node in _nodes(data, "mine")
        for comment in _all_comments(node)
        if _login(comment) != me
    ]


def _mention_pattern(me: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w-])@{re.escape(me)}(?![\w-])", re.IGNORECASE)


def _mentions(data: dict, me: str) -> list[Event]:
    pattern = _mention_pattern(me)
    events = []
    for node in _nodes(data, "mentions"):
        if _login(node) != me and pattern.search(node.get("body") or ""):
            events.append(
                _event(
                    node,
                    Kind.MENTION,
                    f"mention:{node['id']}",
                    node["url"],
                    _login(node),
                    snippet(node["body"]),
                    node["createdAt"],
                    _is_bot(node),
                )
            )
        events += [
            _comment_event(node, Kind.MENTION, comment)
            for comment in _all_comments(node)
            if _login(comment) != me and pattern.search(comment.get("body") or "")
        ]
    return events


def _replies(data: dict, me: str) -> list[Event]:
    """Comments by others that come after one of my comments in the same conversation."""
    events = []
    for node in _nodes(data, "replies"):
        for group in _comment_groups(node):
            mine = [c["createdAt"] for c in group if _login(c) == me]
            if not mine:
                continue
            first = min(mine)
            events += [
                _comment_event(node, Kind.REPLY, comment)
                for comment in group
                if _login(comment) != me and comment["createdAt"] > first
            ]
    return events
