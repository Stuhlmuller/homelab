#!/usr/bin/env bash
set -euo pipefail

namespace="${NAMESPACE:-media}"
deployment="${DEPLOYMENT:-prowlarr}"
config_path="/config/config.xml"
process_pattern="${PROCESS_PATTERN:-/app/prowlarr/bin/Prowlarr}"
service_name="${SERVICE_NAME:-svc-prowlarr}"

usage() {
  cat <<'USAGE'
Usage: scripts/prowlarr-recover-auth.sh [--yes]

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

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required but was not found in PATH" >&2
  exit 1
fi

if [[ "$confirm" != "true" ]]; then
  cat <<EOF
This will temporarily change runtime state inside the live Prowlarr pod:
  - stop the ${service_name} s6 service in deployment/${deployment}
  - edit ${config_path} on the mounted /config PVC after writing a backup
  - start the ${service_name} s6 service again

Re-run with --yes to continue.
EOF
  exit 1
fi

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

start_service() {
  kubectl -n "$namespace" exec "$pod" -- /bin/sh -ec "
    set -eu
    svc_dir=\"\$(find /run -path '*/servicedirs/${service_name}' -type d 2>/dev/null | grep '/run/s6-rc:' | head -n 1 || true)\"
    if [ -z \"\$svc_dir\" ]; then
      echo \"Could not find s6 service directory for ${service_name}\" >&2
      exit 1
    fi
    s6-svc -u \"\$svc_dir\"
  "
}

restore_on_exit="false"
cleanup() {
  if [[ "${restore_on_exit}" == "true" ]]; then
    start_service >/dev/null || true
  fi
}
trap cleanup EXIT

echo "Stopping ${service_name} inside pod/${pod}..."
kubectl -n "$namespace" exec "$pod" -- /bin/sh -ec "
  set -eu
  svc_dir=\"\$(find /run -path '*/servicedirs/${service_name}' -type d 2>/dev/null | grep '/run/s6-rc:' | head -n 1 || true)\"
  if [ -z \"\$svc_dir\" ]; then
    echo \"Could not find s6 service directory for ${service_name}\" >&2
    exit 1
  fi
  s6-svc -d \"\$svc_dir\"
  for _ in \$(seq 1 60); do
    if ! ps -ef | grep '${process_pattern}' | grep -v grep >/dev/null; then
      exit 0
    fi
    sleep 1
  done
  s6-svstat \"\$svc_dir\" || true
  echo \"Timed out waiting for ${service_name} to stop\" >&2
  exit 1
"
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
kubectl -n "$namespace" exec "$pod" -- /bin/sh -ec "
  set -eu
  for _ in \$(seq 1 60); do
    if ps -ef | grep '${process_pattern}' | grep -v grep >/dev/null; then
      exit 0
    fi
    sleep 1
  done
  echo \"Timed out waiting for Prowlarr process to start\" >&2
  exit 1
"
restore_on_exit="false"
trap - EXIT

echo "Checking that AuthenticationMethod is unset or None after startup..."
auth_method="$(
  kubectl -n "$namespace" exec "$pod" -- /bin/sh -ec \
    "sed -n 's/.*<AuthenticationMethod>\\(.*\\)<\\/AuthenticationMethod>.*/\\1/p' '${config_path}' | head -n 1" \
    2>/dev/null
)"
case "$auth_method" in
  ""|None)
    ;;
  *)
    echo "AuthenticationMethod is ${auth_method}; Prowlarr may not enter password reset flow." >&2
    exit 1
    ;;
esac

echo "Prowlarr auth recovery is ready. Open https://prowlarr.stinkyboi.com and set a new password."
