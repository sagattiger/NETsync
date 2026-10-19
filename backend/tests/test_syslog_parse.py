from netsync.plugins.builtin.syslog import parse


def test_rfc3164():
    p = parse("<189>Oct 19 10:00:01 core-sw1 %LINK-3-UPDOWN: Interface Gi0/1, changed state to down")
    assert p["pri"] == 189
    assert p["hostname"] == "core-sw1"
    assert p["program"] == "%LINK-3-UPDOWN"
    assert p["message"].startswith("Interface Gi0/1")


def test_rfc3164_with_pid():
    p = parse("<30>Oct  9 22:33:20 fw01 sshd[1234]: Accepted publickey for root")
    assert p["program"] == "sshd"
    assert p["message"] == "Accepted publickey for root"


def test_rfc5424():
    p = parse("<165>1 2026-10-19T10:00:00Z router1 dhcpd 42 ID47 - lease granted")
    assert p == {"pri": 165, "hostname": "router1", "program": "dhcpd", "message": "lease granted"}


def test_garbage():
    assert parse("hello")["message"] == "hello"
