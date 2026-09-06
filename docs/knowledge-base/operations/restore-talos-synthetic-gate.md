# Synthetic restore gate on Talos

Related: [[restore-talos-runtime-validation]], [[restore-image-anonymous-pull]],
[[restore-image-publication]], [[restore-egress-boundary]], [[validation-gates]].

## Status and entry point

`.github/workflows/restore-talos-synthetic.yml` owns a manually dispatched,
synthetic-only compatibility check. It creates one bounded Job and immutable
fixture ConfigMap in the existing `octelium-storage` namespace, inspects the
admitted resources, releases one scheduling gate, verifies results, then removes
the exact owned objects. It creates no namespace, RBAC, persistent volume or
production backup reader. No live Kubernetes Secret is mounted; all fixture
bytes are public code or generated synthetic PostgreSQL data.

The fixed `images/postgres-restore-egress/published-image.json` is deliberately
absent. **Actual Talos validation remains unverified and the real restore
candidate remains inactive.** There is no image, node, script or manifest
override input. Do not dispatch until the reviewed publication and anonymous
pull prerequisites have produced a committed pin. Missing pin fails locally
before verifier network requests or the Kubernetes credential step. Normal
GitHub source checkout is separate from that verification boundary.

After those prerequisites land, use the declared workflow with the exact
current `main` SHA:

```sh
restore_source=$(git rev-parse origin/main)
gh workflow run restore-talos-synthetic.yml --ref main -f expected_sha="$restore_source"
```

The preparation job runs static/policy checks, validates the committed clean
pin and source ancestry, verifies the cited public publication attempt, pulls
every image blob anonymously, and builds bounded fixture binaries. Only then
can the `validate` job request the existing `homelab-production` reviewer gate.
It repeats those checks before the Kubernetes credential step and checks current
`main` again immediately before creating the Job. Both jobs explicitly combine
the locked development shell with `nixpkgs#skopeo`; no ambient registry tool or
login is assumed. A newer main commit requires a fresh reviewed dispatch.

The pin's source must be an ancestor of current main. `Dockerfile`, launcher,
Nix image derivation, probe, PostgreSQL fixture, `flake.nix` and `flake.lock`
must match that source byte for byte. This deliberately requires republication
after even an unrelated flake change. The pin is the reviewed attestation that
the cited protected publisher output matched the image; public run metadata and
registry bytes do not independently prove approval or publisher provenance.
See [[restore-image-anonymous-pull]] for that trust boundary.

## Fixed execution and placement contract

`scripts/ci/restore-talos/profile.json` commits `zimaboard-1` and the dated
Talos `1.11.3`, kernel `6.12.52-talos`, Kubernetes `1.34.1`, containerd `2.1.4`,
Linux amd64 profile. Changing runtime or placement requires a reviewed code
change. The node must remain Ready, without pressure, taints or a scheduling
cordon, with expected labels and a stable node UID and boot ID.

Before creation and before accepting results, the runner checks at least
`500m` CPU, `512Mi` memory and `3Gi` ephemeral-storage request headroom, plus
`3Gi` available nodefs. Nodefs statistics must be no older than five minutes.
It uses kubectl's allocated-resource projection, including init-container and
Pod-overhead accounting; missing or changed projections fail closed. These
reads reserve no capacity and cannot prevent concurrent usage. The Job requests
`25m` CPU, `128Mi` memory and `128Mi` ephemeral storage, with limits of `500m`,
`512Mi` and `3Gi`; disk-backed scratch is a `2Gi` emptyDir. It uses ordinary
priority zero and `PreemptLowerPriority`, with the default scheduler and fixed
node selector. It does not promise nonpreemption or choose another node.

The local manifest is always the expected baseline, including after admission.
The runner does not trust the returned Job template as a new expected profile.
It rejects extra execution or placement fields, changed controller management,
additional/init/ephemeral containers, service account injection, PVCs, host
namespaces, host/runtime/proxy sockets, environment credentials, sidecars and
an early `nodeName`. Root is read-only; UID/GID/fsGroup are `65534`, capabilities
are dropped, privilege escalation is disabled, and seccomp is `RuntimeDefault`.
Only the immutable fixture ConfigMap and disposable scratch are mounted.
Service-account automounting and service links are disabled.

Committed labels and annotations are checked on the Job, template and Pod,
including after release. The template and Pod must carry the four exact
Job-UID/name-derived controller labels (legacy and `batch.kubernetes.io` keys).
Every nonterminal Pod requires the job-tracking finalizer, including after gate
release. Its controller removal is allowed only once the Pod reaches `Succeeded`
or `Failed`; missing or unknown phase evidence does not relax this check.
Unknown policy labels, annotation prefixes or finalizers fail
acceptance even when the Pod spec is unchanged.
[Pinned Job label generation](https://github.com/kubernetes/kubernetes/blob/93248f9ae092f571eb870b7664c534bfc7d00f03/pkg/registry/batch/job/strategy.go#L223-L265).

One Pod is inspected while gated, with no process-start evidence. The Job
template permanently retains the gate; only the captured Pod UID is released.
Job parallelism/completions are one, backoff is zero, replacement policy is
`Failed`, and restart policy is `Never`. Additional, replaced or deleting Pods
fail the run. The ordinary controller's 1,800-second deadline includes gate
waiting, and terminal Jobs have a one-hour TTL.

UID/resourceVersion/gate JSONPatch tests reject stale release attempts. A
conflict fails the run and triggers cleanup; the runner never drops those tests
or releases a second Pod. Admission runs after patch application and can still
change permitted fields before the next read. **Post-release profile and image
checks detect acceptance mismatch; they cannot prevent execution changed by
trusted admission or control-plane actors.** This is synthetic code without
real data or credentials, not a hostile-control-plane containment claim.
[Pinned patch/admission order](https://github.com/kubernetes/kubernetes/blob/93248f9ae092f571eb870b7664c534bfc7d00f03/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/patch.go#L642-L700).

## Proof and cleanup

The Kubernetes command explicitly invokes `/usr/local/bin/restore-no-network`
before the exact `scripts/ci/restore-talos/run.sh`. The image ENTRYPOINT alone
would be insufficient. The script checks the actual root mount and PID 1
UID/GID, all capability sets, no-new-privileges and at least two seccomp filters.
The unchanged probe exercises forbidden-call `EPERM`, working Unix sockets,
fork/exec inheritance, attempted filter relaxation and alternate-ABI rejection.
A new small helper adds a restriction beneath the existing filter, causing
the unchanged next launcher to fail installation or its Unix self-test before
the command sentinel. The unchanged PostgreSQL fixture performs a real
init/dump/drop/restore and checks SQL/program child inheritance.

Acceptance requires the admitted image and container status `imageID` to equal
the pin's full repository-and-manifest reference exactly. Bare config digests,
aliases, tags, schemes and suffix matches fail closed. The anonymous verifier
independently hashes the published manifest, config and every layer. Pinned
Kubernetes uses CRI `image_ref` for the public imageID; containerd normally
returns a repository digest but can fall back to a raw config digest. Recognizing
that fallback is insufficient proof of the exact requested repository manifest.
[Kubernetes imageID mapping](https://github.com/kubernetes/kubernetes/blob/93248f9ae092f571eb870b7664c534bfc7d00f03/pkg/kubelet/kubelet_pods.go#L2106-L2117),
[containerd image reference](https://github.com/containerd/containerd/blob/75cb2b7193e4e490e9fbdc236c0e811ccaba3376/internal/cri/server/container_status.go#L34-L64).

The receipt contains reviewed source/pin, observed Job/Pod/image/node identities,
runtime/process profile, capacity projection and hashes of the public fixture
bytes. It prints no Pod inventory, workflow data, credentials or raw API logs.
Success also requires verified cleanup. The runner captures a successful create
response's fixed namespace/name/UID before validating content, so rejection can
still remove that exact owned resource. Uncertain create responses reconcile
only the original UUID path and require the full contract before adoption;
they never cause a second create. A lone 404 after an uncertain create does not
prove absence and cannot produce a successful cleanup receipt.

Cleanup uses UID-preconditioned foreground deletion of the owned Job and
ConfigMap, then checks the Job, ConfigMap, owned Pod inventory and captured Pod
name. It does not delete replacements, force Pod deletion or clear finalizers.
The 120-second cleanup wait fails if dependents or uncertainty remain. Deadline,
foreground GC and TTL depend on controllers and are not hard wall-clock cleanup
guarantees during outages or stuck finalizers. Job absence alone never proves
dependent cleanup. Preserve a failed/unverified result and investigate with
read-only inspection; any recovery needs another reviewed repository-owned path.
[Job deadline](https://github.com/kubernetes/kubernetes/blob/93248f9ae092f571eb870b7664c534bfc7d00f03/pkg/controller/job/job_controller.go#L921-L966),
[TTL eligibility](https://github.com/kubernetes/kubernetes/blob/93248f9ae092f571eb870b7664c534bfc7d00f03/pkg/controller/ttlafterfinished/ttlafterfinished_controller.go#L280-L295).

## Credentials and validation boundary

The existing `OCTELIUM_CI_AUTH_TOKEN` is injected only into the protected step
and installed through `scripts/ci/install-kubeconfig.sh`. An inherited
`KUBECONFIG` or existing default config is rejected; the step removes its own
config afterward. No new authorization or scope is granted. This existing
credential may have broader privileges; the script's constrained operations
are not a replacement for upstream authorization.

The actual API minimum includes normal discovery, get namespace/node, list
Pods and events across namespaces for `kubectl describe node`, and read
`nodes/proxy` for kubelet stats. In `octelium-storage` it needs Job/ConfigMap
create/get/delete, Pod get/list/patch and Pod-log get. The node proxy permission
is broader than node metadata read; absent permission fails, never silently
expands RBAC. GitHub metadata uses the workflow's contents-read token; no AWS,
OIDC or registry write permission is requested.

Offline tests cover admission drift, returned-UID cleanup, uncertain creates,
replacement resources, strict image identity, stale capacity and dependency
cleanup. Credential-free native CI additionally executes the exact fixture
script and fault helper inside **each** independently built and tested image
before export, alongside all nine Octelium fixtures. Both attach streams have
an aggregate byte bound and deadline. Docker keeps its established runtime
profile and `128Mi` scratch tmpfs; this establishes generic Linux behavior,
not Talos admission, CRI identity or disk-emptyDir compatibility. No pin is
required for these native tests. Only a later successful protected run can
establish the separate actual-Talos gate, followed by reviewed GitOps activation.
