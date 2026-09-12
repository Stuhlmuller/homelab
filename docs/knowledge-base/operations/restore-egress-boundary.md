# Restore process network boundary

Related: [[../runbooks/runtime-isolation]], [[../architecture/storage-and-state]],
[[validation-gates]].

## Prerequisite, not an activated workload

`images/postgres-restore-egress/` adds a source-built Linux seccomp launcher and
an image recipe based on the exact PostgreSQL14.23 Bookworm image used by the
proposed Octelium restore drill. No Kubernetes image reference, CronJob schedule,
registry credential or image publishing workflow changes here. Linux execution
and the promised network boundary remain unverified until the dedicated CI job
actually passes. Do not enable the proposed PR #970 drill on the strength of
an unenforced NetworkPolicy: this cluster's Flannel does not enforce it.

The launcher installs its own filter before executing the restore script or
reading backups. It allows only `AF_UNIX` socket creation, closes inherited
nonstandard descriptors, accepts only regular-file/FIFO/`/dev/null` standard descriptors, and denies
io_uring, ancillary descriptor receipt, tracing, descriptor stealing and namespace-switching calls. It rejects
foreign syscall architectures and x86 x32 calls. Every startup must prove denied
IP sockets return `EPERM` and Unix communication works; inability to install or
verify the filter exits before command execution. Read-only backup mounts and
bounded disposable storage remain separate requirements.

`recvmsg` and `recvmmsg` are denied regardless of socket family: an unfiltered
Unix peer could otherwise transfer an INET socket with `SCM_RIGHTS` after the
startup descriptor cleanup. Every startup checks both calls return `EPERM`.
Ordinary `read`/`recvfrom` remain available for PostgreSQL's Unix protocol but
cannot receive ancillary file descriptors. This defense is intrinsic even
though production must still exclude unfiltered Unix peers and proxy sockets.
[Unix descriptor passing](https://man7.org/linux/man-pages/man7/unix.7.html).

The kernel permits a non-root process with `no_new_privs` to add seccomp filters.
They survive fork/exec and cannot be weakened by adding a later permissive
filter. Existing RuntimeDefault, UID/GID65534, drop-ALL, read-only root and
no-privilege-escalation controls remain in force. This is a process network
boundary, not a claim that the Pod network namespace disappears or a complete
hostile-code sandbox. No host/runtime/proxy Unix sockets, unfiltered sidecars,
shared host network/PID namespaces or inherited network descriptors may be
introduced. [Kernel seccomp behavior](https://docs.kernel.org/userspace-api/seccomp_filter.html),
[ABI considerations](https://man7.org/linux/man-pages/man2/seccomp.2.html).

io_uring can create sockets without the ordinary socket syscall, hence all its
entry points are explicitly denied. PostgreSQL14.23's localhost UDP statistics
collector cannot run under this filter; its pinned source disables collection
and forces `track_counts=off` instead of failing startup. The real SQL fixture
checks this expected behavior. [io_uring socket operation](https://man7.org/linux/man-pages/man2/io_uring_enter.2.html),
[PostgreSQL14.23 fallback](https://github.com/postgres/postgres/blob/REL_14_23/src/backend/postmaster/pgstat.c#L641).

## Build and validation

On native x86_64 Linux with Docker and Nix:

```sh
python3 scripts/ci/restore-egress-check.py
```

The script uses the committed flake lock to build static launcher/probe binaries,
then builds the exact base-image recipe with deterministic copied-file times
and `SOURCE_DATE_EPOCH=1`. It never logs into a registry or publishes an image;
it removes its local image and disposable containers. `.github/workflows/restore-egress.yml`
runs it on Linux PRs with `contents: read`, no persisted checkout credentials,
and no secrets. Its checkout/Nix action pins match the existing `validate.yml`
workflow. The image's final layer contains only the launcher, not the
probe binary. `nix build .#restore-egress-tools` exposes the two test/build tools;
ARM64 source/build support does not establish ARM64 runtime verification.

The harness deliberately uses ordinary Docker bridge networking. Local TCP/UDP
echo servers prove the unfiltered synthetic probe can communicate; IPv6 socket
creation is also a required positive control. Filtered probes require `EPERM`
for IPv4/IPv6, packet, netlink and vsock sockets/socketpairs; transport timeouts
or refused connections do not pass. It checks io_uring denial, fork/exec
inheritance, an attempted permissive second filter, x32/i386 rejection, inherited-fd
closure and socket/anonymous-stdio rejection. The controlled servers must receive no
additional traffic from filtered tests.

A separate real Unix broker offers both unconnected and preconnected INET
descriptors after the receiver has executed its launcher and connected to the
broker. Unfiltered `recvmsg`/`recvmmsg` controls must import the offered socket
and send a byte to a local TCP listener. Filtered calls must return `EPERM`
without adding descriptors; `read`/`recvfrom` must receive the ordinary byte
without importing its attached descriptor. The broker must confirm delivery,
and filtered cases must send no traffic through the offered socket. These
synthetic tests deliberately introduce the otherwise prohibited Unix peer;
they do not relax the production mount or sidecar contract.

A real PostgreSQL init/dump/drop/restore round trip must succeed over Unix
sockets. Harmless SQL `COPY ... FROM PROGRAM` and psql shell children execute the
same negative probe, exercising both server and client subprocess inheritance.
Injected filter-installation and Unix self-test failures must stop before a
command sentinel can run. Runtime probes require UID/GID65534, no_new_privs, a seccomp filter and
zero effective/permitted/inheritable capabilities. These tests do not restore
production backups or contact production services. Restoring dumps can execute
source-superuser code, so a checksum alone cannot replace this boundary.
[PostgreSQL restore warning](https://www.postgresql.org/docs/14/app-pgrestore.html).

## Integration and rollout gates

1. Obtain genuine green native Linux results for the exact reviewed source and
   derived image. The current job tests amd64 only; constrain an initial drill
   to `kubernetes.io/arch: amd64`, or add and pass native ARM64 validation before
   publishing a multi-architecture image.
2. Add a separately reviewed, protected image-publication path. This repository
   previously had semantic-release only, not an OCI publishing workflow. Record
   the tested source and immutable resulting image digest; do not substitute an
   untested image or add runtime downloads/compilers.
3. Update PR #970 declaratively to that digest and make the launcher the explicit
   Kubernetes command preceding `/bin/sh /scripts/restore-drill.sh ...`.
   Kubernetes `command` overrides an image ENTRYPOINT, so inheriting the image
   alone is insufficient. Static rendering must reject launcher bypass and
   preserve all existing resource, mount and security bounds.
4. Run the original archive/invariant fixtures through the final launcher/image,
   then the full repository gate and reviewed server-side diff. Docker CI uses
   Docker's default seccomp profile; it does not prove compatibility with the
   deployed Talos/containerd RuntimeDefault profile. Before any real backup
   reads, add and run a reviewed repository-owned synthetic Job with the final
   image, launcher and production security settings, but no backup PVC or
   credentials. Require its startup denial checks and a synthetic Unix-socket
   PostgreSQL restore to pass on the target runtime. Do not use ad hoc live probes.
5. Only after that proof, enable the real drill through GitOps. Verify the
   actual scheduled Job's startup denial checks and successful restore before
   claiming recovery coverage. A normal restore success without filter checks
   is insufficient.

If the filter cannot load on the deployed RuntimeDefault/kernel, the Job must
fail and the stale-backup alert must remain actionable. Rollback suspends/removes
the drill through GitOps; never remove the launcher just to make it green.
