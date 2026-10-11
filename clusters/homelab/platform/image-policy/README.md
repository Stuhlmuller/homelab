# Harbor-only Pod images

This platform Application uses Kubernetes native admission to reject public
image references in regular, init and ephemeral/debug containers. It requires
no webhook workload, registry credential, Service, PVC or additional ingress.
`failurePolicy: Fail` and the `Deny, Audit` binding fail closed on evaluation errors.

The `homelab` AppProject already permits the two cluster-scoped admission kinds.
Registration depends on Harbor; this is ordering, not publication or readiness
acceptance. Keep this change draft until all application and generated images
use Harbor, complete publication/anonymous pulls succeed, and private node pulls
have live acceptance. Enabling it beforehand can stop replacement Pods.

## Talos system exceptions

Kubelet-created mirror Pods are accepted only in `kube-system`, with the
`system:nodes` group, a username matching the Pod's assigned node and a mirror
annotation. An ordinary user cannot bypass the rule by copying the annotation.

Talos-owned Flannel and kube-proxy keep their supported upstream names. Only
`kube-system` Pods using the exact `flannel`/`kube-proxy` service account and
corresponding committed image version are allowed. Their bytes must come through
verified fail-closed node mirrors. There is no namespace-wide exemption, and
these exceptions do not allow public debug containers. Review versions with
Talos/Kubernetes upgrades. Remaining controllers require explicit Harbor refs.

## Verification and recovery

```sh
nix develop --command kubectl kustomize clusters/homelab/platform/image-policy
nix develop --command python3 -I scripts/ci/image-policy-check.py
```

The second command needs Docker. It creates a disposable Kubernetes 1.34 Kind
cluster with a private temporary kubeconfig, verifies native type checking,
and tests accepted/rejected image references, init/debug containers, hostname
lookalikes, system account boundaries and mirror annotation spoofing. Test Pods
never pull images: they use an absent node and `imagePullPolicy: Never`; admission
requests use server dry runs. No homelab credentials or production context are used.

After protected delivery, require Argo Synced/Healthy and no
`status.typeChecking.expressionWarnings`. Run equivalent server dry-run Pod
cases against the actual cluster and require rejection to name
`harbor-only-images`; another admission failure is not proof of this policy.

For reviewed cold bootstrap or registry recovery, temporarily change
`binding.yaml` to `validationActions: [Audit]` in the same source change as the
upstream recovery image profiles. Apply through the declared GitOps path;
restore `Deny, Audit` after private image transport is verified. Never patch or
remove the live binding to repair a failed rollout. This policy prevents public
references; Istio egress and node registry controls remain separate requirements.

[Kubernetes admission reference](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/)
