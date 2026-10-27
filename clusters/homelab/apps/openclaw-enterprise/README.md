# OpenClaw Enterprise application candidate

This is a dormant local source for release `oce` in `openclaw-system`. Its Argo
Application and root Terragrunt unit are declared with automatic sync disabled;
they have not been applied. Agent activation remains false
in `scripts/config/openclaw-enterprise.json`. The stock chart comes from upstream
commit `33bb74590a749f37934da4502fca6035cd234a55`; this directory supplies
values, one EnvoyProxy image override, and Helm-style lifecycle hooks.

The pinned stock chart uses cert-manager to create the internal gateway root
`openclaw-system/occ-gateway-654a256bceae-root` and the separate Envoy listener
certificate `openclaw-system/oce-private-gateway-tls`. API and worker Pods mount
only the root's public `tls.crt`; T051 must preserve its private `tls.key` in the
protected recovery set. Traefik's `*.agents.oce.stinkyboi.com` certificate
terminates private user ingress and does not replace this internal CA.

`profile-input.json` is the non-secret input to upstream's `openclaw` profile
renderer. Its output is `installation.yaml` and `values.yaml`, with two reviewed
site adjustments: the gateway name is `oce-private-gateway`, and the startup
configuration has a versioned immutable Secret created from reviewed bytes by
the protected `openclaw-enterprise-startup` workflow after foundation sync.
`values.yaml` names that Secret and pins the SHA-256 of the exact Installation
bytes. `check-installation.mjs` is an unmodified copy of the chart file at the
pinned commit, SHA-256
`d6919627a375f708d4d7e8142aff8bbc783c0a0565254c4372b83b7a306ffd13`.
The focused test reruns the renderer against a supplied upstream checkout and
compares every output byte after those two site adjustments.
The Checkov secrets baseline pins three public PVC/Secret-name false positives
by path and fingerprint; all other findings still fail. This keeps the reviewed
Installation bytes and their checksum unchanged.

The Helm hooks follow weights `-40` (service accounts, scoped RBAC, policy and
script ConfigMap), `-18` (startup/dependency preflight), `-15` (API/worker
quiescence), then the unmodified chart's `-10` migration/bootstrap. The stock
bootstrap isolation policy and initialization service account run at `-30` and
`-20`. Preflight refuses a nonterminal previous initialization Job or Pod,
missing/changed immutable candidate, absent Secret keys, unbound bootstrap
claim, or PostgreSQL without a ready endpoint. Quiesce scales only the two
identified Deployments through `deployments/scale`, waits for every matching
Pod to disappear, and leaves writers stopped if migration or a later step
fails. Only a later normal full Sync restores one replica of each. No selective
sync, skip-hook option, self-heal, or independent writer can be allowed during
an Application sync.

The candidate intentionally cannot run yet. `operator@oce.example.invalid`
is an administrator placeholder rejected by preflight. No node has the
`oce-role` placement labels, and the local storage classes/bootstrap claim,
credential and capacity gates are unfinished. The foundation now declares the
dedicated PostgreSQL Service at `10.96.0.51`, but its Application has not been
applied or synced; qualify its reachability under the real Talos network policy
before registration. The bounded trusted-proxy CIDRs are the four observed
node PodCIDRs; chart API ingress additionally selects the exact Octelium
console Service and Traefik Pods. Verify proxy header rewriting and the actual
Envoy-to-agent source addresses before private route cutover.

The Secret's `openclaw.dev/installation-id` annotation cannot be known until
bootstrap. The T041 protected binding path must set/check that annotation against
`GET /installation` and verify both Ready Pods' exact startup binding before
reconciliation. `scripts/openclaw-enterprise-bind-installation.py` supplies the
source-only binder: it requires protected exact-`main` dispatch and a private
bootstrap-key file, proves the reviewed Secret and Ready controllers before and
after a UID/resource-version guarded annotation patch, and blocks on ambiguity.
It is not yet wired into a protected post-bootstrap workflow. The CLI's
read-only `check` consumes the resulting proof. With its protected credential
file, exact main SHA and journal, `reconcile` can create/adopt the logical
`claw` Namespace in the prepared `openclaw-agents` namespace, one native
Agent Configuration, and one stopped Embedded Agent. The Configuration uses
native model reference
`openai/openrouter/free` so OCE selects its supported `openai` Harness provider;
the OpenRouter wire model remains `openrouter/free`. It follows the pinned
first-Agent helper's `OPENAI_API_KEY` model secret reference, denies tools,
and starts with native control UI disabled. The dedicated model key is
still absent, so the agent has no `harnessAuth` binding and cannot be deployed.
`verify` checks the journaled identities, complete Configuration values,
generation and stopped Agent without sending inference. A failed `reconcile`
may have changed Enterprise and Kubernetes state. Inspect the journal and exact
API objects before retrying; unknown creates are recovered from owned reads,
not reposted. Keep activation false and preserve the journal for rollback.
Removing this logical Namespace needs a reviewed repository-owned cleanup path;
do not delete the physical tenant Namespace.

The source-only active path remains gated by the committed
`activationEnabled: false` and the absent dedicated OpenRouter key. A later
protected workflow must supply a 0600 file inside a 0700 private directory:
`{"parameter":"/homelab/openclaw-enterprise/model-api-key","version":1,"key":"<private>"}`.
The version is the SSM parameter version; `key` is never journaled or printed.
The CLI accepts this file through `--model-credential-file` only when the exact
reviewed `main` config enables activation. It then creates one OCC model Secret,
grants only this Agent principal `operate` on that Secret, binds `harnessAuth`,
provisions transport credentials and admits one revision. `verify` only reads
those identities, integration-free Agent/revision settings, and deployment
status. `stop` requires that journaled revision,
uses OCE's Agent stop API, and waits for a cleared active revision and no
runtime Pods. The staged operator also lists every Pod in the dedicated
`openclaw-agents` Namespace after the API reports zero; any Pod, including an
unlabelled or foreign one, or an uncertain list blocks stopped verification and
keeps a pending stop intent. Uncertain creates and
deploys are read back before retry; a changed key version blocks pending a
reviewed rotation path. These checks are offline fixtures, not live acceptance.

## Durable reconciliation journal

The reconciler cannot run safely from an ephemeral Actions runner. Its
`privateJournal.mountPath` is `/private/openclaw-enterprise/journal.json`, and
`ProtectedJournal` requires a process-owned `0700` parent, a `0600` file,
exclusive locking, and fsynced replacement. A lost runner disk would lose the
IDs and pending intent needed to distinguish a retry from a second create.
The chart's bootstrap claim holds the upstream service key and initial password;
it is writable by upstream initialization and must not hold this operator
journal.

The source-only operator bundle in `../openclaw-enterprise-operator/` declares a
separate retained journal claim, read-only Kubernetes proof permissions, a
projected service-account kubeconfig, and a narrow egress policy. No active
Argo CD Application references that bundle. The protected operations workflow
now routes fixed `reconcile`, `stop`, and `verification` names to a one-shot Job
dispatcher, but `journalOperator.enabled` is false; dispatch stops before
creating a Job. Full-sync keeps its existing runner path. Restore and
acceptance remain blocked pending their separate recovery and owner-session
contracts.

The Job mounts the whole journal claim writable at
`/private/openclaw-enterprise` so atomic replacement and `flock` work across
retries. It mounts the bootstrap claim read-only below that path and uses a
projected service-account token and cluster CA to reach the exact
`https://10.1.0.199:6443` Kubernetes API. The CI runner continues to use the
Octelium endpoint. The Job never receives the Octelium token. The startup
Secret GET permission is pinned to the current Installation digest and exposes
the Secret body. Change that Role with any Installation candidate change.

T022/T035 must choose the node and add a fourth static Retain PV, with its
directory precreated for UID 1000 at mode `0700` through a reviewed code
path. The PVC, PV, and bootstrap claim UIDs, path and node then belong in the
reviewed `journalOperator` declaration. The exact-source operator digest and
source SHA are already pinned there while the operator remains disabled.
UID 1000 matches the pinned upstream bootstrap Job, which writes its service
key as an owner-only `0600` file; a different UID cannot read that key from
the operator's read-only bootstrap mount. The dormant declaration still uses
UID 10001 to preserve the exact historical legacy-restore provenance input;
the dispatcher rejects that UID. T035 must review that provenance guard and
set UID 1000 before enabling the operator.
The operator image must contain a prior reviewed homelab source commit,
`python3`, `kubectl`, and `yq`. The dispatcher compares its embedded
reconciler, Installation, and values files with current `main`, then projects
current `main`'s config and SHA receipt through an immutable ConfigMap. The
later commit pins the image digest without a self-referential build.
[Protected publisher `40056484158`](https://github.com/Stuhlmuller/homelab/actions/runs/40056484158)
proved the build, signed Harbor receipt and complete authenticated pull.
Bootstrap-key UID access and in-cluster console TLS/network-policy proofs
remain pending. Changing `enabled` alone cannot pass the dispatcher.
The current model key Secret is in `openclaw-agents`, cannot be mounted across
namespaces, and lacks the versioned private-file shape required for active
reconciliation. Active deployment needs a separate reviewed credential path.

A canceled hosted runner can leave its Job running. The next dispatch checks
retained Jobs before creation, waits on the exact same Job when safe, and
refuses a different running, uncertain, or failed Job. Verification takes the
same journal lock as mutation and performs no inference. Failed Jobs and the
private journal stay in place for inspection; no automatic delete or retry
changes tenant state. The dispatcher emits only a fixed sanitized result, and
no journal or key is uploaded as a workflow artifact. T043 remains open until
the placement, image, access, and recovery proofs pass live.

At the pinned upstream revision, `native-admin` requires an authenticated
human session with exact Agent `administer`. Service keys cannot inspect its
origin. T048 records the returned `data.origin` during browser acceptance and
commits it as `privateOrigins.nativeOrigin`. Until that reviewed origin is
present, automated active reconciliation and verification block after the
first revision. With a reviewed origin, the source-only reconciler verifies
the first revision, journals a pending Configuration update, and PATCHes only
with its exact prior generation. A lost response is adopted only when the API
and owned Driver ConfigMap agree on the next generation and reviewed values;
an unchanged or foreign result blocks a second PATCH. The transition requires
the original generation 1 and journals the first revision before admitting
one generation 2 revision from the reviewed Configuration.
Lost deployment responses are adopted only from one exact new revision;
unknown or foreign outcomes block reposting. Read-only verification checks
both revisions and the active second deployment. T041 still needs protected
live proof. The GitHub runner also has no durable private journal mount, so
mutating workflow stages remain disabled pending a declared in-cluster path.
The chart's Kubernetes policy also needs nonempty reviewed `database.cidrs` and
`cluster.cidrs`; this candidate has explicit destinations, but Service DNAT
behavior still needs the isolated canary qualification.

Render and check locally with the pinned upstream checkout:

```sh
kubectl kustomize clusters/homelab/apps/openclaw-enterprise
kubectl kustomize clusters/homelab/apps/openclaw-enterprise-foundation
helm template oce /path/to/openclaw-enterprise/deploy/helm/openclaw-enterprise \
  --namespace openclaw-system \
  --values clusters/homelab/apps/openclaw-enterprise/values.yaml
python3 -I scripts/ci/openclaw-enterprise-chart-hooks-test.py \
  --upstream-root /path/to/openclaw-enterprise
python3 -I scripts/ci/openclaw-enterprise-lifecycle-test.py \
  --upstream-root /path/to/openclaw-enterprise
python3 -I scripts/ci/openclaw-enterprise-quiesce-test.py
```

The chart comparison asserts exactly one repeated resource identity, the
`oce-private-gateway` EnvoyProxy, and exact equality after adding only its
mirrored Envoy image. Actual Argo `RepeatedResourceWarning` count and the
installed Argo hook failure matrix remain live gates before registration.

The protected [operations workflow](../../../../.github/workflows/openclaw-enterprise-operations.yml)
also offers `enterprise_stage=full-sync` after registration and an approved
`installationPhase`. The current `unselected` phase blocks it before any sync.
Dispatch with `expected_sha=<CURRENT_MAIN_SHA>` and leave
`legacy_stage=none`. It verifies both Application sources, checks the platform
Envoy Gateway, then runs complete foundation and Enterprise Argo syncs at that
exact commit. It never selects resources, skips hooks, prunes, or forces apply.
The foundation must be healthy before Enterprise runs; a failed or interrupted
sync leaves the quiesce gate in charge of writer safety. Re-dispatch against
current `main` after inspecting failed hook and Application state. The separate
Enterprise reconcile, stop, restore, and acceptance stages remain unavailable
until a declared durable private journal and recovery operator exist.
