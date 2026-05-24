# Quickstart: Argo CD Application Onboarding

This quickstart describes the intended validation and rollout path for the
implementation generated from this plan. Commands assume the operator is at the
repository root.

## 1. Review Scope

Confirm the feature includes the 13 requested Argo CD Applications plus the
supporting platform storage registration:

```sh
find IaC/live/argocd-apps -mindepth 1 -maxdepth 1 -type d | sort
```

Expected app directories:

```text
cert-manager
deluge
descheduler
external-secrets
grafana
istio
litellm
openclaw
platform-storage
prometheus
radarr
sonarr
tailscale
tines
```

## 2. Confirm Secret Safety

Review committed secret references:

```sh
rg -n "AWS SSM|ssm|ExternalSecret|parameter" clusters/homelab/apps IaC/live/argocd-apps
```

Expected result: only AWS SSM Parameter Store names or paths, ExternalSecret
names, and non-secret defaults are present. No plaintext tokens, passwords,
private keys, private certificates, or kubeconfigs with credentials are
committed.

## 3. Validate Terragrunt Structure

Format and validate the Terragrunt units:

```sh
terragrunt hcl fmt
```

Run plans from the app registration root:

```sh
cd IaC/live/argocd-apps
terragrunt run --all plan -no-color
```

Expected result: 13 requested Argo CD Application registrations plus the
supporting `platform-storage` registration are planned, and each unit with
upstream requirements lists explicit Terragrunt dependencies.

## 4. Render Or Review GitOps Sources

For Helm-backed applications, render each chart with the committed values file
or use Argo CD's source rendering in the target environment. For repo-owned raw
or Kustomize manifests, build or dry-run the path:

```sh
kubectl diff --server-side -f clusters/homelab/apps/<app>
```

Expected result: manifests render deterministically and do not require manual
cluster edits.

## 5. Verify Network Policy And DNS Assumptions

Confirm implementation documents:

- Istio as the reverse proxy.
- Tailscale tailnet as internal reachability.
- Zero first-rollout Tailscale Funnel paths.
- Initial DNS setup that avoids per-app DNS record edits.

Expected result: every app is tailnet-only in the first rollout.

## 6. Validate Stateful Workload Profiles

Discover the existing NFS provisioner with read-only inspection before
committing the default StorageClass desired state:

```sh
kubectl get storageclass -o yaml
kubectl get storageclass
```

Expected result: the operator identifies the existing NFS provisioner name and
any public-safe StorageClass parameters. Private hostnames, sensitive export
paths, or other unsafe local values are redacted, replaced with placeholders, or
documented as external prerequisites before review.

Confirm the default NFS StorageClass desired state exists and only references
public-safe provisioner details:

```sh
rg -n "StorageClass|provisioner|storageclass.kubernetes.io/is-default-class" clusters/homelab/platform/storage
```

Expected result: one NFS-backed StorageClass is marked default, references the
existing provisioner discovered through read-only inspection, and does not
commit unsafe private provisioner values.

Before rollout, inspect each stateful app profile in docs or app-local README:

```sh
rg -n "Storage|Backup|Restore|Rollback" clusters/homelab/apps docs
```

Expected result: Prometheus, Grafana, Tines, Radarr, Sonarr, Deluge, OpenClaw,
and LiteLLM use the default NFS StorageClass unless an exception is documented,
and each has explicit backup coverage, restore, and rollback decisions.

## 7. Roll Out Through Desired State

After planning passes and required external secret material exists in AWS SSM
Parameter Store, apply from the Terragrunt app registration root:

```sh
cd IaC/live/argocd-apps
terragrunt run --all apply
```

Do not create applications manually in the Argo CD UI.

## 8. Post-Rollout Checks

Check Argo CD sync and health:

```sh
argocd app list
argocd app get platform-storage
argocd app get external-secrets
argocd app get cert-manager
argocd app get istio
argocd app get tailscale
argocd app get prometheus
argocd app get grafana
argocd app get descheduler
argocd app get deluge
argocd app get radarr
argocd app get sonarr
argocd app get litellm
argocd app get openclaw
argocd app get tines
```

Expected result: all 13 requested applications plus the supporting
platform-storage registration reach the documented sync and health expectation
within 30 minutes, or each exception is recorded with an operator action and
rollback decision.

## 9. Rollback Order

Rollback dependent services before shared foundations:

1. OpenClaw
2. Tines
3. Radarr and Sonarr
4. LiteLLM
5. Deluge
6. Grafana
7. Descheduler
8. Prometheus
9. platform-storage
10. Tailscale
11. Istio
12. cert-manager
13. external-secrets

Before deleting or disabling any stateful application, follow its workload
profile and preserve or snapshot persistent data according to the documented
rollback behavior.
