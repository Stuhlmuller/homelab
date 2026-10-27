#!/usr/bin/env python3
"""Check a recovery tar stream, then extract a separately checked stream.

The caller must first bind the ciphertext to a protected expected SHA-256 and
run this helper in check mode over a complete age decryption. Only then may it
decrypt the same local ciphertext again for extract mode.
"""

import os
from pathlib import Path
import sys
import tarfile


ROOT_FILES = {"database.dump", "database-bootstrap.sql", "SHA256SUMS"}
REQUIRED_FILES = ROOT_FILES | {"material/recovery.json"}
MAX_ENTRIES = 100000
MAX_PATH_BYTES = 4096
MAX_COMPONENTS = 64
MAX_COMPONENT_BYTES = 255
MAX_AGGREGATE_PATH_BYTES = 16777216


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def normalized(member):
    name = member.name
    require(isinstance(name, str) and name and not name.startswith("/"),
            "unsafe archive path")
    require("\\" not in name and not any(ord(char) < 32 or ord(char) == 127
                                           for char in name), "unsafe archive path")
    path = name[:-1] if member.isdir() and name.endswith("/") else name
    parts = path.split("/")
    require(all(part not in ("", ".", "..") for part in parts),
            "unsafe archive path")
    require(len(parts) <= MAX_COMPONENTS and
            len(os.fsencode(path)) <= MAX_PATH_BYTES and
            all(len(os.fsencode(part)) <= MAX_COMPONENT_BYTES for part in parts),
            "archive path bound exceeded")
    require(parts[0] == "material" or path in ROOT_FILES,
            "unexpected archive root")
    require(not (parts[0] in ROOT_FILES and len(parts) != 1),
            "unexpected archive root")
    return path, parts


def process(mode, max_bytes, destination):
    os.umask(0o077)
    require(mode in ("check", "extract"), "invalid mode")
    require(max_bytes > 0, "invalid size bound")
    seen = {}
    total = 0
    total_path_bytes = 0
    root = Path(destination)
    if mode == "extract":
        root.mkdir(mode=0o700)
    else:
        require(not root.exists(), "check mode must not touch recovery output")
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as stream:
        for member in stream:
            require(len(seen) < MAX_ENTRIES, "too many archive members")
            require(member.isdir() or member.isreg(), "unsafe archive type")
            require(member.size >= 0, "invalid archive size")
            require(not member.isdir() or member.size == 0,
                    "directory carries archive content")
            require(not member.linkname, "unsafe archive link")
            require(not getattr(member, "sparse", None), "sparse archive member")
            require(not any(key.startswith("GNU.sparse") or
                            key.startswith("SCHILY.realsize")
                            for key in member.pax_headers), "sparse archive member")
            path, parts = normalized(member)
            require(path not in seen, "duplicate archive member")
            total_path_bytes += len(os.fsencode(path))
            require(total_path_bytes <= MAX_AGGREGATE_PATH_BYTES,
                    "archive path budget exceeded")
            seen[path] = "directory" if member.isdir() else "file"
            total += member.size if member.isreg() else 0
            require(0 <= total <= max_bytes, "archive size bound exceeded")
            if mode != "extract":
                continue
            target = root.joinpath(*parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = stream.extractfile(member)
            require(source is not None, "missing archive content")
            with source, target.open("xb") as output:
                remaining = member.size
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    require(bool(block), "truncated archive content")
                    output.write(block)
                    remaining -= len(block)
    require(REQUIRED_FILES <= {name for name, kind in seen.items() if kind == "file"},
            "incomplete archive")
    require(seen.get("material") == "directory", "missing material directory")
    for name in seen:
        parts = name.split("/")
        for index in range(1, len(parts)):
            require(seen.get("/".join(parts[:index])) != "file",
                    "archive parent is a file")


def main():
    if len(sys.argv) != 4:
        raise ValueError("usage: safe-extract.py check|extract max-bytes destination")
    try:
        limit = int(sys.argv[2], 10)
    except ValueError as error:
        raise ValueError("invalid size bound") from error
    process(sys.argv[1], limit, sys.argv[3])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, tarfile.TarError, EOFError) as error:
        print(f"recovery archive rejected: {error}", file=sys.stderr)
        sys.exit(1)
