# Harbor-only image policy

This Argo CD Application registers Kubernetes native admission for Pod regular,
init, and ephemeral containers. An image must start with
`harbor.stinkyboi.com/`; there are no namespace, account, mirror-Pod, or
system-image exceptions.

## Current phase

The binding uses `Warn, Audit`. Public image references are accepted but produce
a `harbor-only-images` warning and audit event. `failurePolicy: Fail` makes CEL
evaluation errors visible through those same actions. This observes future Pod
writes before any replacement Pod is blocked.
Use the separate static and live fleet inventory to establish current public
references before promotion.

Image pulls are node/containerd traffic, not Pod egress. This policy neither
permits registry egress nor proves that Harbor publication, node authentication,
or an application rollout succeeded.

## Promotion

Change the binding to include `Deny` only after the full catalog is published,
private Harbor pulls are accepted on every node, the audit inventory has no
new violations, the separate static and live inventory has no public application
references, and the policy has no type-check warnings. Make that promotion
through this GitOps source; never patch or remove the live binding to recover a
rollout.

## Validation

```sh
nix develop --command kubectl kustomize clusters/homelab/platform/image-policy
nix develop --command python3 -I scripts/ci/image-policy-check.py
```

The second command creates a disposable Kind cluster. It sends server dry-run
Pod requests and creates one unschedulable Harbor Pod for update and ephemeral
subresource cases. It proves the native CEL policy type-checks and that Harbor
references stay clean while public regular, init, ephemeral, update, and
`kube-system` requests warn. It verifies the binding requests `Audit`, but
production audit-sink retention needs separate live acceptance. Workload images
are never pulled. The test then changes only its disposable binding to `Deny`
and proves the same public cases reject; shipped manifests stay `Warn, Audit`.

[Kubernetes ValidatingAdmissionPolicy reference](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/)
