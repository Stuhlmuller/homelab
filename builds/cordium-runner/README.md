# Cordium runner compatibility probe

This image extends the official Actions runner 2.338.0 Ubuntu image at a
fixed digest. It adds the missing Docker firewall tooling, Python, and a writable
Python toolcache. Cordium builds this Dockerfile inside the disposable probe
Workspace; no App key, runner token, or controller credential enters the build.

The existing reviewed-main Cordium check has a fixed `runner-probe` mode.
It creates a 2 CPU / 2 GiB / 10 GB ephemeral Workspace, verifies the exact
checkout, starts nested Docker with disposable storage, then proves a Docker
build, bind mount, bridged HTTPS request, and Node action runtime. The outer
helper verifies Workspace deletion even after probe failure. This is
compatibility evidence only: it does not register a runner or prove job or
untrusted-code isolation.

The Workspace requests `SYS_ADMIN` for nested mounts and `NET_ADMIN` for its
Docker bridge/firewall. Those capabilities apply inside Cordium's rootless
Workspace container; no node Docker socket is mounted. Keep this fixed probe
main-only. Do not enable public PR execution until denied access to Kubernetes,
the homelab LAN, other Workspaces, and provisioner credentials is verified.

After reviewed merge, CI identity reconciliation and base-image publication:

```sh
gh workflow run cordium-check.yml --ref main \
  -f expected_sha=FULL_REVIEWED_MAIN_SHA -f mode=runner-probe
```

Require a successful run and verified Workspace/PVC deletion. The wrapper
withholds native output; a failed run is not compatibility acceptance. A build
or Docker-daemon failure needs private diagnostic inspection before retrying.
The pinned `vfs` Docker storage driver favors compatibility over disk speed;
measure storage and memory before running image builds as production jobs.

Rollback by removing the new mode and its fixed image/probe files through a
reviewed commit. No persistent Docker storage or runner registration exists.
