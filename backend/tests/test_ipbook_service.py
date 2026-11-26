"""IP Book pinging: down after 3 misses, which IPs alert, neutral names for sensitive rows."""

from datetime import UTC, datetime
from types import SimpleNamespace as NS

from netsync.models import State
from netsync.notify_rules import problem_type
from netsync.plugins.builtin.ipbook import health, service

NOW = datetime(2026, 11, 26, tzinfo=UTC)


def test_down_after_three_misses():
    s = health.next_state(None, False, None, NOW)
    s = health.next_state(s, False, None, NOW)
    assert s["state"] == "unknown" and s["misses"] == 2
    s = health.next_state(s, False, None, NOW)
    assert s["state"] == "down"
    s = health.next_state(s, True, 1.234, NOW)
    assert s == {"misses": 0, "state": "up", "rtt": 1.23, "at": NOW.isoformat()}
    up = health.next_state(s, False, None, NOW)
    assert up["state"] == "up" and up["misses"] == 1  # one miss doesn't turn an up IP red


def test_effective_alert():
    r = NS(alert_when_down=None)
    assert service.effective_alert(r, [False, True]) is True
    assert service.effective_alert(r, []) is False
    assert service.effective_alert(NS(alert_when_down=False), [True]) is False
    assert service.effective_alert(NS(alert_when_down=True), []) is True


def test_check_names():
    r = NS(id=12, sensitive=False, values={"service": {"name": "Wiki", "logo": None}, "hostname": "app01.example.test"})
    c = service.check_for(r, "10.0.0.5", {"state": "down"})
    assert c.check == "ipbook_ping" and c.kind == "ipbook_ip" and c.index == "12:10.0.0.5"
    assert c.name == "Wiki 10.0.0.5" and c.state == State.CRIT
    assert service.check_for(r, "10.0.0.5", {"state": "up", "rtt": 2.0}).state == State.OK
    assert service.check_for(r, "10.0.0.5", {"state": "unknown"}).state == State.UNKNOWN
    host = NS(id=13, sensitive=False, values={"hostname": "app02.example.test"})
    assert service.check_for(host, "10.0.0.6", {"state": "down"}).name == "app02.example.test 10.0.0.6"


def test_sensitive_check_is_neutral():
    r = NS(id=7, sensitive=True, values={"service": {"name": "Vault", "logo": None}, "hostname": "vault01.example.test"})
    c = service.check_for(r, "10.0.0.9", {"state": "down", "rtt": None})
    text = f"{c.name} {c.output}"
    assert c.name == "IP Book: sensitive entry #7 address 1" and c.output == "down"
    assert "10.0.0.9" not in text and "Vault" not in text and "vault01" not in text


def test_alert_off_removes_service():
    assert service.services_to_remove({"1:10.0.0.5", "2:10.0.0.6"}, {"2:10.0.0.6"}) == {"1:10.0.0.5"}


def test_notification_problem_type():
    assert problem_type("ipbook_ping") == "ipbook"


def test_sensitive_row_with_two_ips_has_two_services():
    r = NS(id=7, sensitive=True, values={})
    a = service.check_for(r, "10.0.0.9", {"state": "down"}, 1)
    b = service.check_for(r, "10.0.0.10", {"state": "up"}, 2)
    assert a.name != b.name and a.name == "IP Book: sensitive entry #7 address 1"
    assert "10.0.0" not in a.name + b.name


def test_targets_from_service_books_and_ip_books():
    books = {1: NS(id=1, kind="service", title="Stack", alert_when_down=True),
             2: NS(id=2, kind="ip", title="Servers", alert_when_down=False)}
    rows = [NS(id=5, book_id=1, sensitive=False, alert_when_down=None, values={"hostname": "app01.example.test", "ip_lan": "10.0.0.5"}),
            NS(id=6, book_id=1, sensitive=True, alert_when_down=False, values={"ip_lan": "10.0.0.6, 10.0.0.7"})]
    addrs = [NS(book_id=2, ip="10.0.0.9", values={"addr_hostname": "sw01.example.test"}, reserved=False, alert_when_down=True),
             NS(book_id=2, ip="10.0.0.10", values={}, reserved=True, alert_when_down=None),
             NS(book_id=2, ip="10.0.0.11", values={"addr_info": "printer"}, reserved=False, alert_when_down=None)]
    t = {x.key: x for x in service.targets(rows, books, addrs, {"ip_lan"})}
    assert set(t) == {"5:10.0.0.5", "6:10.0.0.6", "6:10.0.0.7", "a2:10.0.0.9", "a2:10.0.0.11"}  # reserved: not pinged
    assert t["5:10.0.0.5"].alert is True and t["6:10.0.0.6"].alert is False  # book switch / row override
    assert t["a2:10.0.0.9"].alert is True and t["a2:10.0.0.11"].alert is False
    assert t["6:10.0.0.7"].check({"state": "down"}).name == "IP Book: sensitive entry #6 address 2"
    assert t["a2:10.0.0.9"].check({"state": "down"}).name == "sw01.example.test 10.0.0.9"
    assert t["a2:10.0.0.11"].check({"state": "down"}).name == "10.0.0.11 (Servers)"
