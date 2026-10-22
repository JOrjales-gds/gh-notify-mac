"""Helpers that build small GitHub-shaped responses for tests."""

ME = "gillespied"


def author(login, bot=False):
    return {"login": login, "__typename": "Bot" if bot else "User"}


def comment(cid, login, created, body="hello", bot=False):
    return {
        "id": cid,
        "url": f"https://github.com/o/r/pull/1#{cid}",
        "body": body,
        "createdAt": created,
        "author": author(login, bot),
    }


def item(item_id="PR_1", number=1, login="alice", **extra):
    return {
        "id": item_id,
        "number": number,
        "title": "Add a thing",
        "url": f"https://github.com/o/r/pull/{number}",
        "createdAt": "2026-10-01T00:00:00Z",
        "body": "",
        "repository": {"nameWithOwner": "o/r"},
        "author": author(login),
        "comments": {"nodes": []},
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "commits": {"nodes": []},
        "isDraft": False,
        **extra,
    }


def response(review=(), mine=(), mentions=(), replies=()):
    return {
        "viewer": {"login": ME},
        "review": {"nodes": list(review)},
        "mine": {"nodes": list(mine)},
        "mentions": {"nodes": list(mentions)},
        "replies": {"nodes": list(replies)},
    }


def ci(oid, state):
    return {"nodes": [{"commit": {"oid": oid, "statusCheckRollup": {"state": state}}}]}
