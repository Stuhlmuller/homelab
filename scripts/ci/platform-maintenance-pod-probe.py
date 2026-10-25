#!/usr/bin/env python3
"""Functional DNS and NFS claim I/O probe inside the fixture Pod."""

import hashlib
import json
import os
import socket
import sys
import uuid
from pathlib import Path


def run(mount, api_ip, grafana_ip):
    resolved = {}
    for name, expected in (
            ("kubernetes.default.svc.cluster.local", api_ip),
            ("grafana.monitoring.svc.cluster.local", grafana_ip)):
        answers = {item[4][0] for item in socket.getaddrinfo(
            name, None, socket.AF_INET, socket.SOCK_STREAM)}
        if answers != {expected}:
            raise ValueError("cluster DNS answer differs from Service address")
        resolved[name] = expected

    path = Path(mount) / f".platform-maintenance-{uuid.uuid4().hex}"
    payload = os.urandom(4096)
    created = False
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        with path.open("rb") as stream:
            observed = stream.read(4097)
        if observed != payload:
            raise ValueError("NFS claim readback differs from write")
    finally:
        if created:
            path.unlink()
    if path.exists():
        raise ValueError("NFS claim probe file remains")

    return {"dns": resolved, "storage": {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                                          "readBack": True, "deleted": True}}


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(2)
    print(json.dumps(run(*sys.argv[1:])))
