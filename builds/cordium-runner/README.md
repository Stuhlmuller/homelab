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

The controller entrypoint is scripts/cordium-runner-controller.py. It keeps its
login and state outside the clean repository, copies the two projected Secret
keys into a mode-0700 directory as mode-0400 files, and refreshes those copies
before each queue cycle. Both source files are checked before either replacement;
temporary files are atomically renamed and removed on failure. This supports
non-root Kubernetes Secret projections with group-read permissions without
weakening the provisioner's private-file guards. World-readable projections are
rejected. SIGTERM enters the existing lifecycle cleanup before process exit.

The entrypoint checks the exact current-main checkout and pinned client, acquires
its private lock, and stops when activation remains disabled. It is not registered
as a Deployment yet; image publication, RBAC, token-file kubeconfig and actual
projected-file refresh acceptance still precede activation.

The dormant access manifest declares one controller ServiceAccount and only
namespace Roles. In cordium it can create/delete/read/watch NetworkPolicies and
inspect Pods, Deployments and PVCs; it cannot mutate workloads or read Secrets.
In kube-system it can get only the named enforcer DaemonSet and list Pods for
worker readiness checks. No ClusterRole or ClusterRoleBinding is added.
Automatic service-account mounting is disabled. The token-file kubeconfig
references a future explicit projected API token and CA at
/var/run/cordium-runner-api; no token or certificate material is committed.
Mount its config at the image user's default kubeconfig path when registering
the published controller Deployment. These declarations are not applied live.

Dockerfile.controller packages the non-root entrypoint and pinned native clients,
with kubectl 1.34.1 verified against its official SHA-256. It fetches only the
exact public source revision supplied by the reviewed build, so local ignored
credentials never enter the build context. Its source/revision labels identify
that checkout. This image has not been built or published yet; do not add a
consuming Deployment reference until publication and cold-pull acceptance pass.

The optional serve mode polls active workflow runs and every job page, matching
all requested labels case-insensitively. It refreshes the scoped App client and
rechecks current main and the native identity on each cycle, executes one
Workspace lifecycle at a time, and stops on drift or any lifecycle failure.
A private nonblocking lock prevents two processes sharing one login directory.
GitHub caps filtered run searches at 1,000 results; the loop rejects that boundary
instead of silently omitting jobs. Partition inventory by time before supporting
that scale.

After activation gates and a verified dedicated login, add the serve flag:

~~~sh
python3 -I scripts/cordium-runner.py --serve \
  --expected-sha FULL_REVIEWED_MAIN_SHA \
  --app-key-file /PRIVATE/RUNNER_APP_KEY.pem \
  --auth-token-file /PRIVATE/RUNNER_AUTH_TOKEN \
  --homedir /PRIVATE/DEDICATED_RUNNER_LOGIN
~~~

This process is not deployed yet. Use one replica with Recreate rollout when
packaging it; the filesystem lock is not a distributed leader lease. Deployment refresh on new main commits remains required. The private native
token file is reread per cycle and supplied only to parent CLI processes, not
Pod env, argv or Workspace exec env. The pinned client handles access-token
refresh and credential fallback using its local authenticated state. Observation
or transport failures stop the loop; no retry infers session expiry. The initial canary
labels and disabled registration flag remain unchanged.

The service catalog declares `homelab-cordium-runners` as a WORKLOAD User with
one concurrent session, a 60-minute client duration, and only
`homelab-cordium-runner-execution`. The policy allows owned Workspace creation,
start, inspection, deletion and exec; a priority `-4` denial excludes other
Cordium methods before upstream's broad MainService allowance. It grants no
management/bootstrap API access. The provisioner checks the actual login's
domain and User type/name plus an exact forbidden-method denial before reading
the App key. The pinned status response omits policy attachments; exact policy
specification remains verified by the scoped operator reconciler.
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
require successful execution before controller deployment. The reconciler can
create only the fixed `homelab-cordium-runner-controller` credential, scoped to
the runner User/Policy, with a 30-day credential lifetime and client sessions
bounded by the User's 60-minute limit. It never rotates an existing credential
or overwrites an output file. Use an existing mode-0700 private directory:

```sh
nix develop --command python3 -I scripts/cordium-ci-reconcile.py \
  --runner-identities --execute --expected-sha FULL_REVIEWED_MAIN_SHA \
  --runner-credential-output /PRIVATE/runner-intake/auth-token
```

After identity/credential validation, place that file and the verified App key
in the two `homelab-production` environment secrets using stdin (never argv):

```sh
gh secret set CORDIUM_RUNNER_AUTH_TOKEN --repo Stuhlmuller/homelab \
  --env homelab-production < /PRIVATE/runner-intake/auth-token
gh secret set CORDIUM_RUNNER_APP_PRIVATE_KEY --repo Stuhlmuller/homelab \
  --env homelab-production < /PRIVATE/runner-intake/app-private-key.pem
gh workflow run cordium-runner-credentials.yml --repo Stuhlmuller/homelab \
  --ref main -f expected_sha=FULL_REVIEWED_MAIN_SHA
```

Require a successful intake and both ExternalSecret keys in the segregated
restricted namespace. The protected workflow temporarily uses the existing
hosted bootstrap runner; migrate its selector with the rest of #1276 after the
pool is proven. It verifies both identities and existing encrypted SSM slots
before writing, and limits its AWS session to only those two slots. A partial
write stays failed; inspect both parameter versions privately before retrying.
The native login/logout acceptance and refresh caveats are recorded in
`docs/secrets-aws-ssm.md`. No credential, parameter value, environment secret or
live Kubernetes object has been created by this branch preparation.
