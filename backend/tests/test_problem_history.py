"""Problems over time: open count per bucket, opened and resolved."""

from datetime import UTC, datetime, timedelta

from netsync.api.monitoring import problem_series

T0 = datetime(2026, 11, 15, 0, 0, tzinfo=UTC)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def test_series_follows_each_service():
    # service 1 already CRIT; 2 and 3 open, 2 escalates (not new), 1 recovers, 4 opens late
    changes = [(at(5), 2, 2), (at(7), 3, 1), (at(8), 3, 2), (at(20), 1, 0), (at(50), 4, 3)]
    s = problem_series({1: 2}, changes, T0, at(59), 900)
    assert [b["open"] for b in s] == [3, 2, 2, 3]
    assert [b["new"] for b in s] == [2, 0, 0, 1] and [b["resolved"] for b in s] == [0, 1, 0, 0]


def test_new_services_settling_to_ok_are_not_resolutions():
    s = problem_series({}, [(at(1), 9, 0), (at(2), 8, 0)], T0, at(29), 600)
    assert [b["open"] for b in s] == [0, 0, 0] and sum(b["resolved"] for b in s) == 0


def test_general_settings_validation():
    import pytest

    from netsync.general import DEFAULTS, validate

    validate({**DEFAULTS})
    for bad in ({"accent_color": "pink"}, {"logo": "data:text/html;base64,PGI+"}, {"autodiscovery_networks": "10.0.0.0/16"},
                {"autodiscovery_networks": "not-a-net"}, {"autodiscovery": True, "autodiscovery_networks": ""}):
        with pytest.raises(ValueError):
            validate({**DEFAULTS, **bad})
    validate({**DEFAULTS, "accent_color": "#3b82f6", "autodiscovery": True, "autodiscovery_networks": "10.128.100.0/24\n10.128.101.0/24"})
