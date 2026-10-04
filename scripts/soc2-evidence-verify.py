#!/usr/bin/env python3
"""Verify v5 source/evidence and archived tree proofs without PR-only commits."""

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PACKET = "docs/compliance/soc2/evidence/HOME-30-v5/"
ENVELOPE = {PACKET + name for name in (
    "population.json", "history.json", "packet.md", "validation.json",
    "SHA256SUMS", "review.json", "reconciliation.json")}


# Independently review these fixed original bindings; never derive them from refreshed evidence.
EXPECTED_HISTORY = {
    1: {
        "version": 1,
        "revision": "0771f1952f8026a7ad9f6e5e5f61752c0a54ae9d",
        "tree": "33e796b33bee39dd9e943b7ebe2fcb6979f0095f",
        "manifest": "docs/compliance/soc2/evidence/HOME-30-v1/SHA256SUMS",
        "manifest_sha256": "e630311cbb26b13f531a9b71caf247b66f7f6148459b6bfb06e7f0a288c76e0c",
    },
    2: {
        "version": 2,
        "revision": "fb0f0296b409d9c21c4d3801beaf0a207aa9fdb1",
        "tree": "3f1fa3e164aeb124f70279d8fad3eeeb3b4b9820",
        "manifest": "docs/compliance/soc2/evidence/HOME-30-v2/SHA256SUMS",
        "manifest_sha256": "477cbf8ba9c2e16638680ee917bb20d119a028325b2dd90302eb808790a60503",
    },
    3: {
        "version": 3,
        "revision": "17612c10bc5d86fc14dc888f0e5f04a621298283",
        "tree": "9b3bb2f6c6ff2a58ecc95a7d7a2b6dac0a4a72e3",
        "manifest": "docs/compliance/soc2/evidence/HOME-30-v3/SHA256SUMS",
        "manifest_sha256": "d6cfaf36a7cf9ab533f5a3afcca9fdaea342d29f51977398fb0b4fec86e99fa8",
    },
}


class EvidenceError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def safe_path(path):
    require(isinstance(path, str) and path and not PurePosixPath(path).is_absolute()
            and ".." not in PurePosixPath(path).parts and "\\" not in path,
            "unsafe artifact path")
    return path


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def object_id(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def parse_tree(raw):
    entries = {}
    pos = 0
    while pos < len(raw):
        stop = raw.index(b"\0", pos)
        mode, name = raw[pos:stop].split(b" ", 1)
        require(stop + 21 <= len(raw), "truncated tree")
        name = name.decode()
        require(name not in entries and "/" not in name and name not in (".", ".."),
                "invalid tree entry")
        entries[name] = (mode.decode(), raw[stop + 1:stop + 21].hex())
        pos = stop + 21
    return entries


def history_check(history):
    require(
        isinstance(history, dict) and history.get("schema_version") == 1,
        "unsupported historical archive schema",
    )
    packets = history.get("packets")
    require(
        isinstance(packets, list) and len(packets) == len(EXPECTED_HISTORY),
        "historical packet set must contain exactly v1-v3",
    )
    seen = set()
    for snapshot in packets:
        require(isinstance(snapshot, dict), "invalid historical packet")
        version = snapshot.get("version")
        require(
            type(version) is int
            and version in EXPECTED_HISTORY
            and version not in seen,
            "historical packet versions must be unique v1-v3",
        )
        require(
            snapshot == EXPECTED_HISTORY[version],
            "original historical binding mismatch",
        )
        seen.add(version)
    require(seen == set(EXPECTED_HISTORY), "incomplete historical packet versions")
    require(
        isinstance(history.get("objects"), dict) and history["objects"],
        "missing historical objects",
    )
    objects = {}
    for oid, record in history["objects"].items():
        kind = record["type"]
        require(kind in ("tree", "blob"), "unexpected archive object type")
        data = base64.b64decode(record["base64"], validate=True)
        require(object_id(kind, data) == oid, "archived Git object digest mismatch")
        objects[oid] = (kind, data)

    def get_blob(root, path):
        parts = PurePosixPath(safe_path(path)).parts
        oid = root
        for part in parts:
            kind, raw = objects[oid]
            require(kind == "tree", "invalid tree proof")
            _, oid = parse_tree(raw)[part]
        kind, data = objects[oid]
        require(kind == "blob", "artifact is not a blob")
        return data

    for snapshot in history["packets"]:
        manifest_path = safe_path(snapshot["manifest"])
        root = snapshot["tree"]
        manifest = get_blob(root, manifest_path).decode()
        require(hashlib.sha256(manifest.encode()).hexdigest() == snapshot["manifest_sha256"],
                "historical manifest digest mismatch")
        names = set()
        for line in manifest.splitlines():
            digest, path = line.split("  ", 1)
            require(path not in names, "duplicate historical entry")
            names.add(path)
            require(hashlib.sha256(get_blob(root, path)).hexdigest() == digest,
                    "historical artifact mismatch")
    return len(history["packets"])


def verify():
    manifest_path = ROOT / PACKET / "SHA256SUMS"
    manifest = manifest_path.read_bytes()
    # Bind the root manifest to the checked-out commit, not an editable checksum.
    require(manifest == git("show", "HEAD:" + PACKET + "SHA256SUMS"),
            "working manifest differs from reviewed commit")
    names = set()
    for line in manifest.decode().splitlines():
        digest, path = line.split("  ", 1)
        safe_path(path)
        require(path not in names, "duplicate artifact")
        names.add(path)
        target = ROOT / path
        require(not target.is_symlink() and target.is_file(), "missing or symlink artifact")
        require(hashlib.sha256(target.read_bytes()).hexdigest() == digest,
                "artifact digest mismatch: " + path)
    require(names == ENVELOPE - {PACKET + "SHA256SUMS"}, "incomplete evidence envelope")
    population = json.loads((ROOT / PACKET / "population.json").read_text())
    actual = {}
    for record in filter(None, git("ls-tree", "-r", "-z", "HEAD").split(b"\0")):
        meta, path = record.split(b"\t", 1)
        actual[path.decode()] = meta.decode().split()
    recorded = {}
    for row in population["entries"]:
        path, mode, kind, oid, digest = row
        safe_path(path)
        require(path not in recorded and path not in ENVELOPE, "duplicate or recursive population entry")
        recorded[path] = [mode, kind, oid]
        require(actual.get(path) == [mode, kind, oid], "committed source drift: " + path)
        target = ROOT / path
        require(kind == "blob" and mode in ("100644", "100755")
                and target.is_file() and not target.is_symlink(), "unsupported source entry")
        data = target.read_bytes()
        require(hashlib.sha256(data).hexdigest() == digest and object_id("blob", data) == oid,
                "working source drift: " + path)
    require(set(actual) == set(recorded) | ENVELOPE, "whole-tree population mismatch")
    for path in ENVELOPE:
        require(actual[path][:2] == ["100644", "blob"], "unexpected evidence mode")
        require(object_id("blob", (ROOT / path).read_bytes()) == actual[path][2],
                "working evidence differs from commit")
    history = json.loads((ROOT / PACKET / "history.json").read_text())
    count = history_check(history)
    print(f"PASS: {len(actual)} paths, complete source/evidence closure, {count} archived packet proofs")


if __name__ == "__main__":
    try:
        verify()
    except (EvidenceError, OSError, ValueError, KeyError, TypeError,
            subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
