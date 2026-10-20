from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from netsync.api.monitoring import problem_episode

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


def sc(minutes, old, new):
    return SimpleNamespace(time=T0 + timedelta(minutes=minutes), old_state=old, new_state=new)


def test_active_problem_spans_warn_to_crit():
    history = [sc(10, 1, 2), sc(5, 0, 1), sc(0, 2, 0)]  # newest first
    episode, started, resolved = problem_episode(history, current_state=2)
    assert [e.new_state for e in episode] == [2, 1]
    assert started == T0 + timedelta(minutes=5)
    assert resolved is None


def test_resolved_problem():
    history = [sc(20, 2, 0), sc(10, 1, 2), sc(5, 0, 1)]
    episode, started, resolved = problem_episode(history, current_state=0)
    assert started == T0 + timedelta(minutes=5)
    assert resolved == T0 + timedelta(minutes=20)
    assert len(episode) == 2


def test_problem_since_first_check():
    # created straight into CRIT (UNKNOWN -> CRIT) and never OK before
    episode, started, resolved = problem_episode([sc(3, 3, 2)], current_state=2)
    assert started == T0 + timedelta(minutes=3) and len(episode) == 1


def test_ok_without_problem_is_not_a_resolution():
    assert problem_episode([sc(1, 3, 0)], current_state=0) == ([], None, None)
