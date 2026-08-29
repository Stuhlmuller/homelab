#!/usr/bin/env bash
set -euo pipefail

domain="stinkyboi.com"
secret_name="homelab-ci-kubeconfig"
kubeconfig=""
context=""
readonly expected_server="https://10.1.0.199:6443"
readonly kubectl_bin="${OCTELIUM_KUBECTL_BIN:-kubectl}"
readonly octeliumctl_bin="${OCTELIUMCTL_BIN:-octeliumctl}"

usage() {
	cat <<'USAGE'
Usage: scripts/octelium-ci-kubeconfig-secret.sh --kubeconfig PATH [options]

Validate, minify, and create an Octelium Secret for the CI and private
human/Cordium Kubernetes Services. Existing Secrets are never overwritten;
rotate through a new staged name and the documented Service cutover.

Options:
  --kubeconfig PATH   Source kubeconfig file (required).
  --context NAME      Context to select. Default: the file's current context.
  --domain DOMAIN     Octelium Cluster domain. Default: stinkyboi.com
  --secret-name NAME  New Octelium Secret name. Default: homelab-ci-kubeconfig
  -h, --help          Show this help.
USAGE
}

need_value() {
	[[ $# -ge 2 && -n "$2" ]] || {
		echo "error: $1 requires a value" >&2
		exit 2
	}
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--kubeconfig)
		need_value "$@"
		kubeconfig="$2"
		shift 2
		;;
	--context)
		need_value "$@"
		context="$2"
		shift 2
		;;
	--domain)
		need_value "$@"
		domain="$2"
		shift 2
		;;
	--secret-name)
		need_value "$@"
		secret_name="$2"
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

[[ -n "$kubeconfig" && -f "$kubeconfig" && -r "$kubeconfig" ]] || {
	echo "error: --kubeconfig must name a readable file" >&2
	exit 1
}
if [[ ! "$secret_name" =~ ^homelab-ci-kubeconfig(-[0-9]{8}t[0-9]{6}z)?$ ]]; then
	echo "error: --secret-name must be homelab-ci-kubeconfig or a lowercase UTC timestamped replacement" >&2
	exit 1
fi
for command_name in "$kubectl_bin" "$octeliumctl_bin" jq openssl; do
	command -v "$command_name" >/dev/null || {
		echo "error: ${command_name} is required" >&2
		exit 127
	}
done

umask 077
scratch_dir="$(mktemp -d)"
cleanup() {
	[[ ! -d "$scratch_dir" ]] || rm -rf -- "$scratch_dir"
}
trap cleanup EXIT

selected_json="${scratch_dir}/selected.json"
normalized_kubeconfig="${scratch_dir}/kubeconfig"
ca_file="${scratch_dir}/ca.pem"
client_certificate_file="${scratch_dir}/client.pem"
client_key_file="${scratch_dir}/client-key.pem"

kubectl_config_args=(--kubeconfig="$kubeconfig")
[[ -z "$context" ]] || kubectl_config_args+=(--context="$context")
if ! "$kubectl_bin" "${kubectl_config_args[@]}" config view --raw --minify -o json >"$selected_json"; then
	echo "error: kubeconfig context selection failed" >&2
	exit 1
fi

if ! jq -e '
  (.contexts | length) == 1 and
  (.clusters | length) == 1 and
  (.users | length) == 1 and
  .["current-context"] == .contexts[0].name and
  .contexts[0].context.cluster == .clusters[0].name and
  .contexts[0].context.user == .users[0].name
' "$selected_json" >/dev/null; then
	echo "error: kubeconfig must select exactly one context, cluster, and user" >&2
	exit 1
fi

actual_server="$(jq -er '.clusters[0].cluster.server | select(type == "string")' "$selected_json")" || {
	echo "error: kubeconfig cluster server is missing" >&2
	exit 1
}
if [[ "$actual_server" != "$expected_server" ]]; then
	echo "error: kubeconfig cluster server must be ${expected_server}" >&2
	exit 1
fi

if ! jq -e '
  .clusters[0].cluster as $cluster |
  (($cluster | keys) - ["server", "certificate-authority-data", "disable-compression"] | length) == 0 and
  (($cluster["certificate-authority-data"] // "") | type == "string" and length > 0) and
  (($cluster["disable-compression"] // false) | type == "boolean")
' "$selected_json" >/dev/null; then
	echo "error: kubeconfig must embed its CA, verify TLS, and use no file, proxy, or TLS-name override" >&2
	exit 1
fi

if ! jq -er '.clusters[0].cluster["certificate-authority-data"]' "$selected_json" |
	openssl base64 -d -A >"$ca_file" ||
	[[ ! -s "$ca_file" ]] ||
	! awk '
    BEGIN {
      begin = "-----BEGIN " "CERTIFICATE-----"
      end = "-----END " "CERTIFICATE-----"
      certificates = 0
      inside = 0
      invalid = 0
    }
    {
      sub(/\r$/, "")
      if ($0 == begin) {
        if (inside) invalid = 1
        certificates++
        inside = 1
        next
      }
      if ($0 == end) {
        if (!inside) invalid = 1
        inside = 0
        next
      }
      if (!inside && $0 !~ /^[[:space:]]*$/) invalid = 1
    }
    END { exit !(certificates == 1 && inside == 0 && invalid == 0) }
  ' "$ca_file" ||
	! openssl x509 -in "$ca_file" -noout -checkend 0 >/dev/null 2>&1; then
	echo "error: kubeconfig CA data must contain exactly one current, parseable PEM certificate" >&2
	exit 1
fi

credential_kind="$(jq -r '
  .users[0].user as $user |
  if
    ($user | keys) == ["token"] and
    ($user.token | type == "string" and test("[^[:space:]]"))
  then "token"
  elif
    (($user | keys) == ["client-certificate-data", "client-key-data"]) and
    (($user["client-certificate-data"] // "") | type == "string" and length > 0) and
    (($user["client-key-data"] // "") | type == "string" and length > 0)
  then "certificate"
  else "unsupported"
  end
' "$selected_json")"
if [[ "$credential_kind" == "unsupported" ]]; then
	echo "error: kubeconfig must use one inline token or one embedded client certificate/key pair" >&2
	exit 1
fi

if [[ "$credential_kind" == "certificate" ]]; then
	if ! jq -er '.users[0].user["client-certificate-data"]' "$selected_json" |
		openssl base64 -d -A >"$client_certificate_file" ||
		[[ ! -s "$client_certificate_file" ]] ||
		! openssl x509 -in "$client_certificate_file" -noout -checkend 0 >/dev/null 2>&1; then
		echo "error: embedded client certificate is not current and parseable" >&2
		exit 1
	fi
	if ! jq -er '.users[0].user["client-key-data"]' "$selected_json" |
		openssl base64 -d -A >"$client_key_file" ||
		[[ ! -s "$client_key_file" ]] ||
		! openssl pkey -in "$client_key_file" -noout -check >/dev/null 2>&1; then
		echo "error: embedded client key is not parseable" >&2
		exit 1
	fi
fi

jq '{
  apiVersion: "v1",
  kind: "Config",
  clusters,
  contexts: [{
    name: .contexts[0].name,
    context: {
      cluster: .contexts[0].context.cluster,
      user: .contexts[0].context.user
    }
  }],
  users,
  "current-context": .["current-context"]
}' "$selected_json" >"$normalized_kubeconfig"
chmod 0600 "$normalized_kubeconfig"

if ! env \
	-u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
	-u http_proxy -u https_proxy -u all_proxy \
	"$kubectl_bin" --kubeconfig="$normalized_kubeconfig" \
	--request-timeout=15s auth whoami >/dev/null; then
	echo "error: authenticated Kubernetes API/TLS probe failed; Octelium was not changed" >&2
	exit 1
fi

if ! "$octeliumctl_bin" create secret "$secret_name" \
	--domain "$domain" --file "$normalized_kubeconfig" >/dev/null; then
	echo "error: Secret was not created; existing Secrets are never overwritten" >&2
	echo "stage rotation with a new --secret-name and switch both Services through the reviewed catalog" >&2
	exit 1
fi

echo "Created staged Octelium Secret ${secret_name}."
