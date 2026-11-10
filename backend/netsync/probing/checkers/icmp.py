"""ICMP ping (unprivileged sockets): RTT min/avg/max, jitter and loss. FQDNs are resolved every round."""

from netsync.models import State
from netsync.plugins.base import CheckResult
from netsync.probing.base import Checker, KindConfig, ProbeSpec, Result, error_message, register


class IcmpConfig(KindConfig):
    pass


def ping_result(target: str, h) -> Result:
    """Result for one icmplib Host (pure, unit tested). Keeps the Ping RTT / Ping loss services."""
    loss = h.packet_loss * 100
    metrics = {"ping_loss": loss}
    if h.is_alive:
        metrics.update(ping_min=h.min_rtt, ping_avg=h.avg_rtt, ping_max=h.max_rtt, ping_jitter=h.jitter)
        out = f"rtt avg {h.avg_rtt:.1f} ms (min {h.min_rtt:.1f}, max {h.max_rtt:.1f}), loss {loss:.0f}%"
        checks = [CheckResult("ping_rtt", "Ping RTT", value=h.avg_rtt, unit="ms", output=out),
                  CheckResult("ping_loss", "Ping loss", value=loss, unit="%", output=f"{loss:.0f}% packet loss")]
        msg = f"{h.avg_rtt:.1f} ms" + (f", {loss:.0f}% loss" if loss else "")
        return Result(True, h.avg_rtt, State.OK, msg, metrics, checks)
    checks = [CheckResult("ping_rtt", "Ping RTT", state=State.CRIT, output="host unreachable"),
              CheckResult("ping_loss", "Ping loss", state=State.CRIT, value=100, unit="%", output="100% packet loss")]
    return Result(False, None, State.CRIT, "no reply", metrics, checks)


@register
class IcmpChecker(Checker):
    kind = "icmp"
    label = "Ping (ICMP)"
    Config = IcmpConfig
    concurrency = 50

    async def check(self, spec: ProbeSpec) -> Result:
        from icmplib import async_ping

        try:
            h = await async_ping(spec.target, count=spec.count, interval=0.5, timeout=2, privileged=False)
        except Exception as e:
            msg = "name resolution failed" if type(e).__name__ == "NameLookupError" else error_message(e)
            return Result(False, None, State.CRIT, msg, {"ping_loss": 100.0}, [
                CheckResult("ping_rtt", "Ping RTT", state=State.CRIT, output=msg),
                CheckResult("ping_loss", "Ping loss", state=State.CRIT, value=100, unit="%", output="100% packet loss"),
            ])
        return ping_result(spec.target, h)

