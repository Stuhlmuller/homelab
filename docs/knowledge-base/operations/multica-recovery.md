# Multica Recovery

The `Break Glass Multica Recovery` workflow is a temporary, manual recovery
path for the Multica first rollout when the normal Octelium clientless
Kubernetes CI credential is broken before Terragrunt can run.

The workflow is intentionally constrained:

- it runs only from `main` through `workflow_dispatch`;
- it uses the protected `homelab-production` environment;
- it uses `KUBE_CONFIG_B64` only for this named break-glass workflow;
- it creates Multica SSM bootstrap parameters only when AWS returns
  `ParameterNotFound`;
- it does not overwrite existing Multica SSM parameter values;
- it applies only the Multica Argo CD `Application` and asks Argo CD to refresh.

After the Octelium CI credential is repaired with
`scripts/octelium-ci-credential.sh`, prefer the normal Terragrunt Apply path and
remove this break-glass workflow in a follow-up cleanup PR.
