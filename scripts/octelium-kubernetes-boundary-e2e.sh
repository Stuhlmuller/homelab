#!/usr/bin/env bash
set -euo pipefail

DOMAIN="stinkyboi.com"
ROLE=""
KUBECONFIG_PATH=""
KUBE_CONTEXT=""
EVIDENCE_DIR=""
NAMESPACE="cordium"
REQUEST_TIMEOUT="15s"
STATUS_TIMEOUT_SECONDS=15
EXPECTED_KUBE_CLUSTER="kubernetes"
EXPECTED_KUBE_USER="kubernetes-admin"
EXPECTED_KUBE_CONTEXT="kubernetes-admin@kubernetes"
# checkov:skip=CKV_SECRET_6:Public Octelium v0.35 placeholder prefix, not secret material.
EXPECTED_KUBE_TOKEN_PREFIX="dummy-token-authenticated-by"
EXPECTED_KUBE_TOKEN="${EXPECTED_KUBE_TOKEN_PREFIX}-octelium-session"

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-kubernetes-boundary-e2e.sh \
  --role cordium|owner --kubeconfig PATH --evidence-dir ABSOLUTE_PATH [options]

Run the live Octelium Kubernetes authorization matrix through an already-active
HUMAN/CLIENT session. Run the cordium role inside a homelab-cordium-user
Workspace and the owner role from a homelab-owner operator session. The script
does not log in, create credentials, apply catalog state, or mutate Kubernetes.

Options:
  --role ROLE             Required identity role: cordium or owner.
  --kubeconfig PATH       Required Octelium-generated kubeconfig.
  --context NAME          Optional; must be kubernetes-admin@kubernetes.
  --evidence-dir PATH     Required empty private directory outside this repo.
  --domain DOMAIN         Octelium Cluster domain. Default: stinkyboi.com.
  --namespace NAME        Cordium namespace. Default: cordium.
  -h, --help              Show this help.
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --role)
      [ "$#" -ge 2 ] || die "--role requires a value"
      ROLE="$2"
      shift 2
      ;;
    --kubeconfig)
      [ "$#" -ge 2 ] || die "--kubeconfig requires a value"
      KUBECONFIG_PATH="$2"
      shift 2
      ;;
    --context)
      [ "$#" -ge 2 ] || die "--context requires a value"
      KUBE_CONTEXT="$2"
      shift 2
      ;;
    --evidence-dir)
      [ "$#" -ge 2 ] || die "--evidence-dir requires a value"
      EVIDENCE_DIR="$2"
      shift 2
      ;;
    --domain)
      [ "$#" -ge 2 ] || die "--domain requires a value"
      DOMAIN="$2"
      shift 2
      ;;
    --namespace)
      [ "$#" -ge 2 ] || die "--namespace requires a value"
      NAMESPACE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

case "${ROLE}" in
  cordium)
    EXPECTED_USER="homelab-cordium-user"
    ;;
  owner)
    EXPECTED_USER="homelab-owner"
    ;;
  *)
    die "--role must be cordium or owner"
    ;;
esac

if [ -z "${KUBE_CONTEXT}" ]; then
  KUBE_CONTEXT="${EXPECTED_KUBE_CONTEXT}"
elif [ "${KUBE_CONTEXT}" != "${EXPECTED_KUBE_CONTEXT}" ]; then
  die "--context must be ${EXPECTED_KUBE_CONTEXT} for an Octelium v0.35 kubeconfig"
fi

if [ "${#NAMESPACE}" -gt 63 ] ||
  ! [[ "${NAMESPACE}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
  die "--namespace must be a Kubernetes DNS label"
fi

[ -f "${KUBECONFIG_PATH}" ] || die "kubeconfig is missing: ${KUBECONFIG_PATH:-<unset>}"
case "${EVIDENCE_DIR}" in
  /*) ;;
  *) die "--evidence-dir must be an absolute path" ;;
esac

for required_command in git jq kubectl octelium; do
  command -v "${required_command}" >/dev/null 2>&1 || die "missing required command: ${required_command}"
done
if [ "${CI:-}" = "true" ] || [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  die "live HUMAN identity evidence must not run in CI"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel)"
if ! REPO_STATUS="$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=normal)"; then
  die "could not inspect repository checkout state"
fi
if [ -n "${REPO_STATUS}" ]; then
  die "repository checkout must be clean before collecting evidence"
fi
BOUNDARY_SCRIPT_PATH="${REPO_ROOT}/scripts/octelium-kubernetes-boundary-e2e.sh"
CATALOG_PATH="${REPO_ROOT}/docs/examples/octelium/homelab-services.yaml"
[ -f "${CATALOG_PATH}" ] || die "catalog is missing: ${CATALOG_PATH}"
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
  die "missing required command: sha256sum or shasum"
fi
umask 077
mkdir -p -- "${EVIDENCE_DIR}"
EVIDENCE_DIR="$(cd "${EVIDENCE_DIR}" && pwd -P)"
case "${EVIDENCE_DIR}/" in
  "${REPO_ROOT}/"*) die "evidence directory must be outside the repository" ;;
esac
if [ -n "$(ls -A "${EVIDENCE_DIR}")" ]; then
  die "evidence directory must be empty: ${EVIDENCE_DIR}"
fi
chmod 0700 "${EVIDENCE_DIR}"

SUMMARY_FILE="${EVIDENCE_DIR}/summary.tsv"
IDENTITY_EVIDENCE="${EVIDENCE_DIR}/identity.json"
KUBECONFIG_EVIDENCE="${EVIDENCE_DIR}/kubeconfig.json"
CHECKS=0
FAILURES=0
LAST_STDOUT=""

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -- "$1" | awk '{print $1}'
  else
    shasum -a 256 -- "$1" | awk '{print $1}'
  fi
}

if ! SCRIPT_SHA256="$(sha256_file "${BOUNDARY_SCRIPT_PATH}")" ||
  ! CATALOG_SHA256="$(sha256_file "${CATALOG_PATH}")"; then
  die "could not digest the boundary script and catalog"
fi
if ! [[ "${SCRIPT_SHA256}" =~ ^[0-9a-f]{64}$ ]] ||
  ! [[ "${CATALOG_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
  die "invalid SHA-256 digest output"
fi

printf 'id\trole\texpectation\tresult\texit_code\tcheck\n' >"${SUMMARY_FILE}"
printf 'started_at\t%s\nrole\t%s\nexpected_user\t%s\ndomain\t%s\nnamespace\t%s\nrepository_commit\t%s\nscript_sha256\t%s\ncatalog_sha256\t%s\n' \
  "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${ROLE}" "${EXPECTED_USER}" "${DOMAIN}" "${NAMESPACE}" \
  "$(git -C "${REPO_ROOT}" rev-parse HEAD)" "${SCRIPT_SHA256}" "${CATALOG_SHA256}" \
  >"${EVIDENCE_DIR}/metadata.tsv"

pass() {
  printf 'PASS: %s\n' "$*"
}

fail() {
  FAILURES=$((FAILURES + 1))
  printf 'FAIL: %s\n' "$*" >&2
}

kubectl_boundary() (
  local args=(--kubeconfig "${KUBECONFIG_PATH}" --context "${KUBE_CONTEXT}" --request-timeout="${REQUEST_TIMEOUT}")
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
  kubectl "${args[@]}" "$@"
)

octelium_status() {
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
  export OCTELIUM_CONTAINER_MODE=true
  exec octelium status --domain "${DOMAIN}" -o json
}

run_with_timeout() {
  local timeout_seconds="$1" command_pid remaining_ticks exit_code
  shift

  "$@" &
  command_pid="$!"
  remaining_ticks=$((timeout_seconds * 10))
  while kill -0 "${command_pid}" 2>/dev/null; do
    if [ "${remaining_ticks}" -eq 0 ]; then
      kill -KILL "${command_pid}" 2>/dev/null || true
      wait "${command_pid}" 2>/dev/null || true
      return 124
    fi
    sleep 0.1
    remaining_ticks=$((remaining_ticks - 1))
  done
  if wait "${command_pid}"; then
    exit_code=0
  else
    exit_code=$?
  fi
  return "${exit_code}"
}

sanitize_denial() {
  awk '
    $0 == "Error from server (Forbidden): Octelium: Unauthorized request" { canonical = 1 }
    END {
      printf "octelium_forbidden_status\t%s\n", canonical ? "true" : "false"
    }
  '
}

run_check() {
  local expectation="$1" label="$2" slug output error denial exit_code filter_exit result detail
  local -a pipeline_status
  shift 2

  CHECKS=$((CHECKS + 1))
  printf -v slug '%03d-%s' "${CHECKS}" "$(printf '%s' "${label}" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '-')"
  slug="${slug%-}"
  output="${EVIDENCE_DIR}/${slug}.out"
  error="${EVIDENCE_DIR}/${slug}.err"
  denial="${EVIDENCE_DIR}/${slug}.denial.tsv"
  detail="inspect ${output} and ${error}"
  if [ "${expectation}" = "octelium-denied" ]; then
    set +e
    "$@" 2>&1 | sanitize_denial >"${denial}"
    pipeline_status=("${PIPESTATUS[@]}")
    set -e
    exit_code="${pipeline_status[0]}"
    filter_exit="${pipeline_status[1]}"
    detail="inspect ${denial}"
  elif "$@" >"${output}" 2>"${error}"; then
    exit_code=0
  else
    exit_code=$?
  fi

  result="FAIL"
  case "${expectation}" in
    allowed)
      if [ "${exit_code}" -eq 0 ]; then
        result="PASS"
      fi
      ;;
    allowed-yes)
      if [ "${exit_code}" -eq 0 ] && grep -Fxq 'yes' "${output}"; then
        result="PASS"
      fi
      ;;
    octelium-denied)
      if [ "${filter_exit}" -eq 0 ] && [ "${exit_code}" -ne 0 ] &&
        grep -Fxq $'octelium_forbidden_status\ttrue' "${denial}"; then
        result="PASS"
      fi
      ;;
    *)
      die "unsupported check expectation: ${expectation}"
      ;;
  esac

  printf '%03d\t%s\t%s\t%s\t%s\t%s\n' \
    "${CHECKS}" "${ROLE}" "${expectation}" "${result}" "${exit_code}" "${label}" >>"${SUMMARY_FILE}"
  if [ "${expectation}" != "octelium-denied" ]; then
    LAST_STDOUT="${output}"
  fi
  if [ "${result}" = "PASS" ]; then
    pass "${label}"
  else
    fail "${label}; ${detail}"
  fi
}

finish() {
  printf 'completed_at\t%s\nchecks\t%s\nfailures\t%s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${CHECKS}" "${FAILURES}" >>"${EVIDENCE_DIR}/metadata.tsv"
  if [ "${FAILURES}" -gt 0 ]; then
    printf 'Octelium Kubernetes boundary check failed with %s failure(s). Private evidence: %s\n' \
      "${FAILURES}" "${EVIDENCE_DIR}" >&2
    return 1
  fi
  printf 'Octelium Kubernetes boundary check passed. Private evidence: %s\n' "${EVIDENCE_DIR}"
}

EXPECTED_KUBE_SERVER="https://kubernetes-api.homelab.local.${DOMAIN}:6443"
if kubectl_boundary config view --raw -o json 2>/dev/null |
  jq -e \
    --arg server "${EXPECTED_KUBE_SERVER}" \
    --arg cluster "${EXPECTED_KUBE_CLUSTER}" \
    --arg user "${EXPECTED_KUBE_USER}" \
    --arg context "${EXPECTED_KUBE_CONTEXT}" \
    --arg token "${EXPECTED_KUBE_TOKEN}" \
    '
      select(
        .apiVersion == "v1" and
        .kind == "Config" and
        .preferences == null and
        (keys | sort) == (["apiVersion", "kind", "clusters", "users", "contexts", "current-context"] | sort) and
        .["current-context"] == $context and
        (.clusters | length) == 1 and
        (.clusters[0] | keys | sort) == (["name", "cluster"] | sort) and
        .clusters[0].name == $cluster and
        (.clusters[0].cluster | keys) == ["server"] and
        .clusters[0].cluster.server == $server and
        (.users | length) == 1 and
        (.users[0] | keys | sort) == (["name", "user"] | sort) and
        .users[0].name == $user and
        (.users[0].user | keys) == ["token"] and
        .users[0].user.token == $token and
        (.contexts | length) == 1 and
        (.contexts[0] | keys | sort) == (["name", "context"] | sort) and
        .contexts[0].name == $context and
        (.contexts[0].context | keys | sort) == (["cluster", "user"] | sort) and
        .contexts[0].context.cluster == $cluster and
        .contexts[0].context.user == $user
      ) |
      {server: .clusters[0].cluster.server, context: .["current-context"], usesOcteliumSessionPlaceholder: true}
    ' >"${KUBECONFIG_EVIDENCE}"; then
  pass "supplied kubeconfig matches the Octelium v0.35 session config"
else
  rm -f -- "${KUBECONFIG_EVIDENCE}"
  fail "supplied kubeconfig does not match the exact Octelium v0.35 session config"
  finish || true
  exit 1
fi

if run_with_timeout "${STATUS_TIMEOUT_SECONDS}" octelium_status 2>/dev/null |
  jq -e \
    --arg domain "${DOMAIN}" \
    --arg user "${EXPECTED_USER}" \
    'select(
       .domain == $domain and
       .user.metadata.name == $user and
       .user.spec.type == "HUMAN" and
       .session.status.type == "CLIENT" and
       .session.status.isConnected == true
     ) |
     {domain, user: .user.metadata.name, userType: .user.spec.type,
      sessionType: .session.status.type, isConnected: .session.status.isConnected}' \
    >"${IDENTITY_EVIDENCE}"; then
  pass "active ${EXPECTED_USER} HUMAN/CLIENT identity"
else
  rm -f -- "${IDENTITY_EVIDENCE}"
  fail "active identity is not connected ${EXPECTED_USER} HUMAN/CLIENT"
  finish || true
  exit 1
fi

printf -v PROBE_ID '%05d%05d%05d' "${RANDOM}" "${RANDOM}" "${RANDOM}"
PROBE_NAME="octelium-boundary-${PROBE_ID}"
PROBE_SELECTOR="octelium-boundary-probe%3D${PROBE_ID}"
CONFIGMAP_JSON="${EVIDENCE_DIR}/configmap.json"
DELETE_OPTIONS_JSON="${EVIDENCE_DIR}/delete-options.json"
SSAR_JSON="${EVIDENCE_DIR}/self-subject-access-review.json"
INVALID_JSON="${EVIDENCE_DIR}/invalid.json"
printf '%s\n' \
  "{\"apiVersion\":\"v1\",\"kind\":\"ConfigMap\",\"metadata\":{\"name\":\"${PROBE_NAME}\",\"namespace\":\"${NAMESPACE}\"},\"data\":{\"probe\":\"dry-run-only\"}}" \
  >"${CONFIGMAP_JSON}"
printf '%s\n' '{"apiVersion":"v1","kind":"DeleteOptions","dryRun":["All"]}' >"${DELETE_OPTIONS_JSON}"
printf '%s\n' \
  "{\"apiVersion\":\"authorization.k8s.io/v1\",\"kind\":\"SelfSubjectAccessReview\",\"spec\":{\"resourceAttributes\":{\"namespace\":\"${NAMESPACE}\",\"verb\":\"get\",\"resource\":\"pods\"}}}" \
  >"${SSAR_JSON}"
printf '%s\n' '{"apiVersion":"invalid.homelab/v1","kind":"Invalid"}' >"${INVALID_JSON}"

if [ "${ROLE}" = "cordium" ]; then
  for path in /api /api/v1 /apis /apis/apps/v1 /apis/batch/v1; do
    run_check allowed "allowed discovery ${path}" kubectl_boundary get --raw="${path}"
  done

  for resource in events pods services daemonsets.apps deployments.apps replicasets.apps statefulsets.apps cronjobs.batch jobs.batch; do
    run_check allowed "allowed list ${resource}" kubectl_boundary -n "${NAMESPACE}" get "${resource}" -o name
  done

  run_check allowed "allowed list pods for exact probe" kubectl_boundary -n "${NAMESPACE}" get pods -o name
  POD_NAME="$(sed -n 's#^pod/##p' "${LAST_STDOUT}" | head -1)"
  if [ -z "${POD_NAME}" ]; then
    fail "allowed exact get needs a running Pod in ${NAMESPACE}"
  else
    run_check allowed "allowed get exact pod" kubectl_boundary -n "${NAMESPACE}" get pod "${POD_NAME}" -o name
  fi
  run_check allowed "allowed watch pods" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/pods?watch=true&timeoutSeconds=1"

  run_check octelium-denied "deny all-namespaces pod list" kubectl_boundary get \
    --raw="/api/v1/pods?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny Namespaces" kubectl_boundary get \
    --raw="/api/v1/namespaces?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny secret get" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/secrets/${PROBE_NAME}"
  run_check octelium-denied "deny secret list" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/secrets?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny secret watch" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/secrets?watch=true&timeoutSeconds=1&labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny ConfigMaps" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/configmaps?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny service accounts" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/serviceaccounts?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny namespaced Roles" kubectl_boundary get \
    --raw="/apis/rbac.authorization.k8s.io/v1/namespaces/${NAMESPACE}/roles?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny namespaced RoleBindings" kubectl_boundary get \
    --raw="/apis/rbac.authorization.k8s.io/v1/namespaces/${NAMESPACE}/rolebindings?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny ClusterRoles" kubectl_boundary get \
    --raw="/apis/rbac.authorization.k8s.io/v1/clusterroles?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny ClusterRoleBindings" kubectl_boundary get \
    --raw="/apis/rbac.authorization.k8s.io/v1/clusterrolebindings?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny Nodes" kubectl_boundary get \
    --raw="/api/v1/nodes?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny PersistentVolumes" kubectl_boundary get \
    --raw="/api/v1/persistentvolumes?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny PersistentVolumeClaims" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/persistentvolumeclaims?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny Endpoints" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/endpoints?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny EndpointSlices" kubectl_boundary get \
    --raw="/apis/discovery.k8s.io/v1/namespaces/${NAMESPACE}/endpointslices?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny CustomResourceDefinitions" kubectl_boundary get \
    --raw="/apis/apiextensions.k8s.io/v1/customresourcedefinitions?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny existing custom resources" kubectl_boundary get \
    --raw="/apis/argoproj.io/v1alpha1/namespaces/argocd/applications?labelSelector=${PROBE_SELECTOR}"
  run_check octelium-denied "deny authorization reviews" kubectl_boundary create \
    --raw="/apis/authorization.k8s.io/v1/selfsubjectaccessreviews?dryRun=All" -f "${SSAR_JSON}"
  run_check octelium-denied "deny unknown future resources" kubectl_boundary get \
    --raw="/apis/unknown.homelab.invalid/v1/namespaces/${NAMESPACE}/widgets"

  run_check octelium-denied "deny pod log subresource" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/pods/${PROBE_NAME}/log"
  run_check octelium-denied "deny pod exec subresource" kubectl_boundary create \
    --raw="/api/v1/namespaces/${NAMESPACE}/pods/${PROBE_NAME}/exec?dryRun=All" -f "${INVALID_JSON}"
  run_check octelium-denied "deny pod attach subresource" kubectl_boundary create \
    --raw="/api/v1/namespaces/${NAMESPACE}/pods/${PROBE_NAME}/attach?dryRun=All" -f "${INVALID_JSON}"
  run_check octelium-denied "deny pod proxy subresource" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/pods/${PROBE_NAME}/proxy"
  run_check octelium-denied "deny service proxy subresource" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/services/${PROBE_NAME}/proxy"
  run_check octelium-denied "deny pod port-forward subresource" kubectl_boundary create \
    --raw="/api/v1/namespaces/${NAMESPACE}/pods/${PROBE_NAME}/portforward?dryRun=All" -f "${INVALID_JSON}"
  run_check octelium-denied "deny service-account token subresource" kubectl_boundary create \
    --raw="/api/v1/namespaces/${NAMESPACE}/serviceaccounts/${PROBE_NAME}/token?dryRun=All" -f "${INVALID_JSON}"
  run_check octelium-denied "deny status subresource" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/pods/${PROBE_NAME}/status"
  run_check octelium-denied "deny unknown subresources" kubectl_boundary get \
    --raw="/api/v1/namespaces/${NAMESPACE}/pods/${PROBE_NAME}/future"

  run_check octelium-denied "deny create verb" kubectl_boundary create \
    --raw="/api/v1/namespaces/${NAMESPACE}/configmaps?dryRun=All" -f "${CONFIGMAP_JSON}"
  run_check octelium-denied "deny update verb" kubectl_boundary replace \
    --raw="/api/v1/namespaces/${NAMESPACE}/configmaps/${PROBE_NAME}?dryRun=All" -f "${CONFIGMAP_JSON}"
  run_check octelium-denied "deny patch verb" kubectl_boundary -n "${NAMESPACE}" patch \
    configmap "${PROBE_NAME}" --type=merge -p '{"data":{"probe":"dry-run-only"}}' --dry-run=server
  run_check octelium-denied "deny delete verb" kubectl_boundary delete \
    --raw="/api/v1/namespaces/${NAMESPACE}/configmaps/${PROBE_NAME}?dryRun=All" -f "${DELETE_OPTIONS_JSON}"
  run_check octelium-denied "deny deletecollection verb" kubectl_boundary delete \
    --raw="/api/v1/namespaces/${NAMESPACE}/configmaps?dryRun=All&labelSelector=${PROBE_SELECTOR}" -f "${DELETE_OPTIONS_JSON}"

  run_check octelium-denied "deny future apps version" kubectl_boundary get \
    --raw="/apis/apps/v2/namespaces/${NAMESPACE}/deployments?labelSelector=${PROBE_SELECTOR}"

  run_check octelium-denied "deny metrics non-resource path" kubectl_boundary get --raw=/metrics
  run_check octelium-denied "deny debug non-resource path" kubectl_boundary get --raw=/debug/pprof/
  run_check octelium-denied "deny readyz non-resource path" kubectl_boundary get --raw=/readyz
  run_check octelium-denied "deny OpenAPI non-resource path" kubectl_boundary get --raw=/openapi/v3
  run_check octelium-denied "deny version non-resource path" kubectl_boundary get --raw=/version
  run_check octelium-denied "deny non-GET discovery" kubectl_boundary create --raw="/api?dryRun=All" -f "${INVALID_JSON}"
else
  run_check allowed "owner discovery" kubectl_boundary get --raw=/apis
  run_check allowed "owner list pods" kubectl_boundary -n "${NAMESPACE}" get pods -o name
  POD_NAME="$(sed -n 's#^pod/##p' "${LAST_STDOUT}" | head -1)"
  if [ -z "${POD_NAME}" ]; then
    fail "owner exact get needs a running Pod in ${NAMESPACE}"
  else
    run_check allowed "owner get exact pod" kubectl_boundary -n "${NAMESPACE}" get pod "${POD_NAME}" -o name
    run_check allowed "owner watch pods" kubectl_boundary get \
      --raw="/api/v1/namespaces/${NAMESPACE}/pods?watch=true&timeoutSeconds=1"
  fi
  for resource in secrets configmaps serviceaccounts roles.rbac.authorization.k8s.io; do
    run_check allowed "owner list ${resource}" kubectl_boundary -n "${NAMESPACE}" get "${resource}" -o name
  done
  for resource in nodes persistentvolumes customresourcedefinitions.apiextensions.k8s.io clusterroles.rbac.authorization.k8s.io; do
    run_check allowed "owner list ${resource}" kubectl_boundary get "${resource}" -o name
  done
  run_check allowed "owner list custom resources" kubectl_boundary -n argocd get applications.argoproj.io -o name
  run_check allowed-yes "owner authorization review" kubectl_boundary auth can-i get pods -n "${NAMESPACE}"
  run_check allowed "owner metrics non-resource path" kubectl_boundary get --raw=/metrics
  run_check allowed "owner dry-run create" kubectl_boundary create -f "${CONFIGMAP_JSON}" --dry-run=server -o name
fi

finish
