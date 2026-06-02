#!/usr/bin/env bash
set -euo pipefail

namespace="${NAMESPACE:-media}"
deployment="${DEPLOYMENT:-prowlarr}"
config_path="/config/config.xml"
process_pattern="${PROCESS_PATTERN:-/app/prowlarr/bin/Prowlarr}"
service_name="${SERVICE_NAME:-svc-prowlarr}"

validate_kubernetes_name() {
  local label="$1"
  local value="$2"

  if [[ ! "$value" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
    echo "${label} must be a Kubernetes DNS label; got: ${value}" >&2
    exit 2
  fi
}

validate_process_pattern() {
  if [[ ! "$process_pattern" =~ ^[A-Za-z0-9_./:-]+$ ]]; then
    echo "PROCESS_PATTERN contains unsupported characters; use only letters, numbers, '_', '.', '/', ':', and '-'." >&2
    exit 2
  fi
}

usage() {
  cat <<'USAGE'
Usage: scripts/prowlarr-recover-auth.sh [--yes]

BREAK-GLASS RECOVERY: this is not a normal GitOps reconciliation path.
Use it only to recover Prowlarr authentication, then verify the repo-owned
configuration still represents the desired steady state.

Recovers a locked-out LinuxServer Prowlarr deployment by following the Servarr
procedure in-place inside the running pod:
  1. stop the internal s6 Prowlarr service
  2. back up /config/config.xml
  3. remove the AuthenticationMethod line
  4. start the internal s6 Prowlarr service

Environment overrides:
  NAMESPACE        Kubernetes namespace, default: media
  DEPLOYMENT       Prowlarr Deployment name, default: prowlarr
  SERVICE_NAME     s6 service name, default: svc-prowlarr
  PROCESS_PATTERN  Prowlarr process pattern, default: /app/prowlarr/bin/Prowlarr
USAGE
}

confirm="false"
case "${1:-}" in
  --yes)
    confirm="true"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  "")
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

validate_kubernetes_name NAMESPACE "$namespace"
validate_kubernetes_name DEPLOYMENT "$deployment"
validate_kubernetes_name SERVICE_NAME "$service_name"
validate_process_pattern

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required but was not found in PATH" >&2
  exit 1
fi

if [[ "$confirm" != "true" ]]; then
  cat <<EOF
BREAK-GLASS RECOVERY: this is not a normal GitOps reconciliation path.
Use it only to recover Prowlarr authentication, then verify the repo-owned
configuration still represents the desired steady state.

This will temporarily change runtime state inside the live Prowlarr pod:
  - stop the ${service_name} s6 service in deployment/${deployment}
  - edit ${config_path} on the mounted /config PVC after writing a backup
  - start the ${service_name} s6 service again

Re-run with --yes to continue.
EOF
  exit 1
fi

remote_service_script='set -eu
service_name="$1"
action="$2"
svc_dir="$(find /run -path "*/servicedirs/${service_name}" -type d 2>/dev/null | grep "/run/s6-rc:" | head -n 1 || true)"
if [ -z "$svc_dir" ]; then
  echo "Could not find s6 service directory for ${service_name}" >&2
  exit 1
fi
s6-svc "$action" "$svc_dir"'

remote_process_absent_script='set -eu
process_pattern="${PROCESS_PATTERN:?PROCESS_PATTERN is required}"
for _ in $(seq 1 60); do
  if command -v pgrep >/dev/null 2>&1; then
    if ! pgrep -f -- "$process_pattern" >/dev/null; then
      exit 0
    fi
  elif ! ps -ef | grep -F -- "$process_pattern" | grep -v grep >/dev/null; then
    exit 0
  fi
  sleep 1
done
echo "Timed out waiting for process to stop: ${process_pattern}" >&2
exit 1'

remote_process_present_script='set -eu
process_pattern="${PROCESS_PATTERN:?PROCESS_PATTERN is required}"
for _ in $(seq 1 60); do
  if command -v pgrep >/dev/null 2>&1; then
    if pgrep -f -- "$process_pattern" >/dev/null; then
      exit 0
    fi
  elif ps -ef | grep -F -- "$process_pattern" | grep -v grep >/dev/null; then
    exit 0
  fi
  sleep 1
done
echo "Timed out waiting for process to start: ${process_pattern}" >&2
exit 1'

start_service() {
  kubectl -n "$namespace" exec "$pod" -- /bin/sh -ec "$remote_service_script" sh "$service_name" -u
}

stop_service() {
  kubectl -n "$namespace" exec "$pod" -- /bin/sh -ec "$remote_service_script" sh "$service_name" -d
  kubectl -n "$namespace" exec "$pod" -- env PROCESS_PATTERN="$process_pattern" /bin/sh -ec "$remote_process_absent_script"
}

wait_for_start() {
  kubectl -n "$namespace" exec "$pod" -- env PROCESS_PATTERN="$process_pattern" /bin/sh -ec "$remote_process_present_script"
}

echo "Checking live Prowlarr resources..."
kubectl -n "$namespace" get deployment "$deployment" >/dev/null

pod="$(
  kubectl -n "$namespace" get pod \
    -l "app.kubernetes.io/name=${deployment},app.kubernetes.io/instance=${deployment}" \
    -o jsonpath='{.items[0].metadata.name}'
)"

if [[ -z "$pod" ]]; then
  echo "No running Prowlarr pod found for deployment/${deployment} in namespace ${namespace}" >&2
  exit 1
fi

restore_on_exit="false"
cleanup() {
  if [[ "${restore_on_exit}" == "true" ]]; then
    start_service >/dev/null || true
  fi
}
trap cleanup EXIT

echo "Stopping ${service_name} inside pod/${pod}..."
stop_service
restore_on_exit="true"

echo "Backing up config.xml and removing AuthenticationMethod..."
kubectl -n "$namespace" exec "$pod" -- /bin/sh -ec '
  set -eu
  config="/config/config.xml"
  if [ ! -f "$config" ]; then
    echo "$config does not exist" >&2
    exit 1
  fi

  if ! grep -q "<AuthenticationMethod>" "$config"; then
    echo "AuthenticationMethod is already absent"
    exit 0
  fi

  backup="/config/config.xml.auth-recovery.$(date -u +%Y%m%dT%H%M%SZ)"
  tmp="/config/config.xml.auth-recovery.tmp"
  cp "$config" "$backup"
  sed "/<AuthenticationMethod>.*<\/AuthenticationMethod>/d" "$backup" > "$tmp"
  mv "$tmp" "$config"

  if grep -q "<AuthenticationMethod>" "$config"; then
    echo "AuthenticationMethod is still present after edit" >&2
    exit 1
  fi

  echo "Backup written to ${backup}"
'

echo "Starting ${service_name}..."
start_service

echo "Waiting for Prowlarr to start..."
wait_for_start
restore_on_exit="false"
trap - EXIT

echo "Checking that AuthenticationMethod is unset or None after startup..."
auth_method="$(
  kubectl -n "$namespace" exec "$pod" -- /bin/sh -ec '
    sed -n "s/.*<AuthenticationMethod>\(.*\)<\/AuthenticationMethod>.*/\1/p" /config/config.xml | head -n 1
  ' 2>/dev/null
)"
case "$auth_method" in
  ""|None)
    ;;
  *)
    echo "AuthenticationMethod is ${auth_method}; Prowlarr may not enter password reset flow." >&2
    exit 1
    ;;
esac

cat <<'EOF'
Prowlarr auth recovery is ready. Open https://prowlarr.stinkyboi.com and set a new password.

Post-recovery checklist:
  - Confirm the repo-owned Prowlarr manifests still describe the desired steady state.
  - Record any durable configuration change in git instead of leaving it only on the PVC.
  - Keep the timestamped /config/config.xml.auth-recovery.* backup until the new login is verified.
EOF
