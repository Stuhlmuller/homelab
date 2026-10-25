#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(pwd)"
source "${script_dir}/terragrunt-filter-base.sh"

cleanup_dirs=()

cleanup_temp_dirs() {
  local temp_dir

  for temp_dir in "${cleanup_dirs[@]}"; do
    if [[ -d "$temp_dir" ]]; then
      rm -rf "$temp_dir"
    fi
  done

  find IaC/homelab/us-west-2/shared/aws-ssm-parameters IaC/homelab/us-west-2/shared/kubernetes-node-labels \
    \( -name plan.out -o -name plan.json \) -type f -delete 2>/dev/null || true
}

trap cleanup_temp_dirs EXIT

azuread_credentials_available() {
  [[ -n "${ARM_CLIENT_ID:-}" && -n "${ARM_TENANT_ID:-}" ]] || return 1
  case "${ARM_USE_OIDC:-false}" in
    true)
      [[ -n "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" && -n "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]]
      ;;
    false) [[ -n "${ARM_CLIENT_SECRET:-}" ]] ;;
    *) return 1 ;;
  esac
}

verify_current_main_commit() {
  bash "${script_dir}/terragrunt-current-main.sh"
}

destroy_deleted_terragrunt_units() {
  local deleted_units=()
  local snapshot_dir
  local unit_dir
  local snapshot_unit_dir
  local state_list_file

  while IFS= read -r unit_dir; do
    deleted_units+=("$unit_dir")
  done < <(terragrunt_deleted_unit_paths)

  if ((${#deleted_units[@]} == 0)); then
    echo "No deleted Terragrunt units require destroy handling."
    return 0
  fi

  for unit_dir in "${deleted_units[@]}"; do
    snapshot_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/terragrunt-deleted-apply.XXXXXX")"
    cleanup_dirs+=("$snapshot_dir")
    terragrunt_create_deleted_unit_destroy_stack "$snapshot_dir" "$unit_dir"
    snapshot_unit_dir="${snapshot_dir}/${unit_dir}"
    state_list_file="${snapshot_unit_dir}/state-resources.txt"

    if [[ ! -f "${snapshot_unit_dir}/terragrunt.hcl" ]]; then
      echo "Deleted Terragrunt unit ${unit_dir} fake stack was not generated." >&2
      exit 1
    fi

    echo "::group::Deleted Terragrunt unit state destroy: ${unit_dir}"
    (
      cd "$snapshot_unit_dir"
      terragrunt --log-disable init -no-color
      if ! terragrunt --log-disable state list >"$state_list_file"; then
        echo "Unable to list state for deleted Terragrunt unit ${unit_dir}; inspect the backend or credentials before applying." >&2
        exit 1
      fi
      if [[ -s "$state_list_file" ]]; then
        echo "Resources in deleted Terragrunt unit state:"
        cat "$state_list_file"
        terragrunt plan -destroy -refresh=false -out plan.out -no-color >/dev/null
        terragrunt --log-disable show -json plan.out >plan.json
        conftest test --policy "${snapshot_dir}/policy" --output github plan.json
        verify_current_main_commit
        terragrunt apply -no-color plan.out
      else
        echo "Deleted Terragrunt unit ${unit_dir} has no resources in remote state."
      fi
    )
    echo "::endgroup::"
  done
}

adopt_existing_ssm_parameters() {
  local parameter_region="us-west-2"
  local state_resources
  local parameter_name
  local resource_address
  local existing_name
  local parameter_names=(
    "/homelab/github-actions-runner/registration-token"
    "/homelab/cordium/agent-auth-token"
    "/homelab/cordium-runners/github-app-private-key"
    "/homelab/cordium-runners/auth-token"
  )

  terragrunt init -no-color
  state_resources="$(terragrunt state list -no-color 2>/dev/null || true)"

  for parameter_name in "${parameter_names[@]}"; do
    resource_address="aws_ssm_parameter.this[\"${parameter_name}\"]"

    if grep -Fxq "$resource_address" <<<"$state_resources"; then
      echo "SSM parameter ${parameter_name} is already managed in OpenTofu state."
      continue
    fi

    existing_name="$(
      aws ssm describe-parameters \
        --region "$parameter_region" \
        --parameter-filters "Key=Name,Option=Equals,Values=${parameter_name}" \
        --query "Parameters[0].Name" \
        --output text 2>/dev/null || true
    )"

    if [[ "$existing_name" == "$parameter_name" ]]; then
      echo "Adopting existing SSM parameter ${parameter_name} into OpenTofu state."
      verify_current_main_commit
      terragrunt import -no-color "$resource_address" "$parameter_name"
    else
      echo "SSM parameter ${parameter_name} is absent; OpenTofu will create the placeholder."
    fi
  done
}

plan_and_apply_ssm_prerequisites() {
  echo "::group::AWS SSM parameter declaration plan and apply"
  (
    cd IaC/homelab/us-west-2/shared/aws-ssm-parameters
    rm -f plan.out plan.json
    adopt_existing_ssm_parameters
    terragrunt plan -out plan.out -no-color
    terragrunt --log-disable show -json plan.out >plan.json
    conftest test --policy "${repo_root}/policy" --output github plan.json
    verify_current_main_commit
    terragrunt apply -no-color plan.out
  )
  echo "::endgroup::"
}

plan_and_apply_langfuse_prerequisites() {
  local langfuse_plan_dir

  plan_and_apply_ssm_prerequisites

  echo "::group::Langfuse blob storage plan and apply"
  # Application filters omit this sibling AWS unit. Keep its private saved-plan
  # policy gate and apply ahead of Langfuse registration, including targeted runs.
  langfuse_plan_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/homelab-langfuse-plan.XXXXXX")"
  cleanup_dirs+=("$langfuse_plan_dir")
  (
    cd IaC/homelab/us-west-2/apps/langfuse/blob-storage
    terragrunt init -no-color
    terragrunt plan -out "$langfuse_plan_dir/plan.out" -no-color
    terragrunt --log-disable show -json "$langfuse_plan_dir/plan.out" >"$langfuse_plan_dir/plan.json"
    conftest test --policy "${repo_root}/policy" --output github "$langfuse_plan_dir/plan.json"
    verify_current_main_commit
    terragrunt apply -no-color "$langfuse_plan_dir/plan.out"
  )
  echo "::endgroup::"
}

plan_and_apply_application_backup_storage() {
  local plan_dir

  plan_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/homelab-openclaw-archive-plan.XXXXXX")"
  cleanup_dirs+=("$plan_dir")
  (
    cd IaC/homelab/us-west-2/operator/application-backup-storage
    terragrunt init -no-color
    terragrunt plan -out "$plan_dir/plan.out" -no-color
    terragrunt --log-disable show -json "$plan_dir/plan.out" >"$plan_dir/plan.json"
    conftest test --policy "${repo_root}/policy" --output github "$plan_dir/plan.json"
    verify_current_main_commit
    terragrunt apply -no-color "$plan_dir/plan.out"
  )
}

plan_and_apply_argocd_apps() {
  local filter
  local plan_dir
  local plan_json_files=()
  local live_apps
  local app_unit
  local app

  plan_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/terragrunt-argocd-apps.XXXXXX")"
  cleanup_dirs+=("$plan_dir")
  filter="$(cd IaC/homelab/us-west-2/apps && terragrunt_argocd_app_filter)"
  if [[ "$existing_argocd_only" == true ]]; then
    live_apps="$(kubectl -n argocd get applications -o json | jq -r '.items[].metadata.name')"
    [[ -n "$live_apps" ]] || { echo "No live Argo CD Applications found; refusing existing-only apply." >&2; return 1; }
    for app_unit in IaC/homelab/us-west-2/apps/*/argocd/terragrunt.hcl; do
      app="${app_unit%/argocd/terragrunt.hcl}"
      app="${app##*/}"
      if ! grep -Fxq "$app" <<<"$live_apps"; then
        filter+=" | !${app}/argocd"
        echo "::notice::Skipping absent Argo CD Application ${app}; use a targeted apply after its gates."
      fi
    done
  fi

  (
    cd IaC/homelab/us-west-2/apps
    terragrunt run --all --filter "$filter" --non-interactive --parallelism 1 --source-update \
      --out-dir "$plan_dir" --json-out-dir "$plan_dir" -- plan -no-color
  )

  while IFS= read -r plan_json_file; do
    plan_json_files+=("$plan_json_file")
  done < <(find "$plan_dir" -name tfplan.json -type f -print | sort)

  if ((${#plan_json_files[@]} == 0)); then
    echo "No affected Argo CD Application registration units require apply."
    return
  fi

  conftest test --policy policy --output github "${plan_json_files[@]}"
  if [[ "$existing_argocd_only" == true ]] &&
    jq -s -e 'any(.[]; any(.resource_changes[]?; .type == "kubernetes_manifest" and (.change.actions | index("create"))))' \
      "${plan_json_files[@]}" >/dev/null; then
    echo "Existing-only Argo CD apply would create an Application; use a targeted apply after its gates." >&2
    return 1
  fi
  if jq -s -e 'any(.[]; any(.resource_changes[]?; .type == "kubernetes_manifest" and (.change.actions | index("delete"))))' \
    "${plan_json_files[@]}" >/dev/null; then
    echo "Argo CD Application replacement or deletion requires explicit state repair or deleted-unit handling." >&2
    return 1
  fi

  (
    cd IaC/homelab/us-west-2/apps
    verify_current_main_commit
    terragrunt run --all --filter "$filter" --non-interactive --parallelism 1 \
      --out-dir "$plan_dir" -- apply -no-color
  )
}

prepare_terragrunt_filter_base
existing_argocd_only="${TERRAGRUNT_EXISTING_ARGOCD_ONLY:-false}"
case "$existing_argocd_only" in
  true)
    [[ -z "${TERRAGRUNT_ARGOCD_APP:-}" ]] || { echo "Existing-only mode cannot target one Argo CD Application." >&2; exit 2; }
    ;;
  false) ;;
  *) echo "TERRAGRUNT_EXISTING_ARGOCD_ONLY must be true or false." >&2; exit 2 ;;
esac
backup_storage_scope="${TERRAGRUNT_APPLICATION_BACKUP_STORAGE:-false}"
case "$backup_storage_scope" in
  true)
    [[ -z "${TERRAGRUNT_ARGOCD_APP:-}" && "${TERRAGRUNT_REPAIR_ARGOCD_APP_STATE:-false}" == false && "$existing_argocd_only" == false ]] || {
      echo "The backup-storage scope cannot be combined with an Argo CD target, existing-only mode or state repair." >&2
      exit 2
    }
    ;;
  false) ;;
  *) echo "Invalid backup-storage scope." >&2; exit 2 ;;
esac
terragrunt_generate_stack

if [[ "$backup_storage_scope" == true ]]; then
  echo "::group::OpenClaw legacy offsite bucket plan and apply"
  plan_and_apply_application_backup_storage
  echo "::endgroup::"
  exit 0
fi

repair_argocd_app_state_unit="$(
  cd IaC/homelab/us-west-2/apps
  terragrunt_argocd_app_state_repair_unit
)"
if [[ "${TERRAGRUNT_ARGOCD_APP:-}" == "langfuse" || "${TERRAGRUNT_ARGOCD_APP:-}" == "fleet" || "${TERRAGRUNT_ARGOCD_APP:-}" == "mastodon" || "${TERRAGRUNT_ARGOCD_APP:-}" == "traefik" ]]; then
  # This path skips bootstrap/platform reconciliation. Fail before any state
  # repair, import or apply if those existing prerequisites are not ready.
  (cd IaC/homelab/us-west-2/apps && terragrunt_argocd_app_filter) >/dev/null
  echo "::group::Targeted Argo CD apply prerequisites"
  kubectl -n argocd get appproject homelab -o json | jq -e --arg app "$TERRAGRUNT_ARGOCD_APP" '
    .spec |
    (.sourceRepos | index("https://github.com/Stuhlmuller/homelab.git") != null) and
    ($app != "langfuse" or (.sourceRepos | index("ghcr.io/langfuse/langfuse-k8s/charts") != null)) and
    ($app != "traefik" or (.sourceRepos | index("https://bjw-s-labs.github.io/helm-charts") != null)) and
    any(.destinations[]; .namespace == $app and .server == "https://kubernetes.default.svc") and
    any(.clusterResourceWhitelist[]; .group == "" and .kind == "Namespace") and
    ($app != "mastodon" or (
      any(.clusterResourceWhitelist[]; .group == "" and .kind == "PersistentVolume") and
      any(.clusterResourceWhitelist[]; .group == "storage.k8s.io" and .kind == "StorageClass")
    ))
  ' >/dev/null
  prerequisite_apps=(external-secrets cert-manager istio platform-storage)
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "traefik" ]]; then
    prerequisite_apps=(cert-manager istio tailscale)
  elif [[ "$TERRAGRUNT_ARGOCD_APP" == "mastodon" ]]; then
    prerequisite_apps+=(octelium-public)
  elif [[ "$TERRAGRUNT_ARGOCD_APP" == "fleet" ]]; then
    prerequisite_apps+=(traefik)
  fi
  kubectl -n argocd get applications "${prerequisite_apps[@]}" -o json | jq -e \
    --argjson expected "${#prerequisite_apps[@]}" '
    (.items | length == $expected) and
    all(.items[]; .status.sync.status == "Synced" and .status.health.status == "Healthy")
  ' >/dev/null
  prerequisite_crds=(
    crd/externalsecrets.external-secrets.io crd/clustersecretstores.external-secrets.io
    crd/authorizationpolicies.security.istio.io crd/virtualservices.networking.istio.io
  )
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "traefik" ]]; then
    prerequisite_crds=(
      crd/certificates.cert-manager.io crd/clusterissuers.cert-manager.io
      crd/authorizationpolicies.security.istio.io
    )
  fi
  kubectl wait --for=condition=Established --timeout=0s "${prerequisite_crds[@]}"
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "traefik" ]]; then
    kubectl wait --for=condition=Ready --timeout=0s clusterissuer/letsencrypt-cloudflare
  else
    kubectl wait --for=condition=Ready --timeout=0s clustersecretstore/aws-ssm
    if [[ "$TERRAGRUNT_ARGOCD_APP" == "fleet" || "$TERRAGRUNT_ARGOCD_APP" == "mastodon" ]]; then
      kubectl get clustersecretstore aws-ssm -o json | jq -e --arg app "$TERRAGRUNT_ARGOCD_APP" '
        any(.spec.conditions[]?.namespaces[]?; . == $app)
      ' >/dev/null
    fi
    kubectl get storageclass nfs-default -o name >/dev/null
  fi
  echo "::endgroup::"
fi

if [[ -n "$repair_argocd_app_state_unit" ]]; then
  echo "::group::Targeted Argo CD Application state repair"
  (
    cd "IaC/homelab/us-west-2/apps/${repair_argocd_app_state_unit}"
    terragrunt init -no-color
    verify_current_main_commit
    if ! repair_output="$(terragrunt run -- untaint -no-color kubernetes_manifest.this 2>&1)"; then
      printf '%s\n' "$repair_output"
      if ! grep -Eiq 'not tainted|no such instance|does not exist' <<<"$repair_output"; then
        echo "Argo CD Application state repair failed." >&2
        exit 1
      fi
      echo "Argo CD Application state was already clean; continuing."
    else
      printf '%s\n' "$repair_output"
    fi
  )
  echo "::endgroup::"
fi

if [[ -n "${TERRAGRUNT_ARGOCD_APP:-}" ]]; then
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "langfuse" ]]; then
    plan_and_apply_langfuse_prerequisites
  elif [[ "$TERRAGRUNT_ARGOCD_APP" == "fleet" || "$TERRAGRUNT_ARGOCD_APP" == "mastodon" ]]; then
    plan_and_apply_ssm_prerequisites
  fi
  echo "::group::Targeted Argo CD Application registration apply"
  plan_and_apply_argocd_apps
  echo "::endgroup::"
  exit 0
fi

if ! azuread_credentials_available && terragrunt_azuread_stack_changed; then
  echo "AzureAD credentials are required because IaC/homelab/us-west-2/apps changed or the apply diff could not be determined." >&2
  echo "Set AZUREAD_CLIENT_ID and AZUREAD_TENANT_ID on homelab-production; the job requires GitHub OIDC token access." >&2
  exit 1
fi

destroy_deleted_terragrunt_units

echo "::group::OpenClaw legacy offsite bucket plan and apply"
plan_and_apply_application_backup_storage
echo "::endgroup::"

echo "::group::Argo CD bootstrap apply"
(
  cd IaC/homelab/us-west-2/bootstrap/argocd
  terragrunt init -no-color
  if ! terragrunt state list -no-color 2>/dev/null | grep -Fxq 'helm_release.this'; then
    if helm status argocd --namespace argocd >/dev/null 2>&1; then
      echo "Adopting existing Argo CD Helm release into OpenTofu state."
      verify_current_main_commit
      terragrunt import -no-color helm_release.this argocd/argocd
    else
      echo "Argo CD Helm release is absent; OpenTofu will install it."
    fi
  fi
  verify_current_main_commit
  terragrunt apply -no-color -auto-approve
)
echo "::endgroup::"

plan_and_apply_langfuse_prerequisites

echo "::group::Kubernetes node label apply"
(
  cd IaC/homelab/us-west-2/shared/kubernetes-node-labels
  rm -f plan.out plan.json
  terragrunt plan -out plan.out -no-color
  terragrunt --log-disable show -json plan.out >plan.json
  conftest test --policy "${repo_root}/policy" --output github plan.json
  verify_current_main_commit
  terragrunt apply -no-color plan.out
)
echo "::endgroup::"

echo "::group::AzureAD application registration apply"
if azuread_credentials_available; then
  (
    cd IaC/homelab/us-west-2/apps
    verify_current_main_commit
    terragrunt run --all --filter "$(terragrunt_azuread_changed_filter)" --filter "$(terragrunt_azuread_pilot_filter)" --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
  )
elif terragrunt_azuread_stack_changed; then
  echo "AzureAD credentials are required because IaC/homelab/us-west-2/apps changed or the apply diff could not be determined." >&2
  echo "Set AZUREAD_CLIENT_ID and AZUREAD_TENANT_ID on homelab-production; the job requires GitHub OIDC token access." >&2
  exit 1
else
  echo "::warning::Skipping AzureAD application registration because AzureAD credentials are not configured and IaC/homelab/us-west-2/apps did not change in this push."
fi
echo "::endgroup::"

echo "::group::Argo CD Application registration apply"
plan_and_apply_argocd_apps
echo "::endgroup::"

echo "::group::External Secrets AWS auth Secret state adoption"
verify_current_main_commit
kubectl apply -f clusters/homelab/apps/external-secrets/namespace.yaml
if kubectl -n external-secrets get secret aws-ssm-auth >/dev/null 2>&1; then
  (
    cd IaC/homelab/us-west-2/shared/kubernetes-secrets/external-secrets-aws-ssm-auth
    terragrunt init -no-color
    if ! terragrunt state list -no-color 2>/dev/null | grep -Fxq 'kubernetes_secret_v1.this'; then
      verify_current_main_commit
      terragrunt import -no-color kubernetes_secret_v1.this external-secrets/aws-ssm-auth
    fi
  )
else
  echo "external-secrets/aws-ssm-auth is absent; Kubernetes secret materialization will create it from SSM."
fi
echo "::endgroup::"

echo "::group::Kubernetes secret materialization apply"
(
  cd IaC/homelab/us-west-2/shared/kubernetes-secrets
  verify_current_main_commit
  terragrunt run --all --filter "$(terragrunt_changed_filter '*')" --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
)
echo "::endgroup::"
