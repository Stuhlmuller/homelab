---
type: overview
title: "Source Map"
description: "Maps wiki topics to canonical guides, operational runbooks, workload READMEs and source ownership."
tags: [knowledge-base, source-map]
sources:
  - id: openwiki-source-e82cbcffb5df1a3ee146efb1
    resource: repo://.cordium/runner-pool.json
  - id: openwiki-source-a793a7dd08d0dc13de84207b
    resource: repo://.github/workflows/cordium-runner-publish.yml
  - id: openwiki-source-a1af3dbae268cb4278427934
    resource: repo://.github/workflows/harbor-native-chainguard-receipt.yml
  - id: openwiki-source-f3c1ec74b74e361ea2192c05
    resource: repo://.github/workflows/mastodon-public-dns.yml
  - id: openwiki-source-23ac5bc03d1cee79a72b06af
    resource: repo://.github/workflows/mastodon-smtp-credential.yml
  - id: openwiki-source-02c6601e3ee1ac6a7a26e042
    resource: repo://.github/workflows/openclaw-enterprise-operations.yml
  - id: openwiki-source-c0ca5e405a32db452e0a5896
    resource: repo://.github/workflows/openclaw-enterprise-startup.yml
  - id: openwiki-source-50e1601d2f23b472521e5c0f
    resource: repo://builds/cordium-runner/README.md
  - id: openwiki-source-efd15335758af38c6e6af9ab
    resource: repo://clusters/homelab/apps/deluge/daemon-status.py
  - id: openwiki-source-9f4d1b63d947cd42e3af68b2
    resource: repo://clusters/homelab/apps/deluge/README.md
  - id: openwiki-source-58caddf8069d72479935ea1e
    resource: repo://clusters/homelab/apps/fleet/FREE-ENTRA.md
  - id: openwiki-source-ffe9c2c54bc78625ce9efd78
    resource: repo://clusters/homelab/apps/mastodon/README.md
  - id: openwiki-source-878d8aa0884abae2a8194701
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/README.md
  - id: openwiki-source-9268fd97f2c4ec8553f9ecb8
    resource: repo://clusters/homelab/apps/openclaw-enterprise/README.md
  - id: openwiki-source-fbaccd01ca51226fa9e5324d
    resource: repo://clusters/homelab/apps/traefik/README.md
  - id: openwiki-source-e26a7307e86732ce7e6a34b6
    resource: repo://clusters/homelab/apps/traefik/routes.yaml
  - id: openwiki-source-ae0b2b6cec91dbc3476c410b
    resource: repo://clusters/homelab/platform/tailnet-dns/README.md
  - id: openwiki-source-b3b14c71f8a81de8a3b71c02
    resource: repo://docs/examples/octelium/homelab-services.yaml
  - id: openwiki-source-b6af8459ba491c30ebdfcbb9
    resource: repo://IaC/mastodon/stack.hcl
  - id: openwiki-source-39e11b90e7410131b2dc0a6e
    resource: repo://IaC/tailnet-dns/stack.hcl
  - id: openwiki-source-f6b60d0a5b2ad5df65f1b2ee
    resource: repo://IaC/terragrunt-catalog/modules/entra-owner-mail/README.md
  - id: openwiki-source-13b48922f1b929b52f4a0233
    resource: repo://IaC/terragrunt-catalog/modules/tailscale-access/README.md
  - id: openwiki-source-a6cfce5073f9b7c35fd3c9dc
    resource: repo://scripts/ci/harbor-native-chainguard-receipt.py
  - id: openwiki-source-4091442a62f62f0adc73ce96
    resource: repo://scripts/ci/openclaw-enterprise-access-test.py
  - id: openwiki-source-18423e8d68f98d1e991a1691
    resource: repo://scripts/ci/openclaw-enterprise-chart-hooks-test.py
  - id: openwiki-source-80b544ebc719878ac3f31bac
    resource: repo://scripts/ci/openclaw-enterprise-foundation-test.py
  - id: openwiki-source-97ce7e27aba2d6e5fa8a5c6f
    resource: repo://scripts/ci/openclaw-enterprise-full-sync-test.py
  - id: openwiki-source-8483d28614308625b1073872
    resource: repo://scripts/ci/openclaw-enterprise-full-sync.sh
  - id: openwiki-source-4c0fec174d4f7cf025f2e7f8
    resource: repo://scripts/ci/openclaw-enterprise-test.py
  - id: openwiki-source-388dfb5b8078e3e9f29dbd62
    resource: repo://scripts/entra-owner-conversion.py
  - id: openwiki-source-45cdc02b9fdef209e9d530d7
    resource: repo://scripts/octelium-entra-oidc.sh
  - id: openwiki-source-e293d5daa2ad090397b8923e
    resource: repo://scripts/openclaw-enterprise-access.py
  - id: openwiki-source-2eea896f325c470e4979019b
    resource: repo://scripts/openclaw-enterprise.py
  - id: openwiki-source-9e73eddbbea62807ee2ea389
    resource: repo://scripts/tailnet-dns-check.py
  - id: openwiki-source-6f8ea3753bc76b21d99fe402
    resource: repo://scripts/tailscale-ci-configure.py
  - id: openwiki-source-81658af78f4007503983579d
    resource: repo://scripts/tailscale-ingress-sign.py
  - id: openwiki-source-c4ba7c9b8c99ef7f9cfb598b
    resource: repo://scripts/tailscale-private-dns.sh
generated: { by: "codex", at: "2026-10-20T06:54:44.714Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-20T06:54:44.714Z
---

# Source Map

This wiki summarizes repository source files; it does not replace them. Use
this map to jump from wiki pages back to canonical files before changing
desired state.

## Top-Level Guidance

| Source | Wiki page | Purpose |
| --- | --- | --- |
| `README.md` | [Homelab Knowledge Base](quickstart.md) | Project overview, repository map, and first-read navigation |
| `AGENTS.md` | [Continuous Improvement](operations/continuous-improvement.md) | Agent workflow, safety boundaries, ownership, ongoing stewardship |
| `ONBOARDING.md` | [Homelab Onboarding](runbooks/homelab-onboarding.md) | Talos and cluster onboarding |

## Runbooks

| Source | Wiki page |
| --- | --- |
| `docs/argocd-bootstrap.md` | [Argo CD Bootstrap](runbooks/argocd-bootstrap.md) |
| `docs/argocd-app-onboarding.md` | [Argo CD App Onboarding](runbooks/argocd-app-onboarding.md) |
| `docs/image-automation.md` | [Image Automation](runbooks/image-automation.md) |
| `docs/ci-cd.md` | [CI/CD](runbooks/ci-cd.md) |
| `builds/cordium-runner/README.md`, `.cordium/runner-pool.json`, and `cordium-runner-*.yml` workflows | [Staged runner workflow](runbooks/ci-cd.md), [identity](architecture/secrets-and-identity.md#dedicated-cordium-ci-assertion), and [validation gates](operations/validation-gates.md#cordium-remote-repository-gate) |
| `clusters/homelab/apps/traefik/README.md` and `routes.yaml` | [Staged mesh ingress and callbacks](runbooks/tailnet-ingress.md) |
| `clusters/homelab/platform/tailnet-dns/README.md`, `values.yaml`, and `IaC/tailnet-dns/stack.hcl` | [Separate tailnet resolver ownership](runbooks/tailnet-ingress.md#cutover-utilities), [topology](architecture/cluster-topology.md#canonical-endpoints) |
| `scripts/tailnet-dns-check.py` and `scripts/ci/tailnet-dns-test.py` | [Direct DNS handoff and declaration checks](operations/validation-gates.md#tailnet-dns-resolver-handoff) |
| `scripts/tailscale-private-dns.sh` | [Guarded later public address retirement](runbooks/tailnet-ingress.md#cutover-utilities) |
| `IaC/terragrunt-catalog/modules/tailscale-access/README.md` and `scripts/config/tailscale-policy.json` | [Tailscale provider and signed CI key ownership](architecture/secrets-and-identity.md#tailscale-provider-foundation) |
| `scripts/tailscale-ingress-sign.py` | [Fixed proxy Tailnet Lock signing](runbooks/tailnet-ingress.md#tailnet-lock) |
| `scripts/tailscale-ci-configure.py` | [Scoped CI signing, interrupted-signature recovery and authority retirement](architecture/secrets-and-identity.md#tailscale-provider-foundation) |
| `clusters/homelab/apps/traefik/CUTOVER.md` | [Ordered DNS, Mac, callback and CI acceptance](runbooks/tailnet-ingress.md#cutover-utilities) |
| `scripts/talos-harbor-mirrors.py` | [Private node registry path](operations/harbor-oci.md#private-node-registry-foundation) |
| `.github/workflows/harbor-native-chainguard-receipt.yml` and `scripts/ci/harbor-native-chainguard-receipt.py` | [Native Chainguard receipt](operations/harbor-oci.md), [validation gates](operations/validation-gates.md#harbor-oci-rollout) |
| `docs/networking-tailnet-ingress.md` | [Tailnet And App Ingress](runbooks/tailnet-ingress.md) |
| `docs/octelium.md` | [Octelium](runbooks/octelium.md) |
| `docs/examples/octelium/homelab-services.yaml`, `scripts/openclaw-enterprise-access.py`, and `scripts/ci/openclaw-enterprise-access-test.py` | [Staged Enterprise console and redirect catalog](runbooks/octelium.md#openclaw-enterprise-access-staging), [private native routes](runbooks/tailnet-ingress.md#route-boundaries) |
| `scripts/octelium-entra-oidc.sh` | [Immutable Entra identity bindings](architecture/secrets-and-identity.md) |
| `IaC/terragrunt-catalog/modules/entra-owner-mail/README.md` | [Retired owner-mail PATCH](architecture/secrets-and-identity.md) |
| `scripts/entra-owner-conversion.py` and `scripts/ci/entra-owner-conversion-test.py` | [Owner conversion boundary](architecture/secrets-and-identity.md#fleet-free-identity-boundaries), [Fleet validation](operations/validation-gates.md#fleet-device-management-rollout) |
| `clusters/homelab/apps/fleet/FREE-ENTRA.md` | [Retired Platform SSO boundary and historical identity evidence](architecture/secrets-and-identity.md#fleet-free-identity-boundaries) |
| `docs/rollback-argocd-apps.md` | [Argo CD App Rollback](runbooks/rollback.md) |
| `docs/runtime-isolation.md` | [Runtime Isolation](runbooks/runtime-isolation.md) |
| `docs/secrets-aws-ssm.md` | [AWS SSM Secret References](runbooks/secrets-aws-ssm.md) |
| `docs/storage-nfs.md` | [NFS Storage](runbooks/storage-nfs.md) |
| `scripts/langfuse-valkey-recovery.py` | [Valkey offline capture](architecture/storage-and-state.md) |
| `clusters/homelab/apps/litellm/native_keys.py` | [Native service-key migration](architecture/ai-observability.md) |
| `docs/talos-control-plane-maintenance.md` | [Talos Control-Plane Maintenance](runbooks/talos-control-plane-maintenance.md) |
| `docs/validation-runbook.md` | [Validation](runbooks/validation.md) |

## App And Platform Notes

| Source | Wiki page |
| --- | --- |
| `clusters/homelab/apps/README.md` | [Application Notes](workloads/application-notes.md) |
| `clusters/homelab/apps/*/README.md` | [Application Notes](workloads/application-notes.md) |
| `clusters/homelab/apps/openclaw-enterprise-foundation/` | [Dormant workload boundary](workloads/inventory.md), [secrets and TLS](architecture/secrets-and-identity.md#dormant-openclaw-enterprise-boundary) |
| `clusters/homelab/apps/openclaw-enterprise/` | [Dormant stock chart candidate](workloads/inventory.md), [chart ownership](patterns/helm-chart-organization.md) |
| `.github/workflows/openclaw-enterprise-startup.yml` and `scripts/openclaw-enterprise-startup.py` | [Protected exact-main startup Secret](runbooks/ci-cd.md), [secret boundary](runbooks/secrets-aws-ssm.md#openclaw-enterprise-model-key) |
| `.github/workflows/openclaw-enterprise-operations.yml`, `scripts/ci/openclaw-enterprise-full-sync.sh`, and `scripts/ci/openclaw-enterprise-full-sync-test.py` | [Protected fixed full sync](runbooks/ci-cd.md), [source and live gates](operations/validation-gates.md#openclaw-enterprise-replacement-gates) |
| `scripts/ci/openclaw-enterprise-chart-hooks-test.py`, `scripts/ci/openclaw-enterprise-startup-test.py`, and `scripts/ci/openclaw-enterprise-quiesce-test.py` | [Dormant chart and lifecycle fixtures](operations/validation-gates.md#openclaw-enterprise-replacement-gates) |
| `scripts/openclaw-enterprise.py`, `scripts/ci/openclaw-enterprise-foundation-test.py`, and `scripts/ci/openclaw-enterprise-test.py` | [Guarded Namespace reconciliation and source gates](operations/validation-gates.md#openclaw-enterprise-replacement-gates) |
| `clusters/homelab/apps/deluge/daemon-status.py` and Deluge `README.md` | [Daemon health incident](operations/deluge-cpu-audit-2026-09-05.md#october-8-daemon-health-failure), [health verification](operations/validation-gates.md#deluge-daemon-health) |
| `clusters/homelab/platform/*/README.md` | [Application Notes](workloads/application-notes.md) |
| `IaC/live/argocd-apps/README.md` | [Argo CD App Onboarding](runbooks/argocd-app-onboarding.md) |

Mastodon source ownership: [workload runbook](../clusters/homelab/apps/mastodon/README.md),
[registration](../IaC/mastodon/stack.hcl),
[secret declarations](../IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl),
[protected SMTP injection](../.github/workflows/mastodon-smtp-credential.yml), and
[public DNS publication](../.github/workflows/mastodon-public-dns.yml).
See the [inventory](workloads/inventory.md),
[credential boundary](architecture/secrets-and-identity.md#mastodon-credential-boundary)
and [activation gates](operations/validation-gates.md#mastodon-activation-gates).
