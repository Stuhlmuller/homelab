#!/usr/bin/env python3
"""Verify final v3 tree closure, decision digest and immutable historical packets."""

import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def tree(revision):
    result = {}
    for row in filter(None, git("ls-tree", "-r", "-z", revision).split(b"\0")):
        metadata, path = row.split(b"\t", 1)
        result[path.decode()] = metadata.decode().split()
    return result


def main():
    register = json.loads((HERE / "whole-tree.json").read_text())
    subprocess.run(["python3", str(ROOT / "scripts/soc2-whole-tree.py"),
                    "--previous-main", register["previous_main"],
                    "--selected-main", register["selected_main"],
                    "--revision", register["integration_revision"],
                    "--check", str(HERE / "whole-tree.json")], check=True)
    base = {row[0]: row[1:4] for row in register["entries"]}
    final = tree("HEAD")
    for path, identity in base.items():
        assert final.get(path) == identity, "unreconciled integration-tree change"
    manifest = {}
    for row in (HERE / "SHA256SUMS").read_text().splitlines():
        digest, path = row.split("  ", 1)
        assert path not in manifest, "duplicate manifest entry"
        manifest[path] = digest
        assert hashlib.sha256(git("show", "HEAD:" + path)).hexdigest() == digest
    checksum_path = str((HERE / "SHA256SUMS").relative_to(ROOT))
    additions = set(final) - set(base)
    assert additions == (set(manifest) - set(base)) | {checksum_path}, "unaccounted final addition"
    assert all(p.startswith(str(HERE.relative_to(ROOT)) + "/") for p in additions)
    assert all(final[p][:2] == ["100644", "blob"] for p in additions)
    provenance = json.loads((HERE / "decision-provenance.json").read_text())
    assert hashlib.sha256((HERE / "HOME-45-original.txt").read_bytes()).hexdigest() == provenance["sha256"]
    for version, revision in [(1, "0771f1952f8026a7ad9f6e5e5f61752c0a54ae9d"),
                              (2, "fb0f0296b409d9c21c4d3801beaf0a207aa9fdb1")]:
        prefix = f"docs/compliance/soc2/evidence/HOME-30-v{version}/"
        original = git("show", revision + ":" + prefix + "SHA256SUMS")
        assert original == (ROOT / prefix / "SHA256SUMS").read_bytes()
        for row in original.decode().splitlines():
            digest, path = row.split("  ", 1)
            assert hashlib.sha256(git("show", revision + ":" + path)).hexdigest() == digest
    print(f"PASS: {len(base)} integration entries plus {len(additions)} final packet additions; decision and v1/v2 history verified")


if __name__ == "__main__":
    main()
