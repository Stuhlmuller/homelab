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

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/terragrunt-filter-base.sh"

terragrunt_generate_stack

echo "::group::Operator OpenTofu validation"
rg -Fq 'sid       = "DenyTemporarySessionCredentials"' IaC/modules/aws-github-actions-role-policy/main.tf
rg -Fq 'variable = "aws:TokenIssueTime"' IaC/modules/aws-github-actions-role-policy/main.tf
rg -Fq 'variable = "aws:ViaAWSService"' IaC/modules/aws-github-actions-role-policy/main.tf
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
    ' IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl
  )"
  rg -Fq 'reader_access = false' <<<"$parameter_block"
done
(
  cd IaC/operator/github-actions-role-policy
  terragrunt --log-disable init -backend=false -no-color
  terragrunt --log-disable run --no-auto-init -- validate -no-color
  terragrunt --log-disable run --no-auto-init -- test -no-color
)
(
  cd IaC/operator/azuread-ci-identities
  terragrunt --log-disable init -backend=false -no-color
  terragrunt --log-disable run --no-auto-init -- validate -no-color
)
rg -Fq 'data "msgraph_resource" "domain"' IaC/modules/entra-domain-verification/main.tf
rg -Fq 'resource "msgraph_resource" "domain"' IaC/modules/entra-domain-verification/main.tf && exit 1
verify_action_block="$(sed -n '/^resource "msgraph_resource_action" "verify" {/,/^}$/p' IaC/modules/entra-domain-verification/main.tf)"
rg -Fq 'method       = "POST"' <<<"$verify_action_block"
if rg -q '^[[:space:]]*(body[[:space:]]*=|forceTakeover[[:space:]]*=)' <<<"$verify_action_block"; then
  echo "The standard Entra domain verification action must use a bodyless POST." >&2
  exit 1
fi
rg -Fq 'local.user_principal_domain == var.required_verified_domain' IaC/modules/entra-verified-family-user/main.tf
rg -Fq 'verify_domain = true' IaC/.catalog/units/operator/entra-stuhlmuller-domain/terragrunt.hcl
rg -Fq 'required_verified_domain = "stuhlmuller.net"' IaC/.catalog/units/operator/entra-stuhlmuller-pilot-user/terragrunt.hcl
for operator_unit in entra-stuhlmuller-domain entra-stuhlmuller-pilot-user entra-owner-mail entra-google-workspace-federation; do
  (
    cd "IaC/operator/${operator_unit}"
    terragrunt --log-disable init -backend=false -no-color
    terragrunt --log-disable run --no-auto-init -- validate -no-color
    if [[ "$operator_unit" == entra-owner-mail ]]; then
      terragrunt --log-disable run --no-auto-init -- test -no-color
    fi
  )
done
python3 -I scripts/ci/entra-google-workspace-federation-metadata-test.py
echo "::endgroup::"

echo "::group::Etcd offsite bucket offline guards"
(
  cd IaC/operator/etcd-backup-storage
  terragrunt --log-disable init -backend=false -no-color
  terragrunt --log-disable run --no-auto-init -- validate -no-color
  terragrunt --log-disable run --no-auto-init -- test -no-color
)
echo "::endgroup::"

echo "::group::Octelium bootstrap node containment"
(
  cd IaC/live/kubernetes-node-labels
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

    run_checkov() {
      local framework="$1"
      local directory="$2"

      if ! checkov --config-file .checkov.yaml --framework "$framework" --directory "$directory" >"$checkov_output" 2>&1; then
        echo "Checkov ${framework} scan failed; detailed output was withheld to prevent publishing a detected secret." >&2
        return 1
      fi
    }

    run_checkov terraform IaC/modules
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
