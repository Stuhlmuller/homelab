"""Inspect offline Valkey copies; promote only an explicitly approved repair."""

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


def offline_pod(deployments, pods, writable=False):
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
    # Kubernetes omits default-false fields in live Pod JSON.
    assert mount.get("readOnly", False) is (not writable)
    claim = volume["persistentVolumeClaim"]
    assert claim["claimName"] == "langfuse-valkey-data"
    assert claim.get("readOnly", False) is (not writable)
    return inspector["metadata"]["name"], inspector["metadata"]["uid"]


def release_guard(expected_sha):
    assert re.fullmatch(r"[0-9a-f]{40}", expected_sha or "")
    assert output("git", "-C", str(ROOT), "rev-parse", "HEAD").strip() == expected_sha
    assert output("gh", "api", "repos/Stuhlmuller/homelab/commits/main", "--jq", ".sha").strip() == expected_sha
    assert not output("git", "-C", str(ROOT), "status", "--porcelain")
    assert output("kubectl", "config", "view", "--minify", "-o",
                  "jsonpath={.clusters[0].cluster.server}") == "https://10.1.0.199:6443"


def cluster_guard(writable=False):
    deployments = json.loads(output("kubectl", "-n", "langfuse", "get", "deployments", *WRITERS, "-o", "json"))
    pods = json.loads(output("kubectl", "-n", "langfuse", "get", "pods", "-o", "json"))
    return offline_pod(deployments["items"], pods["items"], writable)


def remote_hashes(command):
    assert not output(*command, "find", "/source", "!", "-type", "f", "!", "-type", "d").strip()
    lines = output(*command, "sh", "-ec", "cd /source && find . -type f -exec sha256sum {} +",
                   timeout=300).splitlines()
    result = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  \./([A-Za-z0-9_./-]+)", line)
        assert match and ".." not in Path(match[2]).parts and match[2] not in result
        result[match[2]] = match[1]
    assert result
    return result


def capture(directory, expected_sha):
    release_guard(expected_sha)

    pod, uid = cluster_guard()
    command = ["kubectl", "-n", "langfuse", "exec", pod, "-c", "inspection", "--"]

    before = remote_hashes(command)
    size = int(output(*command, "du", "-sb", "/source").split()[0])
    assert shutil.disk_usage(directory.parent).free > size * 5 + 64 * 1024 * 1024
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    archive = directory / "original.tar"
    with archive.open("xb") as stream:
        subprocess.run([*command, "tar", "-C", "/source", "-cf", "-", "."],
                       stdout=stream, stderr=subprocess.DEVNULL, timeout=300, check=True)
    assert cluster_guard() == (pod, uid) and remote_hashes(command) == before
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


def promotion_source(directory, approved_discarded_bytes):
    """Accept only the captured archive and one prefix-preserving AOF truncation."""
    assert directory.stat().st_mode & 0o077 == 0
    report = json.loads((directory / "inspection/report.json").read_text())
    assert all(report[key] is True for key in ("source_unchanged", "backup_verified", "candidate_valid"))
    before, after = report["before"], report["candidate"]
    assert fingerprint(directory / "source") == fingerprint(directory / "inspection/original") == before
    assert fingerprint(directory / "inspection/candidate") == after
    assert before.keys() == after.keys()
    changed = [name for name in before if before[name] != after[name]]
    assert len(changed) == 1
    name = changed[0]
    assert re.fullmatch(r"appendonlydir/appendonly\.aof\.[0-9]+\.incr\.aof", name)
    lost = before[name]["bytes"] - after[name]["bytes"]
    assert lost > 0 and lost == report["discarded_bytes"] == approved_discarded_bytes
    candidate = directory / "inspection/candidate" / name
    with (directory / "source" / name).open("rb") as original, candidate.open("rb") as repaired:
        while chunk := repaired.read(1024 * 1024):
            assert original.read(len(chunk)) == chunk
    archive = directory / "original.tar"
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    assert (directory / "original.tar.sha256").read_text() == digest + "  original.tar\n"
    archived = {}
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            path = Path(member.name)
            assert not path.is_absolute() and ".." not in path.parts
            assert member.isfile() or member.isdir()
            if member.isfile():
                assert str(path) not in archived
                with bundle.extractfile(member) as stream:
                    archived[str(path)] = {"bytes": member.size,
                                          "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}
    assert archived == before
    return name, candidate, {key: entry["sha256"] for key, entry in before.items()}, {
        key: entry["sha256"] for key, entry in after.items()}


def promote(directory, expected_sha, approved_discarded_bytes):
    release_guard(expected_sha)
    name, candidate, before, after = promotion_source(directory, approved_discarded_bytes)
    pod, uid = cluster_guard(writable=True)
    command = ["kubectl", "-n", "langfuse", "exec", pod, "-c", "inspection", "--"]
    stage = str(Path(name).parent / (".homelab-repaired-" + after[name]))

    def current():
        # A failed upload is safe to overwrite; never the original.
        return {key: value for key, value in remote_hashes(command).items() if key != stage}

    observed = current()
    if observed == after:
        assert cluster_guard(writable=True) == (pod, uid)
        assert remote_hashes(command) == after
        return
    assert observed == before
    with candidate.open("rb") as stream:
        subprocess.run(["kubectl", "-n", "langfuse", "exec", "-i", pod, "-c", "inspection", "--",
                        "sh", "-ec", '''
umask 077
test ! -L "$1"
if test -e "$1"; then
    test -f "$1"
    test "$(stat -c %h "$1")" = 1
fi
cat > "$1"
sync "$1"
''',
                        "--", "/source/" + stage], stdin=stream, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=300, check=True)
    assert cluster_guard(writable=True) == (pod, uid) and current() == before
    assert remote_hashes(command)[stage] == after[name]
    release_guard(expected_sha)
    output(*command, "sh", "-ec", '''
test ! -L "$1"
test ! -L "$2"
test "$(sha256sum "$1" | cut -d ' ' -f 1)" = "$3"
test "$(sha256sum "$2" | cut -d ' ' -f 1)" = "$4"
mv -T -- "$2" "$1"
sync /source/appendonlydir
''', "--", "/source/" + name, "/source/" + stage, before[name], after[name], timeout=300)
    assert cluster_guard(writable=True) == (pod, uid) and remote_hashes(command) == after


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source", type=Path)
    source_group.add_argument("--capture-cluster", action="store_true")
    source_group.add_argument("--promote-cluster", type=Path, metavar="CAPTURE_DIRECTORY")
    parser.add_argument("--expected-sha")
    parser.add_argument("--approved-discarded-bytes", type=int)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--checker", default="valkey-check-aof")
    args = parser.parse_args()
    if args.promote_cluster:
        if args.destination is not None or args.approved_discarded_bytes is None:
            parser.error("Promotion requires explicit --approved-discarded-bytes and no --destination")
        try:
            promote(args.promote_cluster, args.expected_sha, args.approved_discarded_bytes)
        except (AssertionError, KeyError, StopIteration, OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
            raise SystemExit("Promotion failed; keep writers stopped and all backups; rerun only after inspection") from None
        print("Approved candidate is installed and hashes verified; writers remain stopped")
        raise SystemExit(0)
    if args.destination is None or args.approved_discarded_bytes is not None:
        parser.error("Copy inspection requires --destination and no promotion approval")
    try:
        source = capture(args.destination, args.expected_sha) if args.capture_cluster else args.source
        destination = args.destination / "inspection" if args.capture_cluster else args.destination
        result = prepare(source, destination, args.checker)
    except (AssertionError, KeyError, StopIteration, OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
        raise SystemExit("Copy inspection failed; private files retained; source not repaired") from None
    print(f"Candidate validated; discarded bytes: {result['discarded_bytes']}; source not repaired")
