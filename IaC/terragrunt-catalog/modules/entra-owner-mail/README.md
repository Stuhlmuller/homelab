# Retired Entra owner-mail migration

This temporary operator unit retires the historic mail-only Graph PATCH. The
PATCH cannot release the owner's SMTP alias, so it must not run again.

The `removed` block has `destroy = false`: a reviewed apply forgets only
`msgraph_update_resource.mail` from the encrypted Terraform state and makes no
Graph mutation. Retain this unit until that apply has completed. Reject a plan
that proposes any provider action other than removing the retired state address.

This unit accepts no private owner-mail input. The supported owner conversion
uses the Entra admin center and preserves the immutable user object ID relied on
by the other Terraform units.
