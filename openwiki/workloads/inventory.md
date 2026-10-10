---
type: workload
title: "Workload Inventory"
description: "Application and platform namespaces, GitOps paths, dependencies, resource and state contracts, and runtime readiness boundaries."
tags: ["workloads", "argocd", "inventory"]
sources:
  - id: openwiki-source-efd15335758af38c6e6af9ab
    resource: repo://clusters/homelab/apps/deluge/daemon-status.py
  - id: openwiki-source-653e94c230cb8a02b742f512
    resource: repo://clusters/homelab/apps/deluge/values.yaml
  - id: openwiki-source-19486243ca5f1efdd808adf2
    resource: repo://clusters/homelab/apps/tailscale/values.yaml
  - id: openwiki-source-cc574ebd8a3bf817cd4a4c4b
    resource: repo://clusters/homelab/apps/traefik/values.yaml
  - id: openwiki-source-da61504fb6ba4ceba279edb0
    resource: repo://IaC/stacks/traefik/stack.hcl
generated: { by: "codex", at: "2026-10-10T18:57:48.826Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-10T18:57:48.826Z
---

# Workload Inventory

<!-- markdownlint-disable MD013 MD060 -->

This inventory summarizes the current application and platform ownership map.
Treat `docs/argocd-app-onboarding.md`, the `clusters/` tree, and Terragrunt
units as the source of truth when they disagree with this note.

Runtime secret contract: declared SSM parameters use AWS-managed `alias/aws/ssm`.
Secret/state recovery copies and encryption ownership are recorded in
[State Encryption](../operations/state-encryption.md).

LiteLLM's UI-key migration prepares a dedicated `litellm-postgres` StatefulSet
inside its existing `ai` Application, with a 20 GiB NFS claim and separate
admin/app SSM credentials. This prerequisite is not live key migration;
database readiness and native-auth cutover remain pending. See
[AI observability](../architecture/ai-observability.md).

## Import Note

The staged migration foundation adds private Traefik ingress and the Tailscale
operator API proxy while retaining existing Octelium/Cloudflare routes until
live cutover passes. The new route inventory keeps Fleet mesh-only, exposes only
n8n and Policy Bot callbacks through Funnel, and retains Octelium for Cordium
and control services. Existing per-app access notes below describe the retained
source path; they are not proof that cutover has happened. See
[the staged ingress runbook](../runbooks/tailnet-ingress.md).

## Platform And Support Applications

Fleet Free adds family device management in namespace `fleet`, registered by
`IaC/live/argocd-apps/fleet` from `clusters/homelab/apps/fleet`. It depends on
SSM, External Secrets, Istio, retained NFS and `octelium-public`. The reviewed
`fleet.stinkyboi.com` native-client route uses Fleet authentication and permanently
blocks public first-admin setup. MySQL, Redis and nightly MySQL backups use
retained NFS; the APNs/provider setup and a real enrolled device remain separate
acceptance gates. See the [Fleet runbook](../../clusters/homelab/apps/fleet/README.md).

Fleet's [Free Entra setup](../../clusters/homelab/apps/fleet/FREE-ENTRA.md)
separates native Microsoft Password Platform SSO from console SAML. Company
Portal supplies the Mac extension; Fleet remains the MDM. A repository operator
script delivers Mac and iPhone/iPad profiles with host-scoped commands. The
desired state retires the global **Family Mac security baseline** assignment;
Fleet Free 4.92.2 sends global Apple profiles to phones as well as Macs, and
[`TargetDeviceType=5` only rejects installation](../../clusters/homelab/apps/fleet/FREE-ENTRA.md#mac-only-baseline-through-individual-installs).
[Label scoping requires Premium](https://fleetdm.com/guides/custom-os-settings#target-hosts-with-labels).
`mac-baseline --host-id` verifies an enrolled Mac and installs the new
`.security-baseline.host` identity. Install and verify it on existing Macs
before `mac-baseline-catalog --remove` deletes the old global entry; distinct
identities prevent delayed catalog removals from erasing the replacement.
The catalog action is removal-only and preserves other entries. New Macs need
explicit installation; the baseline has no automatic assignment or drift repair.
`mac-pilot` uses the new baseline with the existing Entra SSO profile.
`ios-baseline --host-id` targets only one Fleet MDM-connected `ios`/`ipados`
host and validates its Apple device identifier before delivering the stable
iPhone/iPad passcode profile:
non-simple six-character minimum, numeric passcodes allowed, five-minute idle
lock, and immediate reauthentication. It has no global catalog assignment or
automatic drift repair. `ProfileList` confirms delivery; `SecurityInfo` fields
report passcode state but do not prove every setting took effect. A physical
passcode/lock test remains required. [Validation Gates](../operations/validation-gates.md)
owns live evidence.
The console enterprise app permits only an individually assigned, precreated
administrator. No Fleet Premium, Intune enrollment, Conditional Access, or paid
Entra device-compliance integration is enabled. iOS uses MDM inventory/security
evidence; Fleet 4.92.2 SQL policies support macOS/Linux, not iOS.

Fleet's [WireGuard/AirVPN catalog](../../clusters/homelab/apps/fleet/WIREGUARD-AIRVPN.md)
adds official app downloads for Mac and iPhone/iPad, a Mac installation-reporting
policy, and private per-device VPN provisioning. Fleet Free cannot automatically
deploy the apps. Owner-supplied AirVPN exports remain outside git; the operator
delivers each VPN profile through an explicit-device MDM command, avoiding
global distribution of one client key. VPN acceptance awaits the configurations
and device connection tests.

| App                     | Kind                      | Namespace               | GitOps path                                   | Terragrunt path                              | Depends on                                                  |
| ----------------------- | ------------------------- | ----------------------- | --------------------------------------------- | -------------------------------------------- | ----------------------------------------------------------- |
| `traefik` | ingress foundation | `traefik` | `clusters/homelab/apps/traefik` | `IaC/live/argocd-apps/traefik` | cert-manager, istio, tailscale; operator policy before proxy registration |
| `platform-dns`          | support                   | `kube-system`           | `clusters/homelab/platform/dns`               | `IaC/live/argocd-apps/platform-dns`          | Argo CD bootstrap                                           |
| `platform-multus`       | support                   | `kube-system`           | `clusters/homelab/platform/multus`            | `IaC/live/argocd-apps/platform-multus`       | Octelium data-plane prerequisites                           |
| `platform-storage`      | support                   | cluster-scoped          | `clusters/homelab/platform/storage`           | `IaC/live/argocd-apps/platform-storage`      | QNAP NFS export                                             |
| `metrics-server`        | support                   | `kube-system`           | official `metrics-server` Helm chart          | `IaC/live/argocd-apps/metrics-server`        | Kubernetes API and node kubelets                            |
| `platform-crossplane`   | support                   | `crossplane-system`     | `clusters/homelab/platform/crossplane`        | `IaC/live/argocd-apps/platform-crossplane`   | Argo CD bootstrap                                           |
| `octelium-storage`      | support                   | `octelium-storage`      | `clusters/homelab/apps/octelium-storage`      | `IaC/live/argocd-apps/octelium-storage`      | external-secrets, platform-storage                          |
| `harbor`                | private OCI registry      | `harbor`                | `clusters/homelab/apps/harbor`                | `IaC/live/argocd-apps/harbor`                | external-secrets, cert-manager, Istio, storage, Prometheus  |
| `media-postgres`        | support                   | `media`                 | `clusters/homelab/apps/media-postgres`        | `IaC/live/argocd-apps/media-postgres`        | external-secrets, platform-storage for retained NFS backups |
| `n8n-postgres`          | support                   | `automation`            | `clusters/homelab/apps/n8n-postgres`          | `IaC/live/argocd-apps/n8n-postgres`          | external-secrets, platform-storage                          |

`platform-dns` forwards public lookups to the unfiltered Cloudflare resolvers
`1.1.1.1` and `1.0.0.1`. This keeps explicit stable upstreams without
sinkholing Prowlarr indexer domains through Cloudflare Family category filters.
It also rewrites in-cluster `octelium-api.stinkyboi.com` lookups to the
dedicated Istio gateway Service, so Cordium and other cluster clients do not
depend on the router's WAN mapping.
It now declares all six CoreDNS resources and pins the running image content,
with a controlled rolling replacement. The Talos bootstrap handoff remains a
separate, gated step; see [CoreDNS GitOps Ownership](../operations/coredns-gitops-ownership.md).

`platform-crossplane` installs Crossplane core `2.3.3` from the upstream stable
Helm repository with default chart values. It intentionally does not install
providers, ProviderConfigs, Compositions, managed resources, or cloud
credentials yet.

`octelium-storage` keeps its PostgreSQL resource store and Redis AOF state on
retained NFS. A daily CronJob writes a verified 14-day PostgreSQL logical
archive to a separate retained NFS claim. The archive supports logical recovery, but it shares the QNAP failure domain and has not passed a
restore drill. The daily isolated PostgreSQL drill has a repository-owned
candidate excluded from live GitOps and suspended; activation and scheduled
success remain required. Redis still lacks an independent
backup.

`media-postgres` keeps recovery-aware 30-minute startup and runtime liveness
windows plus a 120-second termination grace period, but active data now uses a
retained local volume pinned to `acer`. Readiness and liveness execute a real
SQL query.
The active StatefulSet has no NFS mount. A nightly CronJob writes verified
14-day logical backups to the retained NFS claim; the sibling recovery overlay
fences writers before restore.

`n8n-postgres` recovered one replica after a fenced, completion-marked hook
removed its 2026-08-03 stale lock. The one-shot hook is removed; its explicit
retained claim, 30-minute startup and liveness windows, and 120-second shutdown
grace remain.
AFFiNE, n8n, Dispatcharr, and media PostgreSQL readiness and liveness checks
execute `SELECT 1`; `pg_isready` remains only as the recovery-aware startup
gate.

Istio's API gateway now receives outbound Tunnel traffic: browser gRPC-Web
over HTTPS and native TLS gRPC through a separate TCP carrier. The production
Tunnel workflow owns public DNS.

## Requested Applications

| App                    | Namespace          | GitOps path                                     | Terragrunt path                             | State                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Depends on                                                                                                          |
| ---------------------- | ------------------ | ----------------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `affine`               | `affine`           | `clusters/homelab/apps/affine`                  | `IaC/live/argocd-apps/affine`               | Suspended at zero replicas with PostgreSQL and Redis for memory capacity; PVCs retained; AFFiNE `0.27.0`; PostgreSQL 16 with pgvector, an explicit 20 Gi retained claim, NFS-aware checkpoint/WAL tuning, a 30-minute probe recovery window, and 120-second shutdown grace; the 2026-07-20 fenced stale-lock recovery is complete and its one-shot hook has been removed; ephemeral Redis, with persistence disabled; former AOF claim retained, now unmounted; migration init container with `Recreate` ordering; 50 Gi blob storage; retained config; generated ECDSA signing key; disabled public signup; disabled Copilot/BYOK; and `https://affine.stinkyboi.com` through anonymous Octelium transport with AFFiNE-owned authentication for web and native clients                                                       | external-secrets, cert-manager, istio, octelium, octelium-public, platform-storage                                  |
| `argocd-image-updater` | `argocd`           | `clusters/homelab/apps/argocd-image-updater`    | `IaC/live/argocd-apps/argocd-image-updater` | pinned Helm chart plus repository Kustomize source; replicas remain zero while Harbor publication, credential, promotion, and recovery gates are pending; enrollment is generated from the Harbor automation contract                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | none                                                                                                                |
| `external-secrets`     | `external-secrets` | `clusters/homelab/apps/external-secrets`        | `IaC/live/argocd-apps/external-secrets`     | controller state only                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | platform-dns                                                                                                        |
| `cert-manager`         | `cert-manager`     | `clusters/homelab/apps/cert-manager`            | `IaC/live/argocd-apps/cert-manager`         | cert-manager `v1.20.3`; controller, webhook, CA injector, ACME solver, and startup API check images digest-pinned; controller-managed certificates                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | external-secrets                                                                                                    |
| `istio`                | `istio-system`     | `clusters/homelab/apps/istio`                   | `IaC/live/argocd-apps/istio`                | controller state with homelab-sized `512Mi` Istiod and `256Mi`-per-node ztunnel memory requests; ambient CNI and ztunnel are IPv4-only to match the cluster Pod/Service CIDRs, and the CNI pod template carries an explicit config rollout annotation; also owns the dedicated `octelium-api-ingressgateway` release, SNI-tolerant TLS `Gateway`, and API-only `VirtualService` on NodePort `30443`; the API gateway receives browser HTTPS and native TCP Tunnel traffic                                                                                                                                                                                                                                                                                                                                                     | cert-manager                                                                                                        |
| `tailscale`            | `tailscale`        | `clusters/homelab/apps/tailscale`               | `IaC/live/argocd-apps/tailscale`            | temporary Talos/LAN/egress fallback; operator plus exit-node proxy fixed at `1.102.3`; no persistent application state                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | external-secrets                                                                                                    |
| `octelium-cluster`     | `istio-system`     | `clusters/homelab/apps/octelium-cluster`        | `IaC/live/argocd-apps/octelium-cluster`     | Istio front-proxy route for the self-hosted Octelium Cluster domain, portal, API hostnames, and direct Enterprise console hostname, plus an HTTP/2 upstream `DestinationRule` so Octelium CLI gRPC calls keep response trailers, and a scoped console login-return EnvoyFilter; the Octelium runtime namespace and workloads are installed by `scripts/octelium-cluster-bootstrap.sh` through `octops`, and the wrapper labels that namespace for privileged data-plane pods                                                                                                                                                                                                                                                                                                                                                  | istio, platform-multus, octelium-storage                                                                            |
| `octelium-public`      | `octelium-public`  | `clusters/homelab/apps/octelium-public`         | `IaC/live/argocd-apps/octelium-public`      | stateless Cloudflare Tunnel connector for public Octelium browser control-plane and portal routes, app clientless access, the Enterprise console, and the policy-bound clientless CI Kubernetes hostname `kubernetes-api-ci.stinkyboi.com`; reads `/homelab/octelium/cloudflare-tunnel-credentials-json` and forwards public app hostnames such as `grafana.stinkyboi.com` directly to the Octelium ingress dataplane; browser gRPC-Web uses the HTTPS API Tunnel route; native TLS gRPC uses the separate TCP-over-WebSocket Tunnel carrier                                                                                                                                                                                                                                                                                  | external-secrets, istio, octelium-cluster                                                                           |
| `octelium`             | `octelium-client`  | `clusters/homelab/apps/octelium`                | `IaC/live/argocd-apps/octelium`             | stateless TUN-mode Octelium client bridge pinned to Octelium dataplane nodes; private `kubernetes-api.homelab` Service for operator and restricted read-only Cordium Kubernetes access; public `*.stinkyboi.com` WEB Services with Octelium login except reviewed AFFiNE anonymous transport with application-owned authentication; Podinfo demo; SSM-backed client auth; Entra portal login; cutover gated by `scripts/octelium-e2e-check.sh`                                                                                                                                                                                                                                                                                                                                                                                | external-secrets, istio                                                                                             |
| `octelium-enterprise`  | `octelium`         | `clusters/homelab/apps/octelium-enterprise`     | `IaC/live/argocd-apps/octelium-enterprise`  | Argo CD-owned Kubernetes steady state for Enterprise package `octeliumee` `0.22.0` after `scripts/octelium-enterprise-package.sh` install or upgrade; owns package Deployments, Services, ConfigMaps, ServiceAccounts, and PVC declarations for `octelium-rscstore`, `octelium-logstore`, and `octelium-metricstore`; ignores only controller-normalized generated service-proxy image fields; while both native dataplane nodes are NotReady, also owns 26 bounded emergency Deployments on `acer` for the control paths, CI API, and 18 added public WEB Services (19 with OctoBot); generated Secrets and license material stay outside git                                                                                                                                                                                | octelium-cluster, octelium-storage, platform-storage                                                                |
| `cordium`              | `octelium`         | `clusters/homelab/apps/cordium`                 | `IaC/live/argocd-apps/cordium`              | Cordium `0.12.7`; the parent converges prerequisites, then creates the `cordium-bootstrap` child at Sync wave 1. The child gets a fresh 15-minute operation budget with retries disabled. Its one-use privileged identity is created at PostSync wave -1; genesis is bounded to 12 minutes at wave 0; resourceName-scoped PostSync/SyncFail cleanup deletes that identity. Workspaces use the repo-owned `cordium` namespace, documented privileged Pod Security, disposable `cordium-local` storage on `zimaboard-1`, the Talos user-namespace patch, and a DaemonSet-managed sysctl. Browser access uses `cordium.stinkyboi.com` through the dedicated user; workspace subdomains use `*.cordium.stinkyboi.com`; agent automation uses the separate workload identity and credential-policy-restricted `ManagementService`. | external-secrets, octelium-cluster, octelium-enterprise, platform-storage                                           |
| `prometheus`           | `monitoring`       | `clusters/homelab/apps/prometheus`              | `IaC/live/argocd-apps/prometheus`           | persistent metrics, Alertmanager state, Argo CD scrape config, Alertmanager Discord/OpenClaw notification secrets, hourly unresolved-alert reminders, and explicit recovery revisions for hung operator and kube-state-metrics pods                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | external-secrets, platform-storage                                                                                  |
| `grafana`              | `monitoring`       | `clusters/homelab/apps/grafana`                 | `IaC/live/argocd-apps/grafana`              | persistent config; Homelab, Argo CD, GitHub PR, and aggregate Harbor-CVE security dashboards; platform and workload alerts with hourly reminders; Kubernetes, backup, node, and public GitHub API health monitoring                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | external-secrets, cert-manager, istio, prometheus, platform-storage                                                 |
| `kiali`                | `monitoring`       | `clusters/homelab/apps/kiali`                   | `IaC/live/argocd-apps/kiali`                | controller state only; read-only mesh UI through Octelium; Prometheus readiness gate and Istio PodMonitors supply traffic visibility                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | istio, prometheus, grafana                                                                                          |
| `compass`              | `monitoring`       | `clusters/homelab/apps/compass`                 | `IaC/live/argocd-apps/compass`              | stateless Kubernetes service discovery dashboard with Octelium service-name launch links from the `ghcr.io/adinhodovic/charts` OCI Helm source                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | cert-manager, istio, prometheus                                                                                     |
| `descheduler`          | `kube-system`      | `clusters/homelab/apps/descheduler/values.yaml` | `IaC/live/argocd-apps/descheduler`          | controller state only                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | prometheus                                                                                                          |
| `deluge`               | `media`            | `clusters/homelab/apps/deluge`                  | `IaC/live/argocd-apps/deluge`               | active config on a retained local volume pinned to `zimaboard-0`, with nightly verified NFS archives; shared downloads on QNAP `/media`; SSM-backed WireGuard profile via `deluge-vpn`; guarded recovery for libtorrent session state, the torrent catalog, and already-complete target files; readiness gated by both Gluetun health and the Deluge Web listener on `8112`; direct authenticated RPC for startup, liveness and cached metrics, with 30-minute recovery windows; `127.0.0.1` Web-to-daemon host compatibility for Sonarr; Prometheus health for the Gluetun VPN and Deluge daemon                                                                                                                                                                                                                                                                                 | cert-manager, istio, platform-storage                                                                               |
| `dispatcharr`          | `media`            | `clusters/homelab/apps/dispatcharr`             | `IaC/live/argocd-apps/dispatcharr`          | One app and PostgreSQL replica; both PVCs retained; modular IPTV/EPG manager with ephemeral Redis; IPTV-org USA daily refresh, 1,451 manual channels, Auto Channel Sync off; Sports profile has 65 channels and placeholder XMLTV; NAS-only NodePort 31991 with app pinned to acer; a4d5dc78 Synced/Healthy October 7 UTC; QNAP exports, access restrictions and CBS Sports Golazo (1168) playback through Plex verified; alternate Golazo (889) returns upstream 403; Jellyfin remains deliberately stopped pending operator choice; actual event guide data and other-feed playback unverified; credentials stay outside git                                                                                                                                                                                                | external-secrets, cert-manager, istio, platform-storage                                                             |
| `prowlarr`             | `media`            | `clusters/homelab/apps/prowlarr`                | `IaC/live/argocd-apps/prowlarr`             | persistent config on `nfs-default`; indexer state in local `media-postgres`; single-tag Postgres config normalization; `/initialize.json` readiness and 30-minute NFS-aware startup and liveness windows                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | cert-manager, istio, media-postgres, platform-storage                                                               |
| `bazarr`               | `media`            | `clusters/homelab/apps/bazarr`                  | `IaC/live/argocd-apps/bazarr`               | English subtitles for existing and new Sonarr/Radarr items; retained local SQLite/config on `zimaboard-0`, retained NFS backup claim, and shared `/tv` and `/movies` libraries; human-authenticated Octelium WEB Service at `bazarr.stinkyboi.com`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | platform-storage, radarr, sonarr                                                                                    |
| `radarr`               | `media`            | `clusters/homelab/apps/radarr`                  | `IaC/live/argocd-apps/radarr`               | active config on a retained local volume on `zimaboard-0`; the app pod no longer mounts the old NFS claim, which remains for nightly verified archives and rollback; database state in local `media-postgres`; movies and downloads on QNAP `/media`; live cutover and first backup validated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | cert-manager, istio, deluge, media-postgres, prowlarr, platform-storage                                             |
| `sonarr`               | `media`            | `clusters/homelab/apps/sonarr`                  | `IaC/live/argocd-apps/sonarr`               | active config on a retained local volume on `zimaboard-0`; the app's Pod no longer mounts the old NFS claim, which remains for nightly verified archives and rollback; database state in local `media-postgres`; TV and downloads on QNAP `/media`; live cutover and first backup validated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | cert-manager, istio, deluge, media-postgres, prowlarr, platform-storage                                             |
| `litellm`              | `ai`               | `clusters/homelab/apps/litellm`                 | `IaC/live/argocd-apps/litellm`              | internal OpenAI-compatible gateway exposing only `openrouter/free`; the existing SSM `openai-api-key` is mounted only as its OpenRouter upstream credential, while OpenClaw, Multica, NOFX and n8n receive dedicated caller keys; guarded pre-auth admission exports trusted attribution to Langfuse                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | external-secrets, cert-manager, istio, platform-storage                                                             |
| `langfuse`             | `langfuse`         | `clusters/homelab/apps/langfuse`                | `IaC/live/argocd-apps/langfuse`             | operator UI for LiteLLM's trusted caller-attributed traces. Octelium-protected UI: `https://langfuse.stinkyboi.com`. Retained NFS PVCs: PostgreSQL `20Gi`, Valkey `8Gi`, ClickHouse `100Gi`; S3 raw events retain 30 days. No database operator/automatic logical backup; restore unverified.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | aws-ssm-parameters, external-secrets, cert-manager, istio, platform-storage, langfuse-blob-storage; Octelium for UI |
| `multica`              | `ai`               | `clusters/homelab/apps/multica`                 | `IaC/live/argocd-apps/multica`              | Multica `v0.4.29` self-host chart with frontend, backend API/WebSocket server, dedicated pgvector PostgreSQL, generated JWT, database, and private fixed sign-in code secrets; development-mode authentication behind Octelium without email delivery; Postgres and uploads PVCs on `nfs-default`; UI at `https://multica.stinkyboi.com`; persistent OpenCode daemon on acer uses LiteLLM with its dedicated caller key, max one task.                                                                                                                                                                                                                                                                                                                                                                                        | external-secrets, cert-manager, istio, platform-storage                                                             |
| `openclaw`             | `ai`               | `clusters/homelab/apps/openclaw`                | `IaC/live/argocd-apps/openclaw`             | NAS configuration/workspace; retained node-local SQLite state on zimaboard-1; daily verified NAS database snapshots; `6Gi` ephemeral cap; exact-image-version external Discord npm package with no floating fallback; a dedicated LiteLLM caller key and OpenAI-compatible internal endpoint provide `openrouter/free`; Kubernetes-only containment with sandboxing off until a supported Docker, SSH, or OpenShell backend exists; explicit agent resources; HTTP proxy probes; pinned to `zimaboard-1` for persistent local runtime state                                                                                                                                                                                                                                                                                   | external-secrets, cert-manager, istio, litellm, platform-storage                                                    |
| `n8n`                  | `automation`       | `clusters/homelab/apps/n8n`                     | `IaC/live/argocd-apps/n8n`                  | persistent workflows, credential metadata, users, and execution history in n8n-postgres; instance settings and file-backed runtime data on PVC; SSM key bootstraps fresh PVCs only; a dedicated LiteLLM token supplies an internal OpenAI credential override without serializing it in workflows; public callbacks use `https://n8n-webhook.stinkyboi.com` through `octelium-public` and are limited to webhook prefixes; authenticated self-API calls use the plain-HTTP in-cluster Service and are limited to the n8n workload identity; database-aware readiness and liveness recycle n8n when a PostgreSQL interruption leaves its connection pool stale; restricted runtime uses app UID/GID 1000, init UID/GID 65534, RuntimeDefault seccomp, no escalation or capabilities                                            | external-secrets, cert-manager, istio, platform-storage, n8n-postgres, litellm                                      |
| `nofx`                 | `nofx`             | `clusters/homelab/apps/nofx`                    | `IaC/live/argocd-apps/nofx`                 | trading app at `https://nofx.stinkyboi.com` via Octelium `homelab-human-web-access` plus a second NOFX-owned login; backend SQLite data, backtest runs, and logs on the retained `nofx-data` NFS claim; absolute binary runs from `/app/data` so relative writes preserve the read-only image root; private maintained derivative in `builds/nofx` with published, signed OKX US cash-spot images and per-agent ledger ownership (runtime acceptance pending), declared by digest from Harbor with `harbor-pull` references; rollout requires authenticated pulls, fresh Secret readiness, stopped traders, and inactive simulations; allocations require explicit operator amounts; generated JWT, data-encryption, and RSA transport-encryption keys from `/homelab/nofx/*` SSM parameters                                  | external-secrets, harbor, istio, octelium, octelium-public, platform-storage, litellm (after gateway image rollout) |
| `policy-bot`           | `automation`       | `clusters/homelab/apps/policy-bot`              | `IaC/live/argocd-apps/policy-bot`           | stateless GitHub App policy evaluator; one replica after SSM placeholders are replaced; GitHub webhooks use `https://policy-bot-hook.stinkyboi.com/api/github/hook` through `octelium-public`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | external-secrets, cert-manager, istio                                                                               |
| `octobot`              | `finance`          | `clusters/homelab/apps/octobot`                 | `IaC/live/argocd-apps/octobot`              | UI-configured bot state, exchange credentials, logs, and Octelium-targeted UI access; a version-marked init container reconciles the pinned OctoBot 2.1.1 tentacle bundle without editing user configuration                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | cert-manager, istio, platform-storage                                                                               |

LiteLLM's native-key cutover uses its dedicated PostgreSQL database, imports the
four existing service keys once, and removes the custom-auth bypass. UI listing,
revocation and each caller's fresh Langfuse generation remain rollout gates;
see [AI observability](../architecture/ai-observability.md).

Langfuse web allows ten minutes for database migrations before liveness checks
begin and reserves/caps memory at `2Gi`; worker and CPU budgets are unchanged.
Web, worker and Valkey temporarily declare zero replicas for the October 10
offline AOF capture. A credential-free inspector mounts only the queue PVC,
read-only; restoring service requires a reviewed follow-up. The separate 1Gi
`langfuse-migration-recovery` NFS claim preserves private recovery artifacts.
Pod readiness does not establish UI or telemetry acceptance; see
[AI observability](../architecture/ai-observability.md).

Multica PostgreSQL uses SQL-query readiness, 30-minute recovery windows, and
120-second shutdown grace on its retained NFS PVC. This is a probe hardening
change; storage migration and restore verification remain separate work.

OpenClaw's managed `gh` and Git HTTPS helper renew homelab-scoped GitHub App
tokens from the existing mounted key, using temporary private CLI config files.
OpenClaw also mounts a repository-managed assistant bundle using OpenRouter's
`openrouter/free` router: owner Discord
briefings, daytime health checks, bounded daily improvements, and preserved
personal memory. Interactive turns allow one hour; heartbeats and managed
jobs keep their separate shorter budgets. Its personal-assistant extension installs the pinned Google
CLI and enables the Calendar skill, with scoped Marketplace outreach and private
task/deal tracking. Google OAuth and a private Facebook browser/login remain
unconfigured; see [OpenClaw personal assistant](../operations/openclaw-personal-assistant.md).
Monitoring depends on Grafana: the OpenClaw mesh identity
can reach the internal Grafana service, where its dedicated login authorizes
datasource queries. No default Kubernetes context is provided.
See [OpenClaw](application-notes.md#openclaw).

Deluge's disabled Gluetun profiling contract uses a chart-owned ConfigMap and
two read-only files, with a loopback address and private bounded capture helper.
Activation requires renewed high CPU and a successful latest config backup.
It introduces no persistent data or external service. See
[Deluge CPU Audit — 2026-09-05](../operations/deluge-cpu-audit-2026-09-05.md) for the open diagnosis, live verification,
and required disable rollout.

## GitOps Project Boundary

Dispatcharr, OpenClaw, Policy Bot, and Prowlarr use the namespace-limited
`homelab-workloads` AppProject. Their rendered sources need no cluster-scoped
resources. Other applications remain in `homelab` because they own or manage a
namespace, need other cluster-scoped resources, or belong to a later bounded
migration. `n8n-postgres` stays there while its managed namespace metadata
reconciles the cluster-scoped `automation` Namespace.

## Worker Resource Contracts

- Prometheus, Grafana, Prometheus Operator, kube-state-metrics, and config
  reloaders declare memory requests from the retained September 2026 usage
  sample. See [Monitoring Resource Requests](../operations/monitoring-resource-requests.md) for sizing,
  scheduling headroom, and the remaining failover-capacity deficit.
- OpenClaw requests `1` CPU and `2Gi` memory for the app and caps it at
  `1500m` and `4Gi`; its init containers have matching CPU limits, and required
  affinity keeps the workload off Octelium dataplane nodes.
- Deluge, its Gluetun and helper sidecars, Prowlarr, Radarr, and Sonarr all have
  explicit CPU and memory requests and limits derived from the 2026-08-26
  seven-day Prometheus sample. Deluge port reconciliation is low-frequency and
  its metrics endpoint serves a one-minute cache instead of spawning console
  commands per scrape.
- Keep the measured values and the post-rollout remeasurement rule in
  [Zimaboard-0 Resource Envelope](application-notes.md#zimaboard-0-resource-envelope).

## Mesh Policy Summary

Istio ambient is committed for the `affine`, `ai`, `automation`, and `monitoring`
namespaces. The source of truth is `docs/runtime-isolation.md` plus the
`authorizationpolicy.yaml` files in the affected app overlays.

- `affine` uses namespace default-deny, gateway-only server access, and
  service-account-only database/cache access.
- `ai` uses a namespace default-deny policy and explicit inbound allows for the
  Istio gateway path used by Octelium service proxies to LiteLLM, Multica, and
  OpenClaw, the Octelium connector principal reserved for future served
  upstreams, Alertmanager to reach OpenClaw `/hooks/agent`, and OpenClaw to
  reach LiteLLM.
- `automation` currently restricts `n8n` workload access to the Istio gateway,
  the Octelium client bridge, and n8n's own service account for authenticated
  self-API calls; the reviewed public n8n and Policy Bot callback hosts forward
  through the `octelium-public` tunnel into that gateway instead of directly
  to the workloads. `n8n-postgres` has a NetworkPolicy that documents n8n-only
  database access, but the current flannel CNI does not enforce NetworkPolicy
  yet. The namespace is not default-denied because callback traffic and
  database source-identity validation still need live validation after rollout.
- `monitoring` restricts Grafana, Prometheus, Alertmanager, and
  kube-state-metrics by service account. Compass allows only the Istio gateway
  path used by Octelium service proxies, Prometheus scraper, and Octelium
  connector. Compass also owns
  discovery-only `Ingress` resources with an inert `compass-discovery` class;
  those resources intentionally ignore Argo CD health checks because no
  controller populates their load balancer status. The Prometheus operator
  remains unselected until its webhook/control-plane paths are modeled.
- The `octelium-client` pod template is explicitly ambient-enrolled so future
  connector-served upstreams have a stable workload principal when they call
  protected `ai`, `automation`, and `monitoring` services. The e2e gate requires
  each active connector pod to report
  `ambient.istio.io/redirection=enabled`.
- `media` stays out of ambient while Deluge Gluetun/WireGuard and the media app
  ingress model need a repo-owned waypoint or equivalent policy design.

The Traefik foundation adds `cluster.local/ns/traefik/sa/traefik` to the
application ingress allows above. Its namespace joins ambient; the private TLS,
callback and registry listeners remain separate. NetworkPolicy entries declare
intended peers but Flannel does not enforce them. No application PVC, database
or enrollment identity changes as part of this ingress foundation. The Tailscale
operator's authenticated API proxy and scoped CI RBAC are prepared before
workflow transport changes; see [identity ownership](../architecture/secrets-and-identity.md#tailscale-provider-foundation).

## Update Checklist

When a workload changes, update this note for:

- Namespace or path moves.
- New or removed dependencies.
- New ingress host or exposure type.
- New ExternalSecret or SSM parameter contract.
- Persistent storage, backup, restore, or rollback behavior changes.

OpenClaw keeps its UID-private identity coordinator on a shared Pod-local
16 MiB volume because the NAS reports anonymous ownership. Persistent identity,
configuration, sessions, and backups remain on NFS. Its single-replica
`Recreate` strategy and same-Pod writer restriction are required; see
[Storage And State](../architecture/storage-and-state.md).

### Cordium CI execution contract

The optional `cordium-check.yml` workflow uses a dedicated OIDC workload user
and `.cordium/workspace.yaml` to execute repository checks remotely. Workspace
data is disposable node-local state. Cluster limits allow four stored and one
active workspace per user, including interactive users. Live execution and
negative-policy acceptance remain pending; see [Cordium CI](../../docs/cordium-ci.md).

### OpenClaw runtime readiness

Bootstrap verifies the current offline backup, existing SQLite databases and
direct local mounts before configuration. Missing databases require a verified
restore. See [OpenClaw Runtime State](../operations/openclaw-runtime-state.md).

## Private OCI Packages

Harbor owns private `homelab` custom images and the public upstream-only
`mirror` project. Its in-cluster vulnerability collector exports aggregate
completed-scan critical-CVE counts per project for Grafana; it is read-only,
uses the existing file-mounted Harbor administrator credential, and emits no
artifact, digest, or CVE labels. The [Talos mirror rollout](../../docs/harbor-image-mirroring.md)
covers Helm/operator-generated workloads and system images; publication must
precede node cutover or new consumer versions.
New builds use a local signing Job and the cert-manager-owned
`harbor-image-signing` Secret; see the rollout status below.
Its database uses retained local storage on `acer`; registry blobs and logical
backups use retained NFS. See [Harbor Private OCI Registry](../operations/harbor-oci.md) for secret,
networking, publication and acceptance boundaries. Live readiness remains subject
to the evidence recorded there.

## Recovery inventory (HOME-2)

[Application recovery](../../docs/application-recovery.md) records per-workload durable
data, proposed loss/time budgets and remaining capture/secret gaps. Publication
adapters cover complete Octelium/media logical sets and fenced AFFiNE/Multica
DB/blob bundles, but only the existing Octelium/media jobs currently declare
automatic capture. Candidate off-NAS publication and checks are not active.
No new recovery coverage is claimed for runtime OAuth/PAT state, Langfuse, Harbor,
n8n, NOFX or monitoring. Acceptance requires independent retrieval and isolated
application behavior, not only a checksum or successful backup Job.
