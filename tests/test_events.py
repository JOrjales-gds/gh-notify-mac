from builders import ME, author, ci, comment, item, response

from gh_notify.config import Config
from gh_notify.events import Event, Kind, extract_events, notification_text, snippet


def kinds(events):
    return [e.kind for e in events]


def test_review_request_event():
    events = extract_events(response(review=[item()]), ME, Config())
    assert kinds(events) == [Kind.REVIEW_REQUESTED]
    assert events[0].id == "review:PR_1"
    assert events[0].created_at is None


def test_review_request_from_bot_ignored_but_human_kept():
    bot = item("PR_2", 2, login="dependabot")
    bot["author"] = author("dependabot", bot=True)
    events = extract_events(response(review=[item(), bot]), ME, Config())
    assert [e.id for e in events] == ["review:PR_1"]
    assert (
        len(extract_events(response(review=[bot]), ME, Config(ignore_bots=False))) == 1
    )


def test_draft_review_requests_can_be_excluded():
    draft = item(isDraft=True)
    assert (
        extract_events(response(review=[draft]), ME, Config(include_drafts=False)) == []
    )
    assert len(extract_events(response(review=[draft]), ME, Config())) == 1


def test_ci_failure_only_for_failure_or_error():
    failing = item("PR_1", commits=ci("abc", "FAILURE"))
    erroring = item("PR_2", 2, commits=ci("def", "ERROR"))
    passing = item("PR_3", 3, commits=ci("ghi", "SUCCESS"))
    pending = item("PR_4", 4, commits=ci("jkl", None))
    events = extract_events(
        response(mine=[failing, erroring, passing, pending]), ME, Config()
    )
    assert [e.id for e in events] == ["ci:PR_1:abc", "ci:PR_2:def"]


def test_pr_feedback_ignores_own_comments_and_wrapper_reviews():
    pr = item(
        comments={
            "nodes": [
                comment("c1", "bob", "2026-10-02T00:00:00Z"),
                comment("c2", ME, "x"),
            ]
        },
        reviews={
            "nodes": [
                {
                    "id": "r1",
                    "url": "u",
                    "body": "",
                    "state": "COMMENTED",
                    "submittedAt": "2026-10-02T01:00:00Z",
                    "author": author("bob"),
                },
                {
                    "id": "r2",
                    "url": "u",
                    "body": "",
                    "state": "APPROVED",
                    "submittedAt": "2026-10-02T02:00:00Z",
                    "author": author("bob"),
                },
                {
                    "id": "r3",
                    "url": "u",
                    "body": "",
                    "state": "PENDING",
                    "submittedAt": None,
                    "author": author("bob"),
                },
            ]
        },
        reviewThreads={
            "nodes": [
                {
                    "comments": {
                        "nodes": [comment("t1", "carol", "2026-10-02T03:00:00Z")]
                    }
                }
            ]
        },
    )
    events = extract_events(response(mine=[pr]), ME, Config())
    assert sorted(e.id for e in events) == ["c1", "r2", "t1"]
    assert {e.id: e.summary for e in events}["r2"] == "approved"


def test_bot_comments_ignored_by_default():
    pr = item(
        comments={
            "nodes": [comment("c1", "codecov[bot]", "2026-10-02T00:00:00Z", bot=True)]
        }
    )
    assert extract_events(response(mine=[pr]), ME, Config()) == []
    assert len(extract_events(response(mine=[pr]), ME, Config(ignore_bots=False))) == 1


def test_ignore_authors_is_case_insensitive():
    pr = item(comments={"nodes": [comment("c1", "Bob", "2026-10-02T00:00:00Z")]})
    assert extract_events(response(mine=[pr]), ME, Config(ignore_authors=["bob"])) == []


def test_mention_in_body_and_comment_but_not_lookalikes():
    node = item(
        login="alice",
        body="cc @gillespied please look",
        comments={
            "nodes": [
                comment("c1", "bob", "2026-10-02T00:00:00Z", "ping @Gillespied"),
                comment("c2", "bob", "2026-10-02T00:01:00Z", "ping @gillespied-bot"),
                comment("c3", ME, "2026-10-02T00:02:00Z", "me @gillespied"),
            ]
        },
    )
    events = extract_events(response(mentions=[node]), ME, Config())
    assert sorted(e.id for e in events) == ["c1", "mention:PR_1"]
    assert all(e.kind is Kind.MENTION for e in events)


def test_reply_needs_my_earlier_comment_in_same_conversation():
    node = item(
        comments={
            "nodes": [
                comment("a", "bob", "2026-10-02T00:00:00Z"),
                comment("b", ME, "2026-10-02T01:00:00Z"),
                comment("c", "bob", "2026-10-02T02:00:00Z"),
            ]
        },
        reviewThreads={
            "nodes": [
                {
                    "comments": {
                        "nodes": [comment("t1", "carol", "2026-10-02T03:00:00Z")]
                    }
                },
                {
                    "comments": {
                        "nodes": [
                            comment("t2", ME, "2026-10-02T03:00:00Z"),
                            comment("t3", "carol", "2026-10-02T04:00:00Z"),
                        ]
                    }
                },
            ]
        },
    )
    events = extract_events(response(replies=[node]), ME, Config())
    assert sorted(e.id for e in events) == ["c", "t3"]
    assert all(e.kind is Kind.REPLY for e in events)


def test_one_comment_fitting_several_kinds_alerts_once_with_highest_priority():
    mention = comment("c1", "bob", "2026-10-02T00:00:00Z", "@gillespied thoughts?")
    pr = item(comments={"nodes": [mention]})
    data = response(mine=[pr], mentions=[pr])
    events = extract_events(data, ME, Config())
    assert [(e.id, e.kind) for e in events] == [("c1", Kind.MENTION)]


def test_disabled_kind_falls_through_to_the_next():
    mention = comment("c1", "bob", "2026-10-02T00:00:00Z", "@gillespied thoughts?")
    pr = item(comments={"nodes": [mention]})
    events = extract_events(
        response(mine=[pr], mentions=[pr]), ME, Config(mentions=False)
    )
    assert [(e.id, e.kind) for e in events] == [("c1", Kind.PR_FEEDBACK)]


def test_deleted_author_is_ghost():
    pr = item(
        comments={
            "nodes": [{**comment("c1", "x", "2026-10-02T00:00:00Z"), "author": None}]
        }
    )
    events = extract_events(response(mine=[pr]), ME, Config())
    assert events[0].author == "ghost"


def test_snippet_takes_first_line_and_truncates():
    assert snippet("\n\n  first   line \nsecond") == "first line"
    assert snippet("x" * 300).endswith("…") and len(snippet("x" * 300)) == 120
    assert snippet(None) == ""


def test_event_round_trips_through_dict():
    event = extract_events(response(review=[item()]), ME, Config())[0]
    assert Event.from_dict(event.to_dict()) == event


def test_notification_text():
    event = extract_events(response(review=[item()]), ME, Config())[0]
    title, message = notification_text(event)
    assert title == "Review requested"
    assert message.startswith("o/r#1 Add a thing")
    assert "alice" in message
