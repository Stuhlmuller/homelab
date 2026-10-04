# Verified-domain Entra family device user

Creates one cloud-only Entra user with an internal organizational password.
It does not invite or convert an external identity, change the tenant owner,
assign directory roles, join groups, grant Fleet-console access, or assign a
license. `required_verified_domain` must equal the UPN suffix; the module reads
that exact tenant domain and rejects user creation unless it is verified,
managed, non-default and non-initial. This guard makes no domain, federation,
DNS or Google Workspace change.

The 40-character initial password requires replacement at first sign-in.
Subsequent applies ignore the password and first-login flag so the user's
permanent password is not reset. Never taint or replace the password resource
to reset an account: its output would no longer describe the user's credential.
The user resource prevents destruction; account retirement needs a separate
review after confirming device and FileVault recovery access.

This module is for focused `IaC/operator` units only. It must not be used by
the normal AzureAD application collection, whose deployment credential lacks
tenant-wide user-write permission.

State and saved plans require the existing root AWS KMS encryption. Sensitive
outputs are for private, mode-0600 local handoff only: `sensitive` suppresses
normal output but does not redact `output -json` or `output -raw`. Do not print
them in CI, chat, PRs, logs or the repository. The stored bootstrap password is
stale after first sign-in and is not a recovery credential.

Validate before a reviewed plan/apply:

```sh
cd IaC/operator/entra-stuhlmuller-pilot-user
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable validate -no-color
```

The [AzureAD 3.9.0 user resource](https://github.com/hashicorp/terraform-provider-azuread/blob/v3.9.0/docs/resources/user.md)
requires `User.ReadWrite.All` or `Directory.ReadWrite.All` for service-principal
authentication, or User Administrator/Global Administrator for an interactive
principal. Existing application-registration permissions alone are insufficient;
do not grant broader permissions automatically to repair an apply failure.
Entra Free includes cloud user management and known-password changes; creating
this identity does not provide a paid service or mailbox. See the
[Fleet Free runbook](../../../clusters/homelab/apps/fleet/FREE-ENTRA.md) for the
interactive first-login and native Platform SSO acceptance checks.
