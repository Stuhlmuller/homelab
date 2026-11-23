#!/usr/bin/env python3
"""Extract an n8n PVC archive to disposable runner scratch without disclosing config."""

import argparse
import hashlib
import json
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def verify(archive_path: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="n8n-pvc-restore-") as root:
        restored = Path(root)
        with tarfile.open(archive_path, "r:") as archive:
            members = archive.getmembers()
            if not members or len(members) > 100_000:
                raise ValueError("invalid archive member count")
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or member.isdev():
                    raise ValueError("unsafe archive member")
            archive.extractall(restored, filter="data")

        config = restored / "config"
        if not config.is_file() or config.is_symlink():
            raise ValueError("persisted n8n config missing")
        raw = config.read_bytes()
        settings = json.loads(raw)
        if not isinstance(settings, dict) or not isinstance(settings.get("encryptionKey"), str) or not settings["encryptionKey"]:
            raise ValueError("persisted n8n encryption key missing")

        count = 0
        for path in restored.rglob("*"):
            mode = path.lstat().st_mode
            if stat.S_ISREG(mode):
                count += 1
            elif not stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
                raise ValueError("unexpected restored file type")
        if count < 1:
            raise ValueError("empty restored PVC")
        return {"files": count, "config_sha256": hashlib.sha256(raw).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    args.result.write_text(json.dumps(verify(args.archive), sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
