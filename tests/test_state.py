from datetime import UTC, datetime, timedelta

from gh_notify.events import Event, Kind
from gh_notify.state import State, iso

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def make(event_id, kind=Kind.PR_FEEDBACK, created=None):
    return Event(event_id, kind, "o/r", 1, "t", "http://x", "bob", "hi", created)


def test_first_poll_records_without_alerting(tmp_path):
    state = State(tmp_path / "s.json")
    assert state.apply([make("a"), make("review:1", Kind.REVIEW_REQUESTED)], T0) == []
    assert state.unread() == []
    assert state.initialised


def test_new_event_after_baseline_alerts_once(tmp_path):
    state = State(tmp_path / "s.json")
    state.apply([make("a")], T0)
    later = T0 + timedelta(minutes=2)
    created = iso(T0 + timedelta(minutes=1))
    new = state.apply([make("a"), make("b", created=created)], later)
    assert [e.id for e in new] == ["b"]
    assert state.apply([make("a"), make("b", created=created)], later) == []
    assert [e.id for e in state.unread()] == ["b"]


def test_old_comment_on_newly_visible_item_is_recorded_but_not_alerted(tmp_path):
    state = State(tmp_path / "s.json")
    state.apply([], T0)
    old = make("old", created=iso(T0 - timedelta(days=3)))
    assert state.apply([old], T0 + timedelta(minutes=1)) == []
    assert state.apply([old], T0 + timedelta(minutes=2)) == []
    assert state.unread() == []


def test_state_events_without_timestamp_alert_when_new(tmp_path):
    state = State(tmp_path / "s.json")
    state.apply([], T0)
    new = state.apply(
        [make("review:1", Kind.REVIEW_REQUESTED)], T0 + timedelta(minutes=1)
    )
    assert [e.id for e in new] == ["review:1"]


def test_stateful_unread_clears_when_no_longer_live(tmp_path):
    state = State(tmp_path / "s.json")
    state.apply([], T0)
    review = make("review:1", Kind.REVIEW_REQUESTED)
    comment = make("c", created=iso(T0 + timedelta(minutes=1)))
    state.apply([review, comment], T0 + timedelta(minutes=2))
    assert len(state.unread()) == 2
    state.apply([comment], T0 + timedelta(minutes=4))
    assert [e.id for e in state.unread()] == ["c"]


def test_mark_read_and_persistence(tmp_path):
    path = tmp_path / "s.json"
    state = State(path)
    state.apply([], T0)
    created = iso(T0 + timedelta(minutes=1))
    state.apply(
        [make("a", created=created), make("b", created=created)],
        T0 + timedelta(minutes=2),
    )
    state.mark_read("a")
    reloaded = State(path)
    assert [e.id for e in reloaded.unread()] == ["b"]
    assert reloaded.apply([make("a", created=created)], T0 + timedelta(minutes=3)) == []
    reloaded.mark_all_read()
    assert State(path).unread() == []


def test_since_is_capped_and_defaults_to_a_week(tmp_path):
    state = State(tmp_path / "s.json")
    assert state.since(T0) == iso(T0 - timedelta(days=7))
    state.apply([], T0)
    assert state.since(T0 + timedelta(hours=1)) == iso(T0 - timedelta(minutes=15))
    assert state.since(T0 + timedelta(days=20)) == iso(T0 + timedelta(days=13))


def test_corrupt_state_file_starts_fresh(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    assert not State(path).initialised
