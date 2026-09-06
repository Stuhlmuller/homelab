#!/usr/bin/env python3
"""Verify the committed restore image contract, then pull all image bytes anonymously."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PIN = Path("images/postgres-restore-egress/published-image.json")
REPO = "Stuhlmuller/homelab"
SOURCE = f"https://github.com/{REPO}"
WORKFLOW = ".github/workflows/restore-image-publish.yml"
DIGEST = r"sha256:[0-9a-f]{64}"
COMPONENT = r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
IMAGE = rf"[a-z0-9]+(?:[.-][a-z0-9]+)+(?::[1-9][0-9]{{0,4}})?/{COMPONENT}(?:/{COMPONENT})*@{DIGEST}"
FORMATS = {
    "application/vnd.docker.distribution.manifest.v2+json": (
        "application/vnd.docker.container.image.v1+json",
        {"application/vnd.docker.image.rootfs.diff.tar.gzip"}),
    "application/vnd.oci.image.manifest.v1+json": (
        "application/vnd.oci.image.config.v1+json",
        {"application/vnd.oci.image.layer.v1.tar", "application/vnd.oci.image.layer.v1.tar+gzip",
         "application/vnd.oci.image.layer.v1.tar+zstd"}),
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique_object)


def parse_contract(raw):
    contract = decode(raw)
    if (not isinstance(contract, dict) or set(contract) != {
            "version", "image", "config_digest", "source_commit", "source_url", "os", "architecture", "publication"}
            or type(contract["version"]) is not int or contract["version"] != 1
            or any(not isinstance(contract[key], str) for key in contract if key not in {"version", "publication"})
            or not re.fullmatch(IMAGE, contract["image"])
            or not re.fullmatch(DIGEST, contract["config_digest"])
            or not re.fullmatch(r"[0-9a-f]{40}", contract["source_commit"])
            or contract["source_url"] != SOURCE or contract["os"] != "linux"
            or contract["architecture"] != "amd64"):
        raise ValueError("Invalid committed image contract")
    publication = contract["publication"]
    if (not isinstance(publication, dict) or set(publication) != {"run_id", "run_attempt"}
            or any(type(value) is not int or not 1 <= value <= 2**63 - 1 for value in publication.values())):
        raise ValueError("Invalid publication run contract")
    return contract


def child_environment(scratch):
    home = scratch / "home"
    config = home / ".config"
    config.mkdir(parents=True)
    runtime = scratch / "runtime"
    runtime.mkdir()
    # Construct only the child environment; never change the caller's environment.
    return {"PATH": os.defpath, "HOME": str(home), "XDG_CONFIG_HOME": str(config),
            "XDG_RUNTIME_DIR": str(runtime), "LANG": "C", "TMPDIR": str(scratch)}


def check_publication_metadata(metadata, contract):
    publication = contract["publication"]
    expected = {"id": publication["run_id"], "run_attempt": publication["run_attempt"],
                "head_sha": contract["source_commit"], "head_branch": "main", "event": "workflow_dispatch",
                "path": WORKFLOW, "status": "completed", "conclusion": "success"}
    if (not isinstance(metadata, dict)
            or any(type(metadata.get(key)) is not type(value) or metadata.get(key) != value
                   for key, value in expected.items())
            or any(not isinstance(metadata.get(key), dict) or metadata[key].get("full_name") != REPO
                   for key in ("repository", "head_repository"))):
        raise ValueError("Publication run/source metadata mismatch")


def verify_publication(contract):
    executable = shutil.which("curl")
    if executable is None:
        raise RuntimeError("Use the repository-locked toolchain")
    publication = contract["publication"]
    url = (f"https://api.github.com/repos/{REPO}/actions/runs/{publication['run_id']}"
           f"/attempts/{publication['run_attempt']}")
    with tempfile.TemporaryDirectory(prefix="restore-publication-read-") as directory:
        scratch = Path(directory)
        env = child_environment(scratch)
        response = scratch / "attempt.json"
        # --disable is first to ignore curlrc; no redirects, netrc, proxies or auth.
        result = subprocess.run([executable, "--disable", "--silent", "--proto", "=https", "--noproxy", "*",
                                 "--connect-timeout", "15", "--max-time", "30", "--max-filesize", "1048576",
                                 "--output", str(response), "--write-out", "%{http_code}",
                                 "--header", "Accept: application/vnd.github+json",
                                 "--header", "X-GitHub-Api-Version: 2022-11-28",
                                 "--user-agent", "homelab-restore-image-verifier", url],
                                env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                check=True, timeout=35)
        if result.stdout != "200" or not response.is_file() or response.stat().st_size > 1048576:
            raise ValueError("Public publication metadata unavailable; redirects are not followed")
        check_publication_metadata(decode(response.read_bytes()), contract)


def read_contract(root=ROOT):
    # Missing/invalid pin fails before even looking up Skopeo or touching the network.
    path = root / PIN
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
        raise ValueError("Reviewed published-image pin is absent or invalid")
    raw = path.read_bytes()
    contract = parse_contract(raw)
    committed = subprocess.run(["git", "show", f"HEAD:{PIN.as_posix()}"], cwd=root,
                               check=True, capture_output=True, timeout=30).stdout
    dirty = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all", "--", str(PIN)],
                           cwd=root, check=True, capture_output=True, timeout=30).stdout
    if committed != raw or dirty:
        raise ValueError("Image pin must be committed and unchanged")
    return contract


def checked_file(path, expected, size=None, limit=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Image content is missing or not a regular file")
    actual_size = path.stat().st_size
    if (size is not None and actual_size != size) or (limit is not None and actual_size > limit):
        raise ValueError("Image content size mismatch")
    with path.open("rb") as stream:
        actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError("Image content digest mismatch")


def verify_layout(layout, contract):
    expected = contract["image"].split("@", 1)[1]
    manifest_path = layout / "manifest.json"
    checked_file(manifest_path, expected, limit=4 * 1024 * 1024)
    manifest = decode(manifest_path.read_bytes())
    if (not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2 or manifest.get("mediaType") not in FORMATS
            or "manifests" in manifest or "subject" in manifest):
        raise ValueError("Only a single image manifest is supported")
    config_type, layer_types = FORMATS[manifest["mediaType"]]
    if not isinstance(manifest.get("layers"), list) or not 1 <= len(manifest["layers"]) <= 128:
        raise ValueError("Invalid image layers")
    descriptors = [manifest["config"], *manifest["layers"]]
    for index, descriptor in enumerate(descriptors):
        if (not isinstance(descriptor, dict) or "urls" in descriptor or "data" in descriptor
                or not isinstance(descriptor.get("digest"), str)
                or not re.fullmatch(DIGEST, descriptor["digest"])
                or type(descriptor.get("size")) is not int or descriptor["size"] < 0
                or descriptor.get("mediaType") not in ({config_type} if index == 0 else layer_types)):
            raise ValueError("Unsupported image descriptor")
        checked_file(layout / descriptor["digest"].split(":", 1)[1], descriptor["digest"], descriptor["size"])
    if manifest["config"]["digest"] != contract["config_digest"]:
        raise ValueError("Image config differs from reviewed publication")
    config_path = layout / contract["config_digest"].split(":", 1)[1]
    if config_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Oversized image config")
    config = decode(config_path.read_bytes())
    if (not isinstance(config, dict) or not isinstance(config.get("config"), dict)
            or not isinstance(config["config"].get("Labels"), dict)):
        raise ValueError("Image source labels missing")
    labels = config["config"]["Labels"]
    if (config.get("os") != contract["os"] or config.get("architecture") != contract["architecture"]
            or labels.get("org.opencontainers.image.source") != contract["source_url"]
            or labels.get("org.opencontainers.image.revision") != contract["source_commit"]):
        raise ValueError("Image source/platform mismatch")
    return {**contract, "anonymous_pull_verified": True}


def pull(contract):
    executable = shutil.which("skopeo")
    if executable is None:
        raise RuntimeError("Use the repository-locked Skopeo shell")
    with tempfile.TemporaryDirectory(prefix="restore-anonymous-") as directory:
        scratch = Path(directory)
        env = child_environment(scratch)
        containers = Path(env["XDG_CONFIG_HOME"]) / "containers"
        containers.mkdir()
        # A user config takes precedence AND excludes system registry drop-ins.
        (containers / "registries.conf").write_text('unqualified-search-registries = []\n')
        for name in ("registries.conf.d", "registries.d", "certs.d"):
            (containers / name).mkdir()
        auth = containers / "auth.json"
        auth.write_text('{"auths":{}}\n')
        policy = containers / "policy.json"
        # Digest/source binding is enforced below; no claim of publisher signatures.
        policy.write_text('{"default":[{"type":"reject"}],"transports":{"docker":{' +
                          json.dumps(contract["image"].split("@", 1)[0]) +
                          ':[{"type":"insecureAcceptAnything"}]}}}\n')
        layout = scratch / "image"
        # No host environment, auth helpers, proxy credentials, custom certs or mirrors.
        subprocess.run([executable, "--policy", str(policy), "--registries.d", str(containers / "registries.d"),
                        "--override-os", "linux", "--override-arch", "amd64", "--command-timeout", "10m",
                        "copy", "--src-no-creds", "--src-authfile", str(auth), "--dest-authfile", str(auth),
                        "--src-cert-dir", str(containers / "certs.d"), "--src-tls-verify=true",
                        "--preserve-digests", "--quiet", f"docker://{contract['image']}", f"dir:{layout}"],
                       env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=620)
        return verify_layout(layout, contract)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-contract", action="store_true", help="Validate committed pin only; no network")
    args = parser.parse_args()
    contract = read_contract()
    if args.check_contract:
        result = contract
    else:
        verify_publication(contract)
        result = {**pull(contract), "publication_metadata_verified": True}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        raise SystemExit("Anonymous restore image verification failed; no runtime validation is authorized") from None
