#!/usr/bin/env bash
set -euo pipefail
[[ $# == 0 ]]
recipe_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(git -C "$recipe_dir" rev-parse --show-toplevel)"
source_sha="$(git -C "$repo_root" rev-parse HEAD)"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]]
context="$(mktemp -d)"
trap 'rm -rf -- "$context"' EXIT
# Both recipes have no local COPY input; ignored workstation credentials stay out.
docker build --platform linux/amd64 --file "$recipe_dir/Dockerfile" \
  --label "org.opencontainers.image.source=https://github.com/Stuhlmuller/homelab" \
  --label "org.opencontainers.image.revision=$source_sha" \
  --tag homelab-cordium-runner:build "$context"
docker build --platform linux/amd64 --file "$recipe_dir/Dockerfile.controller" \
  --build-arg "SOURCE_SHA=$source_sha" --tag homelab-cordium-controller:build "$context"
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
echo 'Built exact-source runner/controller images; non-root read-only controller smoke passed.'
