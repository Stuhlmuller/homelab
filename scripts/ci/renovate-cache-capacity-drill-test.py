#!/usr/bin/env python3
"""The capacity drill must recognize only its dedicated NFS mount."""

from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[2]
app = root / "clusters/homelab/apps/renovate"
base = (app / "cache-capacity-drill-base.yaml").read_text()
fill = (app / "cache-capacity-drill-fill.yaml").read_text()
restore = (app / "cache-capacity-drill-restore.yaml").read_text()
source_line = next(line.strip() for line in base.splitlines()
                   if line.strip().startswith("source=$(awk "))
program = source_line.split("awk '", 1)[1].split("' /proc/self/mountinfo", 1)[0]


def parsed(mountinfo):
    result = subprocess.run(["awk", program], input=mountinfo, text=True,
                            capture_output=True, check=True)
    return result.stdout.strip()


prefix = "125 96 0:45 / /cache rw,relatime - "
assert parsed(prefix + "nfs 10.1.0.2:/renovate-cache rw,vers=3\n") == (
    "nfs 10.1.0.2:/renovate-cache")
for wrong in (
    prefix + "nfs 10.1.0.2:/homelab rw,vers=3\n",
    prefix + "nfs4 10.1.0.2:/renovate-cache rw,vers=4\n",
    "125 96 0:45 / /other rw,relatime - nfs 10.1.0.2:/renovate-cache rw,vers=3\n",
    2 * (prefix + "nfs 10.1.0.2:/renovate-cache rw,vers=3\n"),
):
    assert parsed(wrong) != "nfs 10.1.0.2:/renovate-cache"

assert re.search(r'\[ "\$source" = \'nfs 10\.1\.0\.2:/renovate-cache\' \]', base)
assert "16777216" in base and "25165824" in base
assert base.count("kind: ConfigMap") == 1
assert base.count("kind: NetworkPolicy") == 1
assert "kind: Job" not in base
for name, manifest in (("fill", fill), ("restore", restore)):
    assert manifest.count("kind: Job") == 1
    assert f"name: renovate-cache-capacity-{name}" in manifest
    assert "  suspend: true" in manifest
    assert "claimName: renovate-cache-dedicated" in manifest
    assert "configMap: {name: renovate-cache-capacity-drill}" in manifest
    assert f"/drill/drill.sh, {name}]" in manifest
kustomization = (app / "kustomization.yaml").read_text()
for name in ("base", "fill", "restore"):
    assert f"cache-capacity-drill-{name}.yaml" not in kustomization
print("Dedicated NFS mount identity guard passed")
