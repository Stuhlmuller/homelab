#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || "$1" != "--install-dir" ]]; then
  echo 'Usage: scripts/ci/install-cordium-client.sh --install-dir PATH' >&2
  exit 2
fi
install_dir="$2"
case "$(uname -s)/$(uname -m)" in
  Linux/x86_64 | Linux/amd64)
    platform=linux-amd64
    digest=7c5c5bcc4357b892dd9e09464efb770868e3138da3a7507b931a2db43f610898
    ;;
  Linux/aarch64 | Linux/arm64)
    platform=linux-arm64
    digest=4f9c5fde73b33789b04d77d10ce03b7fd388ea8be60d0de81eb2e7ca2619ba63
    ;;
  Darwin/arm64)
    platform=darwin-arm64
    digest=070e83d9ea8fb372c1cd35ce77a6fc32c077afe67d7a722276066382be7b906e
    ;;
  Darwin/x86_64)
    platform=darwin-amd64
    digest=6ff15ab83be341512888b73bf7fb189743123cc342f66961e746119b3a603070
    ;;
  *)
    echo 'Unsupported platform for pinned Cordium client' >&2
    exit 1
    ;;
esac
scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT
curl -fsSL --max-time 120 \
  "https://github.com/octelium/cordium/releases/download/v0.12.7/cordium-${platform}.tar.gz" \
  -o "$scratch/cordium.tar.gz"
printf '%s  %s\n' "$digest" "$scratch/cordium.tar.gz" | shasum -a 256 --check -
tar -xzf "$scratch/cordium.tar.gz" -C "$scratch" cordium
install -d -m 0755 "$install_dir"
install -m 0755 "$scratch/cordium" "$install_dir/cordium"
"$install_dir/cordium" version
