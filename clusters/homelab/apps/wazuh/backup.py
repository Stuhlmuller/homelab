"""Snapshot indexed data and verify copies of closed raw archives on the NAS.

Never removes manager logs. Manager identities/databases require the separate
quiesced restore procedure; this is a data backup, not a complete manager backup.
"""

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import ssl
import time
import urllib.request
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publish_checksum(target, checksum):
    manifest = target.with_suffix(target.suffix + ".sha256")
    value = (checksum + "\n").encode()
    try:
        if manifest.read_bytes() == value:
            return
    except FileNotFoundError:
        # A prior archive publication may have stopped before its manifest.
        pass
    temporary = manifest.with_suffix(manifest.suffix + ".partial")
    with temporary.open("wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(manifest)


def mirror_archives():
    copied = 0
    now = time.time()
    for category in ("alerts", "archives"):
        source_root = Path("/manager/logs") / category
        for source in source_root.rglob("*.gz"):
            before = source.stat()
            # Today's rolling compressed file may still change. Copy closed days.
            if now - before.st_mtime < 86400:
                continue
            target = Path("/backups/raw") / category / source.relative_to(source_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                checksum = digest(source)
                if digest(target) == checksum:
                    publish_checksum(target, checksum)
                    continue
            temporary = target.with_suffix(target.suffix + ".partial")
            with source.open("rb") as incoming, temporary.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                temporary.unlink(missing_ok=True)
                raise RuntimeError("A rotated Wazuh archive changed during backup")
            checksum = digest(source)
            if digest(temporary) != checksum:
                temporary.unlink(missing_ok=True)
                raise RuntimeError("Wazuh archive backup checksum mismatch")
            temporary.replace(target)
            publish_checksum(target, checksum)
            copied += 1
    print(f"Verified raw archive mirror; copied {copied} closed files")


def snapshot():
    context = ssl.create_default_context(cafile="/run/admin/ca.crt")
    context.load_cert_chain("/run/admin/tls.crt", "/run/admin/tls.key")
    name = "homelab-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    url = "https://wazuh-indexer.wazuh.svc.cluster.local:9200/_snapshot/homelab/" + name
    body = {"indices": "wazuh-*,.kibana*", "ignore_unavailable": True, "include_global_state": False}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, context=context, timeout=60) as response:
        if not json.load(response).get("accepted"):
            raise RuntimeError("Wazuh index snapshot was not accepted")
    for _ in range(60):
        with urllib.request.urlopen(url, context=context, timeout=60) as response:
            result = json.load(response)["snapshots"][0]
        if result["state"] == "SUCCESS":
            print("Wazuh index snapshot completed successfully")
            return name
        if result["state"] != "IN_PROGRESS":
            raise RuntimeError("Wazuh index snapshot did not complete successfully")
        time.sleep(10)
    raise RuntimeError("Timed out waiting for Wazuh index snapshot")


def prune_snapshots(current):
    """Keep 14 days and at least three successes; never remove repository files."""
    context = ssl.create_default_context(cafile="/run/admin/ca.crt")
    context.load_cert_chain("/run/admin/tls.crt", "/run/admin/tls.key")
    base = "https://wazuh-indexer.wazuh.svc.cluster.local:9200/_snapshot/homelab/"

    def request(method, suffix):
        req = urllib.request.Request(base + suffix, method=method)
        with urllib.request.urlopen(req, context=context, timeout=60) as response:
            return json.load(response)

    snapshots = request("GET", "_all")["snapshots"]
    eligible = [item for item in snapshots
                if re.fullmatch(r"homelab-[0-9]{8}-[0-9]{6}", item["snapshot"])
                and item["state"] == "SUCCESS"
                and isinstance(item.get("end_time_in_millis"), int)]
    if not any(item["snapshot"] == current for item in eligible):
        raise RuntimeError("New successful snapshot missing from retention readback")
    newest = sorted(eligible, key=lambda item: item["end_time_in_millis"], reverse=True)[:3]
    keep = {current, *(item["snapshot"] for item in newest)}
    cutoff = (time.time() - 14 * 86400) * 1000
    removed = set()
    for item in eligible:
        name = item["snapshot"]
        if name in keep or item["end_time_in_millis"] >= cutoff:
            continue
        if request("DELETE", name).get("acknowledged") is not True:
            raise RuntimeError("Wazuh snapshot deletion was not acknowledged")
        removed.add(name)
    remaining = {item["snapshot"] for item in request("GET", "_all")["snapshots"]}
    if removed & remaining or not keep <= remaining:
        raise RuntimeError("Wazuh snapshot retention readback failed")
    print(f"Verified snapshot retention; removed {len(removed)} older successful snapshots")


if __name__ == "__main__":
    os.umask(0o077)
    mirror_archives()
    prune_snapshots(snapshot())
