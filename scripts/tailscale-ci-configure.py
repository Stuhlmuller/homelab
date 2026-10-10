#!/usr/bin/env python3
"""Sign provider-managed CI keys and publish only their fixed GitHub secrets."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("entra_ci_guards", ROOT / "scripts/entra-ci-configure.py")
GUARDS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARDS)
TAILSCALE = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
AUTH_PREFIX = "-".join(("tskey", "auth", ""))
CACHE = Path.home() / ".config/homelab/tailscale/ci-signed-keys.json"
BINDINGS = {
    "plan": ("homelab-plan", "TAILSCALE_AUTH_KEY", "TAILSCALE_CLIENT_ID"),
    "apply": ("homelab-production", "TAILSCALE_AUTH_KEY", "TAILSCALE_CLIENT_ID"),
    "cordium": (None, "TAILSCALE_CORDIUM_AUTH_KEY", "TAILSCALE_CORDIUM_CLIENT_ID"),
}


def read_identity():
    values = GUARDS.read_json([
        "terragrunt", "--log-disable", "--working-dir",
        str(ROOT / "IaC/operator/tailscale-access"), "output", "-json",
    ], "private Tailscale operator outputs")
    try:
        output = values["github_auth_keys"]
        keys = output["value"]
        if (set(values) != {"github_auth_keys", "github_identity_client_ids"}
                or output["sensitive"] is not True or set(keys) != set(BINDINGS)):
            raise ValueError
        for identity, entry in keys.items():
            key = entry["key"]
            expiry = datetime.fromisoformat(entry["expires_at"].replace("Z", "+00:00"))
            if (not isinstance(key, str) or not re.fullmatch(re.escape(AUTH_PREFIX) + r"[A-Za-z0-9]+-[A-Za-z0-9]+", key)
                    or not isinstance(entry["id"], str) or not 0 < len(entry["id"]) <= 1024
                    or not all("!" <= char <= "~" for char in entry["id"])
                    or entry["invalid"] is not False
                    or any(entry[name] is not True for name in ("reusable", "ephemeral", "preauthorized"))
                    or entry["tags"] != [f"tag:homelab-ci-{identity}"]
                    or type(entry["generation"]) is not int or not 1 <= entry["generation"] <= 999999
                    or expiry < datetime.now(timezone.utc) + timedelta(days=7)):
                raise ValueError
        if (len({entry["id"] for entry in keys.values()}) != 3
                or len({entry["key"] for entry in keys.values()}) != 3
                or len({entry["generation"] for entry in keys.values()}) != 1):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise GUARDS.Failure("Operator output must contain three distinct, valid scoped CI keys with at least seven days remaining") from None
    return keys


def names(kind, environment):
    scope = ["--env", environment] if environment else []
    entries = GUARDS.read_json(["gh", kind, "list", "--repo", GUARDS.HOST_REPO,
                               *scope, "--json", "name"], "GitHub setting names lookup")
    if (not isinstance(entries, list) or any(not isinstance(item, dict)
            or not isinstance(item.get("name"), str) for item in entries)):
        raise GUARDS.Failure("GitHub setting names lookup returned invalid data")
    return {item["name"] for item in entries}


def verify_destinations():
    for environment in GUARDS.ENVIRONMENTS.values():
        GUARDS.verify_protection(environment, GUARDS.github(
            f"environments/{environment}", "environment protection lookup"))
    if GUARDS.github("branches/main", "main protection lookup").get("protected") is not True:
        raise GUARDS.Failure("Production deployment requires a protected main branch")
    for environment in (None, *GUARDS.ENVIRONMENTS.values()):
        for kind, common, cordium in (("secret", "TAILSCALE_AUTH_KEY", "TAILSCALE_CORDIUM_AUTH_KEY"),
                                     ("variable", "TAILSCALE_CLIENT_ID", "TAILSCALE_CORDIUM_CLIENT_ID")):
            if (cordium if environment else common) in names(kind, environment):
                raise GUARDS.Failure("A Tailscale setting exists outside its declared scope")


def lock_status():
    status = GUARDS.read_json([TAILSCALE, "status", "--json"], "local Tailscale profile")
    if (status.get("BackendState") != "Running" or status.get("Self", {}).get("Online") is not True
            or status.get("CurrentTailnet", {}).get("MagicDNSSuffix") != "tail67beb.ts.net"):
        raise GUARDS.Failure("Signing requires the online homelab tailnet profile")
    value = GUARDS.read_json([TAILSCALE, "lock", "status", "--json"], "local Tailnet Lock status")
    try:
        trusted = {item["Public"]: item.get("Meta", {}) for item in value["TrustedKeys"]}
        if (value["Enabled"] is not True or value["NodeKeySigned"] is not True
                or value["PublicKey"] not in trusted
                or not all(re.fullmatch(r"tlpub:[0-9a-f]{64}", key) for key in trusted)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise GUARDS.Failure("This Mac must be an authorized, trusted Tailnet Lock signer") from None
    return trusted


def validate_wrapped_key(wrapped):
    # Upstream tka.DecodeWrappedAuthkey: --TL<credential>-<delegated private key>.
    # The delegated key is distinct from the trusted credential signer.
    try:
        _, suffix = wrapped.split("--TL", 1)
        signature, encoded = suffix.split("-", 1)
        raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
        sig = base64.b64decode(signature + "=" * (-len(signature) % 4), validate=True)
        if len(raw) != 64 or not sig or len(wrapped) > 16384:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise GUARDS.Failure("Signed-key output or private cache is invalid; details withheld") from None


def private_metadata(path, directory=False):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)):
        raise GUARDS.Failure("Tailscale private cache requires an owned 0700 directory and regular 0600 files")


def read_cache():
    if not CACHE.parent.exists():
        return []
    private_metadata(CACHE.parent, directory=True)
    if not CACHE.exists() and not CACHE.is_symlink():
        return []
    private_metadata(CACHE)
    with os.fdopen(os.open(CACHE, os.O_RDONLY | os.O_NOFOLLOW)) as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise GUARDS.Failure("Tailscale private cache is invalid")
    for entry in value:
        if (set(entry) != {"identity", "generation", "fingerprint", "wrapped", "authority"}
                or entry["identity"] not in BINDINGS or type(entry["generation"]) is not int
                or not re.fullmatch(r"[0-9a-f]{64}", entry["fingerprint"])
                or not re.fullmatch(r"tlpub:[0-9a-f]{64}", entry["authority"])):
            raise GUARDS.Failure("Tailscale private cache is invalid")
        validate_wrapped_key(entry["wrapped"])
    if (len({entry["fingerprint"] for entry in value}) != len(value)
            or len({entry["authority"] for entry in value}) != len(value)):
        raise GUARDS.Failure("Tailscale private cache contains duplicate key records")
    return value


def save_cache(entries):
    with tempfile.NamedTemporaryFile(mode="w", dir=CACHE.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(entries, handle)
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temporary, CACHE)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def locked_cache():
    CACHE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_metadata(CACHE.parent, directory=True)
    path = CACHE.parent / "ci-signed-keys.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as handle:
        private_metadata(path)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def fingerprint(entry):
    return hashlib.sha256(entry["key"].encode()).hexdigest()


def authority_matches(wrapped, authority, trusted):
    stable_id = wrapped.removeprefix(AUTH_PREFIX).split("-", 1)[0]
    matches = [public for public, metadata in trusted.items()
               if isinstance(metadata, dict) and metadata.get("purpose") == "pre-auth key"
               and metadata.get("authkey_stableid") == stable_id]
    return matches == [authority]


def signed_keys(keys, cache):
    result = {}
    for identity, entry in keys.items():
        matches = [item for item in cache if item["fingerprint"] == fingerprint(entry)]
        trusted = lock_status()
        if matches:
            saved = matches[0]
            if (saved["identity"] != identity or saved["generation"] != entry["generation"]
                    or not saved["wrapped"].startswith(entry["key"] + "--TL")
                    or not authority_matches(saved["wrapped"], saved["authority"], trusted)):
                raise GUARDS.Failure("Cached signed key no longer matches trusted provider state")
            result[identity] = saved["wrapped"]
            continue
        stable_id = entry["key"].removeprefix(AUTH_PREFIX).split("-", 1)[0]
        if any(isinstance(meta, dict) and meta.get("authkey_stableid") == stable_id for meta in trusted.values()):
            raise GUARDS.Failure("An uncached authority already signs this auth key; recover its private cache before retrying")
        with tempfile.NamedTemporaryFile(mode="w", dir=CACHE.parent) as raw:
            raw.write(entry["key"])
            raw.flush()
            wrapped = GUARDS.command([TAILSCALE, "lock", "sign", "file:" + raw.name],
                                     "CI key signing").strip()
        validate_wrapped_key(wrapped)
        after = lock_status()
        added = set(after) - set(trusted)
        # CLI wrapAuthKey adds one credential signer; its separate delegated key
        # is embedded in the wrapper. Preserve the exact successful CLI receipt.
        if (not wrapped.startswith(entry["key"] + "--TL") or len(added) != 1
                or any(public not in after or after[public] != metadata for public, metadata in trusted.items())):
            raise GUARDS.Failure("Signing changed an unexpected trusted authority; publication stopped")
        authority = added.pop()
        if not authority_matches(wrapped, authority, after):
            raise GUARDS.Failure("New signed key did not match the provider key and trusted signing authority")
        cache.append({"identity": identity, "generation": entry["generation"],
                      "fingerprint": fingerprint(entry), "wrapped": wrapped, "authority": authority})
        save_cache(cache)  # Persist each signature before any GitHub write so retry does not add authorities.
        result[identity] = wrapped
    return result


def publish(keys):
    for identity, (environment, name, _) in BINDINGS.items():
        scope = ["--env", environment] if environment else []
        GUARDS.command(["gh", "secret", "set", name, "--repo", GUARDS.HOST_REPO, *scope],
                       "Tailscale signed-key publication", data=keys[identity] + "\n")
    # GitHub cannot return secret values. Confirm presence only; runtime CI proves usability.
    for environment, name, _ in BINDINGS.values():
        if name not in names("secret", environment):
            raise GUARDS.Failure("Published secret metadata is missing; identity variables were retained")
    for environment, _, old_name in BINDINGS.values():
        if old_name in names("variable", environment):
            scope = ["--env", environment] if environment else []
            GUARDS.command(["gh", "variable", "delete", old_name, "--repo", GUARDS.HOST_REPO, *scope],
                           "unused Tailscale identity variable retirement")


def previous_records(keys, cache):
    current = {fingerprint(entry) for entry in keys.values()}
    previous = [entry for entry in cache if entry["fingerprint"] not in current]
    if any(entry["generation"] >= keys[entry["identity"]]["generation"] for entry in previous):
        raise GUARDS.Failure("Refusing signing-authority retirement across a reversed or reused generation")
    return previous


def retire(keys, cache):
    # Explicit post-acceptance operation. Never remove an arbitrary trusted signer.
    if not {fingerprint(entry) for entry in keys.values()}.issubset({entry["fingerprint"] for entry in cache}):
        raise GUARDS.Failure("Publish and validate current signed keys before retiring previous authority")
    signed_keys(keys, cache)  # All current keys must already be cached; this cannot create new signatures.
    for record in previous_records(keys, cache):
        trusted = lock_status()
        public = record["authority"]
        if public in trusted:
            if not authority_matches(record["wrapped"], public, trusted):
                raise GUARDS.Failure("Previous signing authority does not match the private CI cache")
            GUARDS.command([TAILSCALE, "lock", "remove", public], "previous CI signing-authority retirement")
            if public in lock_status():
                raise GUARDS.Failure("Previous CI signing authority is still trusted")
        cache.remove(record)
        save_cache(cache)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Sign and publish three fixed scoped CI secrets")
    parser.add_argument("--retire-previous", action="store_true", help="After successful replacement CI runs, retire cached older signing authorities")
    args = parser.parse_args(argv)
    try:
        revision = GUARDS.verify_main() if args.execute else None
        keys = read_identity()
        verify_destinations()
        lock_status()
        previous_records(keys, read_cache())
        if not args.execute:
            print("Preview passed: provider keys, destination scopes and local signer validated; nothing changed.")
            return 0
        with locked_cache():
            cache = read_cache()
            if GUARDS.verify_main() != revision:
                raise GUARDS.Failure("Current main changed during preflight; execution stopped")
            verify_destinations()
            if args.retire_previous:
                retire(keys, cache)
            else:
                signed = signed_keys(keys, cache)
                if GUARDS.verify_main() != revision:
                    raise GUARDS.Failure("Current main changed during signing; publication stopped")
                verify_destinations()
                publish(signed)
    except GUARDS.Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - secret-bearing API/subprocess/cache exceptions stay private.
        print("Tailscale CI configuration failed; private details withheld", file=sys.stderr)
        return 1
    print("Previous CI signing authorities retired." if args.retire_previous else
          "Published three scoped CI secrets and checked metadata; verify them with protected CI runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
