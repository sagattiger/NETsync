"""Settings → Charts: the chart preference is checked field by field."""

import pytest
from fastapi import HTTPException

from netsync.api.auth import chart_preferences


def test_chart_preferences_keep_valid_fields_and_clamp():
    out = chart_preferences({"palette": "tableau", "glow": 0, "line_width": 9, "fill_opacity": -1, "fill": "solid",
                             "style": "line", "grid": False, "smooth": 1, "colors": ["#112233"], "evil": "x"})
    assert out == {"palette": "tableau", "glow": False, "line_width": 4.0, "fill_opacity": 0.0, "fill": "solid",
                   "style": "line", "grid": False, "smooth": True, "colors": ["#112233"]}
    assert chart_preferences({"palette": "nope", "fill": "x"}) == {}


@pytest.mark.parametrize("bad", ["x", {"colors": ["red"]}, {"line_width": "wide"}])
def test_chart_preferences_refuse_bad_values(bad):
    with pytest.raises(HTTPException):
        chart_preferences(bad)
