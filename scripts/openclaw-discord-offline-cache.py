#!/usr/bin/env python3
"""Build and prove a private, offline npm cache for the pinned legacy Discord plugin.

The cache contains public npm package bytes only. It never includes OpenClaw state,
plugin install records, credentials, or a restored user archive.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


IMAGE = (
    "ghcr.io/openclaw/openclaw:2026.9.5@sha256:"
    "ea298b62be8955d3ef750e2004a610dd90c3a30e5f9886e5d654d78a0c573218"
)
SPEC = "@openclaw/discord@2026.9.5"
INTEGRITY = "sha512-kPEbPiYAnJqxqLHqBnZCr3zowsxzboW0Q7ZdqX52X7IENLrU4CBdK4+ndqzQf+255ilffrYBTDrHBg8a137cgQ=="
ARTIFACTS = ("npm-cache.tar", "dependency-lock.json", "manifest.json")
MAX_BYTES = {"npm-cache.tar": 1024 * 1024 * 1024,
             "dependency-lock.json": 10 * 1024 * 1024,
             "manifest.json": 64 * 1024}


def run(*args, capture=False):
    return subprocess.run(args, check=True, text=True, capture_output=capture)


def container(work, state, home, command, *, offline):
    args = [
        "docker", "run", "--rm", "--platform", "linux/amd64",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--mount", f"type=bind,src={work},dst=/work",
        "--env", f"HOME=/work/{home}", "--env", f"OPENCLAW_STATE_DIR=/work/{state}",
        "--env", "npm_config_audit=false", "--env", "npm_config_fund=false",
    ]
    if offline:
        args += ["--network", "none", "--env", "npm_config_offline=true"]
    args += ["--entrypoint", "/bin/sh", IMAGE, "-eu", "-c", command]
    return run(*args, capture=True)


def check_image_contract(root):
    config = json.loads((root / "scripts/config/openclaw-enterprise.json").read_text())
    if config["legacyRetention"]["image"] != IMAGE:
        raise ValueError("legacy image changed; review the offline cache contract")
    values = (root / "clusters/homelab/apps/openclaw/values.yaml").read_text()
    if IMAGE not in values:
        # The Helm repository is the private Harbor mirror of this exact upstream digest.
        if IMAGE.split("@", 1)[1] not in values:
            raise ValueError("legacy Helm image digest changed; review the offline cache contract")


def check_inspect(report, work):
    plugin = report["plugin"]
    install = report.get("install") or {}
    if not (
        plugin.get("id") == "discord"
        and plugin.get("origin") == "global"
        and install.get("source") == "npm"
        and install.get("spec") == SPEC
        and install.get("version") == "2026.9.5"
    ):
        raise ValueError("offline Discord install provenance or version mismatch")
    root = Path(plugin["rootDir"])
    if not root.is_relative_to("/work/offline-state"):
        raise ValueError("Discord plugin root is outside fresh offline state")
    local_root = work / root.relative_to("/work")
    if not local_root.resolve().is_relative_to((work / "offline-state").resolve()):
        raise ValueError("Discord plugin root escapes fresh offline state")
    package = json.loads((local_root / "package.json").read_text())
    if (package.get("name"), package.get("version")) != ("@openclaw/discord", "2026.9.5"):
        raise ValueError("offline Discord package manifest mismatch")


def archive_cache(cache, destination):
    """Tar only the npm cache, with stable metadata and no links or special files."""
    with tarfile.open(destination, "w") as output:
        for path in sorted(cache.rglob("*")):
            relative = path.relative_to(cache)
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError(f"unexpected npm cache entry: {relative}")
            info = tarfile.TarInfo(str(Path("_cacache") / relative))
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ""
            info.mode = 0o700 if path.is_dir() else 0o600
            if path.is_dir():
                info.type = tarfile.DIRTYPE
                output.addfile(info)
            else:
                info.size = path.stat().st_size
                with path.open("rb") as source:
                    output.addfile(info, source)


def restore_cache_archive(artifact, destination):
    """Recreate the transfer input in a separate empty cache for proof."""
    with tarfile.open(artifact, "r") as archive:
        for entry in archive:
            path = Path(entry.name)
            if path.is_absolute() or ".." in path.parts or path.parts[0] != "_cacache":
                raise ValueError("unsafe npm cache archive path")
            target = destination / path
            if entry.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif entry.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(entry) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            else:
                raise ValueError("unexpected npm cache archive entry")


def project_lock(state):
    locks = list(state.glob("npm/projects/*/package-lock.json"))
    if len(locks) != 1:
        raise ValueError("expected exactly one managed Discord npm project lockfile")
    lock = json.loads(locks[0].read_text())
    package = lock["packages"]["node_modules/@openclaw/discord"]
    if (package.get("version"), package.get("integrity")) != ("2026.9.5", INTEGRITY):
        raise ValueError("managed npm project lockfile package integrity mismatch")
    return lock


def dependency_locks_match(warm, offline):
    """Compare the package closure, ignoring only npm's project-root name."""
    if not all(isinstance(lock.get("name"), str) and lock["name"] for lock in (warm, offline)):
        return False
    return {**warm, "name": None} == {**offline, "name": None}


def check_registry_integrity(raw):
    # npm 12 wraps even one exact-version --json result in a list.
    if json.loads(raw) not in (INTEGRITY, [INTEGRITY]):
        raise ValueError("npm registry integrity changed for pinned Discord package")


def verify_bundle(directory, root):
    """Verify the complete public package closure before publication or transfer."""
    check_image_contract(root)
    if not directory.is_dir() or directory.is_symlink() or set(
        path.name for path in directory.iterdir()
    ) != set(ARTIFACTS):
        raise ValueError("Discord cache artifact set changed")
    for name in ARTIFACTS:
        path = directory / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES[name]:
            raise ValueError("Discord cache artifact type or size changed")
    manifest = json.loads((directory / "manifest.json").read_text())
    if set(manifest) != {"schema", "image", "platform", "package", "npm_integrity",
                         "cache_sha256", "dependency_lock_sha256", "validation"} or not (
        manifest["schema"] == 1 and manifest["image"] == IMAGE and
        manifest["platform"] == "linux/amd64" and manifest["package"] == SPEC and
        manifest["npm_integrity"] == INTEGRITY and
        manifest["validation"] == "fresh-state-network-none-install-and-runtime-inspect"
    ):
        raise ValueError("Discord cache manifest contract changed")
    for name, field in (("npm-cache.tar", "cache_sha256"),
                        ("dependency-lock.json", "dependency_lock_sha256")):
        with (directory / name).open("rb") as content:
            if hashlib.file_digest(content, "sha256").hexdigest() != manifest[field]:
                raise ValueError("Discord cache artifact digest differs from manifest")
    lock = json.loads((directory / "dependency-lock.json").read_text())
    package = lock["packages"]["node_modules/@openclaw/discord"]
    if (package.get("version"), package.get("integrity")) != ("2026.9.5", INTEGRITY):
        raise ValueError("Discord dependency lock changed")
    seen = set()
    total = 0
    files = 0
    with tarfile.open(directory / "npm-cache.tar", "r") as archive:
        for member in archive:
            path = Path(member.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts or
                    path.parts[0] != "_cacache" or
                    path.as_posix() != member.name or path.as_posix() in seen or
                    not (member.isfile() or member.isdir())):
                raise ValueError("unsafe Discord npm cache entry")
            seen.add(path.as_posix())
            if member.isfile():
                files += 1
                total += member.size
                if total > MAX_BYTES["npm-cache.tar"]:
                    raise ValueError("Discord npm cache expands beyond limit")
    if files == 0:
        raise ValueError("Discord npm cache has no package content")
    return manifest


def build(output_dir, root):
    check_image_contract(root)
    if output_dir.exists():
        raise ValueError("output directory must be absent")
    output_dir.mkdir(mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix="openclaw-discord-cache-") as scratch:
            work = Path(scratch)
            for name in ("warm-home", "offline-home", "warm-state", "offline-state"):
                (work / name).mkdir(mode=0o700)

            run("docker", "pull", "--platform", "linux/amd64", IMAGE, capture=True)
            metadata = container(
                work, "warm-state", "warm-home",
                f"npm view {SPEC} dist.integrity --json",
                offline=False,
            ).stdout.strip()
            check_registry_integrity(metadata)

            install = f"openclaw plugins install npm:{SPEC} --pin --force --accept-capabilities"
            container(work, "warm-state", "warm-home", install, offline=False)
            warm_lock = project_lock(work / "warm-state")
            artifact = output_dir / "npm-cache.tar"
            # npm logs and notifier files are intentionally excluded from the closure.
            archive_cache(work / "warm-home" / ".npm" / "_cacache", artifact)
            restore_cache_archive(artifact, work / "offline-home" / ".npm")
            # The bind mount cannot expose the warm install to the offline container.
            for name in ("warm-state", "warm-home"):
                shutil.rmtree(work / name)
            if any((work / name).exists() for name in ("warm-state", "warm-home")):
                raise ValueError("warm OpenClaw state remains before offline proof")
            if any((work / "offline-state").iterdir()):
                raise ValueError("offline OpenClaw state is not fresh")
            container(work, "offline-state", "offline-home", install, offline=True)
            report = container(
                work, "offline-state", "offline-home",
                "openclaw plugins inspect discord --runtime --json",
                offline=True,
            )
            check_inspect(json.loads(report.stdout), work)
            offline_lock = project_lock(work / "offline-state")
            if not dependency_locks_match(warm_lock, offline_lock):
                raise ValueError("offline managed npm dependency tree differs from warm install")

            lock_bytes = (json.dumps(warm_lock, indent=2, sort_keys=True) + "\n").encode()
            lock_path = output_dir / "dependency-lock.json"
            lock_path.write_bytes(lock_bytes)
            os.chmod(lock_path, 0o600)

            with artifact.open("rb") as content:
                digest = hashlib.file_digest(content, "sha256").hexdigest()
            manifest = {
                "schema": 1,
                "image": IMAGE,
                "platform": "linux/amd64",
                "package": SPEC,
                "npm_integrity": INTEGRITY,
                "cache_sha256": digest,
                "dependency_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
                "validation": "fresh-state-network-none-install-and-runtime-inspect",
            }
            (output_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            )
            os.chmod(output_dir / "manifest.json", 0o600)
            verify_bundle(output_dir, root)
            print(json.dumps(manifest, sort_keys=True))
    except Exception:
        shutil.rmtree(output_dir)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        build(args.output_dir.resolve(), root)
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"offline Discord cache build failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            for output in (error.stdout, error.stderr):
                if output:
                    print(output, file=sys.stderr, end="" if output.endswith("\n") else "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
