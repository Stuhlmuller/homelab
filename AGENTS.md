# Agent Harness

This public repository is the control surface for a Kubernetes homelab running
on Talos Linux. It has two goals:

- Operate the homelab through repeatable code changes, PRs, and agent-assisted
  maintenance.
- Teach the system as it evolves so readers can learn how to start, operate,
  and upgrade their own homelab.

Agents should treat the repo as both production infrastructure and educational
material. A good change should be safe to apply, easy to review, and useful to
someone learning the pattern for the first time.

## Repository intent

- Prefer declarative, reproducible configuration over manual cluster mutation.
- Use OpenTofu modules orchestrated by Terragrunt for infrastructure as code,
  and preserve a documented path that can stand the project up from scratch with
  one `terragrunt apply` command after public prerequisites and external secret
  material are available.
- Deliver Kubernetes runtime changes through Argo CD, Helm, Kustomize,
  repository-owned manifests, or another declared code path in this repository.
- Keep Talos, Kubernetes, networking, storage, and secret-management decisions
  documented near the code that implements them.
- Make PRs the normal unit of change for cluster setup, maintenance, upgrades,
  and documentation.
- Include the "why" when changing architecture, workflows, or operational
  assumptions.
- Keep examples copyable, but clearly mark values that are specific to this
  homelab.

## Expected ownership

The exact tree may change as the homelab grows. Preserve these ownership
boundaries when adding or moving files:

- `.talos/` owns Talos machine config, patches, generated-safe templates, and
  Talos client configuration references.
- Kubernetes app and cluster directories own manifests, Helm values, Kustomize
  overlays, GitOps resources, and namespace-scoped configuration.
- Infrastructure-as-code directories own OpenTofu modules, Terragrunt stacks,
  Terragrunt includes, generated backend/provider configuration, and cloud or
  external dependencies such as DNS, object storage, IAM, and state backends.
- `docs/` and top-level guides own learner-facing explanations, walkthroughs,
  diagrams, and runbooks.
- `scripts/` owns repeatable operator commands and validation helpers.
- `.codex/skills/` owns project-local Codex skills that wrap validated
  workflows.

Do not reintroduce Nomad, Ansible, or host-bootstrap assumptions unless the code
base intentionally adopts them again and the documentation explains why.

## Safety rules

- This is a public repository. Never commit secrets, kubeconfigs with private
  credentials, Talos secrets, age keys, tokens, private SSH keys, private
  hostnames that should not be public, or raw certificate material.
- Commit secret references, sealed/encrypted secret manifests, external-secret
  names, and non-secret defaults only when they are safe for a public repo.
- Do not use environment variables as normal inputs for Terragrunt, OpenTofu,
  Helm, Kustomize, Talos config, application config, or local operator
  workflows. Desired-state inputs must be committed as non-secret code or data.
- Use environment variables only inside CI/CD pipelines for credentials or
  secret injection. If a secret is required, inject it in the CI/CD pipeline and
  keep only safe references, templates, encrypted values, or contracts in git.
- Treat live Talos and Kubernetes operations as production changes, even though
  this is a homelab.
- Never make manual infrastructure, cloud, Talos, Kubernetes, Argo CD, or
  secret-manager changes to fix live state. All desired-state changes must be
  represented in repository-owned code first and then applied through the
  declared code path, such as Terragrunt, Argo CD, Helm, Kustomize, Talos
  config, or a repo-owned script.
- Do not use ad hoc live mutation commands such as `kubectl apply`,
  `kubectl patch`, `kubectl delete`, `kubectl annotate`, `talosctl apply-config`,
  cloud-provider CLIs, or provider web consoles to repair drift or unblock a
  rollout. If the required change cannot be expressed in this repository, stop
  and add or request the missing code path before changing live state.
- Do not change live cluster state until the relevant validation commands have
  passed or you have recorded why they are unavailable.
- Prefer read-only inspection before changing bootstrap, networking, storage,
  or upgrade assumptions.
- Use `--insecure` with `talosctl` only for nodes that are known to be in Talos
  maintenance mode before machine config has been applied.
- After Talos machine config is applied, use authenticated Talos access through
  the configured Talos client config.
- Keep Kubernetes ingress explicit and documented. Public HTTP entry points
  should be intentional, reviewed, and routed through the chosen ingress
  controller.
- Keep persistent storage, backup, and restore implications documented for any
  stateful workload.
- Prefer file-backed or controller-managed runtime secrets over direct
  environment-variable injection.

## Default agent workflow

1. Read the relevant docs and code before changing behavior.
2. Inspect current state with read-only commands when the task depends on live
   cluster reality.
3. Run the repo validation gate when available, such as `nix run .#validate` or
   the documented replacement.
4. Make the smallest code and documentation change that solves the request.
5. Re-run relevant validation.
6. For live rollout work, run any documented live-cluster validation before
   applying changes.
7. Summarize what changed, what was validated, and any remaining operational
   risk.

If a checkout is intentionally incomplete and expected scripts or Nix targets
are missing, say that clearly in the PR or final response and use the next best
specific validation available, such as `talosctl validate`, `kubectl diff`,
`helm template`, or `kustomize build`.

## Documentation standards

- Write for a reader who is technical but may be new to Talos, Kubernetes, or
  homelab operations.
- Keep operational runbooks concrete: include commands, expected outputs, and
  failure modes when useful.
- Separate public teaching values from private local values. Use placeholders
  for anything that should not be copied directly.
- When adding automation, document what it changes, how to verify it, and how
  to roll it back.
- Prefer diagrams and short explanations for architecture changes, but keep the
  source of truth in code.

## Infrastructure-as-code conventions

- Use OpenTofu for infrastructure modules and Terragrunt for stack orchestration.
- Keep module inputs small, typed, and readable. If adding another similar
  resource requires copying a large block, introduce or extend a module first.
- Keep module and stack inputs explicit in repository-owned code or data. Do
  not use `get_env`, `TF_VAR_*`, shell-exported values, or process environment
  lookups to change desired state outside CI/CD credential or secret injection.
- Keep the steady-state bootstrap path compatible with one documented
  `terragrunt apply` command from the chosen root. If a temporary staged
  bootstrap is unavoidable, document why and what follow-up restores the single
  apply path.
- Run Terragrunt/OpenTofu formatting and planning for affected stacks before
  applying infrastructure changes, or record why those checks were unavailable.

## Kubernetes and Talos conventions

- Use hyphenated Kubernetes object and node names.
- Keep Talos machine config changes patch-oriented when only one node differs
  from the shared baseline.
- Validate Talos configs with `talosctl validate --mode metal --strict` before
  applying them.
- Use `kubectl diff`, server-side dry runs, Helm rendering, or Kustomize builds
  before applying Kubernetes changes when those tools match the change.
- Do not hand-edit, patch, delete, restart, annotate, or otherwise mutate live
  resources to make a change. Capture the desired state in git and apply through
  the documented workflow.
- For Argo CD Applications or other Git-backed chart/manifest references that
  point at this repository, set the remote target revision to the default branch
  `main` unless the change explicitly documents a temporary non-default branch
  for testing or recovery.
- When upgrading Talos, Kubernetes, CNI, CSI, ingress, or cert-manager, include
  version notes and rollback considerations.

## Current cluster notes

Known details from the existing onboarding guide:

- Talos control plane endpoint: `10.1.0.199`
- Kubernetes API endpoint: `https://10.1.0.199:6443`
- Talos config reference: `.talos/talosconfig`
- Base worker config reference: `.talos/worker.yaml`
- Worker nodes use hyphenated names such as `zimaboard-0`, `zimaboard-1`, and
  `zimaboard-2`.
- Persistent storage NAS: QNAP NFS share `homelab` at `10.1.0.2`.

Refresh these notes whenever the cluster topology changes. If they conflict
with a newer runbook or live read-only inspection, update the docs in the same
PR as the operational change.

## Active Technologies
- HCL for Terragrunt/OpenTofu; Kubernetes YAML and Helm values for GitOps desired state + Terragrunt catalog modules `argocd-application` and, only when exact CRD control is required, `argocd-application-manifest`; Argo CD; Helm/Kustomize-compatible application sources; AWS SSM Parameter Store through external-secrets (001-onboard-argocd-apps)
- Kubernetes persistent volumes for stateful apps that require data retention: Prometheus, Grafana, Tines, Radarr, Sonarr, Deluge, OpenClaw, and LiteLLM when configured with persistent state; no persistent storage expected for cert-manager, external-secrets, Istio, Tailscale, or descheduler except controller-managed runtime objects (001-onboard-argocd-apps)
- HCL for Terragrunt/OpenTofu, Kubernetes manifest schemas, Markdown runbooks + Terragrunt, OpenTofu, Helm provider, Kubernetes provider, Argo CD Helm chart, Argo CD Application CRD (001-bootstrap-argocd-terragrunt)
- S3 remote state from `IaC/root.hcl`; no workload persistent storage introduced by this feature (001-bootstrap-argocd-terragrunt)

## Recent Changes
- 001-onboard-argocd-apps: Added HCL for Terragrunt/OpenTofu; Kubernetes YAML and Helm values for GitOps desired state + Terragrunt catalog modules `argocd-application` and, only when exact CRD control is required, `argocd-application-manifest`; Argo CD; Helm/Kustomize-compatible application sources; AWS SSM Parameter Store through external-secrets
- 001-bootstrap-argocd-terragrunt: Added HCL for Terragrunt/OpenTofu, Kubernetes manifest schemas, Markdown runbooks + Terragrunt, OpenTofu, Helm provider, Kubernetes provider, Argo CD Helm chart, Argo CD Application CRD
