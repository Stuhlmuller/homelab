#!/usr/bin/env python3
"""Preview/install only an already-signed production CI key; never sign/enroll."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tailscale_ci", ROOT / "scripts/tailscale-ci-configure.py")
SHARED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHARED)
G = SHARED.GUARDS
ENVIRONMENT = "homelab-production"
SECRET = "TAILSCALE_AUTH_KEY"
TAG = "tag:homelab-ci-apply"


def production_key():
    # Existing state bundles three keys; select production before any validation/use.
    values = G.read_json(["terragrunt", "--log-disable", "--working-dir",
                          str(ROOT / "IaC/homelab/us-west-2/operator/tailscale-access"),
                          "output", "-json"], "existing operator outputs")
    try:
        output = values["github_auth_keys"]
        entry = output["value"]["apply"]
        expiry = datetime.fromisoformat(entry["expires_at"].replace("Z", "+00:00"))
        remaining = expiry - datetime.now(timezone.utc)
        if (output["sensitive"] is not True or entry["invalid"] is not False
                or entry["tags"] != [TAG]
                or any(entry[k] is not True for k in ("reusable", "ephemeral", "preauthorized"))
                or type(entry["generation"]) is not int or not 1 <= entry["generation"] <= 999999
                or not re.fullmatch(re.escape(SHARED.AUTH_PREFIX) + r"[A-Za-z0-9]+-[A-Za-z0-9]+", entry["key"])
                or not timedelta(days=7) <= remaining <= timedelta(days=90)):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise G.Failure("Production key must match its existing tag/type and have 7-90 days remaining") from None
    return entry


def trusted_authorities():
    status = G.read_json(["tailscale", "status", "--json"], "existing local tailnet")
    lock = G.read_json(["tailscale", "lock", "status", "--json"], "existing Tailnet Lock")
    try:
        trusted = {item.get("Public", item.get("Key")): item.get("Meta", item.get("Metadata"))
                   for item in lock["TrustedKeys"]}
        if (status["BackendState"] != "Running" or status["Self"]["Online"] is not True
                or status["CurrentTailnet"]["MagicDNSSuffix"] != "tail67beb.ts.net"
                or lock["Enabled"] is not True or lock["NodeKeySigned"] is not True
                or lock["PublicKey"] not in trusted
                or not all(isinstance(k, str) and re.fullmatch(r"tlpub:[0-9a-f]{64}", k) for k in trusted)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise G.Failure("Existing online homelab profile must be signed with Tailnet Lock enabled") from None
    return trusted


def cached_production(entry, trusted):
    path = SHARED.CACHE
    SHARED.private_metadata(path.parent, directory=True)
    SHARED.private_metadata(path)
    if path.stat().st_size > 1024 * 1024:
        raise G.Failure("Private signed-key cache exceeds bound")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as f:
        cache = json.load(f)
    if not isinstance(cache, list):
        raise G.Failure("Private signed-key cache is invalid")
    matches = [item for item in cache if isinstance(item, dict) and item.get("identity") == "apply"
               and item.get("fingerprint") == SHARED.fingerprint(entry)]
    if len(matches) != 1:
        raise G.Failure("Exactly one previously signed production key is required; signing is not supported")
    saved = matches[0]
    SHARED.validate_wrapped_key(saved.get("wrapped"))
    if (saved.get("generation") != entry["generation"]
            or not saved["wrapped"].startswith(entry["key"] + "--TL")
            or not SHARED.authority_matches(saved["wrapped"], saved.get("authority"), trusted)):
        raise G.Failure("Cached production key does not match current provider/trust metadata")
    return saved


def destination_absent():
    if G.read_json(["gh", "api", "--hostname", "github.com", "user"], "operator identity").get("login") != "rstuhlmuller":
        raise G.Failure("Production installation requires the approved rstuhlmuller identity")
    if G.github("branches/main", "main protection").get("protected") is not True:
        raise G.Failure("Production requires protected main")
    G.verify_protection(ENVIRONMENT, G.github("environments/" + ENVIRONMENT, "production protection"))
    policies = G.github("environments/" + ENVIRONMENT + "/deployment-branch-policies", "production branches")
    branches = policies.get("branch_policies")
    if (not isinstance(branches, list) or len(branches) != 1
            or branches[0].get("name") != "main" or branches[0].get("type") != "branch"):
        raise G.Failure("Production must admit exactly main")
    existing = G.read_json(["gh", "secret", "list", "--repo", G.HOST_REPO, "--env", ENVIRONMENT,
                            "--json", "name"], "production secret metadata")
    if not isinstance(existing, list) or any(not isinstance(x, dict) or not isinstance(x.get("name"), str) for x in existing):
        raise G.Failure("Production secret metadata is invalid")
    if any(x["name"] == SECRET for x in existing):
        raise G.Failure("Production secret already exists; replacement needs separate approval")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--generation", type=int)
    p.add_argument("--authority")
    p.add_argument("--expires-at")
    args = p.parse_args(argv)
    try:
        revision = G.verify_main()
        destination_absent()
        entry = production_key()
        saved = cached_production(entry, trusted_authorities())
        if not args.execute:
            print(json.dumps({"identity": "apply", "tag": TAG, "generation": entry["generation"],
                              "expires_at": entry["expires_at"], "authority": saved["authority"],
                              "destination": ENVIRONMENT + "/" + SECRET,
                              "reusable": True, "ephemeral": True, "new_signing": False}))
            return 0
        if (args.generation != entry["generation"] or args.authority != saved["authority"]
                or args.expires_at != entry["expires_at"]):
            raise G.Failure("Execution requires the reviewed generation, expiry and existing authority")
        if G.verify_main() != revision:
            raise G.Failure("Current main changed; stopped")
        destination_absent()
        # shortcut: GitHub secrets have no compare-and-set; require a publication quiet window.
        G.command(["gh", "secret", "set", SECRET, "--repo", G.HOST_REPO, "--env", ENVIRONMENT],
                  "production-only key publication", data=saved["wrapped"] + "\n")
        result = G.read_json(["gh", "secret", "list", "--repo", G.HOST_REPO, "--env", ENVIRONMENT,
                              "--json", "name"], "production publication metadata")
        if not isinstance(result, list) or not any(x.get("name") == SECRET for x in result if isinstance(x, dict)):
            raise G.Failure("Publication outcome unverified; inspect metadata before any retry")
        print("Installed production CI secret only; no signing, enrollment or other identity changes.")
        return 0
    except G.Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - never expose secret-bearing provider/cache/subprocess exceptions.
        print("Production-only preview/install stopped; private details withheld.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
