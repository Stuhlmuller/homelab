# Argo CD Self-Management

This directory is the repository-owned desired-state path for Argo CD managing
its own steady-state configuration in the `homelab` cluster.

Terragrunt owns only the first seed:

- Install the Argo CD Helm release.
- Create the cluster-capable `homelab` AppProject and the namespace-limited
  `homelab-workloads` AppProject.
- Disable the wildcard `default` AppProject so new Applications must choose a
  reviewed project explicitly.
- Create the `argocd-self-management` Application.
- Hand off to repository-defined automated prune and self-heal.

Argo CD owns changes under this directory after bootstrap. Automated prune and
self-heal are part of the repository desired state, so changes to the source
path, revision, or sync policy must still be reviewed in git instead of patched
as permanent live mutations.

`cmd-params-configmap.yaml` bounds sync operations to 15 minutes so a failed
resource cannot leave an Application operation running forever. During the
reviewed ownership transfer, bootstrap Helm declares the same required data and
both copies carry no-prune and ignore-extraneous annotations. Remove this file
only after the protected bootstrap apply and live parameter checks pass; Helm
then becomes the sole declared owner without an automated-prune deletion gap.

Before the follow-up removal, run these read-only checks:

```sh
helm get values argocd --namespace argocd --all -o json |
  jq -e '.configs.params."controller.sync.timeout.seconds" == "900" and
    .configs.params."server.insecure" == "true" and
    .configs.params.annotations."argocd.argoproj.io/sync-options" == "Prune=false" and
    .configs.params.annotations."argocd.argoproj.io/compare-options" == "IgnoreExtraneous"'
kubectl --namespace argocd get configmap argocd-cmd-params-cm -o json |
  jq -e '.data."controller.sync.timeout.seconds" == "900" and
    .data."server.insecure" == "true" and
    .metadata.annotations."argocd.argoproj.io/sync-options" == "Prune=false" and
    .metadata.annotations."argocd.argoproj.io/compare-options" == "IgnoreExtraneous"'
kubectl --namespace argocd get application argocd-self-management -o json |
  jq -e '.status.sync.status == "Synced" and .status.health.status == "Healthy"'
```

All three commands must exit successfully before phase two.

Keep each named AppProject's sources, destinations, and resource allow-lists
aligned with the Applications registered under `IaC/live/argocd-apps`.
Ordinary applications that render no cluster resources belong in
`homelab-workloads`. Keep platform controllers and applications that require
audited cluster resources in `homelab`. Update the selected project manifest
in the same PR as any new chart repository, namespace, or resource kind. Keep
`default-appproject.yaml` intentionally empty.

This path also owns the External Secrets Operator resources that create the
`argocd-oidc-sso` Kubernetes Secret from AWS Systems Manager Parameter Store.
Keep those resources here instead of the Terragrunt bootstrap Helm values so a
fresh cluster can install Argo CD before External Secrets CRDs exist. Sync
`oidc-external-secret.yaml` only after External Secrets Operator is installed
and allowed to read the Argo CD OIDC issuer, client ID, and client secret
parameters in `us-west-2`. The browser-facing Argo CD URL is non-secret
desired state in the bootstrap Terragrunt values, not an SSM parameter.
The ExternalSecret uses `refreshPolicy: OnChange`; if only the SSM values
change, roll that through a repo-owned metadata or spec change and let Argo CD
sync it instead of patching the live resource.
