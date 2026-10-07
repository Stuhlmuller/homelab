#!/usr/bin/env python3
"""Mock the operator boundary: oid identity survives email reuse and failed preflight never writes."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SCRIPT = Path(__file__).resolve().parents[1] / "octelium-entra-oidc.sh"
OWNER = "11111111-1111-4111-8111-111111111111"
PILOT = "22222222-2222-4222-8222-222222222222"
CLIENT = "33333333-3333-4333-8333-333333333333"
ISSUER = "https://login.microsoftonline.com/44444444-4444-4444-8444-444444444444/v2.0"
ARGS = ["--admin-user-name", "owner", "--admin-email", "person@example.com", "--admin-object-id", OWNER]
PROVIDER = {"metadata": {"name": "entra", "labels": {"retained": "yes"}},
            "spec": {"oidc": {"identifierClaim": "preferred_username", "clientID": CLIENT,
                               "issuerURL": ISSUER, "scopes": ["openid", "email", "profile"]}}}
USER = {"metadata": {"name": "owner", "displayName": "Existing owner"}, "spec": {
    "type": "HUMAN", "email": "person@example.com", "groups": ["existing-group"],
    "authorization": {"policies": ["existing-policy"]}, "authentication": {
        "identities": [{"identityProvider": "entra", "identifier": "person@example.com"},
                       {"identityProvider": "other", "identifier": "preserved"}],
        "preferredSessionDuration": "1h"}}}
MOCK = r'''
import json
from pathlib import Path
import sys
state_path = Path(__file__).parent / "state.json"
state = json.loads(state_path.read_text())
args = sys.argv[1:]
def record(event):
    state.setdefault("events", []).append(event)
    state_path.write_text(json.dumps(state))
if Path(sys.argv[0]).name == "aws":
    name = args[args.index("--name") + 1].rsplit("/", 1)[-1]
    record({"read": name})
    print(state["parameters"][name])
elif args[0] == "get":
    kind = args[1]
    if state.get("read_error") == kind:
        sys.exit(1)
    if kind == "secret":
        print("existing")
    else:
        items = state["providers" if kind == "identityprovider" else "users"]
        print(json.dumps({"items": items, "listResponseMeta": {
            "itemsPerPage": 1000, "totalCount": len(items) + int(state.get("truncated", False))}}))
elif args[0] == "apply":
    resource = json.loads(Path(args[-1]).read_text())
    if state.get("apply_error") == resource["kind"]:
        print("Could not update " + resource["kind"])
    else:
        key = "users" if resource["kind"] == "User" else "providers"
        state[key] = [item for item in state[key] if item["metadata"]["name"] != resource["metadata"]["name"]] + [resource]
        record({"write": resource})
        print("Updated " + resource["kind"])
else:
    assert args[0] in ("create", "update") and args[1] == "secret"
    assert sys.stdin.read() == "fixture-secret"
    record({"write": "Secret"})
'''


def exercise(*, args=ARGS, provider=PROVIDER, users=None, **overrides):
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        state = {"parameters": {"client-id": CLIENT, "issuer-url": ISSUER, "client-secret": "fixture-secret"},
                 "providers": [provider] if provider else [], "users": copy.deepcopy(users if users is not None else [USER]),
                 **overrides}
        (directory / "state.json").write_text(json.dumps(state))
        for command in ("aws", "octeliumctl"):
            path = directory / command
            path.write_text(f"#!{sys.executable}\n" + MOCK)
            path.chmod(0o700)
        result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                                env={**os.environ, "PATH": str(directory) + os.pathsep + os.environ["PATH"]}, timeout=15)
        return result, json.loads((directory / "state.json").read_text())


def no_write(result, state):
    assert result.returncode != 0, result.stdout
    assert not any("write" in event for event in state.get("events", [])), state
    assert {"read": "client-secret"} not in state.get("events", []), state


# Existing contact, groups, authentication settings, other IdP and authorization survive.
result, migrated = exercise()
assert result.returncode == 0, result.stderr
writes = [event["write"] for event in migrated["events"] if "write" in event]
assert [item if isinstance(item, str) else item["kind"] for item in writes] == ["Secret", "User", "IdentityProvider"]
owner = migrated["users"][0]
expected = copy.deepcopy(USER)
expected["kind"] = "User"
expected["spec"]["email"] = "person@example.com"
expected["spec"]["authentication"]["identities"] = [USER["spec"]["authentication"]["identities"][1],
    {"identityProvider": "entra", "identifier": OWNER}]
assert owner == expected
provider = migrated["providers"][0]
assert provider["spec"]["oidc"]["identifierClaim"] == "oid"
assert provider["metadata"] == PROVIDER["metadata"]
# Reusing the former alias cannot authenticate as owner or replace an oid binding.
assert all(item["identifier"] != "person@example.com" for item in owner["spec"]["authentication"]["identities"])
assert owner["spec"]["authentication"]["identities"][-1]["identifier"] != PILOT
no_write(*exercise(provider=provider, users=[owner], args=ARGS[:-1] + [PILOT]))
# Normal refresh retains oid matching; dry-run reads no secret and writes nothing.
result, refreshed = exercise(provider=provider, users=[owner], args=[])
assert result.returncode == 0, result.stderr
assert refreshed["users"] == [owner]
assert refreshed["providers"][0]["spec"]["oidc"]["identifierClaim"] == "oid"
result, preview = exercise(args=ARGS + ["--dry-run"])
assert result.returncode == 0, result.stderr
assert not any("write" in event or event.get("read") == "client-secret" for event in preview["events"])
# Legacy refresh, incomplete flags, invalid oid, reads and incomplete inventories fail closed.
for options in ({"args": []}, {"args": ARGS[:-2]}, {"args": ARGS[:-1] + ["not-a-uuid"]},
                {"args": [*ARGS[:3], "wrong@example.com", *ARGS[4:]]},
                {"truncated": True}, {"read_error": "user"}, {"read_error": "identityprovider"}):
    no_write(*exercise(**options))
other = copy.deepcopy(USER)
other["metadata"]["name"] = "other-human"
other["spec"]["authentication"]["identities"][0]["identifier"] = "other@example.com"
no_write(*exercise(users=[USER, other]))
other["spec"]["authentication"]["identities"][0]["identifier"] = OWNER
no_write(*exercise(provider=provider, users=[other]))
no_write(*exercise(provider=provider))  # stale email binding under an oid provider
workload = copy.deepcopy(USER)
workload["spec"]["type"] = "WORKLOAD"
no_write(*exercise(users=[workload]))
duplicate = copy.deepcopy(USER)
duplicate["spec"]["authentication"]["identities"].append(
    {"identityProvider": "entra", "identifier": "another@example.com"})
no_write(*exercise(users=[duplicate]))
# A partially completed migration is retryable with the same verified object ID.
result, retried = exercise(users=[owner])
assert result.returncode == 0, result.stderr
assert retried["providers"][0]["spec"]["oidc"]["identifierClaim"] == "oid"
wrong_tenant = copy.deepcopy(PROVIDER)
wrong_tenant["spec"]["oidc"]["issuerURL"] = ISSUER.replace("44444444", "55555555")
no_write(*exercise(provider=wrong_tenant))
# A failed native User apply (even exit 0) must not switch the IdP claim.
result, failed = exercise(apply_error="User")
assert result.returncode != 0
assert failed["providers"][0]["spec"]["oidc"]["identifierClaim"] == "preferred_username"
assert not any(isinstance(event.get("write"), dict) for event in failed["events"])
# Fresh setup retains the new-user policy, with no email authorization binding.
result, fresh = exercise(provider=None, users=[])
assert result.returncode == 0, result.stderr
assert fresh["users"][0]["spec"]["authorization"]["policies"] == ["allow-all"]
assert fresh["users"][0]["spec"]["authentication"]["identities"][0]["identifier"] == OWNER
print("Octelium Entra oid migration boundary: passed")
