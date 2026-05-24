# Contract: Argo CD Bootstrap Operator Workflow

This contract defines the operator-facing interface for bootstrapping Argo CD
with Terragrunt and handing steady-state ownership to Argo CD.

## Entry Point

```sh
cd IaC/bootstrap/argocd
terragrunt apply
```

The command MUST be the documented one-command bootstrap entry point for this
feature. It may be preceded by read-only validation commands, but the durable
desired-state apply path must remain this Terragrunt unit.

## Required Preconditions

- Kubernetes API access for the target homelab cluster is available through the
  documented local operator context or CI/CD credential injection.
- Provider credentials required for encrypted OpenTofu state are available as
  external credential material and are not committed.
- `IaC/root.hcl` remote state settings are valid for the chosen stack path.
- The Argo CD desired-state repository path exists before the self-management
  Application is applied.
- No raw repository credential, token, key, kubeconfig, Talos secret, or
  certificate material is present in the changed files.

## Committed Inputs

The Terragrunt unit or module input file MUST commit the following non-secret
inputs:

- Argo CD namespace
- Argo CD Helm chart repository, chart name, and pinned chart version
- Argo CD service exposure mode
- Argo CD self-management application name
- Desired-state repository URL or safe reference
- Desired-state path
- Desired-state target revision
- Sync handoff mode
- KMS key alias or ARN for encrypted OpenTofu state/plan handling

The implemented input names are:

- `terraform.source`
- `name`
- `namespace`
- `create_namespace`
- `repository`
- `chart`
- `chart_version`
- `values`
- `values[0].configs.params.server.insecure`
- `values[0].server.service.type`
- `after_hook.apply_self_management_application`
- `self_management_application_manifest`
- `kms_key_id`
- `kms_region`
- `kms_key_spec`

The workflow MUST NOT require `get_env`, `TF_VAR_*`, shell-exported values, or
process environment lookups for normal operator-selected desired state.

## Expected Outputs

After a successful first apply:

- The `argocd` namespace exists.
- The Argo CD Helm release is present and healthy enough for its CRDs to be
  served by the Kubernetes API.
- The Argo CD self-management Application exists in the `argocd` namespace.
- The self-management Application points at this repository and the declared
  desired-state path.
- Argo CD steady-state ownership is ready for first-sync validation.

After the validated handoff:

- Argo CD owns steady-state Argo CD configuration from repository desired state.
- Automated prune/self-heal is enabled only after the source path and first sync
  have been verified.

## Failure Contract

- If Argo CD CRDs are missing, the operator verifies the Helm release before
  retrying the self-management registration.
- If the self-management Application points at the wrong path, the operator
  corrects repository desired state before reapplying.
- If credentials are missing, the operator supplies them through the documented
  external credential or CI/CD injection path.
- If a live emergency mutation is made, the mutation is incomplete until the
  repository desired state is updated and validated.
