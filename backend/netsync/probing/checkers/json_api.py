"""JSON API monitoring: an HTTP(S) request plus assertions on the JSON response (all must pass).

Paths use dot/bracket notation: ``data.items[0].status``, ``meta["x.y"]``, ``$.count`` ("$" is optional)."""

import asyncio
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from netsync.models import State
from netsync.probing.base import ProbeSpec, Result, register, short
from netsync.probing.checkers.http import HttpChecker, HttpConfig, fetch, http_error

Op = Literal["==", "!=", "<", "<=", ">", ">=", "contains", "not contains", "regex", "exists", "not exists"]
_TOKEN = re.compile(r"""\.?([A-Za-z_$][\w$-]*)|\[(\d+)\]|\[\s*"((?:[^"\\]|\\.)*)"\s*\]|\[\s*'((?:[^'\\]|\\.)*)'\s*\]""")
MISSING = object()


def parse_path(path: str) -> list[str | int]:
    p = path.strip()
    if p.startswith("$"):
        p = p[1:]
    if not p:
        return []
    out: list[str | int] = []
    pos = 0
    while pos < len(p):
        m = _TOKEN.match(p, pos)
        if not m or m.end() == pos:
            raise ValueError(f"invalid JSON path {path!r}")
        name, index, dq, sq = m.groups()
        out.append(int(index) if index is not None else name if name is not None else (dq if dq is not None else sq))
        pos = m.end()
    return out


def resolve(doc: Any, path: list[str | int]) -> Any:
    cur = doc
    for key in path:
        if isinstance(key, int) and isinstance(cur, list) and -len(cur) <= key < len(cur):
            cur = cur[key]
        elif isinstance(key, str) and isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return MISSING
    return cur


def _expected(raw: str | None) -> Any:
    """'42' -> 42, 'true' -> True, 'null' -> None, '"x"' -> 'x', anything else stays a string."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    try:
        return float(str(v))
    except ValueError:
        return None


def evaluate(actual: Any, op: str, raw: str | None) -> bool:
    if op == "exists":
        return actual is not MISSING
    if op == "not exists":
        return actual is MISSING
    if actual is MISSING:
        return False
    exp = _expected(raw)
    if op in ("==", "!="):
        equal = actual == exp or (not isinstance(actual, dict | list) and str(actual) == str(raw))
        if isinstance(actual, bool) or isinstance(exp, bool):
            equal = actual is exp or str(actual).lower() == str(raw).lower()
        return equal if op == "==" else not equal
    if op in ("<", "<=", ">", ">="):
        a, b = _num(actual), _num(exp)
        if a is None or b is None:
            return False
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if op in ("contains", "not contains"):
        if isinstance(actual, list):
            found = exp in actual or any(str(x) == str(raw) for x in actual)
        elif isinstance(actual, dict):
            found = str(exp) in actual
        else:
            found = str(raw) in str(actual)
        return found if op == "contains" else not found
    if op == "regex":
        return re.search(raw or "", actual if isinstance(actual, str) else json.dumps(actual)) is not None
    return False


class Assertion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=256)
    op: Op = "=="
    value: str | None = Field(None, max_length=1024)

    @model_validator(mode="after")
    def _check(self):
        parse_path(self.path)
        if self.op == "regex":
            try:
                re.compile(self.value or "")
            except re.error as e:
                raise ValueError(f"invalid regex: {e}") from None
        if self.op not in ("exists", "not exists") and self.value is None:
            raise ValueError(f"assertion on {self.path!r} needs a value")
        return self

    def label(self) -> str:
        return f"{self.path} {self.op}" + ("" if self.op in ("exists", "not exists") else f" {self.value}")


class JsonConfig(HttpConfig):
    assertions: list[Assertion] = Field(default_factory=list, max_length=20)


def check_assertions(doc: Any, assertions: list[Assertion]) -> list[dict]:
    out = []
    for a in assertions:
        actual = resolve(doc, parse_path(a.path))
        ok = evaluate(actual, a.op, a.value)
        shown = None if actual is MISSING else short(json.dumps(actual), 120)
        out.append({"path": a.path, "op": a.op, "value": a.value, "ok": ok, "actual": shown})
    return out


@register
class JsonChecker(HttpChecker):
    kind = "json"
    label = "JSON API"
    Config = JsonConfig

    async def check(self, spec: ProbeSpec) -> Result:
        cfg = JsonConfig(**spec.config)
        try:
            res, body = await asyncio.wait_for(fetch(spec, cfg, self.transport), spec.timeout_s + 2)
        except Exception as e:  # noqa: BLE001 - reported as a generic category
            return Result(False, None, State.CRIT, http_error(e))
        if not res.up:
            return res
        try:
            doc = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            res.up, res.state, res.message = False, State.CRIT, "invalid JSON response"
            return res
        results = check_assertions(doc, cfg.assertions)
        res.details = {"assertions": results}
        failed = [r for r in results if not r["ok"]]
        res.metrics["assertions_failed"] = float(len(failed))
        if failed:
            first = next(a for a in cfg.assertions if a.path == failed[0]["path"] and a.op == failed[0]["op"])
            res.up, res.state = False, State.CRIT
            res.message = short(f"assertion failed: {first.label()}" + (f" (+{len(failed) - 1} more)" if len(failed) > 1 else ""))
        else:
            res.message = f"HTTP {int(res.metrics['status_code'])}, {len(results)} assertion{'s' if len(results) != 1 else ''} passed"
        return res
