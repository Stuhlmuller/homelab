# OpenClaw Enterprise application candidate

This is a dormant local source for release `oce` in `openclaw-system`. Its Argo
Application and root Terragrunt unit are declared with automatic sync disabled;
they have not been applied. Agent activation remains false
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
sync, skip-hook option, self-heal, or independent writer can be allowed during
an Application sync.

The candidate intentionally cannot run yet. `operator@oce.example.invalid`
is an administrator placeholder rejected by preflight. No node has the
`oce-role` placement labels, and the local storage classes/bootstrap claim,
credential and capacity gates are unfinished. The foundation declares its
PostgreSQL Service at `10.96.0.51`; qualify that address under the real Talos
network policy before first sync. The bounded trusted-proxy CIDRs are the four
observed node PodCIDRs; chart API ingress additionally selects the exact Octelium
console Service and Traefik Pods. Verify proxy header rewriting and the actual
Envoy-to-agent source addresses before private route cutover.

The Secret's `openclaw.dev/installation-id` annotation cannot be known until
bootstrap. The T041 protected selected-Driver proof must set/check that annotation
against `GET /installation` and verify both Ready Pods' exact startup binding
before reconciliation. The CLI's read-only `check` gathers that proof; the
annotation binder is pending. With its protected credential file, exact main
SHA and journal, `reconcile` can create/adopt the logical `claw` Namespace in
the prepared `openclaw-agents` namespace, then exits blocked while Agent work
remains unfinished. A failed `reconcile` may therefore have changed Enterprise
and Kubernetes state. Inspect the journaled Namespace ID, exact API GET and
owned Kubernetes Namespace/NetworkPolicies before retrying with the same
journal; unknown creates are not reposted. Keep activation false and preserve
the journal for rollback. Removing this logical Namespace needs a reviewed
repository-owned cleanup path; do not delete the physical tenant Namespace.
Tenant `verify` remains read-only and blocked.
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
installed Argo hook failure matrix remain live gates before first sync.
