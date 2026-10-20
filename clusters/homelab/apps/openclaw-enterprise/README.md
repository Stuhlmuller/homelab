# OpenClaw Enterprise application candidate

This is a dormant local source for release `oce` in `openclaw-system`. No Argo
Application or root Terragrunt unit registers it. Agent activation remains false
in `scripts/config/openclaw-enterprise.json`. The stock chart comes from upstream
commit `33bb74590a749f37934da4502fca6035cd234a55`; this directory supplies
values, one EnvoyProxy image override, and Helm-style lifecycle hooks.

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
sync, skip-hook option, self-heal, or independent writer can be allowed when
the Application is registered.

The candidate intentionally cannot run yet. `operator@oce.example.invalid`
is an administrator placeholder rejected by preflight. No node has the
`oce-role` placement labels, and the dedicated PostgreSQL Service, local
storage classes/bootstrap claim, credential and capacity gates are unfinished.
The proposed PostgreSQL Service address `10.96.0.51` is reserved in source but
must be declared by T036 and qualified under the real Talos network policy
before registration. The bounded trusted-proxy CIDRs are the four observed
node PodCIDRs; chart API ingress additionally selects the exact Octelium
console Service and Traefik Pods. Verify proxy header rewriting and the actual
Envoy-to-agent source addresses before private route cutover.

The Secret's `openclaw.dev/installation-id` annotation cannot be known until
bootstrap. The T041 protected selected-Driver proof must set/check that annotation
against `GET /installation` and verify both Ready Pods' exact startup binding
before reconciliation. The CLI's read-only `check` gathers that proof; the
annotation binder is pending. With its protected credential file, exact main
SHA and journal, `reconcile` can create/adopt the logical `claw` Namespace in
the prepared `openclaw-agents` namespace, one native Agent Configuration, and
one stopped Embedded Agent. The Configuration uses native model reference
`openai/openrouter/free` so OCE selects its supported `openai` Harness provider;
the OpenRouter wire model remains `openrouter/free`. The dedicated model key is
still absent, so the agent has no `harnessAuth` binding and cannot be deployed.
`verify` checks the journaled identities, complete Configuration values,
generation and stopped Agent without sending inference. A failed `reconcile`
may have changed Enterprise and Kubernetes state. Inspect the journal and exact
API objects before retrying; unknown creates are recovered from owned reads,
not reposted. Keep activation false and preserve the journal for rollback.
Removing this logical Namespace needs a reviewed repository-owned cleanup path;
do not delete the physical tenant Namespace.

### Durable reconciliation journal

The reconciler cannot run safely from an ephemeral Actions runner. Its
`privateJournal.mountPath` is `/private/openclaw-enterprise/journal.json`, and
`ProtectedJournal` requires a process-owned `0700` parent, a `0600` file,
exclusive locking, and fsynced replacement. A lost runner disk would lose the
IDs and pending intent needed to distinguish a retry from a second create.
The chart's bootstrap claim holds the upstream service key and initial password;
it is writable by upstream initialization and must not hold this operator
journal.

The planned protected execution path is a one-shot, serialized operator Job in
`openclaw-system` with a separate retained local journal PVC mounted writable
only to that Job. Mount the bootstrap files read-only at
`/private/openclaw-enterprise/bootstrap`. The pinned operator image must carry
the reviewed script, config, `kubectl`, and an exact-source checkout for its
`--expected-sha` guard. Scope its service account to the exact startup Secret
and the controller and tenant objects the readback uses; the startup Secret
read includes its contents and cannot be treated as metadata-only access.
The Job must use a kubeconfig whose API endpoint is
`https://kubernetes-api-ci.stinkyboi.com`, matching the script's context check. The protected
workflow will pin the image digest, source SHA, PVC identity, and fixed Job
manifest, then wait for a sanitized result without logging credentials or
journal contents.

This Job and its workflow stage are not declared yet. T035 must first admit a
fourth retained local claim with safe UID and `0700` ownership, alongside the
three application claims. The operator image identity, source pairing, private
credential, archive, and isolated network-policy receipts are also pending.
Until those gates pass, the CLI remains a source-validated candidate; no
reconcile, stop, or verify stage may be exposed as an executable cutover step.

At the pinned upstream revision, `native-admin` requires an authenticated
human session with exact Agent `administer`. Service keys cannot inspect its
origin. T048 records the returned `data.origin` during browser acceptance;
the service-key reconciler cannot supply that receipt.
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
`installationPhase`. Dispatch with `expected_sha=<CURRENT_MAIN_SHA>` and leave
`legacy_stage=none`. It verifies both Application sources, checks the platform
Envoy Gateway, then runs complete foundation and Enterprise Argo syncs at that
exact commit. It never selects resources, skips hooks, prunes, or forces apply.
The foundation must be healthy before Enterprise runs; a failed or interrupted
sync leaves the quiesce gate in charge of writer safety. Re-dispatch against
current `main` after inspecting failed hook and Application state. The separate
Enterprise reconcile, stop, restore, and acceptance stages remain unavailable
until a declared durable private journal and recovery operator exist.
