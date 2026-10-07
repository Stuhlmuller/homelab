# Existing Entra owner mail

This operator-only module owns one Graph `PATCH` body: `mail` on the existing
external MicrosoftAccount owner. It does not manage an `azuread_user`, import
that account, reset redemption, or write UPN, identities, password, MFA, roles,
grants, `otherMails`, or `proxyAddresses`. Private baseline guards require the
same enabled, accepted external member with UPN `rodman@stinkyboi.com` before
the write and after its readback. A failed postcondition does not undo the write.

## Private input contract

Copy `private.tfvars.json.example` to an absolute path outside the checkout in
a directory with mode `0700`; keep the completed file mode `0600`. Populate it
from fresh read-only Graph evidence and the privately confirmed reachable
replacement mailbox. Keep the complete existing identities collection,
including the null MicrosoftAccount issuer-assigned ID. Never commit the filled
file, put its values in Terragrunt inputs or environment variables, or include
them in public plans, wiki pages, run metadata or review comments. The template
is deliberately invalid until completed.

Only the private `-var-file` supplies owner object ID, baseline identities and
replacement mail. The shared root provides the existing S3 backend and KMS
inputs; both OpenTofu state and saved plans enforce AES-GCM encryption with
that AWS KMS key. The entire PATCH body is marked sensitive. Plan JSON and
provider diagnostics can still contain private data: keep all plan/show/apply
output in the private directory, with provider debug logging disabled.

## Focused operator review

First complete the application identity-dependency migration and owner access
checks in the [Fleet runbook](../../../clusters/homelab/apps/fleet/FREE-ENTRA.md).
Use the existing approved administrator sessions; ordinary CI must not plan or
apply this operator unit. Generate the unit from `IaC/terragrunt.stack.hcl`, run
backend-disabled `init` and `validate`, then initialize its normal remote state.

Use `plan -input=false -var-file=/absolute/private/owner.tfvars.json` with an
encrypted `-out=/absolute/private/owner.tfplan`. Review the saved JSON privately:
exactly one managed action for `msgraph_update_resource.mail` (initial `create`
means a PATCH of an existing user, later actions are `update` or `no-op`), exact
reviewed `users/<owner-object-id>` URL, `v1.0`, `PATCH`, and a body containing only
the reviewed `mail`. Reject deletes, replacements, imports, unknown body values,
or any other managed resource. Refresh the identity baseline before applying
those same saved bytes; a saved plan cannot detect later out-of-band changes.

After apply, privately read the actual mail, proxies, identities, UPN, ID,
enabled state, roles and grants. Verify fresh owner authentication, MFA and
application access resolve the original owner object. **Stop if the original
SMTP alias remains.** Graph mail updates trigger proxy recalculation but do not
guarantee alias removal. This module does not retry, patch proxies, reset
redemption or start the pilot rename. Those require a separately reviewed,
supported operation. No state operation proves successful sign-in.

Rollback is another reviewed mail-only plan with the prior mailbox while its
address remains available. After the pilot claims the old address, release it
from that pilot through its declared path before attempting owner rollback.
Deleting `msgraph_update_resource` performs no Graph undo; `prevent_destroy`
guards accidental state removal, but removing its configuration also removes
that guard. Do not delete the module or unit as a rollback.

Run the synthetic plan-only regression with `tofu test -no-color` after
backend-disabled initialization. It mocks Graph and checks the sensitive PATCH
scope plus refusal when owner ID or identity differs. It does not test live
Graph recalculation or human authentication.

References: [Graph user updates](https://learn.microsoft.com/en-us/graph/api/user-update?view=graph-rest-1.0),
[mail/proxy behavior](https://learn.microsoft.com/en-us/graph/api/resources/user?view=graph-rest-1.0#mail-and-proxyaddresses-properties),
[provider PATCH and deletion semantics](https://github.com/microsoft/terraform-provider-msgraph/blob/v0.5.0/docs/resources/update_resource.md).
