"""Home page widgets, map widget options, sites input."""

import pytest
from pydantic import ValidationError

from netsync.api.dashboards import HOME_WIDGETS, DashboardIn, Widget, dump_widget
from netsync.api.sites import SiteIn


def test_default_home_layout_is_valid():
    d = DashboardIn(name="Home", widgets=HOME_WIDGETS)
    assert [w.type for w in d.widgets][:3] == ["hero", "strip", "map"]


def test_map_widget_options_round_trip():
    w = Widget(id="m", type="map", center=[-46.8, -23.5], zoom=30, map_style="night", hide_sites=True, height="xl")
    stored = dump_widget(w)
    assert stored["center"] == [-46.8, -23.5] and stored["zoom"] == 30 and stored["hide_sites"] is True
    assert "hide_sites" not in dump_widget(Widget(id="m2", type="map"))
    with pytest.raises(ValidationError):
        Widget(id="x", type="map", center=[1.0])
    with pytest.raises(ValidationError):
        Widget(id="x", type="map", map_style="neon")


def test_site_input_checks_coordinates_and_kind():
    assert SiteIn(name="Osasco DC", kind="datacenter", lat=-23.53, lon=-46.79).kind == "datacenter"
    for bad in ({"lat": 91}, {"lon": -181}, {"kind": "office"}):
        with pytest.raises(ValidationError):
            SiteIn(name="x", **bad)
