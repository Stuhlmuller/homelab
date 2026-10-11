#!/usr/bin/env python3
"""Validate the two runner credentials and inject only their declared SSM slots."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = {
    "CORDIUM_RUNNER_APP_PRIVATE_KEY": "/homelab/cordium-runners/github-app-private-key",
    "CORDIUM_RUNNER_AUTH_TOKEN": "/homelab/cordium-runners/auth-token",
}
REGION = "us-west-2"
KEY_ID = "alias/aws/ssm"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


github = module("github_operator", "policy-bot-webhook.py")
native = module("native_operator", "octelium-nofx-reconcile.py")


def command(*args, env=None):
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, timeout=45, check=False)
    if result.returncode:
        raise RuntimeError("Credential validation or storage command failed; private output withheld")
    return result.stdout


def context():
    expected = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_WORKFLOW_REF": "Stuhlmuller/homelab/.github/workflows/cordium-runner-credentials.yml@refs/heads/main"}
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Run only through the protected current-main runner credential workflow")
    github.verify_reviewed_main(os.environ.get("GITHUB_SHA"))


def validate_native(token, directory):
    version = command("octelium", "version").decode()
    if not re.search(r"(?m)^gitCommit:\s*5e4eb3e36911ba4f66f5f43df2cc4b264211c4ce\s*$", version):
        raise RuntimeError("Native credential validation requires the pinned Octelium client")
    client = ["octelium", "--domain", "stinkyboi.com", "--homedir", str(directory / "login")]
    with native.native_transport(directory) as environment:
        environment = {key: value for key, value in environment.items()
                       if not key.startswith("AWS_") and key not in {"GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"}}
        environment["OCTELIUM_AUTH_TOKEN"] = token
        try:
            command(*client, "login", env=environment)
            status = json.loads(command(*client, "status", "-o", "json", env=environment))
            user = status.get("user", {})
            if (status.get("domain") != "stinkyboi.com" or user.get("metadata", {}).get("name") != "homelab-cordium-runners"
                    or user.get("spec", {}).get("type") != "WORKLOAD"
                    or user["spec"].get("authorization", {}).get("policies") != ["homelab-cordium-runner-execution"]):
                raise RuntimeError("Native credential is not the dedicated runner identity")
        finally:
            environment.pop("OCTELIUM_AUTH_TOKEN", None)
            command(*client, "logout", env=environment)


def inject():
    if len(sys.argv) != 1:
        raise RuntimeError("This fixed credential workflow accepts no command-line inputs")
    values = {key: os.environ.pop(key, "") for key in PARAMETERS}
    context()
    if any(not value or len(value.encode()) > 4096 for value in values.values()):
        raise RuntimeError("Both credentials must fit their declared Standard SecureString slots")
    if any(character.isspace() for character in values["CORDIUM_RUNNER_AUTH_TOKEN"]):
        raise RuntimeError("Native authentication token must contain no whitespace")
    app = github.github_client(github.app_jwt("5270069", values["CORDIUM_RUNNER_APP_PRIVATE_KEY"].encode()))
    if app("GET", "/app").get("id") != 5270069:
        raise RuntimeError("Private key does not belong to the declared runner App")
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"GH_TOKEN", "GITHUB_TOKEN", "OCTELIUM_AUTH_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"}
                   and not key.startswith("AWS_ENDPOINT_URL")}
    environment.update(AWS_IGNORE_CONFIGURED_ENDPOINT_URLS="true", AWS_PAGER="")
    # Validate every slot and both credentials before the first write.
    for name in PARAMETERS.values():
        response = json.loads(command("aws", "ssm", "describe-parameters", "--region", REGION,
                                      "--parameter-filters", "Key=Name,Option=Equals,Values=" + name,
                                      "--output", "json", env=environment))
        records = response.get("Parameters", [])
        if (len(records) != 1 or records[0].get("Name") != name or records[0].get("Type") != "SecureString"
                or records[0].get("KeyId") != KEY_ID or records[0].get("Tier") != "Standard"):
            raise RuntimeError("Apply the declared encrypted runner parameter slots before intake")
    with tempfile.TemporaryDirectory(prefix="cordium-runner-intake-") as temporary:
        directory = Path(temporary)
        validate_native(values["CORDIUM_RUNNER_AUTH_TOKEN"], directory)
        for key, name in PARAMETERS.items():
            context()  # Recheck exact current main immediately before each mutation.
            path = directory / "parameter.json"
            with open(path, "w", opener=lambda target, flags: os.open(target, flags, 0o600)) as output:
                json.dump({"Name": name, "Type": "SecureString", "KeyId": KEY_ID, "Value": values[key], "Overwrite": True}, output)
            result = json.loads(command("aws", "ssm", "put-parameter", "--region", REGION,
                                        "--cli-input-json", "file://" + str(path), "--output", "json", env=environment))
            path.unlink()
            if type(result.get("Version")) is not int or result["Version"] < 1:
                raise RuntimeError("Credential write lacks a version receipt; inspect both slots before retrying")
            print(f"Updated runner credential slot {name} to version {result['Version']}")
    print("Both credential identities verified; file-backed ExternalSecret refresh is within five minutes.")


if __name__ == "__main__":
    try:
        inject()
    except Exception:
        raise SystemExit("Runner credential intake failed; inspect private state before retrying; no raw output exposed") from None
