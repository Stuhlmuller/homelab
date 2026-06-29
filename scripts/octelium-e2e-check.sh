#!/usr/bin/env bash
set -euo pipefail

DOMAIN="stinkyboi.com"
CLIENT_NAMESPACE="octelium-client"
CONTROL_NAMESPACE="octelium"
CATALOG="docs/examples/octelium/homelab-services.yaml"
IDP_NAME="entra"
TEST_PATH="/"
CLIENT_IMPLEMENTATION="gvisor"
APP_GATEWAY_SERVICE="homelab-app-gateway.homelab"
OCTELIUMCTL_TIMEOUT_SECONDS=20
HOMELAB_KUBECONFIG=""
HOMELAB_CONTEXT=""
OCTELIUM_KUBECONFIG=""
OCTELIUM_CONTEXT=""

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-e2e-check.sh [options]

Validate that Octelium is the homelab backbone for app access, CI reachability,
VPN entry points, and reviewed public callbacks.
The check requires a running Octelium Cluster, an applied homelab service
catalog, an active octelium-client connector, and clientless WEB access for
the existing app FQDNs.

Options:
  --domain DOMAIN             Octelium Cluster domain. Default: stinkyboi.com
  --catalog PATH              Octelium catalog file. Default: docs/examples/octelium/homelab-services.yaml
  --idp-name NAME             Required Octelium IdentityProvider name. Default: entra
  --path PATH                 HTTPS path to probe on each app hostname. Default: /
  --client-implementation IMPL Deprecated; accepted for compatibility.
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

APP_HOSTS="
argocd.stinkyboi.com
compass.stinkyboi.com
cordium.stinkyboi.com
console.stinkyboi.com
deluge.stinkyboi.com
grafana.stinkyboi.com
kiali.stinkyboi.com
litellm.stinkyboi.com
n8n.stinkyboi.com
octobot.stinkyboi.com
openclaw.stinkyboi.com
policy-bot.stinkyboi.com
prowlarr.stinkyboi.com
radarr.stinkyboi.com
sonarr.stinkyboi.com
"

CALLBACK_PROBES="
n8n-webhook.stinkyboi.com /webhook/__octelium_e2e_missing__ expect-n8n-404
policy-bot-hook.stinkyboi.com /api/github/hook no-404
"

REQUIRED_SERVICES="
kubernetes-api.ci
argocd
compass
cordium
deluge
grafana
homelab-demo.homelab
kiali
litellm
n8n
octobot
openclaw
policy-bot
prowlarr
radarr
sonarr
"

FAILURES=0
GRPC_READY=1
SERVICES_JSON=""

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

octeliumctl_cluster() {
  octeliumctl --domain "${DOMAIN}" "$@"
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
  return "${cleanup_status}"
}
trap cleanup EXIT

note "Checking local tools"
require_command kubectl
require_command curl
require_command dig
require_command octeliumctl
require_command jq

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

GRPC_HEADER_FILE="$(mktemp "${TMPDIR:-/tmp}/octelium-grpc-headers.XXXXXX")"
GRPC_TRAILERS_HEADER="$(printf '%s%s: trailers' t e)"
GRPC_HTTP_CODE="$(
  curl -sS \
    --http2 \
    -H "content-type: application/grpc" \
    -H "${GRPC_TRAILERS_HEADER}" \
    --data-binary '' \
    --max-time 15 \
    -o /dev/null \
    -D "${GRPC_HEADER_FILE}" \
    -w '%{http_code}' \
    "https://${API_HOST}/octelium.api.main.user.v1.MainService/GetStatus" || true
)"
GRPC_SERVER="$(awk 'tolower($1) == "server:" {print $2}' "${GRPC_HEADER_FILE}" | tr -d '\r' | tail -1)"
rm -f "${GRPC_HEADER_FILE}"
case "${GRPC_HTTP_CODE}" in
  200|204|400|401|404|405|415|501)
    pass "https://${API_HOST} accepted a POST gRPC-shaped request path with HTTP ${GRPC_HTTP_CODE}"
    ;;
  403)
    if [ "${GRPC_SERVER}" = "cloudflare" ]; then
      fail "https://${API_HOST} returned Cloudflare HTTP 403 to a gRPC request; enable Cloudflare zone gRPC or use a non-public-hostname Tunnel route before Octelium clients can connect from outside the tailnet"
    else
      fail "https://${API_HOST} returned HTTP 403 to a gRPC request"
    fi
    GRPC_READY=0
    ;;
  000|"")
    fail "https://${API_HOST} did not respond to a gRPC-shaped request"
    GRPC_READY=0
    ;;
  *)
    fail "https://${API_HOST} returned unexpected HTTP ${GRPC_HTTP_CODE} to a gRPC request"
    GRPC_READY=0
    ;;
esac

note "Checking Octelium service catalog"
if [ ! -f "${CATALOG}" ]; then
  fail "catalog file is missing: ${CATALOG}"
else
  pass "catalog file exists: ${CATALOG}"
fi

if [ "${GRPC_READY}" -eq 1 ]; then
  if run_with_timeout "${OCTELIUMCTL_TIMEOUT_SECONDS}" octeliumctl_cluster get identityprovider >/tmp/octelium-idp.$$ 2>/tmp/octelium-idp.err.$$; then
    if grep -F "${IDP_NAME}" /tmp/octelium-idp.$$ >/dev/null 2>&1; then
      pass "Octelium IdentityProvider exists: ${IDP_NAME}"
    else
      fail "Octelium IdentityProvider is missing: ${IDP_NAME}"
    fi
  else
    if [ -s /tmp/octelium-idp.err.$$ ]; then
      fail "Octelium IdentityProvider ${IDP_NAME} is not available: $(tr '\n' ' ' </tmp/octelium-idp.err.$$)"
    else
      fail "Octelium IdentityProvider ${IDP_NAME} could not be listed within ${OCTELIUMCTL_TIMEOUT_SECONDS}s"
    fi
  fi
else
  note "Skipping octeliumctl IdentityProvider check because public Octelium gRPC is not available"
fi
rm -f /tmp/octelium-idp.$$ /tmp/octelium-idp.err.$$

if [ "${GRPC_READY}" -eq 1 ]; then
  if run_with_timeout "${OCTELIUMCTL_TIMEOUT_SECONDS}" octeliumctl_cluster get service -o json >/tmp/octelium-services.$$ 2>/tmp/octelium-services.err.$$; then
    SERVICES_JSON="$(cat /tmp/octelium-services.$$)"
    for SERVICE in ${REQUIRED_SERVICES}; do
      if jq -e --arg service "${SERVICE}" '.items[] | select(.metadata.name == $service or .status.primaryHostname == $service)' >/dev/null 2>&1 <<<"${SERVICES_JSON}"; then
        pass "Octelium Service exists: ${SERVICE}"
      else
        fail "Octelium Service is missing: ${SERVICE}"
      fi
    done
    for SERVICE in argocd compass cordium deluge grafana kiali litellm n8n octobot openclaw policy-bot prowlarr radarr sonarr; do
      if jq -e --arg service "${SERVICE}" '.items[] | select((.metadata.name == $service or .status.primaryHostname == $service) and .spec.mode == "WEB" and .spec.isPublic == true)' >/dev/null 2>&1 <<<"${SERVICES_JSON}"; then
        pass "Octelium Service ${SERVICE} is WEB and public/clientless"
      else
        fail "Octelium Service ${SERVICE} is not WEB with isPublic=true"
      fi
      if jq -e --arg service "${SERVICE}" '.items[] | select((.metadata.name == $service or .status.primaryHostname == $service) and .spec.config.upstream.url == "https://istio-ingressgateway.istio-system.svc.cluster.local:443" and .spec.config.tls.insecureSkipVerify == true)' >/dev/null 2>&1 <<<"${SERVICES_JSON}"; then
        pass "Octelium Service ${SERVICE} uses the non-redirecting Istio HTTPS upstream"
      else
        fail "Octelium Service ${SERVICE} is not using the non-redirecting Istio HTTPS upstream"
      fi
    done
  else
    if [ -s /tmp/octelium-services.err.$$ ]; then
      fail "octeliumctl could not list services for ${DOMAIN}: $(tr '\n' ' ' </tmp/octelium-services.err.$$)"
    else
      fail "octeliumctl could not list services for ${DOMAIN} within ${OCTELIUMCTL_TIMEOUT_SECONDS}s"
    fi
  fi
else
  note "Skipping octeliumctl Service catalog check because public Octelium gRPC is not available"
fi
rm -f /tmp/octelium-services.$$ /tmp/octelium-services.err.$$

note "Checking public app and Enterprise console hostnames"
while read -r HOST; do
    [ -n "${HOST}" ] || continue
    HEADER_FILE="$(mktemp "${TMPDIR:-/tmp}/octelium-app-headers.XXXXXX")"
    CURL_ERR="$(mktemp "${TMPDIR:-/tmp}/octelium-app-curl.XXXXXX")"
    PRIVATE_IPV4="$(
      dig +short @1.1.1.1 "${HOST}" A 2>/dev/null |
        awk '/^100\.64\./ {print; exit}'
    )"
    PRIVATE_IPV6="$(
      dig +short @1.1.1.1 "${HOST}" AAAA 2>/dev/null |
        awk '/^fdee:b76e:/ {print; exit}'
    )"
    PUBLIC_IPV4="$(
      dig +short @1.1.1.1 "${HOST}" A 2>/dev/null |
        awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ {print; exit}'
    )"
    if [ -n "${PRIVATE_IPV4}" ] || [ -n "${PRIVATE_IPV6}" ]; then
      fail "https://${HOST} still resolves to private Octelium service records (${PRIVATE_IPV4:-no A}/${PRIVATE_IPV6:-no AAAA})"
      rm -f "${HEADER_FILE}" "${CURL_ERR}"
      continue
    fi
    if [ -z "${PUBLIC_IPV4}" ]; then
      fail "https://${HOST} has no public IPv4 DNS answer"
      rm -f "${HEADER_FILE}" "${CURL_ERR}"
      continue
    else
      pass "https://${HOST} resolves publicly for clientless access"
    fi

    CURL_OUT="$(
      curl -sS -I --max-time 20 -o "${HEADER_FILE}" -w '%{http_code} %{remote_ip}' "https://${HOST}${TEST_PATH}" 2>"${CURL_ERR}" || true
    )"
    HTTP_CODE="${CURL_OUT%% *}"
    REMOTE_IP="${CURL_OUT#* }"
    SERVER="$(awk 'tolower($1) == "server:" {print $2}' "${HEADER_FILE}" | tr -d '\r' | tail -1)"
    LOCATION="$(awk 'tolower($1) == "location:" {print $2}' "${HEADER_FILE}" | tr -d '\r' | tail -1)"

    if [ "${HOST}" = "console.stinkyboi.com" ] && printf '%s' "${LOCATION}" | grep -F "console.octelium.stinkyboi.com" >/dev/null 2>&1; then
      fail "https://${HOST}${TEST_PATH} redirected to unsupported nested console hostname: ${LOCATION}"
      rm -f "${HEADER_FILE}" "${CURL_ERR}"
      continue
    fi

    case "${HTTP_CODE}" in
      200|204|301|302|307|308|401|403|405)
        pass "https://${HOST}${TEST_PATH} responded through the public access path with HTTP ${HTTP_CODE}"
        ;;
      404)
        fail "https://${HOST}${TEST_PATH} returned HTTP 404; the public access route did not match this hostname"
        ;;
      000|"")
        fail "https://${HOST}${TEST_PATH} did not respond publicly; curl: $(tr '\n' ' ' <"${CURL_ERR}")"
        ;;
      *)
        fail "https://${HOST}${TEST_PATH} returned unexpected HTTP ${HTTP_CODE} from ${REMOTE_IP:-unknown} server ${SERVER:-unknown}"
        ;;
    esac

    rm -f "${HEADER_FILE}" "${CURL_ERR}"
done <<<"${APP_HOSTS}"

note "Checking public callback hostnames"
while read -r HOST CALLBACK_PATH MODE; do
    [ -n "${HOST}" ] || continue
    HEADER_FILE="$(mktemp "${TMPDIR:-/tmp}/octelium-callback-headers.XXXXXX")"
    BODY_FILE="$(mktemp "${TMPDIR:-/tmp}/octelium-callback-body.XXXXXX")"
    CURL_ERR="$(mktemp "${TMPDIR:-/tmp}/octelium-callback-curl.XXXXXX")"
    PRIVATE_IPV4="$(
      dig +short @1.1.1.1 "${HOST}" A 2>/dev/null |
        awk '/^100\.64\./ {print; exit}'
    )"
    PRIVATE_IPV6="$(
      dig +short @1.1.1.1 "${HOST}" AAAA 2>/dev/null |
        awk '/^fdee:b76e:/ {print; exit}'
    )"
    PUBLIC_IPV4="$(
      dig +short @1.1.1.1 "${HOST}" A 2>/dev/null |
        awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ {print; exit}'
    )"
    if [ -n "${PRIVATE_IPV4}" ] || [ -n "${PRIVATE_IPV6}" ]; then
      fail "https://${HOST} still resolves to private Octelium service records (${PRIVATE_IPV4:-no A}/${PRIVATE_IPV6:-no AAAA})"
      rm -f "${HEADER_FILE}" "${BODY_FILE}" "${CURL_ERR}"
      continue
    fi
    if [ -z "${PUBLIC_IPV4}" ]; then
      fail "https://${HOST} has no public IPv4 DNS answer"
      rm -f "${HEADER_FILE}" "${BODY_FILE}" "${CURL_ERR}"
      continue
    else
      pass "https://${HOST} resolves publicly for callback access"
    fi

    CURL_OUT="$(
      curl -sS --max-time 20 -D "${HEADER_FILE}" -o "${BODY_FILE}" -w '%{http_code} %{remote_ip}' "https://${HOST}${CALLBACK_PATH}" 2>"${CURL_ERR}" || true
    )"
    HTTP_CODE="${CURL_OUT%% *}"
    REMOTE_IP="${CURL_OUT#* }"
    SERVER="$(awk 'tolower($1) == "server:" {print $2}' "${HEADER_FILE}" | tr -d '\r' | tail -1)"

    case "${HTTP_CODE}" in
      200|204|301|302|307|308|400|401|403|405)
        pass "https://${HOST}${CALLBACK_PATH} reached the callback route with HTTP ${HTTP_CODE}"
        ;;
      404)
        if [ "${MODE}" = "expect-n8n-404" ] && grep -qi 'webhook' "${BODY_FILE}"; then
          pass "https://${HOST}${CALLBACK_PATH} reached the callback host with expected app-level HTTP 404"
        else
          fail "https://${HOST}${CALLBACK_PATH} returned HTTP 404 without an expected app response; the callback route may be hitting an edge or gateway catch-all"
        fi
        ;;
      000|"")
        fail "https://${HOST}${CALLBACK_PATH} did not respond publicly; curl: $(tr '\n' ' ' <"${CURL_ERR}")"
        ;;
      *)
        fail "https://${HOST}${CALLBACK_PATH} returned unexpected HTTP ${HTTP_CODE} from ${REMOTE_IP:-unknown} server ${SERVER:-unknown}"
        ;;
    esac

    rm -f "${HEADER_FILE}" "${BODY_FILE}" "${CURL_ERR}"
done <<<"${CALLBACK_PROBES}"

if [ "${FAILURES}" -gt 0 ]; then
  echo "Octelium e2e check failed with ${FAILURES} failure(s)." >&2
  exit 1
fi

echo "Octelium e2e check passed."
