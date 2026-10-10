"""Back up an offline Valkey AOF set and inspect repair on a private copy only."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

if not __debug__:
    raise RuntimeError("Recovery guards require Python assertions enabled")

ROOT = Path(__file__).resolve().parents[1]
WRITERS = ("langfuse-web", "langfuse-worker", "langfuse-valkey")
IMAGE = "docker.io/valkey/valkey:8.0@sha256:4436c94fc34ce4af0354b9379d433a1f258998fb955f995c89822f98c14a8cab"


def output(*args, timeout=30):
    return subprocess.check_output(args, text=True, timeout=timeout, stderr=subprocess.DEVNULL)


def offline_pod(deployments, pods):
    assert {item["metadata"]["name"] for item in deployments} == set(WRITERS)
    for item in deployments:
        assert item["spec"]["replicas"] == 0
        assert item["status"].get("observedGeneration", 0) >= item["metadata"]["generation"]
        assert item["status"].get("replicas", 0) == 0
    active = [pod for pod in pods if pod["status"]["phase"] not in ("Succeeded", "Failed")]
    inspectors = [pod for pod in active if pod["metadata"].get("labels", {}).get(
        "app.kubernetes.io/name") == "langfuse-valkey-inspection"]
    assert len(inspectors) == 1
    inspector = inspectors[0]
    for pod in active:
        if pod is inspector:
            continue
        assert not any(pod["metadata"]["name"].startswith(name + "-") for name in WRITERS)
        assert not any(v.get("persistentVolumeClaim", {}).get("claimName") == "langfuse-valkey-data"
                       for v in pod["spec"].get("volumes", []))
    assert not inspector["metadata"].get("deletionTimestamp")
    assert inspector["status"]["phase"] == "Running"
    assert len(inspector["status"]["containerStatuses"]) == 1
    assert all(c["ready"] for c in inspector["status"]["containerStatuses"])
    spec = inspector["spec"]
    assert spec["automountServiceAccountToken"] is False
    assert len(spec["containers"]) == 1 and not spec.get("initContainers")
    container = spec["containers"][0]
    assert container["image"] == IMAGE
    assert container["command"] == ["/bin/sh", "-ec", "exec sleep infinity"]
    mount = next(m for m in container["volumeMounts"] if m["mountPath"] == "/source")
    volume = next(v for v in spec["volumes"] if v["name"] == mount["name"])
    assert mount["readOnly"] is True
    assert volume["persistentVolumeClaim"] == {"claimName": "langfuse-valkey-data", "readOnly": True}
    return inspector["metadata"]["name"], inspector["metadata"]["uid"]


def capture(directory, expected_sha):
    assert re.fullmatch(r"[0-9a-f]{40}", expected_sha or "")
    assert output("git", "-C", str(ROOT), "rev-parse", "HEAD").strip() == expected_sha
    assert output("gh", "api", "repos/Stuhlmuller/homelab/commits/main", "--jq", ".sha").strip() == expected_sha
    assert not output("git", "-C", str(ROOT), "status", "--porcelain")
    assert output("kubectl", "config", "view", "--minify", "-o",
                  "jsonpath={.clusters[0].cluster.server}") == "https://10.1.0.199:6443"

    def guard():
        deployments = json.loads(output("kubectl", "-n", "langfuse", "get", "deployments", *WRITERS, "-o", "json"))
        pods = json.loads(output("kubectl", "-n", "langfuse", "get", "pods", "-o", "json"))
        return offline_pod(deployments["items"], pods["items"])

    pod, uid = guard()
    command = ["kubectl", "-n", "langfuse", "exec", pod, "-c", "inspection", "--"]

    def hashes():
        lines = output(*command, "sh", "-ec", "cd /source && find . -type f -exec sha256sum {} +",
                       timeout=300).splitlines()
        result = {}
        for line in lines:
            match = re.fullmatch(r"([0-9a-f]{64})  \./([A-Za-z0-9_./-]+)", line)
            assert match and ".." not in Path(match[2]).parts
            result[match[2]] = match[1]
        assert result
        return result

    before = hashes()
    size = int(output(*command, "du", "-sb", "/source").split()[0])
    assert shutil.disk_usage(directory.parent).free > size * 5 + 64 * 1024 * 1024
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    archive = directory / "original.tar"
    with archive.open("xb") as stream:
        subprocess.run([*command, "tar", "-C", "/source", "-cf", "-", "."],
                       stdout=stream, stderr=subprocess.DEVNULL, timeout=300, check=True)
    assert guard() == (pod, uid) and hashes() == before
    source = directory / "source"
    source.mkdir(mode=0o700)
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            assert member.isfile() or member.isdir()
            assert not Path(member.name).is_absolute() and ".." not in Path(member.name).parts
        bundle.extractall(source, filter="data")
    assert {name: entry["sha256"] for name, entry in fingerprint(source).items()} == before
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (directory / "original.tar.sha256").write_text(digest + "  original.tar\n")
    return source


def fingerprint(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Recovery source contains unsupported file types")
        if path.is_file():
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            result[str(path.relative_to(directory))] = {
                "bytes": path.stat().st_size, "sha256": digest}
    if not result:
        raise ValueError("Recovery source is empty")
    return result


def prepare(source, destination, checker):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Backup must be outside the source directory")
    manifest = Path("appendonlydir/appendonly.aof.manifest")
    if not (source / manifest).is_file():
        raise ValueError("Expected multipart AOF manifest is missing")
    before = fingerprint(source)
    entries = (source / manifest).read_text().splitlines()
    if not entries:
        raise ValueError("AOF manifest is empty")
    for entry in entries:
        match = re.fullmatch(r"file ([A-Za-z0-9_.-]+) seq [0-9]+ type [bih]", entry)
        if not match or match[1] in (".", ".."):
            raise ValueError("AOF manifest contains an unsupported member reference")
        if str(manifest.parent / match[1]) not in before:
            raise ValueError("AOF manifest member is missing")
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    original, candidate = destination / "original", destination / "candidate"
    shutil.copytree(source, original)
    if fingerprint(original) != before or fingerprint(source) != before:
        raise ValueError("Source changed during backup; retained copy is not accepted")
    shutil.copytree(original, candidate)

    def check(name, fix=False):
        with (destination / name).open("xb") as log:
            return subprocess.run(
                [checker, *(["--fix"] if fix else []), str(candidate / manifest)],
                input=b"y\n" if fix else b"", stdout=log, stderr=subprocess.STDOUT,
                cwd=candidate / manifest.parent, timeout=300, check=False).returncode

    needed_repair = check("check-before.log") != 0
    if needed_repair and check("repair-copy.log", fix=True) != 0:
        raise ValueError("Candidate repair failed; source and backup retained")
    if check("check-after.log") != 0:
        raise ValueError("Candidate remains invalid; source and backup retained")
    after = fingerprint(candidate)
    if fingerprint(source) != before or fingerprint(original) != before:
        raise ValueError("Source or backup changed; candidate is not accepted")
    report = {
        "source_unchanged": True, "backup_verified": True,
        "candidate_valid": True, "needed_repair": needed_repair,
        "before": before, "candidate": after,
        "discarded_bytes": sum(max(0, entry["bytes"] - after.get(name, {}).get("bytes", 0))
                               for name, entry in before.items()),
        "live_replacement_authorized": False,
    }
    with (destination / "report.json").open("x") as stream:
        json.dump(report, stream, indent=2)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source", type=Path)
    source_group.add_argument("--capture-cluster", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--checker", default="valkey-check-aof")
    args = parser.parse_args()
    try:
        source = capture(args.destination, args.expected_sha) if args.capture_cluster else args.source
        destination = args.destination / "inspection" if args.capture_cluster else args.destination
        result = prepare(source, destination, args.checker)
    except (AssertionError, KeyError, StopIteration, OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
        raise SystemExit("Copy inspection failed; private files retained; source not repaired") from None
    print(f"Candidate validated; discarded bytes: {result['discarded_bytes']}; source not repaired")
