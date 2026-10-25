#!/usr/bin/env bash
set -euo pipefail

# GitHub checksum metadata can exceed OpenTofu's ten-second default.
if [[ "${GITHUB_ACTIONS:-}" == true ]]; then
  export TF_REGISTRY_CLIENT_TIMEOUT=60
fi
case "${1:-}" in
  "") bash scripts/ci/nix-checks.sh ;;
  --offline-verified) [[ $# == 1 ]] ;;
  *) echo 'Usage: static-checks.sh [--offline-verified]' >&2; exit 2 ;;
esac
python3 -I scripts/ci/nix-cache-signature-test.py
python3 -I scripts/ci/openclaw-retirement-test.py
python3 -I scripts/ci/openclaw-retirement-status-test.py
python3 -I scripts/ci/openclaw-enterprise-operations-test.py
python3 -I scripts/ci/openclaw-enterprise-resume-test.py
python3 -I scripts/ci/openclaw-enterprise-journal-operator-test.py
python3 -I scripts/ci/openclaw-enterprise-operator-image-test.py
python3 -I scripts/ci/openclaw-enterprise-full-sync-test.py
python3 -I scripts/ci/openclaw-enterprise-foundation-test.py
python3 -I scripts/ci/openclaw-enterprise-postgres-test.py
python3 -I scripts/ci/openclaw-enterprise-chart-hooks-test.py
python3 -I scripts/ci/openclaw-enterprise-lifecycle-test.py
python3 -I scripts/ci/openclaw-enterprise-startup-test.py
python3 -I scripts/ci/openclaw-enterprise-bind-installation-test.py
python3 -I scripts/ci/openclaw-enterprise-quiesce-test.py
python3 -I scripts/ci/openclaw-enterprise-test.py
python3 -I scripts/ci/openclaw-enterprise-active-test.py
python3 -I scripts/ci/openclaw-enterprise-recovery-test.py
python3 -I scripts/ci/openclaw-enterprise-access-test.py
node --test scripts/ci/renovate-config-test.js
node --test scripts/ci/renovate-cache-corruption-drill-test.mjs
python3 -I scripts/ci/renovate-cache-capacity-drill-test.py
python3 -I scripts/ci/renovate-acceptance-app-test.py
node --test scripts/ci/renovate-acceptance-observer-test.js
node --test scripts/ci/renovate-acceptance-schedule-collector-test.js
node --test scripts/ci/renovate-acceptance-inventory-test.js
python3 -I scripts/ci/renovate-acceptance-review-test.py
python3 -I scripts/ci/renovate-acceptance-schedule-test.py
python3 -I scripts/ci/renovate-acceptance-schedule-assemble-test.py
node --test scripts/ci/renovate-acceptance-report-test.js
node --test scripts/ci/renovate-acceptance-pr-proof-test.js
node --test scripts/ci/renovate-acceptance-source-review-test.js
python3 -I scripts/ci/renovate-acceptance-secret-boundary-test.py
python3 -I scripts/ci/renovate-acceptance-final-report-test.py
python3 -I scripts/ci/renovate-acceptance-ledger-cleanup-test.py
python3 -I scripts/ci/tailnet-dns-test.py
python3 -I scripts/ci/platform-maintenance-test.py
python3 -I scripts/ci/platform-maintenance-stage-test.py
python3 -I scripts/ci/platform-maintenance-credentials-test.py
python3 -I scripts/ci/network-policy-canary-node-test.py
python3 -I scripts/ci/network-policy-enforcement-test.py
python3 -I scripts/ci/network-policy-qualification-test.py
python3 -I scripts/ci/network-policy-ownership-test.py
python3 -I scripts/ci/network-policy-cleanup-test.py
python3 -I scripts/ci/envoy-gateway-prerequisite-test.py

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091 # Shared helper is linted separately.
source "${script_dir}/terragrunt-filter-base.sh"

terragrunt_generate_stack
python3 -I scripts/ci/openclaw-enterprise-registration-test.py
python3 -I scripts/ci/envoy-gateway-registration-test.py
python3 -I scripts/ci/network-policy-registration-test.py

echo "::group::Operator OpenTofu validation"
rg -Fq 'sid       = "DenyTemporarySessionCredentials"' IaC/terragrunt-catalog/modules/aws-github-actions-role-policy/main.tf
rg -Fq 'variable = "aws:TokenIssueTime"' IaC/terragrunt-catalog/modules/aws-github-actions-role-policy/main.tf
rg -Fq 'variable = "aws:ViaAWSService"' IaC/terragrunt-catalog/modules/aws-github-actions-role-policy/main.tf
for parameter in \
  '/homelab/external-secrets/aws-ssm/access-key-id' \
  '/homelab/external-secrets/aws-ssm/secret-access-key' \
  '/homelab/github-actions-runner/registration-token' \
  '/homelab/deluge/vpn/wireguard-addresses' \
  '/homelab/deluge/vpn/wireguard-endpoint-ip' \
  '/homelab/deluge/vpn/wireguard-endpoint-port' \
  '/homelab/deluge/vpn/wireguard-preshared-key' \
  '/homelab/deluge/vpn/wireguard-private-key' \
  '/homelab/deluge/vpn/wireguard-public-key' \
  '/homelab/octelium/cloudflare-zone-settings-token' \
  '/homelab/argocd-image-updater/github-app/id' \
  '/homelab/argocd-image-updater/github-app/installation-id' \
  '/homelab/argocd-image-updater/github-app/private-key' \
  '/homelab/fleet/google-oauth' \
  '/homelab/entra/google-workspace-federation-metadata'; do
  parameter_block="$(
    awk -v target="\"${parameter}\" = {" '
      index($0, target) { found = 1 }
      found { print }
      found && /^    }$/ { exit }
    ' IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl
  )"
  rg -Fq 'reader_access = false' <<<"$parameter_block"
done
(
  cd IaC/homelab/us-west-2/operator/github-actions-role-policy
  terragrunt --log-disable init -backend=false -no-color
  terragrunt --log-disable run --no-auto-init -- validate -no-color
  terragrunt --log-disable run --no-auto-init -- test -no-color
)
(
  cd IaC/homelab/us-west-2/operator/azuread-ci-identities
  terragrunt --log-disable init -backend=false -no-color
  terragrunt --log-disable run --no-auto-init -- validate -no-color
)
rg -Fq 'data "msgraph_resource" "domain"' IaC/terragrunt-catalog/modules/entra-domain-verification/main.tf
rg -Fq 'resource "msgraph_resource" "domain"' IaC/terragrunt-catalog/modules/entra-domain-verification/main.tf && exit 1
verify_action_block="$(sed -n '/^resource "msgraph_resource_action" "verify" {/,/^}$/p' IaC/terragrunt-catalog/modules/entra-domain-verification/main.tf)"
rg -Fq 'method       = "POST"' <<<"$verify_action_block"
if rg -q '^[[:space:]]*(body[[:space:]]*=|forceTakeover[[:space:]]*=)' <<<"$verify_action_block"; then
  echo "The standard Entra domain verification action must use a bodyless POST." >&2
  exit 1
fi
rg -Fq 'local.user_principal_domain == var.required_verified_domain' IaC/terragrunt-catalog/modules/entra-verified-family-user/main.tf
rg -Fq 'verify_domain = true' IaC/terragrunt-catalog/units/operator/entra-stuhlmuller-domain/terragrunt.hcl
rg -Fq 'required_verified_domain = "stuhlmuller.net"' IaC/terragrunt-catalog/units/operator/entra-stuhlmuller-pilot-user/terragrunt.hcl
rg -Fq 'user_principal_name      = "rodman.mac@stuhlmuller.net"' IaC/terragrunt-catalog/units/operator/entra-stuhlmuller-pilot-user/terragrunt.hcl
rg -Fq 'homelab-emergency-admin' IaC/terragrunt-catalog/modules/entra-emergency-global-admin/main.tf
rg -Fq '62e90394-69f5-4237-9190-012177145e10' IaC/terragrunt-catalog/modules/entra-emergency-global-admin/main.tf
rg -Fq 'azuread_directory_role_assignment' IaC/terragrunt-catalog/modules/entra-emergency-global-admin/main.tf
rg -Fq 'disable_password_expiration = true' IaC/terragrunt-catalog/modules/entra-emergency-global-admin/main.tf
gate_unit="IaC/homelab/us-west-2/operator/entra-emergency-global-admin"
gate_config="$gate_unit/terragrunt.hcl"
if rg -Fq 'feature "emergency_global_admin"' "$gate_config"; then
  echo "The emergency administrator activation must remain source-controlled." >&2
  exit 1
fi
gate_enabled="$(rg -o '^[[:space:]]*emergency_global_admin_enabled[[:space:]]*=[[:space:]]*(true|false)[[:space:]]*$' "$gate_config" | sed -E 's/.*=[[:space:]]*//; s/[[:space:]]*$//')"
case "$gate_enabled" in
  true|false) ;;
  *)
    echo "The emergency administrator activation literal is invalid." >&2
    exit 1
    ;;
esac
rg -Fq 'if      = !local.emergency_global_admin_enabled' "$gate_config"
rg -Fq 'no_run  = true' "$gate_config"
rg -Fq 'actions = ["apply", "destroy"]' "$gate_config"
(
  terragrunt --working-dir "$gate_unit" --log-disable render --json --write=false --no-color \
    | jq -e --argjson enabled "$gate_enabled" '
        .locals.emergency_global_admin_enabled == $enabled and
        .exclude.if == (if $enabled then false else true end) and
        .exclude.actions == ["apply", "destroy"]
      ' >/dev/null
  if [ "$gate_enabled" = false ]; then
    gate_dir="$(mktemp -d)"
    trap 'rm -rf "$gate_dir"' EXIT
    gate_tofu="$gate_dir/tofu-blocker"
    cat > "$gate_tofu" <<'EOF'
#!/bin/sh
case "$1" in
  -version|version)
    echo "OpenTofu v1.10.0"
    exit 0
    ;;
  *)
    exit 99
    ;;
esac
EOF
    chmod 700 "$gate_tofu"
    terragrunt --working-dir "$gate_unit" --log-disable apply --tf-path "$gate_tofu" \
      -auto-approve -no-color
  fi
)
python3 -I scripts/ci/entra-emergency-global-admin-plan-test.py
rg -Fq 'from = msgraph_update_resource.mail' IaC/terragrunt-catalog/modules/entra-owner-mail/main.tf
rg -Fq 'destroy = false' IaC/terragrunt-catalog/modules/entra-owner-mail/main.tf
for operator_unit in entra-stuhlmuller-domain entra-stuhlmuller-pilot-user entra-emergency-global-admin entra-owner-mail entra-google-workspace-federation; do
  (
    cd "IaC/homelab/us-west-2/operator/${operator_unit}"
    terragrunt --log-disable init -backend=false -no-color
    terragrunt --log-disable run --no-auto-init -- validate -no-color
  )
done
python3 -I scripts/ci/entra-google-workspace-federation-metadata-test.py
python3 -I scripts/ci/entra-owner-conversion-test.py
python3 -I scripts/ci/azuread-saml-uuid-validation-test.py
echo "::endgroup::"

echo "::group::Etcd offsite bucket offline guards"
(
  cd IaC/homelab/us-west-2/operator/etcd-backup-storage
  terragrunt --log-disable init -backend=false -no-color
  terragrunt --log-disable run --no-auto-init -- validate -no-color
  terragrunt --log-disable run --no-auto-init -- test -no-color
)
echo "::endgroup::"

echo "::group::Octelium bootstrap node containment"
(
  cd IaC/homelab/us-west-2/shared/kubernetes-node-labels
  terragrunt --log-disable init -backend=false -no-color
  terragrunt --log-disable run --no-auto-init -- test -no-color
)
(
  # Run the actual prerequisites against mocked API responses, without cluster access.
  bootstrap_label_checks="$(awk '/^require_label\(\)/,/^}/; /^require_label /' scripts/octelium-cluster-bootstrap.sh)"
  check_bootstrap_labels() (
    node_two_state="$1"
    # Used by the prerequisites evaluated below.
    # shellcheck disable=SC2034
    kubectl_cmd=(kubectl)
    # shellcheck disable=SC2329
    kubectl() {
      case "$4" in
        octelium.com/node-mode-dataplane) printf '%s\n' node/zimaboard-0 ;;
        octelium.com/node-mode-controlplane) printf '%s\n' node/zimaboard-1 ;;
        '!octelium.com/node-mode-dataplane')
          case "$node_two_state" in
            absent) printf '%s\n' node/zimaboard-2 ;;
            present | missing) return 0 ;;
            error) return 1 ;;
          esac
          ;;
        *) return 1 ;;
      esac
    }
    eval "$bootstrap_label_checks"
  )
  check_bootstrap_labels absent
  for node_two_state in present missing error; do
    if check_bootstrap_labels "$node_two_state"; then
      echo "Octelium bootstrap accepted unsafe node state: ${node_two_state}" >&2
      exit 1
    fi
  done
)
echo "::endgroup::"

echo "::group::Harbor chart, credentials and cold bootstrap"
bash scripts/ci/harbor-check.sh
echo "::endgroup::"

echo "::group::Langfuse migration startup allowance"
bash scripts/ci/langfuse-startup-check.sh
echo "::endgroup::"

echo "::group::Secret scan"
bash scripts/ci/secret-scan.sh --self-check
bash scripts/ci/secret-scan.sh
echo "::endgroup::"

echo "::group::Checkov"
if command -v checkov >/dev/null 2>&1; then
  (
    checkov_output="$(mktemp "${TMPDIR:-/tmp}/homelab-checkov.XXXXXX")"
    trap 'rm -f "$checkov_output"' EXIT

    # These four exact findings are public PVC/Secret names in the pinned
    # OpenClaw profile and a generated NetworkPolicy name paired with its
    # reviewed spec hash. Reject any wider secrets-scan baseline or changed
    # finding fingerprint.
    jq -e '.failed_checks == [
      {"file":"/clusters/homelab/apps/openclaw-enterprise/installation.yaml","findings":[
        {"resource":"b34905fb692e6b1b108a7dfa4d2c3b2b5ef683cd","check_ids":["CKV_SECRET_6"]}
      ]},
      {"file":"/clusters/homelab/apps/openclaw-enterprise/profile-input.json","findings":[
        {"resource":"4c854688a8888c241dae89b2c0036f1014dd193b","check_ids":["CKV_SECRET_6"]},
        {"resource":"b34905fb692e6b1b108a7dfa4d2c3b2b5ef683cd","check_ids":["CKV_SECRET_6"]}
      ]},
      {"file":"/docs/evidence/openclaw-enterprise-policy-review.json","findings":[
        {"resource":"900d958341a77ac728b81edab1190560c72fd655","check_ids":["CKV_SECRET_6"]}
      ]}
    ]' .checkov.baseline >/dev/null || {
      echo "Checkov secrets baseline differs from the four reviewed public names." >&2
      exit 1
    }

    run_checkov() {
      local framework="$1"
      local directory="$2"
      local -a extra_args=()
      if [[ "$framework" == secrets ]]; then
        extra_args+=(--baseline .checkov.baseline)
      fi

      if ! checkov --config-file .checkov.yaml --framework "$framework" --directory "$directory" "${extra_args[@]}" >"$checkov_output" 2>&1; then
        echo "Checkov ${framework} scan failed; detailed output was withheld to prevent publishing a detected secret." >&2
        return 1
      fi
    }

    run_checkov terraform IaC/terragrunt-catalog/modules
    run_checkov kubernetes clusters
    run_checkov secrets .
  )
elif [[ "${CI:-}" == "true" ]]; then
  echo "checkov is required in CI but was not found in PATH" >&2
  exit 1
else
  echo "::warning::checkov is not available in this local shell; GitHub Actions still enforces Checkov on Linux."
fi
echo "::endgroup::"

echo "::group::Whitespace"
git diff --check
echo "::endgroup::"
