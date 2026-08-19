# Multica Recovery

The `Break Glass Multica Recovery` workflow is a temporary, manual recovery
path for the Multica first rollout when the normal Octelium clientless
Kubernetes CI credential is broken before Terragrunt can run.

The workflow is intentionally constrained:

- it runs only from `main` through `workflow_dispatch`;
- it uses the protected `homelab-production` environment;
- it uses `KUBE_CONFIG_B64` only for the guarded `recover` job;
- it applies the repository-owned `IaC/live/aws-ssm-parameters` unit before
  Multica so bootstrap secret material is created or adopted through its
  declared Terragrunt state owner;
- it uses `terragrunt stack generate` and applies only the repository-owned
  Multica Argo CD unit after the SSM unit succeeds;
- it polls the Multica Argo CD `Application` until it is both synced and
  healthy, then fails the workflow if recovery does not complete;
- it does not imperatively patch, annotate, or otherwise mutate the live
  `Application` during polling.

After the Octelium CI credential is repaired with
`scripts/octelium-ci-credential.sh`, prefer the normal Terragrunt Apply path and
remove this break-glass workflow in a follow-up cleanup PR.
