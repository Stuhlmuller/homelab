#!/usr/bin/env bash
# The functions and variables below are called by source extracted through eval.
# shellcheck disable=SC2034,SC2329
set -euo pipefail

# Exercise the wrapper's preflight without cluster access or an octops binary.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
preflight_definition="$(sed -n '/^ensure_octelium_namespace_labels()/,/^}/p; /^apply_quic_cluster_config()/,/^}/p; /^assert_unpinned_enforcer_absent()/,/^}/p; /^assert_genesis_write_safe()/,/^}/p; /^preflight_genesis_image()/,/^}/p; /^run_octops()/,/^}/p' "$repo_root/scripts/octelium-cluster-bootstrap.sh")"
[[ -n "$preflight_definition" ]]
eval "$preflight_definition"

test_dir="$(mktemp -d "${TMPDIR:-/tmp}/octelium-genesis-pin-test.XXXXXX")"
trap 'rm -rf "$test_dir"' EXIT
contract="$test_dir/source.json"
valid_image="harbor.stinkyboi.com/homelab/homelab-octelium-genesis@sha256:$(printf 'a%.0s' {1..64})"

write_image() {
  printf '{"octelium":{"publishedGenesisImage":%s}}\n' "$1" >"$contract"
}

run_preflight() (
  local expected="$1"
  local cli_mode="$2"
  local enforcer_state="$3"
  local requested_version="$4"
  version="$requested_version"
  genesis_image=""
  kubectl_cmd=(kubectl)
  octops_cmd=(octops)
  kubectl() {
    [[ "$1" == "-n" && "$2" == "kube-system" && "$3" == "get" && "$4" == "daemonsets" ]] || return 1
    case "$enforcer_state" in
      absent) return 0 ;;
      present) printf '%s\n' kube-router-network-policy ;;
      error) return 1 ;;
      *) return 2 ;;
    esac
  }
  octops() {
    [[ "$2" == "--help" ]] || return 1
    case "$cli_mode" in
      patched) printf '%s\n' '  --genesis-image string' ;;
      unpatched) printf '%s\n' '  --version string' ;;
      init-only | upgrade-only)
        if [[ "$cli_mode" == "${1}-only" ]]; then
          printf '%s\n' '  --genesis-image string'
        else
          printf '%s\n' '  --version string'
        fi
        ;;
      *) return 2 ;;
    esac
  }
  if [[ "$expected" == "pass" ]]; then
    preflight_genesis_image "$contract"
    if [[ "$cli_mode" == "patched" && "$enforcer_state" == "unused" ]]; then
      [[ "$genesis_image" == "$valid_image" ]]
    else
      [[ -z "$genesis_image" ]]
    fi
  elif preflight_genesis_image "$contract" >/dev/null 2>&1; then
    echo "preflight accepted unsafe ${cli_mode}/${enforcer_state}/${requested_version}" >&2
    return 1
  fi
)

write_image null
run_preflight pass unpatched absent 0.35.0
run_preflight fail unpatched present 0.35.0
run_preflight fail unpatched error 0.35.0
printf '{"octelium":{}}\n' >"$contract"
run_preflight fail patched unused 0.35.0
write_image 42
run_preflight fail patched unused 0.35.0
write_image '"docker.io/example@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"'
run_preflight fail patched unused 0.35.0
write_image "\"$valid_image\""
run_preflight pass patched unused 0.35.0
run_preflight fail unpatched unused 0.35.0
run_preflight fail init-only unused 0.35.0
run_preflight fail upgrade-only unused 0.35.0
run_preflight fail patched unused latest
: >"$contract"
run_preflight fail patched unused 0.35.0
write_image null
printf '{"octelium":{"publishedGenesisImage":null}}\n' >>"$contract"
run_preflight fail patched unused 0.35.0

# The enforcer may appear during prerequisite waits after early preflight.
late_enforcer_case() (
  local late_state="$1"
  local count_file="$test_dir/kubectl-count"
  local octops_called="$test_dir/octops-called"
  printf '0\n' >"$count_file"
  rm -f "$octops_called"
  write_image null
  version="0.35.0"
  genesis_image=""
  kubectl_cmd=(kubectl)
  octops_cmd=(octops)
  kubectl() {
    local call_count
    call_count="$(cat "$count_file")"
    call_count=$((call_count + 1))
    printf '%s\n' "$call_count" >"$count_file"
    [[ "$1" == "-n" && "$2" == "kube-system" && "$3" == "get" && "$4" == "daemonsets" ]] || return 1
    if ((call_count == 1)); then
      return 0
    fi
    case "$late_state" in
      present) printf '%s\n' kube-router-network-policy ;;
      absent) return 0 ;;
      error) return 1 ;;
    esac
  }
  octops() {
    touch "$octops_called"
  }
  preflight_genesis_image "$contract"
  if [[ "$late_state" == "absent" ]]; then
    run_octops init
    [[ -f "$octops_called" ]]
  elif run_octops init >/dev/null 2>&1; then
    echo "octops ran after late enforcer state ${late_state}" >&2
    return 1
  else
    [[ ! -e "$octops_called" ]]
  fi
  [[ "$(cat "$count_file")" == "2" ]]
)
late_enforcer_case present
late_enforcer_case error
late_enforcer_case absent

# An enforcer arriving during prerequisite waits must prevent later live writes.
late_write_case() (
  local late_state="$1"
  local writes="$test_dir/live-writes"
  : >"$writes"
  write_image null
  version="0.35.0"
  genesis_image=""
  domain="example.com"
  TMPDIR="$test_dir/$late_state"
  mkdir -p "$TMPDIR"
  kubectl_cmd=(kubectl)
  enforcer_state=absent
  kubectl() {
    if [[ "$1" == "-n" && "$2" == "kube-system" && "$3" == "get" && "$4" == "daemonsets" ]]; then
      case "$enforcer_state" in
        present) printf '%s\n' kube-router-network-policy ;;
        error) return 1 ;;
      esac
      return 0
    fi
    if [[ "$1" == "get" && "$2" == "namespace" ]]; then
      return 0
    fi
    if [[ "$1" == "wait" ]]; then
      enforcer_state="$late_state"
      return 0
    fi
    printf 'kubectl %s\n' "$1" >>"$writes"
  }
  octeliumctl() {
    if [[ "$1" == "get" ]]; then
      printf '%s\n' '{"spec":{"network":{"quicv0":{"enable":false}}}}'
    else
      printf 'octeliumctl %s\n' "$1" >>"$writes"
    fi
  }
  require_command() { :; }
  preflight_genesis_image "$contract"
  kubectl wait
  if ensure_octelium_namespace_labels >/dev/null 2>&1; then
    echo 'namespace changed after late enforcer arrival' >&2
    return 1
  fi
  if apply_quic_cluster_config >/dev/null 2>&1; then
    echo 'QUIC config changed after late enforcer arrival' >&2
    return 1
  fi
  [[ ! -s "$writes" ]]
)
late_write_case present
late_write_case error

python3 - "$repo_root/scripts/octelium-cluster-bootstrap.sh" <<'PY_TEST'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
assert source.index('preflight_genesis_image "$generator_source_file"') < source.index('ensure_octelium_namespace_labels\n\npostgres_password=')
assert source.index('preflight_genesis_image "$generator_source_file"') < source.index('  apply_quic_cluster_config\n')
assert 'action+=(--genesis-image "$genesis_image")' in source
assert 'assert_genesis_write_safe || return 1\n  "${kubectl_cmd[@]}" label namespace octelium' in source
assert 'assert_genesis_write_safe || return 1\n  "${kubectl_cmd[@]}" annotate namespace octelium' in source
assert 'assert_genesis_write_safe || return 1\n  octeliumctl apply' in source
assert 'run_octops() {\n  # Prerequisite waits can outlast the first read; recheck at invocation.\n  assert_genesis_write_safe || return 1' in source
PY_TEST

echo 'Octelium Genesis pin preflight passed'
