#!/usr/bin/env bash
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  echo "error: diagnostics must run only from a private operator terminal" >&2
  exit 1
fi

for command_name in jq kubectl octelium; do
  command -v "$command_name" >/dev/null || {
    echo "error: ${command_name} is required" >&2
    exit 1
  }
done

umask 077
readonly domain="stinkyboi.com"
readonly service="kubernetes-api.homelab"
readonly local_server="http://127.0.0.1:16443"
state_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-grafana-diagnostics.XXXXXX")"
readonly state_dir
readonly octelium_home="${state_dir}/octelium"
readonly kubeconfig="${state_dir}/.kube/${service}.${domain}"
octelium_cmd=(octelium --homedir "$octelium_home" --domain "$domain")
login_attempted="false"
connect_attempted="false"

cleanup() {
  local status="$?"
  local cleanup_failed="false"
  trap - EXIT INT TERM

  if [[ "$connect_attempted" == "true" ]] &&
    ! HOME="$state_dir" "${octelium_cmd[@]}" disconnect >/dev/null; then
    echo "error: Octelium disconnect failed; inspect the client session" >&2
    cleanup_failed="true"
    status=1
  fi
  if [[ "$login_attempted" == "true" ]] &&
    ! HOME="$state_dir" "${octelium_cmd[@]}" --logout version >/dev/null; then
    echo "error: Octelium logout failed; revoke the client session" >&2
    cleanup_failed="true"
    status=1
  fi
  if [[ "$cleanup_failed" == "true" ]]; then
    echo "error: cleanup failed; temporary state preserved at ${state_dir}" >&2
  elif [[ -d "$state_dir" ]] && ! rm -rf -- "$state_dir"; then
    echo "error: temporary diagnostic state remains at ${state_dir}" >&2
    status=1
  fi
  exit "$status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

login_attempted="true"
HOME="$state_dir" "${octelium_cmd[@]}" login

status_json="$(HOME="$state_dir" "${octelium_cmd[@]}" status -o json)"
jq -e '
  .user.metadata.name == "homelab-owner" and
  .user.spec.type == "HUMAN"
' >/dev/null <<<"$status_json" || {
  echo "error: diagnostics require the Entra-backed homelab-owner HUMAN identity" >&2
  exit 1
}

connect_attempted="true"
HOME="$state_dir" "${octelium_cmd[@]}" connect \
  --detach \
  --implementation gvisor \
  --no-dns \
  --publish "${service}:127.0.0.1:16443"

status_json="$(HOME="$state_dir" "${octelium_cmd[@]}" status -o json)"
jq -e '
  .session.status.type == "CLIENT" and
  .session.status.isConnected == true
' >/dev/null <<<"$status_json" || {
  echo "error: Octelium did not establish a connected CLIENT session" >&2
  exit 1
}

HOME="$state_dir" "${octelium_cmd[@]}" config "$service"
[[ -f "$kubeconfig" ]] || {
  echo "error: Octelium did not create the expected kubeconfig" >&2
  exit 1
}
chmod 0600 "$kubeconfig"

server="$(kubectl --kubeconfig "$kubeconfig" config view \
  --minify -o jsonpath='{.clusters[0].cluster.server}')"
if [[ "$server" != "$local_server" ]]; then
  echo "error: diagnostics must use the Octelium localhost bridge, got ${server}" >&2
  exit 1
fi

echo "Diagnostic output may contain sensitive data; keep this terminal private." >&2
kubectl_cmd=(kubectl --kubeconfig "$kubeconfig" --request-timeout=15s)
"${kubectl_cmd[@]}" version
"${kubectl_cmd[@]}" -n monitoring get deploy,rs,pod,svc,endpoints,endpointslice,pvc \
  -l app.kubernetes.io/name=grafana -o wide
"${kubectl_cmd[@]}" -n monitoring describe deployment grafana
"${kubectl_cmd[@]}" -n monitoring describe service grafana
"${kubectl_cmd[@]}" -n monitoring get events \
  --field-selector involvedObject.namespace=monitoring \
  --sort-by=.lastTimestamp | tail -80

if ! pods="$(
  "${kubectl_cmd[@]}" -n monitoring get pod \
    -l app.kubernetes.io/name=grafana \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)"; then
  echo "error: unable to enumerate Grafana pods" >&2
  exit 1
fi

while IFS= read -r pod; do
  [[ -n "$pod" ]] || continue
  echo "== describe ${pod} =="
  "${kubectl_cmd[@]}" -n monitoring describe pod "$pod"
  echo "== logs ${pod} =="
  "${kubectl_cmd[@]}" -n monitoring logs "$pod" --all-containers --tail=200 || true
  echo "== previous logs ${pod} =="
  "${kubectl_cmd[@]}" -n monitoring logs "$pod" --all-containers --previous --tail=200 || true
done <<<"$pods"
