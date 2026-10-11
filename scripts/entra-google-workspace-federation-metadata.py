#!/usr/bin/env python3
"""Store validated Google Workspace SAML metadata in its declared SSM slot."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as element_tree

PARAMETER = "/homelab/entra/google-workspace-federation-metadata"
REGION = "us-west-2"
ROOT = Path(__file__).resolve().parents[1]


class Failure(Exception):
    """Only fixed diagnostics may leave the private metadata boundary."""


def command(args):
    result = subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, timeout=60,
        env={**os.environ, "AWS_PAGER": "", "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true"},
    )
    if result.returncode:
        raise Failure("Private command failed")
    return result.stdout


def metadata(path):
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or len(raw) > 1024 * 1024:
        raise Failure("Invalid Google metadata")
    try:
        root = element_tree.fromstring(raw)
    except element_tree.ParseError as error:
        raise Failure("Invalid Google metadata") from error
    namespace = "{urn:oasis:names:tc:SAML:2.0:metadata}"
    certificate_namespace = "{http://www.w3.org/2000/09/xmldsig#}"
    issuer = root.get("entityID", "")
    sign_in = next((service.get("Location", "") for service in root.findall(
        f".//{namespace}SingleSignOnService")
                    if "HTTP-Redirect" in service.get("Binding", "")), "")
    certificate = "".join(next(iter(root.findall(
        f".//{certificate_namespace}X509Certificate")), element_tree.Element("empty")).text or "".split())
    if not (issuer.startswith("https://accounts.google.com/") and
            sign_in.startswith("https://accounts.google.com/") and certificate):
        raise Failure("Google metadata is missing the required SAML identity-provider values")
    try:
        base64.b64decode(certificate, validate=True)
    except ValueError as error:
        raise Failure("Google metadata contains an invalid signing certificate") from error
    return {"issuer_uri": issuer, "sign_in_uri": sign_in, "signing_certificate": certificate}


def validate_context():
    if command(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip() != "main":
        raise Failure("Run from signed current main after the declared SSM parameter exists")
    if command(["git", "status", "--porcelain"]).strip():
        raise Failure("Run from a clean signed current main checkout")
    if command(["git", "rev-parse", "HEAD"]).strip() != command(
            ["git", "rev-parse", "origin/main"]).strip():
        raise Failure("Checkout is not current main")
    parameters = json.loads(command([
        "aws", "ssm", "describe-parameters", "--region", REGION,
        "--parameter-filters", f"Key=Name,Option=Equals,Values={PARAMETER}", "--output", "json",
    ])).get("Parameters", [])
    if (len(parameters) != 1 or parameters[0].get("Name") != PARAMETER or
            parameters[0].get("Type") != "SecureString" or
            parameters[0].get("KeyId") != "alias/aws/ssm"):
        raise Failure("Apply the declared federation metadata SecureString first")


def store(values):
    with tempfile.TemporaryDirectory(prefix="entra-google-metadata-") as directory:
        payload_path = Path(directory) / "parameter.json"
        descriptor = os.open(payload_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as payload:
            json.dump({"Name": PARAMETER, "Type": "SecureString", "KeyId": "alias/aws/ssm",
                       "Value": json.dumps(values, separators=(",", ":")), "Overwrite": True}, payload)
        result = json.loads(command([
            "aws", "ssm", "put-parameter", "--region", REGION,
            "--cli-input-json", f"file://{payload_path}", "--output", "json",
        ]))
    if not isinstance(result.get("Version"), int) or result["Version"] < 1:
        raise Failure("Federation metadata write was not confirmed")


def main():
    if len(sys.argv) != 2:
        raise Failure("Usage: entra-google-workspace-federation-metadata.py GoogleIDPMetadata.xml")
    source = Path(sys.argv[1]).expanduser().resolve()
    if not source.is_file():
        raise Failure("Google metadata file is unavailable")
    values = metadata(source)
    validate_context()
    store(values)
    print("Google Workspace metadata stored. Run the reviewed operator federation plan next.")


if __name__ == "__main__":
    try:
        main()
    except Failure as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
