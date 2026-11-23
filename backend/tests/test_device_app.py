"""The main application shown on a device (logo + name, set by hand)."""

import pytest
from pydantic import ValidationError

from netsync.api.schemas import DeviceOut, DeviceUpdate


def test_app_logo_and_name_validation():
    u = DeviceUpdate(app_logo="di:observium", app_name="  Observium   SNMP ")
    assert (u.app_logo, u.app_name) == ("di:observium", "Observium SNMP")
    assert DeviceUpdate(app_logo="https://example.com/logo.svg").app_logo == "https://example.com/logo.svg"
    assert DeviceUpdate(app_logo="", app_name="").model_dump(exclude_unset=True) == {"app_logo": None, "app_name": None}
    for bad in ("http://example.com/x.png", "javascript:alert(1)", "di:Bad Slug", "https://x.com/a\"b.png"):
        with pytest.raises(ValidationError):
            DeviceUpdate(app_logo=bad)


def test_app_fields_in_device_output():
    assert {"app_logo", "app_name"} <= set(DeviceOut.model_fields)
