#!/usr/bin/env python3
"""Import and verify bounded protected native Chainguard receipt artifacts."""

import argparse
import base64
import copy
import hashlib
import importlib.util
import io
import json
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTOMATION = ROOT / "clusters/homelab/apps/harbor/image-automation.json"
REPLICATION = ROOT / "clusters/homelab/apps/harbor/chainguard-replication.json"
CATALOG = ROOT / "scripts/config/harbor-chainguard-images.json"
STATE = ROOT / "scripts/config/image-automation-state.json"
STATE_PATH = "scripts/config/image-automation-state.json"
REPOSITORY = "Stuhlmuller/homelab"
WORKFLOW_PATH = ".github/workflows/harbor-native-chainguard-receipt.yml"
ARTIFACT_PREFIX = "harbor-native-chainguard-receipt-"
RECEIPT_FILE = "harbor-native-chainguard-receipt.json"
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")

NATIVE_RECEIPT_SPEC = importlib.util.spec_from_file_location(
    "harbor_native_chainguard_receipt", Path(__file__).with_name("harbor-native-chainguard-receipt.py")
)
NATIVE_RECEIPT = importlib.util.module_from_spec(NATIVE_RECEIPT_SPEC)
NATIVE_RECEIPT_SPEC.loader.exec_module(NATIVE_RECEIPT)


class ImportError(ValueError):
    """Protected receipt provenance did not meet the fixed contract."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def require(condition, message):
    if not condition:
        raise ImportError(message)


def digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def read_json(path, limit=MAX_ARTIFACT_BYTES):
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise ImportError("receipt input is unavailable") from error
    require(len(raw) <= limit, "receipt input exceeds its fixed size limit")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImportError("receipt input is not valid JSON") from error


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def json_bytes(raw, message):
    require(len(raw) <= MAX_RECEIPT_BYTES, "receipt JSON exceeds its fixed size limit")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ImportError(message) from None


def native_plans(config):
    return {
        plan["image_id"]: plan for plan in NATIVE_RECEIPT.build_plan(
            config, NATIVE_RECEIPT.read_json(REPLICATION), NATIVE_RECEIPT.read_json(CATALOG)
        )
    }


def valid_provenance(value):
    fields = {"repository", "workflow_path", "workflow_id", "run_id", "artifact_id", "artifact_sha256"}
    return (
        isinstance(value, dict)
        and set(value) == fields
        and value.get("repository") == REPOSITORY
        and value.get("workflow_path") == WORKFLOW_PATH
        and all(type(value.get(key)) is int and value[key] > 0 for key in ("workflow_id", "run_id", "artifact_id"))
        and isinstance(value.get("artifact_sha256"), str)
        and SHA256.fullmatch(value["artifact_sha256"]) is not None
    )


def verify_imported_receipt(plan, value):
    if not isinstance(value, dict) or set(value) != {"receipt", "provenance"}:
        return False, "native receipt import fields are incomplete or unknown"
    if not valid_provenance(value["provenance"]):
        return False, "native receipt provenance is invalid"
    return NATIVE_RECEIPT.verify_native_receipt(plan, value["receipt"])


def receipt_envelope(value, expected_sha, plans):
    fields = {"schema_version", "kind", "repository_sha", "receipts"}
    require(isinstance(value, dict) and set(value) == fields, "native receipt artifact envelope is invalid")
    require(value.get("schema_version") == 1 and value.get("kind") == "native-chainguard-receipts-v1"
            and value.get("repository_sha") == expected_sha and isinstance(value.get("receipts"), list),
            "native receipt artifact envelope does not match the expected revision")
    receipts = {}
    for receipt in value["receipts"]:
        require(isinstance(receipt, dict) and isinstance(receipt.get("image_id"), str),
                "native receipt artifact has an invalid image identifier")
        image_id = receipt["image_id"]
        require(image_id in plans and image_id not in receipts, "native receipt artifact image set is invalid")
        valid, reason = NATIVE_RECEIPT.verify_native_receipt(plans[image_id], receipt)
        require(valid and receipt.get("repository_sha") == expected_sha, reason)
        receipts[image_id] = receipt
    require(set(receipts) == set(plans), "native receipt artifact is incomplete")
    return receipts


class GitHubActionsClient:
    """Small read-only GitHub Actions API client that never forwards a token to redirects."""

    def __init__(self, token=None):
        require(token is None or (isinstance(token, str) and token and not any(c.isspace() for c in token)),
                "GitHub token is invalid")
        self.token = token
        self.api = "https://api.github.com"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.no_redirect = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def headers(self):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "homelab-native-chainguard-receipt-importer",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def json(self, path):
        request = urllib.request.Request(self.api + path, headers=self.headers(), method="GET")
        try:
            with self.opener.open(request, timeout=20) as response:
                require(response.status == 200, "GitHub Actions metadata request was rejected")
                raw = response.read(MAX_ARTIFACT_BYTES + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            raise ImportError("GitHub Actions metadata request failed") from None
        require(len(raw) <= MAX_ARTIFACT_BYTES, "GitHub Actions metadata response exceeded its limit")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ImportError("GitHub Actions metadata response is malformed") from None

    def download(self, path):
        request = urllib.request.Request(self.api + path, headers=self.headers(), method="GET")
        location = None
        try:
            response = self.no_redirect.open(request, timeout=20)
            response.close()
            raise ImportError("GitHub receipt artifact download did not redirect")
        except urllib.error.HTTPError as error:
            if error.code != 302:
                error.close()
                raise ImportError("GitHub receipt artifact download was rejected") from None
            location = error.headers.get("Location")
            error.close()
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ImportError("GitHub receipt artifact download failed") from None
        require(isinstance(location, str) and urllib.parse.urlsplit(location).scheme == "https",
                "GitHub receipt artifact redirect is invalid")
        request = urllib.request.Request(location, headers={"User-Agent": self.headers()["User-Agent"]}, method="GET")
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(MAX_ARTIFACT_BYTES + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            raise ImportError("GitHub receipt artifact download failed") from None
        require(len(raw) <= MAX_ARTIFACT_BYTES, "GitHub receipt artifact exceeds its fixed size limit")
        return raw

    def content(self, repository, path, revision):
        require(repository == REPOSITORY and path == STATE_PATH and SHA.fullmatch(revision) is not None,
                "pull request state lookup is invalid")
        encoded_path = urllib.parse.quote(path, safe="/")
        value = self.json(f"/repos/{repository}/contents/{encoded_path}?ref={revision}")
        require(isinstance(value, dict) and value.get("type") == "file" and value.get("path") == path
                and value.get("encoding") == "base64" and type(value.get("size")) is int
                and 0 <= value["size"] <= MAX_RECEIPT_BYTES and isinstance(value.get("content"), str),
                "pull request state response is malformed")
        try:
            raw = base64.b64decode("".join(value["content"].splitlines()), validate=True)
        except (ValueError, UnicodeError):
            raise ImportError("pull request state response is not base64") from None
        require(len(raw) == value["size"] and len(raw) <= MAX_RECEIPT_BYTES,
                "pull request state response exceeds its fixed size limit")
        return json_bytes(raw, "pull request state response is not JSON")

    def compare(self, repository, base_sha, head_sha):
        require(repository == REPOSITORY and SHA.fullmatch(base_sha) is not None and SHA.fullmatch(head_sha) is not None,
                "pull request comparison is invalid")
        value = self.json(f"/repos/{repository}/compare/{base_sha}...{head_sha}")
        merge_base = value.get("merge_base_commit") if isinstance(value, dict) else None
        files = value.get("files") if isinstance(value, dict) else None
        require(isinstance(merge_base, dict) and merge_base.get("sha") == base_sha
                and isinstance(files, list) and len(files) == 1
                and isinstance(files[0], dict) and isinstance(files[0].get("filename"), str),
                "pull request comparison is malformed or does not start at its base revision")
        return {files[0]["filename"]}


def safe_artifact_receipt(value):
    try:
        with zipfile.ZipFile(io.BytesIO(value)) as archive:
            files = archive.infolist()
            require(len(files) == 1, "GitHub receipt artifact must contain exactly one file")
            item = files[0]
            mode = (item.external_attr >> 16) & 0o177777
            require(item.filename == RECEIPT_FILE and not item.is_dir() and not item.flag_bits & 1
                    and not stat.S_ISLNK(mode) and 0 <= item.file_size <= MAX_RECEIPT_BYTES
                    and 0 <= item.compress_size <= MAX_ARTIFACT_BYTES,
                    "GitHub receipt artifact member is unsafe")
            raw = archive.read(item)
    except (OSError, RuntimeError, zipfile.BadZipFile):
        raise ImportError("GitHub receipt artifact is not a safe ZIP") from None
    require(len(raw) == item.file_size and len(raw) <= MAX_RECEIPT_BYTES,
            "GitHub receipt artifact member exceeds its fixed size limit")
    return json_bytes(raw, "GitHub receipt artifact JSON is malformed")


def verify_artifact(client, repository, run_id, expected_sha, plans):
    require(repository == REPOSITORY and type(run_id) is int and run_id > 0
            and isinstance(expected_sha, str) and SHA.fullmatch(expected_sha) is not None,
            "protected receipt import request is invalid")
    run = client.json(f"/repos/{repository}/actions/runs/{run_id}")
    repository_value = run.get("repository") if isinstance(run, dict) else None
    require(isinstance(run, dict) and run.get("id") == run_id and run.get("event") == "workflow_dispatch"
            and run.get("path") in {WORKFLOW_PATH, WORKFLOW_PATH + "@main"}
            and run.get("head_branch") == "main"
            and run.get("head_sha") == expected_sha and run.get("status") == "completed"
            and run.get("conclusion") == "success" and isinstance(repository_value, dict)
            and repository_value.get("full_name") == repository and type(run.get("workflow_id")) is int
            and run["workflow_id"] > 0,
            "GitHub receipt run provenance is invalid")
    artifacts = client.json(f"/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")
    require(isinstance(artifacts, dict) and isinstance(artifacts.get("artifacts"), list),
            "GitHub receipt artifact listing is malformed")
    name = ARTIFACT_PREFIX + expected_sha
    matches = [item for item in artifacts["artifacts"] if isinstance(item, dict) and item.get("name") == name]
    require(len(matches) == 1, "GitHub receipt run does not have one exact receipt artifact")
    artifact = matches[0]
    workflow = artifact.get("workflow_run")
    require(type(artifact.get("id")) is int and artifact["id"] > 0 and artifact.get("expired") is False
            and type(artifact.get("size_in_bytes")) is int and 0 < artifact["size_in_bytes"] <= MAX_ARTIFACT_BYTES
            and isinstance(artifact.get("digest"), str) and SHA256.fullmatch(artifact["digest"]) is not None
            and isinstance(workflow, dict) and workflow.get("id") == run_id
            and workflow.get("head_branch") == "main" and workflow.get("head_sha") == expected_sha
            and workflow.get("repository_id") == repository_value.get("id"),
            "GitHub receipt artifact provenance is invalid")
    archive = client.download(f"/repos/{repository}/actions/artifacts/{artifact['id']}/zip")
    require(digest(archive) == artifact["digest"], "GitHub receipt artifact digest does not match its metadata")
    receipts = receipt_envelope(safe_artifact_receipt(archive), expected_sha, plans)
    provenance = {
        "repository": repository,
        "workflow_path": WORKFLOW_PATH,
        "workflow_id": run["workflow_id"],
        "run_id": run_id,
        "artifact_id": artifact["id"],
        "artifact_sha256": artifact["digest"],
    }
    return receipts, provenance


def imported_state(state, receipts, provenance):
    require(isinstance(state, dict) and state.get("schema_version") == 1
            and isinstance(state.get("receipts"), dict), "image automation state is malformed")
    result = copy.deepcopy(state)
    for image_id, receipt in receipts.items():
        result["receipts"][image_id] = {
            "receipt": receipt,
            "provenance": provenance,
        }
    return result


def verify_state_change(config, base_state, state, client, expected_sha):
    require(isinstance(base_state, dict) and isinstance(base_state.get("receipts"), dict)
            and isinstance(state, dict) and isinstance(state.get("receipts"), dict)
            and isinstance(expected_sha, str) and SHA.fullmatch(expected_sha) is not None,
            "image automation state is malformed")
    plans = native_plans(config)
    changed = []
    for image_id, plan in plans.items():
        entry = state["receipts"].get(image_id)
        if entry is None:
            require(base_state["receipts"].get(image_id) is None,
                    "native receipt deletion requires a separate reviewed revocation path")
            continue
        valid, reason = verify_imported_receipt(plan, entry)
        require(valid, reason)
        if entry != base_state["receipts"].get(image_id):
            require(entry["receipt"]["repository_sha"] == expected_sha,
                    "changed native receipt was produced for a different base revision")
            changed.append((image_id, entry))
    cached = {}
    for image_id, entry in changed:
        provenance = entry["provenance"]
        key = (provenance["run_id"], provenance["artifact_id"])
        if key not in cached:
            receipts, actual = verify_artifact(
                client, provenance["repository"], provenance["run_id"],
                entry["receipt"]["repository_sha"], plans,
            )
            cached[key] = (receipts, actual)
        receipts, actual = cached[key]
        require(actual == provenance and receipts.get(image_id) == entry["receipt"],
                "changed native receipt does not match its protected GitHub artifact")
    return [image_id for image_id, _ in changed]


def verify_pull_request(config, client, base_sha, head_sha):
    require(isinstance(base_sha, str) and SHA.fullmatch(base_sha) is not None
            and isinstance(head_sha, str) and SHA.fullmatch(head_sha) is not None,
            "pull request revisions are invalid")
    base_state = client.content(REPOSITORY, STATE_PATH, base_sha)
    state = client.content(REPOSITORY, STATE_PATH, head_sha)
    plans = native_plans(config)
    base_other = copy.deepcopy(base_state)
    state_other = copy.deepcopy(state)
    base_receipts = base_other.pop("receipts", None)
    state_receipts = state_other.pop("receipts", None)
    require(isinstance(base_receipts, dict) and isinstance(state_receipts, dict),
            "image automation state is malformed")
    unknown_native = {
        image_id for image_id in set(base_receipts) | set(state_receipts)
        if isinstance(image_id, str) and image_id.startswith("chainguard-") and image_id not in plans
    }
    require(all(base_receipts.get(image_id) == state_receipts.get(image_id) for image_id in unknown_native),
            "native receipt import may not preseed an unmanaged Chainguard image")
    changed = [image_id for image_id in plans
               if base_receipts.get(image_id) != state_receipts.get(image_id)]
    if not changed:
        return []
    require(client.compare(REPOSITORY, base_sha, head_sha) == {STATE_PATH},
            "native receipt import pull requests may change only image automation state")
    require(base_other == state_other,
            "native receipt import may not change other image automation state")
    require(all(base_receipts.get(image_id) == state_receipts.get(image_id)
                for image_id in set(base_receipts) | set(state_receipts) if image_id not in plans),
            "native receipt import may not change non-native receipts")
    verify_state_change(config, base_state, state, client, base_sha)
    return sorted(changed)


def token(path):
    if path is None:
        return None
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        raise ImportError("GitHub token file is unavailable") from None
    require(value and len(value) <= 4096 and not any(character.isspace() for character in value),
            "GitHub token file is invalid")
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("import", "verify-state-change", "verify-pull-request"))
    parser.add_argument("--config", type=Path, default=AUTOMATION)
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--base-state", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--expected-sha")
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args()
    config = read_json(args.config)
    client = GitHubActionsClient(token(args.token_file))
    if args.command == "import":
        require(args.output is not None and args.run_id is not None and args.expected_sha is not None,
                "import requires --output, --run-id, and --expected-sha")
        receipts, provenance = verify_artifact(client, REPOSITORY, args.run_id, args.expected_sha, native_plans(config))
        write_json(args.output, imported_state(read_json(args.state), receipts, provenance))
        print("Native Chainguard receipt import candidate verified")
    elif args.command == "verify-state-change":
        require(args.base_state is not None and args.expected_sha is not None,
                "verify-state-change requires --base-state and --expected-sha")
        changed = verify_state_change(config, read_json(args.base_state), read_json(args.state),
                                      client, args.expected_sha)
        print("Native Chainguard receipt changes verified: " + ", ".join(sorted(changed) or ["none"]))
    else:
        require(args.base_sha is not None and args.head_sha is not None,
                "verify-pull-request requires --base-sha and --head-sha")
        changed = verify_pull_request(config, client, args.base_sha, args.head_sha)
        print("Native Chainguard receipt pull request verified: " + ", ".join(changed or ["none"]))


if __name__ == "__main__":
    try:
        main()
    except (ImportError, OSError) as error:
        sys.exit(str(error))
