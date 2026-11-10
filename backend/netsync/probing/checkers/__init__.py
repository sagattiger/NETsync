"""Probe kinds. Importing this package registers every checker (see netsync/probing/base.py)."""

from netsync.probing.checkers import dns, http, icmp, json_api, push, tcp, tls, udp  # noqa: F401
