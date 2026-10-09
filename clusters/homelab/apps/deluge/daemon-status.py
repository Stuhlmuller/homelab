#!/usr/bin/env python3
"""Read daemon health and aggregate counts; callers bound total process time."""

import logging
import sys

logging.disable(logging.CRITICAL)

from deluge.ui.client import client
from twisted.internet import defer, task


@defer.inlineCallbacks
def status(_reactor):
    try:
        try:
            with open("/config/auth", encoding="utf-8") as auth:
                username, password, _ = next(
                    line.rstrip().split(":", 2)
                    for line in auth if line.startswith("localclient:")
                )
            if not password:
                raise ValueError("Missing local daemon password")
            yield client.connect("127.0.0.1", 58846, username, password)
            torrents = yield client.core.get_torrents_status({}, ["state"])
            total = len(torrents)
            errors = sum(item["state"] == "Error" for item in torrents.values())
        finally:
            yield client.disconnect()
    except Exception:
        print("Deluge daemon RPC health check failed", file=sys.stderr)
        raise SystemExit(1)
    print("Total torrents: {}\nError: {}".format(total, errors))


if __name__ == "__main__":
    task.react(status)
