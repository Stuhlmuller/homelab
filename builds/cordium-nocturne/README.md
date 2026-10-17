# Cordium workspace reservations

The pinned v0.12.7 Nocturne generator requests 5 MiB and 10 millicores for
workspaces whose configured limits may be 2 GiB and 2 CPUs. The
[bounded smoke receipt](../../docs/evidence/cordium-startup-capacity-2026-10-17.json)
records this mismatch, a contemporaneous worker runtime failure, and verified
cleanup. The nested image-pull stall's exact cause remains unproven.

`check.sh` uses checksum-pinned upstream source and its Go 1.25.8 Linux toolchain.
It runs the real Pod-spec generator with default and explicit limits and
requires the under-reservation assertion to fail. Compilation failure does not
count as reproducing the defect. It creates no workspace or cluster resources.
The hosted diagnostic job is temporary bootstrap infrastructure; include it in
the full Cordium selector cutover after the fleet passes live acceptance.

```sh
# Linux x86_64, with curl, jq, sha256sum, tar and Python's existing CI toolset
bash builds/cordium-nocturne/check.sh
```

Acer eligibility also needs user-namespace prerequisites, storage topology and
node-path coverage, enough CPU/memory/Pod overhead, and a declared controller
image rollout. Adding a node label alone is insufficient. Preserve existing
worker eligibility and bound PV node affinity for the six stopped workspaces.
Do not change runtime placement or raise startup deadlines to claim this test
fixes the live startup failure.
