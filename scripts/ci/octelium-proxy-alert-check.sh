#!/usr/bin/env bash
set -euo pipefail

test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT

yq '.spec' clusters/homelab/apps/prometheus/octelium-proxy-prometheusrules.yaml > "$test_dir/rules.yml"
cp scripts/ci/fixtures/octelium-proxy-alerts/rules.test.yml "$test_dir/rules.test.yml"
(
  cd "$test_dir"
  promtool check rules rules.yml
  promtool test rules rules.test.yml
)
