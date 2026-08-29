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
(
  cd IaC/operator/github-actions-role-policy
  terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
  terragrunt --log-disable validate -no-color
)
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
      "path": "clusters/homelab/apps/cordium-bootstrap",
      "kustomize": {}
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
    (.on | keys) == ["pull_request"] and
    .on.pull_request.types == ["opened", "synchronize", "reopened", "ready_for_review"] and
    .on.pull_request.paths == null and
    (.jobs | keys | sort) == ["static-policy", "terragrunt-gate", "terragrunt-plan", "terragrunt-plan-skipped"] and
    .jobs["static-policy"].permissions == {"contents": "read"} and
    .jobs["static-policy"].steps[0].with["fetch-depth"] == 0 and
    .jobs["static-policy"].outputs["requires-live-plan"] == "${{ steps.live-plan-scope.outputs.requires-live-plan }}" and
    ($scope | length) == 1 and
    $scope[0].env.BASE_REF == "${{ github.base_ref }}" and
    ($scope[0].run |
      contains("git diff --name-only \"origin/${BASE_REF}...HEAD\"") and
      contains(".github/workflows/terragrunt-plan.yml") and
      contains("IaC/*|flake.nix|flake.lock|policy/kubernetes.rego|policy/terraform.rego") and
      contains("scripts/ci/terragrunt-*") and
      contains("requires-live-plan=${requires_live_plan}")) and
    ($conftest | length) == 1 and
    .jobs["terragrunt-plan"].needs == ["static-policy"] and
    (.jobs["terragrunt-plan"].if |
      contains("github.event.pull_request.head.repo.full_name == github.repository") and
      contains("needs.static-policy.outputs.requires-live-plan == '\''true'\''")) and
    .jobs["terragrunt-plan"].environment == {"name": "homelab-plan"} and
    .jobs["terragrunt-plan"].permissions == {
      "contents": "read",
      "id-token": "write",
      "pull-requests": "write"
    } and
    .jobs["terragrunt-plan-skipped"].needs == ["static-policy"] and
    (.jobs["terragrunt-plan-skipped"].if |
      contains("github.event.pull_request.head.repo.full_name == github.repository") and
      contains("needs.static-policy.outputs.requires-live-plan != '\''true'\''")) and
    .jobs["terragrunt-plan-skipped"].environment == null and
    .jobs["terragrunt-plan-skipped"].permissions == {
      "contents": "read",
      "pull-requests": "write"
    } and
    ([.jobs | to_entries[] | select(.value.environment != null) | .key]) == ["terragrunt-plan"] and
    .jobs["terragrunt-gate"].if == "${{ always() }}" and
    .jobs["terragrunt-gate"].needs == ["static-policy", "terragrunt-plan", "terragrunt-plan-skipped"] and
    .jobs["terragrunt-gate"].permissions == {} and
    .jobs["terragrunt-gate"].environment == null and
    (.jobs["terragrunt-gate"] | tostring | contains("secrets") | not) and
    (.jobs["terragrunt-gate"].steps | length) == 1 and
    (.jobs["terragrunt-gate"].steps[0].run |
      contains("test \"${STATIC_RESULT}\" = \"success\"") and
      contains("test \"${LIVE_PLAN_RESULT}\" = \"success\"") and
      contains("test \"${LIVE_PLAN_RESULT}\" = \"skipped\""))
  ' >/dev/null
echo "::endgroup::"

echo "::group::Exact workflow dispatch commits"
for workflow_job in \
  '.github/workflows/homelab-diagnostics.yml:grafana' \
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
      "APPLY_HEAD_SHA",
      "TERRAGRUNT_ARGOCD_APP",
      "TERRAGRUNT_REPAIR_ARGOCD_APP_STATE"
    ] and
    (.jobs["terragrunt-apply"].env | tostring | contains("secrets") | not) and
    .jobs["terragrunt-apply"].env.TERRAGRUNT_ARGOCD_APP == "${{ inputs.argocd_app }}" and
    .jobs["terragrunt-apply"].env.TERRAGRUNT_REPAIR_ARGOCD_APP_STATE == "${{ inputs.repair_argocd_app_state }}" and
    .jobs["terragrunt-apply"].concurrency == {
      "group": "terragrunt-apply-production",
      "cancel-in-progress": false,
      "queue": "single"
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
    (.jobs["terragrunt-apply"].steps[] | select(.name == "Resolve Last Successful Apply").run |
      contains("--paginate --slurp") and
      contains("branch=main&status=success&per_page=100") and
      contains(".event == \"push\"") and
      contains(".event == \"workflow_dispatch\"") and
      contains("startswith(\"Full @ \")") and
      contains("max_by(.run_number)"))
  ' >/dev/null
bash -n scripts/ci/terragrunt-apply.sh
rg -Fq 'terragrunt run -- untaint -no-color kubernetes_manifest.this' scripts/ci/terragrunt-apply.sh
echo "::endgroup::"

echo "::group::Renovate config"
jq empty renovate.json
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

echo "::group::OpenClaw plugin supply chain"
openclaw_values="clusters/homelab/apps/openclaw/values.yaml"
rg -Fq 'openclaw plugins inspect discord --json' "$openclaw_values"
rg -Fq 'plugin.get("origin") == "bundled"' "$openclaw_values"
rg -Fq 'package.get("version") == expected' "$openclaw_values"
rg -Fq 'openclaw plugins inspect discord --runtime --json' "$openclaw_values"
if rg -q 'plugins install|falling back|current_discord_plugin_spec|clawhub:@openclaw/discord|npm:@openclaw/discord' "$openclaw_values"; then
  echo "OpenClaw Discord bootstrap must use only the exact image-bundled plugin" >&2
  exit 1
fi
yq -e '
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
bash scripts/ci/secret-scan.sh
echo "::endgroup::"

echo "::group::Checkov"
if command -v checkov >/dev/null 2>&1; then
  checkov --config-file .checkov.yaml --framework terraform --directory IaC/modules
  checkov --config-file .checkov.yaml --framework kubernetes --directory clusters
  checkov --config-file .checkov.yaml --framework secrets --directory .
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
