"""Probe kinds. Importing this package registers every checker (see netsync/probing/base.py)."""

from netsync.probing.checkers import http, icmp, tcp  # noqa: F401
