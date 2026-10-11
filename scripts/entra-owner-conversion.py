#!/usr/bin/env python3
"""Prepare and attest the one supported Entra owner conversion without Graph writes."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
REPO = "Stuhlmuller/homelab"
OWNER_OBJECT_ID = "08dfba7f-71ea-4eae-ae56-b3fb6cb2ad45"
OWNER_UPN = "rodman@stinkyboi.com"
TARGET_UPN = "rodman@stuhlmuller.net"
TARGET_DOMAIN = "stuhlmuller.net"
EMERGENCY_ADMIN_LOCAL_PART = "homelab-emergency-admin"
GLOBAL_ADMINISTRATOR_ROLE_DEFINITION_ID = "62e90394-69f5-4237-9190-012177145e10"
RECEIPT_NAME = "entra-owner-conversion.json"
SHA = re.compile(r"[0-9a-f]{40}")


class Failure(Exception):
    """Only fixed diagnostics may cross the private identity boundary."""


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward the Microsoft Graph bearer token to a redirect target."""

    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise Failure("Microsoft Graph read rejected a redirect")


GRAPH_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    RejectRedirects(),
)


def command(args, operation):
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False,
                                cwd=ROOT, timeout=120)
    except (OSError, subprocess.SubprocessError):
        raise Failure(f"{operation} failed; private output withheld") from None
    if result.returncode:
        raise Failure(f"{operation} failed; private output withheld")
    return result.stdout


def read_json(args, operation):
    try:
        return json.loads(command(args, operation))
    except (TypeError, ValueError):
        raise Failure(f"{operation} returned invalid data; private output withheld") from None


def github(path, operation):
    return read_json(["gh", "api", "--hostname", "github.com", f"repos/{REPO}/{path}"], operation)


def verify_main(expected_sha):
    if not SHA.fullmatch(expected_sha):
        raise Failure("Expected SHA must be a full lowercase commit SHA")
    if command(["git", "status", "--porcelain=v1", "--untracked-files=all",
                "--ignore-submodules=none"], "checkout cleanliness"):
        raise Failure("Execution requires a clean checkout, including untracked files")
    head = command(["git", "rev-parse", "HEAD"], "checkout revision").strip()
    current = github("commits/main", "verified main lookup")
    if (head != expected_sha or current.get("sha") != head
            or current.get("commit", {}).get("verification", {}).get("verified") is not True):
        raise Failure("Execution requires the expected signed, verified current GitHub main")
    return head


def private_directory(raw):
    path = raw.expanduser().absolute()
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError:
        raise Failure("Receipt directory must already exist as a private directory outside Git") from None
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise Failure("Receipt directory must be owner-only mode 0700 and must not be a symlink")
    if resolved.is_relative_to(ROOT) or any((parent / ".git").exists()
                                           for parent in (resolved, *resolved.parents)):
        raise Failure("Receipt directory must be outside Git repositories")
    return resolved


def private_file(path):
    try:
        info = path.lstat()
    except OSError:
        raise Failure("Private conversion receipt is missing") from None
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise Failure("Conversion receipt must be an owner-only mode 0600 regular file")


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_new_receipt(path, value):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise Failure("Conversion receipt already exists; inspect or attest it instead of preparing again") from None
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    sync_directory(path.parent)
    private_file(path)


def replace_receipt(path, value):
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
        private_file(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def read_receipt(path):
    private_file(path)
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        raise Failure("Conversion receipt is invalid; private details withheld") from None
    if not isinstance(value, dict):
        raise Failure("Conversion receipt is invalid; private details withheld")
    return value


def graph_token():
    value = read_json([
        "az", "account", "get-access-token", "--resource-type", "ms-graph",
        "--output", "json", "--only-show-errors",
    ], "Microsoft Graph token lookup")
    token = value.get("accessToken") if isinstance(value, dict) else None
    if not isinstance(token, str) or len(token) < 20:
        raise Failure("Microsoft Graph token lookup returned invalid data; private output withheld")
    return token


def graph_get(token, path, *, missing=False):
    if not path or path.startswith(("http:", "https:")):
        raise Failure("Microsoft Graph read path is invalid")
    request = urllib.request.Request(
        "https://graph.microsoft.com/v1.0/" + path.lstrip("/"),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, method="GET",
    )
    try:
        with GRAPH_OPENER.open(request, timeout=30) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if getattr(response, "status", 200) != 200 or len(raw) > 2 * 1024 * 1024:
                raise Failure("Microsoft Graph read returned an invalid response")
    except urllib.error.HTTPError as error:
        if missing and error.code == 404:
            return None
        raise Failure("Microsoft Graph read failed; private details withheld") from None
    except (OSError, ValueError):
        raise Failure("Microsoft Graph read failed; private details withheld") from None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise Failure("Microsoft Graph read returned invalid data; private details withheld") from None
    if not isinstance(value, dict):
        raise Failure("Microsoft Graph read returned invalid data; private details withheld")
    return value


def emergency_role_assignment_path(actor_id):
    return "roleManagement/directory/roleAssignments?" + urllib.parse.urlencode({
        "$filter": " and ".join((
            f"principalId eq '{actor_id}'",
            f"roleDefinitionId eq '{GLOBAL_ADMINISTRATOR_ROLE_DEFINITION_ID}'",
            "directoryScopeId eq '/'",
        )),
        "$select": "id,principalId,roleDefinitionId,directoryScopeId,appScopeId",
    })


def graph_state(include_actor=False, recovery_actor_id=None):
    token = graph_token()
    owner = graph_get(token, f"users/{OWNER_OBJECT_ID}?$select=id,userPrincipalName,userType,creationType,externalUserState,accountEnabled,identities,onPremisesSyncEnabled,lastPasswordChangeDateTime")
    domain = graph_get(token, f"domains/{TARGET_DOMAIN}")
    domains = graph_get(token, "domains?$select=id,isVerified,authenticationType,isDefault,isInitial")
    target = graph_get(token, "users/" + urllib.parse.quote(TARGET_UPN, safe="@") + "?$select=id",
                       missing=True)
    state = {"owner": owner, "domain": domain,
             "default_domain": default_domain_state(domains), "target": target}
    if include_actor:
        state["actor"] = graph_get(token, "me?$select=id,userPrincipalName")
    if recovery_actor_id is not None:
        initial_domain = initial_domain_state(domains)
        actor_path = "me?$select=id,userPrincipalName,userType,accountEnabled,onPremisesSyncEnabled,externalUserState"
        if recovery_actor_id:
            actor_path = "users/" + urllib.parse.quote(recovery_actor_id, safe="") + "?$select=id,userPrincipalName,userType,accountEnabled,onPremisesSyncEnabled,externalUserState"
        actor = emergency_actor_state(graph_get(
            token, actor_path
        ), initial_domain)
        state["recovery"] = {
            "initial_domain": initial_domain,
            "actor": actor,
            "assignment": graph_get(token, emergency_role_assignment_path(actor["id"])),
        }
    return state


def domain_state(value):
    if (not isinstance(value, dict) or value.get("id") != TARGET_DOMAIN
            or value.get("isVerified") is not True or value.get("authenticationType") != "Managed"
            or value.get("isDefault") is not False or value.get("isInitial") is not False):
        raise Failure("The target Entra domain is not verified, managed, non-default, and non-initial")
    return {key: value[key] for key in
            ("id", "isVerified", "authenticationType", "isDefault", "isInitial")}


def default_domain_state(value):
    domains = value.get("value") if isinstance(value, dict) else None
    matches = [domain for domain in domains if isinstance(domain, dict)
               and domain.get("isDefault") is True] if isinstance(domains, list) else []
    if len(matches) != 1:
        raise Failure("The tenant default Entra domain does not match the required conversion state")
    domain = matches[0]
    if not isinstance(domain.get("id"), str) or domain.get("isVerified") is not True:
        raise Failure("The tenant default Entra domain does not match the required conversion state")
    return {key: domain[key] for key in ("id", "isVerified", "isDefault")}


def initial_domain_state(value):
    domains = value.get("value") if isinstance(value, dict) else None
    matches = [domain for domain in domains if isinstance(domain, dict)
               and domain.get("isInitial") is True] if isinstance(domains, list) else []
    if len(matches) != 1:
        raise Failure("The independent Entra recovery administrator does not match the required state")
    domain = matches[0]
    if (not isinstance(domain.get("id"), str) or not domain["id"].endswith(".onmicrosoft.com")
            or domain.get("isVerified") is not True
            or domain.get("authenticationType") != "Managed"
            or domain.get("isDefault") is not False):
        raise Failure("The independent Entra recovery administrator does not match the required state")
    return {key: domain[key] for key in
            ("id", "isVerified", "authenticationType", "isDefault", "isInitial")}


def emergency_actor_state(value, initial_domain):
    expected_upn = f"{EMERGENCY_ADMIN_LOCAL_PART}@{initial_domain['id']}"
    if (not isinstance(value, dict) or not isinstance(value.get("id"), str)
            or value.get("id") == OWNER_OBJECT_ID or value.get("userPrincipalName") != expected_upn
            or value.get("userType") != "Member" or value.get("accountEnabled") is not True
            or "onPremisesSyncEnabled" not in value or value["onPremisesSyncEnabled"] is not None
            or "externalUserState" not in value or value["externalUserState"] is not None):
        raise Failure("The independent Entra recovery administrator does not match the required state")
    try:
        uuid.UUID(value["id"])
    except (TypeError, ValueError):
        raise Failure("The independent Entra recovery administrator does not match the required state") from None
    return {key: value[key] for key in
            ("id", "userPrincipalName", "userType", "accountEnabled", "onPremisesSyncEnabled",
             "externalUserState")}


def emergency_role_assignment_state(value, actor):
    assignments = value.get("value") if isinstance(value, dict) else None
    if not isinstance(assignments, list) or value.get("@odata.nextLink") is not None:
        raise Failure("The independent Entra recovery administrator does not match the required state")
    matches = [assignment for assignment in assignments if isinstance(assignment, dict)
               and assignment.get("principalId") == actor["id"]
               and assignment.get("roleDefinitionId") == GLOBAL_ADMINISTRATOR_ROLE_DEFINITION_ID
               and assignment.get("directoryScopeId") == "/"
               and assignment.get("appScopeId") is None]
    if len(matches) != 1 or len(assignments) != 1:
        raise Failure("The independent Entra recovery administrator does not match the required state")
    assignment = matches[0]
    if not isinstance(assignment.get("id"), str):
        raise Failure("The independent Entra recovery administrator does not match the required state")
    return {key: assignment[key] for key in
            ("id", "principalId", "roleDefinitionId", "directoryScopeId", "appScopeId")}


def recovery_state(value, *, stored=False):
    if not isinstance(value, dict):
        raise Failure("The independent Entra recovery administrator does not match the required state")
    initial_domain = initial_domain_state({"value": [value.get("initial_domain")]})
    actor = emergency_actor_state(value.get("actor"), initial_domain)
    assignment_value = value.get("assignment")
    if stored:
        assignment_value = {"value": [assignment_value]}
    assignment = emergency_role_assignment_state(assignment_value, actor)
    return {"initial_domain": initial_domain, "actor": actor, "assignment": assignment}


def owner_state(value, expected_upn=None, external=False):
    if (not isinstance(value, dict) or value.get("id") != OWNER_OBJECT_ID
            or value.get("userType") != "Member" or value.get("accountEnabled") is not True
            or not isinstance(value.get("userPrincipalName"), str)):
        raise Failure("The immutable Entra owner does not match the required conversion state")
    if expected_upn is not None and value["userPrincipalName"] != expected_upn:
        raise Failure("The immutable Entra owner does not match the required conversion state")
    fields = ("id", "userPrincipalName", "userType", "accountEnabled")
    if external:
        if value.get("creationType") != "Invitation" or value.get("externalUserState") != "Accepted":
            raise Failure("The immutable Entra owner does not match the required conversion state")
        fields += ("creationType", "externalUserState")
    return {key: value[key] for key in fields}


def internal_owner_state(value, expected_upn, default_domain):
    state = owner_state(value, expected_upn)
    if "externalUserState" not in value or value["externalUserState"] is not None:
        raise Failure("The immutable Entra owner does not match the required conversion state")
    identity = {
        "signInType": "userPrincipalName",
        "issuer": default_domain["id"],
        "issuerAssignedId": expected_upn,
    }
    if (value.get("identities") != [identity] or "onPremisesSyncEnabled" not in value
            or value["onPremisesSyncEnabled"] is not None):
        raise Failure("The immutable Entra owner does not match the required conversion state")
    return {**state, "externalUserState": None, "identities": [identity],
            "onPremisesSyncEnabled": None}


def timestamp_value(value):
    if not isinstance(value, str):
        raise Failure("The immutable Entra owner does not match the required conversion state")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Failure("The immutable Entra owner does not match the required conversion state") from None
    if parsed.tzinfo is None:
        raise Failure("The immutable Entra owner does not match the required conversion state")
    return parsed.astimezone(timezone.utc)


def fresh_local_password(value, prepared_at):
    if timestamp_value(value.get("lastPasswordChangeDateTime")) <= prepared_at:
        raise Failure("The immutable Entra owner does not match the required conversion state")


def actor_state(value):
    if (not isinstance(value, dict) or value.get("id") != OWNER_OBJECT_ID
            or value.get("userPrincipalName") != TARGET_UPN):
        raise Failure("The Microsoft Graph caller does not match the converted Entra owner")


def prepared_state(state):
    before = owner_state(state.get("owner"), OWNER_UPN, external=True)
    if before["userPrincipalName"] == TARGET_UPN or state.get("target") is not None:
        raise Failure("The target UPN is already occupied or the owner is already converted")
    default_domain = default_domain_state({"value": [state.get("default_domain")]})
    recovery = recovery_state(state.get("recovery"))
    return before, domain_state(state.get("domain")), default_domain, recovery


def attested_state(state, prepared_at, default_domain, recovery):
    if state.get("default_domain") != default_domain:
        raise Failure("The tenant default Entra domain does not match the required conversion state")
    after = internal_owner_state(state.get("owner"), TARGET_UPN, default_domain)
    fresh_local_password(state["owner"], prepared_at)
    actor_state(state.get("actor"))
    target = state.get("target")
    if not isinstance(target, dict) or target.get("id") != OWNER_OBJECT_ID:
        raise Failure("The converted target UPN does not resolve to the immutable Entra owner")
    if recovery_state(state.get("recovery")) != recovery:
        raise Failure("The independent Entra recovery administrator does not match the required state")
    return after, domain_state(state.get("domain"))


def receipt_base(receipt, expected_sha):
    if (receipt.get("schema") != 5 or receipt.get("owner_object_id") != OWNER_OBJECT_ID
            or receipt.get("target_upn") != TARGET_UPN or receipt.get("expected_sha") != expected_sha
            or receipt.get("status") not in ("prepared", "attested")
            or not isinstance(receipt.get("prepared_at"), str)
            or not isinstance(receipt.get("before"), dict) or not isinstance(receipt.get("domain"), dict)
            or not isinstance(receipt.get("default_domain"), dict)
            or not isinstance(receipt.get("recovery"), dict)):
        raise Failure("Conversion receipt does not match the reviewed transaction")
    owner_state(receipt["before"], OWNER_UPN, external=True)
    domain_state(receipt["domain"])
    default_domain = default_domain_state({"value": [receipt["default_domain"]]})
    recovery = recovery_state(receipt["recovery"], stored=True)
    prepared_at = timestamp_value(receipt["prepared_at"])
    if receipt["status"] == "attested":
        if not isinstance(receipt.get("attested_at"), str) or not isinstance(receipt.get("after"), dict):
            raise Failure("Conversion receipt does not match the reviewed transaction")
        internal_owner_state(receipt["after"], TARGET_UPN, default_domain)
    return prepared_at, default_domain, recovery


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def prepare(expected_sha, directory):
    verify_main(expected_sha)
    receipt_path = private_directory(directory) / RECEIPT_NAME
    if receipt_path.exists() or receipt_path.is_symlink():
        raise Failure("Conversion receipt already exists; inspect or attest it instead of preparing again")
    before, domain, default_domain, recovery = prepared_state(graph_state(recovery_actor_id=""))
    verify_main(expected_sha)
    write_new_receipt(receipt_path, {
        "schema": 5,
        "status": "prepared",
        "expected_sha": expected_sha,
        "owner_object_id": OWNER_OBJECT_ID,
        "target_upn": TARGET_UPN,
        "prepared_at": timestamp(),
        "before": before,
        "domain": domain,
        "default_domain": default_domain,
        "recovery": recovery,
    })
    print("Private conversion receipt prepared. In Entra admin center use only Convert to internal user for the existing owner, set the documented target UPN, then run attest. No Graph write was made.")


def attest(expected_sha, directory):
    verify_main(expected_sha)
    receipt_path = private_directory(directory) / RECEIPT_NAME
    receipt = read_receipt(receipt_path)
    prepared_at, default_domain, recovery = receipt_base(receipt, expected_sha)
    after, domain = attested_state(
        graph_state(include_actor=True, recovery_actor_id=recovery["actor"]["id"]),
        prepared_at, default_domain, recovery,
    )
    verify_main(expected_sha)
    if receipt["status"] == "prepared":
        receipt.update({"status": "attested", "attested_at": timestamp(), "after": after, "domain": domain})
        replace_receipt(receipt_path, receipt)
    elif receipt.get("after") != after or receipt.get("domain") != domain:
        raise Failure("Existing conversion attestation differs from current Entra state")
    print("Private conversion attestation passed. The immutable Entra owner now has the documented internal UPN.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    for action in ("prepare", "attest"):
        child = subcommands.add_parser(action)
        child.add_argument("--expected-sha", required=True)
        child.add_argument("--receipt-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            prepare(args.expected_sha, args.receipt_directory)
        else:
            attest(args.expected_sha, args.receipt_directory)
    except Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - identity/API details must never reach diagnostics.
        print("Entra conversion transaction failed; private details withheld", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
