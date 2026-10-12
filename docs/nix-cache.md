# Signed offline check cache

Offline Python and shell fixtures and manifest policies are Nix derivations in
[`flake.nix`](../flake.nix). A successful check creates a `result` file. A
failed check creates no output and cannot populate the cache. The complete
tracked source tree, fixture commands, pinned tools, and platform determine
the derivation; Git commit metadata does not. Testing before a signed commit
therefore remains reusable when the committed files match.

[`offline-checks.sh`](../scripts/ci/offline-checks.sh) owns the extracted
Python checks; [offline-static-checks.sh](../scripts/ci/offline-static-checks.sh)
owns shell fixtures and source contracts. Their generated Terragrunt units are fixtures; it performs no
provider initialization or authenticated cloud/cluster requests.
[`conftest-policies.sh`](../scripts/ci/conftest-policies.sh) owns the second
check. Provider initialization/validation, Helm chart downloads, Git-sensitive
secret scanning, security scanners, live plans, and cluster acceptance still
run fresh. These network-dependent validations are outside the sandboxed
offline suite. NOFX image publication and other credentialed builds retain their
existing workflow and provenance gates.

## Local validation and publication

From the repository root:

```sh
bash scripts/ci/nix-checks.sh
nix develop --command bash scripts/ci/static-checks.sh --offline-verified
nix develop --command python3 -I scripts/nix-cache.py publish --linux \
  --key-file ~/.config/homelab/nix-cache/signing.key
```

Initialize the empty cache endpoint before publishing its first outputs:

```sh
python3 -I scripts/nix-cache.py init-cache \
  --key-file ~/.config/homelab/nix-cache/signing.key
```

The publisher rebuilds or substitutes the expected checks, checks that the
private key matches the committed public key, signs the outputs, and uploads
them to the `nix-cache` GitHub prerelease. It uploads NARs before metadata,
never replaces existing assets, and rejects a differing existing asset.
GitHub authentication requires repository write access; CI readers need no
cache credentials. The private signing key remains outside the checkout and
is never supplied to PR jobs. Both checks produce self-contained outputs.

The cache is an ordinary Nix binary cache hosted as release assets. NAR URLs
are flattened because release assets cannot contain directory paths. Nix
signatures cover store path, NAR hash, size, and references; changing the
download URL does not change the signed fingerprint.

The [homelab Linux builder](../clusters/homelab/apps/nix-builder/README.md)
primes Ubuntu CI through authenticated Kubernetes exec. Stage the exact files
first; `publish --linux` rejects unstaged changes and verifies the returned
outputs against the local Linux derivation paths. The signing key stays local.
Native macOS outputs serve macOS validation when its Nix daemon accepts the
cache and sandbox policy. The client refuses to publish when Nix ignores
those settings. Alternatively, run on another trusted **x86_64 Linux** Nix machine. The platform must match;
macOS or ARM Linux results cannot satisfy x86_64 Linux checks. If copying a key to another builder, protect that machine as carefully as CI. A Linux cache miss builds the checks normally.

Stopping the local publisher does not guarantee that Kubernetes exec stops the
remote build. To cancel an interrupted attempt, run:

```sh
python3 -I scripts/nix-builder.py --cancel \
  --pod <original-pod-name> --pod-uid <original-pod-uid> \
  --attempt-id <original-attempt-id>
```

The helper prints the original Pod name, UID, and immutable attempt ID before execution. Cancellation
rejects a replacement Pod and matches the immutable ID in the timeout supervisor’s final argument.
Later cancellation works even if source or cache policy has changed; retain the
printed ID from the publication log. TERM reaches the supervisor's process
group; a 10-second grace period precedes KILL of any surviving group members,
followed by 10 seconds to confirm the group contains no running processes. Local interrupt, timeout, and remote errors invoke
this path automatically. An independent 30-minute remote deadline limits the
entire attempt even if the operator connection is lost. A workspace lock excludes
concurrent attempts; the shell retains its lock during termination and waits for remaining
process-group members even if the main command exits first. Cancellation releases only
its matching owner lock after the whole group has stopped. The independent
deadline can leave a lock and workspace; fail closed pending operator review.
If node exec is unavailable, cancellation cannot be confirmed; keep builds
held and diagnose the node through the declared recovery path.

Immediately before execution, preflight requires every node Ready without
memory, disk, or PID pressure, node leases at most 75 seconds old, a single
Ready builder with its declared 1 GiB reservation and limit, and node memory
metrics at most 120 seconds old. The builder node needs at least 1.5 GiB
allocatable memory minus measured working-set usage: 1 GiB for the build and
512 MiB operating margin. This is an admission floor, not proof of runtime
capacity; monitor node health, actual peak memory, and OOM counters throughout
the first full check. Dependency substitutions run one at a time to reduce
cold-start pressure. Missing or stale evidence rejects execution.

The first Linux attempt on 2026-10-11 stopped during dependency substitution.
All four nodes were Ready before it started. `zimaboard-0` last renewed its
kubelet lease at 15:42:14 UTC, then became NotReady while runtime service
health changed. Last observed builder cgroup peak was 620,990,464 bytes with
zero OOM events; subsequent host inspection showed only 543 MiB available.
These observations do not establish the cause. ClickHouse OOM messages in
kernel history were from October 9 at 06:37 UTC, not this incident.

Stopping the local publisher left its remote Nix build alive. The controller
later replaced the Pod; cancellation reached the replacement and found no
matching process. Independent Talos process inspection subsequently confirmed
that the old process and every `nix build` command were gone, and all four
nodes plus kubelet, CRI, and containerd were healthy again. No manual node or
service recovery mutation was performed, and no signed outputs were published.
Keep retries held until cancellation lifecycle and resource preflight are
reviewed; preserve raw incident diagnostics in private operator storage.

The separately released retry on main `65ecac9a` downloaded dependencies but
failed before either check ran: `cannot set loopback interface flags:
Operation not permitted`. The worker exposed `user.max_user_namespaces=0`,
and the builder's effective/bounding capabilities omitted `NET_ADMIN`.
[Nix 2.35.2 sandbox setup](https://github.com/NixOS/nix/blob/2.35.2/src/libstore/linux/build/linux-derivation-builder.cc)
creates a private network namespace and raises its loopback interface. Without
user namespaces, that interface operation needs `NET_ADMIN` in the parent
user namespace. Do not disable the build sandbox to bypass this failure.

All four nodes remained Ready without pressure; OOM/OOM-kill counters stayed
zero. Observed cgroup peak was 1,079,291,904 bytes (about 1,029 MiB), with the
configured memory limit still 1 GiB. The failed command exited, automatic
cancellation found no remaining supervisor, and independent inspection
confirmed the owner lock and attempt workspaces were absent. The release
still contained only `nix-cache-info`; no signed results were published.

The protected runtime fix adds only `NET_ADMIN` to the nix-builder container
and updates its namespace
justification/README, followed by Argo rollout and one newly authorized
bounded retry. The operator explicitly approved this capability change and
one further attempt on October 11, 2026. A temporary candidate rendered and
passed all 224 Conftest policy assertions without policy changes; this is not runtime acceptance.
`NET_ADMIN` also allows configuring the Pod's network namespace, so obtain
explicit privilege-change approval first. Keep RuntimeDefault seccomp,
strict sandbox/signature verification, the 1 GiB request/limit, serial
substitutions and lifecycle safeguards. Host namespace sysctls, host
networking, credentials, capacity and other workloads are outside this fix.
The first full check's memory sufficiency and signed-cache hit remain
unproved. Preserve raw failure logs and original attempt IDs privately.
The earlier one-attempt release remains exhausted; further attempts require
new explicit authorization.

The newly authorized attempt after PR #1291 on `af18e0e6` passed the private
loopback setup but failed at Nix sandbox root pivot for the Node.js dependency:
`cannot pivot old root directory ... Operation not permitted`. Neither offline
check completed, and no signed outputs were published. RuntimeDefault seccomp,
strict sandbox/signature verification, the 1 GiB limit and the reviewed
capabilities were retained. This error identifies the failing operation, not
its confirmed enforcement cause; diagnose the sandbox/profile boundary before
proposing any additional privilege or profile change.

The attempt exited with status 1. Independent inspection confirmed the owner
lock and attempt workspaces absent, no active Nix/timeout process, four Ready
nodes without pressure and fresh leases. Memory peak was 1,060,679,680 bytes
(about 1,012 MiB), below the configured 1 GiB limit, with no max/OOM events.
The full-check resource budget remains unproved. The one additional attempt
release is exhausted; further execution or privilege/profile changes require
new explicit authorization through the protected source/rollout path.

New untracked files must first be staged: Git-backed flakes only include
tracked files. Do not stage private key material. Changes to tracked docs or
unrelated configuration also invalidate these broad checks; narrow input
sets only after their complete dependency footprint is established.

## CI trust and freshness

Static jobs fetch `main` and read its
[`nix-cache.json`](../scripts/config/nix-cache.json). PR changes cannot add
trusted cache keys. Before this policy initially lands on `main`, jobs build
without the shared cache. Required checks still run and report success only
after Nix realizes both expected outputs and remaining validation passes.
`require-sigs` and the build sandbox remain enabled. Missing entries build;
signature or content corruption fails verification.

Static jobs no longer restore the entire Nix store from an Actions cache:
existing unsigned store objects could bypass binary-cache signature checks.
Live jobs retain their development-shell dependency cache; live plans and
cluster checks do not consume cached test receipts.

## Key lifecycle and rollback

Initialize a replacement key using the repository-owned command:

```sh
python3 -I scripts/nix-cache.py init-key \
  --key-file ~/.config/homelab/nix-cache/replacement.key
```

This prints only the public key and refuses to overwrite existing files.
Review the new public key and a new release tag/URL in `nix-cache.json`, then
merge through normal protection. Publish into the new cache with that key.
Keep the private key in secure, recoverable operator storage; losing it
requires rotation. A compromised key can forge successful results: revoke
it by removing it from the protected policy before trusting more outputs.

To disable the cache, set `url` and `publicKey` to empty strings in the
protected policy. CI then builds all offline checks. Reverting the workflow,
flake, and extraction restores the previous uncached gate. Cache release
assets are disposable and contain only check outputs; retain a bounded
history or remove the prerelease through a separately authorized repository
cleanup when no longer needed.
