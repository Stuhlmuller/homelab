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
GitHub. The factory permits GitHub's six-hour default job budget plus five
minutes for runner pickup/shutdown; existing job deadlines remain unchanged.
Cleanup attempts Workspace and runner
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
for package and Actions downloads. Its TCP 8080 ingress exception is limited to the native Nocturne and API
controller Pods described below. Verify actual control connectivity before
activation. Tests prove the template's selectors/CIDR intent, not CNI enforcement
or supervisor readiness.

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

The entrypoint checks its clean immutable source and pinned client, acquires
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

The build-only workflow runs both recipes from a fixed public checkout with an
empty Docker context. It verifies the controller's non-root UID, read-only root
filesystem, dropped capabilities and private projected-file copying without
network access in the smoke container. It publishes no image and consumes no
production credentials. Native API, Docker-in-Cordium, session renewal and
workload isolation remain separate live acceptance gates.

The optional serve mode polls active workflow runs and every job page, matching
all requested labels case-insensitively. It refreshes the scoped App client and
rechecks current main and the native identity on each cycle, executes one
Workspace lifecycle at a time, and stops on drift or any lifecycle failure.
A private nonblocking lock prevents two processes sharing one login directory.
GitHub caps filtered run searches at 1,000 results; the loop rejects that boundary
instead of silently omitting jobs. Partition inventory by time before supporting
that scale.

After activation gates and a verified dedicated login, add the serve flag:

```sh
python3 -I scripts/cordium-runner.py --serve \
  --expected-sha FULL_REVIEWED_MAIN_SHA \
  --app-key-file /PRIVATE/RUNNER_APP_KEY.pem \
  --auth-token-file /PRIVATE/RUNNER_AUTH_TOKEN \
  --homedir /PRIVATE/DEDICATED_RUNNER_LOGIN
```

This process is not deployed yet. Use one replica with Recreate rollout when
packaging it; the filesystem lock is not a distributed leader lease. The private native
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

On 2026-10-11, hosted build run [38120324201](https://github.com/Stuhlmuller/homelab/actions/runs/38120324201) passed both image builds and the non-root/read-only/network-disabled controller smoke at head ebe67f7. Images were local to that job and were not published. Cordium execution, actual credential refresh, policy enforcement, publication/cold pulls and complete workflow acceptance remain unproven.

## Protected private publication

After reviewed merge and release of the cutover hold, dispatch the exact current
main through cordium-runner-publish.yml with expected_sha. It rebuilds/smoke-tests
both fixed images before registry login, enters homelab-production, shares the
existing harbor-packages-production concurrency group, and uses the existing
publisher/signing identity. The helper's publish-cordium mode accepts no image
name or destination input and requires manual current-main dispatch.

Only homelab-cordium-runner and homelab-cordium-controller in the private Harbor
homelab project are pushed. Each digest is checked, fully downloaded with the
private authentication, and checked again before the repository-owned signer
receives it. The enrolled public-key fingerprint and both signatures must verify.
Only then are fixed digest references emitted into a 30-day artifact. A digest,
complete-pull, signer identity or signature failure withholds successful outputs
and still runs the existing cleanup. NOFX and public mirror modes retain their
original destination scopes. Forty-five mocked publisher regression tests passed;
this Cordium publication path has not been executed live.

Use the returned immutable references in a reviewed Deployment change only after
cold-pull acceptance. Do not treat the build-only workflow as registry publication.


## Runner canary before workflow cutover

After the controller and isolation gates pass, dispatch the exact current main:

```sh
gh workflow run cordium-runner-canary.yml --repo Stuhlmuller/homelab \
  --ref main -f expected_sha=FULL_REVIEWED_MAIN_SHA -f mode=checks
gh workflow run cordium-runner-canary.yml --repo Stuhlmuller/homelab \
  --ref main -f expected_sha=FULL_REVIEWED_MAIN_SHA -f mode=force-failure
```

The canary uses only `cordium-canary` runners. It checks the actual runner name,
Linux/x64 platform, reviewed source, Nix, Python toolcache and a Docker action.
The second mode must fail with exit 42. Also dispatch `mode=session-renewal`;
its fixed 65-minute heartbeat crosses the initial one-hour credential boundary,
checks Docker afterward, and allows 120 minutes including compatibility setup. Cancel an active canary separately and
verify controller cleanup after success, failure and cancellation: no registered
runner, native Workspace, Deployment, Pod, PVC or owned NetworkPolicy remains.
A green job alone does not prove cleanup. Keep workflow selectors unchanged
until these live cases pass; then switch the pool and all jobs to `cordium` in
the reviewed cutover. Neither canary mode has run live yet.


## Native supervisor control traffic

The per-Workspace policy permits TCP 8080 ingress only from Cordium Nocturne and
`default-cordium.octelium-api` service Pods in `octelium`. Both namespace and Pod
selectors must match. Nocturne initializes and observes the supervisor; the
Cordium API forwards `exec` to it. These labels were verified against the live
controller/service Pods on 2026-10-11. An empty ingress list prevents these
operations once policy enforcement is active.

The pinned [supervisor address helper](https://github.com/octelium/cordium/blob/e12b0b16d5fe94716e414fca7cfdc10b21014f2c/cluster/common/suputils/utils.go),
[Nocturne initialization](https://github.com/octelium/cordium/blob/e12b0b16d5fe94716e414fca7cfdc10b21014f2c/cluster/nocturne/nocturne/controllers/workspaces/watcher.go)
and [API exec forwarding](https://github.com/octelium/cordium/blob/e12b0b16d5fe94716e414fca7cfdc10b21014f2c/cluster/apiserver/apiserver/wrks/terminal.go)
are the source for this exception. Browser portal, SSH and UDP tunnel ingress
are not required by the runner lifecycle and have no exception. Live acceptance
must prove initialization and exec succeed while unrelated Pods cannot connect;
source/readback checks alone do not prove enforcement or connectivity.


## Controller image and current main

Publishing an image at commit A and committing its Deployment at B necessarily
moves main. The controller therefore accepts current main only when A remains
an ancestor and every declared executable/client/image/runner-contract path is
identical to the baked source. It fetches public main into a private bare mirror
under `/data/cordium-runner/source.git`; fetched files are never executed and the
image checkout stays unchanged. Each queue cycle repeats the comparison and
creates Workspaces at the verified current main SHA, rather than the image SHA.

Deployment, unrelated workload, workflow-selector and documentation commits can
advance main without disabling an unchanged controller. Changes to controller
code, imported helpers, runner Dockerfiles, client installers or `.cordium`
contracts stop provisioning and require a rebuilt, verified image and reviewed
Deployment update. Rewritten main history, dirty image source or a failed fetch
also stops provisioning. Operator one-shot/serve commands retain their exact
local/expected/current-main check. Tests cover a shallow image checkout, its
later Deployment commit, executable drift, restoration and rewritten history.


## GitHub-managed Code Quality jobs

The 33 local jobs are not the complete live Actions inventory. On 2026-10-11,
GitHub Code Quality was configured for Go, JavaScript/TypeScript and Python with
`runner_type: standard`, an empty runner label and AI findings disabled. Its
`dynamic/github-code-quality/codeql` workflow is generated by GitHub, so changing
YAML selectors cannot migrate it. The legacy dynamic code-scanning workflow is
still listed, but code-scanning default setup is `not-configured`; preserve the
repository-owned advanced Actions scan.

The [Code Quality setup API](https://docs.github.com/en/rest/code-quality/code-quality)
supports runner selection. The fixed helper previews or changes only
`runner_type: labeled` and `runner_label: cordium` on `Stuhlmuller/homelab`.
It refuses to enable an unconfigured service and verifies that languages, state
and AI findings remain unchanged. Keep the App key outside runner Workspaces.

```sh
python3 -I scripts/cordium-code-quality.py \
  --app-key-file /PRIVATE/RUNNER_APP_KEY.pem
```

Preview reports `verified: false, changed: false` until the managed selection
matches. Only after the live canary, isolation and cleanup gates pass, enable the
pool's `cordium` label through reviewed code/image delivery and run from exact
current main:

```sh
python3 -I scripts/cordium-code-quality.py \
  --app-key-file /PRIVATE/RUNNER_APP_KEY.pem \
  --execute --expected-sha FULL_REVIEWED_MAIN_SHA
```

A validation run ID or `changed: true` is an acknowledgement, not acceptance.
If `verified` remains false, observe that exact run and repeat the read-only
preview; do not repeatedly PATCH pending setup. Require matching readback and
successful generated Code Quality jobs with Cordium runner names before counting
this part of migration complete. Rollback changes the helper's desired runner
contract in a reviewed commit and reconciles it before retiring the pool. The
live preview was exercised; no managed runner selection was changed.


## Runner lifetime and credential expiry

The factory now covers the [default 360-minute GitHub job deadline](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idtimeout-minutes)
plus five minutes of runner pickup/shutdown grace. The regression suite checks
every declared local job, using the default when no timeout is specified. A
larger future job budget requires increasing the factory bound in reviewed code.
Existing workflow timeouts are unchanged.

GitHub cleanup creates a fresh repository-scoped installation client after the
job, rather than reusing its potentially expired registration client. The
controller refreshes projected private copies first; the one-shot path rereads
its private App key file. Refresh failure remains a cleanup failure and stops
the controller, while Workspace/Pod/PVC/policy cleanup still runs independently.
Tests simulate an expired registration token and a failed cleanup refresh.

Long-job native session renewal, credential rotation and cleanup still require
live acceptance before cutover. Short canaries do not prove this path.
