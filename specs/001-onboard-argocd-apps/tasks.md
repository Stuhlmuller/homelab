# Tasks: Argo CD Application Onboarding

**Input**: Design documents from `/specs/001-onboard-argocd-apps/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/argocd-app-onboarding.md, quickstart.md

**Tests**: No test-first tasks were requested. Validation tasks for Terragrunt/OpenTofu, GitOps rendering, Kubernetes dry runs, secret scanning, Argo CD expectations, and operational documentation are included.

**Organization**: Tasks are grouped by user story so platform add-ons, homelab services, and operations guidance can be implemented and reviewed as independent increments after the shared foundation is complete.

## Phase 1: Setup (Shared Structure)

**Purpose**: Create the repository surfaces that all later Argo CD, Terragrunt, app, and operations tasks will use.

- [X] T001 Create the Argo CD app registration root README with catalog-module conventions in `IaC/live/argocd-apps/README.md`
- [X] T002 Create the GitOps app source root README with per-app file conventions in `clusters/homelab/apps/README.md`
- [X] T003 [P] Create the onboarding inventory and dependency overview document in `docs/argocd-app-onboarding.md`
- [X] T004 [P] Create the tailnet ingress, no-Funnel, and no-DNS-churn design document in `docs/networking-tailnet-ingress.md`
- [X] T005 [P] Create the AWS SSM Parameter Store and External Secrets reference document in `docs/secrets-aws-ssm.md`
- [X] T006 [P] Create the pre-rollout and post-rollout validation runbook in `docs/validation-runbook.md`
- [X] T007 [P] Create the dependency-aware rollback runbook in `docs/rollback-argocd-apps.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish storage, secret, ingress, and dependency foundations that must exist before any user story app work rolls forward.

**Critical**: No user story work should be considered rollout-ready until this phase is complete.

- [X] T008 Record read-only NFS provisioner inspection commands, observed public-safe provisioner name, and redaction decisions in `docs/storage-nfs.md`
- [X] T009 Create the default NFS-backed StorageClass manifest using only public-safe provisioner details in `clusters/homelab/platform/storage/default-nfs-storageclass.yaml`
- [X] T010 Create the storage Kustomize entry for the default StorageClass in `clusters/homelab/platform/storage/kustomization.yaml`
- [X] T011 Create the platform storage README documenting ownership boundaries and the non-owned NFS provisioner prerequisite in `clusters/homelab/platform/storage/README.md`
- [X] T012 Create the supporting Argo CD registration for platform storage with the Terragrunt catalog module in `IaC/live/argocd-apps/platform-storage/terragrunt.hcl`
- [X] T013 Document NFS backup coverage, restore expectations, and the stateful rollout gate in `docs/storage-nfs.md`
- [X] T014 Update shared app source conventions for values, ExternalSecrets, Istio routes, and kustomizations in `clusters/homelab/apps/README.md`
- [X] T015 [P] Add the AWS SSM ExternalSecret naming matrix and non-secret placeholder rules in `docs/secrets-aws-ssm.md`
- [X] T016 [P] Add the complete Terragrunt dependency matrix, including `platform-storage`, in `docs/argocd-app-onboarding.md`
- [X] T017 [P] Add the baseline Istio plus Tailscale routing policy with zero first-rollout Funnel paths in `docs/networking-tailnet-ingress.md`
- [X] T018 [P] Add the Argo CD bootstrap prerequisite and validation checkpoint list in `docs/validation-runbook.md`

**Checkpoint**: Storage, secret, ingress, and dependency foundations are documented and ready for app-specific desired state.

---

## Phase 3: User Story 1 - Register Platform Add-Ons Through GitOps (Priority: P1) MVP

**Goal**: Register external-secrets, cert-manager, Istio, Tailscale, Prometheus, Grafana, and descheduler as Argo CD managed applications with explicit Terragrunt dependencies.

**Independent Test**: Review only the Phase 3 files and confirm the seven platform add-ons have Argo CD registrations, owning GitOps paths, explicit dependency edges, tailnet/no-Funnel behavior where applicable, and documented storage or stateless profiles.

### Implementation for User Story 1

- [X] T019 [P] [US1] Create External Secrets Helm values with AWS SSM backend assumptions in `clusters/homelab/apps/external-secrets/values.yaml`
- [X] T020 [P] [US1] Create the AWS SSM ClusterSecretStore or placeholder backend manifest in `clusters/homelab/apps/external-secrets/cluster-secret-store.yaml`
- [X] T021 [US1] Create the external-secrets Argo CD Terragrunt unit with no app-level dependencies beyond bootstrap in `IaC/live/argocd-apps/external-secrets/terragrunt.hcl`
- [X] T022 [P] [US1] Create cert-manager Helm values in `clusters/homelab/apps/cert-manager/values.yaml`
- [X] T023 [P] [US1] Create cert-manager issuer placeholders or issuer reference notes in `clusters/homelab/apps/cert-manager/issuer.yaml`
- [X] T024 [US1] Create the cert-manager Argo CD Terragrunt unit depending on external-secrets in `IaC/live/argocd-apps/cert-manager/terragrunt.hcl`
- [X] T025 [P] [US1] Create Istio Helm values for reverse-proxy ownership in `clusters/homelab/apps/istio/values.yaml`
- [X] T026 [P] [US1] Create the Istio tailnet gateway manifest with no public Funnel exposure in `clusters/homelab/apps/istio/tailnet-gateway.yaml`
- [X] T027 [US1] Create the Istio Argo CD Terragrunt unit depending on cert-manager in `IaC/live/argocd-apps/istio/terragrunt.hcl`
- [X] T028 [P] [US1] Create Tailscale operator or connector values in `clusters/homelab/apps/tailscale/values.yaml`
- [X] T029 [P] [US1] Create the Tailscale ExternalSecret reference manifest with AWS SSM parameter names only in `clusters/homelab/apps/tailscale/externalsecret.yaml`
- [X] T030 [US1] Create the Tailscale Argo CD Terragrunt unit depending on external-secrets and Istio in `IaC/live/argocd-apps/tailscale/terragrunt.hcl`
- [X] T031 [P] [US1] Create Prometheus Helm values with default NFS StorageClass persistence in `clusters/homelab/apps/prometheus/values.yaml`
- [X] T032 [P] [US1] Create Prometheus storage, backup, restore, and rollback notes in `clusters/homelab/apps/prometheus/README.md`
- [X] T033 [US1] Create the Prometheus Argo CD Terragrunt unit depending on external-secrets and platform-storage in `IaC/live/argocd-apps/prometheus/terragrunt.hcl`
- [X] T034 [P] [US1] Create Grafana Helm values with Prometheus datasource and default NFS StorageClass persistence in `clusters/homelab/apps/grafana/values.yaml`
- [X] T035 [P] [US1] Create Grafana ExternalSecret references for admin and auth values in `clusters/homelab/apps/grafana/externalsecret.yaml`
- [X] T036 [P] [US1] Create the Grafana tailnet-only Istio route with Funnel disabled in `clusters/homelab/apps/grafana/virtualservice.yaml`
- [X] T037 [US1] Create the Grafana Argo CD Terragrunt unit depending on external-secrets, cert-manager, Istio, Tailscale, Prometheus, and platform-storage in `IaC/live/argocd-apps/grafana/terragrunt.hcl`
- [X] T038 [P] [US1] Create conservative descheduler values and policy settings in `clusters/homelab/apps/descheduler/values.yaml`
- [X] T039 [P] [US1] Create descheduler safety notes for critical, storage-sensitive, and single-replica workloads in `clusters/homelab/apps/descheduler/README.md`
- [X] T040 [US1] Create the descheduler Argo CD Terragrunt unit depending on Prometheus in `IaC/live/argocd-apps/descheduler/terragrunt.hcl`
- [X] T041 [US1] Add platform app ownership, dependency, secret, storage, and ingress entries in `docs/argocd-app-onboarding.md`
- [X] T042 [US1] Add platform app render, plan, sync, and health validation steps in `docs/validation-runbook.md`
- [X] T043 [US1] Add platform app rollback notes and dependency order in `docs/rollback-argocd-apps.md`

**Checkpoint**: User Story 1 is independently reviewable as the MVP platform foundation.

---

## Phase 4: User Story 2 - Register Homelab Services Consistently (Priority: P2)

**Goal**: Register Deluge, Prowlarr, Radarr, Sonarr, LiteLLM, OpenClaw, and Tines using the same Argo CD and Terragrunt catalog pattern, with safe secret references, default NFS storage, and tailnet-only routes.

**Independent Test**: Review only the Phase 4 files after Phase 2 and confirm the seven service apps have stable identities, non-secret configuration, explicit dependencies, stateful workload profiles, and no public Tailscale Funnel paths.

### Implementation for User Story 2

- [X] T044 [P] [US2] Create Deluge Helm values with default NFS StorageClass persistence for config and downloads in `clusters/homelab/apps/deluge/values.yaml`
- [X] T045 [P] [US2] Create Deluge ExternalSecret references for auth and integration values in `clusters/homelab/apps/deluge/externalsecret.yaml`
- [X] T046 [P] [US2] Create the Deluge tailnet-only Istio route with Funnel disabled in `clusters/homelab/apps/deluge/virtualservice.yaml`
- [X] T047 [US2] Create the Deluge Argo CD Terragrunt unit depending on external-secrets, cert-manager, Istio, Tailscale, and platform-storage in `IaC/live/argocd-apps/deluge/terragrunt.hcl`
- [X] T048 [P] [US2] Create Radarr Helm values with default NFS StorageClass persistence and Deluge integration placeholders in `clusters/homelab/apps/radarr/values.yaml`
- [X] T049 [P] [US2] Create Radarr ExternalSecret references for app and download-client credentials in `clusters/homelab/apps/radarr/externalsecret.yaml`
- [X] T050 [P] [US2] Create the Radarr tailnet-only Istio route with Funnel disabled in `clusters/homelab/apps/radarr/virtualservice.yaml`
- [X] T051 [US2] Create the Radarr Argo CD Terragrunt unit depending on cert-manager, Istio, Tailscale, Deluge, Prowlarr, and platform-storage in `IaC/live/argocd-apps/radarr/terragrunt.hcl`
- [X] T052 [P] [US2] Create Sonarr Helm values with default NFS StorageClass persistence and Deluge integration placeholders in `clusters/homelab/apps/sonarr/values.yaml`
- [X] T053 [P] [US2] Create Sonarr ExternalSecret references for app and download-client credentials in `clusters/homelab/apps/sonarr/externalsecret.yaml`
- [X] T054 [P] [US2] Create the Sonarr tailnet-only Istio route with Funnel disabled in `clusters/homelab/apps/sonarr/virtualservice.yaml`
- [X] T055 [US2] Create the Sonarr Argo CD Terragrunt unit depending on cert-manager, Istio, Tailscale, Deluge, Prowlarr, and platform-storage in `IaC/live/argocd-apps/sonarr/terragrunt.hcl`
- [X] T056 [P] [US2] Create LiteLLM Helm values with AWS SSM provider placeholders and default NFS StorageClass persistence when state is enabled in `clusters/homelab/apps/litellm/values.yaml`
- [X] T057 [P] [US2] Create LiteLLM ExternalSecret references for model provider keys and routing secrets in `clusters/homelab/apps/litellm/externalsecret.yaml`
- [X] T058 [P] [US2] Create the LiteLLM tailnet-only Istio route with Funnel disabled in `clusters/homelab/apps/litellm/virtualservice.yaml`
- [X] T059 [US2] Create the LiteLLM Argo CD Terragrunt unit depending on external-secrets, cert-manager, Istio, Tailscale, and platform-storage in `IaC/live/argocd-apps/litellm/terragrunt.hcl`
- [X] T060 [P] [US2] Create OpenClaw values with LiteLLM gateway references and default NFS StorageClass persistence in `clusters/homelab/apps/openclaw/values.yaml`
- [X] T061 [P] [US2] Create OpenClaw ExternalSecret references for app and model integration secrets in `clusters/homelab/apps/openclaw/externalsecret.yaml`
- [X] T062 [P] [US2] Create the OpenClaw tailnet-only Istio route with Funnel disabled in `clusters/homelab/apps/openclaw/virtualservice.yaml`
- [X] T063 [US2] Create the OpenClaw Argo CD Terragrunt unit depending on external-secrets, cert-manager, Istio, Tailscale, LiteLLM, and platform-storage in `IaC/live/argocd-apps/openclaw/terragrunt.hcl`
- [X] T064 [P] [US2] Create Tines Helm values with default NFS StorageClass persistence for automation state in `clusters/homelab/apps/tines/values.yaml`
- [X] T065 [P] [US2] Create Tines ExternalSecret references for app, auth, and integration credentials in `clusters/homelab/apps/tines/externalsecret.yaml`
- [X] T066 [P] [US2] Create the Tines tailnet-only Istio route with Funnel disabled in `clusters/homelab/apps/tines/virtualservice.yaml`
- [X] T067 [US2] Create the Tines Argo CD Terragrunt unit depending on external-secrets, cert-manager, Istio, Tailscale, and platform-storage in `IaC/live/argocd-apps/tines/terragrunt.hcl`
- [X] T068 [US2] Add service app stateful workload profiles and restore expectations in `docs/storage-nfs.md`
- [X] T069 [US2] Add service app tailnet route inventory and zero-Funnel confirmation in `docs/networking-tailnet-ingress.md`
- [X] T070 [US2] Add service app AWS SSM parameter-name inventory with no secret values in `docs/secrets-aws-ssm.md`
- [X] T071 [US2] Add service app ownership, dependency, storage, secret, and ingress entries in `docs/argocd-app-onboarding.md`

**Checkpoint**: User Story 2 is independently reviewable once platform foundations are present.

---

## Phase 5: User Story 3 - Operate, Validate, and Recover the Onboarding (Priority: P3)

**Goal**: Make the onboarding safe to apply, review, validate, and roll back without relying on undocumented live-cluster knowledge.

**Independent Test**: Follow the operations documents without applying live changes and confirm every requested app has validation commands, rollback order, stateful data handling, secret-source expectations, and ingress exposure policy.

### Implementation for User Story 3

- [X] T072 [P] [US3] Add pre-mutation Terragrunt plan, Helm or Kustomize render, and Kubernetes dry-run guidance in `docs/validation-runbook.md`
- [X] T073 [P] [US3] Add dependency-aware rollback order for all 15 requested apps and platform-storage in `docs/rollback-argocd-apps.md`
- [X] T074 [P] [US3] Add per-stateful-app restore instructions and data-preservation warnings in `docs/storage-nfs.md`
- [X] T075 [P] [US3] Add the future Tailscale Funnel webhook exception template with owner, path, purpose, validation, and rollback fields in `docs/networking-tailnet-ingress.md`
- [X] T076 [P] [US3] Update the learner-facing onboarding guide to link app, storage, ingress, validation, and rollback docs in `ONBOARDING.md`
- [X] T077 [US3] Add failure-mode handling for missing AWS SSM parameters, unavailable External Secrets, incompatible NFS provisioner state, unhealthy Argo CD apps, and unavailable Tailscale reachability in `docs/validation-runbook.md`
- [X] T078 [US3] Add the Argo CD sync and health exception recording format for all apps in `docs/argocd-app-onboarding.md`

**Checkpoint**: User Story 3 documents the complete operational path for review, rollout, and recovery.

---

## Phase 6: IaC, GitOps, and Operations Validation

**Purpose**: Prove the generated desired state is reviewable, reproducible, and safe before live rollout.

- [X] T079 Run Terragrunt HCL formatting and record the result in `docs/validation-runbook.md`
- [X] T080 Run `terragrunt run --all plan -no-color` from `IaC/live/argocd-apps` and record the planned Argo CD registrations and dependency edges in `docs/validation-runbook.md`
- [X] T081 Render Helm charts, build Kustomize overlays, or run documented Argo CD source rendering for all app paths and record results in `docs/validation-runbook.md`
- [X] T082 [P] Run repository secret scanning for app values, ExternalSecrets, Terragrunt units, kubeconfigs, private keys, raw certificates, and tokens, then record zero-secret evidence in `docs/validation-runbook.md`
- [X] T083 [P] Verify first-rollout manifests contain zero enabled Tailscale Funnel paths and record the result in `docs/networking-tailnet-ingress.md`
- [X] T084 [P] Verify every persistent app Terragrunt unit depends on `IaC/live/argocd-apps/platform-storage/terragrunt.hcl` and record the result in `docs/storage-nfs.md`
- [X] T085 Run the quickstart pre-rollout workflow and record any unavailable live-cluster validation with reasons in `docs/validation-runbook.md`
- [X] T086 Review the PR readiness checklist and record unresolved checklist items or waivers in `docs/validation-runbook.md`

---

## Phase 7: Follow-Up Automation Defaults

**Purpose**: Enable default Argo CD automation and add safe opt-in image update
automation.

- [X] T087 Add automated prune and self-heal to every app Terragrunt sync policy in `IaC/live/argocd-apps/**/terragrunt.hcl`
- [X] T088 Create the Argo CD Image Updater Terragrunt registration in `IaC/live/argocd-apps/argocd-image-updater/terragrunt.hcl`
- [X] T089 Create Argo CD Image Updater values and opt-in selector CR in `clusters/homelab/apps/argocd-image-updater/`
- [X] T090 Enable automated prune and self-heal on the self-management Application in `clusters/homelab/argocd/self-management/application.yaml`
- [X] T091 Update app inventory, storage readiness, validation, rollback, and bootstrap docs for autosync defaults

---

## Phase 8: Prowlarr Media Follow-Up

**Purpose**: Add Prowlarr as the media indexer manager while preserving the
same Argo CD, Terragrunt, NFS, and tailnet-only rollout model.

- [X] T092 Add Prowlarr app-template values with persistent `nfs-default` config storage in `clusters/homelab/apps/prowlarr/values.yaml`
- [X] T093 Add the Prowlarr tailnet-only Istio route with Funnel disabled in `clusters/homelab/apps/prowlarr/virtualservice.yaml`
- [X] T094 Add the Prowlarr Argo CD Terragrunt unit depending on cert-manager, Istio, Tailscale, and platform-storage in `IaC/live/argocd-apps/prowlarr/terragrunt.hcl`
- [X] T095 Update Radarr and Sonarr Terragrunt dependencies so Prowlarr registration precedes their media automation rollout
- [X] T096 Update app inventory, storage readiness, validation, ingress, secrets, rollback, and spec artifacts for the 15-app desired state

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies and can start immediately.
- **Phase 2 Foundational**: Depends on Phase 1 and blocks rollout-ready work for all user stories.
- **Phase 3 User Story 1**: Depends on Phase 2 and is the MVP.
- **Phase 4 User Story 2**: Depends on Phase 2 and should be reviewed after or alongside User Story 1, but service rollout depends on platform readiness.
- **Phase 5 User Story 3**: Depends on Phase 2 and can progress in parallel with User Story 1 or User Story 2 docs once concrete app paths exist.
- **Phase 6 Validation**: Depends on completed desired-state files and blocks live rollout.

### User Story Dependencies

- **User Story 1 (P1)**: Requires foundational storage, secret, ingress, and dependency docs; no dependency on User Story 2 or User Story 3.
- **User Story 2 (P2)**: Requires foundational docs and platform dependencies from User Story 1 for actual rollout; can still be reviewed independently for desired-state completeness.
- **User Story 3 (P3)**: Requires the concrete app and support paths from User Story 1 and User Story 2 to finalize validation and rollback coverage.

### Application Dependency Highlights

- `cert-manager` depends on `external-secrets`.
- `istio` depends on `cert-manager`.
- `tailscale` depends on `external-secrets` and `istio`.
- Persistent apps depend on `platform-storage`.
- `grafana` depends on `prometheus`.
- `descheduler` depends on `prometheus`.
- `radarr` and `sonarr` depend on `deluge` and `prowlarr`.
- `openclaw` depends on `litellm`.

---

## Parallel Execution Examples

### User Story 1

```text
Task: "Create External Secrets Helm values with AWS SSM backend assumptions in clusters/homelab/apps/external-secrets/values.yaml"
Task: "Create cert-manager Helm values in clusters/homelab/apps/cert-manager/values.yaml"
Task: "Create Istio Helm values for reverse-proxy ownership in clusters/homelab/apps/istio/values.yaml"
Task: "Create Tailscale operator or connector values in clusters/homelab/apps/tailscale/values.yaml"
Task: "Create Prometheus Helm values with default NFS StorageClass persistence in clusters/homelab/apps/prometheus/values.yaml"
```

### User Story 2

```text
Task: "Create Deluge Helm values with default NFS StorageClass persistence for config and downloads in clusters/homelab/apps/deluge/values.yaml"
Task: "Create Prowlarr Helm values with default NFS StorageClass persistence for indexer and app integration config in clusters/homelab/apps/prowlarr/values.yaml"
Task: "Create Radarr Helm values with default NFS StorageClass persistence and Deluge/Prowlarr integration placeholders in clusters/homelab/apps/radarr/values.yaml"
Task: "Create Sonarr Helm values with default NFS StorageClass persistence and Deluge/Prowlarr integration placeholders in clusters/homelab/apps/sonarr/values.yaml"
Task: "Create LiteLLM Helm values with AWS SSM provider placeholders and default NFS StorageClass persistence when state is enabled in clusters/homelab/apps/litellm/values.yaml"
Task: "Create Tines Helm values with default NFS StorageClass persistence for automation state in clusters/homelab/apps/tines/values.yaml"
```

### User Story 3

```text
Task: "Add pre-mutation Terragrunt plan, Helm or Kustomize render, and Kubernetes dry-run guidance in docs/validation-runbook.md"
Task: "Add dependency-aware rollback order for all 15 requested apps and platform-storage in docs/rollback-argocd-apps.md"
Task: "Add per-stateful-app restore instructions and data-preservation warnings in docs/storage-nfs.md"
Task: "Add the future Tailscale Funnel webhook exception template with owner, path, purpose, validation, and rollback fields in docs/networking-tailnet-ingress.md"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 setup.
2. Complete Phase 2 foundational storage, secret, ingress, and dependency prerequisites.
3. Complete Phase 3 platform add-ons.
4. Stop and validate User Story 1 independently with Terragrunt plan output, rendered GitOps sources, zero-secret review, and dependency review.

### Incremental Delivery

1. Deliver Setup plus Foundational to establish shared repo structure and storage safety.
2. Deliver User Story 1 as the MVP platform foundation.
3. Deliver User Story 2 to add homelab services using the same pattern.
4. Deliver User Story 3 to finish validation, rollback, and learner-facing operations guidance.
5. Run Phase 6 validation before any live apply.

### Rollout Gate

Do not roll out stateful apps until `docs/storage-nfs.md` documents NFS backup coverage, restore expectations, and read-only provisioner inspection evidence for the default StorageClass.
