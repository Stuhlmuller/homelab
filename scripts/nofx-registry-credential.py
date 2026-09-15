#!/usr/bin/env python3
"""Validate a dedicated private GHCR reader before updating its declared SSM slot."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

REPO = "Stuhlmuller/homelab"
REGISTRY_USER = "rstuhlmuller"
PARAMETER = "/homelab/nofx/ghcr-read-token"
REGION = "us-west-2"
KEY_ID = "alias/aws/ssm"
ROOT = Path(__file__).resolve().parents[1]
# These reviewed published images are the authentication bootstrap acceptance
# targets. Deployment remains on its current images until this check succeeds.
SOURCE_SHA = "f76c27834ff987aa1dfad81d0c9ff273be7dd3cd"
IMAGES = (
    "ghcr.io/stuhlmuller/homelab-nofx-backend@sha256:"
    "8da04a4a63b5c0a1eb7b938218a41c7cbebba82489f784d9abda43a5fa47985f",
    "ghcr.io/stuhlmuller/homelab-nofx-frontend@sha256:"
    "66f001923a8ea65af86d777db2bd46e9c829acba0a877c1af2037bf6dab974c5",
)
COMMAND_STAGES = frozenset({
    "checkout-revision", "current-main", "ssm-metadata", "registry-login",
    "backend-pull", "backend-inspect", "frontend-pull", "frontend-inspect", "ssm-write",
})
AWS_ERROR_CODES = {
    "AccessDenied": "aws-access-denied",
    "AccessDeniedException": "aws-access-denied",
    "ExpiredToken": "expired",
    "ExpiredTokenException": "expired",
    "InvalidClientTokenId": "invalid",
    "InvalidKeyId": "aws-invalid-key",
    "KMSAccessDeniedException": "kms-access-denied",
    "ParameterNotFound": "ssm-parameter-not-found",
    "Throttling": "aws-throttled",
    "ThrottlingException": "aws-throttled",
    "ValidationException": "aws-validation-error",
}
REGISTRY_ERROR_CODES = {
    "unauthorized": "registry-unauthorized",
    "denied": "registry-denied",
    "manifest unknown": "registry-manifest-unknown",
    "name unknown": "registry-name-unknown",
    "toomanyrequests": "registry-rate-limited",
}


class Failure(Exception):
    """Only fixed, non-secret error messages may cross the CI log boundary."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Failure("GitHub authentication unexpectedly redirected")


def command_error_code(stage, stderr):
    # Never publish a captured substring. Only recognize known error codes and
    # return their fixed labels; arbitrary messages and credential echoes stay
    # private. A nonstandard response receives the same generic fallback.
    if stage.startswith("ssm-"):
        match = re.search(r"An error occurred \(([A-Za-z][A-Za-z0-9]+)\)", stderr)
        if match:
            return AWS_ERROR_CODES.get(match.group(1), "command-failed")
    elif stage in {"registry-login", "backend-pull", "frontend-pull"}:
        for code, label in REGISTRY_ERROR_CODES.items():
            if re.search(r"(?:^|[\s:])" + re.escape(code) + r"(?::|$)", stderr.lower()):
                return label
    return "command-failed"


def command(args, *, stage, data=None, timeout=30):
    if stage not in COMMAND_STAGES:
        raise Failure("Unknown credential validation stage")
    # A fixed progress marker also identifies the active boundary if parsing a
    # successful command's private response fails afterward.
    print(f"NOFX registry credential: stage {stage}", flush=True)
    # Do not propagate the PAT into children. Docker login receives it on stdin;
    # AWS receives only the single write payload on stdin after pull validation.
    env = {key: value for key, value in os.environ.items()
           if key not in {"NOFX_GHCR_READ_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"}
           and not key.startswith("AWS_ENDPOINT_URL")}
    env.update(AWS_IGNORE_CONFIGURED_ENDPOINT_URLS="true", AWS_PAGER="")
    try:
        result = subprocess.run(
            args, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False, timeout=timeout, cwd=ROOT, env=env,
        )
    except subprocess.TimeoutExpired:
        raise Failure(f"Stage {stage} failed: command-timeout; private output withheld") from None
    except OSError:
        raise Failure(f"Stage {stage} failed: command-unavailable; private output withheld") from None
    except subprocess.SubprocessError:
        raise Failure(f"Stage {stage} failed: command-failed; private output withheld") from None
    if result.returncode:
        code = command_error_code(stage, result.stderr)
        raise Failure(f"Stage {stage} failed: {code}; private output withheld")
    return result.stdout


def github_user(token):
    request = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            scopes = {scope.strip() for scope in response.headers.get("X-OAuth-Scopes", "").split(",")
                      if scope.strip()}
            user = json.loads(response.read(1048576))
    except Exception:
        raise Failure("Dedicated GitHub credential validation failed") from None
    if user.get("login") != REGISTRY_USER or scopes != {"read:packages"}:
        raise Failure("Credential must belong to rstuhlmuller and have only read:packages scope")


def validate_context():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise Failure("Run only through the protected NOFX Registry Credential workflow on main")
    sha = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise Failure("Invalid reviewed main revision")
    if command(["git", "rev-parse", "HEAD"], stage="checkout-revision").strip() != sha:
        raise Failure("Checkout does not match the dispatched main revision")
    current = command(["git", "ls-remote", f"https://github.com/{REPO}.git", "refs/heads/main"], stage="current-main")
    if current.split() != [sha, "refs/heads/main"]:
        raise Failure("Dispatch is stale; use the current reviewed main revision")


def parameter_metadata():
    metadata = json.loads(command([
        "aws", "ssm", "describe-parameters", "--region", REGION,
        "--parameter-filters", f"Key=Name,Option=Equals,Values={PARAMETER}",
        "--output", "json",
    ], stage="ssm-metadata"))
    parameters = metadata.get("Parameters", [])
    if (len(parameters) != 1 or parameters[0].get("Name") != PARAMETER
            or parameters[0].get("Type") != "SecureString"
            or parameters[0].get("KeyId") != KEY_ID
            or parameters[0].get("Tier") != "Standard"):
        raise Failure("Apply the declared NOFX SecureString parameter before credential bootstrap")


def authenticate_images(token):
    with tempfile.TemporaryDirectory(prefix="nofx-registry-") as directory:
        # TemporaryDirectory is mode 0700; docker's auth file is removed even on
        # failure and never enters the checkout or an uploaded artifact.
        docker = ["docker", "--config", directory]
        command(docker + ["login", "ghcr.io", "--username", REGISTRY_USER, "--password-stdin"],
                stage="registry-login", data=token, timeout=60)
        for component, image in zip(("backend", "frontend"), IMAGES, strict=True):
            command(docker + ["pull", "--platform", "linux/amd64", image], stage=f"{component}-pull", timeout=240)
            labels = json.loads(command(docker + ["image", "inspect", "--format", "{{json .Config.Labels}}", image],
                                        stage=f"{component}-inspect"))
            if (labels.get("org.opencontainers.image.source") != f"https://github.com/{REPO}"
                    or labels.get("org.opencontainers.image.revision") != SOURCE_SHA):
                raise Failure("Pulled image provenance does not match the reviewed NOFX release")


def rotate():
    if len(sys.argv) != 1:
        raise Failure("This workflow accepts no command-line inputs")
    token = os.environ.pop("NOFX_GHCR_READ_TOKEN", "")
    if not re.fullmatch(r"ghp_[A-Za-z0-9]{36,252}", token):
        raise Failure("Set the dedicated classic PAT in homelab-production secret NOFX_GHCR_READ_TOKEN")
    validate_context()
    github_user(token)
    parameter_metadata()
    authenticate_images(token)
    # Recheck main immediately before the only mutation, after potentially slow
    # image pulls. No Kubernetes resource or NOFX application setting changes.
    validate_context()
    result = json.loads(command([
        "aws", "ssm", "put-parameter", "--region", REGION,
        "--cli-input-json", "file:///dev/stdin", "--output", "json",
    ], stage="ssm-write", data=json.dumps({"Name": PARAMETER, "Type": "SecureString", "KeyId": KEY_ID,
                        "Value": token, "Overwrite": True})))
    if type(result.get("Version")) is not int or result["Version"] < 1:
        raise Failure("SSM write returned no version; inspect the private parameter before retrying")
    print(f"Verified both private NOFX image pulls; updated declared SSM credential version {result['Version']}.")
    print("External Secrets refreshes the pull secret within five minutes; no trader was started.")


def main():
    try:
        rotate()
    except Failure as error:
        print(f"NOFX registry credential: {error}", file=sys.stderr)
        return 1
    except Exception:
        # JSON/process/HTTP exceptions can contain credentials or response data.
        print("NOFX registry credential: operation failed; private details withheld", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
