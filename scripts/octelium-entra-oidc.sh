#!/usr/bin/env bash
set -euo pipefail

domain="stinkyboi.com"
region="us-west-2"
idp_name="entra"
idp_display_name="Login with Microsoft Entra"
secret_name="entra-oidc-client-secret"
client_id_parameter="/homelab/octelium/entra/client-id"
client_secret_parameter="/homelab/octelium/entra/client-secret"
issuer_url_parameter="/homelab/octelium/entra/issuer-url"
admin_user_name=""
admin_email=""
admin_object_id=""
dry_run=false

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-entra-oidc.sh [options]

Configures the Octelium Microsoft Entra OIDC IdentityProvider from the
Terragrunt-managed SSM parameters. The client secret is copied into an
Octelium native Secret and is never written to git.

Options:
  --domain DOMAIN                    Octelium Cluster domain. Default: stinkyboi.com
  --region REGION                    AWS region for SSM. Default: us-west-2
  --idp-name NAME                    Octelium IdentityProvider name. Default: entra
  --secret-name NAME                 Octelium Secret name for the client secret.
                                     Default: entra-oidc-client-secret
  --client-id-parameter NAME         SSM parameter containing the client ID.
  --client-secret-parameter NAME     SSM parameter containing the client secret.
  --issuer-url-parameter NAME        SSM parameter containing the issuer URL.
  --admin-user-name NAME             Optional HUMAN user name to apply.
  --admin-email EMAIL                New-user contact email; expected old identifier for migration.
  --admin-object-id UUID             Immutable Entra object ID for the HUMAN user.
  --dry-run                         Validate mappings without reading the client secret or writing.
  -h, --help                         Show this help.

All three admin options must be supplied together. Existing HUMAN fields,
including contact email and policies, are preserved; only a new user receives
allow-all. Legacy email matching (including implicit email fallback) can migrate
only the selected sole Entra user; --admin-email must match its old identifier.
The migrated provider disables email fallback. Verify the object ID with Microsoft Graph first; Octelium cannot
prove that an email and object ID belong to the same Entra account. Keep an
independent authenticated operator session available: the user mapping and IdP update are not atomic.
Verify fresh owner login before renaming or reusing any former email identifier.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      domain="$2"
      shift 2
      ;;
    --region)
      region="$2"
      shift 2
      ;;
    --idp-name)
      idp_name="$2"
      shift 2
      ;;
    --secret-name)
      secret_name="$2"
      shift 2
      ;;
    --client-id-parameter)
      client_id_parameter="$2"
      shift 2
      ;;
    --client-secret-parameter)
      client_secret_parameter="$2"
      shift 2
      ;;
    --issuer-url-parameter)
      issuer_url_parameter="$2"
      shift 2
      ;;
    --admin-user-name)
      admin_user_name="$2"
      shift 2
      ;;
    --admin-email)
      admin_email="$2"
      shift 2
      ;;
    --admin-object-id)
      admin_object_id="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown option $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command not found: $1" >&2
    exit 1
  fi
}

validate_name() {
  local value="$1"
  local label="$2"
  if [[ ! "$value" =~ ^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$ ]]; then
    echo "error: $label must use lowercase DNS-style characters: $value" >&2
    exit 1
  fi
}

validate_email() {
  local value="$1"
  if [[ ! "$value" =~ ^[^[:space:]\"\'\<\>]+@[^[:space:]\"\'\<\>]+$ ]]; then
    echo "error: --admin-email does not look like a safe email identifier" >&2
    exit 1
  fi
}

read_parameter() {
  local name="$1"
  aws ssm get-parameter \
    --region "$region" \
    --name "$name" \
    --with-decryption \
    --query 'Parameter.Value' \
    --output text
}

apply_identity_resources() {
  local apply_output

  if ! apply_output="$(octeliumctl apply --domain "$domain" "$1" 2>&1)"; then
    printf '%s\n' "$apply_output" >&2
    exit 1
  fi

  printf '%s\n' "$apply_output"

  if grep -Eq '(^|[[:space:]])Could not (create|update|apply)|gRPC error' <<<"$apply_output"; then
    echo "error: octeliumctl reported one or more failed resource changes" >&2
    exit 1
  fi
}

require_command aws
require_command octeliumctl
require_command python3
validate_name "$idp_name" "--idp-name"
validate_name "$secret_name" "--secret-name"
if [[ -n "$admin_user_name" ]]; then
  validate_name "$admin_user_name" "--admin-user-name"
fi
if [[ -n "$admin_email" ]]; then
  validate_email "$admin_email"
fi
if [[ -n "$admin_user_name$admin_email$admin_object_id" ]] &&
   [[ -z "$admin_user_name" || -z "$admin_email" || -z "$admin_object_id" ]]; then
  echo "error: all three --admin options must be supplied together" >&2
  exit 1
fi

client_id="$(read_parameter "$client_id_parameter")"
issuer_url="$(read_parameter "$issuer_url_parameter")"
identity_dir="$(mktemp -d "${TMPDIR:-/tmp}/octelium-entra-identity.XXXXXX")"
chmod 700 "$identity_dir"
trap 'test ! -d "$identity_dir" || rm -rf -- "$identity_dir"' EXIT

# Read every Entra mapping before any mutation, including native Secret writes.
python3 -I - "$domain" "$idp_name" "$admin_user_name" "$admin_email" \
  "$admin_object_id" "$client_id" "$issuer_url" "$secret_name" \
  "$idp_display_name" "$identity_dir" <<'PYTHON'
import json
import pathlib
import re
import subprocess
import sys
import uuid

(domain, idp_name, user_name, email, object_id, client_id, issuer,
 secret_name, display_name, directory) = sys.argv[1:]
path = pathlib.Path(directory)


def require(condition, message):
    if not condition:
        raise SystemExit("error: " + message)


def is_uuid(value):
    try:
        parsed = uuid.UUID(value)
        return parsed.int != 0 and str(parsed) == value.lower()
    except (ValueError, AttributeError, TypeError):
        return False


def inventory(kind):
    result = subprocess.run(["octeliumctl", "get", kind, "--domain", domain,
                             "--items-per-page", "1000", "-o", "json"],
                            capture_output=True, text=True, timeout=45)
    require(result.returncode == 0, "could not read Octelium identity inventory")
    empty = {"identityprovider": "No IdentityProviders found", "user": "No Users found"}
    if result.stdout.strip() == empty[kind]:
        return []
    value = json.loads(result.stdout)
    items = value["items"]
    # ponytail: one complete page only; add pagination if the inventory exceeds it.
    require(isinstance(items, list) and len(items) == int(value["listResponseMeta"]["totalCount"]),
            "identity inventory is incomplete; refuse a partial migration")
    require(len({item["metadata"]["name"] for item in items}) == len(items),
            "duplicate resource names in identity inventory")
    return items


try:
    require(not object_id or is_uuid(object_id), "--admin-object-id must be a nonzero UUID")
    object_id = object_id.lower()
    require(is_uuid(client_id), "SSM returned an invalid Entra client ID")
    require(re.fullmatch(r"https://login\.microsoftonline\.com/[0-9a-fA-F-]{36}/v2\.0", issuer)
            and is_uuid(issuer.split("/")[3]), "Entra issuer must identify one tenant")
    providers = inventory("identityprovider")
    users = inventory("user")
    provider = next((item for item in providers if item["metadata"]["name"] == idp_name), None)
    owner = next((item for item in users if item["metadata"]["name"] == user_name), None)
    oidc = provider["spec"].get("oidc", {}) if provider else {}
    claim = oidc.get("identifierClaim")
    require(not provider or (claim in ("oid", "preferred_username")
            and oidc.get("clientID") == client_id and oidc.get("issuerURL") == issuer),
            "existing Entra provider claim, client or tenant differs from the reviewed configuration")
    bindings = []
    for user in users:
        matches = [identity for identity in user["spec"].get("authentication", {}).get("identities", [])
                   if identity.get("identityProvider") == idp_name]
        require(len(matches) <= 1, "multiple Entra bindings on one user are unsupported")
        if matches:
            require(user["spec"]["type"] == "HUMAN", "Entra mapping belongs to a non-HUMAN user")
            identifier = matches[0].get("identifier")
            require(isinstance(identifier, str) and identifier, "invalid Entra user identifier")
            bindings.append((user["metadata"]["name"], identifier))
        elif (provider and not provider["spec"].get("disableEmailAsIdentity", False)
              and user["spec"]["type"] == "HUMAN" and user["spec"].get("email")):
            # Without an explicit match, Octelium also authenticates via spec.email.
            # Count these users before changing the claim or disabling fallback.
            require(isinstance(user["spec"]["email"], str), "invalid fallback email identifier")
            bindings.append((user["metadata"]["name"], user["spec"]["email"]))
    require(provider is not None or not bindings, "Entra mappings exist without their provider")
    require(len({identifier.lower() for _, identifier in bindings}) == len(bindings),
            "duplicate Entra user identifiers")
    if claim == "preferred_username" and bindings:
        require(bool(object_id) and len(bindings) == 1 and bindings[0][0] == user_name,
                "legacy Entra mappings require explicit migration of the sole mapped HUMAN user")
        require(bindings[0][1].lower() in (email.lower(), object_id),
                "--admin-email must match the existing legacy Entra identifier")
    for name, identifier in bindings:
        require(claim != "oid" or is_uuid(identifier), "oid provider has a non-UUID user binding")
        if name == user_name and is_uuid(identifier):
            require(identifier.lower() == object_id, "refusing to replace an existing immutable user binding")
        if name != user_name:
            require(identifier.lower() != object_id, "object ID already belongs to another Octelium user")
    if user_name:
        require(not owner or owner["spec"]["type"] == "HUMAN", "selected administrator is not HUMAN")
        owner = owner or {"metadata": {"name": user_name}, "spec": {
            "type": "HUMAN", "email": email, "authorization": {"policies": ["allow-all"]}}}
        authentication = owner["spec"].setdefault("authentication", {})
        authentication["identities"] = [identity for identity in authentication.get("identities", [])
                                        if identity.get("identityProvider") != idp_name] + [
            {"identityProvider": idp_name, "identifier": object_id}]
        (path / "user.json").write_text(json.dumps({"kind": "User", "metadata": owner["metadata"],
                                                   "spec": owner["spec"]}))
    provider = provider or {"metadata": {"name": idp_name, "displayName": "Microsoft Entra"},
                            "spec": {"displayName": display_name, "oidc": {}}}
    provider["spec"]["disableEmailAsIdentity"] = True
    provider["spec"]["oidc"].update({"issuerURL": issuer, "clientID": client_id,
        "clientSecret": {"fromSecret": secret_name}, "identifierClaim": "oid",
        "scopes": ["openid", "email", "profile"]})
    (path / "idp.json").write_text(json.dumps({"kind": "IdentityProvider", "metadata": provider["metadata"],
                                             "spec": provider["spec"]}))
    if claim == "preferred_username" and bindings:
        (path / "user-first").touch()
    print("Validated complete Entra inventory and immutable user bindings")
except (KeyError, TypeError, ValueError, subprocess.SubprocessError):
    raise SystemExit("error: invalid or unavailable Octelium identity inventory") from None
PYTHON

if "$dry_run"; then
  echo "Dry run: no client-secret read or live changes. Retain an independent operator session for execution."
  exit 0
fi

client_secret="$(read_parameter "$client_secret_parameter")"
if [[ -z "$client_secret" || "$client_secret" == "REPLACE_ME" ]]; then
  echo "error: SSM returned an empty or placeholder client secret" >&2
  exit 1
fi
if octeliumctl get secret "$secret_name" --domain "$domain" >/dev/null 2>&1; then
  printf '%s' "$client_secret" | octeliumctl update secret "$secret_name" --domain "$domain" --file - >/dev/null
else
  printf '%s' "$client_secret" | octeliumctl create secret "$secret_name" --domain "$domain" --file - >/dev/null
fi

# Migrate the existing mapping before switching claims; never leave the new
# oid provider pointing at a legacy email after a failed User apply.
if [[ -f "$identity_dir/user-first" ]]; then
  apply_identity_resources "$identity_dir/user.json"
fi
apply_identity_resources "$identity_dir/idp.json"
if [[ -f "$identity_dir/user.json" && ! -f "$identity_dir/user-first" ]]; then
  apply_identity_resources "$identity_dir/user.json"
fi

echo "Configured Octelium Entra oid matching; verify fresh owner login before reusing an email."
