# Data Model: Bootstrap Argo CD With Terragrunt

## Bootstrap Stack

Represents the single Terragrunt entry point operators use for the initial Argo
CD bootstrap.

**Fields**

- `path`: `IaC/bootstrap/argocd/terragrunt.hcl`
- `source_module`: `git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/helm-release?ref=0.3.0`
- `cluster_name`: committed non-secret cluster identifier
- `argocd_namespace`: namespace for Argo CD resources, default `argocd`
- `kms_key_id`: committed non-secret KMS key alias or ARN used for encrypted
  OpenTofu state and plans
- `desired_state_repo_url`: public repository URL or safe repository reference
- `desired_state_target_revision`: branch, tag, or commit used by the
  self-management application
- `desired_state_path`: repository path containing Argo CD steady-state config
- `self_management_application_manifest`: repo-owned manifest path applied by
  the Terragrunt `after_hook`
- `handoff_mode_annotation`: `initial-validation` or `automated`
- `chart_version`: pinned chart version, initially `9.5.15`
- `source_repo_url`: `https://github.com/Stuhlmuller/homelab.git`
- `source_path`: `clusters/homelab/argocd/self-management`
- `target_revision`: `main`

**Validation Rules**

- `path` MUST be the documented one-command entry point.
- `argocd_namespace` MUST be non-empty and hyphenated if changed.
- `kms_key_id` MUST NOT be read from environment variables.
- Repository credentials MUST NOT be committed.
- The handoff-mode annotation MUST start as `initial-validation` for first
  bootstrap.

**State Transitions**

1. `not-applied`
2. `argocd-installed`
3. `self-management-registered`
4. `handoff-validated`
5. `automated-reconciliation-enabled`

## Argo CD Installation

Represents the Helm-managed initial Argo CD install created by Terragrunt.

**Fields**

- `release_name`: Helm release name, default `argocd`
- `namespace`: Kubernetes namespace, default `argocd`
- `chart_repository`: Argo CD Helm repository URL
- `chart_name`: Argo CD chart name
- `chart_version`: pinned chart version
- `service_type`: expected `ClusterIP` for initial bootstrap
- `values`: committed non-secret Helm values
- `wait`: whether the install waits for readiness
- `timeout`: maximum install/update wait duration

**Validation Rules**

- `chart_version` MUST be pinned before live rollout.
- `service_type` MUST remain internal unless ingress is separately specified.
- Helm values MUST NOT contain raw secrets.
- Install MUST complete before the self-management Application is planned or
  applied.

## Self-Management Application

Represents the Argo CD Application that points Argo CD back at this repository.

**Fields**

- `name`: Argo CD application name
- `namespace`: namespace containing the Application CRD, default `argocd`
- `project`: Argo CD project, default `default` unless a project is added
- `source_repo_url`: repository URL or safe reference
- `source_path`: path containing Argo CD desired state
- `target_revision`: branch, tag, or commit
- `destination_server`: target Kubernetes API URL, normally in-cluster
- `destination_namespace`: target namespace
- `sync_policy`: manual for first handoff, automated after validation
- `sync_options`: list of Argo CD sync options
- `finalizers`: optional resource cleanup finalizers
- `apply_mode`: Terragrunt `after_hook` during clean bootstrap, Argo CD
  reconciliation after handoff

**Validation Rules**

- `source_path` MUST exist in the repository before rollout.
- First handoff MUST be validated before automated prune/self-heal is enabled.
- `destination_namespace` MUST match the intended Argo CD namespace unless the
  desired-state path explicitly separates install and runtime configuration.
- Credentials MUST be references only.

**State Transitions**

1. `absent`
2. `created-by-terragrunt`
3. `first-sync-pending`
4. `first-sync-validated`
5. `automated-sync-enabled`
6. `steady-state-managed-by-argocd`

## Catalog Module Source

Represents the remote catalog module source used by the bootstrap stack.

**Fields**

- `catalog_url`: `https://github.com/Stuhlmuller/terragrunt-catalog`
- `catalog_ref`: pinned catalog version `0.3.0`
- `catalog_commit`: `415f4ec587846f6928aeb344cd9e46f66c16a005`
- `module_name`: `helm-release`
- `source`: `git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/helm-release?ref=0.3.0`

**Validation Rules**

- `catalog_ref` MUST be pinned.
- No repository-local OpenTofu module copy may be used by this bootstrap stack.
- Any later catalog refresh MUST be a separate reviewed code change.

## Bootstrap Runbook

Represents the operator-facing documentation needed to run, verify, roll back,
and recover the bootstrap.

**Fields**

- `prerequisites`
- `apply_command`
- `validation_commands`
- `expected_healthy_state`
- `first_handoff_validation`
- `enable_automation_step`
- `rollback_steps`
- `partial_failure_recovery`
- `break_glass_backfill_rule`

**Validation Rules**

- Runbook MUST identify the one Terragrunt apply entry point.
- Runbook MUST include failure modes for missing CRDs, bad repo path,
  credentials, and partial install.
- Runbook MUST state that live emergency changes are incomplete until backfilled
  into repository code.
