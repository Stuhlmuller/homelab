#!/usr/bin/env bash
set -euo pipefail

DOMAIN="stinkyboi.com"
CLIENT_NAMESPACE="octelium-client"
CONTROL_NAMESPACE="octelium"
CATALOG="docs/examples/octelium/homelab-services.yaml"
IDP_NAME="entra"
TEST_PATH="/"
CLIENT_IMPLEMENTATION="gvisor"
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
Set OCTELIUM_AUTH_TOKEN to run the final tunnel check noninteractively with an
authentication token; otherwise the script uses the current local Octelium
login state.

Options:
  --domain DOMAIN             Octelium Cluster domain. Default: stinkyboi.com
  --catalog PATH              Octelium catalog file. Default: docs/examples/octelium/homelab-services.yaml
  --idp-name NAME             Required Octelium IdentityProvider name. Default: entra
  --path PATH                 HTTPS path to probe on each app hostname. Default: /
  --client-implementation IMPL Octelium client implementation for hostname probes. Default: gvisor
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
    --idp-name)
      IDP_NAME="$2"
      shift 2
      ;;
    --path)
      TEST_PATH="$2"
      shift 2
      ;;
    --client-implementation)
      CLIENT_IMPLEMENTATION="$2"
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
CONTROL_HOSTS=("${DOMAIN}" "${PORTAL_HOST}" "${API_HOST}")
if [ "${DOMAIN}" = "stinkyboi.com" ]; then
  CONTROL_HOSTS+=("octelium.stinkyboi.com")
fi

APP_TARGETS="
argocd.stinkyboi.com argocd.homelab 18443
compass.stinkyboi.com compass.homelab 18444
deluge.stinkyboi.com deluge.homelab 18445
grafana.stinkyboi.com grafana.homelab 18446
kiali.stinkyboi.com kiali.homelab 18447
litellm.stinkyboi.com litellm.homelab 18448
n8n.stinkyboi.com n8n.homelab 18449
octobot.stinkyboi.com octobot.homelab 18450
openclaw.stinkyboi.com openclaw.homelab 18451
policy-bot.stinkyboi.com policy-bot.homelab 18452
prowlarr.stinkyboi.com prowlarr.homelab 18453
radarr.stinkyboi.com radarr.homelab 18454
sonarr.stinkyboi.com sonarr.homelab 18455
"

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
require_command dig
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

TARGET_SECRET="$(kubectl_homelab -n "${CLIENT_NAMESPACE}" get externalsecret octelium-client-auth -o jsonpath='{.status.binding.name}' 2>/dev/null || true)"
if [ -z "${TARGET_SECRET}" ]; then
  TARGET_SECRET="$(kubectl_homelab -n "${CLIENT_NAMESPACE}" get externalsecret octelium-client-auth -o jsonpath='{.spec.target.name}' 2>/dev/null || true)"
fi

if [ -n "${TARGET_SECRET}" ] && kubectl_homelab -n "${CLIENT_NAMESPACE}" get secret "${TARGET_SECRET}" >/dev/null 2>&1; then
  pass "octelium-client-auth target Secret exists: ${TARGET_SECRET}"
else
  fail "octelium-client-auth target Secret is missing"
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
for HOST in "${CONTROL_HOSTS[@]}"; do
  HEADER_FILE="$(mktemp "${TMPDIR:-/tmp}/octelium-headers.XXXXXX")"
  HTTP_CODE="$(curl -sS -I --max-time 15 -o "${HEADER_FILE}" -w '%{http_code}' "https://${HOST}" || true)"
  SERVER="$(awk 'tolower($1) == "server:" {print $2}' "${HEADER_FILE}" | tr -d '\r' | tail -1)"
  rm -f "${HEADER_FILE}"
  case "${HTTP_CODE}" in
    200|204|301|302|307|308|401|403|405)
      pass "https://${HOST} responded with HTTP ${HTTP_CODE}"
      ;;
    404)
      if [ "${HOST}" = "${API_HOST}" ]; then
        pass "https://${HOST} responded with HTTP 404 at the gRPC API root"
      elif [ "${SERVER}" = "istio-envoy" ]; then
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

if run_with_timeout "${OCTELIUMCTL_TIMEOUT_SECONDS}" octeliumctl get identityprovider "${IDP_NAME}" --domain "${DOMAIN}" >/tmp/octelium-idp.$$ 2>/tmp/octelium-idp.err.$$; then
  pass "Octelium IdentityProvider exists: ${IDP_NAME}"
else
  if [ -s /tmp/octelium-idp.err.$$ ]; then
    fail "Octelium IdentityProvider ${IDP_NAME} is not available: $(tr '\n' ' ' </tmp/octelium-idp.err.$$)"
  else
    fail "Octelium IdentityProvider ${IDP_NAME} could not be listed within ${OCTELIUMCTL_TIMEOUT_SECONDS}s"
  fi
fi
rm -f /tmp/octelium-idp.$$ /tmp/octelium-idp.err.$$

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

note "Checking app hostnames over Octelium VPN"
CONNECT_ARGS=(
  octelium
  connect
  --domain "${DOMAIN}"
  --implementation="${CLIENT_IMPLEMENTATION}"
  --no-dns
)

if [ -n "${OCTELIUM_AUTH_TOKEN:-}" ]; then
  CONNECT_ARGS+=(--auth-token "${OCTELIUM_AUTH_TOKEN}")
  CONNECT_ARGS+=(--scope "api:user.MainService/Connect")
  for SERVICE in ${REQUIRED_SERVICES}; do
    CONNECT_ARGS+=(--scope "service:${SERVICE}")
  done
fi

while read -r HOST SERVICE LOCAL_PORT; do
  [ -n "${HOST}" ] || continue
  CONNECT_ARGS+=(--publish "${SERVICE}:127.0.0.1:${LOCAL_PORT}")
done <<<"${APP_TARGETS}"

"${CONNECT_ARGS[@]}" >/tmp/octelium-connect.$$ 2>/tmp/octelium-connect.err.$$ &
CONNECT_PID="$!"

sleep 5
if ! kill -0 "${CONNECT_PID}" >/dev/null 2>&1; then
  fail "octelium connect exited before app hostname checks; connect log: $(tr '\n' ' ' </tmp/octelium-connect.err.$$)"
else
  while read -r HOST SERVICE LOCAL_PORT; do
    [ -n "${HOST}" ] || continue
    HEADER_FILE="$(mktemp "${TMPDIR:-/tmp}/octelium-app-headers.XXXXXX")"
    CURL_ERR="$(mktemp "${TMPDIR:-/tmp}/octelium-app-curl.XXXXXX")"
    RESOLVED_IP="$(
      dig +short @1.1.1.1 "${HOST}" AAAA 2>/dev/null |
        awk '/^fdee:b76e:/ {print; exit}'
    )"
    if [ -z "${RESOLVED_IP}" ]; then
      fail "https://${HOST}${TEST_PATH} has no public Octelium AAAA record"
      rm -f "${HEADER_FILE}" "${CURL_ERR}"
      continue
    else
      pass "https://${HOST} resolves to Octelium service IPv6 ${RESOLVED_IP}"
    fi

    CURL_OUT="$(
      curl -sS -I --max-time 20 --connect-to "${HOST}:443:127.0.0.1:${LOCAL_PORT}" -o "${HEADER_FILE}" -w '%{http_code} %{remote_ip}' "https://${HOST}${TEST_PATH}" 2>"${CURL_ERR}" || true
    )"
    HTTP_CODE="${CURL_OUT%% *}"
    REMOTE_IP="${CURL_OUT#* }"
    SERVER="$(awk 'tolower($1) == "server:" {print $2}' "${HEADER_FILE}" | tr -d '\r' | tail -1)"

    case "${HTTP_CODE}" in
      200|204|301|302|307|308|401|403|404|405)
        if [ "${REMOTE_IP}" = "127.0.0.1" ]; then
          pass "https://${HOST}${TEST_PATH} reached ${SERVICE} through Octelium publish on localhost:${LOCAL_PORT} with HTTP ${HTTP_CODE}"
        else
          fail "https://${HOST}${TEST_PATH} connected to ${REMOTE_IP:-unknown}, not the local Octelium publish port"
        fi
        ;;
      000|"")
        fail "https://${HOST}${TEST_PATH} did not respond via Octelium; curl: $(tr '\n' ' ' <"${CURL_ERR}")"
        ;;
      *)
        fail "https://${HOST}${TEST_PATH} returned unexpected HTTP ${HTTP_CODE} from ${REMOTE_IP:-unknown} via ${SERVICE}"
        ;;
    esac

    rm -f "${HEADER_FILE}" "${CURL_ERR}"
  done <<<"${APP_TARGETS}"
fi
rm -f /tmp/octelium-connect.$$ /tmp/octelium-connect.err.$$

if [ "${FAILURES}" -gt 0 ]; then
  echo "Octelium e2e check failed with ${FAILURES} failure(s)." >&2
  exit 1
fi

echo "Octelium e2e check passed."
