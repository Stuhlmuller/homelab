#!/usr/bin/env bash
set -euo pipefail

log_args() {
  [ -n "${BOUNDARY_FIXTURE_LOG:-}" ] || return
  {
    printf '%s' "$(basename "$0")"
    printf '\t%s' "$@"
    printf '\n'
  } >>"${BOUNDARY_FIXTURE_LOG}"
}

assert_proxy_env_clean() {
  if env | grep -Eq '^(HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|http_proxy|https_proxy|all_proxy)='; then
    printf 'proof command inherited proxy environment\n' >&2
    exit 65
  fi
}

assert_octelium_auth_env() {
  if env | grep -Eq '^(OCTELIUM_AUTH_TOKEN|OCTELIUM_AUTH_ASSERTION|OCTELIUM_ACCESS_TOKEN)='; then
    printf 'identity command inherited an Octelium credential override\n' >&2
    exit 65
  fi
  case "${BOUNDARY_FIXTURE_ROLE}" in
    cordium)
      [ "${OCTELIUM_AUTH_PROXY_SOCKET:-}" = "/var/run/octelium-proxy.sock" ] || {
        printf 'Cordium identity command did not use its exact auth proxy socket\n' >&2
        exit 65
      }
      ;;
    owner)
      [ -z "${OCTELIUM_AUTH_PROXY_SOCKET:-}" ] || {
        printf 'owner identity command inherited an auth proxy socket\n' >&2
        exit 65
      }
      ;;
  esac
}

fake_octelium() {
  local user="homelab-${BOUNDARY_FIXTURE_ROLE}-user" user_type="HUMAN" session_type="CLIENT" connected="true"
  assert_proxy_env_clean
  assert_octelium_auth_env
  [ "${OCTELIUM_CONTAINER_MODE:-}" = "true" ] || {
    printf 'BROWSER_LOGIN_SENTINEL\n' >&2
    exit 65
  }
  [ "${BOUNDARY_FIXTURE_ROLE}" = "owner" ] && user="homelab-owner"
  case "${BOUNDARY_FIXTURE_IDENTITY:-valid}" in
    valid) ;;
    wrong-user) user="wrong-user" ;;
    workload) user_type="WORKLOAD" ;;
    clientless) session_type="CLIENTLESS" ;;
    disconnected) connected="false" ;;
    missing|expired)
      printf 'authentication required in workload mode\n' >&2
      return 1
      ;;
    hang)
      exec sleep 30
      ;;
    *) exit 64 ;;
  esac
  log_args "$@"
  printf '%s\n' \
    "{\"domain\":\"${BOUNDARY_FIXTURE_DOMAIN}\",\"rawOnly\":\"SENSITIVE_IDENTITY_RAW_SENTINEL\",\"user\":{\"metadata\":{\"name\":\"${user}\"},\"spec\":{\"type\":\"${user_type}\"}},\"session\":{\"status\":{\"type\":\"${session_type}\",\"isConnected\":${connected}}}}"
}

fake_kubectl_config() {
  # checkov:skip=CKV_SECRET_6:Public Octelium v0.35 placeholder prefix, not secret material.
  local token_prefix="dummy-token-authenticated-by"
  jq -cn \
    --arg server "https://kubernetes-api.homelab.local.${BOUNDARY_FIXTURE_DOMAIN}:6443" \
    --arg token "${token_prefix}-octelium-session" \
    --arg mode "${BOUNDARY_FIXTURE_CONFIG:-valid}" '
      {apiVersion: "v1", kind: "Config",
       clusters: [{name: "kubernetes", cluster: {server: $server}}],
       users: [{name: "kubernetes-admin", user: {token: $token}}],
       contexts: [{name: "kubernetes-admin@kubernetes", context: {cluster: "kubernetes", user: "kubernetes-admin"}}],
       "current-context": "kubernetes-admin@kubernetes"} |
      if $mode == "valid" then .
      elif $mode == "wrong-server" then .clusters[0].cluster.server = "https://10.1.0.199:6443"
      elif $mode == "proxy" then .clusters[0].cluster["proxy-url"] = "http://127.0.0.1:1"
      elif $mode == "tls-bypass" then .clusters[0].cluster["insecure-skip-tls-verify"] = true
      elif $mode == "alternate-credential" then
        .users[0].user = {exec: {apiVersion: "client.authentication.k8s.io/v1", command: "false"}}
      elif $mode == "wrong-context" then
        .contexts[0].name = "other" | .["current-context"] = "other"
      else error("unsupported kubeconfig fixture")
      end
    '
}

fake_kubectl() {
  local arg command="" raw=""
  assert_proxy_env_clean
  log_args "$@"
  for arg in "$@"; do
    case "${arg}" in
      config|get|create|replace|patch|delete|auth) [ -z "${command}" ] && command="${arg}" ;;
      --raw=*) raw="${arg#--raw=}" ;;
    esac
  done
  if [ "${command}" = "config" ]; then
    fake_kubectl_config
    return
  fi

  if [ "${BOUNDARY_FIXTURE_ROLE}" = "owner" ]; then
    if [ "${command}" = "auth" ]; then
      printf 'yes\n'
    elif printf '\t%s' "$@" | grep -Fq $'\tget\tpods'; then
      printf 'pod/fixture-pod\n'
    elif [ "${command}" = "create" ]; then
      printf 'configmap/fixture\n'
    else
      printf '{}\n'
    fi
    return
  fi

  case "${raw}" in
    /api|/api/v1|/apis|/apis/apps/v1|/apis/batch/v1|/api/v1/namespaces/cordium/pods\?watch=true\&timeoutSeconds=1)
      printf '{}\n'
      return
      ;;
    "")
      if [ "${command}" = "get" ]; then
        if printf '\t%s' "$@" | grep -Fq $'\tget\tpods'; then
          printf 'pod/fixture-pod\n'
        fi
        return
      fi
      ;;
  esac

  case "${BOUNDARY_FIXTURE_DENIAL:-octelium}" in
    octelium)
      printf 'Error from server (Forbidden): Octelium: Unauthorized request\n' >&2
      return 1
      ;;
    generic)
      printf 'Error from server (Forbidden): denied upstream\n' >&2
      return 1
      ;;
    wrong-status)
      printf 'Error from server (Unauthorized): Octelium: Unauthorized request\n' >&2
      return 1
      ;;
    leak)
      printf 'SENSITIVE_DENIED_BODY_SENTINEL\n'
      return 0
      ;;
    *) return 64 ;;
  esac
}

fake_git() {
  log_args "$@"
  if printf ' %s ' "$*" | grep -Fq ' status --porcelain '; then
    case "${BOUNDARY_FIXTURE_GIT_STATUS:-clean}" in
      clean) return ;;
      dirty) printf '?? fixture-dirty\n'; return ;;
      error) return 1 ;;
      *) return 64 ;;
    esac
  fi
  "${BOUNDARY_REAL_GIT}" "$@"
}

case "$(basename "$0")" in
  octelium) fake_octelium "$@"; exit ;;
  kubectl) fake_kubectl "$@"; exit ;;
  git) fake_git "$@"; exit ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel)"
BOUNDARY_SCRIPT="${REPO_ROOT}/scripts/octelium-kubernetes-boundary-e2e.sh"
BOUNDARY_CATALOG="${REPO_ROOT}/docs/examples/octelium/homelab-services.yaml"
BOUNDARY_REAL_GIT="$(command -v git)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/octelium-boundary-test.XXXXXX")"
FAKE_BIN="${TEST_ROOT}/bin"
KUBECONFIG_FIXTURE="${TEST_ROOT}/kubeconfig"
mkdir -p "${FAKE_BIN}"
ln -s "${SCRIPT_DIR}/$(basename "$0")" "${FAKE_BIN}/octelium"
ln -s "${SCRIPT_DIR}/$(basename "$0")" "${FAKE_BIN}/kubectl"
ln -s "${SCRIPT_DIR}/$(basename "$0")" "${FAKE_BIN}/git"
printf 'fixture\n' >"${KUBECONFIG_FIXTURE}"
trap 'rm -rf -- "${TEST_ROOT}"' EXIT

run_case() {
  local name="$1" role="$2" identity="$3" config="$4" denial="$5" expected="$6" git_status="${7:-clean}"
  local evidence="${TEST_ROOT}/${name}-evidence" output="${TEST_ROOT}/${name}.out" log="${TEST_ROOT}/${name}.log" exit_code
  if CI=false GITHUB_ACTIONS=false \
    BOUNDARY_FIXTURE_ROLE="${role}" \
    BOUNDARY_FIXTURE_IDENTITY="${identity}" \
    BOUNDARY_FIXTURE_CONFIG="${config}" \
    BOUNDARY_FIXTURE_DENIAL="${denial}" \
    BOUNDARY_FIXTURE_GIT_STATUS="${git_status}" \
    BOUNDARY_FIXTURE_DOMAIN="stinkyboi.com" \
    BOUNDARY_FIXTURE_LOG="${log}" \
    BOUNDARY_REAL_GIT="${BOUNDARY_REAL_GIT}" \
    HTTP_PROXY="http://upper-http.invalid:1" \
    HTTPS_PROXY="http://upper-https.invalid:1" \
    ALL_PROXY="http://upper-all.invalid:1" \
    http_proxy="http://lower-http.invalid:1" \
    https_proxy="http://lower-https.invalid:1" \
    all_proxy="http://lower-all.invalid:1" \
    OCTELIUM_AUTH_TOKEN="fixture" \
    OCTELIUM_AUTH_ASSERTION="fixture" \
    OCTELIUM_ACCESS_TOKEN="fixture" \
    OCTELIUM_AUTH_PROXY_SOCKET="/tmp/fixture.sock" \
    PATH="${FAKE_BIN}:${PATH}" \
    "${BOUNDARY_SCRIPT}" --role "${role}" --kubeconfig "${KUBECONFIG_FIXTURE}" \
      --evidence-dir "${evidence}" --evidence-id "${name}" >"${output}" 2>&1; then
    exit_code=0
  else
    exit_code=$?
  fi
  if [ "${expected}" = "pass" ] && [ "${exit_code}" -ne 0 ]; then
    printf 'fixture %s unexpectedly failed\n' "${name}" >&2
    sed -n '1,240p' "${output}" >&2
    exit 1
  fi
  if [ "${expected}" = "fail" ] && [ "${exit_code}" -eq 0 ]; then
    printf 'fixture %s unexpectedly passed\n' "${name}" >&2
    exit 1
  fi
  if [ -d "${evidence}" ]; then
    [ ! -e "${evidence}/identity.raw.json" ]
    [ ! -e "${evidence}/identity.raw.err" ]
    [ ! -e "${evidence}/kubeconfig.raw.err" ]
  fi
}

fixture_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -- "$1" | awk '{print $1}'
  else
    shasum -a 256 -- "$1" | awk '{print $1}'
  fi
}

run_case cordium-pass cordium valid valid octelium pass
run_case owner-pass owner valid valid octelium pass
reviewed_commit="$("${BOUNDARY_REAL_GIT}" -C "${REPO_ROOT}" rev-parse HEAD)"
CI=true GITHUB_ACTIONS=true BOUNDARY_FIXTURE_GIT_STATUS=clean \
  BOUNDARY_REAL_GIT="${BOUNDARY_REAL_GIT}" BOUNDARY_FIXTURE_LOG="${TEST_ROOT}/verify.log" \
  PATH="${FAKE_BIN}:${PATH}" \
  "${BOUNDARY_SCRIPT}" --verify --role cordium \
  --evidence-dir "${TEST_ROOT}/cordium-pass-evidence" --evidence-id cordium-pass \
  --reviewed-commit "${reviewed_commit}" >/dev/null

expect_verify_failure() {
  local role="$1" evidence_id="$2" evidence_dir="$3"
  if CI=true GITHUB_ACTIONS=true BOUNDARY_FIXTURE_GIT_STATUS=clean \
    BOUNDARY_REAL_GIT="${BOUNDARY_REAL_GIT}" BOUNDARY_FIXTURE_LOG="${TEST_ROOT}/verify.log" \
    PATH="${FAKE_BIN}:${PATH}" \
    "${BOUNDARY_SCRIPT}" --verify --role "${role}" \
    --evidence-dir "${evidence_dir}" --evidence-id "${evidence_id}" \
    --reviewed-commit "${reviewed_commit}" >/dev/null 2>&1; then
    echo "invalid ${role} evidence unexpectedly verified: ${evidence_id}" >&2
    exit 1
  fi
}

expect_verify_failure owner cordium-pass "${TEST_ROOT}/cordium-pass-evidence"
expect_verify_failure cordium stale-run "${TEST_ROOT}/cordium-pass-evidence"

cp -R "${TEST_ROOT}/cordium-pass-evidence" "${TEST_ROOT}/tampered-identity-evidence"
jq '.user = "homelab-owner"' "${TEST_ROOT}/tampered-identity-evidence/identity.json" \
  >"${TEST_ROOT}/identity.tmp"
mv "${TEST_ROOT}/identity.tmp" "${TEST_ROOT}/tampered-identity-evidence/identity.json"
expect_verify_failure cordium cordium-pass "${TEST_ROOT}/tampered-identity-evidence"

cp -R "${TEST_ROOT}/cordium-pass-evidence" "${TEST_ROOT}/tampered-kubeconfig-evidence"
jq '.server = "https://10.1.0.199:6443"' "${TEST_ROOT}/tampered-kubeconfig-evidence/kubeconfig.json" \
  >"${TEST_ROOT}/kubeconfig.tmp"
mv "${TEST_ROOT}/kubeconfig.tmp" "${TEST_ROOT}/tampered-kubeconfig-evidence/kubeconfig.json"
expect_verify_failure cordium cordium-pass "${TEST_ROOT}/tampered-kubeconfig-evidence"

cp -R "${TEST_ROOT}/cordium-pass-evidence" "${TEST_ROOT}/tampered-digest-evidence"
awk -F '\t' 'BEGIN { OFS = "\t" } $1 == "script_sha256" { $2 = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff" } { print }' \
  "${TEST_ROOT}/tampered-digest-evidence/metadata.tsv" >"${TEST_ROOT}/metadata.tmp"
mv "${TEST_ROOT}/metadata.tmp" "${TEST_ROOT}/tampered-digest-evidence/metadata.tsv"
expect_verify_failure cordium cordium-pass "${TEST_ROOT}/tampered-digest-evidence"

jq -e '.server == "https://kubernetes-api.homelab.local.stinkyboi.com:6443" and .context == "kubernetes-admin@kubernetes" and .usesOcteliumSessionPlaceholder == true' \
  "${TEST_ROOT}/cordium-pass-evidence/kubeconfig.json" >/dev/null
jq -e '.user == "homelab-cordium-user" and .userType == "HUMAN" and .sessionType == "CLIENT" and .isConnected == true' \
  "${TEST_ROOT}/cordium-pass-evidence/identity.json" >/dev/null
script_digest="$(fixture_sha256 "${BOUNDARY_SCRIPT}")"
catalog_digest="$(fixture_sha256 "${BOUNDARY_CATALOG}")"
grep -Fxq $'script_sha256\t'"${script_digest}" "${TEST_ROOT}/cordium-pass-evidence/metadata.tsv"
grep -Fxq $'catalog_sha256\t'"${catalog_digest}" "${TEST_ROOT}/cordium-pass-evidence/metadata.tsv"
grep -Fxq $'evidence_id\tcordium-pass' "${TEST_ROOT}/cordium-pass-evidence/metadata.tsv"
grep -Fxq $'repository_commit\t'"${reviewed_commit}" \
  "${TEST_ROOT}/cordium-pass-evidence/metadata.tsv"
grep -Fxq $'failures\t0' "${TEST_ROOT}/cordium-pass-evidence/metadata.tsv"
if rg -q 'SENSITIVE_(IDENTITY_RAW|DENIED_BODY)_SENTINEL' \
  "${TEST_ROOT}/cordium-pass-evidence" "${TEST_ROOT}/cordium-pass.out"; then
  echo "sanitized passing evidence retained a fixture sentinel" >&2
  exit 1
fi

for mode in wrong-user workload clientless disconnected; do
  run_case "identity-${mode}" cordium "${mode}" valid octelium fail
  if rg -q 'SENSITIVE_IDENTITY_RAW_SENTINEL' \
    "${TEST_ROOT}/identity-${mode}-evidence" "${TEST_ROOT}/identity-${mode}.out"; then
    echo "failed identity evidence retained raw identity data: ${mode}" >&2
    exit 1
  fi
done

for mode in missing expired; do
  run_case "identity-${mode}" cordium "${mode}" valid octelium fail
  if rg -q 'BROWSER_LOGIN_SENTINEL' \
    "${TEST_ROOT}/identity-${mode}-evidence" "${TEST_ROOT}/identity-${mode}.out"; then
    echo "${mode} identity attempted browser login" >&2
    exit 1
  fi
done

SECONDS=0
run_case identity-timeout cordium hang valid octelium fail
if [ "${SECONDS}" -gt 20 ]; then
  echo "identity status timeout was not bounded" >&2
  exit 1
fi

for mode in wrong-server proxy tls-bypass alternate-credential wrong-context; do
  run_case "config-${mode}" cordium valid "${mode}" octelium fail
  if rg -Fq $'octelium\tstatus' "${TEST_ROOT}/config-${mode}.log"; then
    echo "invalid kubeconfig reached the identity request: ${mode}" >&2
    exit 1
  fi
done

run_case denial-attribution cordium valid valid generic fail
if awk -F '\t' '$3 == "octelium-denied" && $4 != "FAIL" { exit 1 }' \
  "${TEST_ROOT}/denial-attribution-evidence/summary.tsv"; then
  :
else
  echo "generic Kubernetes denials were attributed to Octelium" >&2
  exit 1
fi

run_case denial-wrong-status cordium valid valid wrong-status fail

run_case denied-body cordium valid valid leak fail
if rg -q 'SENSITIVE_DENIED_BODY_SENTINEL' \
  "${TEST_ROOT}/denied-body-evidence" "${TEST_ROOT}/denied-body.out"; then
  echo "denied response body was retained" >&2
  exit 1
fi

rg -q -- '--raw=/api/v1/namespaces/cordium/configmaps\?dryRun=All' "${TEST_ROOT}/cordium-pass.log"
rg -q -- '--raw=/api/v1/namespaces/cordium/pods/octelium-boundary-[0-9]+/exec\?dryRun=All' "${TEST_ROOT}/cordium-pass.log"
rg -q -- '--raw=/api/v1/namespaces/cordium/pods/octelium-boundary-[0-9]+/attach\?dryRun=All' "${TEST_ROOT}/cordium-pass.log"
rg -q -- '--raw=/api/v1/namespaces/cordium/services/octelium-boundary-[0-9]+/proxy' "${TEST_ROOT}/cordium-pass.log"
rg -q -- '--raw=/api/v1/namespaces/cordium/pods/octelium-boundary-[0-9]+/status' "${TEST_ROOT}/cordium-pass.log"
rg -q -- '--raw=/apis/apps/v2/namespaces/cordium/deployments\?labelSelector=' "${TEST_ROOT}/cordium-pass.log"
rg -Fq -- '--raw=/readyz' "${TEST_ROOT}/cordium-pass.log"
rg -Fq -- '--raw=/openapi/v3' "${TEST_ROOT}/cordium-pass.log"
rg -q -- '--raw=/api/v1/namespaces\?labelSelector=' "${TEST_ROOT}/cordium-pass.log"
rg -q -- '--raw=/api/v1/namespaces/cordium/endpoints\?labelSelector=' "${TEST_ROOT}/cordium-pass.log"
rg -q -- '--raw=/apis/discovery.k8s.io/v1/namespaces/cordium/endpointslices\?labelSelector=' "${TEST_ROOT}/cordium-pass.log"
rg -q -- '--dry-run=server' "${TEST_ROOT}/cordium-pass.log"
rg -q -- 'labelSelector=octelium-boundary-probe%3D[0-9]+' "${TEST_ROOT}/cordium-pass.log"
if rg -Fq '/pods/fixture-pod/log' "${TEST_ROOT}/cordium-pass.log"; then
  echo "denied log probe targeted a real Pod" >&2
  exit 1
fi
if rg -Fq '/namespaces/kube-system/pods' "${TEST_ROOT}/cordium-pass.log"; then
  echo "boundary fixture incorrectly expected an explicit namespace to be denied" >&2
  exit 1
fi

run_case dirty-checkout cordium valid valid octelium fail dirty
rg -Fq 'repository checkout must be clean' "${TEST_ROOT}/dirty-checkout.out"
if rg -q '^(octelium|kubectl)\t' "${TEST_ROOT}/dirty-checkout.log"; then
  echo "dirty checkout reached a proof command" >&2
  exit 1
fi

run_case git-status-error cordium valid valid octelium fail error
rg -Fq 'could not inspect repository checkout state' "${TEST_ROOT}/git-status-error.out"

CI_OUTPUT="${TEST_ROOT}/ci.out"
if CI=true GITHUB_ACTIONS=false PATH="${FAKE_BIN}:${PATH}" \
  "${BOUNDARY_SCRIPT}" --role cordium --kubeconfig "${KUBECONFIG_FIXTURE}" \
    --evidence-dir "${TEST_ROOT}/ci-evidence" --evidence-id ci-evidence >"${CI_OUTPUT}" 2>&1; then
  echo "live boundary fixture unexpectedly ran in CI" >&2
  exit 1
fi
rg -Fq 'live HUMAN identity evidence must not run in CI' "${CI_OUTPUT}"

echo "Octelium Kubernetes boundary behavioral fixtures passed."
