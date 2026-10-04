# Entra SAML enterprise application

Creates a single-tenant SAML application, enterprise service principal,
Microsoft-generated signing certificate, and individual user assignments.
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
credentials. The applying identity owns both the application and service
principal; changing that identity may change ownership, so review the plan.
The operator needs permission to manage applications, create token-signing
certificates, read the individually assigned users, and assign application roles.
A successful plan does not establish permission for those write operations.

Entra's default SAML NameID uses the user's UPN. Precreate the exact UPN in
Fleet with SSO enabled and verify the actual SAML login before retiring any
recovery access. This module does not grant a Fleet role or provision a Fleet
user. The Fleet console is separate from the Mac's native Microsoft Platform
SSO extension.

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
