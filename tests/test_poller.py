import threading

import pytest
from builders import ME, item, response

from gh_notify.config import Config
from gh_notify.github import AuthError, GitHubError, RateLimitError
from gh_notify.poller import AUTH_RETRY_S, MAX_BACKOFF_S, Poller
from gh_notify.state import State


class FakeClient:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)

    def fetch_all(self, since):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_poller(tmp_path, client, results, errors):
    return Poller(
        client=client,
        state=State(tmp_path / "s.json"),
        load_config=Config,
        is_paused=lambda: False,
        on_result=results.append,
        on_error=errors.append,
    )


def test_poll_once_counts_outstanding_reviews_and_baselines(tmp_path):
    data = response(review=[item("PR_1"), item("PR_2", 2)])
    poller = make_poller(tmp_path, FakeClient(data, data), [], [])
    first = poller.poll_once(Config())
    assert (first.outstanding_reviews, first.new_events, first.login) == (2, [], ME)
    assert poller.poll_once(Config()).new_events == []


def test_new_review_request_reported_on_second_poll(tmp_path):
    poller = make_poller(
        tmp_path, FakeClient(response(), response(review=[item("PR_9", 9)])), [], []
    )
    poller.poll_once(Config())
    assert [e.id for e in poller.poll_once(Config()).new_events] == ["review:PR_9"]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AuthError("signed out"), AUTH_RETRY_S),
        (RateLimitError("limit", 10), 60),
        (RateLimitError("limit", 500), 500),
        (GitHubError("boom"), 180),
        (ValueError("bug"), 180),
    ],
)
def test_error_delays(tmp_path, error, expected):
    errors = []
    poller = make_poller(tmp_path, FakeClient(error), [], errors)
    assert poller._poll_and_report(Config()) == expected
    assert len(errors) == 1


def test_backoff_grows_then_resets_after_success(tmp_path):
    results, errors = [], []
    poller = make_poller(
        tmp_path, FakeClient(*[GitHubError("x")] * 6, response()), results, errors
    )
    delays = [poller._poll_and_report(Config()) for _ in range(6)]
    assert delays == [180, 360, 720, MAX_BACKOFF_S, MAX_BACKOFF_S, MAX_BACKOFF_S]
    assert poller._poll_and_report(Config()) == 90
    assert len(results) == 1


def test_stop_ends_the_thread_promptly(tmp_path):
    poller = make_poller(tmp_path, FakeClient(response()), [], [])
    poller.start()
    done = threading.Event()
    threading.Thread(target=lambda: (poller.stop(), poller.join(5), done.set())).start()
    assert done.wait(6)
    assert not poller.is_alive()
