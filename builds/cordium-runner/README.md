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

## One-job provisioner

`scripts/cordium-runner.py` reuses the repository's App JWT and HTTPS client.
It scopes installation tokens to `homelab`, creates a Workspace with reviewed
main, and issues a repository JIT configuration only after checkout verification.
The App key never enters Cordium; only the one-job JIT configuration enters
native exec stdin. Runner output is discarded locally; job logs remain in
GitHub. Execution is capped at 30 minutes. Cleanup attempts Workspace and runner
deletion independently, checks their absence, and fails if either is incomplete.
Ambiguous creation/registration requires operator inspection before retrying.

Registration is disabled in `.cordium/runner-pool.json`. Its initial label is
`cordium-canary`, so this stage does not switch the existing workflows. Labels
are routing hints, not an authorization boundary for a public repository.
Before enabling registration, add runner-only network isolation and verify
denied access to the LAN, Kubernetes, controller credentials and other Workspaces.
Observed Cordium Pods have only a dynamic Workspace UID label; do not impose a
namespace-wide deny policy that breaks existing human Workspaces.

The dormant `.cordium/runner-network-policy.json` template selects one Workspace
UID. It denies unsolicited ingress and private-address web traffic, while allowing
CoreDNS, Cordium's configured public DNS resolvers, and public HTTP/HTTPS needed
for package and Actions downloads. It has no private control-plane exception.
Do not instantiate it until actual supervisor/control connectivity is mapped;
add only the exact required peers through reviewed code. Tests prove the template's
selectors/CIDR intent, not CNI enforcement or supervisor readiness.

Read-only inspection on 2026-10-10 confirmed `kube-flannel` on all four nodes;
Flannel does not enforce these policies. Dependency work is staged in
[policy-enforcer publication #1270](https://github.com/Stuhlmuller/homelab/pull/1270)
and [NRI/enforcement prerequisites #1271](https://github.com/Stuhlmuller/homelab/pull/1271).
Neither currently proves production enforcement. Require NRI startup isolation,
allowed/denied traffic, restart recovery and ambient compatibility before applying
runner policies. The controller must install and read back the exact UID policy
before starting its Workspace, and retire the policy only after Workspace,
Deployment, Pod and UID-named PVC deletion is verified. The one-job provisioner
now implements that ordering, retains isolation on cleanup failure, and attempts
GitHub unregister independently. It rejects a different Kubernetes API context,
a stale/unready enforcer, conflicting fail-open/NRI flags, or a runner Pod with
unexpected placement, host namespaces or service-account token mounting.
These checks inspect both the desired DaemonSet and actual worker Pod; they do
not substitute for live allowed/denied traffic acceptance. Registration remains
disabled until supervisor connectivity and production enforcement are proven.

After the live isolation gate passes, enable the canary in a reviewed commit,
reconcile the declared dedicated runner identity and file-backed credentials,
then invoke from that exact clean main checkout:

```sh
python3 -I scripts/cordium-runner.py --expected-sha FULL_REVIEWED_MAIN_SHA \
  --app-key-file /PRIVATE/RUNNER_APP_KEY.pem \
  --homedir /PRIVATE/DEDICATED_RUNNER_LOGIN
```

This is the single-job lifecycle used to prove registration before adding the
in-cluster queue controller. It is not a deployed controller. Provisioner restart
recovery, cancellation, image publication, protected jobs and complete workflow
execution remain migration acceptance gates. Retire the unused bootstrap App key
only after the verified replacement has durable secret-manager custody.

## Dedicated native identity

The service catalog declares `homelab-cordium-runners` as a WORKLOAD User with
one concurrent session, a 60-minute client duration, and only
`homelab-cordium-runner-execution`. The policy allows owned Workspace creation,
start, inspection, deletion and exec; a priority `-4` denial excludes other
Cordium methods before upstream's broad MainService allowance. It grants no
management/bootstrap API access. The provisioner checks the actual login's
domain, User type/name and exact policy attachment before reading the App key.
Do not reuse an existing human, agent or CI-check login.

Preview only these two resources through the existing fixed reconciler:

```sh
nix develop --command python3 -I scripts/cordium-ci-reconcile.py --runner-identities
```

After reviewed merge, full validation and release of the cutover hold, use the
same exact-main checkout guards documented in `docs/cordium-ci.md`, then:

```sh
nix develop --command python3 -I scripts/cordium-ci-reconcile.py \
  --runner-identities --execute --expected-sha FULL_REVIEWED_MAIN_SHA
```

The Policy applies before the User; a second pass must converge and spec
readback must match. This scope cannot apply CI OIDC or unrelated credentials.
Credential creation, durable secret injection and native login renewal still
need a repository-owned path before controller deployment; the reconciler
does not generate or expose authentication material.
