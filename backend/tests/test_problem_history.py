"""Problems over time: open count per bucket, opened and resolved."""

from datetime import UTC, datetime, timedelta

from netsync.api.monitoring import problem_series

T0 = datetime(2026, 11, 15, 0, 0, tzinfo=UTC)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def test_series_counts_open_new_and_resolved():
    changes = [(at(5), 0, 2), (at(7), 0, 1), (at(8), 1, 2), (at(20), 2, 0), (at(50), 0, 3)]
    s = problem_series(1, changes, T0, at(59), 900)  # 15-minute buckets, one problem already open
    assert [b["open"] for b in s] == [3, 2, 2, 3]
    assert [b["new"] for b in s] == [2, 0, 0, 1] and [b["resolved"] for b in s] == [0, 1, 0, 0]
    assert s[0]["peak"] == 3 and s[1]["peak"] == 3  # still 3 open when the second bucket starts; WARN -> CRIT is not new


def test_series_never_goes_negative_and_fills_empty_buckets():
    s = problem_series(0, [(at(1), 2, 0)], T0, at(29), 600)
    assert [b["open"] for b in s] == [0, 0, 0] and s[0]["resolved"] == 1


def test_general_settings_validation():
    import pytest

    from netsync.general import DEFAULTS, validate

    validate({**DEFAULTS})
    for bad in ({"accent_color": "pink"}, {"logo": "data:text/html;base64,PGI+"}, {"autodiscovery_networks": "10.0.0.0/16"},
                {"autodiscovery_networks": "not-a-net"}, {"autodiscovery": True, "autodiscovery_networks": ""}):
        with pytest.raises(ValueError):
            validate({**DEFAULTS, **bad})
    validate({**DEFAULTS, "accent_color": "#3b82f6", "autodiscovery": True, "autodiscovery_networks": "10.128.100.0/24\n10.128.101.0/24"})
