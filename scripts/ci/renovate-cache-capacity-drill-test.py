#!/usr/bin/env python3
"""The capacity drill must recognize only its dedicated NFS mount."""

from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[2]
manifest = (root / "clusters/homelab/apps/renovate/cache-capacity-drill.yaml").read_text()
source_line = next(line.strip() for line in manifest.splitlines()
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

assert re.search(r'\[ "\$source" = \'nfs 10\.1\.0\.2:/renovate-cache\' \]', manifest)
assert "16777216" in manifest and "25165824" in manifest
print("Dedicated NFS mount identity guard passed")
