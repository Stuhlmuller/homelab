#!/usr/bin/env python3
"""Archive all SSM versions, then re-encrypt current values without rotation.

Only the committed manifest supplies desired state. Secret values stay in
memory or private temporary files; subprocess output is never echoed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


CONFIG = Path(__file__).resolve().parent / "config/ssm-aws-managed-migration.json"


def aws(region, service, operation, **request):
    # AWS CLI streaming bodies must be supplied with --body, not JSON input.
    body = request.pop("Body", None)
    with tempfile.TemporaryDirectory(prefix="homelab-ssm-") as directory:
        path = Path(directory) / "request.json"
        path.write_text(json.dumps(request))
        path.chmod(0o600)
        result = subprocess.run(
            ["aws", service, operation, "--region", region,
             "--cli-input-json", f"file://{path}", "--output", "json"]
            + (["--body", body] if body is not None else []),
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(f"AWS {service} {operation} failed; details suppressed to protect values")
        return json.loads(result.stdout) if result.stdout.strip() else {}


def read_archive(config):
    with tempfile.TemporaryDirectory(prefix="homelab-ssm-") as directory:
        path = Path(directory) / "archive.json"
        result = subprocess.run(
            ["aws", "s3api", "get-object", "--region", config["archive_region"],
             "--bucket", config["archive_bucket"], "--key", config["archive_key"],
             str(path)], capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError("Verified history archive is required before migration")
        body = path.read_bytes()
        metadata = json.loads(result.stdout)
        assert metadata["Metadata"]["sha256"] == hashlib.sha256(body).hexdigest()
        assert metadata["ServerSideEncryption"] == "aws:kms"
        managed = aws(config["archive_region"], "kms", "describe-key",
                      KeyId=config["archive_kms_key"])["KeyMetadata"]["Arn"]
        assert metadata["SSEKMSKeyId"] == managed
        archive = json.loads(body)
        assert archive["config"] == config
        assert set(archive["history"]) == set(config["parameters"])
        return archive


def archive_history(config):
    history = {}
    for name in config["parameters"]:
        versions = aws(config["region"], "ssm", "get-parameter-history",
                       Name=name, WithDecryption=True)["Parameters"]
        assert versions and all(v["Type"] == "SecureString" for v in versions)
        assert not any(v.get("Labels") for v in versions), "Version labels need explicit migration"
        history[name] = versions
    body = json.dumps({"config": config, "history": history}, sort_keys=True).encode()
    with tempfile.TemporaryDirectory(prefix="homelab-ssm-") as directory:
        path = Path(directory) / "history.json"
        path.write_bytes(body)
        path.chmod(0o600)
        aws(config["archive_region"], "s3api", "put-object",
            Bucket=config["archive_bucket"], Key=config["archive_key"],
            Body=str(path), ServerSideEncryption="aws:kms",
            SSEKMSKeyId=config["archive_kms_key"], BucketKeyEnabled=True,
            IfNoneMatch="*", Metadata={"sha256": hashlib.sha256(body).hexdigest()})
    verified = read_archive(config)
    assert verified["history"] == history
    print(f"Archived and verified {sum(map(len, history.values()))} versions across {len(history)} parameters")


def migrate(config, write):
    archive = read_archive(config)
    metadata = aws(config["region"], "ssm", "describe-parameters")["Parameters"]
    metadata = {item["Name"]: item for item in metadata}
    target = aws(config["region"], "kms", "describe-key",
                 KeyId=config["target_key_alias"])["KeyMetadata"]
    assert target["KeyManager"] == "AWS"
    target_ids = {config["target_key_alias"], target["KeyId"], target["Arn"]}
    migrated = 0
    for name in config["parameters"]:
        current = aws(config["region"], "ssm", "get-parameter",
                      Name=name, WithDecryption=True)["Parameter"]
        previous = max(archive["history"][name], key=lambda v: v["Version"])
        assert current["Value"] == previous["Value"], "Value changed since archive; stop for review"
        if metadata[name].get("KeyId") not in target_ids:
            old = aws(config["region"], "kms", "describe-key",
                      KeyId=metadata[name]["KeyId"])["KeyMetadata"]["KeyId"]
            assert old == config["source_key_id"], "Unexpected source key"
            assert current["Version"] == previous["Version"], "Concurrent parameter write"
            if not write:
                raise RuntimeError("A current parameter has not migrated")
            aws(config["region"], "ssm", "put-parameter", Name=name,
                Value=current["Value"], Type="SecureString", Overwrite=True,
                KeyId=config["target_key_alias"], Tier=metadata[name]["Tier"])
            after = aws(config["region"], "ssm", "get-parameter",
                        Name=name, WithDecryption=True)["Parameter"]
            assert after["Value"] == current["Value"], "Post-write value mismatch"
            migrated += 1
    print(f"Verified {len(config['parameters'])} unchanged values; migrated {migrated}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["archive", "migrate", "verify"])
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text())
    identity = aws(config["region"], "sts", "get-caller-identity")
    assert identity["Account"] == config["account_id"], "Wrong AWS account"
    if args.action == "archive":
        archive_history(config)
    else:
        migrate(config, args.action == "migrate")


if __name__ == "__main__":
    main()
