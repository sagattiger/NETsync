"""IP Book import: reading a sheet with a title banner, mapping its columns, cleaning values and planning the merge.
Every name and address here is invented."""

import csv
import io

import pytest

from netsync.plugins.builtin.ipbook import importer

HEADER = ["Service Name", "Hypervisor", "Type", "VMID", "HA", "Device / Hostname", "IP Mgmt", "IP Wan", "NAT",
          "IP Lan", "Internal FQDN", "Public FQDN", "Public URLs", "SSL", "MGMT or Internal URLs", "http port",
          "https port", "Web User", "Web Pass", "OS User", "OS Password", "DB Password", "Enable Secret", "Shelf", "", ""]
DATA = [
    ["Edge Router", "N/A", "RouterOS", "N/A", "-", "rt01.example.test", "10.0.0.254", "198.51.100.2", "N", "N/A",
     "rt01.example.test", "N/A", "N/A", "N", "N/A", "N/A", "N/A", "", "", "", "", "N/A", "", "A3", "", ""],
    ["Wiki", "pve01", "LXC Container", "101", "N", "app01.example.test", "10.0.0.101", "10.0.1.101", "S", "N/A",
     "app01.example.test", "N/A", "https://wiki.example.test/", "S", "http://app01.example.test:8080/", "8080",
     "default", "admin", "pw-wiki-1", "", "", "", "", "B1", "", ""],
    ["Chat", "pve01", "LXC Container", "102", "N", "app01b.example.test", "10.0.0.102", "10.0.1.102", "S", "N/A",
     "", "", "", "N", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["Docs", "pve01", "LXC Container", "103", "N", "app03.example.test", "10.0.0.103", "10.0.1.102", "S", "",
     "", "", "", "N", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["Lab box", "pve02", "VM Machine", "120", "N", "lab01.example.test", "10.0.5.20", "N/A", "N", "", "", "", "",
     "N", "", "", "", "", "", "", "", "", "", "", "", ""],
    [""] * 26,
]
TABLE = [["Example Stack", "", ""], [""] * 3, ["", "", "Devices info details and passwords"], HEADER, *DATA]


def csv_bytes(rows, sep=","):
    buf = io.StringIO()
    csv.writer(buf, delimiter=sep).writerows(rows)
    return buf.getvalue().encode()


def test_find_header_skips_banner_rows():
    assert importer.find_header(TABLE) == 3


def test_guess_mapping():
    m = importer.guess_mapping(HEADER)
    assert m[:10] == ["service", "hypervisor", "type", "vmid", "ha", "hostname", "ip_mgmt", "ip_wan", "nat", "ip_lan"]
    assert m[14] == "urls_internal" and m[18] == "web_pass" and m[22] == "enable_secret"
    assert m[23] is None and m[24] is None  # unknown ("Shelf") and empty columns are not mapped


def test_clean_cell():
    assert importer.clean_cell("nat", "S") is True and importer.clean_cell("ssl", "N") is False
    assert importer.clean_cell("fqdn_public", "N/A") is None and importer.clean_cell("ha", "-") is None
    assert importer.clean_cell("https_port", "default") == "default"
    assert importer.clean_cell("http_port", "8080") == 8080
    assert importer.clean_cell("db_pass", "???") == "???"


@pytest.mark.parametrize(("raw", "expected"), [
    ("LXC Container", ("LXC", None)), ("VM Machine", ("VM", None)), ("Docker", ("Docker", None)), ("kvm", ("VM", None)),
    ("RouterOS", ("Device", "RouterOS")), ("Debian 13", ("Device", "Debian 13")), ("", (None, None)),
])
def test_split_type(raw, expected):
    assert importer.split_type(raw) == expected


def test_read_csv_and_semicolons():
    table, sheets = importer.read_table(csv_bytes(TABLE, ";"), "list.csv")
    assert sheets == [] and table[3][0] == "Service Name" and table[5][18] == "pw-wiki-1"
    latin = "Serviço;Tipo\nCâmera;LXC\n".encode("latin-1")
    assert importer.read_table(latin, "x.csv")[0][1] == ["Câmera", "LXC"]


def test_read_xlsx():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.title = "Stacks"
    for r in TABLE:
        wb.active.append(r)
    wb.create_sheet("Other")
    buf = io.BytesIO()
    wb.save(buf)
    table, sheets = importer.read_table(buf.getvalue(), "list.xlsx")
    assert sheets == ["Stacks", "Other"] and importer.find_header(table) == 3 and table[5][3] == "101"


def test_too_big_is_refused():
    with pytest.raises(ValueError):
        importer.read_table(b"x" * (importer.MAX_BYTES + 1), "big.csv")


def test_sheet_rows_become_values():
    rows, skipped = importer.sheet_rows(TABLE, 3, importer.guess_mapping(HEADER))
    assert len(rows) == 5 and skipped == 1  # the empty row is skipped
    wiki = rows[1]
    assert wiki["type"] == "LXC" and "os" not in wiki and wiki["vmid"] == 101 and wiki["nat"] is True
    assert wiki["urls_public"] == ["https://wiki.example.test/"] and wiki["web_pass"] == "pw-wiki-1"
    assert wiki["service"] == {"name": "Wiki", "logo": None} and wiki["hypervisor_name"] == "pve01"
    assert rows[0]["type"] == "Device" and rows[0]["os"] == "RouterOS" and "ip_lan" not in rows[0]


def test_plan_import():
    rows, _ = importer.sheet_rows(TABLE, 3, importer.guess_mapping(HEADER))
    existing = [
        {"id": 1, "hostname": "rt01.example.test", "ips": ["10.0.0.254"], "values": {"ip_mgmt": "10.0.0.254"}},
        {"id": 2, "hostname": "app01", "ips": ["10.0.0.101"], "values": {"ip_mgmt": "10.0.0.101", "vmid": 999}},
        {"id": 3, "hostname": "other.example.test", "ips": ["10.0.1.102"], "values": {}},
    ]
    plan = importer.plan_import(rows, existing, ["10.0.0.0/24", "10.0.1.0/24"])
    merged = {m["row_id"]: m for m in plan["merge"]}
    assert set(merged) == {1, 2}  # by hostname, with and without the domain
    assert merged[2]["conflicts"] == {"vmid": {"manual": 101, "discovered": 999}}
    # 10.0.1.102 is in two sheet rows: matching by IP is not allowed, both become new entries
    assert sorted(r["hostname"] for r in plan["create"]) == ["app01b.example.test", "app03.example.test", "lab01.example.test"]
    assert plan["networks"] == ["10.0.5.0/24"]  # 198.51.100.2 is public: no network proposed
    assert plan["skip"] == 0
    assert importer.plan_import([{"description": "just a note"}], [], [])["skip"] == 1  # nothing to identify it
