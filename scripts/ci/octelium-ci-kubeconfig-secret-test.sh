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
  printf 'whoami\n' >>"$TEST_PROBE_LOG"
  exit "${TEST_PROBE_EXIT:-0}"
fi
if [[ " $* " == *" create --raw /apis/authorization.k8s.io/v1/selfsubjectaccessreviews -f - "* ]]; then
  request="$(cat)"
  if jq -e '
    .apiVersion == "authorization.k8s.io/v1" and
    .kind == "SelfSubjectAccessReview" and
    .spec == {
      resourceAttributes: {
        group: "*",
        resource: "*",
        verb: "*",
        namespace: ""
      }
    }
  ' >/dev/null <<<"$request"; then
    printf 'resource-review\n' >>"$TEST_PROBE_LOG"
    jq -cn --argjson allowed "${TEST_RESOURCE_AUTH_ALLOWED:-true}" \
      '{status: {allowed: $allowed}}'
    exit 0
  fi
  if jq -e '
    .apiVersion == "authorization.k8s.io/v1" and
    .kind == "SelfSubjectAccessReview" and
    .spec == {
      nonResourceAttributes: {
        path: "/*",
        verb: "*"
      }
    }
  ' >/dev/null <<<"$request"; then
    printf 'non-resource-review\n' >>"$TEST_PROBE_LOG"
    jq -cn --argjson allowed "${TEST_NONRESOURCE_AUTH_ALLOWED:-true}" \
      '{status: {allowed: $allowed}}'
    exit 0
  fi
  echo "unexpected SelfSubjectAccessReview payload" >&2
  exit 1
fi
exec "$REAL_KUBECTL" "$@"
MOCK

cat >"${test_dir}/octeliumctl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s %s\n' "${1:-}" "${2:-}" >>"$TEST_OCTELIUM_LOG"
case "${1:-} ${2:-}" in
"create secret")
  secret_name="$3"
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--file" ]]; then
      cp "$2" "$TEST_CAPTURED_KUBECONFIG"
      break
    fi
    shift
  done
  if [[ "${TEST_CREATE_MODE:-success}" == "fail-absent" ]]; then
    exit 1
  fi
  printf '%s\n' "$secret_name" >>"$TEST_SECRET_STATE"
  [[ "${TEST_CREATE_MODE:-success}" != "fail-after-commit" ]]
  ;;
"get secret")
  secret_name="$3"
  if [[ "${TEST_SECRET_GET_EXIT:-0}" -ne 0 ]]; then
    echo 'gRPC error Unavailable: unavailable' >&2
    exit "$TEST_SECRET_GET_EXIT"
  fi
  if rg -Fxq "$secret_name" "$TEST_SECRET_STATE"; then
    jq -cn --arg name "$secret_name" '{metadata: {name: $name}}'
  else
    echo 'gRPC error NotFound: Secret not found' >&2
    exit 1
  fi
  ;;
"get services")
  [[ "${TEST_SERVICE_LIST_EXIT:-0}" -eq 0 ]] || exit "$TEST_SERVICE_LIST_EXIT"
  jq -n \
    --arg ci "${TEST_CI_SECRET_REF:-homelab-ci-kubeconfig}" \
    --arg human "${TEST_HUMAN_SECRET_REF:-homelab-ci-kubeconfig}" \
    --argjson malformed "${TEST_MALFORMED_SERVICE:-false}" '
      {items: ((if $malformed then [{metadata: {name: "broken"}, spec: "malformed"}] else [] end) + [
        {
          metadata: {name: "kubernetes-api-ci"},
          spec: {config: {kubernetes: {kubeconfig: {fromSecret: $ci}}}}
        },
        {
          metadata: {name: "kubernetes-api.homelab"},
          spec: {config: {kubernetes: {kubeconfig: {fromSecret: $human}}}}
        }
      ])}
    '
  ;;
"delete secret")
  secret_name="$3"
  if [[ "${TEST_DELETE_NOOP:-0}" -eq 0 ]]; then
    awk -v name="$secret_name" '$0 != name' "$TEST_SECRET_STATE" >"${TEST_SECRET_STATE}.next"
    mv "${TEST_SECRET_STATE}.next" "$TEST_SECRET_STATE"
  fi
  exit "${TEST_DELETE_EXIT:-0}"
  ;;
*)
  echo "unexpected octeliumctl call: $*" >&2
  exit 1
  ;;
esac
MOCK
chmod +x "${test_dir}/kubectl" "${test_dir}/octeliumctl"

export REAL_KUBECTL="$real_kubectl"
export TEST_PROBE_LOG="${test_dir}/probe.log"
export TEST_OCTELIUM_LOG="${test_dir}/octelium.log"
export TEST_CAPTURED_KUBECONFIG="${test_dir}/captured-kubeconfig"
export TEST_SECRET_STATE="${test_dir}/secret-state"

reset_test_state() {
	: >"$TEST_PROBE_LOG"
	: >"$TEST_OCTELIUM_LOG"
	: >"$TEST_SECRET_STATE"
	rm -f -- "$TEST_CAPTURED_KUBECONFIG"
	unset TEST_PROBE_EXIT TEST_RESOURCE_AUTH_ALLOWED TEST_NONRESOURCE_AUTH_ALLOWED
	unset TEST_CREATE_MODE TEST_SECRET_GET_EXIT TEST_SERVICE_LIST_EXIT
	unset TEST_CI_SECRET_REF TEST_HUMAN_SECRET_REF TEST_DELETE_NOOP TEST_DELETE_EXIT
	unset TEST_MALFORMED_SERVICE
}

assert_no_rotation() {
	[[ ! -s "$TEST_OCTELIUM_LOG" ]] || {
		echo "Octelium was called before kubeconfig validation completed" >&2
		exit 1
	}
}

reset_test_state
write_kubeconfig "https://10.1.0.216:6443" "${test_dir}/wrong-server"
if OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/wrong-server" >/dev/null 2>&1; then
	echo "Wrong Kubernetes server was accepted" >&2
	exit 1
fi
assert_no_rotation

reset_test_state
write_kubeconfig "https://10.1.0.199:6443" "${test_dir}/multiple-ca" "$multi_ca_data"
if OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/multiple-ca" >/dev/null 2>&1; then
	echo "Multiple Kubernetes CA certificates were accepted" >&2
	exit 1
fi
assert_no_rotation

reset_test_state
write_kubeconfig "https://10.1.0.199:6443" "${test_dir}/valid"
if OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/valid" \
	--secret-name homelab-ci-kubeconfig-20260829T140000Z >/dev/null 2>&1; then
	echo "Octelium-invalid uppercase Secret name was accepted" >&2
	exit 1
fi
assert_no_rotation

reset_test_state
if TEST_PROBE_EXIT=1 OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" \
	OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/valid" >/dev/null 2>&1; then
	echo "Failed authenticated probe was accepted" >&2
	exit 1
fi
assert_no_rotation

reset_test_state
if TEST_RESOURCE_AUTH_ALLOWED=false OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" \
	OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/valid" >/dev/null 2>&1; then
	echo "Kubeconfig without cluster-wide resource access was accepted" >&2
	exit 1
fi
assert_no_rotation

reset_test_state
if TEST_NONRESOURCE_AUTH_ALLOWED=false OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" \
	OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/valid" >/dev/null 2>&1; then
	echo "Kubeconfig without non-resource access was accepted" >&2
	exit 1
fi
assert_no_rotation

reset_test_state
if TEST_CREATE_MODE=fail-after-commit OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" \
	OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/valid" \
	--secret-name homelab-ci-kubeconfig-20260829t130000z \
	>"${test_dir}/ambiguous.out" 2>&1; then
	echo "Failed Secret creation was accepted" >&2
	exit 1
fi
rg -q 'outcome is ambiguous' "${test_dir}/ambiguous.out"
rg -q 'do not retry or choose another name' "${test_dir}/ambiguous.out"
[[ "$(cat "$TEST_SECRET_STATE")" == "homelab-ci-kubeconfig-20260829t130000z" ]]
[[ "$(tail -n 1 "$TEST_OCTELIUM_LOG")" == "get secret" ]]

reset_test_state
printf '%s\n' homelab-ci-kubeconfig-20260829t120000z >"$TEST_SECRET_STATE"
if TEST_CI_SECRET_REF=homelab-ci-kubeconfig-20260829t120000z \
	OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --retire-secret homelab-ci-kubeconfig-20260829t120000z \
	>/dev/null 2>&1; then
	echo "Referenced Octelium Secret was retired" >&2
	exit 1
fi
! rg -q '^delete secret$' "$TEST_OCTELIUM_LOG"

reset_test_state
printf '%s\n' homelab-ci-kubeconfig-20260829t120000z >"$TEST_SECRET_STATE"
if TEST_SECRET_GET_EXIT=1 OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --retire-secret homelab-ci-kubeconfig-20260829t120000z \
	>/dev/null 2>&1; then
	echo "Unknown Octelium Secret lookup was treated as absence" >&2
	exit 1
fi
! rg -q '^delete secret$' "$TEST_OCTELIUM_LOG"

reset_test_state
printf '%s\n' homelab-ci-kubeconfig-20260829t120000z >"$TEST_SECRET_STATE"
if TEST_MALFORMED_SERVICE=true OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --retire-secret homelab-ci-kubeconfig-20260829t120000z \
	>/dev/null 2>&1; then
	echo "Malformed Octelium Service list allowed Secret retirement" >&2
	exit 1
fi
! rg -q '^delete secret$' "$TEST_OCTELIUM_LOG"

reset_test_state
printf '%s\n' homelab-ci-kubeconfig homelab-ci-kubeconfig-20260829t120000z >"$TEST_SECRET_STATE"
OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --retire-secret homelab-ci-kubeconfig-20260829t120000z >/dev/null
[[ "$(cat "$TEST_SECRET_STATE")" == "homelab-ci-kubeconfig" ]]
[[ "$(rg -c '^delete secret$' "$TEST_OCTELIUM_LOG")" -eq 1 ]]

reset_test_state
printf '%s\n' homelab-ci-kubeconfig homelab-ci-kubeconfig-20260829t120000z >"$TEST_SECRET_STATE"
if TEST_DELETE_NOOP=1 OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --retire-secret homelab-ci-kubeconfig-20260829t120000z \
	>/dev/null 2>&1; then
	echo "Unverified Octelium Secret deletion was accepted" >&2
	exit 1
fi
rg -q '^homelab-ci-kubeconfig-20260829t120000z$' "$TEST_SECRET_STATE"

reset_test_state
printf '%s\n' homelab-ci-kubeconfig >"$TEST_SECRET_STATE"
OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --retire-secret homelab-ci-kubeconfig-20260829t120000z >/dev/null
! rg -q '^delete secret$' "$TEST_OCTELIUM_LOG"

reset_test_state
TEST_PROBE_EXIT=0 OCTELIUM_KUBECTL_BIN="${test_dir}/kubectl" \
	OCTELIUMCTL_BIN="${test_dir}/octeliumctl" \
	"$rotation_script" --kubeconfig "${test_dir}/valid" \
	--secret-name homelab-ci-kubeconfig-20260829t140000z >/dev/null
[[ "$(cat "$TEST_OCTELIUM_LOG")" == "create secret" ]]
[[ "$(cat "$TEST_PROBE_LOG")" == $'whoami\nresource-review\nnon-resource-review' ]]
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
