# Entra SAML enterprise application

Creates a single-tenant SAML application, enterprise service principal,
Microsoft-generated signing certificate, explicit NameID mapping, and individual
user assignments.
No client password, Graph permission grant, group assignment, Conditional
Access policy, Intune enrollment, subscription, or purchased license is created.

The AzureAD provider owns the application and certificate. Microsoft's
`msgraph_update_resource` owns only `preferredTokenSigningKeyThumbprint`, which
the AzureAD provider cannot set. It reads that property back on refresh so a
different active certificate produces a plan. Removing the update resource
alone does not reset the property; change it explicitly before removing that
resource. No local-exec or imperative Graph patch is involved.

The existing root S3 backend and AWS KMS state/plan encryption protect state.
Outputs are sensitive to keep tenant/app identifiers and metadata URLs out of
ordinary CLI output. `output -json` and saved plan JSON still disclose sensitive
values; capture them privately and never commit them or raw certificates.

The Fleet operator reads `metadata_url`, `tenant_id`, `client_id`,
`signing_certificate_thumbprint`, and `signing_certificate_expires_at` directly
from these sensitive runtime outputs. Before changing Fleet SSO, it checks the
app-specific URL, tenant, future certificate expiry, and an exact DER certificate
fingerprint match in the IdP signing metadata. SHA-1 identifies Microsoft's
selected certificate here; it does not verify a SAML message signature.

For Fleet, generate the explicit stack and use only
`IaC/live/azuread-applications/fleet` for init, validation, plan, and the reviewed
apply. Providers reuse existing Azure CLI login locally or CI-injected identity
credentials. Explicit human and automation owners apply to both the application
and service principal; human owners and assignments resolve by immutable object
ID so a supported UPN conversion does not replace them. The assignment map keys
remain stable Terraform addresses and are not sign-in names. Switching the
Terraform login does not replace the owners.
Bootstrap the named automation principal through the operator-owned identity
unit before planning this unit. Keep the human owner during the transition.
The operator needs permission to manage applications, create token-signing
certificates, read the individually assigned users, and assign application roles.
A successful plan does not establish permission for those write operations.

The first Fleet browser test returned `account_disabled`: the external
Microsoft-account owner's signed NameID matched the password-only recovery user
instead of the precreated organizational UPN. Fleet 4.92.2 resolves NameID by
account email, then rejects users with SSO disabled. Do not fix that collision by
converting the recovery user to SSO.

The dedicated service principal now owns an explicit claims mapping policy:
`Source=user`, `ID=userprincipalname`, and the standard SAML `nameidentifier`
claim URI. This is Microsoft's documented Graph v1.0 mapping. Basic claims are
retained. The policy overrides default claim configuration and uses the existing
app-specific signing key; it does not enable `acceptMappedClaims`, issue a shared
constant identity, or modify the owner's user object. Microsoft's UI documents
`user.localuserprincipalname` for B2B users, but that ID is absent from the stable
claims-mapping source reference, so this module does not assume API support.
Verify the actual callback resolves the precreated UPN after apply; configuration
and metadata checks alone do not establish that the collision is fixed.

[Entra Free](https://www.microsoft.com/en-us/security/business/microsoft-entra-pricing)
includes unlimited SaaS SSO. Microsoft's claims customization and Graph API
references list permissions, not an additional P1/P2 requirement, for this basic
SAML mapping. A service principal applying the policy needs
`Policy.ReadWrite.ApplicationConfiguration` and `Policy.Read.All`; an interactive
principal needs Application Administrator or Global Administrator. The module
does not grant these permissions. Stop on a license error without adding a paid
license or trial. This is not a custom claims provider/authentication extension.

Precreate the exact intended NameID in Fleet with SSO enabled and verify actual
SAML login before retiring any recovery access. This module does not grant a
Fleet role or provision a Fleet user. The console remains separate from the
Mac's native Microsoft Platform SSO extension. Removing the policy assignment
restores default claims and can reproduce the collision; retain recovery access
and verify a fresh callback when changing or rolling back the mapping.

Certificate expiry is a reviewed input, not a perpetual timestamp expression.
Before expiry, change the date in a PR, review replacement, and apply. The new
certificate is created before the old one is destroyed; the Graph resource
selects its thumbprint. Verify metadata, fresh SAML login, and an empty follow-up
plan. This replacement removes the previous certificate during apply: retain
working recovery access until a fresh SAML login is accepted. An already
destroyed certificate cannot be restored by reverting the old expiry; recovery
requires another certificate replacement. Disabling Fleet SSO does not remove
the Entra application.

References:

- [Fleet SAML configuration](https://fleetdm.com/docs/deploy/single-sign-on-sso)
- [AzureAD token-signing certificate resource](https://registry.terraform.io/providers/hashicorp/azuread/3.9.0/docs/resources/service_principal_token_signing_certificate)
- [Microsoft Graph update resource](https://github.com/microsoft/terraform-provider-msgraph/blob/v0.5.0/docs/resources/update_resource.md)
- [Microsoft Graph SAML signing-key activation](https://learn.microsoft.com/en-us/graph/application-saml-sso-configure-api#activate-the-custom-signing-key)
- [Microsoft Graph service principal](https://learn.microsoft.com/en-us/graph/api/resources/serviceprincipal?view=graph-rest-1.0)
- [Microsoft Graph v1.0 NameID mapping example](https://learn.microsoft.com/en-us/graph/api/claimsmappingpolicy-post-claimsmappingpolicies?view=graph-rest-1.0)
- [Claims-mapping sources, precedence and restrictions](https://learn.microsoft.com/en-us/entra/identity-platform/reference-claims-customization)
- [B2B UPN behavior](https://learn.microsoft.com/en-us/entra/external-id/claims-mapping)
- [AzureAD claims-mapping policy](https://github.com/hashicorp/terraform-provider-azuread/blob/v3.9.0/docs/resources/claims_mapping_policy.md)
- [AzureAD policy assignment](https://github.com/hashicorp/terraform-provider-azuread/blob/v3.9.0/docs/resources/service_principal_claims_mapping_policy_assignment.md)
- [Fleet 4.92.2 NameID lookup and SSO-disabled rejection](https://github.com/fleetdm/fleet/blob/fleet-v4.92.2/server/service/sessions.go#L794)
