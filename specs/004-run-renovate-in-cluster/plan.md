<!-- markdownlint-disable MD013 -->
# Implementation Plan: Run Renovate in the Homelab

**Branch**: 004-run-renovate-in-cluster (feature selection; checkout detached) | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from specs/004-run-renovate-in-cluster/spec.md

## Summary

Move the existing Stuhlmuller Renovate GitHub App runner from its daily GitHub Actions schedule to an hourly homelab CronJob. Keep the current global and repository policies, including auto-merge under each repository's protection rules. Use owner-filtered autodiscovery, a persistent protected cache PVC, file-backed App credentials, and the existing Argo CD/Terragrunt path. After a successful full cluster dry run proves parity, retire the legacy workflow and its repository Actions private key in the separate Stuhlmuller/renovate repository before enabling cluster writes.

## Technical Context

**Language/Version**: JavaScript on the Node.js version bundled in a digest-pinned Renovate image; Kubernetes YAML and Terragrunt/OpenTofu HCL.

**Primary Dependencies**: Renovate CLI, GitHub App REST authentication, Argo CD, Kubernetes CronJob, External Secrets, AWS SSM Parameter Store, and the existing NFS StorageClass.

**Storage**: One retained nfs-default PVC for package, repository-extraction, private-package, and downloaded-tool caches. Ephemeral base directory for clones and work files; no backup of rebuildable cache. A separate protected, temporary ledger PVC records acceptance samples and is retired through GitOps after aggregate reporting.

**Testing**: Global/repository config validation; mock App-token and discovery-transition tests; Kustomize render and policy checks; Terragrunt format/validate/plan for changed units; a GitOps-deployed Renovate full dry run; scheduled-run, TRACE-level cache-hit, reviewed release-canary, PR-identity, and sampled seven-day acceptance checks.

**Target Platform**: Talos Kubernetes homelab, GitHub.com repositories owned by Stuhlmuller, and the existing AWS SSM secret path.

**Project Type**: Scheduled GitOps-managed infrastructure workload with a small file-backed authentication adapter; no inbound service.

**Performance Goals**: One cycle hourly; 95% start within 15 minutes; no overlap; 95% of independently observed eligible releases in the preregistered sample proposed or explicitly deferred within four hours during healthy operation.

**Constraints**: One-hour GitHub App installation-token lifetime; bound each job below that lifetime; no public endpoint, cluster API credential, permanent GitHub token, plaintext secret, manual live mutation, or environment variable as a desired-state input.

**Scale/Scope**: All non-archived repositories owned by Stuhlmuller, including newly owned and forked repositories; archived repositories are skipped, while missing App access to an otherwise eligible owned repository blocks cutover. Current read-only owner inventory has eight non-archived repositories, but cutover must compare the App's actual access.

## Constitution Check

The repository's .specify/memory/constitution.md is v1.0.0 and derives from AGENTS.md. The design must satisfy its five principles and the more detailed repository rules.

| Gate | Design result |
| --- | --- |
| Declarative changes and one Terragrunt root apply | Pass: register through the shared Argo CD unit; add SSM/IAM desired state to existing IaC owners. |
| Public-repository secret boundary | Pass: commit names and contracts only; transfer the existing key through protected CI into SSM and mount it as a file. |
| No environment-derived desired state | Pass: commit global config and read mounted credential files; keep the installation token in process memory. |
| GitOps-only cluster mutation | Pass: Argo CD owns CronJob, PVC, ExternalSecret, and rules; no ad hoc kubectl mutation. |
| Pinned images and preflight validation | Pass: publish and pin a reviewed Renovate image digest, render manifests, plan IaC, and complete a GitOps-deployed dry run before write-enabled activation. |
| State, backup, and rollback | Pass: cache is retained but rebuildable; document PVC reset and a two-repository schedule rollback. |
| Documentation and source ownership | Pass: update app README, secret matrix, image-automation guide, workload inventory source, and generated wiki through its documented refresh path. |

**Post-design recheck**: The file-backed token flow satisfies secret safety; the protected rebuildable cache has documented storage and recovery; the two-repository cutover remains declarative and reviewable. The separate Renovate-repository PR and secure key-transfer workflow are required before activation. No constitution exception is needed.

## Project Structure

### Documentation (this feature)

    specs/004-run-renovate-in-cluster/
      spec.md
      plan.md
      research.md
      data-model.md
      quickstart.md
      contracts/runner-contract.md
      tasks.md                  # Created by speckit-tasks, not this phase

### Source Code (repository root)

    clusters/homelab/apps/renovate/
      kustomization.yaml
      cronjob.yaml
      pvc.yaml
      externalsecret.yaml
      config.js                 # Global policy and App token from mounted files
      README.md
    IaC/stacks/renovate/stack.hcl
    IaC/terragrunt.stack.hcl
    IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl
    IaC/modules/aws-github-actions-role-policy/
    clusters/homelab/apps/prometheus/
    clusters/homelab/apps/renovate/acceptance-observer.js
    clusters/homelab/apps/renovate/acceptance-observer-cronjob.yaml
    clusters/homelab/apps/renovate/acceptance-ledger-pvc.yaml
    clusters/homelab/apps/renovate/acceptance-ledger-cleanup-job.yaml
    scripts/config/harbor-images.json
    docs/secrets-aws-ssm.md
    docs/image-automation.md
    scripts/ci/

**Companion source**: Stuhlmuller/renovate owns the existing .github/workflows/renovate.yml. A reviewed change there transfers the current App secret through a dedicated CI path, then removes the legacy workflow including manual dispatch after dry-run parity. A guarded script retires its repository Actions private key before cluster writes. Its temporary renovate.json custom manager watches scripts/fixtures/renovate-cache-canary.txt through the github-releases datasource; a protected workflow publishes the controlled GitHub Releases. Remove this companion fixture and workflow after acceptance.

**Structure Decision**: Use a namespaced workload in the existing automation namespace and homelab-workloads Argo CD project, following the policy-bot and backup-CronJob patterns. No new service, ingress, Redis, or custom controller.

## Design

1. **Policy**: Carry forward the existing global config, with owner-filtered autodiscovery, optional repository config, no onboarding, and fork processing enabled. Keep current auto-merge and per-repository overrides. Do not permit untrusted install scripts or arbitrary post-upgrade commands globally.
2. **Schedule and cache**: Use an hourly CronJob with Forbid concurrency, a 15-minute start deadline, and an active deadline below 60 minutes. Mount a retained PVC only at Renovate's cache directory; enable repository and private-package caches; retain upstream TTL behavior. Keep clones on ephemeral storage and size/expand the PVC from measured use.
3. **Credentials**: Reuse the existing Renovate App. Declare exact SSM parameters, a file-backed ExternalSecret, and a dedicated short-lived CI transfer role for the existing GitHub Actions secret. The config file signs an App JWT and mints one installation token per Job without writing it to disk or environment. Disable service-account token mounting. Remove the temporary transfer grant after Secret projection is verified; rotation first restores a reviewed temporary grant.
4. **Observability**: Retain Job history and access-restricted logs. Reuse the existing failed-Job rule; add an hourly freshness rule because a missed cycle creates no failed Job. Use Renovate's per-repository result logs for diagnosis without publishing private names or package data.
5. **Cutover**: Publish the pinned image, reconcile the CronJob initially suspended, and verify Secret projection before unsuspending it in full dry-run mode through GitOps. Validate discovery, planned proposals, existing App identity and PR continuity, effective merge policy, and cache reuse. After the last legacy run finishes, delete its entire workflow through a reviewed companion PR and verify no scheduled or manual trigger or nonterminal legacy run remains across event types. Retire the repository Actions private key with a guarded current-main receipt proving SSM transfer, later Ready Secret projection, key absence, and drained old runs. Only then enable cluster writes through reviewed GitOps and verify a real scheduled run. If deletion, drainage, or key retirement cannot complete, stay in dry-run mode. Roll back by suspending cluster writes in GitOps, verifying no pending or active Job or Pod, restoring the Actions key from SSM with the guarded companion script and receipt, then restoring the legacy workflow through a reviewed PR. The interval between deletion and the first cluster write is a planned no-writer gap.
6. **Acceptance evidence**: Fix a reproducible dependency sample across all used datasource classes before the seven-day window. A temporary GitOps-managed, read-only, no-shared-cache observer and protected ledger record upstream release visibility brackets and compare them with GitHub PR or policy-deferral timestamps; publish only aggregates and remove the observer through reviewed code after acceptance. The companion repository's temporary custom manager watches its own canary file through github-releases; publish the next version only through its reviewed workflow to prove refresh after normal cache expiry. Confirm a package-cache hit in distinct Pods using scoped restricted TRACE or a mock-registry counter. Before cutover, prove live owner/App inventory parity and all-repositories installation selection; a deterministic mocked add/remove transition tests discovery logic, while the first real owner transition remains a later operational check.

## Delivery Order and Gates

1. Capture the legacy workflow/config SHA, current App access and permission grants, owner inventory, and a baseline run. Verify archived/fork behavior, inventory parity, and current PR identity.
2. Add reviewed SSM placeholders and a dedicated transfer IAM role. Use protected CI in Stuhlmuller/renovate to transfer only the existing App issuer ID and private key; verify ExternalSecret readiness without reading values.
3. Mirror and pin the Renovate image; add the hourly workload suspended in full dry-run mode and focused tests. Render manifests, validate policy and config, and plan the affected Terragrunt units before any live change.
4. Reconcile via the declared GitOps path. Verify ExternalSecret projection, remove the temporary transfer grant, then unsuspend the dry-run schedule through a reviewed desired-state change. Observe at least two dry-run cycles, including a package-cache hit after a pod replacement and a reviewed release canary after normal refresh. Compare planned proposals, existing PR continuity, App identity, and effective auto-merge policy with the legacy baseline.
5. After the last legacy run finishes, remove its workflow, including manual dispatch, through a companion PR and verify no nonterminal legacy run or trigger remains across scheduled and manual events. Retire the repository Actions private key with a current post-delete receipt, then remove full dry-run mode through a reviewed GitOps change and verify at least one eligible PR/deferral under the same App and merge policy. Observe the one-writer invariant and failure/freshness signals; use the quickstart for seven-day SLO acceptance and guarded key restore before any legacy rollback.
