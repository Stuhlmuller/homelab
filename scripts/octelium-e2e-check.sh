#!/usr/bin/env bash
set -euo pipefail

DOMAIN="octelium.stinkyboi.com"
CLIENT_NAMESPACE="octelium-client"
CONTROL_NAMESPACE="octelium"
CATALOG="docs/examples/octelium/homelab-services.yaml"
TEST_SERVICE="homelab-demo.homelab"
TEST_PATH="/version"
LOCAL_PORT="18081"
OCTELIUMCTL_TIMEOUT_SECONDS=20
HOMELAB_KUBECONFIG=""
HOMELAB_CONTEXT=""
OCTELIUM_KUBECONFIG=""
OCTELIUM_CONTEXT=""

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-e2e-check.sh [options]

Validate that Octelium has fully replaced Tailscale for homelab app access.
The check requires a running Octelium Cluster, an applied homelab service
catalog, an active octelium-client connector, and a working client tunnel.

Options:
  --domain DOMAIN             Octelium Cluster domain. Default: octelium.stinkyboi.com
  --catalog PATH              Octelium catalog file. Default: docs/examples/octelium/homelab-services.yaml
  --service NAME              Service to tunnel for the final probe. Default: homelab-demo.homelab
  --path PATH                 HTTP path to probe through the tunnel. Default: /version
  --local-port PORT           Local port for the tunnel. Default: 18081
  --homelab-kubeconfig PATH   Kubeconfig for the homelab cluster. Default: kubectl default
  --homelab-context NAME      Kube context for homelab connector checks. Default: kubectl current context
  --octelium-kubeconfig PATH  Kubeconfig for the Octelium control-plane cluster. Default: kubectl default
  --octelium-context NAME     Kube context for Octelium control-plane checks. Default: kubectl current context
  -h, --help                  Show this help.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --domain)
      DOMAIN="$2"
      shift 2
      ;;
    --catalog)
      CATALOG="$2"
      shift 2
      ;;
    --service)
      TEST_SERVICE="$2"
      shift 2
      ;;
    --path)
      TEST_PATH="$2"
      shift 2
      ;;
    --local-port)
      LOCAL_PORT="$2"
      shift 2
      ;;
    --homelab-kubeconfig)
      HOMELAB_KUBECONFIG="$2"
      shift 2
      ;;
    --homelab-context)
      HOMELAB_CONTEXT="$2"
      shift 2
      ;;
    --octelium-kubeconfig)
      OCTELIUM_KUBECONFIG="$2"
      shift 2
      ;;
    --octelium-context)
      OCTELIUM_CONTEXT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

API_HOST="octelium-api.${DOMAIN}"
PORTAL_HOST="portal.${DOMAIN}"

REQUIRED_SERVICES="
argocd.homelab
compass.homelab
deluge.homelab
grafana.homelab
homelab-demo.homelab
kiali.homelab
litellm.homelab
n8n.homelab
octobot.homelab
openclaw.homelab
policy-bot.homelab
prowlarr.homelab
radarr.homelab
sonarr.homelab
"

FAILURES=0
CONNECT_PID=""

note() {
  printf '==> %s\n' "$*"
}

pass() {
  printf 'PASS: %s\n' "$*"
}

fail() {
  FAILURES=$((FAILURES + 1))
  printf 'FAIL: %s\n' "$*" >&2
}

require_command() {
  if command -v "$1" >/dev/null 2>&1; then
    pass "found $1"
  else
    fail "missing required command: $1"
  fi
}

kubectl_homelab() {
  if [ -n "${HOMELAB_CONTEXT}" ]; then
    set -- --context "${HOMELAB_CONTEXT}" "$@"
  fi
  if [ -n "${HOMELAB_KUBECONFIG}" ]; then
    set -- --kubeconfig "${HOMELAB_KUBECONFIG}" "$@"
  fi

  if kubectl "$@"; then
    return 0
  else
    return "$?"
  fi
}

kubectl_octelium() {
  if [ -n "${OCTELIUM_CONTEXT}" ]; then
    set -- --context "${OCTELIUM_CONTEXT}" "$@"
  fi
  if [ -n "${OCTELIUM_KUBECONFIG}" ]; then
    set -- --kubeconfig "${OCTELIUM_KUBECONFIG}" "$@"
  fi

  if kubectl "$@"; then
    return 0
  else
    return "$?"
  fi
}

run_with_timeout() {
  timeout_seconds="$1"
  shift

  "$@" &
  command_pid="$!"
  elapsed_seconds=0

  while kill -0 "${command_pid}" >/dev/null 2>&1; do
    if [ "${elapsed_seconds}" -ge "${timeout_seconds}" ]; then
      kill "${command_pid}" >/dev/null 2>&1 || true
      wait "${command_pid}" >/dev/null 2>&1 || true
      return 124
    fi
    sleep 1
    elapsed_seconds=$((elapsed_seconds + 1))
  done

  if wait "${command_pid}"; then
    return 0
  else
    return "$?"
  fi
}

cleanup() {
  local cleanup_status
  cleanup_status=$?
  if [ -n "${CONNECT_PID}" ]; then
    kill "${CONNECT_PID}" >/dev/null 2>&1 || true
    wait "${CONNECT_PID}" >/dev/null 2>&1 || true
  fi
  return "${cleanup_status}"
}
trap cleanup EXIT

note "Checking local tools"
require_command kubectl
require_command curl
require_command octelium
require_command octeliumctl

if [ "${FAILURES}" -gt 0 ]; then
  echo "Cannot continue without required local tools." >&2
  exit 1
fi

note "Checking Kubernetes control-plane and connector state"
if kubectl_octelium get namespace "${CONTROL_NAMESPACE}" >/dev/null 2>&1; then
  pass "Octelium control namespace exists: ${CONTROL_NAMESPACE}"
else
  fail "Octelium control namespace is missing: ${CONTROL_NAMESPACE}"
fi

CONTROL_SERVICES="$(kubectl_octelium -n "${CONTROL_NAMESPACE}" get svc -o name 2>/dev/null || true)"
if [ -n "${CONTROL_SERVICES}" ]; then
  pass "Octelium control-plane services are visible"
else
  fail "Octelium control-plane services are not visible"
fi

if kubectl_homelab get namespace "${CLIENT_NAMESPACE}" >/dev/null 2>&1; then
  pass "Octelium client namespace exists: ${CLIENT_NAMESPACE}"
else
  fail "Octelium client namespace is missing: ${CLIENT_NAMESPACE}"
fi

if kubectl_homelab -n "${CLIENT_NAMESPACE}" get externalsecret octelium-client-auth >/dev/null 2>&1; then
  READY="$(kubectl_homelab -n "${CLIENT_NAMESPACE}" get externalsecret octelium-client-auth -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
  if [ "${READY}" = "True" ]; then
    pass "octelium-client-auth ExternalSecret is Ready"
  else
    fail "octelium-client-auth ExternalSecret is not Ready"
  fi
else
  fail "octelium-client-auth ExternalSecret is missing"
fi

if kubectl_homelab -n "${CLIENT_NAMESPACE}" get secret octelium-client-auth >/dev/null 2>&1; then
  pass "octelium-client-auth Secret exists"
else
  fail "octelium-client-auth Secret is missing"
fi

if kubectl_homelab -n "${CLIENT_NAMESPACE}" get deploy octelium-client >/dev/null 2>&1; then
  REPLICAS="$(kubectl_homelab -n "${CLIENT_NAMESPACE}" get deploy octelium-client -o jsonpath='{.spec.replicas}')"
  READY_REPLICAS="$(kubectl_homelab -n "${CLIENT_NAMESPACE}" get deploy octelium-client -o jsonpath='{.status.readyReplicas}')"
  READY_REPLICAS="${READY_REPLICAS:-0}"
  if [ "${REPLICAS}" -ge 1 ] && [ "${READY_REPLICAS}" -ge 1 ]; then
    pass "octelium-client Deployment is active (${READY_REPLICAS}/${REPLICAS})"
  else
    fail "octelium-client Deployment is not active (${READY_REPLICAS}/${REPLICAS})"
  fi
else
  fail "octelium-client Deployment is missing"
fi

note "Checking Octelium TLS/API endpoints"
for HOST in "${DOMAIN}" "${PORTAL_HOST}" "${API_HOST}"; do
  HEADER_FILE="$(mktemp "${TMPDIR:-/tmp}/octelium-headers.XXXXXX")"
  HTTP_CODE="$(curl -sS -I --max-time 15 -o "${HEADER_FILE}" -w '%{http_code}' "https://${HOST}" || true)"
  SERVER="$(awk 'tolower($1) == "server:" {print $2}' "${HEADER_FILE}" | tr -d '\r' | tail -1)"
  rm -f "${HEADER_FILE}"
  case "${HTTP_CODE}" in
    200|204|301|302|307|308|401|403|405)
      pass "https://${HOST} responded with HTTP ${HTTP_CODE}"
      ;;
    404)
      if [ "${SERVER}" = "istio-envoy" ]; then
        fail "https://${HOST} is still a generic Istio 404, not Octelium"
      else
        fail "https://${HOST} returned HTTP 404"
      fi
      ;;
    000|"")
      fail "https://${HOST} did not respond"
      ;;
    *)
      fail "https://${HOST} returned unexpected HTTP ${HTTP_CODE}"
      ;;
  esac
done

note "Checking Octelium service catalog"
if [ ! -f "${CATALOG}" ]; then
  fail "catalog file is missing: ${CATALOG}"
else
  pass "catalog file exists: ${CATALOG}"
fi

if run_with_timeout "${OCTELIUMCTL_TIMEOUT_SECONDS}" octeliumctl get service --domain "${DOMAIN}" >/tmp/octelium-services.$$ 2>/tmp/octelium-services.err.$$; then
  for SERVICE in ${REQUIRED_SERVICES}; do
    if grep -F "${SERVICE}" /tmp/octelium-services.$$ >/dev/null 2>&1; then
      pass "Octelium Service exists: ${SERVICE}"
    else
      fail "Octelium Service is missing: ${SERVICE}"
    fi
  done
else
  if [ -s /tmp/octelium-services.err.$$ ]; then
    fail "octeliumctl could not list services for ${DOMAIN}: $(tr '\n' ' ' </tmp/octelium-services.err.$$)"
  else
    fail "octeliumctl could not list services for ${DOMAIN} within ${OCTELIUMCTL_TIMEOUT_SECONDS}s"
  fi
fi
rm -f /tmp/octelium-services.$$ /tmp/octelium-services.err.$$

note "Checking client tunnel to ${TEST_SERVICE}"
octelium connect --domain "${DOMAIN}" -p "${TEST_SERVICE}:${LOCAL_PORT}" >/tmp/octelium-connect.$$ 2>/tmp/octelium-connect.err.$$ &
CONNECT_PID="$!"

TUNNEL_READY=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS --max-time 3 "http://127.0.0.1:${LOCAL_PORT}${TEST_PATH}" >/tmp/octelium-e2e-response.$$ 2>/tmp/octelium-e2e-curl.err.$$; then
    TUNNEL_READY=1
    break
  fi
  if ! kill -0 "${CONNECT_PID}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if [ "${TUNNEL_READY}" -eq 1 ]; then
  pass "tunneled ${TEST_SERVICE}${TEST_PATH} through Octelium on localhost:${LOCAL_PORT}"
else
  fail "could not tunnel ${TEST_SERVICE}${TEST_PATH}; connect log: $(tr '\n' ' ' </tmp/octelium-connect.err.$$)"
fi
rm -f /tmp/octelium-connect.$$ /tmp/octelium-connect.err.$$ /tmp/octelium-e2e-response.$$ /tmp/octelium-e2e-curl.err.$$

if [ "${FAILURES}" -gt 0 ]; then
  echo "Octelium e2e check failed with ${FAILURES} failure(s)." >&2
  exit 1
fi

echo "Octelium e2e check passed."
