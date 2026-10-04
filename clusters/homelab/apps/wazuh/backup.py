"""Snapshot indexed data and verify copies of closed raw archives on the NAS.

Never removes manager logs. Manager identities/databases require the separate
quiesced restore procedure; this is a data backup, not a complete manager backup.
"""

import datetime as dt
import hashlib
import json
import os
import shutil
import ssl
import time
import urllib.request
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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
            if target.exists() and digest(target) == digest(source):
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
            target.with_suffix(target.suffix + ".sha256").write_text(checksum + "\n")
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
            return
        if result["state"] != "IN_PROGRESS":
            raise RuntimeError("Wazuh index snapshot did not complete successfully")
        time.sleep(10)
    raise RuntimeError("Timed out waiting for Wazuh index snapshot")


if __name__ == "__main__":
    os.umask(0o077)
    mirror_archives()
    snapshot()
