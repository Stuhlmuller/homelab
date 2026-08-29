#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
rotation_script="${repo_root}/scripts/octelium-ci-kubeconfig-secret.sh"
real_kubectl="$(command -v kubectl)"

umask 077
test_dir="$(mktemp -d)"
cleanup() {
	[[ ! -d "$test_dir" ]] || rm -rf -- "$test_dir"
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
	-subj /CN=kubeconfig-test-ca \
	-keyout "${test_dir}/ca-key.pem" -out "${test_dir}/ca.pem" >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes -subj /CN=kubeconfig-test-user \
	-keyout "${test_dir}/client-key.pem" -out "${test_dir}/client.csr" >/dev/null 2>&1
openssl x509 -req -days 1 -in "${test_dir}/client.csr" \
	-CA "${test_dir}/ca.pem" -CAkey "${test_dir}/ca-key.pem" -CAcreateserial \
	-out "${test_dir}/client.pem" >/dev/null 2>&1

ca_data="$(openssl base64 -A -in "${test_dir}/ca.pem")"
multi_ca_data="$(cat "${test_dir}/ca.pem" "${test_dir}/ca.pem" | openssl base64 -A)"
client_certificate_data="$(openssl base64 -A -in "${test_dir}/client.pem")"
client_key_data="$(openssl base64 -A -in "${test_dir}/client-key.pem")"

write_kubeconfig() {
	local server="$1"
	local output="$2"
	local embedded_ca="${3:-$ca_data}"
	jq -n \
		--arg server "$server" \
		--arg ca_key "certificate-authority-data" \
		--arg ca "$embedded_ca" \
		--arg certificate_key "client-certificate-data" \
		--arg certificate "$client_certificate_data" \
		--arg private_key_key "client-key-data" \
		--arg private_key "$client_key_data" '
      {
        apiVersion: "v1",
        kind: "Config",
        "current-context": "selected",
        clusters: [
          {name: "selected", cluster: ({server: $server} | .[$ca_key] = $ca)},
          {name: "ignored", cluster: {server: "https://192.0.2.1:6443"}}
        ],
        contexts: [
          {name: "selected", context: {cluster: "selected", user: "selected"}},
          {name: "ignored", context: {cluster: "ignored", user: "ignored"}}
        ],
        users: [
          {
            name: "selected",
            user: (
              {}
              | .[$certificate_key] = $certificate
              | .[$private_key_key] = $private_key
            )
          },
          {name: "ignored", user: {token: "x"}}
        ]
      }
    ' >"$output"
}

cat >"${test_dir}/kubectl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ " $* " == *" auth whoami "* ]]; then
  printf 'probe\n' >>"$TEST_PROBE_LOG"
  exit "${TEST_PROBE_EXIT:-0}"
fi
exec "$REAL_KUBECTL" "$@"
MOCK

cat >"${test_dir}/octeliumctl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s %s\n' "${1:-}" "${2:-}" >>"$TEST_OCTELIUM_LOG"
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--file" ]]; then
    cp "$2" "$TEST_CAPTURED_KUBECONFIG"
    break
  fi
  shift
done
MOCK
chmod +x "${test_dir}/kubectl" "${test_dir}/octeliumctl"

export REAL_KUBECTL="$real_kubectl"
export TEST_PROBE_LOG="${test_dir}/probe.log"
export TEST_OCTELIUM_LOG="${test_dir}/octelium.log"
export TEST_CAPTURED_KUBECONFIG="${test_dir}/captured-kubeconfig"

assert_no_rotation() {
	[[ ! -s "$TEST_OCTELIUM_LOG" ]] || {
		echo "Octelium was called before kubeconfig validation completed" >&2
		exit 1
	}
}

write_kubeconfig "https://10.1.0.216:6443" "${test_dir}/wrong-server"
if OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/wrong-server" >/dev/null 2>&1; then
	echo "Wrong Kubernetes server was accepted" >&2
	exit 1
fi
assert_no_rotation

write_kubeconfig "https://10.1.0.199:6443" "${test_dir}/multiple-ca" "$multi_ca_data"
if OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/multiple-ca" >/dev/null 2>&1; then
	echo "Multiple Kubernetes CA certificates were accepted" >&2
	exit 1
fi
assert_no_rotation

write_kubeconfig "https://10.1.0.199:6443" "${test_dir}/valid"
if OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/valid" \
	--secret-name homelab-ci-kubeconfig-20260829T140000Z >/dev/null 2>&1; then
	echo "Octelium-invalid uppercase Secret name was accepted" >&2
	exit 1
fi
assert_no_rotation

if TEST_PROBE_EXIT=1 OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" \
	OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/valid" >/dev/null 2>&1; then
	echo "Failed authenticated probe was accepted" >&2
	exit 1
fi
assert_no_rotation

TEST_PROBE_EXIT=0 OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" \
	OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/valid" \
	--secret-name homelab-ci-kubeconfig-20260829t140000z >/dev/null

[[ "$(cat "$TEST_OCTELIUM_LOG")" == "create secret" ]]
"$real_kubectl" --kubeconfig "$TEST_CAPTURED_KUBECONFIG" config view --raw -o json |
	jq -e '
    .["current-context"] == "selected" and
    (.contexts | length) == 1 and
    (.clusters | length) == 1 and
    (.users | length) == 1 and
    .clusters[0].cluster.server == "https://10.1.0.199:6443"
  ' >/dev/null
if rg -q 'ignored' "$TEST_CAPTURED_KUBECONFIG"; then
	echo "Unselected kubeconfig entries reached Octelium" >&2
	exit 1
fi

echo "Octelium kubeconfig validation tests passed."
