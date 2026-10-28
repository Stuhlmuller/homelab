#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 0 && "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REPOSITORY:-}" == Stuhlmuller/homelab ]]
[[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch && "${GITHUB_REF:-}" == refs/heads/main ]]
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ && "${EXPECTED_SHA:-}" == "$GITHUB_SHA" ]]
[[ "${KUBE_API_SERVER_URL:-}" == https://kubernetes-api-ci.stinkyboi.com ]]
: "${OCTELIUM_AUTH_TOKEN:?The protected CI cluster credential is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP must be set}"
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]
[[ "$(git ls-remote https://github.com/Stuhlmuller/homelab.git refs/heads/main | cut -f1)" == "$GITHUB_SHA" ]]
[[ ! -e "$HOME/.kube/config" ]]
if grep -Eq '(^|[[:space:]])harbor[.]stinkyboi[.]com([[:space:]]|$)|# homelab-harbor-ci$' /etc/hosts; then
  echo 'Harbor hosts entry already exists.' >&2
  exit 1
fi
python3 -I scripts/ci/harbor-chart-publish.py --check

umask 077
scratch="$(mktemp -d "${RUNNER_TEMP}/harbor-charts.XXXXXX")"
forward_pid=""
hosts_added=false
kubeconfig_added=false
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$forward_pid" ]]; then
    kill -TERM "$forward_pid" 2>/dev/null || true
    wait "$forward_pid" 2>/dev/null || true
  fi
  if "$hosts_added"; then
    sudo -n sed -i '/# homelab-harbor-ci$/d' /etc/hosts || status=1
  fi
  if "$kubeconfig_added"; then
    rm -f -- "$HOME/.kube/config" || status=1
  fi
  rm -rf -- "$scratch" || status=1
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

kubeconfig_added=true
bash scripts/ci/install-kubeconfig.sh
kubectl --request-timeout=15s version >/dev/null
cp "$(command -v kubectl)" "$scratch/kubectl"
chmod 700 "$scratch/kubectl"
sudo -n setcap cap_net_bind_service=+ep "$scratch/kubectl"
hosts_added=true
printf '%s\n' '127.0.0.1 harbor.stinkyboi.com # homelab-harbor-ci' | sudo -n tee -a /etc/hosts >/dev/null

ready=false
for attempt in 1 2 3; do
  timeout --signal=TERM --kill-after=5s 19800 \
    "$scratch/kubectl" --kubeconfig "$HOME/.kube/config" \
    --namespace traefik port-forward --address 127.0.0.1 \
    service/traefik-private 443:443 >"$scratch/port-forward.log" 2>&1 &
  forward_pid=$!
  for _ in {1..30}; do
    if ! kill -0 "$forward_pid" 2>/dev/null; then break; fi
    status="$(curl --silent --show-error --noproxy '*' --max-time 5 \
      --output /dev/null --write-out '%{http_code}' https://harbor.stinkyboi.com/v2/ 2>/dev/null)" || status=""
    if [[ "$status" == 401 ]]; then ready=true; break; fi
    sleep 2
  done
  if "$ready"; then break; fi
  kill -TERM "$forward_pid" 2>/dev/null || true
  wait "$forward_pid" 2>/dev/null || true
  forward_pid=""
  sleep "$attempt"
done
"$ready" || { echo 'Private Harbor route is not ready.' >&2; exit 1; }

aws ssm get-parameter --region us-west-2 \
  --name /homelab/harbor/mirror-robot-push-password --with-decryption \
  --query Parameter.Value --output text >"$scratch/publisher-password"
aws ssm get-parameter --region us-west-2 \
  --name /homelab/harbor/mirror-robot-pull-password --with-decryption \
  --query Parameter.Value --output text >"$scratch/reader-password"
[[ -s "$scratch/publisher-password" && -s "$scratch/reader-password" ]]
helm registry login harbor.stinkyboi.com --username "robot\$mirror+publisher" \
  --password-stdin --registry-config "$scratch/publisher-helm.json" \
  <"$scratch/publisher-password" >/dev/null
helm registry login harbor.stinkyboi.com --username "robot\$mirror+pull" \
  --password-stdin --registry-config "$scratch/reader-helm.json" \
  <"$scratch/reader-password" >/dev/null
skopeo login --authfile "$scratch/reader-skopeo.json" --username "robot\$mirror+pull" \
  --password-stdin harbor.stinkyboi.com <"$scratch/reader-password" >/dev/null
rm -f -- "$scratch/publisher-password" "$scratch/reader-password"
python3 -I scripts/ci/harbor-chart-publish.py --publish \
  "$scratch/reader-skopeo.json" "$scratch/reader-helm.json" "$scratch/publisher-helm.json"
