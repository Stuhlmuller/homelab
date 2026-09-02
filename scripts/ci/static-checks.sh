#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/terragrunt-filter-base.sh"

terragrunt_generate_stack

echo "::group::Terragrunt HCL"
terragrunt hcl fmt --check
terragrunt hcl validate
expected_units="$(rg -c '^unit "' IaC/terragrunt.stack.hcl)"
parsed_units="$(terragrunt_stack_unit_paths_at_ref HEAD | wc -l | tr -d ' ')"
if [[ "$parsed_units" -ne "$expected_units" ]]; then
  echo "Parsed ${parsed_units} of ${expected_units} explicit stack units" >&2
  exit 1
fi
if rg -q '^[[:space:]]+kustomize[[:space:]]*=[[:space:]]*\{\}[[:space:]]*$' IaC/terragrunt.stack.hcl; then
  echo "Terragrunt-owned Argo CD Applications must omit empty Kustomize options because Argo CD normalizes them away." >&2
  exit 1
fi
terragrunt --log-disable --working-dir IaC/live/argocd-apps/istio \
  render --json --write=false --no-color \
  | jq -e '
      any(.inputs.manifest.spec.sources[];
        .chart == "ztunnel" and
        any(.helm.parameters[]?;
          .name == "podLabels.homelab\\.rst\\.io/service-account-issuer-cutover" and
          .value == "10-1-0-199-v1")
        and any(.helm.parameters[]?;
          .name == "updateStrategy.rollingUpdate.maxSurge" and
          .value == "0")
        and any(.helm.parameters[]?;
          .name == "updateStrategy.rollingUpdate.maxUnavailable" and
          .value == "1")
      )
    ' >/dev/null
while IFS= read -r unit_dir; do
  if [[ ! -f "${unit_dir}/.terraform.lock.hcl" ]]; then
    echo "Explicit Terragrunt unit ${unit_dir} is missing .terraform.lock.hcl" >&2
    exit 1
  fi
done < <(terragrunt_stack_unit_paths_at_ref HEAD)
if rg -q 'extra_arguments[[:space:]]+"plan"|arguments[[:space:]]*=[[:space:]]*\[[^]]*plan\.out' IaC/root.hcl; then
  echo "IaC/root.hcl must not persist every local plan; saved plans belong only in explicit, cleaned-up workflows." >&2
  exit 1
fi
if rg -q 'show[[:space:]]+-no-color[[:space:]]+.*plan\.out|cat[[:space:]]+"?\$state_list_file"?' scripts/ci/terragrunt-plan.sh; then
  echo "The public PR plan job must not render live plan or state details." >&2
  exit 1
fi
if ! yq -e '[.repos[] | select(.repo != "local") | .rev | test("^[0-9a-f]{40}$")] | all' \
  .pre-commit-config.yaml >/dev/null; then
  echo "Remote pre-commit hooks must be pinned to full commit SHAs." >&2
  exit 1
fi
echo "::endgroup::"

echo "::group::Terragrunt Azure credential gate"
(
  base_root=$'locals {}\n\nterraform {\n  extra_arguments "plan" {\n    commands  = ["plan"]\n    arguments = ["-out", "plan.out"]\n  }\n}\n\ninputs = {}'
  head_root=$'locals {}\n\ninputs = {}'
  direct_azure_change=false
  root_change=false
  root_helper_failure=false
  stack_change=false

  git() {
    case "$1" in
      cat-file) [[ "$3" != 'bad^{commit}' ]] ;;
      diff) [[ "$direct_azure_change" == false ]] ;;
      show)
        if [[ "$root_helper_failure" == true ]]; then
          return 1
        fi
        case "$2" in
          base:IaC/root.hcl) printf '%s\n' "$base_root" ;;
          head:IaC/root.hcl)
            if [[ "$root_change" == true ]]; then
              printf '%s\n' "${head_root/inputs = \{\}/inputs = { changed = true\}}"
            else
              printf '%s\n' "$head_root"
            fi
            ;;
          *) return 1 ;;
        esac
        ;;
      *) return 1 ;;
    esac
  }
  terragrunt_stack_units_at_ref() {
    if [[ "$stack_change" == true && "$1" == head ]]; then
      printf 'changed\n'
    else
      printf 'unchanged\n'
    fi
  }

  export APPLY_BASE_SHA="base"
  export APPLY_HEAD_SHA="head"
  if terragrunt_azuread_stack_changed; then
    echo "The removed legacy root plan block must not require Azure credentials." >&2
    exit 1
  fi

  root_change=true
  terragrunt_azuread_stack_changed
  root_change=false

  direct_azure_change=true
  terragrunt_azuread_stack_changed
  direct_azure_change=false

  stack_change=true
  terragrunt_azuread_stack_changed
  stack_change=false

  APPLY_BASE_SHA=""
  terragrunt_azuread_stack_changed
  APPLY_BASE_SHA=bad
  terragrunt_azuread_stack_changed
  APPLY_BASE_SHA="base"

  root_helper_failure=true
  terragrunt_azuread_stack_changed
)
echo "::endgroup::"

echo "::group::Terragrunt deleted-unit ownership"
(
  git() {
    case "$1" in
      rev-parse) return 0 ;;
      diff) printf '%s\n' IaC/.catalog/units/live/old/terragrunt.hcl IaC/operator/old/terragrunt.hcl IaC/live/old/terragrunt.hcl IaC/bootstrap/old/terragrunt.hcl ;;
      *) return 1 ;;
    esac
  }
  terragrunt_stack_unit_paths_at_ref() {
    printf '%s\n' IaC/live/old
    if [[ "$1" == "base" ]]; then
      printf '%s\n' IaC/live/retired IaC/operator/retired
    fi
  }
  export TERRAGRUNT_EFFECTIVE_FILTER_BASE_REF="base"
  export TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF="head"
  [[ "$(terragrunt_deleted_unit_paths)" == $'IaC/bootstrap/old\nIaC/live/retired' ]]
)
echo "::endgroup::"

echo "::group::Terragrunt deleted-unit providers"
(
  deleted_unit_test_root="$(mktemp -d)"
  trap 'rm -rf -- "$deleted_unit_test_root"' EXIT
  terragrunt_create_deleted_unit_destroy_stack "$deleted_unit_test_root" IaC/live/argocd-apps/deleted-unit-test
  (
    cd "${deleted_unit_test_root}/IaC/live/argocd-apps/deleted-unit-test"
    terragrunt render --json
  ) | jq -e '
    .generate.kubernetes_provider.contents as $kubernetes |
    .generate.deleted_unit_destroy_config.contents as $config |
    ($kubernetes | contains("provider \"kubernetes\"")) and
    ($kubernetes | contains("config_path = pathexpand(\"~/.kube/config\")")) and
    ($config | contains("provider \"helm\"")) and
    ($config | contains("config_path = pathexpand(\"~/.kube/config\")"))
  ' >/dev/null
)
echo "::endgroup::"

echo "::group::Terragrunt generated-unit filters"
(
  cd IaC/live/argocd-apps
  terragrunt_stack_changed() { return 0; }
  [[ "$(terragrunt_changed_filter 'IaC/live/argocd-apps/*')" == "*" ]]
  terragrunt_stack_changed() { [[ "${2:-false}" == "true" ]]; }
  [[ "$(terragrunt_changed_filter 'IaC/live/argocd-apps/*' true)" == "*" ]]
  [[ "$(terragrunt_changed_filter 'IaC/live/argocd-apps/*')" == "IaC/live/argocd-apps/* | [main...HEAD]" ]]
  [[ "$(TERRAGRUNT_ARGOCD_APP=affine terragrunt_argocd_app_filter)" == "affine" ]]
  if TERRAGRUNT_ARGOCD_APP=../bootstrap terragrunt_argocd_app_filter; then
    echo "Unsafe Argo CD Application unit filter was accepted" >&2
    exit 1
  fi
  [[ -z "$(TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=false terragrunt_argocd_app_state_repair_unit)" ]]
  if TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=invalid terragrunt_argocd_app_state_repair_unit; then
    echo "Invalid Argo CD Application state repair value was accepted" >&2
    exit 1
  fi
  if TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=true GITHUB_EVENT_NAME=push \
    TERRAGRUNT_ARGOCD_APP=affine terragrunt_argocd_app_state_repair_unit; then
    echo "Non-dispatch Argo CD Application state repair was accepted" >&2
    exit 1
  fi
  if TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=true GITHUB_EVENT_NAME=workflow_dispatch \
    terragrunt_argocd_app_state_repair_unit; then
    echo "Untargeted Argo CD Application state repair was accepted" >&2
    exit 1
  fi
  if TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=true GITHUB_EVENT_NAME=workflow_dispatch \
    TERRAGRUNT_ARGOCD_APP=../bootstrap terragrunt_argocd_app_state_repair_unit; then
    echo "Unsafe Argo CD Application state repair target was accepted" >&2
    exit 1
  fi
  [[ "$(TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=true GITHUB_EVENT_NAME=workflow_dispatch \
    TERRAGRUNT_ARGOCD_APP=affine terragrunt_argocd_app_state_repair_unit)" == "affine" ]]
)
echo "::endgroup::"

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
  '/homelab/argocd-image-updater/github-app/private-key'; do
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
  terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
  terragrunt --log-disable run --no-auto-init -- validate -no-color
  terragrunt --log-disable run --no-auto-init -- test -no-color
)
echo "::endgroup::"

echo "::group::Octelium bootstrap node containment"
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

echo "::group::Cloudflare API response handling"
(
  check_cloudflare_response() (
    local script="$1"
    local mock_response="$2"
    local curl_status="${3:-0}"
    local cf_api_source

    cf_api_source="$(awk '/^cf_api\(\)/,/^}/' "$script")"
    [[ -n "$cf_api_source" ]]

    # Used by the helper evaluated below.
    # shellcheck disable=SC2034
    # checkov:skip=CKV_SECRET_6: Inert leak-detection sentinel, not secret material.
    cloudflare_token="mock-token-must-not-leak"
    # Invoked indirectly by the evaluated helper.
    # shellcheck disable=SC2329
    curl() {
      printf '%s\n' "$mock_response"
      return "$curl_status"
    }

    eval "$cf_api_source"
    cf_api GET "/zones/mock"
  )

  for script in scripts/octelium-public-dns.sh scripts/octelium-gateway-dns.sh; do
    success_response='{"success":true,"result":[]}'
    [[ "$(check_cloudflare_response "$script" "$success_response")" == "$success_response" ]]

    for rejected_response in \
      '{"success":false,"errors":[{"code":1000,"message":"rejected"}]}' \
      '{}' \
      'not-json'; do
      if response_error="$(check_cloudflare_response "$script" "$rejected_response" 2>&1)"; then
        echo "${script} accepted a rejected or invalid Cloudflare API response" >&2
        exit 1
      fi
      if grep -Fq 'mock-token-must-not-leak' <<<"$response_error"; then
        echo "${script} exposed the Cloudflare API token while reporting a response error" >&2
        exit 1
      fi
    done

    if transport_error="$(check_cloudflare_response "$script" "$success_response" 22 2>&1)"; then
      echo "${script} accepted a failed Cloudflare API transport" >&2
      exit 1
    fi
    if grep -Fq 'mock-token-must-not-leak' <<<"$transport_error"; then
      echo "${script} exposed the Cloudflare API token while reporting a transport error" >&2
      exit 1
    fi
  done
)
echo "::endgroup::"

echo "::group::Helm workload token contracts"
yq -e '.controllers.octobot.pod.automountServiceAccountToken == false' \
  clusters/homelab/apps/octobot/values.yaml >/dev/null
yq -e '.automountServiceAccountToken == false' \
  clusters/homelab/apps/grafana/values.yaml >/dev/null
echo "::endgroup::"

echo "::group::Kustomize overlays"
while IFS= read -r overlay; do
  echo "rendering ${overlay}"
  kubectl kustomize "$overlay" >/dev/null
done < <(
  find clusters/homelab/argocd clusters/homelab/apps clusters/homelab/platform \
    -name kustomization.yaml \
    -exec dirname {} \; | sort
)
echo "::endgroup::"

echo "::group::Multica PostgreSQL recovery probes"
kubectl kustomize clusters/homelab/apps/multica |
  yq ea -o=json -I=0 '[.]' - |
  jq -e '
    [.[] | select(.kind == "Deployment" and .metadata.name == "multica-postgres")] |
    length == 1 and (.[0].spec.template.spec |
      .terminationGracePeriodSeconds == 120 and
      (.containers[] | select(.name == "postgres") |
        .startupProbe.exec.command == ["pg_isready", "-U", "multica", "-d", "multica"] and
        [.startupProbe.periodSeconds, .startupProbe.timeoutSeconds, .startupProbe.failureThreshold] == [10, 5, 180] and
        .readinessProbe.exec.command == ["psql", "-U", "multica", "-d", "multica", "-Atqc", "SELECT 1"] and
        [.readinessProbe.periodSeconds, .readinessProbe.timeoutSeconds, .readinessProbe.failureThreshold] == [10, 5, 6] and
        .livenessProbe.exec.command == .readinessProbe.exec.command and
        [.livenessProbe.periodSeconds, .livenessProbe.timeoutSeconds, .livenessProbe.failureThreshold] == [30, 5, 60]
      )
    )
  ' >/dev/null
echo "::endgroup::"

echo "::group::Media PostgreSQL backup claim"
kubectl kustomize clusters/homelab/apps/media-postgres |
  yq ea -o=json -I=0 '[.]' - |
  jq -e '
    [.[] | select(.kind == "PersistentVolumeClaim" and .metadata.name == "data-media-postgres-0")] as $claims |
    [.[] | select(.kind == "CronJob" and .metadata.name == "media-postgres-backup")] as $backups |
    ($claims | length) == 1 and
    ($backups | length) == 1 and
    $claims[0].metadata.annotations["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false" and
    $claims[0].spec.storageClassName == "nfs-default" and
    $claims[0].spec.resources.requests.storage == "20Gi" and
    any($backups[0].spec.jobTemplate.spec.template.spec.volumes[];
      .persistentVolumeClaim.claimName == "data-media-postgres-0"
    )
  ' >/dev/null
echo "::endgroup::"

echo "::group::Octelium PostgreSQL backup contract"
kubectl kustomize clusters/homelab/apps/octelium-storage |
  yq ea -o=json -I=0 '[.]' - |
  jq -e '
    [.[] | select(.kind == "CronJob" and .metadata.name == "octelium-postgres-backup")] as $backups |
    [.[] | select(.kind == "PersistentVolumeClaim" and .metadata.name == "octelium-postgres-backup")] as $claims |
    [.[] | select(.kind == "NetworkPolicy" and .metadata.name == "octelium-postgres-backup")] as $policies |
    $backups[0] as $backup |
    $backup.spec.jobTemplate.spec.template.spec as $pod |
    $pod.containers[0].command[2] as $script |
    ($backups | length) == 1 and
    ($claims | length) == 1 and
    ($policies | length) == 1 and
    $backup.spec.schedule == "30 2 * * *" and
    $backup.spec.timeZone == "Etc/UTC" and
    $backup.spec.concurrencyPolicy == "Forbid" and
    $backup.spec.jobTemplate.spec.activeDeadlineSeconds == 3600 and
    $backup.spec.jobTemplate.spec.backoffLimit == 1 and
    $pod.automountServiceAccountToken == false and
    ($script | contains("pg_dumpall")) and
    ($script | contains("--no-role-passwords")) and
    ($script | test("(?m)^pg_dump[[:space:]]+\\\\$")) and
    ($script | contains("--file=\"${partial}/octelium.dump\"")) and
    ($script | test("(?m)^[[:space:]]+octelium$")) and
    ($script | contains("pg_restore --list")) and
    ($script | contains("sha256sum --check")) and
    ($script | contains("mv \"$partial\" \"$complete\"")) and
    ($script | contains("-mtime +13")) and
    any($pod.volumes[];
      .name == "backup" and
      .persistentVolumeClaim.claimName == "octelium-postgres-backup"
    ) and
    $claims[0].metadata.annotations["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false" and
    $claims[0].spec.storageClassName == "nfs-default" and
    $claims[0].spec.resources.requests.storage == "20Gi" and
    $policies[0].spec.podSelector.matchLabels["app.kubernetes.io/name"] == "octelium-postgres" and
    any($policies[0].spec.ingress[];
      any(.from[];
        .podSelector.matchLabels["app.kubernetes.io/name"] == "octelium-postgres-backup"
      ) and
      any(.ports[]; .protocol == "TCP" and .port == 5432)
    )
  ' >/dev/null
echo "::endgroup::"

echo "::group::Cordium genesis privilege lifecycle"
yq -e '.data."controller.sync.timeout.seconds" == "900"' \
  clusters/homelab/argocd/self-management/cmd-params-configmap.yaml >/dev/null
yq ea -o=json -I=0 '[.]' clusters/homelab/argocd/self-management/appproject.yaml |
  jq -e '
    [.[] | select(.kind == "AppProject" and .metadata.name == "homelab")][0].spec as $project |
    any($project.sourceRepos[]; . == "https://github.com/Stuhlmuller/homelab.git") and
    any($project.destinations[]; . == {
      "server": "https://kubernetes.default.svc",
      "namespace": "argocd"
    }) and
    any($project.destinations[]; . == {
      "server": "https://kubernetes.default.svc",
      "namespace": "octelium"
    }) and
    any($project.clusterResourceWhitelist[]; . == {
      "group": "rbac.authorization.k8s.io",
      "kind": "ClusterRole"
    }) and
    any($project.clusterResourceWhitelist[]; . == {
      "group": "rbac.authorization.k8s.io",
      "kind": "ClusterRoleBinding"
    })
  ' >/dev/null
kubectl kustomize clusters/homelab/apps/cordium |
  yq ea -o=json -I=0 '[.]' - |
  jq -e '
    [.[] | select(.kind == "Application" and .metadata.name == "cordium-bootstrap")] as $bootstrap_apps |
    [.[] | select(.kind == "NetworkPolicy" and (.metadata.name == "cordium-genesis" or .metadata.name == "cordium-cluster-config"))] as $bootstrap_policies |
    [.[] | select(.kind == "ExternalSecret" and .metadata.name == "cordium-agent-auth")] as $bootstrap_secrets |
    [.[] | select(.kind == "DaemonSet" and .metadata.name == "cordium-user-namespace-sysctl")] as $bootstrap_hosts |
    [.[] | select(
      (.kind == "Job" and (.metadata.name == "cordium-genesis" or .metadata.name == "cordium-genesis-cleanup" or .metadata.name == "cordium-cluster-config")) or
      ((.kind == "ServiceAccount" or .kind == "ClusterRole" or .kind == "ClusterRoleBinding") and .metadata.name == "cordium-genesis")
    )] as $misowned_bootstrap |
    ($bootstrap_apps | length) == 1 and
    $bootstrap_apps[0].metadata.namespace == "argocd" and
    $bootstrap_apps[0].metadata.finalizers == ["resources-finalizer.argocd.argoproj.io"] and
    $bootstrap_apps[0].metadata.annotations["argocd.argoproj.io/hook"] == null and
    $bootstrap_apps[0].metadata.annotations["argocd.argoproj.io/sync-wave"] == "1" and
    $bootstrap_apps[0].spec.project == "homelab" and
    $bootstrap_apps[0].spec.source == {
      "repoURL": "https://github.com/Stuhlmuller/homelab.git",
      "targetRevision": "main",
      "path": "clusters/homelab/apps/cordium-bootstrap"
    } and
    $bootstrap_apps[0].spec.destination == {
      "server": "https://kubernetes.default.svc",
      "namespace": "octelium"
    } and
    $bootstrap_apps[0].spec.syncPolicy == {
      "automated": {
        "allowEmpty": false,
        "enabled": true,
        "prune": true,
        "selfHeal": true
      },
      "syncOptions": ["CreateNamespace=false", "ServerSideApply=true"],
      "retry": {
        "limit": 0
      }
    } and
    ($bootstrap_policies | length) == 2 and
    all($bootstrap_policies[]; .metadata.annotations["argocd.argoproj.io/sync-wave"] == null) and
    ($bootstrap_secrets | length) == 1 and
    $bootstrap_secrets[0].metadata.annotations["argocd.argoproj.io/sync-wave"] == null and
    ($bootstrap_hosts | length) == 1 and
    $bootstrap_hosts[0].metadata.annotations["argocd.argoproj.io/sync-wave"] == null and
    ($misowned_bootstrap | length) == 0
  ' >/dev/null
kubectl kustomize clusters/homelab/apps/cordium-bootstrap |
  yq ea -o=json -I=0 '[.]' - |
  jq -e '
    [.[] | select(
      .metadata.name == "cordium-genesis" and
      (.kind == "ServiceAccount" or .kind == "ClusterRole" or .kind == "ClusterRoleBinding")
    )] as $bootstrap |
    [.[] | select(.kind == "ServiceAccount" and .metadata.name == "cordium-genesis-cleanup")] as $cleanup_service_accounts |
    [.[] | select(.kind == "Role" and .metadata.name == "cordium-genesis-cleanup")] as $cleanup_roles |
    [.[] | select(.kind == "RoleBinding" and .metadata.name == "cordium-genesis-cleanup")] as $cleanup_role_bindings |
    [.[] | select(.kind == "ClusterRole" and .metadata.name == "cordium-genesis-cleanup")] as $cleanup_cluster_roles |
    [.[] | select(.kind == "ClusterRoleBinding" and .metadata.name == "cordium-genesis-cleanup")] as $cleanup_cluster_role_bindings |
    [.[] | select(.kind == "Job" and .metadata.name == "cordium-genesis")] as $genesis_jobs |
    [.[] | select(.kind == "Job" and .metadata.name == "cordium-genesis-cleanup")] as $cleanup_jobs |
    [.[] | select(.kind == "Job" and .metadata.name == "cordium-cluster-config")] as $cluster_config_jobs |
    [.[] | select(.kind == "ConfigMap" and (.metadata.name | startswith("cordium-cluster-config-")))] as $cluster_configs |
    [.[] | select(.kind == "Application" or .kind == "NetworkPolicy" or .kind == "ExternalSecret" or .kind == "DaemonSet")] as $misowned_prerequisites |
    ($bootstrap | length) == 3 and
    all($bootstrap[];
      .metadata.annotations["argocd.argoproj.io/hook"] == "PostSync" and
      .metadata.annotations["argocd.argoproj.io/hook-delete-policy"] == "BeforeHookCreation" and
      .metadata.annotations["argocd.argoproj.io/sync-wave"] == "-1"
    ) and
    ($cleanup_service_accounts | length) == 1 and
    $cleanup_service_accounts[0].automountServiceAccountToken == false and
    $cleanup_service_accounts[0].metadata.annotations["homelab.rst.io/cordium-genesis-revision"] ==
      $genesis_jobs[0].metadata.annotations["homelab.rst.io/cordium-genesis-revision"] and
    $genesis_jobs[0].spec.template.metadata.annotations["homelab.rst.io/cordium-genesis-revision"] ==
      $genesis_jobs[0].metadata.annotations["homelab.rst.io/cordium-genesis-revision"] and
    ($cleanup_roles | length) == 1 and
    $cleanup_roles[0].rules == [{
      "apiGroups": [""],
      "resources": ["serviceaccounts"],
      "resourceNames": ["cordium-genesis"],
      "verbs": ["delete"]
    }] and
    ($cleanup_role_bindings | length) == 1 and
    $cleanup_role_bindings[0].roleRef == {
      "apiGroup": "rbac.authorization.k8s.io",
      "kind": "Role",
      "name": "cordium-genesis-cleanup"
    } and
    $cleanup_role_bindings[0].subjects == [{
      "kind": "ServiceAccount",
      "name": "cordium-genesis-cleanup",
      "namespace": "octelium"
    }] and
    ($cleanup_cluster_roles | length) == 1 and
    $cleanup_cluster_roles[0].rules == [{
      "apiGroups": ["rbac.authorization.k8s.io"],
      "resources": ["clusterroles", "clusterrolebindings"],
      "resourceNames": ["cordium-genesis"],
      "verbs": ["delete"]
    }] and
    ($cleanup_cluster_role_bindings | length) == 1 and
    $cleanup_cluster_role_bindings[0].roleRef == {
      "apiGroup": "rbac.authorization.k8s.io",
      "kind": "ClusterRole",
      "name": "cordium-genesis-cleanup"
    } and
    $cleanup_cluster_role_bindings[0].subjects == [{
      "kind": "ServiceAccount",
      "name": "cordium-genesis-cleanup",
      "namespace": "octelium"
    }] and
    ($genesis_jobs | length) == 1 and
    $genesis_jobs[0].metadata.annotations["argocd.argoproj.io/hook"] == "PostSync" and
    $genesis_jobs[0].metadata.annotations["argocd.argoproj.io/sync-wave"] == "0" and
    $genesis_jobs[0].spec.activeDeadlineSeconds == 720 and
    ($cleanup_jobs | length) == 1 and
    $cleanup_jobs[0].metadata.annotations["argocd.argoproj.io/hook"] == "PostSync,SyncFail" and
    $cleanup_jobs[0].metadata.annotations["argocd.argoproj.io/hook-delete-policy"] == "BeforeHookCreation,HookSucceeded" and
    $cleanup_jobs[0].metadata.annotations["argocd.argoproj.io/sync-wave"] == "1" and
    $cleanup_jobs[0].spec.template.spec.serviceAccountName == "cordium-genesis-cleanup" and
    $cleanup_jobs[0].spec.template.spec.automountServiceAccountToken == true and
    ($cluster_config_jobs | length) == 1 and
    $cluster_config_jobs[0].metadata.annotations["argocd.argoproj.io/hook"] == "PostSync" and
    $cluster_config_jobs[0].metadata.annotations["argocd.argoproj.io/sync-wave"] == "1" and
    ($cluster_configs | length) == 1 and
    $cluster_configs[0].metadata.annotations["homelab.rst.io/cordium-cluster-config-revision"] == "20260822" and
    ($misowned_prerequisites | length) == 0 and
    $cleanup_jobs[0].spec.template.spec.containers[0].args == [
      "delete",
      "clusterrolebinding.rbac.authorization.k8s.io/cordium-genesis",
      "clusterrole.rbac.authorization.k8s.io/cordium-genesis",
      "serviceaccount/cordium-genesis",
      "--namespace=octelium",
      "--ignore-not-found=true",
      "--wait=false",
      "--request-timeout=30s",
      "--cache-dir=/tmp/kubectl-cache"
    ]
  ' >/dev/null
echo "::endgroup::"

echo "::group::Prowlarr config normalization"
bash scripts/ci/prowlarr-config-check.sh
echo "::endgroup::"

echo "::group::Octelium catalog security contracts"
yq ea -o=json -I=0 '[.]' docs/examples/octelium/homelab-services.yaml |
  jq -e '
    [.[] | select(.kind == "User" and .metadata.name == "homelab-ci")] as $users |
    [.[] | select(.kind == "Policy" and .metadata.name == "homelab-ci-kubernetes-api-access")] as $policies |
    [.[] | select(.kind == "Service" and .metadata.name == "nofx")] as $nofx |
    ($users | length) == 1 and
    $users[0].spec.type == "WORKLOAD" and
    $users[0].spec.session.clientlessDuration == {"days": 30} and
    $users[0].spec.session.accessTokenDuration == {"days": 30} and
    ($nofx | length) == 1 and
    ($nofx[0].spec.isAnonymous // false) == false and
    $nofx[0].spec.authorization.policies == ["homelab-human-web-access"] and
    $nofx[0].spec.config.http.header.authorizationMode == "PASS" and
    ($policies | length) == 1 and
    $policies[0].spec.rules == [{
      "name": "kubernetes-api-service",
      "effect": "ALLOW",
      "condition": {"all": {"of": [
        {"match": "ctx.user.metadata.name == \"homelab-ci\""},
        {"match": "ctx.user.spec.type == \"WORKLOAD\""},
        {"match": "ctx.session.status.type == \"CLIENTLESS\""},
        {"match": "ctx.service.metadata.name == \"kubernetes-api-ci.default\""},
        {"match": "ctx.service.spec.mode == \"KUBERNETES\""}
      ]}}
    }]
  ' >/dev/null
echo "::endgroup::"

echo "::group::Terragrunt pull request gate"
yq -o=json '.' .github/workflows/terragrunt-plan.yml |
  jq -e '
    [.jobs["static-policy"].steps[] | select(.id == "live-plan-scope")] as $scope |
    [.jobs["static-policy"].steps[] | select(.name == "Run Conftest Policies")] as $conftest |
    [.jobs["terragrunt-plan"].steps[] | select(.name == "Verify Live Plan Inputs")] as $plan_inputs |
    [.jobs["terragrunt-plan"].steps[] | select(.name == "Configure AWS Credentials")] as $aws_credentials |
    [.jobs["terragrunt-plan"].steps[] | select(.name == "Run Live Terragrunt Plan")] as $live_plan |
    (.on | keys) == ["pull_request"] and
    .on.pull_request.types == ["opened", "synchronize", "reopened", "ready_for_review"] and
    .on.pull_request.paths == null and
    (.jobs | keys | sort) == ["static-policy", "terragrunt-gate", "terragrunt-plan", "terragrunt-plan-skipped"] and
    .jobs["static-policy"].permissions == {"contents": "read"} and
    .jobs["static-policy"].steps[0].with["fetch-depth"] == 0 and
    .jobs["static-policy"].outputs["requires-live-plan"] == "${{ steps.live-plan-scope.outputs.requires-live-plan }}" and
    ($scope | length) == 1 and
    $scope[0].env.BASE_REF == "${{ github.base_ref }}" and
    ($scope[0].run | type) == "string" and
    ($conftest | length) == 1 and
    .jobs["terragrunt-plan"].needs == ["static-policy"] and
    (.jobs["terragrunt-plan"].if |
      contains("github.event.pull_request.head.repo.full_name == github.repository") and
      contains("needs.static-policy.outputs.requires-live-plan == '\''true'\''")) and
    .jobs["terragrunt-plan"].environment == {"name": "homelab-plan"} and
    .jobs["terragrunt-plan"].permissions == {
      "contents": "read",
      "id-token": "write"
    } and
    .jobs["terragrunt-plan"].env == null and
    ($plan_inputs | length) == 1 and
    $plan_inputs[0].env == {
      "AWS_PLAN_ROLE_ARN": "${{ vars.AWS_ROLE_TO_ASSUME_HOMELAB || secrets.AWS_ROLE_TO_ASSUME_HOMELAB }}",
      "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}"
    } and
    ($aws_credentials | length) == 1 and
    $aws_credentials[0].with["role-to-assume"] == "${{ vars.AWS_ROLE_TO_ASSUME_HOMELAB || secrets.AWS_ROLE_TO_ASSUME_HOMELAB }}" and
    ($live_plan | length) == 1 and
    $live_plan[0].env == {
      "ARM_CLIENT_ID": "${{ vars.AZUREAD_CLIENT_ID || secrets.AZUREAD_CLIENT_ID }}",
      "ARM_CLIENT_SECRET": "${{ secrets.AZUREAD_CLIENT_SECRET }}",
      "ARM_TENANT_ID": "${{ vars.AZUREAD_TENANT_ID || secrets.AZUREAD_TENANT_ID }}",
      "KUBE_API_SERVER_URL": "${{ env.KUBE_API_SERVER_URL }}",
      "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}"
    } and
    ([.jobs["terragrunt-plan"].steps[] |
      select(.name != "Run Live Terragrunt Plan") |
      .env.ARM_CLIENT_SECRET // empty] | length) == 0 and
    .jobs["terragrunt-plan-skipped"].needs == ["static-policy"] and
    (.jobs["terragrunt-plan-skipped"].if |
      contains("github.event.pull_request.head.repo.full_name == github.repository") and
      contains("needs.static-policy.outputs.requires-live-plan != '\''true'\''")) and
    .jobs["terragrunt-plan-skipped"].environment == null and
    .jobs["terragrunt-plan-skipped"].permissions == {} and
    (.jobs["terragrunt-plan-skipped"].steps | length) == 1 and
    (. | tostring | contains("update-pr-plan-description") | not) and
    (. | tostring | contains("pull-requests") | not) and
    ([.jobs | to_entries[] | select(.value.environment != null) | .key]) == ["terragrunt-plan"] and
    .jobs["terragrunt-gate"].if == "${{ always() }}" and
    .jobs["terragrunt-gate"].needs == ["static-policy", "terragrunt-plan", "terragrunt-plan-skipped"] and
    .jobs["terragrunt-gate"].permissions == {} and
    .jobs["terragrunt-gate"].environment == null and
    (.jobs["terragrunt-gate"] | tostring | contains("secrets") | not) and
    (.jobs["terragrunt-gate"].steps | length) == 1 and
    (.jobs["terragrunt-gate"].steps[0].run | type) == "string"
  ' >/dev/null
scope_body_sha256="$(
  yq -r '.jobs."static-policy".steps[] | select(.id == "live-plan-scope") | .run' \
    .github/workflows/terragrunt-plan.yml |
    shasum -a 256 |
    cut -d' ' -f1
)"
gate_body_sha256="$(
  yq -r '.jobs."terragrunt-gate".steps[0].run' .github/workflows/terragrunt-plan.yml |
    shasum -a 256 |
    cut -d' ' -f1
)"
[[ "$scope_body_sha256" == "9479ae825c1cb4bc27377c47c14d0c5e4ff18d3ebb74ce5cf504bb500091fee4" ]] || {
  echo "Live-plan scope body changed; review it and update its exact security hash." >&2
  exit 1
}
[[ "$gate_body_sha256" == "72b4b48f8151b1c2c778f963c618380e57df259175ce4728d57f870a439fc471" ]] || {
  echo "Terragrunt gate body changed; review it and update its exact security hash." >&2
  exit 1
}

workflow_sha256() {
  yq -o=json '.' "$1" |
    jq -cS '.' |
    shasum -a 256 |
    cut -d' ' -f1
}

credentialed_job_inventory="$({
  while IFS= read -r -d '' workflow; do
    yq -o=json '.' "$workflow" |
      jq -r --arg workflow "$workflow" '
        def has_write($permissions):
          if ($permissions | type) == "object" then
            any($permissions[]; . == "write")
          else
            $permissions == "write-all"
          end;
        def credential_context($text):
          $text | ascii_downcase |
          test("(^|[^A-Za-z0-9_])(secrets|github)([^A-Za-z0-9_]|$)");

        . as $document |
        (.permissions // {}) as $workflow_permissions |
        ((.env // {}) | tostring) as $workflow_env_text |
        .jobs | to_entries[] |
        . as $entry |
        ($entry.value | tostring) as $job_text |
        select(
          ($entry.value.environment? != null) or
          credential_context($job_text) or
          credential_context($workflow_env_text) or
          (($document.on | tostring) | contains("workflow_call")) or
          has_write($entry.value.permissions // {}) or
          has_write($workflow_permissions)
        ) |
        "\($workflow):\($entry.key)"
      '
  done < <(find .github/workflows -maxdepth 1 -type f \( -name '*.yml' -o -name '*.yaml' \) -print0)
} | LC_ALL=C sort)"
jq -en '
  def credential_context($text):
    $text | ascii_downcase |
    test("(^|[^A-Za-z0-9_])(secrets|github)([^A-Za-z0-9_]|$)");
  credential_context("${{ GITHUB [ \"token\" ] }}") and
  credential_context("${{ SECRETS [ \"NAME\" ] }}") and
  credential_context("${{ toJSON(GITHUB) }}")
' >/dev/null
expected_credentialed_job_inventory="$({
  printf '%s\n' \
    '.github/workflows/codeql.yml:analyze-actions' \
    '.github/workflows/homelab-diagnostics.yml:grafana' \
    '.github/workflows/lint.yml:build' \
    '.github/workflows/octelium-cloudflare-origin-port-remove.yml:remove' \
    '.github/workflows/octelium-cloudflare-origin-port.yml:reconcile' \
    '.github/workflows/octelium-private-kubernetes-apply.yml:reconcile' \
    '.github/workflows/octelium-private-kubernetes-apply.yml:static-policy' \
    '.github/workflows/release.yml:release' \
    '.github/workflows/release.yml:release-dry-run' \
    '.github/workflows/terragrunt-apply-request.yml:request' \
    '.github/workflows/terragrunt-apply.yml:static-policy' \
    '.github/workflows/terragrunt-apply.yml:terragrunt-apply' \
    '.github/workflows/terragrunt-plan.yml:static-policy' \
    '.github/workflows/terragrunt-plan.yml:terragrunt-gate' \
    '.github/workflows/terragrunt-plan.yml:terragrunt-plan-skipped' \
    '.github/workflows/terragrunt-plan.yml:terragrunt-plan'
} | LC_ALL=C sort)"
[[ "$credentialed_job_inventory" == "$expected_credentialed_job_inventory" ]] || {
  echo "Credentialed workflow-job inventory changed; review and hash every exact job." >&2
  diff -u \
    <(printf '%s\n' "$expected_credentialed_job_inventory") \
    <(printf '%s\n' "$credentialed_job_inventory") >&2 || true
  exit 1
}

while read -r workflow expected_hash; do
  [[ "$(workflow_sha256 "$workflow")" == "$expected_hash" ]] || {
    echo "Credential-bearing workflow changed; review it and update its exact security hash: $workflow" >&2
    exit 1
  }
done <<'EOF'
.github/workflows/codeql.yml 054c9f0d5c7305fe445b849942924088ee49ca660a3f5f2931ba650b7da471be
.github/workflows/homelab-diagnostics.yml 5043c57789978d8a1e4d352ad7d2d073168c3e298bb8dcdf008aef0ea0326864
.github/workflows/lint.yml 746d58ce358dc2cb5fb6fc0e0728c8faee85e4679b1464ff89fd2c6a6ecca139
.github/workflows/octelium-cloudflare-origin-port-remove.yml 2ea507d0bb5bb2480a19686953a3a7b12d22d9c2eff1fca6b32311824a04e037
.github/workflows/octelium-cloudflare-origin-port.yml a4e2e5601e475466eb72281b228e7f2372473cbe56cc8f6035ea3e2024bf8e19
.github/workflows/octelium-private-kubernetes-apply.yml d1500cd345ed01f16907ba9c43a15848f62cbcb13a76088e0f000428601d2aae
.github/workflows/release.yml 399ebea06d5bbd57412facb55585f4bb32b1f3d345a7669aa74096a009b15361
.github/workflows/terragrunt-apply-request.yml 0b744c5a337978c6f5675156ee62b727653f37a008f86260113610ba8646b4e5
.github/workflows/terragrunt-apply.yml a135de51cadb29530e31bc0a4f1bd3b3a033134000aa829bf6cd1c391496607f
.github/workflows/terragrunt-plan.yml 5aa71d2d401f4e6677184e5e8ad3581e4cdcef1f832d4ec7685389faffa4a240
EOF
echo "::endgroup::"

echo "::group::Exact workflow dispatch commits"
for workflow_job in \
  '.github/workflows/homelab-diagnostics.yml:grafana' \
  '.github/workflows/octelium-private-kubernetes-apply.yml:static-policy' \
  '.github/workflows/terragrunt-apply.yml:static-policy'; do
  workflow="${workflow_job%%:*}"
  job="${workflow_job##*:}"
  yq -o=json '.' "$workflow" |
    jq -e --arg job "$job" '
      .on.workflow_dispatch.inputs.expected_sha.required == true and
      .jobs[$job].steps[0].name == "Verify Dispatch Commit" and
      .jobs[$job].steps[0].env.ACTUAL_REF == "${{ github.ref }}" and
      .jobs[$job].steps[0].env.ACTUAL_SHA == "${{ github.sha }}" and
      .jobs[$job].steps[0].env.EXPECTED_SHA == "${{ inputs.expected_sha }}" and
      (.jobs[$job].steps[0].run | contains("refs/heads/main")) and
      (.jobs[$job].steps[0].run | contains("test \"${ACTUAL_SHA}\" = \"${EXPECTED_SHA}\""))
    ' >/dev/null
done
yq -o=json '.' .github/workflows/terragrunt-apply-request.yml |
  jq -e '
    (.on | keys) == ["push"] and
    .on.push == {"branches": ["main"]} and
    .permissions == {} and
    .env == null and
    (.jobs | keys) == ["request"] and
    .concurrency == {
      "group": "terragrunt-apply-request",
      "cancel-in-progress": true
    } and
    .jobs.request.environment == null and
    .jobs.request.env == null and
    .jobs.request.permissions == {"actions": "read"} and
    (.jobs.request | tostring | contains("secrets") | not) and
    (.jobs.request.permissions["id-token"] == null) and
    (.jobs.request.steps | length) == 1 and
    .jobs.request.steps[0].name == "Show Exact Apply Command" and
    .jobs.request.steps[0].env.REQUEST_SHA == "${{ github.sha }}" and
    (.jobs.request.steps[0].run |
      contains("gh workflow run terragrunt-apply.yml --repo ${GH_REPO} --ref main -f expected_sha=${REQUEST_SHA}") and
      contains("terragrunt-apply.yml/runs?per_page=100") and
      contains("select(.status != \"completed\")") and
      contains("${GITHUB_STEP_SUMMARY}"))
  ' >/dev/null
yq -o=json '.' .github/workflows/terragrunt-apply.yml |
  jq -e '
    (.concurrency == null) and
    (.on | keys) == ["workflow_dispatch"] and
    (.jobs | keys) == ["static-policy", "terragrunt-apply"] and
    (."run-name" | contains("Full @ {0}") and contains("Targeted {0} @ {1}")) and
    .on.workflow_dispatch.inputs.repair_argocd_app_state == {
      "description": "Untaint the selected Argo CD Application before reconciling it",
      "required": false,
      "default": false,
      "type": "boolean"
    } and
    .jobs["static-policy"].steps[0].if == null and
    .jobs["terragrunt-apply"].needs == ["static-policy"] and
    .jobs["terragrunt-apply"].environment == {"name": "homelab-production"} and
    (.jobs["terragrunt-apply"].env | keys | sort) == [
      "TERRAGRUNT_ARGOCD_APP",
      "TERRAGRUNT_REPAIR_ARGOCD_APP_STATE"
    ] and
    (.jobs["terragrunt-apply"].env | tostring | contains("secrets") | not) and
    .jobs["terragrunt-apply"].env.TERRAGRUNT_ARGOCD_APP == "${{ inputs.argocd_app }}" and
    .jobs["terragrunt-apply"].env.TERRAGRUNT_REPAIR_ARGOCD_APP_STATE == "${{ inputs.repair_argocd_app_state }}" and
    .jobs["terragrunt-apply"].concurrency == {
      "group": "terragrunt-apply-production",
      "cancel-in-progress": false
    } and
    .jobs["terragrunt-apply"].steps[0].name == "Verify Current Main Commit" and
    .jobs["terragrunt-apply"].steps[0].env.ACTUAL_REF == "${{ github.ref }}" and
    .jobs["terragrunt-apply"].steps[0].env.ACTUAL_SHA == "${{ github.sha }}" and
    .jobs["terragrunt-apply"].steps[0].env.EXPECTED_SHA == "${{ inputs.expected_sha }}" and
    .jobs["terragrunt-apply"].steps[0].env.GH_TOKEN == "${{ github.token }}" and
    (.jobs["terragrunt-apply"].steps[0] | tostring | contains("secrets") | not) and
    (.jobs["terragrunt-apply"].steps[0].run |
      contains("repos/${GH_REPO}/git/ref/heads/main") and
      contains("test \"${EXPECTED_SHA}\" = \"${ACTUAL_SHA}\"") and
      contains("test \"${ACTUAL_SHA}\" = \"${current_main_sha}\"")) and
    ([.jobs["terragrunt-apply"].steps | to_entries[] |
      select(.value | tostring | contains("secrets.")) | .key] | min) > 0 and
    any(.jobs["terragrunt-apply"].steps[];
      .name == "Resolve Last Successful Apply" and
      .env.APPLY_HEAD_SHA == "${{ github.sha }}"
    ) and
    (.jobs["terragrunt-apply"].steps[] | select(.name == "Resolve Last Successful Apply").run |
      contains("--paginate --slurp") and
      contains("branch=main&status=success&per_page=100") and
      contains(".event == \"push\"") and
      contains(".event == \"workflow_dispatch\"") and
      contains("startswith(\"Full @ \")") and
      contains("max_by(.run_number)"))
  ' >/dev/null
yq -o=json '.' .github/workflows/octelium-private-kubernetes-apply.yml |
  jq -e '
    [.jobs.reconcile.steps[] |
      select(.name == "Reconcile Private Kubernetes Catalog")] as $catalog_steps |
    (.on | keys) == ["workflow_dispatch"] and
    .on.workflow_dispatch.inputs == {
      "expected_sha": {
        "description": "Exact main commit to apply",
        "required": true,
        "type": "string"
      },
      "dispatch_id": {
        "description": "Unique identifier used to bind the caller to this run",
        "required": true,
        "type": "string"
      }
    } and
    .["run-name"] == "Private Kubernetes @ ${{ github.sha }} / ${{ inputs.dispatch_id }}" and
    .permissions == {} and
    (.jobs | keys | sort) == ["reconcile", "static-policy"] and
    .jobs["static-policy"].permissions == {"contents": "read"} and
    .jobs["static-policy"].steps[0].name == "Verify Dispatch Commit" and
    .jobs.reconcile.needs == ["static-policy"] and
    .jobs.reconcile.environment == {"name": "homelab-production"} and
    .jobs.reconcile.permissions == {"contents": "read"} and
    .jobs.reconcile["timeout-minutes"] == 15 and
    .jobs.reconcile.concurrency == {
      "group": "octelium-private-kubernetes-production",
      "cancel-in-progress": false
    } and
    .jobs.reconcile.steps[0].name == "Verify Current Main Commit" and
    .jobs.reconcile.steps[0].env.ACTUAL_REF == "${{ github.ref }}" and
    .jobs.reconcile.steps[0].env.ACTUAL_SHA == "${{ github.sha }}" and
    .jobs.reconcile.steps[0].env.EXPECTED_SHA == "${{ inputs.expected_sha }}" and
    .jobs.reconcile.steps[0].env.GH_TOKEN == "${{ github.token }}" and
    (.jobs.reconcile.steps[0].run |
      contains("repos/${GH_REPO}/git/ref/heads/main") and
      contains("test \"${EXPECTED_SHA}\" = \"${ACTUAL_SHA}\"") and
      contains("test \"${ACTUAL_SHA}\" = \"${current_main_sha}\"")) and
    ($catalog_steps | length) == 1 and
    $catalog_steps[0].env == {
      "OCTELIUM_CATALOG_AUTH_TOKEN": "${{ secrets.OCTELIUM_CATALOG_AUTH_TOKEN }}"
    } and
    ($catalog_steps[0].run |
      contains("bash scripts/ci/octelium-private-kubernetes-apply.sh") and
      contains("details withheld")) and
    ([.jobs.reconcile.steps[] |
      select(.name != "Reconcile Private Kubernetes Catalog") |
      .env.OCTELIUM_CATALOG_AUTH_TOKEN // empty] | length) == 0 and
    (.jobs.reconcile | tostring | contains("id-token") | not) and
    (.jobs.reconcile | tostring | contains("OCTELIUM_CI_AUTH_TOKEN") | not) and
    (.jobs.reconcile | tostring | contains("kubectl") | not) and
    (.jobs.reconcile | tostring | contains("terragrunt") | not)
  ' >/dev/null
bash -n \
  scripts/ci/octelium-private-kubernetes-apply.sh \
  scripts/octelium-private-kubernetes-credential.sh
[[ "$(shasum -a 256 scripts/ci/octelium-private-kubernetes-apply.sh | cut -d' ' -f1)" == \
  "b91ccb55d0e1e689d3c49a17309a575c4e1ffe2458900b02d2790761dd5b0518" ]] || {
  echo "Octelium private Kubernetes apply helper changed; review its exact security hash." >&2
  exit 1
}
[[ "$(shasum -a 256 scripts/octelium-private-kubernetes-credential.sh | cut -d' ' -f1)" == \
  "f3252fb26d58b7eb4ae57ac8eab64b5d8e76028406a0b60cbc1cc2332ff97ace" ]] || {
  echo "Octelium private Kubernetes credential helper changed; review its exact security hash." >&2
  exit 1
}
bash -n scripts/ci/terragrunt-apply.sh
rg -Fq 'terragrunt run -- untaint -no-color kubernetes_manifest.this' scripts/ci/terragrunt-apply.sh
echo "::endgroup::"

echo "::group::Renovate config"
jq empty renovate.json
echo "::endgroup::"

echo "::group::Private cluster access"
yq ea -o=json -I=0 '[.]' docs/examples/octelium/homelab-services.yaml |
  jq -e '
    [.[] | select(.kind == "Policy" and .metadata.name == "homelab-private-kubernetes-access")] as $policies |
    [.[] | select(.kind == "Service" and .metadata.name == "kubernetes-api.homelab")] as $services |
    [.[] | select(.kind == "Policy" and .metadata.name == "homelab-private-talos-access")] as $talos_policies |
    [.[] | select(.kind == "Service" and .metadata.name == "talos-api.homelab")] as $talos_services |
    [.[] | select(.kind == "User" and .metadata.name == "homelab-catalog-ci")] as $catalog_users |
    [.[] | select(.kind == "Credential" and .metadata.name == "homelab-private-kubernetes-ci")] as $catalog_credentials |
    ($policies | length) == 1 and
    $policies[0].spec.rules == [
      {
        "name": "cordium-sensitive-read-deny",
        "effect": "DENY",
        "condition": {"all": {"of": [
          {"match": "ctx.user.metadata.name == \"homelab-cordium-user\""},
          {"match": "ctx.user.spec.type == \"HUMAN\""},
          {"match": "ctx.session.status.type == \"CLIENT\""},
          {"match": "ctx.service.metadata.name == \"kubernetes-api.homelab\""},
          {"match": "ctx.service.spec.mode == \"KUBERNETES\""},
          {"any": {"of": [
            {"match": "ctx.request.kubernetes.resource in [\"secrets\", \"configmaps\", \"serviceaccounts\", \"tokenreviews\", \"subjectaccessreviews\", \"selfsubjectaccessreviews\", \"localsubjectaccessreviews\", \"selfsubjectrulesreviews\"]"},
            {"match": "ctx.request.kubernetes.subresource in [\"proxy\", \"log\", \"exec\", \"attach\", \"portforward\", \"ephemeralcontainers\", \"token\"]"}
          ]}}
        ]}}
      },
      {
        "name": "operator-client",
        "effect": "ALLOW",
        "condition": {"all": {"of": [
          {"match": "ctx.user.spec.type == \"HUMAN\""},
          {"match": "ctx.session.status.type == \"CLIENT\""},
          {"match": "ctx.service.metadata.name == \"kubernetes-api.homelab\""},
          {"match": "ctx.service.spec.mode == \"KUBERNETES\""},
          {"match": "ctx.user.metadata.name == \"homelab-owner\""}
        ]}}
      },
      {
        "name": "cordium-read-only-client",
        "effect": "ALLOW",
        "condition": {"all": {"of": [
          {"match": "ctx.user.spec.type == \"HUMAN\""},
          {"match": "ctx.session.status.type == \"CLIENT\""},
          {"match": "ctx.service.metadata.name == \"kubernetes-api.homelab\""},
          {"match": "ctx.service.spec.mode == \"KUBERNETES\""},
          {"match": "ctx.user.metadata.name == \"homelab-cordium-user\""},
          {"match": "ctx.request.kubernetes.verb in [\"get\", \"list\", \"watch\"]"}
        ]}}
      }
    ] and
    ($services | length) == 1 and
    ($services[0].spec.isPublic // false) == false and
    $services[0].spec.mode == "KUBERNETES" and
    $services[0].spec.port == 6443 and
    $services[0].spec.authorization.policies == ["homelab-private-kubernetes-access"] and
    $services[0].spec.config.upstream.url == "https://10.1.0.199:6443" and
    # checkov:skip=CKV_SECRET_6:Public name of an Octelium Secret, not secret data.
    $services[0].spec.config.kubernetes.kubeconfig.fromSecret == "homelab-ci-kubeconfig" and
    ($services[0].spec.config.tls.insecureSkipVerify // false) == false and
    ($talos_policies | length) == 1 and
    $talos_policies[0].spec.rules == [
      {
        "name": "operator-client",
        "effect": "ALLOW",
        "condition": {"all": {"of": [
          {"match": "ctx.user.spec.type == \"HUMAN\""},
          {"match": "ctx.session.status.type == \"CLIENT\""},
          {"match": "ctx.service.metadata.name == \"talos-api.homelab\""},
          {"match": "ctx.service.spec.mode == \"TCP\""},
          {"match": "ctx.user.metadata.name == \"homelab-owner\""}
        ]}}
      }
    ] and
    ($talos_services | length) == 1 and
    $talos_services[0].spec == {
      "displayName": "Homelab Talos API",
      "isPublic": false,
      "isTLS": false,
      "mode": "TCP",
      "port": 50000,
      "authorization": {"policies": ["homelab-private-talos-access"]},
      "config": {"upstream": {"url": "tcp://10.1.0.199:50000"}}
    } and
    ($talos_services[0].spec.config.tls // null) == null and
    ($talos_services[0].spec.config.clientCertificate // null) == null and
    ($catalog_users | length) == 1 and
    $catalog_users[0].spec == {
      "type": "WORKLOAD",
      "session": {
        "clientDuration": {"minutes": 15},
        "maxPerUser": 2
      }
    } and
    ($catalog_credentials | length) == 0
  ' >/dev/null
yq -o=json '.' docs/examples/octelium/homelab-private-kubernetes-ci-credential.yaml |
  jq -e '
    .kind == "Credential" and
    .metadata.name == "homelab-private-kubernetes-ci" and
    .spec == {
      "type": "AUTH_TOKEN",
      "user": "homelab-catalog-ci",
      "expiresAt": "1970-01-01T00:00:00Z",
      "sessionType": "CLIENT",
      "maxAuthentications": 1,
      "autoDelete": true,
      "authorization": {
        "inlinePolicies": [{
          "name": "private-kubernetes-catalog-apply",
          "spec": {
            "rules": [
              {
                "name": "deny-other-core-methods",
                "priority": -4,
                "effect": "DENY",
                "condition": {
                  "not": "ctx.user.metadata.name == \"homelab-catalog-ci\" && ctx.user.spec.type == \"WORKLOAD\" && ctx.session.status.type == \"CLIENT\" && ctx.namespace.metadata.name == \"octelium-api\" && ctx.service.metadata.name == \"default.octelium-api\" && ctx.service.spec.mode == \"GRPC\" && ctx.request.grpc.serviceFullName == \"octelium.api.main.core.v1.MainService\" && ctx.request.grpc.method in [\"ListPolicy\", \"CreatePolicy\", \"UpdatePolicy\", \"ListService\", \"CreateService\", \"UpdateService\"]"
                }
              },
              {
                "name": "required-core-methods",
                "priority": -4,
                "effect": "ALLOW",
                "condition": {
                  "match": "ctx.user.metadata.name == \"homelab-catalog-ci\" && ctx.user.spec.type == \"WORKLOAD\" && ctx.session.status.type == \"CLIENT\" && ctx.namespace.metadata.name == \"octelium-api\" && ctx.service.metadata.name == \"default.octelium-api\" && ctx.service.spec.mode == \"GRPC\" && ctx.request.grpc.serviceFullName == \"octelium.api.main.core.v1.MainService\" && ctx.request.grpc.method in [\"ListPolicy\", \"CreatePolicy\", \"UpdatePolicy\", \"ListService\", \"CreateService\", \"UpdateService\"]"
                }
              }
            ]
          }
        }]
      }
    }
  ' >/dev/null
yq -o=json '.' clusters/homelab/apps/istio/values.yaml |
  jq -e '
    .service.type == "ClusterIP" and
    .service.loadBalancerClass == null and
    (.service.annotations["tailscale.com/hostname"] // null) == null and
    (.service.annotations["homelab.rst.io/pod-security"] // "") != "tailscale-proxy-requires-privileged"
  ' >/dev/null
rg -Fq 'octeliumctl update secret "$secret_name"' scripts/octelium-ci-kubeconfig-secret.sh
if rg -Fq 'octeliumctl delete secret' scripts/octelium-ci-kubeconfig-secret.sh; then
  echo "Shared Octelium kubeconfig rotation must not delete the active Secret." >&2
  exit 1
fi
echo "::endgroup::"

echo "::group::Image digest pins"
cert_manager_values="clusters/homelab/apps/cert-manager/values-v1.20.3.yaml"
terragrunt --log-disable --working-dir IaC/live/argocd-apps/cert-manager \
  render --json --write=false --no-color \
  | jq -e '
      any(.inputs.manifest.spec.sources[];
        .repoURL == "https://charts.jetstack.io" and
        .chart == "cert-manager" and
        .targetRevision == "v1.20.3" and
        .helm.valueFiles == ["$values/clusters/homelab/apps/cert-manager/values-v1.20.3.yaml"]
      )
    ' >/dev/null
yq -o=json '.' "$cert_manager_values" \
  | jq -e '[
      .image.digest,
      .webhook.image.digest,
      .cainjector.image.digest,
      .acmesolver.image.digest,
      .startupapicheck.image.digest
    ] | all(.[]; type == "string" and test("^sha256:[0-9a-f]{64}$"))' \
    >/dev/null
tag_only_images="$(
  {
    rg -n '^\s*tag:\s*["'\'']?[^"'\''#[:space:]][^#]*$' clusters/homelab || true
    rg -n '^\s*image:\s*[^[:space:]#]+:[^@#[:space:]]+' clusters/homelab || true
  } \
    | rg -v '@sha256:' \
    || true
)"

if [[ -n "$tag_only_images" ]]; then
  echo "Container images must be pinned as tag@sha256:digest:" >&2
  printf '%s\n' "$tag_only_images" >&2
  exit 1
fi
echo "::endgroup::"

echo "::group::OpenClaw Discord plugin"
openclaw_values="clusters/homelab/apps/openclaw/values.yaml"
rg -Fq '"npm:@openclaw/discord@${openclaw_version}"' "$openclaw_values"
rg -Fq -- '--pin --force --accept-capabilities' "$openclaw_values"
rg -Fq 'openclaw plugins enable discord --accept-capabilities' "$openclaw_values"
rg -Fq 'openclaw plugins inspect discord --runtime --json |' "$openclaw_values"
rg -Fq 'plugin.get("origin") == "global"' "$openclaw_values"
rg -Fq 'plugin.get("status") == "loaded"' "$openclaw_values"
rg -Fq 'install.get("source") == "npm"' "$openclaw_values"
rg -Fq 'install.get("spec") == f"@openclaw/discord@{expected_version}"' "$openclaw_values"
rg -Fq 'install.get("version") == expected_version' "$openclaw_values"
rg -Fq 'package.get("version") == expected_version' "$openclaw_values"
rg -Fq 'for delay in 0 5 15 30' "$openclaw_values"
rg -Fq 'verify_discord_plugin installed' "$openclaw_values"
rg -Fq 'verify_discord_plugin loaded' "$openclaw_values"
rg -Fq 'tar --one-file-system' "$openclaw_values"
rg -Fq -- '--exclude=openclaw/npm' "$openclaw_values"
rg -Fq -- '--exclude=openclaw/extensions' "$openclaw_values"
rg -Fq 'verify_backup_dir "$backup_dir"' "$openclaw_values"
rg -Fq 'required_kib=$((state_kib * 2 + 2097152))' "$openclaw_values"
[[ "$(rg -Fc 'openclaw doctor --session-sqlite inspect' "$openclaw_values")" -eq 2 ]]
rg -Fq 'openclaw doctor --session-sqlite dry-run' "$openclaw_values"
rg -Fq 'openclaw doctor --session-sqlite import' "$openclaw_values"
if rg -Fq 'openclaw doctor --fix' "$openclaw_values" ||
  rg -Fq 'openclaw doctor --session-sqlite validate' "$openclaw_values"; then
  echo "OpenClaw bootstrap contains an unsafe or ineffective doctor repair" >&2
  exit 1
fi
rg -Fq '"maxConcurrent": 4' "$openclaw_values"
if [[ "$(rg -Fc 'openclaw plugins install ' "$openclaw_values")" -ne 1 ]] ||
  rg -q 'falling back|current_discord_plugin_spec|clawhub:@openclaw/discord|plugin\.get\("origin"\) == "bundled"' "$openclaw_values"; then
  echo "OpenClaw Discord bootstrap must use only the exact external plugin version" >&2
  exit 1
fi
if ! awk '
  /tar --one-file-system/ && !backup { backup = NR }
  /^[[:space:]]+verify_backup_dir "\$backup_dir"[[:space:]]*$/ && !backup_verified { backup_verified = NR }
  /--pin --force --accept-capabilities/ && !install { install = NR }
  /--session-sqlite inspect/ && !inspect_before { inspect_before = NR; next }
  /--session-sqlite inspect/ && !inspect_after { inspect_after = NR }
  /--session-sqlite dry-run/ && !dry_run { dry_run = NR }
  /--session-sqlite import/ && !import { import = NR }
  /openclaw config validate/ && !config_validate { config_validate = NR }
  END {
    exit !(backup && backup_verified && install && inspect_before && dry_run && import &&
      inspect_after && config_validate && backup < backup_verified &&
      backup_verified < install &&
      install < inspect_before && inspect_before < dry_run &&
      dry_run < import && import < inspect_after &&
      inspect_after < config_validate)
  }
' "$openclaw_values"; then
  echo "OpenClaw must back up, install Discord, migrate, then validate persisted state" >&2
  exit 1
fi
yq -e '
  .controllers.openclaw.initContainers."bootstrap-config".image.tag == "2026.8.2@sha256:5d25165995041caa6a7175bec82b25ad98c44eb269bb42435da8e27ec06e6be4" and
  .controllers.openclaw.initContainers."bootstrap-config".dependsOn == "00-operator-toolbox" and
  .controllers.openclaw.initContainers."00-operator-toolbox" != null and
  .controllers.openclaw.containers.app.image.tag == "2026.8.2@sha256:5d25165995041caa6a7175bec82b25ad98c44eb269bb42435da8e27ec06e6be4" and
  .controllers.openclaw.containers.proxy.image.tag == "2026.8.2@sha256:5d25165995041caa6a7175bec82b25ad98c44eb269bb42435da8e27ec06e6be4" and
  .controllers.openclaw.strategy == "Recreate" and
  .controllers.openclaw.containers.app.probes.liveness.spec.failureThreshold == 36 and
  .controllers.openclaw.containers.app.probes.liveness.spec.periodSeconds == 10 and
  .controllers.openclaw.containers.app.probes.liveness.spec.timeoutSeconds == 3 and
  .controllers.openclaw.initContainers."bootstrap-config".env.OPENCLAW_SUPERVISOR_MODE == "external" and
  .controllers.openclaw.initContainers."bootstrap-config".env.OPENCLAW_SERVICE_REPAIR_POLICY == "external" and
  .controllers.openclaw.initContainers."bootstrap-config".env.OPENCLAW_NO_AUTO_UPDATE == "1" and
  .controllers.openclaw.containers.app.env.OPENCLAW_SUPERVISOR_MODE == "external" and
  .controllers.openclaw.containers.app.env.OPENCLAW_NO_AUTO_UPDATE == "1" and
  .controllers.openclaw.initContainers."bootstrap-config".env.LITELLM_TOKEN == null and
  .controllers.openclaw.initContainers."bootstrap-config".env.GRAFANA_USERNAME == null and
  .controllers.openclaw.initContainers."bootstrap-config".env.GRAFANA_PASSWORD == null and
  .controllers.openclaw.initContainers."bootstrap-config".env.GITHUB_APP_ID == null and
  .controllers.openclaw.initContainers."bootstrap-config".env.GITHUB_APP_INSTALLATION_ID == null and
  .controllers.openclaw.containers.app.env.GRAFANA_ALERT_HOOK_TOKEN == null and
  .persistence.config.advancedMounts.openclaw.proxy == null and
  .persistence."github-app-private-key".advancedMounts.openclaw."bootstrap-config" == null
' "$openclaw_values" >/dev/null
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

echo "::group::Credential rotation script"
bash -n scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'set +x' scripts/rotate-external-secrets-aws-key.sh
rg -Fq -- '--cli-input-json "file://$1"' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'KUBECONFIG must be unset' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'f83fb4e86c60ea695e6d7d951d5bfef2ea52a33c87707e5f6e540050d9aa8bce' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'actual_kubernetes_insecure_skip_tls_verify' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'json_excludes_new_credentials' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'ambient_aws_variables' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'live-secret-before.json' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'probe_controller_key "$old_key_id" "$old_secret_access_key" old-key' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'probe_controller_key "$new_access_key_id" "$new_secret_access_key" new-key' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'DenyTemporarySessionCredentials' scripts/rotate-external-secrets-aws-key.sh
rg -Fq '"Bool": {"aws:ViaAWSService": "false"}' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'probe_temporary_session_denied' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'duration-seconds 900' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'new-parameters.json' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'cleanup_uncertain_created_key' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'delete_access_key_safely' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'AWS_IGNORE_CONFIGURED_ENDPOINT_URLS=true' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'acquire_rotation_lock' scripts/rotate-external-secrets-aws-key.sh
rg -Fq 'release_rotation_lock' scripts/rotate-external-secrets-aws-key.sh
echo "::endgroup::"

echo "::group::Whitespace"
git diff --check
echo "::endgroup::"
