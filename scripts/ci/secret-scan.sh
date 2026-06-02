#!/usr/bin/env bash
set -euo pipefail

scan_paths=(
  .agents
  .github
  .talos
  IaC
  clusters
  docs
  policy
  scripts
  AGENTS.md
  ONBOARDING.md
  README.md
  flake.nix
  renovate.json
)

existing_scan_paths=()
for path in "${scan_paths[@]}"; do
  if [[ -e "$path" ]]; then
    existing_scan_paths+=("$path")
  fi
done

if ((${#existing_scan_paths[@]} == 0)); then
  echo "No repository paths were available for secret scanning." >&2
  exit 1
fi

echo "::group::Explicit secret marker scan"
secret_matches="$(
  rg -n -I \
    -e '-----BEGIN (RSA |EC |OPENSSH |DSA |PRIVATE )?PRIVATE KEY-----' \
    -e '-----BEGIN CERTIFICATE-----' \
    -e 'AGE-SECRET-KEY-' \
    -e 'AKIA[0-9A-Z]{16}' \
    -e 'ASIA[0-9A-Z]{16}' \
    -e 'github_pat_[0-9A-Za-z_]{20,}' \
    -e 'gh[pousr]_[0-9A-Za-z_]{20,}' \
    -e 'xox[baprs]-[0-9A-Za-z-]+' \
    -e 'tskey-[0-9A-Za-z_-]+' \
    -e 'client-key-data:' \
    -e 'client-certificate-data:' \
    -e 'certificate-authority-data:' \
    -e 'id_rsa' \
    -e 'id_ed25519' \
    "${existing_scan_paths[@]}" \
    --glob '!**/.terraform.lock.hcl' \
    --glob '!**/flake.lock' \
    --glob '!**/.terragrunt-cache/**' \
    --glob '!**/plan.out' \
    --glob '!**/plan.json' \
    --glob '!scripts/ci/secret-scan.sh' || true
)"

if [[ -n "$secret_matches" ]]; then
  printf '%s\n' "$secret_matches" >&2
  echo "Secret-looking material or kubeconfig credential fields were found. Commit only safe references, placeholders, or encrypted material." >&2
  exit 1
fi
echo "::endgroup::"

if command -v gitleaks >/dev/null 2>&1; then
  echo "::group::Gitleaks working tree scan"
  gitleaks detect --no-git --redact --source . --verbose
  echo "::endgroup::"
elif [[ "${CI:-}" == "true" ]]; then
  echo "gitleaks is required in CI but was not found in PATH" >&2
  exit 1
else
  echo "::warning::gitleaks is not available in this local shell; GitHub Actions runs it from the Nix dev shell."
fi
