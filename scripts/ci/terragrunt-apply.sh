#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(pwd)"
# shellcheck source=scripts/ci/terragrunt-filter-base.sh
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

exclude_other_affected_units() {
  local selected="$1"
  local unit

  exclusions=()
  while IFS= read -r unit; do
    [[ "$unit" == "$selected" ]] || exclusions+=(--filter "!./$unit")
  done <<<"$affected_units"
}

destroy_deleted_terragrunt_units() {
  local retire_app="${1:-}"
  local live_app
  local deleted_units=()
  local deleted_unit_paths
  local unit_dir source_dir plan_dir plan_file json_file index
  local -a exclusions
  local source_dirs=() plan_dirs=()

  if ! deleted_unit_paths="$(terragrunt_deleted_unit_paths)"; then
    echo "Unable to determine deleted Terragrunt units; refusing to apply." >&2
    return 1
  fi
  if [[ -n "$retire_app" ]]; then
    deleted_unit_paths="$(terragrunt_retired_argocd_app_path "$retire_app" "$deleted_unit_paths")" || return 1
  fi

  while IFS= read -r unit_dir; do
    [[ -n "$unit_dir" ]] && deleted_units+=("$unit_dir")
  done <<<"$deleted_unit_paths"

  if ((${#deleted_units[@]} == 0)); then
    echo "No deleted Terragrunt units require destroy handling."
    return 0
  fi

  for unit_dir in "${deleted_units[@]}"; do
    plan_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/terragrunt-deleted-apply.XXXXXX")"
    cleanup_dirs+=("$plan_dir")
    source_dir="$(terragrunt_deleted_unit_source "$unit_dir")"
    if ! terragrunt_unit_affected "$source_dir" "$affected_units"; then
      echo "Terragrunt did not discover deleted unit ${source_dir}; refusing retirement." >&2
      return 1
    fi
    if [[ "$unit_dir" == IaC/live/azuread-applications/* ]] && ! azuread_credentials_available; then
      echo "AzureAD credentials are required for deleted AzureAD units." >&2
      return 1
    fi
    source_dirs+=("$source_dir")
    plan_dirs+=("$plan_dir")
    plan_file="${plan_dir}/binary/@main/${source_dir}/tfplan.tfplan"
    json_file="${plan_dir}/json/@main/${source_dir}/tfplan.json"

    echo "::group::Deleted Terragrunt unit state destroy: ${unit_dir}"
    exclude_other_affected_units "$source_dir"
    terragrunt run --all --non-interactive --filter-affected "${exclusions[@]}" --filter-allow-destroy \
      --out-dir "$plan_dir/binary" --json-out-dir "$plan_dir/json" -- plan -refresh=false -no-color >/dev/null
    if [[ ! -s "$plan_file" || ! -s "$json_file" ]] ||
      [[ "$(find "$plan_dir/binary" -type f -name tfplan.tfplan)" != "$plan_file" ||
         "$(find "$plan_dir/json" -type f -name tfplan.json)" != "$json_file" ]]; then
      echo "Expected exactly one saved destroy plan for deleted Terragrunt unit ${unit_dir}." >&2
      return 1
    fi
    conftest test --policy "${repo_root}/policy" --output github "$json_file" || return 1
    if [[ -n "$retire_app" ]]; then
      live_app="$(kubectl -n argocd get application "$retire_app" --ignore-not-found -o json)" || return 1
      if ! terragrunt_retired_argocd_app_plan "$retire_app" "${live_app:-null}" "$json_file"; then
        echo "Retirement plan must delete only the selected Application with cascading deletion enabled." >&2
        return 1
      fi
    fi
    echo "::endgroup::"
  done

  for index in "${!source_dirs[@]}"; do
    echo "::group::Deleted Terragrunt unit state destroy: ${deleted_units[index]}"
    verify_current_main_commit
    exclude_other_affected_units "${source_dirs[index]}"
    terragrunt run --all --non-interactive --filter-affected "${exclusions[@]}" --filter-allow-destroy \
      --out-dir "${plan_dirs[index]}/binary" -- apply -no-color
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
  local filters=() plan_json_files=()
  local live_apps=""
  local plan_dir app_unit app

  if [[ -n "${TERRAGRUNT_ARGOCD_APP:-}" ]]; then
    app_unit="$(cd IaC/homelab/us-west-2/apps && terragrunt_argocd_app_filter)"
    filters+=(--filter "./$app_unit")
  else
    while IFS= read -r app_unit; do
      [[ "$app_unit" == IaC/homelab/us-west-2/apps/*/argocd && -f "$app_unit/terragrunt.hcl" ]] || continue
      app_unit="${app_unit#IaC/homelab/us-west-2/apps/}"
      app="${app_unit%/argocd}"
      if [[ "$existing_argocd_only" == true ]]; then
        if [[ -z "$live_apps" ]]; then
          live_apps="$(kubectl -n argocd get applications -o json | jq -r '.items[].metadata.name')"
          [[ -n "$live_apps" ]] || { echo "No live Argo CD Applications found; refusing existing-only apply." >&2; return 1; }
        fi
        if ! grep -Fxq "$app" <<<"$live_apps"; then
          echo "::notice::Skipping absent Argo CD Application ${app}; use a targeted apply after its gates."
          continue
        fi
      fi
      filters+=(--filter "./$app_unit")
    done <<<"$affected_units"
  fi
  if ((${#filters[@]} == 0)); then
    echo "No affected Argo CD Application registration units require apply."
    return
  fi

  plan_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/terragrunt-argocd-apps.XXXXXX")"
  cleanup_dirs+=("$plan_dir")
  (
    cd IaC/homelab/us-west-2/apps
    terragrunt run --all "${filters[@]}" --non-interactive --parallelism 1 --source-update \
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
  python3 -I scripts/ci/argocd-registration-plan-check.py \
    --existing-only "$existing_argocd_only" "${plan_json_files[@]}"

  (
    cd IaC/homelab/us-west-2/apps
    verify_current_main_commit
    terragrunt run --all "${filters[@]}" --non-interactive --parallelism 1 \
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
    [[ -z "${TERRAGRUNT_ARGOCD_APP:-}" && -z "${TERRAGRUNT_RETIRE_ARGOCD_APP:-}" && "${TERRAGRUNT_REPAIR_ARGOCD_APP_STATE:-false}" == false && "$existing_argocd_only" == false ]] || {
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

if [[ -n "${TERRAGRUNT_RETIRE_ARGOCD_APP:-}" ]]; then
  if [[ "${GITHUB_EVENT_NAME:-}" != workflow_dispatch ||
        -n "${TERRAGRUNT_ARGOCD_APP:-}" || "$existing_argocd_only" != false ||
        "${TERRAGRUNT_REPAIR_ARGOCD_APP_STATE:-false}" != false ]]; then
    echo "Application retirement requires a protected dispatch without another apply scope." >&2
    exit 2
  fi
  affected_units="$(terragrunt_affected_units)"
  destroy_deleted_terragrunt_units "$TERRAGRUNT_RETIRE_ARGOCD_APP"
  exit 0
fi

repair_argocd_app_state_unit="$(
  cd IaC/homelab/us-west-2/apps
  terragrunt_argocd_app_state_repair_unit
)"
if [[ "${TERRAGRUNT_ARGOCD_APP:-}" == "langfuse" || "${TERRAGRUNT_ARGOCD_APP:-}" == "litellm" || "${TERRAGRUNT_ARGOCD_APP:-}" == "fleet" || "${TERRAGRUNT_ARGOCD_APP:-}" == "mastodon" || "${TERRAGRUNT_ARGOCD_APP:-}" == "traefik" || "${TERRAGRUNT_ARGOCD_APP:-}" == "codex-cloud-signer" || "${TERRAGRUNT_ARGOCD_APP:-}" == "uptime-kuma" || "${TERRAGRUNT_ARGOCD_APP:-}" == "adguard" ]]; then
  # This path skips bootstrap/platform reconciliation. Fail before any state
  # repair, import or apply if those existing prerequisites are not ready.
  (cd IaC/homelab/us-west-2/apps && terragrunt_argocd_app_filter) >/dev/null
  echo "::group::Targeted Argo CD apply prerequisites"
  target_project=homelab
  target_namespace="$TERRAGRUNT_ARGOCD_APP"
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "litellm" ]]; then
    target_namespace=ai
    kubectl get namespace ai -o name >/dev/null
  fi
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "uptime-kuma" ]]; then
    target_namespace=monitoring
    kubectl get namespace monitoring -o name >/dev/null
    # Local state is created by the app overlay, but its selected node must
    # already be schedulable and healthy before any secret/state mutation.
    kubectl get node acer -o json | jq -e '
      (.spec.unschedulable != true) and
      any(.status.conditions[]; .type == "Ready" and .status == "True")
    ' >/dev/null
  fi
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "codex-cloud-signer" || "$TERRAGRUNT_ARGOCD_APP" == "adguard" ]]; then
    target_project=homelab-workloads
    target_namespace=automation
    kubectl get namespace automation -o name >/dev/null
  fi
  kubectl -n argocd get appproject "$target_project" -o json | jq -e \
    --arg app "$TERRAGRUNT_ARGOCD_APP" --arg namespace "$target_namespace" '
    .spec |
    (.sourceRepos | index("https://github.com/Stuhlmuller/homelab.git") != null) and
    ($app != "langfuse" or (.sourceRepos | index("ghcr.io/langfuse/langfuse-k8s/charts") != null)) and
    (($app != "traefik" and $app != "uptime-kuma") or (.sourceRepos | index("https://bjw-s-labs.github.io/helm-charts") != null)) and
    any(.destinations[]; .namespace == $namespace and .server == "https://kubernetes.default.svc") and
    ($app == "codex-cloud-signer" or $app == "adguard" or any(.clusterResourceWhitelist[]; .group == "" and .kind == "Namespace")) and
    (($app != "mastodon" and $app != "uptime-kuma") or (
      any(.clusterResourceWhitelist[]; .group == "" and .kind == "PersistentVolume") and
      any(.clusterResourceWhitelist[]; .group == "storage.k8s.io" and .kind == "StorageClass")
    ))
  ' >/dev/null
  prerequisite_apps=(external-secrets cert-manager istio platform-storage)
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "traefik" ]]; then
    prerequisite_apps=(cert-manager istio tailscale)
  elif [[ "$TERRAGRUNT_ARGOCD_APP" == "adguard" ]]; then
    prerequisite_apps=(external-secrets tailscale traefik tailnet-dns platform-storage)
  elif [[ "$TERRAGRUNT_ARGOCD_APP" == "codex-cloud-signer" ]]; then
    prerequisite_apps=(external-secrets tailscale traefik platform-storage)
  elif [[ "$TERRAGRUNT_ARGOCD_APP" == "mastodon" ]]; then
    prerequisite_apps+=(octelium-public)
  elif [[ "$TERRAGRUNT_ARGOCD_APP" == "uptime-kuma" ]]; then
    prerequisite_apps+=(prometheus traefik)
  elif [[ "$TERRAGRUNT_ARGOCD_APP" == "fleet" ]]; then
    prerequisite_apps+=(traefik)
  fi
  kubectl -n argocd get applications "${prerequisite_apps[@]}" -o json | jq -e \
    --argjson expected "${#prerequisite_apps[@]}" --arg target "$TERRAGRUNT_ARGOCD_APP" '
    (.items | length == $expected) and
    all(.items[]; .status.sync.status == "Synced" and
      (if $target == "uptime-kuma" and .metadata.name == "traefik"
       then true else .status.health.status == "Healthy" end))
  ' >/dev/null
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "uptime-kuma" ]]; then
    # Aggregate ingress health includes unrelated consumers. Check the actual
    # private routing workload and its declared wildcard certificate instead.
    kubectl -n traefik get deployment traefik -o json | jq -e '
      (.metadata.generation > 0) and
      (.status.observedGeneration == .metadata.generation) and
      (.spec.replicas > 0) and
      (.status.updatedReplicas == .spec.replicas) and
      (.status.readyReplicas == .spec.replicas) and
      (.status.availableReplicas == .spec.replicas)
    ' >/dev/null
    kubectl -n traefik get certificate traefik -o json | jq -e '
      . as $certificate |
      (.metadata.generation > 0) and
      (.spec.secretName == "traefik-tls") and
      ((.spec.dnsNames // []) | index("*.stinkyboi.com") != null) and
      any(.status.conditions[]?; .type == "Ready" and .status == "True" and
        .observedGeneration == $certificate.metadata.generation)
    ' >/dev/null
  fi
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
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "codex-cloud-signer" || "$TERRAGRUNT_ARGOCD_APP" == "adguard" ]]; then
    prerequisite_crds=(crd/externalsecrets.external-secrets.io crd/clustersecretstores.external-secrets.io)
  fi
  kubectl wait --for=condition=Established --timeout=0s "${prerequisite_crds[@]}"
  if [[ "$TERRAGRUNT_ARGOCD_APP" == "traefik" ]]; then
    kubectl wait --for=condition=Ready --timeout=0s clusterissuer/letsencrypt-cloudflare
  else
    kubectl wait --for=condition=Ready --timeout=0s clustersecretstore/aws-ssm
    if [[ "$TERRAGRUNT_ARGOCD_APP" == "litellm" || "$TERRAGRUNT_ARGOCD_APP" == "fleet" || "$TERRAGRUNT_ARGOCD_APP" == "mastodon" || "$TERRAGRUNT_ARGOCD_APP" == "codex-cloud-signer" || "$TERRAGRUNT_ARGOCD_APP" == "uptime-kuma" || "${TERRAGRUNT_ARGOCD_APP:-}" == "adguard" ]]; then
      kubectl get clustersecretstore aws-ssm -o json | jq -e --arg app "$target_namespace" '
        any(.spec.conditions[]?.namespaces[]?; . == $app)
      ' >/dev/null
    fi
    if [[ "$TERRAGRUNT_ARGOCD_APP" == "codex-cloud-signer" ]]; then
      kubectl get storageclass codex-cloud-signer-local -o name >/dev/null
      kubectl get pv codex-cloud-signer-local -o name >/dev/null
    else
      kubectl get storageclass nfs-default -o name >/dev/null
    fi
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
  elif [[ "$TERRAGRUNT_ARGOCD_APP" == "litellm" || "$TERRAGRUNT_ARGOCD_APP" == "fleet" || "$TERRAGRUNT_ARGOCD_APP" == "mastodon" || "$TERRAGRUNT_ARGOCD_APP" == "codex-cloud-signer" || "$TERRAGRUNT_ARGOCD_APP" == "uptime-kuma" || "${TERRAGRUNT_ARGOCD_APP:-}" == "adguard" || "$TERRAGRUNT_ARGOCD_APP" == "kagent" ]]; then
    plan_and_apply_ssm_prerequisites
  fi
  echo "::group::Targeted Argo CD Application registration apply"
  plan_and_apply_argocd_apps
  echo "::endgroup::"
  exit 0
fi

affected_units="$(terragrunt_affected_units)"
azuread_filters=()
secret_filters=()
while IFS= read -r unit; do
  [[ -f "$unit/terragrunt.hcl" ]] || continue
  case "$unit" in
    IaC/homelab/us-west-2/apps/*/azuread|IaC/homelab/us-west-2/apps/fleet/pilot-user)
      azuread_filters+=(--filter "./${unit#IaC/homelab/us-west-2/apps/}")
      ;;
    IaC/homelab/us-west-2/shared/kubernetes-secrets/*)
      secret_filters+=(--filter "./${unit#IaC/homelab/us-west-2/shared/kubernetes-secrets/}")
      ;;
  esac
done <<<"$affected_units"
if ((${#azuread_filters[@]} > 0)) && ! azuread_credentials_available; then
  echo "AzureAD credentials are required for affected AzureAD units." >&2
  echo "Set AZUREAD_CLIENT_ID and AZUREAD_TENANT_ID on homelab-production; the job requires GitHub OIDC token access." >&2
  exit 1
fi

destroy_deleted_terragrunt_units

if terragrunt_active_unit_affected "IaC/homelab/us-west-2/operator/application-backup-storage" "$affected_units"; then
  echo "::group::OpenClaw legacy offsite bucket plan and apply"
  plan_and_apply_application_backup_storage
  echo "::endgroup::"
fi

if terragrunt_active_unit_affected "IaC/homelab/us-west-2/bootstrap/argocd" "$affected_units"; then
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
fi

if terragrunt_active_unit_affected "IaC/homelab/us-west-2/apps/langfuse/blob-storage" "$affected_units"; then
  plan_and_apply_langfuse_prerequisites
elif terragrunt_active_unit_affected "IaC/homelab/us-west-2/shared/aws-ssm-parameters" "$affected_units"; then
  plan_and_apply_ssm_prerequisites
fi

if terragrunt_active_unit_affected "IaC/homelab/us-west-2/shared/kubernetes-node-labels" "$affected_units"; then
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
fi

if ((${#azuread_filters[@]} > 0)); then
  echo "::group::AzureAD application registration apply"
  (
    cd IaC/homelab/us-west-2/apps
    verify_current_main_commit
    terragrunt run --all "${azuread_filters[@]}" --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
  )
  echo "::endgroup::"
fi

echo "::group::Argo CD Application registration apply"
plan_and_apply_argocd_apps
echo "::endgroup::"

if terragrunt_active_unit_affected "IaC/homelab/us-west-2/shared/kubernetes-secrets/external-secrets-aws-ssm-auth" "$affected_units"; then
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
fi

if ((${#secret_filters[@]} > 0)); then
  echo "::group::Kubernetes secret materialization apply"
  (
    cd IaC/homelab/us-west-2/shared/kubernetes-secrets
    verify_current_main_commit
    terragrunt run --all "${secret_filters[@]}" --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
  )
  echo "::endgroup::"
fi
