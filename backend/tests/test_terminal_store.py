"""Terminal rights and tickets, plugin store catalog, installer safety checks."""

import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from netsync import store, terminal
from netsync.models import Role

ROOT = Path(__file__).resolve().parents[2]


def g(id_, level):
    return NS(id=id_, terminal_access=level)


def test_account_names():
    assert terminal.account_name("alice") == "ns-alice"
    assert terminal.account_name("Alice.Smith@corp") == "ns-alice-smith-corp"
    assert terminal.account_name("__") == "ns-user"
    long = terminal.account_name("x" * 80)
    assert len(long) == 31 and long.startswith("ns-")
    import re

    for name in ("bob", "Joe Doe", "a-b_c", "ÉLISON", "x" * 40, "-lead-"):
        assert re.match(r"^ns-[a-z0-9][a-z0-9_-]{0,28}$", terminal.account_name(name)), name


def test_level_is_the_best_shared_group_capped_by_role():
    dev = NS(groups=[g(1, "read"), g(2, "write"), g(3, "full")])
    assert terminal.level_for(NS(role=Role.ADMIN, groups=[]), dev) == "full"
    assert terminal.level_for(NS(role=Role.OPERATOR, groups=[g(1, "read"), g(2, "write")]), dev) == "write"
    assert terminal.level_for(NS(role=Role.OPERATOR, groups=[g(9, "full")]), dev) == "none"  # no shared group
    assert terminal.level_for(NS(role=Role.VIEWER, groups=[g(3, "full")]), dev) == "read"  # viewers: read at most
    assert terminal.level_for(NS(role=Role.OPERATOR, groups=[g(1, "none")]), NS(groups=[g(1, "none")])) == "none"


def test_ticket_format_matches_the_gateway():
    sys.path.insert(0, str(ROOT / "plugins" / "ssh"))
    try:
        import gateway
    except ImportError:
        pytest.skip("asyncssh not installed")
    tok = terminal.sign({"sid": "abc", "username": "u", "account": "ns-u", "level": "read", "device_id": 1,
                         "hostname": "h", "host": "10.0.0.1", "port": 22, "exp": 9999999999}, "s3cret")
    assert gateway.verify(tok, "s3cret").host == "10.0.0.1"


def test_catalog_file_parses_and_bad_entries_are_dropped():
    cat = store.parse_catalog(json.loads((ROOT / "catalog" / "plugins.json").read_text()))
    ssh = next(p for p in cat["plugins"] if p["name"] == "ssh")
    assert ssh["permissions"] == ["terminal", "events"] and ssh["source"]["dockerfile"] == "ssh/Dockerfile"
    assert (ROOT / "plugins" / ssh["source"]["dockerfile"]).exists()
    bad = store.parse_catalog({"plugins": [{"name": "Bad Name", "version": "1"}, {"name": "ok", "version": "1.0"},
                                           {"name": "fine", "version": "1.0", "source": {"repo": "a/b"},
                                            "permissions": ["tools", "root"]}]})
    assert [p["name"] for p in bad["plugins"]] == ["fine"] and bad["plugins"][0]["permissions"] == ["tools"]
    with pytest.raises(ValueError):
        store.parse_catalog([])


def test_versions():
    assert store.newer("0.2.0", "0.1.9") and store.newer("1.10", "1.9") and not store.newer("1.0", "1.0")


def load_installer():
    pytest.importorskip("docker")
    spec = importlib.util.spec_from_file_location("netsync_installer", ROOT / "installer" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_installer_repacks_only_the_context_folder():
    inst = load_installer()
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as t:
        for name, data in [("NETsync-main/plugins/ssh/Dockerfile", b"FROM x"), ("NETsync-main/plugins/sdk/a.py", b"a"),
                           ("NETsync-main/backend/secret.py", b"no")]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("NETsync-main/plugins/evil")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        t.addfile(link)
    out = inst.context_tar(raw.getvalue(), "plugins")
    with tarfile.open(fileobj=out) as t:
        assert sorted(t.getnames()) == ["sdk/a.py", "ssh/Dockerfile"]


def test_installer_refuses_unsafe_requests():
    inst = load_installer()
    ok = dict(name="ssh", version="0.1.0", source={"repo": "sagattiger/NETsync", "context": "plugins",
                                                    "dockerfile": "ssh/Dockerfile"}, env={"NETSYNC_URL": "x"})
    inst.validate(inst.InstallIn(**ok))
    for change in ({"name": "../x"}, {"env": {"PATH": "/tmp"}}, {"memory_mb": 99999},
                   {"source": {**ok["source"], "context": "../../etc"}}, {"source": {**ok["source"], "repo": "a b/c"}}):
        with pytest.raises(inst.HTTPException):
            inst.validate(inst.InstallIn(**{**ok, **change}))


def test_installer_token_matches_core(monkeypatch):
    inst = load_installer()
    monkeypatch.setenv("NETSYNC_SECRET_KEY", "k1")
    from netsync.config import get_settings

    monkeypatch.setattr(store, "get_settings", lambda: NS(secret_key="k1"))
    assert inst.token() == store.installer_token()
    assert get_settings  # imported for the side effect of config loading
