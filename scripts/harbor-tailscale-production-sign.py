#!/usr/bin/env python3
"""Production-only signing proposal. Default preview; execution needs separate approval."""
import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("production", ROOT / "scripts/harbor-tailscale-production.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
G, S = P.G, P.SHARED
CLI = "/opt/homebrew/bin/tailscale"
CLI_COMMIT = "9a08e8f1c2021d5c85895e660cf01d8bb1bc9df0"
GENERATION = 2
EXPIRY = "2027-01-25T02:58:13Z"


def paths():
    return (S.CACHE.with_name("ci-production-signing-receipt.json"),
            S.CACHE.with_name("ci-production-signing-output.txt"))


def private_read(path, limit=1024 * 1024):
    S.private_metadata(path.parent, directory=True)
    S.private_metadata(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as f:
        value = f.read(limit + 1)
    if len(value) > limit:
        raise G.Failure("Private recovery file exceeds its bound")
    return value


def digest(value):
    return hashlib.sha256(value).hexdigest()


def read_entry():
    values = G.read_json(["terragrunt", "--no-color", "--working-dir",
                          str(ROOT / "IaC/homelab/us-west-2/operator/tailscale-access"),
                          "run", "--backend-require-bootstrap", "--backend-bootstrap=false",
                          "--no-auto-init", "--", "output", "-json"], "existing production state")
    try:
        output = values["github_auth_keys"]
        e = output["value"]["apply"]
        if (output["sensitive"] is not True or e["generation"] != GENERATION
                or type(e["generation"]) is not int or e["expires_at"] != EXPIRY
                or e["tags"] != [P.TAG] or e["invalid"] is not False
                or any(e[k] is not True for k in ("reusable", "ephemeral", "preauthorized"))
                or not isinstance(e["key"], str)
                or not re.fullmatch(re.escape(S.AUTH_PREFIX) + r"[A-Za-z0-9]+-[A-Za-z0-9]+", e["key"])
                or P.datetime.fromisoformat(EXPIRY.replace("Z", "+00:00"))
                <= P.datetime.now(P.timezone.utc) + P.timedelta(days=7)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise G.Failure("Existing apply identity, generation, expiry or key properties differ from approval") from None
    return e


def trust_snapshot(signer):
    status = G.read_json([CLI, "status", "--json"], "local signer identity")
    lock = G.read_json([CLI, "lock", "status", "--json"], "existing public trust metadata")
    try:
        trusted = {}
        for item in lock["TrustedKeys"]:
            public = P.canonical_authority(item.get("Key", item.get("Public")))
            votes = item["Votes"]
            if public in trusted or type(votes) is not int or votes < 0:
                raise ValueError
            trusted[public] = {"metadata": item.get("Metadata", item.get("Meta")), "votes": votes}
        local = P.canonical_authority(lock["PublicKey"])
        node = status["Self"]["ID"]
        if (status["BackendState"] != "Running" or status["Self"]["Online"] is not True
                or status["CurrentTailnet"]["MagicDNSSuffix"] != "tail67beb.ts.net"
                or lock["Enabled"] is not True or lock["NodeKeySigned"] is not True
                or local != signer or local not in trusted or not isinstance(node, str) or not node):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise G.Failure("Approved online signed Mac authority does not match") from None
    return trusted, node


def preflight(args):
    if args.identity != "apply" or args.generation != GENERATION or args.expires_at != EXPIRY:
        raise G.Failure("Approval must name only apply generation 2 and its exact existing expiry")
    signer = P.canonical_authority(args.signer_authority)
    revision = G.verify_main()
    if G.read_json(["gh", "api", "--hostname", "github.com", "user"], "operator identity").get("login") != "rstuhlmuller":
        raise G.Failure("Approved rstuhlmuller operator required")
    version = G.read_json([CLI, "version", "--json"], "pinned operator CLI")
    if version.get("short") != "1.92.3" or version.get("gitCommit") != CLI_COMMIT:
        raise G.Failure("Operator CLI differs from the reviewed implementation")
    entry = read_entry()
    trusted, node = trust_snapshot(signer)
    # A distinct full-helper receipt must be resolved without changing other identities.
    if S.pending_path().exists() or S.pending_path().is_symlink():
        raise G.Failure("Existing shared signing receipt needs separate recovery")
    return revision, entry, trusted, node, signer


def read_cache():
    raw = private_read(S.CACHE)
    cache = json.loads(raw)
    if not isinstance(cache, list) or not all(isinstance(x, dict) for x in cache):
        raise G.Failure("Existing cache must remain a list of unchanged records")
    return raw, cache


def read_receipt(entry, signer, node):
    receipt = json.loads(private_read(paths()[0]))
    if (receipt.get("identity") != "apply" or receipt.get("generation") != GENERATION
            or receipt.get("expires_at") != EXPIRY or receipt.get("fingerprint") != S.fingerprint(entry)
            or receipt.get("signer") != signer or receipt.get("node") != node
            or receipt.get("phase") not in ("intent", "verified", "complete")
            or type(receipt.get("started_at")) is not int
            or not isinstance(receipt.get("before"), dict) or not receipt["before"]
            or not re.fullmatch(r"[0-9a-f]{64}", receipt.get("cache_before_sha256", ""))):
        raise G.Failure("Private production receipt does not match the approved operation")
    return receipt


def matching_authorities(entry, trusted):
    stable = entry["key"].removeprefix(S.AUTH_PREFIX).split("-", 1)[0]
    return [public for public, state in trusted.items() if isinstance(meta := state["metadata"], dict)
            and meta.get("purpose") == "pre-auth key" and meta.get("authkey_stableid") == stable]


def invoke_sign(key, capture):
    # stdout goes directly to a protected durable capture, never to model/tool output.
    result = subprocess.run([CLI, "lock", "sign", "file:/dev/stdin"], input=key,
                            stdout=capture, stderr=subprocess.PIPE, text=True, timeout=120,
                            check=False)
    return result.returncode


def finish(entry, signer, node):
    receipt_path, capture_path = paths()
    receipt = read_receipt(entry, signer, node)
    wrapped = private_read(capture_path, 16384).decode().strip()
    S.validate_wrapped_key(wrapped)
    if not wrapped.startswith(entry["key"] + "--TL"):
        raise G.Failure("Captured wrapper differs from approved current provider key; never re-sign")
    trusted, current_node = trust_snapshot(signer)
    before = receipt["before"]
    added = set(trusted) - set(before)
    if (current_node != node or any(trusted.get(k) != v or k not in trusted for k, v in before.items())
            or len(added) != 1 or matching_authorities(entry, trusted) != list(added)):
        raise G.Failure("Trust readback is incomplete or changed unexpectedly; retain receipt and recover only")
    authority = next(iter(added))
    if trusted[authority]["votes"] != 1:
        raise G.Failure("New delegated authority vote weight differs from the pinned signing operation")
    metadata = trusted[authority]["metadata"]
    try:
        created = int(metadata["wrapper_createtime"])
        # A suspended process may outlive the CLI timeout before the call starts.
        # If killed before recording completion, recovery supplies the upper observation.
        observed_end = receipt.get("attempt_observed_end_at", int(time.time()))
        if (type(observed_end) is not int or not receipt["started_at"] <= observed_end <= int(time.time()) + 5
                or metadata["wrapper_stableid"] != node
                or not receipt["started_at"] - 5 <= created <= observed_end + 5):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise G.Failure("New authority does not match the approved Mac and signing interval") from None
    receipt.setdefault("attempt_observed_end_at", observed_end)
    record = {"identity": "apply", "generation": GENERATION, "fingerprint": S.fingerprint(entry),
              "wrapped": wrapped, "authority": authority}
    raw, cache = read_cache()
    if digest(raw) == receipt.get("cache_after_sha256"):
        if [x for x in cache if x.get("fingerprint") == record["fingerprint"]] != [record]:
            raise G.Failure("Completed-cache recovery conflicts with receipt")
    else:
        if digest(raw) != receipt["cache_before_sha256"]:
            raise G.Failure("Cache changed after intent; retain all records and resolve conflict separately")
        if any(x.get("fingerprint") == record["fingerprint"] for x in cache):
            raise G.Failure("Current-key cache record already exists; no overwrite")
        updated = cache + [record]  # Existing records, including old production, remain unchanged.
        receipt.update(phase="verified", authority=authority,
                       cache_after_sha256=digest(json.dumps(updated).encode()))
        S.save_private(receipt_path, receipt)
        S.save_private(S.CACHE, updated)
    receipt.update(phase="complete", authority=authority)
    S.save_private(receipt_path, receipt)
    return authority


def run(args):
    revision, entry, trusted, node, signer = preflight(args)
    receipt_path, capture_path = paths()
    raw, cache = read_cache()
    if not args.execute and not args.recover:
        blocked = (receipt_path.exists() or receipt_path.is_symlink() or capture_path.exists()
                   or capture_path.is_symlink() or bool(matching_authorities(entry, trusted))
                   or any(x.get("fingerprint") == S.fingerprint(entry) for x in cache))
        return {"mode": "preview", "identity": "apply", "generation": GENERATION, "expires_at": EXPIRY,
                "signer": signer, "receipt_exists": receipt_path.exists(),
                "current_authorities": matching_authorities(entry, trusted),
                "status": "recovery-required" if blocked else "ready-for-separate-approval",
                "would_add_persistent_authority": not blocked, "secret_installation": False}
    if args.execute and not args.allow_new_delegated_authority:
        raise G.Failure("Execution requires explicit approval for one new persistent delegated authority")
    with S.locked_cache():
        raw, cache = read_cache()
        if S.pending_path().exists() or S.pending_path().is_symlink():
            raise G.Failure("Shared signing receipt appeared; recover it separately without signing")
        if args.recover:
            authority = finish(entry, signer, node)  # Never invokes signing, even after an uncertain outcome.
        else:
            if receipt_path.exists() or receipt_path.is_symlink() or capture_path.exists() or capture_path.is_symlink():
                raise G.Failure("Production intent/capture exists; recover only, never blindly retry signing")
            if matching_authorities(entry, trusted) or any(x.get("fingerprint") == S.fingerprint(entry) for x in cache):
                raise G.Failure("Existing current-key authority/cache requires recovery, not signing")
            if G.verify_main() != revision or S.fingerprint(read_entry()) != S.fingerprint(entry):
                raise G.Failure("Current source or provider key changed before signing")
            before, current_node = trust_snapshot(signer)
            if before != trusted or current_node != node:
                raise G.Failure("Trust changed before signing; no intent created")
            receipt = {"phase": "intent", "identity": "apply", "generation": GENERATION,
                       "expires_at": EXPIRY, "fingerprint": S.fingerprint(entry), "source_sha": revision,
                       "signer": signer, "node": node, "before": before,
                       "cache_before_sha256": digest(raw), "started_at": int(time.time())}
            S.save_private(receipt_path, receipt)  # Durable intent must precede any remote mutation.
            fd = os.open(capture_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as capture:
                os.fsync(capture.fileno())
                directory = os.open(capture_path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                try:
                    status = invoke_sign(entry["key"], capture)
                finally:
                    capture.flush()
                    os.fsync(capture.fileno())
                    receipt["attempt_observed_end_at"] = int(time.time())
                    S.save_private(receipt_path, receipt)
            if status:
                raise G.Failure("Signing outcome uncertain; protected receipt/output retained; recover only")
            authority = finish(entry, signer, node)
    return {"mode": "recovered" if args.recover else "signed", "identity": "apply", "generation": GENERATION,
            "expires_at": EXPIRY, "authority": authority, "secret_installation": False,
            "old_authorities_removed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--recover", action="store_true")
    parser.add_argument("--identity", required=True, choices=["apply"])
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--signer-authority", required=True)
    parser.add_argument("--allow-new-delegated-authority", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args)))
        return 0
    except G.Failure as error:
        print(str(error), file=sys.stderr)
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 - never expose secret-bearing exceptions/output.
        print("Production signing/recovery stopped; retain private receipt/output; never blindly retry signing.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
