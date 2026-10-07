# Files

- [Argo CD App Onboarding](argocd-app-onboarding.md) - Application registration through shared Terragrunt inputs, repository source ownership, and ordering versus runtime readiness.
- [Argo CD Bootstrap](argocd-bootstrap.md) - Argo CD bootstrap, transfer to GitOps self-management, single-apply setup, and repository-owned emergency recovery.
- [CI/CD](ci-cd.md) - Trusted Terragrunt plan and exact-SHA apply workflows, Policy Bot merge rules, environment approvals, and credential recovery.
- [Homelab Onboarding](homelab-onboarding.md) - Canonical Talos control-plane, Kubernetes API, and QNAP endpoints with links to cluster onboarding and maintenance.
- [Image Automation](image-automation.md) - Renovate image updates, mandatory digest pins, and reviewed Helm, Kustomize, and Kubernetes image changes.
- [Octelium](octelium.md) - Octelium access ownership, browser gRPC-Web versus native TLS transport, macOS API carrier, and reconnect failure evidence.
- [Runbooks Index](overview.md) - Task routes through Talos onboarding, Argo CD, storage, secrets, Octelium access, validation, rollback, and recovery runbooks.
- [Argo CD App Rollback](rollback.md) - Repository-owned Argo CD rollback and the separate backup and restore decision required for persistent application data.
- [Runtime Isolation](runtime-isolation.md) - Pod Security, service accounts, Istio authorization, workload security contexts, and unenforced NetworkPolicy limits on flannel.
- [AWS SSM Secret References](secrets-aws-ssm.md) - SSM and ExternalSecret contracts plus coordinated Multica PostgreSQL password rotation on an initialized persistent volume.
- [NFS Storage](storage-nfs.md) - QNAP NFS exports, default StorageClass and media volumes, with provisioning, persistence, backup, and restore validation.
- [Tailnet And App Ingress](tailnet-ingress.md) - Octelium primary access, Istio ClusterIP ingress, temporary Tailscale fallback, and explicit path-limited public callbacks.
- [Talos Control-Plane Maintenance](talos-control-plane-maintenance.md) - Authenticated Talos maintenance, etcd snapshot integrity, macOS backup scheduling, retention, offsite publication, and recovery limits.
- [Validation](validation.md) - Canonical validation runbook and focused Terragrunt, Kubernetes render, policy, secret-scan, and live readiness checks.
