#!/usr/bin/env bash
set -euo pipefail

test "$#" -eq 1 || { echo "Usage: $0 INSTALL_DIRECTORY" >&2; exit 2; }
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) platform=darwin-arm64; checksum=6ab99bbb59e67aa0030f6233cb27f2da88e877f5fca2fd8e02f2eb46165252f3 ;;
  Darwin-x86_64) platform=darwin-amd64; checksum=2eec525f918a165e2850d30ac9e7dccfe1cd25aab4e6c8a2a0d20e4b47e7576c ;;
  Linux-x86_64) platform=linux-amd64; checksum=d46e57fc5f34c0462a2eb0357fc32329b5f66f15d4edff6dbb694c51c9dd6eac ;;
  Linux-aarch64) platform=linux-arm64; checksum=8de5cd959ecb50594b92e0cba03c7473aa24b6348ed018ba69a51decb6b86e99 ;;
  *) echo "Unsupported Octelium CLI platform" >&2; exit 1 ;;
esac
temporary="$(mktemp -d)"
trap 'rm -rf "$temporary"' EXIT
curl --fail --silent --show-error --location --max-time 120 \
  "https://github.com/octelium/octelium/releases/download/v0.35.0/octeliumctl-${platform}.tar.gz" \
  --output "$temporary/client.tar.gz"
printf '%s  %s\n' "$checksum" "$temporary/client.tar.gz" | shasum -a 256 --check -
tar -xzf "$temporary/client.tar.gz" -C "$temporary"
install -d -m 0755 "$1"
install -m 0755 "$temporary/octeliumctl" "$1/octeliumctl"
"$1/octeliumctl" version
