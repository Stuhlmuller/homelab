#!/usr/bin/env bash
set -euo pipefail

domain="octelium.stinkyboi.com"
version="0.35.0"
kubeconfig=""
kubecontext=""
wait_timeout="20m"

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-cluster-bootstrap.sh [options]

Bootstrap or upgrade the self-hosted Octelium Cluster in the homelab.

The script reads generated PostgreSQL and Redis passwords from the
octelium-storage-auth Kubernetes Secret, writes a temporary Octelium bootstrap
file outside git, then runs octops with Octelium ingress front-proxy mode so
the existing Istio gateway terminates TLS for:

  octelium.stinkyboi.com
  portal.octelium.stinkyboi.com
  octelium-api.octelium.stinkyboi.com

Options:
  --domain DOMAIN       Octelium Cluster domain. Default: octelium.stinkyboi.com
  --version VERSION     Octelium Cluster version. Default: 0.35.0
                        Use "latest" to omit --version.
  --kubeconfig PATH     Kubeconfig for the homelab cluster.
  --context NAME        Kube context for the homelab cluster.
  --wait-timeout VALUE  kubectl wait timeout. Default: 20m
  -h, --help            Show this help text.

Prerequisites:
  - platform-multus Argo CD Application synced and healthy
  - octelium-storage Argo CD Application synced and healthy
  - IaC/live/kubernetes-node-labels applied
  - octops, kubectl, and base64 installed locally
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      domain="$2"
      shift 2
      ;;
    --version)
      version="$2"
      shift 2
      ;;
    --kubeconfig)
      kubeconfig="$2"
      shift 2
      ;;
    --context)
      kubecontext="$2"
      shift 2
      ;;
    --wait-timeout)
      wait_timeout="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: $1 is required" >&2
    exit 127
  fi
}

kubectl_cmd=(kubectl)
octops_cmd=(octops)

if [[ -n "$kubeconfig" ]]; then
  kubectl_cmd+=(--kubeconfig "$kubeconfig")
  octops_cmd+=(--kubeconfig "$kubeconfig")
fi

if [[ -n "$kubecontext" ]]; then
  kubectl_cmd+=(--context "$kubecontext")
  octops_cmd+=(--kubecontext "$kubecontext")
fi

require_command kubectl
require_command octops
require_command base64

decode_base64() {
  if base64 --decode >/dev/null 2>&1 <<<""; then
    base64 --decode
  else
    base64 -D
  fi
}

jsonpath_secret() {
  local key="$1"
  "${kubectl_cmd[@]}" -n octelium-storage get secret octelium-storage-auth \
    -o "jsonpath={.data.${key}}" | decode_base64
}

require_label() {
  local node="$1"
  local label="$2"
  if ! "${kubectl_cmd[@]}" get node -l "$label" -o name | grep -Fxq "node/${node}"; then
    echo "error: node ${node} is missing required label ${label}" >&2
    exit 1
  fi
}

ensure_octelium_namespace_labels() {
  if ! "${kubectl_cmd[@]}" get namespace octelium >/dev/null 2>&1; then
    return 0
  fi

  "${kubectl_cmd[@]}" label namespace octelium \
    app.kubernetes.io/name=octelium \
    app.kubernetes.io/part-of=octelium \
    pod-security.kubernetes.io/enforce=privileged \
    pod-security.kubernetes.io/enforce-version=latest \
    pod-security.kubernetes.io/audit=restricted \
    pod-security.kubernetes.io/audit-version=latest \
    pod-security.kubernetes.io/warn=restricted \
    pod-security.kubernetes.io/warn-version=latest \
    --overwrite

  "${kubectl_cmd[@]}" annotate namespace octelium \
    "homelab.rst.io/privileged-namespace-justification=Octelium data-plane workloads are installed by octops and require privileged network access." \
    --overwrite
}

echo "Checking Octelium bootstrap prerequisites..."
"${kubectl_cmd[@]}" get crd network-attachment-definitions.k8s.cni.cncf.io >/dev/null
"${kubectl_cmd[@]}" -n kube-system rollout status daemonset/kube-multus-ds --timeout="${wait_timeout}"
"${kubectl_cmd[@]}" -n octelium-storage wait --for=condition=Ready pod -l app.kubernetes.io/name=octelium-postgres --timeout="${wait_timeout}"
"${kubectl_cmd[@]}" -n octelium-storage wait --for=condition=Ready pod -l app.kubernetes.io/name=octelium-redis --timeout="${wait_timeout}"
require_label zimaboard-0 octelium.com/node-mode-dataplane
require_label zimaboard-1 octelium.com/node-mode-controlplane
require_label zimaboard-2 octelium.com/node-mode-dataplane
ensure_octelium_namespace_labels

postgres_password="$(jsonpath_secret POSTGRES_PASSWORD)"
redis_password="$(jsonpath_secret REDIS_PASSWORD)"

for secret_name in POSTGRES_PASSWORD REDIS_PASSWORD; do
  secret_value="${postgres_password}"
  if [[ "$secret_name" == "REDIS_PASSWORD" ]]; then
    secret_value="${redis_password}"
  fi
  if [[ -z "$secret_value" || "$secret_value" == "REPLACE_ME" ]]; then
    echo "error: ${secret_name} is empty or still set to REPLACE_ME" >&2
    exit 1
  fi
done

bootstrap_file="$(mktemp "${TMPDIR:-/tmp}/octelium-bootstrap.XXXXXX")"
cleanup() {
  rm -f "$bootstrap_file"
}
trap cleanup EXIT

chmod 0600 "$bootstrap_file"
cat >"$bootstrap_file" <<EOF
spec:
  primaryStorage:
    postgresql:
      username: octelium
      password: "${postgres_password}"
      host: octelium-postgres.octelium-storage.svc.cluster.local
      port: 5432
      database: octelium
      isTLS: false
  secondaryStorage:
    redis:
      username: default
      password: "${redis_password}"
      host: octelium-redis.octelium-storage.svc.cluster.local
      port: 6379
      database: 0
      isTLS: false
EOF

if [[ -n "$("${kubectl_cmd[@]}" -n octelium get deploy -o name 2>/dev/null || true)" ]]; then
  action=(upgrade "$domain" --wait)
else
  action=(init "$domain" --bootstrap "$bootstrap_file")
fi

if [[ "$version" != "latest" ]]; then
  action+=(--version "$version")
fi

echo "Running octops ${action[0]} for ${domain} in front-proxy mode..."
run_octops() {
  OCTELIUM_INGRESS_FRONT_PROXY=true OCTELIUM_FRONT_PROXY_MODE=true "${octops_cmd[@]}" "$@"
}

if [[ "${action[0]}" == "upgrade" ]]; then
  printf 'y\n' | run_octops "${action[@]}"
else
  run_octops "${action[@]}"
fi
ensure_octelium_namespace_labels

echo "Waiting for Octelium workloads..."
for kind in deployment daemonset statefulset; do
  for workload in $("${kubectl_cmd[@]}" -n octelium get "$kind" -o name); do
    "${kubectl_cmd[@]}" -n octelium rollout status "$workload" --timeout="${wait_timeout}"
  done
done
"${kubectl_cmd[@]}" -n octelium get deploy,sts,ds,svc,pod
