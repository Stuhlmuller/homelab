#!/usr/bin/env python3
"""Prepare by default; publish only in the protected main-dispatch CI job."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
REPO = "Stuhlmuller/homelab"
SOURCE = f"https://github.com/{REPO}"
PACKAGE = "stuhlmuller/homelab-postgres-restore-drill"
REGISTRY = f"ghcr.io/{PACKAGE}"
WORKFLOW = f"{REPO}/.github/workflows/restore-image-publish.yml@refs/heads/main"
DIGEST = r"sha256:[0-9a-f]{64}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, headers):
    return urllib.request.build_opener(NoRedirect).open(
        urllib.request.Request(url, headers=headers), timeout=30)


def run(*command, **kwargs):
    return subprocess.run(command, check=True, text=True, timeout=600, **kwargs)


def context_guard(expected, environ):
    if (not re.fullmatch(r"[0-9a-f]{40}", expected)
            or environ.get("GITHUB_ACTIONS") != "true"
            or environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or environ.get("GITHUB_REPOSITORY") != REPO
            or environ.get("GITHUB_REF") != "refs/heads/main"
            or environ.get("GITHUB_SHA") != expected
            or environ.get("GITHUB_WORKFLOW_REF") != WORKFLOW):
        raise RuntimeError("Only an exact-main dispatch of the declared workflow is supported")


def verify_main(expected):
    context_guard(expected, os.environ)
    if run("git", "rev-parse", "HEAD", cwd=ROOT, capture_output=True).stdout.strip() != expected:
        raise RuntimeError("Checkout does not match dispatch")
    if run("git", "status", "--porcelain=v1", "--untracked-files=all", cwd=ROOT, capture_output=True).stdout:
        raise RuntimeError("Publishing requires a clean reviewed checkout")
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("CI credential missing; no local credential fallback")
    with request(f"https://api.github.com/repos/{REPO}/git/ref/heads/main",
                 {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}) as response:
        current = json.load(response)["object"]["sha"]
    if current != expected:
        raise RuntimeError("Dispatch is stale; current main changed")


def blob(layout, digest):
    if not re.fullmatch(DIGEST, digest):
        raise RuntimeError("Malformed OCI digest")
    body = (layout / "blobs" / "sha256" / digest.split(":")[1]).read_bytes()
    if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
        raise RuntimeError("OCI content digest mismatch")
    return body


def verified_manifest(layout, image):
    index = json.loads((layout / "index.json").read_bytes())
    if len(index["manifests"]) != 1:
        raise RuntimeError("Only the tested single-architecture image may be published")
    digest = index["manifests"][0]["digest"]
    raw = blob(layout, digest)
    manifest = json.loads(raw)
    if manifest["schemaVersion"] != 2 or manifest["config"]["digest"] != image.image_id:
        raise RuntimeError("OCI export does not match the tested Docker image")
    config = json.loads(blob(layout, image.image_id))
    labels = config["config"]["Labels"]
    if (config["architecture"] != "amd64" or config["os"] != "linux"
            or labels.get("org.opencontainers.image.source") != SOURCE
            or labels.get("org.opencontainers.image.revision") != image.source_sha):
        raise RuntimeError("OCI source/platform identity mismatch")
    for layer in manifest["layers"]:
        blob(layout, layer["digest"])
    return digest, raw


class Registry:
    def __init__(self):
        # GHCR challenge verified for this fixed namespace; never follow an arbitrary realm.
        credential = f"{os.environ['GITHUB_ACTOR']}:{os.environ['GH_TOKEN']}".encode()
        scope = urllib.parse.urlencode({"service": "ghcr.io", "scope": f"repository:{PACKAGE}:pull,push"})
        with request(f"https://ghcr.io/token?{scope}", {
            "Authorization": "Basic " + base64.b64encode(credential).decode()
        }) as response:
            self.token = json.load(response)["token"]
        if not isinstance(self.token, str) or not self.token:
            raise RuntimeError("Registry authentication failed")

    def manifest(self, reference):
        headers = {"Authorization": f"Bearer {self.token}", "Accept":
                   "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"}
        try:
            with request(f"https://ghcr.io/v2/{PACKAGE}/manifests/{reference}", headers) as response:
                body = response.read()
                digest = response.headers.get("Docker-Content-Digest")
                if digest != "sha256:" + hashlib.sha256(body).hexdigest():
                    raise RuntimeError("Registry response digest mismatch")
                return digest, body
        except urllib.error.HTTPError as error:
            with error:
                if error.code == 404:
                    errors = json.loads(error.read()).get("errors", [])
                    if errors and all(item.get("code") in {"MANIFEST_UNKNOWN", "NAME_UNKNOWN"} for item in errors):
                        return None
            raise RuntimeError("Registry lookup failed; absence not established") from None


def publish_candidate(registry, tag, candidate, push):
    existing = registry.manifest(tag)
    if existing is not None and existing != candidate:
        raise RuntimeError("Existing source tag differs; refusing overwrite")
    if existing is None:
        push()
    if registry.manifest(tag) != candidate or registry.manifest(candidate[0]) != candidate:
        raise RuntimeError("Published tag/digest readback failed; do not deploy")


def load_boundary():
    spec = importlib.util.spec_from_file_location("restore_egress", ROOT / "scripts/ci/restore-egress-check.py")
    boundary = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = boundary
    spec.loader.exec_module(boundary)
    return boundary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--expected-digest")
    args = parser.parse_args()
    if args.publish and not re.fullmatch(DIGEST, args.expected_digest or ""):
        raise RuntimeError("Publication needs the protected workflow's prepare digest")
    verify_main(args.expected_sha)
    boundary = load_boundary()
    with boundary.verified_image() as image, tempfile.TemporaryDirectory(prefix="restore-publication-") as directory:
        if image.source_sha != args.expected_sha:
            raise RuntimeError("Tested source changed")
        scratch = Path(directory)
        layout = scratch / "oci"
        run("skopeo", "copy", f"docker-daemon:{image.image_id}", f"oci:{layout}:candidate")
        candidate = verified_manifest(layout, image)
        if args.publish:
            if candidate[0] != args.expected_digest:
                raise RuntimeError("Rebuilt tested digest differs from reviewed prepare result")
            # Authentication starts only after all image tests and identity checks pass.
            verify_main(args.expected_sha)
            registry = Registry()
            tag = f"git-{args.expected_sha}-amd64"

            def push():
                auth = scratch / "auth.json"
                run("skopeo", "login", "--authfile", str(auth), "--username", os.environ["GITHUB_ACTOR"],
                    "--password-stdin", "ghcr.io", input=os.environ["GH_TOKEN"] + "\n",
                    stdout=subprocess.DEVNULL)
                verify_main(args.expected_sha)
                run("skopeo", "copy", "--authfile", str(auth), "--preserve-digests",
                    f"oci:{layout}:candidate", f"docker://{REGISTRY}:{tag}")

            publish_candidate(registry, tag, candidate, push)
            receipt = {"source": args.expected_sha, "image": f"{REGISTRY}@{candidate[0]}",
                       "config_digest": image.image_id, "architecture": "amd64",
                       "public_pull_verified": False, "production_runtime_verified": False}
            print(json.dumps(receipt, sort_keys=True))
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
                summary.write(f"Tested source `{args.expected_sha}` published as `{REGISTRY}@{candidate[0]}`.\n\n"
                              "Public pull and Talos synthetic-runtime gates remain unverified. No workload changed.\n")
        else:
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                output.write(f"image_digest={candidate[0]}\n")
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
                summary.write(f"Reviewed source `{args.expected_sha}` prepared and tested as `{candidate[0]}`.\n")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.SubprocessError):
        # Do not leak authentication responses or subprocess inputs into a public log.
        raise SystemExit("Restore image preparation/publication failed; no deployment is authorized") from None
