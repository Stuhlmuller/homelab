# Held private core pull configuration

This candidate directory is excluded from the active Harbor Kustomization.
It declares no consuming image digest and is not an Argo source. The active
Harbor Kustomization owns the namespace-local `harbor-pull` ExternalSecret.

The active pull Secret uses only the existing `/homelab/harbor/robot-pull-password`
parameter and the read-only `robot$homelab+pull` identity. The parameter
declaration, exact-ARN reader grant and `aws-ssm` namespace allowlist already
cover Harbor; no producer/IAM change or credential rotation is included. This
held ServiceAccount overlay preserves automount refusal and exposes the credential
only to kubelet image pulls. It grants no application-container registry access.

After reviewed image publication/signing, complete private pulls, full-container
scan/advisory acceptance and recovery clearance, add the pull reference to the
existing ServiceAccount in the reviewed consumer change. Do not add a second
ServiceAccount object.
Require ExternalSecret Ready and target metadata before a private-image rollout.
The `OnChange` contract needs a repository revision annotation advance after
credential rotation; refresh both Harbor's existing bootstrap Secret and this
pull Secret through their declared annotations. Never print Secret data.

Preserve the current `Recreate` strategy's planned downtime and an upstream
cold-bootstrap/backup-backed recovery path: a stopped in-cluster registry cannot
supply its own cold image.
Rollback uses retained digests and declared GitOps configuration. Do not activate
this directory independently or change live pull credentials manually.
