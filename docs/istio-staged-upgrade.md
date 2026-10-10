<!-- markdownlint-disable MD013 -->

# Istio staged validation and recovery design

HOME-56 remains **operational NO-GO**. This slice adds offline validation and
an inactive design, not a rollout executor. Active Istio pins remain 1.27.3.
Nothing under `specs/istio-upgrade` is registered with Argo CD or Terragrunt.
The committed `hold.json` cannot authorize promotion. Its checker rejects
attempts to accept evidence or enable execution by editing booleans.

## Inputs, ownership and scope

Design inputs are the HOME-56 QA report/evidence bundle (comment
`19005c28-aacb-40eb-948b-aabe4c3c3ba9`) and Recovery plan (comment
`6ffa71d9-1e96-476d-8a07-8a84f526d0fd`), both dated October 4, 2026 and bound
to `33f2277e50f34d69091bfbb6472eef0bf6486699`. Their live fixtures and recovery
checks remain NOT_RUN. This implementation starts from main
`0ad30199ed7fde70832410af39db74dbbbc1ba19`; Istio registration and values are
unchanged, while Wazuh and other application changes require a fresh traffic
inventory before operational acceptance. Prior evidence is not transferred
to the new whole-repository revision.

Ownership reconciliation: HOME-10 history and Platform Operations' assigned
HOME-17 concern existing GitOps/catalog gates; the open PR inventory contains
no competing HOME-56 implementation. HOME-3/#1116 retains network enforcement;
HOME-60/#1168 now integrates the separate Kubernetes/Talos preparation.
HOME-57 owns Harbor collector changes. This slice changes no shared stack,
AppProject, catalog, workflow, CI dispatcher or active service values. Platform
Operations retains those integration files and the eventual executor. SRE owns
these new offline files under the explicit HOME-56 implementation assignment.
Separate Platform review of this design is still required; history inspection
is not approval of future shared-file edits.

## Chart-specific values and reproduction

`specs/istio-upgrade/chart-values.json` contains six inactive value maps, one
for each release. They use chart-specific keys and explicitly retain the
checked DNS/IPv6-off intent, memory requests and gateway service ports/types.
The base chart has no unrelated application settings. The ingress chart no
longer receives unsupported `cni`, `gateways` and `meshConfig` keys.

Standalone chart defaults use root `ambient` and `resources` keys. Do not infer
that the active nested equivalents are ignored: actual 1.27.3 rendering with
the active values and stack override confirms DNS/IPv6 false and istiod 512Mi.
The candidate inputs preserve those observed effects. CNI startup rule
reconciliation is explicitly false in the inactive candidate, so 1.29's default
does not silently enable it. Network/Security must review that choice and its
Pod enrollment consequences before adoption. Do not replace active values with
these inputs based on a schema pass alone.

The repository validator never skips chart schema validation. Only the gateway
archives contain a values schema; other successful renders are not full schema
validation. Rendered assertions additionally check CNI ConfigMap settings and
annotation, istiod/ztunnel memory, ztunnel IPv6/rollout bounds, and gateway
exposure. Input checks reject cross-chart top-level keys, but do not claim a
complete custom schema for every possible upstream value.

`chart-lock.json` records the 20 archive hashes/URLs from QA's verified bundle.
The checker verifies bytes and Chart metadata before Helm runs. This is integrity
against reviewed locks, not signature or cold-recovery availability evidence.
Supply local archives from that bundle; the validator never downloads charts
or contacts a cluster. Use Python with PyYAML and Helm 3.19.0:

```sh
python3 scripts/ci/istio-upgrade-check-test.py
python3 scripts/ci/istio-upgrade-check.py
python3 scripts/ci/istio-upgrade-check.py --helm /path/to/helm \
  --charts /path/to/home56-qa/charts --version 1.27.3
python3 scripts/ci/istio-upgrade-check.py --helm /path/to/helm \
  --charts /path/to/home56-qa/charts --version 1.28.10
python3 scripts/ci/istio-upgrade-check.py --helm /path/to/helm \
  --charts /path/to/home56-qa/charts --version 1.29.8
python3 scripts/ci/istio-upgrade-check.py --helm /path/to/helm \
  --charts /path/to/home56-qa/charts --version 1.30.5
python3 scripts/ci/istio-upgrade-check.py --promotion-check
```

Exit 0 means the requested offline checks passed; the no-argument command
explicitly reports render NOT_RUN. Exit 1 means validation failed, including
missing 1.31.1 locks. `--promotion-check` returns 2 and BLOCKED even when all
offline checks pass. No receipts can unlock this design-only tool. Charts are
not bundled in Git, and the new checker is not wired into shared CI yet.

Initial validation: 14 negative/contract tests and 24 strict chart renders
passed. Gateway output still uses injection-dependent `auto`; the 1.30.5
images still use the changed registry. No hub override, catalog entry or
artifact acceptance is introduced. Full static validation stops at missing
Terragrunt after the runtime bootstrap check. Full policy/CI, admission,
injection, generated inventory and operational checks remain unverified.

## Durable hold contract for the future executor

Candidate hops are 1.27.3 → 1.28.10 → 1.29.8 → 1.30.5 → 1.31.1.
These are assessment candidates, not executable pins. Every hop starts in HOLD
and ends in an accepted checkpoint or ABORTED/HOLD. No automatic next-hop
advance and no overlapping Talos, Kubernetes, mesh or enforcement operation.

The future implementation must persist a private, non-secret transaction
receipt outside the affected cluster. It must bind the issue/decision, exact
signed source and recovery SHAs, applied Application/config hashes, previous
checkpoint, component and node digests, evidence timestamps/expiry, stage,
executor identity reference, deadlines and approval window. Record intent
before an operation, then observed completion; a crash or unknown outcome
returns to HOLD and read-only reconciliation, never replay or retry by guess.

Both ownership layers must honor the same stage: Terragrunt owns Application
registration and Argo owns rendered resources. Platform must first implement
and test a repository-controlled hold that prevents auto-sync, self-heal,
retry, pruning and unrelated apply paths from advancing versions or removing
shared CRDs/RBAC. Disabling automated sync alone does not stop an in-flight
operation. The executor must prove quiescence and applied ownership before
changing a component. This PR does not implement that mechanism; the current
active Application remains automated. Do not treat this document as a live
hold, issue ad hoc patches, or apply the JSON design to a cluster.

Each stage is a separate exact reviewed desired-state revision with a durable
stop after it. A readiness receipt belongs to that revision, not just a Pod's
Ready condition. Source order and Application registration dependencies are
not runtime health barriers.

| Stage | Required acceptance before next stage | Failure disposition |
| --- | --- | --- |
| A: base/CRDs | Served/stored API compatibility, admission and shared ownership across both versions | Preserve CRDs/objects; no blind schema downgrade, prune or etcd restore |
| B: istiod | Admission, XDS/config delivery, certificates and identity/traffic checks; old data plane retained | Restore old istiod only if no newer proxy/CNI exists and retained CRDs/RBAC are compatible |
| C: CNI | Per-node coverage, filesystem/kernel/backend and existing/replaced Pod rules; operator and traffic checks | Retain new istiod; use rehearsed version-specific CNI host-state recovery or stop |
| D: ztunnel | One-node completion, XDS, allowed/denied and long-lived/new connections | Retain new istiod; recover changed nodes with inventory and prior accepted bytes |
| E: gateways | Both gateways and discovered waypoints/sidecars; injected images, paths, TLS/SNI/Host and access | Recover gateways first, then ztunnel, then CNI; old istiod only after compatible data plane |

Skew limits and reverse order are constraints, not a certified downgrade
procedure. Mixed-node state and CNI host rules require exact-version rehearsal.
Image reversal does not prove rule reversal. Never flush iptables, disable
enrollment/STRICT, relax policy or reboot as an assumed recovery shortcut.

## Readiness, access and recovery receipts

Before each hop, require complete forward AND previous recovery chart/image
layers, signatures/platform identities and injection output. Prove empty-cache
retrieval independent of mesh, Harbor and cluster DNS. Current strict Harbor
mirrors (`skipFallback=true`) make upstream fallthrough/cached layers inadequate.

Require separately authorized direct LAN Kubernetes/Talos TLS-authenticated
access from an independent executor, with identity/expiry references only.
Octelium relies on the mesh and the Tailscale fallback runs in Kubernetes;
neither establishes independence. Healthy-mesh reachability alone does not
prove fresh sessions survive an outage. A contained lab must demonstrate that
property; no production fault injection is authorized.

Recovery must supply current off-node etcd integrity/retrieval receipts,
private machine-config/cluster-secret and mesh trust-root custody references,
IaC backend/KMS access and application-consistent access-plane backups.
Etcd snapshots do not protect PVC contents. Preserve old good snapshots and
original volumes; no secret bodies, real backups or certificates in Git/issues.

Recovery's proposed, **unapproved/unmeasured** budgets are: pre-hop etcd age
at most 30 minutes, no accepted application data loss, mesh recovery within
30 minutes including approval time, and stage readiness within 10 minutes.
An unset application interruption budget blocks preflight. An unexpected allow,
plaintext regression, missing CNI coverage, unknown skew or API/etcd degradation
aborts immediately. First failed independent endpoint read holds; a second
failure within 30 seconds aborts. Missing artifacts/executor or ambiguous state
stops recovery rather than improvising a downgrade. These thresholds require
ratification and measurement before an executor can use them.

After recovery require actual intended versions and per-node coverage, XDS,
admission, TLS/identity, both gateway paths, direct operator access, DNS,
Multus/HOME-3 behavior, and allowed AND denied tests with backend observations.
Repeat two successful fixture passes five minutes apart. If API/etcd is lost,
preserve disks/PVCs and route to separately reviewed source-stack disaster
recovery; a Git revert or successful offline etcd test is insufficient.

## Remaining owners and actions

| Owner | Required action; every row remains blocking |
| --- | --- |
| Platform Operations / QA | Resolve 1.31.1 charts and 1.30/1.31 image identities/signatures/layers; retain recovery artifacts; review catalog/source/AppProject integration separately |
| QA | Resolve gateway injection and complete schema/API/generated inventory; rerun exact revision with full CI; rehearse every forward/reverse stage |
| Platform Operations | Implement both-layer quiescent hold, durable receipts, per-stage revisions, guarded executor and CRD/RBAC ownership; wire reviewed checker into shared CI |
| Recovery | Verify independent access/artifact retrieval, current backups/private custody and measured per-hop recovery; ratify budgets |
| Network/Security / HOME-3 | Review explicit CNI reconciliation; test shared-SA callers, Fleet STRICT, plaintext/secondary interfaces, indirect EnvoyFilter writers, direct backends and gateway normalization |
| Release | Produce and independently review signed final revision; API-created draft commits do not waive signing |
| Decision Review | Decide bounded EOL bridge versus supported-environment migration after technical evidence; no blanket exception |
| Delegated decision lead | Separately authorize exact bounded live evidence, rollout and recovery actions with revisions, executor and window |

The current draft grants none of these approvals. Retain HOME-56 in progress.
Use the QA bundle's 35 proposed fixtures as inputs, refreshing them for current
Wazuh/LiteLLM and generated workloads. Negative tests must cover unrelated
callers sharing `default` SAs as well as other SAs; include Fleet STRICT,
SNI/Host disagreement, authority case/port variants and bootstrap/direct paths.
Timeouts are inconclusive, and source fixture passes do not prove enforcement.

Upstream references underlying the supplied reviews:
[ambient upgrades](https://istio.io/latest/docs/ambient/upgrade/helm/),
[support/skew](https://istio.io/latest/docs/releases/supported-releases/),
[1.29 changes](https://istio.io/latest/news/releases/1.29.x/announcing-1.29/upgrade-notes/),
[1.30 changes](https://istio.io/latest/news/releases/1.30.x/announcing-1.30/upgrade-notes/),
[1.31 changes](https://istio.io/latest/news/releases/1.31.x/announcing-1.31/upgrade-notes/).
Revalidate current upstream guidance before selecting executable artifacts.
