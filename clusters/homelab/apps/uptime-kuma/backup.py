#!/usr/bin/env python3
"""Online SQLite backup and fenced, isolated verification. No production SQL writes."""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone

IMAGE = "sha256:7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def summary(db):
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("database-integrity")
        ids = [row[0] for row in connection.execute("select id from monitor order by id")]
        history = connection.execute("select count(*) from heartbeat").fetchone()[0]
    if not ids or history < 1:
        raise ValueError("history-not-ready")
    return {"monitorIds": ids, "monitors": len(ids), "heartbeats": history}


def allowed_files(source):
    files = [source / "db-config.json"]
    uploads = source / "upload"
    if uploads.exists() or uploads.is_symlink():
        if uploads.is_symlink() or not uploads.is_dir():
            raise ValueError("unsafe-upload")
        for path in uploads.rglob("*"):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("unsafe-upload")
            if path.is_file():
                files.append(path)
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError("unsafe-ancillary")
    if json.loads(files[0].read_text()).get("type") != "sqlite":
        raise ValueError("unexpected-database")
    return files


def snapshot(source, destination, catalog, retain=14, scratch_directory=None):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or (source / "kuma.db").is_symlink():
        raise ValueError("unsafe-source")
    files = allowed_files(source)
    destination.mkdir(parents=True, exist_ok=True)
    os.chmod(destination, 0o700)
    name = "snapshot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=destination))
    try:
        with tempfile.TemporaryDirectory(prefix="kuma-snapshot-", dir=scratch_directory) as scratch:
            data = Path(scratch)
            db = data / "kuma.db"
            # Existing writer owns WAL/SHM. mode=ro never creates or changes production state.
            with closing(sqlite3.connect(db)) as writer:
                with closing(sqlite3.connect(f"file:{source / 'kuma.db'}?mode=ro", uri=True, timeout=10)) as reader:
                    deadline = time.monotonic() + 120

                    def progress(status, remaining, total):
                        if time.monotonic() > deadline:
                            raise TimeoutError("snapshot-timeout")

                    if reader.execute("PRAGMA journal_mode").fetchone()[0] == "wal":
                        # Pin the WAL read snapshot across backup steps so external commits
                        # cannot restart the copy. Release it before checking the backup.
                        reader.execute("BEGIN")
                        reader.execute("SELECT rootpage FROM sqlite_schema LIMIT 1").fetchone()
                    reader.backup(writer, pages=256, progress=progress, sleep=0.05)
                writer.execute("PRAGMA journal_mode=DELETE")
            counts = summary(db)
            expected = {m["key"] for m in json.loads(Path(catalog).read_text()).get("monitors", [])}
            if expected:
                with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as connection:
                    markers = [
                        line.removeprefix("homelab-managed:uptime-kuma:v1:")
                        for (description,) in connection.execute("select description from monitor")
                        for line in (description or "").splitlines()
                        if line.startswith("homelab-managed:uptime-kuma:v1:")
                    ]
                if len(markers) != len(set(markers)) or not expected <= set(markers):
                    raise ValueError("history-not-ready")
            for path in files:
                target = data / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target, follow_symlinks=False)
            archive = staging / "data.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for path in sorted(data.rglob("*")):
                    if path.is_file():
                        tar.add(path, arcname=str(path.relative_to(data)), recursive=False)
            manifest = {
                "schemaVersion": 1,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "imageDigest": IMAGE,
                "catalogHash": digest(Path(catalog)),
                "archive": "data.tar.gz",
                "sha256": digest(archive),
                "integrity": "ok",
                **counts,
            }
            (staging / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
            for path in staging.iterdir():
                os.chmod(path, 0o600)
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            os.rename(staging, destination / name)  # archive and manifest become visible together
            fd = os.open(destination, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            bundles = sorted(p for p in destination.glob("snapshot-*") if p.is_dir() and not p.is_symlink())
            for old in bundles[:-retain]:
                shutil.rmtree(old)
            return {
                "ok": True,
                "archiveHash": manifest["sha256"],
                "monitors": counts["monitors"],
                "heartbeats": counts["heartbeats"],
            }
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def restore(source, destination):
    source, destination = Path(source), Path(destination)
    bundles = sorted(p for p in source.glob("snapshot-*") if p.is_dir() and not p.is_symlink())
    if not bundles:
        raise ValueError("no-backup")
    bundle = bundles[-1]
    manifest_path, archive = bundle / "manifest.json", bundle / "data.tar.gz"
    if manifest_path.is_symlink() or archive.is_symlink():
        raise ValueError("unsafe-bundle")
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest.get("schemaVersion") != 1
        or manifest.get("imageDigest") != IMAGE
        or manifest.get("archive") != "data.tar.gz"
        or manifest.get("integrity") != "ok"
        or digest(archive) != manifest.get("sha256")
    ):
        raise ValueError("invalid-backup")
    if destination.is_symlink() or (destination.exists() and any(destination.iterdir())):
        raise ValueError("restore-destination-not-empty")
    destination.mkdir(parents=True, exist_ok=True)
    os.chmod(destination, 0o700)
    try:
        with tarfile.open(archive, "r:gz") as tar:
            seen = set()
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if (
                    not member.isfile()
                    or member.name.startswith("/")
                    or ".." in parts
                    or member.name in seen
                    or not (member.name in {"kuma.db", "db-config.json"} or (parts and parts[0] == "upload"))
                ):
                    raise ValueError("unsafe-archive-member")
                seen.add(member.name)
                target = destination / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
                os.chmod(target, 0o600)
            if not {"kuma.db", "db-config.json"} <= seen:
                raise ValueError("incomplete-archive")
        if json.loads((destination / "db-config.json").read_text()).get("type") != "sqlite":
            raise ValueError("unexpected-database")
        actual = summary(destination / "kuma.db")
        if any(actual[key] != manifest[key] for key in actual):
            raise ValueError("snapshot-summary-mismatch")
        return manifest
    except Exception:
        shutil.rmtree(destination)
        raise


# Full PRAGMA column shape of the bootstrapped pinned 2.5.11 SQLite schema.
PINNED_SCHEMA = "fed51065c4390d71450db581fd20f911f17f78eda7894f84866246ccefc2c2f6"
FENCED_SETTINGS = {"checkUpdate": False, "nscd": False, "cloudflaredTunnelToken": ""}
CHILD_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/tmp", "TMPDIR": "/tmp"}


def schema_shape(connection):
    tables = [
        r[0]
        for r in connection.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"
        )
    ]
    return {t: list(connection.execute('PRAGMA table_info("' + t.replace('"', '""') + '")')) for t in tables}


def hash_value(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=lambda b: {"bytes": bytes(b).hex()}).encode()
    ).hexdigest()


def validate_schema(connection):
    if hash_value(schema_shape(connection)) != PINNED_SCHEMA:
        raise ValueError("unknown-schema")
    if connection.execute("select 1 from setting group by key having count(*) != 1 limit 1").fetchone():
        raise ValueError("ambiguous-settings")
    if connection.execute("select 1 from setting where key is null limit 1").fetchone():
        raise ValueError("ambiguous-settings")


def private_evidence(connection):
    """Only hashes remain in memory; no private rows enter logs or artifacts."""
    result = {}
    for table, columns in schema_shape(connection).items():
        if table == "monitor_notification":
            continue
        names = [c[1] for c in columns]
        omitted = (
            {"active"}
            if table in {"monitor", "maintenance"}
            else {"active", "is_default"}
            if table == "notification"
            else set()
        )
        selected = [n for n in names if n not in omitted]
        sql = "select " + ",".join('"' + n + '"' for n in selected) + ' from "' + table + '"'
        args = ()
        if table == "setting":
            sql += " where key not in (?,?,?)"
            args = tuple(FENCED_SETTINGS)
        # Prefer the stable primary key to avoid sorting wide history rows. Stream
        # row encodings rather than retaining 30 days of heartbeat data in RAM.
        primary = [c[1] for c in sorted(columns, key=lambda c: c[5]) if c[5] and c[1] in selected]
        sql += " order by " + ",".join('"' + n + '"' for n in (primary or selected))
        checksum = hashlib.sha256()
        count = 0
        for row in connection.execute(sql, args):
            checksum.update(
                json.dumps(row, separators=(",", ":"), default=lambda b: {"bytes": bytes(b).hex()}).encode()
            )
            checksum.update(b"\n")
            count += 1
        result[table] = {"rows": count, "sha256": checksum.hexdigest()}
    return result


def assert_fence(connection, original):
    validate_schema(connection)
    for table, flags in [
        ("monitor", ["active"]),
        ("notification", ["active", "is_default"]),
        ("maintenance", ["active"]),
    ]:
        for flag in flags:
            if connection.execute(f"select 1 from {table} where {flag} is null or {flag} != 0 limit 1").fetchone():
                raise ValueError("unsafe-activation")
    if connection.execute("select 1 from monitor_notification limit 1").fetchone():
        raise ValueError("unsafe-notification-binding")
    for key, expected in FENCED_SETTINGS.items():
        rows = list(connection.execute("select value from setting where key=?", (key,)))
        if len(rows) != 1:
            raise ValueError("missing-fenced-setting")
        try:
            actual = json.loads(rows[0][0])
        except (TypeError, ValueError):
            raise ValueError("invalid-fenced-setting") from None
        if type(actual) is not type(expected) or actual != expected:
            raise ValueError("invalid-fenced-setting")
    if private_evidence(connection) != original:
        raise ValueError("clone-evidence-changed")


def fence_clone(destination):
    db = Path(destination) / "kuma.db"
    with closing(sqlite3.connect(db)) as connection:
        validate_schema(connection)
        original = private_evidence(connection)
        with connection:
            for table in ["monitor", "notification", "maintenance"]:
                connection.execute(f"update {table} set active=0")
            connection.execute("update notification set is_default=0")
            connection.execute("delete from monitor_notification")
            for key, value in FENCED_SETTINGS.items():
                if connection.execute("select id from setting where key=?", (key,)).fetchone():
                    connection.execute("update setting set value=? where key=?", (json.dumps(value), key))
                else:
                    connection.execute(
                        "insert into setting (key,value,type) values (?,?,?)", (key, json.dumps(value), "general")
                    )
    # Independent connection observes committed state and catches every missing fence.
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as connection:
        assert_fence(connection, original)
    return original


def verify(source, destination, password_file, observe_seconds=0):
    manifest = restore(source, destination)
    try:
        return _verify_clone(manifest, destination, password_file, observe_seconds)
    finally:
        # restore() accepted only a new empty destination; never source/archive.
        shutil.rmtree(destination)


def _verify_clone(manifest, destination, password_file, observe_seconds):
    original = fence_clone(destination)
    db = Path(destination) / "kuma.db"
    # Recheck at the spawn boundary, even if a caller accidentally changes the clone.
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as connection:
        assert_fence(connection, original)
    server = subprocess.Popen(
        ["node", "/app/server/server.js", "--host=127.0.0.1", "--port=3001", f"--data-dir={destination}"],
        cwd="/app",
        env=CHILD_ENV.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    code = """const fs=require('fs'),a=require('/config/reconcile.js');
(async()=>{const c=await a.connect('http://127.0.0.1:3001');try{
if(await c.request('needSetup')!==false)throw Error('unexpected-setup');
await a.login(c,fs.readFileSync(process.argv[1],'utf8').trim());
const records=Object.values(await c.list());
if(records.some(x=>x.active))throw Error('active-clone');
const ids=records.map(x=>x.id).sort((a,b)=>a-b);
if(JSON.stringify(ids)!==process.argv[2])throw Error('restore-ids');
for(const id of ids){const detail=await c.request('getMonitor',id);if(detail.monitor.active)throw Error('active-detail');}
for(let n=0;n<50&&!Array.from(c.observations.values()).some(x=>x.length);n++)await new Promise(r=>setTimeout(r,100));
if(!Array.from(c.observations.values()).some(x=>x.length))throw Error('native-history-absent');
}finally{c.close()}})().catch(()=>{process.exitCode=1});"""
    try:
        subprocess.run(
            ["node", "-e", code, str(password_file), json.dumps(manifest["monitorIds"], separators=(",", ":"))],
            env=CHILD_ENV.copy(),
            check=True,
            timeout=150,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if observe_seconds:
            time.sleep(observe_seconds)
        if server.poll() is not None:
            raise ValueError("restore-server-exited")
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
            raise ValueError("restore-shutdown-timeout")
    actual = summary(db)
    if actual["heartbeats"] != manifest["heartbeats"]:
        raise ValueError("restore-history-changed")
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as connection:
        current = private_evidence(connection)
        assert_fence(connection, current)
        for table in original:
            if table in {"user", "monitor", "notification", "heartbeat"} or table.startswith("stat_"):
                if current.get(table) != original[table]:
                    raise ValueError("restore-private-evidence-changed")
    return {
        "ok": True,
        "monitors": actual["monitors"],
        "heartbeats": manifest["heartbeats"],
        "archiveHash": manifest["sha256"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["snapshot", "verify"])
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--catalog", default="/config/monitors.json")
    parser.add_argument("--password-file", default="/secret/admin-password")
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--scratch")
    args = parser.parse_args()
    deadline = time.monotonic() + args.wait_seconds
    while True:
        try:
            result = (
                snapshot(args.source, args.destination, args.catalog, scratch_directory=args.scratch)
                if args.mode == "snapshot"
                else verify(args.source, args.destination, args.password_file)
            )
            print(json.dumps(result))
            return
        except (ValueError, sqlite3.Error, FileNotFoundError) as error:
            if (
                args.mode == "snapshot"
                and time.monotonic() < deadline
                and (str(error) == "history-not-ready" or isinstance(error, (sqlite3.Error, FileNotFoundError)))
            ):
                time.sleep(5)
                continue
            raise


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"ok": False, "error": "backup-or-restore-failed"}))
        raise SystemExit(1)
