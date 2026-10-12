# Linux Nix builder

This disposable x86_64 executor primes the signed offline-check cache for
Ubuntu CI. It uses the existing mirrored, digest-pinned `nixos/nix` image.
The shared Terragrunt Application follows `main`; Kustomize owns runtime
configuration. It schedules only on the two 8 GB amd64 workers, avoiding
the smaller worker and control plane.

There is no Service, ingress, host mount, or Kubernetes token. Operators
submit staged source over their existing authenticated Kubernetes connection
using [`nix-builder.py`](../../../../scripts/nix-builder.py). The helper checks
the returned paths against locally evaluated Linux derivations, rejects unsafe
archives, and removes its remote workspace after success or failure. Source
archives contain tracked files only. Builds require sandboxing and verified
substitutes. The signing key remains on the operator machine.

Nix requires root and mount/chroot capabilities to create its nested build
sandboxes. With host user namespaces disabled, NET_ADMIN is also required
to raise loopback inside each private build network namespace. This capability
also permits changes to the Pod network namespace, so the executor remains
limited to reviewed homelab source. The container uses RuntimeDefault seccomp
and is not fully privileged, but `SYS_ADMIN` makes this a high-trust executor. Submit reviewed
homelab source only. NetworkPolicy declares intended DNS/public HTTPS access
and ingress/private-network denial, but current Flannel does not enforce it.
This namespace is not ambient-enrolled; do not assume effective network
isolation. Reviewed source is the input trust boundary. See
[runtime isolation](../../../../docs/runtime-isolation.md#current-boundary).
Do not reuse this workload for arbitrary third-party submissions.

The store and workspaces are disposable container/emptyDir data. No backups
or persistent volumes are required; signed release outputs survive Pod
replacement. Container ephemeral storage is bounded at 16 GiB, and each
build uses at most two cores. A cold replacement downloads dependencies again.

After GitOps deployment:

```sh
kubectl --namespace nix-builder rollout status deployment/nix-builder
nix develop --command python3 -I scripts/nix-cache.py publish --linux \
  --key-file ~/.config/homelab/nix-cache/signing.key
```

See [cache operation and rollback](../../../../docs/nix-cache.md). To remove
the executor, remove its stack registration and runtime source through the
normal protected GitOps workflow. Its disposable build data needs no restore.

On 2026-10-10, read-only node inspection showed 6203 MiB requested on
zimaboard-0 and 7244 MiB on zimaboard-1 (about 7.1 GiB allocatable each).
The 1 GiB builder request fits only the first worker at that snapshot. Verify
current scheduling and actual memory headroom before accepting its rollout;
a Pending Pod is a capacity blocker, not a reason to reduce requests blindly.
Live working-set metrics also showed 84–86% worker memory usage. The builder's
memory limit equals its 1 GiB reservation; an over-budget build fails rather
than borrowing several additional GiB from existing workloads. Measure its
first full build before treating this resource budget as sufficient.
