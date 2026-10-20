# Validation and Execution Guide

Run from the repository root. This is a plan, not an executed deployment.
Existing commands below are available now. Commands marked **implementation
required** become runnable only after the corresponding scripts/manifests exist.
Never skip a missing command or failed gate and report the stage complete.

## 1. Review Inputs and Read-Only Baseline

```sh
python3 -B .specify/scripts/python/check_prerequisites.py --json
git diff --check
kubectl --request-timeout=15s get nodes \
  -o custom-columns=NAME:.metadata.name,KUBELET:.status.nodeInfo.kubeletVersion,OS:.status.nodeInfo.osImage
kubectl --request-timeout=15s get daemonsets -A \
  -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,READY:.status.numberReady,DESIRED:.status.desiredNumberScheduled
kubectl --request-timeout=15s get storageclasses
kubectl --request-timeout=15s top nodes
```

Expected current baseline is recorded in [research.md](research.md#r4--capacity-is-a-real-execution-gate).
Refresh it before selecting actual nodes. No suitable canary or sufficient placement
has been approved. Keep detailed Pod/policy snapshots and storage/credential
inventories in private files; do not paste them into public logs or PRs.

Review the owner's fresh-install scope in [spec.md](spec.md). Old data must be
archived, but old integrations/state must not be copied into the fresh agent.

## 2. Local Implementation Gates

After source changes are implemented, run:

```sh
nix develop --command terragrunt hcl fmt --check
nix develop --command terragrunt --working-dir IaC stack generate
nix develop --command terragrunt hcl validate
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
python3 -I scripts/ci/openclaw-assistant-check.py
python3 -I scripts/ci/openclaw-runtime-storage-check.py
node scripts/ci/openclaw-github-check.cjs
git diff --check
```

Render all new/affected Helm and Kustomize sources with exact pins. Inspect complete
Application inputs, hook weights, privileges, immutable images, replica/ownership
boundaries, storage classes and namespace allowlists. Confirm the expected source
chart exists at the pinned commit; a chart version alone is insufficient.
Check the single shared Gateway API owner and the effective EnvoyProxy image
override; see [the routing contract](contracts/enterprise.md#gateway-api-and-private-envoy).

**Implementation required:**

```sh
python3 -I scripts/ci/platform-maintenance-test.py
python3 -I scripts/ci/network-policy-enforcement-test.py
python3 -I scripts/ci/openclaw-enterprise-test.py
python3 -I scripts/ci/openclaw-retirement-test.py
python3 scripts/platform-maintenance.py validate \
  --config scripts/config/platform-maintenance.json
python3 scripts/openclaw-enterprise.py check \
  --config scripts/config/openclaw-enterprise.json
```

The platform `validate --config` command checks only the pinned declaration.
To validate private Talos bases and every target patch offline, also pass both
`--control-plane-config` and `--worker-config` paths to mode-0600 files.
Neither form proves recovery or live readiness.

Expected: no unsupported upgrade hops, CNI writes, unknown live-operation inputs,
plaintext secrets, duplicate-create retry, unsafe archive path, or bypassed
quiescence. Fixtures prove error paths; they do not prove live enforcement.

## 3. Archive and Stop Legacy OpenClaw

Implement the [retirement contract](contracts/enterprise.md#legacy-shutdown-and-new-recovery)
before changing replicas. Through reviewed GitOps, quiesce old runtime/jobs,
verify zero writers, create the final multi-root archive and perform an isolated
restore. Keep both local authoritative databases, NAS files, old full archives
and historical runtime checkpoint in the protected inventory.

The read-only status helper and protected stages are implemented. The offsite
bucket is applied, the reader is Ready, and the legacy writer is stopped. If the
reader is not Ready or its retained mount identities differ, return it to zero
replicas through GitOps before another archive attempt. Validate the offline
contracts first:

```sh
python3 scripts/ci/openclaw-retirement-test.py
python3 scripts/ci/openclaw-retirement-status-test.py
python3 scripts/ci/openclaw-enterprise-operations-test.py
kubectl kustomize clusters/homelab/apps/openclaw >/dev/null
```

Follow the fixed `inventory`, `archive`, and `verify` dispatches in the
[OpenClaw runbook](../../clusters/homelab/apps/openclaw/README.md#enterprise-replacement-retention).
The protected workflow produces the fresh private Kubernetes status and checks
PVC/PV UIDs against the pre-shutdown inventory. Private files stay outside Git.
Expected: all state roots verified, old gateway stopped, no messages/jobs/writes,
retained volumes intact. Do not proceed on a partial archive or uncertain writer.
Remeasure capacity after shutdown; do not assume it resolves all node deficits.

## 4. Publish, Review, and Run Platform Maintenance

Publish all required image digests through the existing Harbor workflow before
consumer changes. Review authenticated Terragrunt plans for affected scopes;
secret-bearing units use their separate protected plan path. Apply registration
through `terragrunt-apply.yml` with the exact current `main` SHA, following
[CI/CD](../../docs/ci-cd.md); do not replace it with blanket stack apply.

Execute the new platform-maintenance workflow's declared stages, one at a time,
after its source and policy tests pass. Use [the platform contract](contracts/platform.md)
for the exact input/receipt semantics. No raw `talosctl upgrade`, `kubectl patch`,
or `kubectl delete` commands are prescribed as operator shortcuts here.

Expected after version stages: Talos 1.14.4, Istio 1.30.6, Kubernetes 1.35.9 on
all relevant nodes/components; preserved API, etcd, DNS, mesh, access, storage,
webhook and application checks. Stop between every node/minor if any check fails.

## 5. Qualify Enforcement

Capture private Pod and policy snapshots and render every relevant policy owner.
Run the existing inventory tool against concrete files, for example:

```sh
python3 scripts/network-policy-inventory.py \
  --pods /secure/oce-migration/pods.json \
  --policies /secure/oce-migration/policies.json \
  --render /secure/oce-migration/rendered-policies.json \
  --review /secure/oce-migration/policy-review.json \
  --namespace network-policy-canary \
  --fail-on-findings
```

Expected canary result: no unreviewed/drifted/bypass findings. Review ingress
separately; this helper primarily checks egress. Repeat for affected namespaces
and expand only after [all required traffic/lifecycle cases](contracts/platform.md#required-traffic-matrix)
pass on actual Talos nodes.
For Cordium and Octelium snapshots, repeat `--render` with
`clusters/homelab/apps/cordium-bootstrap/generated-networkpolicies.json` to
compare the three source-reviewed Cordium Genesis policies with live specs.
The fixture is not a Kustomize resource and does not approve their traffic.
Also pass `clusters/homelab/apps/octelium/generated-networkpolicies.json`
as another `--render` input for the four source-reviewed Octelium Genesis
policies. It does not approve `svc-upstream` public all-port egress.
Pass `clusters/homelab/apps/octelium-enterprise/generated-networkpolicies.json`
as one more `--render` input for the ten source-reviewed Enterprise Genesis
policies. This fixture does not approve their ingress traffic.

Stock OCE's public TCP/443 rule intentionally fails the stricter broad-egress
finding in this helper. Preserve that finding and the helper's strict behavior;
use a separate feature check to compare the complete policy to pinned upstream
expected semantics and prove its private-range exclusions. Do not relabel this
as passing global egress hardening, ignore unexpected findings, or silently add
permissive policies. This replacement accepts the documented stock boundary.

Expected live proof includes denied traffic from the first application operation,
enforcer restart/crash, API loss, Pod/IP reuse and node reboot. DaemonSet readiness
and a local container fixture are insufficient. Failures block Enterprise.

## 6. Install Foundation and Enterprise

Apply foundation registrations through the shared protected path. Verify
PostgreSQL TLS/role separation, independent restore, ESO readiness, local storage
identity/ownership, bootstrap retention, GatewayClass/CRDs, private Envoy and DNS.
Verify Istio's watched API versions and the actual Envoy proxy digest; require
working private routes after a cold proxy restart and no xDS rejections.
Then perform one full Enterprise sync with the ordered hooks in the
[installation contract](contracts/enterprise.md#installation-and-upgrades).

Expected: invalid configuration fails before old writers stop; any failure after
quiescence leaves them stopped; only successful initialization permits normal
Sync to resume them. Test interrupted sync, retry, Argo restart, and stale Job
handling on the installed Argo version. No selective/skip-hook sync is allowed.

**Implementation required:**

```sh
python3 scripts/openclaw-enterprise.py verify \
  --config scripts/config/openclaw-enterprise.json
kubectl --request-timeout=15s -n openclaw-system get deployments,jobs,pvc
kubectl --request-timeout=15s -n argocd get applications \
  openclaw-enterprise-foundation openclaw-enterprise
```

Expected: observed source/image identities match, Applications Synced/Healthy,
initialization terminal and successful, database/agent recovery paths verified.
An inactive agent while its provider input is missing is an explicit incomplete
state, not successful replacement.

## 7. Activate and Accept the Fresh Agent

Supply the explicit supported model ID and new provider credential through the
declared contract. Only then enable activation through reviewed desired state.
The first deploy runs a real provider probe. Reconciliation runs twice; require
unchanged IDs/grants and no duplicate deployment from a lost response.

Perform these checks through the actual owner access path:

1. Existing OpenClaw URL reaches the authenticated console; native agent link
   resolves its exact OCE-returned origin with trusted TLS and working WebSocket.
2. Three consecutive owner conversations return real model responses.
3. Unauthorized console, native agent and direct gateway/Envoy access fail.
4. Model failure is visible; no old credential, Discord delivery or schedule is
   active in the new runtime. Confirm fresh workspace and distinct agent identity.
5. Deploy one configuration revision, restart/recreate its Pod through the
   declared lifecycle, and verify fresh Enterprise state survives.
6. Restore a complete new recovery set into isolation; verify database, tenant
   resources, agent state and bootstrap/auth material together.
7. Observe 24 hours, including a scheduled backup, node/resource health, required
   shared-service checks, and absence of legacy writes/deliveries.

Record sanitized revision-bound receipts. Browser redirects or healthy Pods alone
are not proof of agent inference, authorization, or data recovery.

## 8. Retire or Recover

After acceptance, retire only old active resources and obsolete grants through
the protected workflow; retain old data and shared dependencies. Confirm Argo
finalizers cannot prune the retained claims.

On failure, stop the new agent through OCE while the control plane is available.
Verify stopped desired state, zero runtime Pods and no uncertain writers; then
quiesce API/worker, preserve new state, and restore the old compatible service
through GitOps. Test this order and interrupted shutdown. An unavailable control
plane or uncertain agent shutdown requires the declared disaster-recovery path.
Policy rollback first stops affected tenants and removes only owned firewall
rules. Kubernetes failure uses reviewed forward repair/disaster recovery, never
an assumed downgrade.
