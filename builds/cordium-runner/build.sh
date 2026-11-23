#!/usr/bin/env bash
set -euo pipefail
[[ $# == 0 ]]
recipe_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(git -C "$recipe_dir" rev-parse --show-toplevel)"
source_sha="$(git -C "$repo_root" rev-parse HEAD)"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]]
context="$(mktemp -d)"
trap 'rm -rf -- "$context"' EXIT
# Stage only these checked-in inputs and keep the controller context free of local files.
install -d "$context/runner" "$context/controller"
cp "$recipe_dir/nix-packages.nix" "$repo_root/flake.lock" "$context/runner/"
docker build --platform linux/amd64 --file "$recipe_dir/Dockerfile.nix" \
  --label "org.opencontainers.image.source=https://github.com/Stuhlmuller/homelab" \
  --label "org.opencontainers.image.revision=$source_sha" \
  --tag homelab-cordium-runner:build "$context/runner"
docker build --platform linux/amd64 --file "$recipe_dir/Dockerfile.controller" \
  --build-arg "SOURCE_SHA=$source_sha" --tag homelab-cordium-controller:build "$context/controller"
# Check installed tools, registered paths and single-user builds without network access.
docker run --rm -i --network none --user root --entrypoint runuser \
  homelab-cordium-runner:build -u runner -- bash -seu <<'RUNNER_SMOKE'
test "$(id -u)" = 1001
test -w "$RUNNER_TOOL_CACHE"
for tool in nix actionlint aws cosign curl docker gh git gitleaks go jq kubectl helm \
    kustomize node npm ssh tofu python python3 regctl rg shellcheck skopeo sops terragrunt yq; do
  command -v "$tool" >/dev/null
done
python -c 'import ssl, sqlite3, venv'
nix path-info --offline "$(readlink -f /opt/runner/tools)" >/dev/null
nix build --offline --no-link --expr '
  derivation {
    name = "cordium-runner-smoke";
    system = "x86_64-linux";
    builder = "/opt/runner/tools/bin/bash";
    args = [ "-c" "/usr/bin/touch $out" ];
  }
'
RUNNER_SMOKE
python_check='import os, tempfile, pathlib, importlib.util
assert os.getuid() == 1001
root = pathlib.Path("/opt/homelab")
spec = importlib.util.spec_from_file_location("controller", root / "scripts/cordium-runner-controller.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(dir="/data") as directory:
    source = pathlib.Path(directory) / "source"; source.mkdir()
    target = pathlib.Path(directory) / "private"
    for key in module.KEYS:
        path = source / key; path.write_bytes(b"fixture"); path.chmod(0o440)
    module.private_copies(source, target)
    assert all((target / key).stat().st_mode & 0o777 == 0o400 for key in module.KEYS)
'
docker run --rm --read-only --user 1001:123 --cap-drop ALL \
  --security-opt no-new-privileges --network none \
  --tmpfs /tmp:rw,nosuid,nodev,mode=1777 \
  --tmpfs /data:rw,nosuid,nodev,uid=1001,gid=123,mode=0700 \
  --entrypoint python3 homelab-cordium-controller:build -I -c "$python_check"
echo 'Built exact-source runner/controller images; non-root runner and read-only controller smoke tests passed.'
