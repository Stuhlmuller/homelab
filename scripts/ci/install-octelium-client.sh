#!/usr/bin/env bash
set -euo pipefail

OCTELIUM_VERSION="${OCTELIUM_VERSION:-0.35.0}"
OCTELIUM_INSTALL_DIR="${OCTELIUM_INSTALL_DIR:-${HOME}/.local/bin}"

case "$(uname -s)" in
  Linux)
    os="linux"
    sha256="bcf55709c49f8972f350ec1c4810c7ccf43550a89ab322c8b10f2153864914e5"
    ;;
  Darwin)
    os="darwin"
    sha256="e03808a19a204e76f657fa40b62860a9c2ac9e20eef5bb08cb1c117aee713ba8"
    ;;
  *)
    echo "Unsupported OS for Octelium client: $(uname -s)" >&2
    exit 1
    ;;
esac

case "$(uname -m)" in
  x86_64 | amd64)
    arch="amd64"
    if [ "${os}" = "darwin" ]; then
      echo "No pinned Octelium Darwin amd64 artifact is configured." >&2
      exit 1
    fi
    ;;
  arm64 | aarch64)
    arch="arm64"
    if [ "${os}" = "linux" ]; then
      echo "No pinned Octelium Linux arm64 artifact is configured." >&2
      exit 1
    fi
    ;;
  *)
    echo "Unsupported architecture for Octelium client: $(uname -m)" >&2
    exit 1
    ;;
esac

artifact="octelium-${os}-${arch}.tar.gz"
url="https://github.com/octelium/octelium/releases/download/v${OCTELIUM_VERSION}/${artifact}"
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

curl -fsSL "${url}" -o "${tmpdir}/${artifact}"
if command -v sha256sum >/dev/null 2>&1; then
  printf '%s  %s\n' "${sha256}" "${tmpdir}/${artifact}" | sha256sum --check -
else
  actual="$(shasum -a 256 "${tmpdir}/${artifact}" | awk '{print $1}')"
  test "${actual}" = "${sha256}" || {
    echo "Checksum mismatch for ${artifact}: got ${actual}" >&2
    exit 1
  }
fi

tar -xzf "${tmpdir}/${artifact}" -C "${tmpdir}"
install -m 0755 -d "${OCTELIUM_INSTALL_DIR}"
install -m 0755 "${tmpdir}/octelium" "${OCTELIUM_INSTALL_DIR}/octelium"

if [ -n "${GITHUB_PATH:-}" ]; then
  printf '%s\n' "${OCTELIUM_INSTALL_DIR}" >>"${GITHUB_PATH}"
fi

"${OCTELIUM_INSTALL_DIR}/octelium" version
