#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT

config="$test_dir/config.xml"
printf '%s\n' \
	'<Config>' \
	'  <PostgresHost>old</PostgresHost>' \
	'  <PostgresHost>older</PostgresHost>' \
	'</Config>' >"$config"

script="$(
	yq -r '.controllers.prowlarr.initContainers.configure-postgres.command[2]' \
		"$repo_root/clusters/homelab/apps/prowlarr/values.yaml" |
		sed "s|^config=/config/config.xml$|config=$config|"
)"

PROWLARR_POSTGRES_HOST=new-host \
	PROWLARR_POSTGRES_PORT=5432 \
	PROWLARR_POSTGRES_USER=media_apps \
	PROWLARR_POSTGRES_PASSWORD='p&<x>' \
	PROWLARR_POSTGRES_MAIN_DB=prowlarr-main \
	PROWLARR_POSTGRES_LOG_DB=prowlarr-log \
	/bin/sh -ec "$script"

assert_tag() {
	tag="$1"
	expected="$2"
	total="$(grep -Ec "^[[:space:]]*<${tag}>.*</${tag}>[[:space:]]*$" "$config" || true)"
	matches="$(grep -Fxc "  <${tag}>${expected}</${tag}>" "$config" || true)"
	[[ "$total" -eq 1 && "$matches" -eq 1 ]]
}

assert_tag PostgresUser media_apps
assert_tag PostgresPassword 'p&amp;&lt;x&gt;'
assert_tag PostgresPort 5432
assert_tag PostgresHost new-host
assert_tag PostgresMainDb prowlarr-main
assert_tag PostgresLogDb prowlarr-log
