from types import SimpleNamespace

from netsync.models import State, ThresholdRule
from netsync.plugins.base import CheckResult
from netsync.rules.engine import RuleSet

device = SimpleNamespace(id=1, groups=[SimpleNamespace(id=10)])


def test_defaults_apply():
    rs = RuleSet([])
    state, out = rs.evaluate(CheckResult("cpu_util", "CPU utilization", value=95, unit="%", output="95%"), device)
    assert state == State.CRIT
    assert "CRIT" in out


def test_explicit_state_wins_over_ok_level():
    rs = RuleSet([])
    cr = CheckResult("if", "Interface Gi0/1", state=State.CRIT, value=1, output="down")
    assert rs.evaluate(cr, device)[0] == State.CRIT


def test_rule_priority_and_regex():
    rules = [
        ThresholdRule(id=1, name="generic", check="storage_used", warn=80, crit=90, priority=100, enabled=True),
        ThresholdRule(id=2, name="backups", check="storage_used", warn=95, crit=98, item_regex="/backup",
                      priority=10, enabled=True),
    ]
    rs = RuleSet(rules)
    assert rs.evaluate(CheckResult("storage_used", "Filesystem /backup", value=92), device)[0] == State.OK
    assert rs.evaluate(CheckResult("storage_used", "Filesystem /", value=92), device)[0] == State.CRIT


def test_below_direction():
    rules = [ThresholdRule(id=1, name="x", check="signal", warn=-70, crit=-80, direction="below",
                           priority=1, enabled=True)]
    rs = RuleSet(rules)
    assert rs.evaluate(CheckResult("signal", "Signal", value=-85), device)[0] == State.CRIT
    assert rs.evaluate(CheckResult("signal", "Signal", value=-60), device)[0] == State.OK
