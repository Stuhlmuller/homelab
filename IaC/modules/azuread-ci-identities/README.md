# Entra identities for GitHub Actions

The operator unit at `IaC/operator/azuread-ci-identities` owns two secretless,
single-tenant application registrations, their service principals, exact GitHub
federated credentials, requested Microsoft Graph permissions, and actual
permission grants. It uses the shared encrypted S3 state and KMS configuration.
The state key is
`IaC/homelab/operator/azuread-ci-identities/terraform.tfstate`.
Its committed unit source is
`IaC/.catalog/units/operator/azuread-ci-identities/terragrunt.hcl`;
`IaC/terragrunt.stack.hcl` generates the ignored operator directory.

| Application | Protected GitHub environment | Graph application permissions |
| --- | --- | --- |
| `homelab-terraform-plan` | `homelab-plan` | `Application.Read.All`, `User.Read.All`, `Policy.Read.All` |
| `homelab-terraform-apply` | `homelab-production` | The same reads plus `Application.ReadWrite.OwnedBy` |

Each credential trusts only
`repo:Stuhlmuller/homelab:environment:<its environment>`, issuer
`https://token.actions.githubusercontent.com`, and audience
`api://AzureADTokenExchange`. Neither application has a client secret, delegated
permission, Azure RBAC assignment, directory role, or license. Workload identity
federation is available in [Entra Workload ID Free](https://learn.microsoft.com/en-us/azure/active-directory/workload-identities/workload-identities-faqs).

The existing human tenant owner remains the sole owner of these two application
registrations and service principals. The unit resolves that owner by immutable
object ID, so a supported UPN conversion does not transfer ownership. A
precondition rejects another caller.
CI must not own either CI identity or traverse this operator unit. Applications
and service principals have `prevent_destroy`; deliberate retirement needs a
reviewed code change.

## Permission boundary

The apply identity can create applications and update applications/service
principals it owns. Ownership of Fleet, Grafana, and Octelium must be declared
in their respective units while preserving the human owner. Ownership must not
depend on whichever principal happens to run a plan. The apply identity has no
permission to change users, application-configuration policies, or application
permission grants. Those changes remain operator-executed Terraform operations
using the same workload states. Do not grant broad permissions merely to clear
a failing CI plan or apply.

Fleet's claims-policy assignment has a specific verification gate: the pinned
AzureAD provider refreshes it with a Graph list call whose documented minimum
includes `Application.ReadWrite.OwnedBy`, even though it is a read. The plan
identity intentionally has only reads. Test the real protected plan; a denied
refresh is an unresolved permission boundary, not permission to add write
access or skip refresh. [Microsoft Graph requirements](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list-claimsmappingpolicies?view=graph-rest-1.0)

## Bootstrap and verification

Run from a reviewed checkout using the existing tenant owner's Azure CLI
session and the existing AWS operator credentials. No manually created Entra
application is necessary when that session can create applications. Inspect
matching display names before the first plan; if one already exists, import
that exact object into the declared address rather than making a duplicate.

From the unit directory, validate without a backend first:

```sh
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
```

Then initialize the normal shared backend, save a private encrypted plan,
review its resource addresses and permission grants, and apply only those
reviewed bytes:

```sh
umask 077
ci_identity_plan_dir="$(mktemp -d /tmp/homelab-entra-ci.XXXXXX)"
terragrunt --log-disable init -reconfigure -no-color
terragrunt --log-disable plan -input=false -lock-timeout=5m \
  -out="$ci_identity_plan_dir/identities.tfplan" -no-color
terragrunt --log-disable show -no-color "$ci_identity_plan_dir/identities.tfplan"
terragrunt --log-disable apply -no-color "$ci_identity_plan_dir/identities.tfplan"
```

For a fresh bootstrap, expect 13 creates: two applications, two service
principals, two federated credentials, and seven Graph permission assignments.
Existing applications, users, policies, credentials, and licenses must not
change. A follow-up plan must be empty. Read back both applications' owners,
credentials, and effective Graph assignments; the requested-permissions list
alone does not prove admin consent.

Configure the corresponding protected GitHub environment with `AZUREAD_CLIENT_ID`
and `AZUREAD_TENANT_ID` from the sensitive outputs without printing them in job
logs. Both providers use `ARM_CLIENT_ID`, `ARM_TENANT_ID`, `ARM_USE_OIDC=true`,
`ARM_USE_CLI=false`, and `ARM_USE_MSI=false`; omit `ARM_CLIENT_SECRET`. The job
needs `id-token: write` and an exact matching `environment`. The providers obtain
the GitHub token directly. Verify authentication in both environments and read
back the exact federation subjects. Record an actual unauthorized-subject
exchange separately if tested; successful authorized login alone does not
prove that negative test.
[AzureAD authentication](https://raw.githubusercontent.com/hashicorp/terraform-provider-azuread/v3.9.0/docs/guides/service_principal_oidc.md),
[MSGraph authentication](https://raw.githubusercontent.com/microsoft/terraform-provider-msgraph/v0.5.0/docs/index.md).

Rollback through a reviewed operator plan that removes the affected federated
credential or permission grant. Preserve application identities and state;
do not delete accounts, regenerate credentials, or widen trust to recover CI.
