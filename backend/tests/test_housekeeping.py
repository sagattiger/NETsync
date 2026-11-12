"""Housekeeping: settings rules, policy parsing and which data tier a graph reads."""

from datetime import timedelta

import pytest

from netsync.housekeeping import DEFAULTS, RETENTION, SETTINGS, _days_of, validate
from netsync.metrics_query import RANGES, source_for


def test_defaults_are_valid_and_complete():
    validate(DEFAULTS)
    keys = {f["key"] for f in SETTINGS}
    assert keys == set(DEFAULTS)
    assert set(RETENTION.values()) <= keys
    for f in SETTINGS:
        assert f["min"] <= DEFAULTS[f["key"]] <= f["max"], f["key"]


@pytest.mark.parametrize(("change", "message"), [
    ({"metrics_raw_days": 400, "metrics_hourly_days": 365}, "every poll"),
    ({"metrics_hourly_days": 2000, "metrics_daily_days": 1825}, "every poll"),
    ({"compress_after_days": 30}, "Compression"),
    ({"probe_beats_days": 500, "probe_hourly_days": 400}, "Probe"),
])
def test_invalid_combinations(change, message):
    with pytest.raises(ValueError, match=message):
        validate({**DEFAULTS, **change})


@pytest.mark.parametrize(("text", "days"), [
    ("30 days", 30), ("90 days", 90), ("1 mon", 30), ("1 year", 365), ("5 years", 1825), ("", None), (None, None),
])
def test_days_of_timescale_intervals(text, days):
    assert _days_of(text) == days


def test_graph_ranges_pick_the_right_tier():
    tiers = {name: source_for(bucket) for name, (_, bucket) in RANGES.items()}
    assert tiers == {"1h": "metrics", "6h": "metrics", "24h": "metrics", "7d": "metrics",
                     "30d": "metrics_hourly", "1y": "metrics_daily"}
    assert source_for(timedelta(days=1)) == "metrics_daily"  # daily uptime override


def test_raw_retention_covers_raw_graphs():
    """Graphs up to 7 days read raw data: the shortest allowed raw retention must cover them."""
    lo = next(f["min"] for f in SETTINGS if f["key"] == "metrics_raw_days")
    longest_raw = max(span for span, bucket in RANGES.values() if source_for(bucket) == "metrics")
    assert timedelta(days=lo) >= longest_raw
