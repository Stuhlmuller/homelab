# Entra provider authentication

Microsoft Entra resources are managed by OpenTofu through Terragrunt. The
existing Azure CLI operator login can bootstrap the provider identities, so no
manual application creation or new subscription is required.

`IaC/operator/azuread-ci-identities` owns two applications, their service
principals, exact GitHub federation subjects, requested Microsoft Graph
permissions and the corresponding permission grants. This operator unit uses
the shared encrypted remote state and is excluded from normal CI traversal.
Its declared human owner retains ownership of both automation identities; CI
does not own them or receive permission to grant itself additional Graph roles.

| Identity | Trust | Graph application permissions |
| --- | --- | --- |
| `homelab-terraform-plan` | `repo:Stuhlmuller/homelab:environment:homelab-plan` | `Application.Read.All`, `User.Read.All`, `Policy.Read.All` |
| `homelab-terraform-apply` | `repo:Stuhlmuller/homelab:environment:homelab-production` | The same reads plus `Application.ReadWrite.OwnedBy` |

Both trusts use issuer `https://token.actions.githubusercontent.com` and audience
`api://AzureADTokenExchange`. The workflows select OIDC explicitly and disable
Azure CLI/MSI fallback. No client password or certificate is created. Microsoft
lists [workload identity federation in Entra Free](https://learn.microsoft.com/en-us/entra/workload-id/workload-identities-faqs).
Neither provider needs an Azure resource subscription to manage Microsoft Graph.

These grants deliberately exclude `User.ReadWrite.All`,
`AppRoleAssignment.ReadWrite.All`, and
`Policy.ReadWrite.ApplicationConfiguration`. User lifecycle, claims-policy
changes and user/application assignments remain reviewed **operator Terraform
operations**, using the existing state and modules. Do not grant tenant-wide
write powers merely to make a CI apply succeed. In particular,
`AppRoleAssignment.ReadWrite.All` can grant API permissions and elevate its own
principal; it is not limited to assigning Fleet administrators.

The plan identity's claims-assignment refresh is a live acceptance gate:
Microsoft's documented least permissions for that read include
`Application.ReadWrite.OwnedBy`. Test the narrower read grants first. A denied
read remains a failure requiring a reviewed solution, not permission to skip
refresh, impersonate the operator or call a write-capable planner read-only.

## Stable ownership

Fleet declares human and automation owners explicitly. It no longer derives
ownership from the currently authenticated Terraform principal. Grafana and
Octelium retain their pinned catalog module; a generated
`ownership_override.tf` changes only its existing `owners` attribute using
ordinary Terraform data-source lookups. The override preserves every other
attribute and nested block. A separate `azuread_application_owner` resource is
incompatible with the catalog's `azuread_application` resource.

Bootstrap the named provider principal before planning these application
ownership changes. Review the ownership transition for additions only; stop if
any existing owner would be removed or an application replaced. Do not change
application IDs, secrets, signing keys, callbacks or user accounts merely to
switch the provider identity.

## Bootstrap and activation

1. Generate the explicit stack and validate the operator module. Use the
   existing authenticated human Azure CLI and AWS sessions. Do not export
   desired-state inputs or add secrets to HCL.
2. Plan the operator unit into an encrypted file outside Git, inspect its JSON
   privately, and run Conftest. A first bootstrap adds only the two applications,
   their two service principals, two exact federation trusts and seven grants.
   Reject unrelated updates, deletion, client credentials, licenses or directory
   roles. If an application was manually bootstrapped, verify its identity and
   import it before planning; do not create a duplicate.
3. Merge signed, reviewed code before applying the saved plan through the
   operator unit. Then review and apply each application's ownership transition
   from the same merged tree. Retain the human administrator and existing state.
4. Ensure both GitHub environments have their declared reviewer protection with
   administrator bypass disabled. Production must allow only protected branches.
   These settings belong to `Stuhlmuller/github-iac`, not a duplicate homelab
   resource. Use that repository's documented environment-only saved-plan path
   to reconcile drift before activating federation.
5. Run `nix develop --command python3 -I scripts/entra-ci-configure.py`
   for a dry run; repeat with `--execute` from clean, signed current `main`.
   It checks protection and copies only client and
   tenant selectors from sensitive Terraform outputs into the two environments.
   Selectors are stored as GitHub secrets to keep their values out of logs;
   they are not authentication secrets. No client secret is published.
6. Dispatch `Entra OIDC Verify` on `main` with its exact current SHA. Approve
   each protected environment after checking that revision. It verifies both
   provider identities by refreshing and planning all four existing Entra
   units; any error or proposed change fails. It never applies or advances the
   full infrastructure checkpoint. A successful operator plan does not prove
   GitHub federation works.

Example operator plan, using private files and the repository Nix shell:

```sh
nix develop
umask 077
cd IaC
terragrunt stack generate
cd operator/azuread-ci-identities
terragrunt init -reconfigure
terragrunt plan -out=/tmp/entra-ci-bootstrap.plan
terragrunt show -json /tmp/entra-ci-bootstrap.plan > /tmp/entra-ci-bootstrap-plan.json
conftest test --policy ../../../policy /tmp/entra-ci-bootstrap-plan.json
# Apply only the reviewed saved plan after protected merge.
terragrunt apply /tmp/entra-ci-bootstrap.plan
```

Do not paste plan output, identity identifiers or authentication tokens into
public PRs or logs. Keep live acceptance details in a private operator report.

## Recovery and limits

Retain the existing human operator login. A federation or CI permission failure
does not require recreating applications, resetting family passwords or changing
Fleet authentication. Correct trust or permissions through the operator unit and
repeat the actual CI check. Client and tenant selector publication is idempotent;
never print their values to diagnose a mismatch.

Removing a federation trust blocks new token exchanges; it does not instantly
revoke already issued access tokens. Review that change in the operator unit
and retain the declared human owner. Application/service-principal destruction
is guarded by `prevent_destroy` and is not routine rollback.

An Entra-only verification does not advance the full homelab apply checkpoint.
The outstanding full infrastructure range still needs its own reviewed plan and
successful full apply. Native Mac Platform SSO, password sync and offline login
remain separate acceptance tests in the [Fleet runbook](../clusters/homelab/apps/fleet/FREE-ENTRA.md).

References:

- [AzureAD provider OIDC](https://github.com/hashicorp/terraform-provider-azuread/blob/v3.9.0/docs/guides/service_principal_oidc.md)
- [MSGraph provider authentication](https://github.com/microsoft/terraform-provider-msgraph/blob/v0.5.0/docs/index.md)
- [Graph claims-policy read permissions](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list-claimsmappingpolicies?view=graph-rest-1.0)
- [Graph permission-grant warning](https://learn.microsoft.com/en-us/graph/permissions-reference#approleassignmentreadwriteall)
- [OpenTofu override files](https://opentofu.org/docs/language/files/override/)
