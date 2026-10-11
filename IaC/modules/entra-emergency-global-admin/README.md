# Entra emergency Global Administrator

Declares one permanent, cloud-only emergency Entra account at
`homelab-emergency-admin@<tenant>.onmicrosoft.com` and assigns the built-in
Global Administrator role. It is the independent recovery path before converting
the existing external owner to `rodman@stuhlmuller.net`.

The module reads the tenant's single initial domain and rejects anything except a
verified, managed `.onmicrosoft.com` domain. It creates no mailbox, license,
group, Fleet account, application, Conditional Access rule, PIM assignment, or
Intune enrollment. Both the user and role assignment have `prevent_destroy`; the
cloud-only password does not expire.

It is used only by the focused operator unit. Its literal
`local.emergency_global_admin_enabled = false` excludes both direct and
run --all apply/destroy operations. It is source-controlled, so no CLI feature
override can enable it. After explicit authorization, a separate signed,
reviewed change may set that literal to `true`; then apply only a reviewed saved
plan containing the random password, user, and Global Administrator assignment
creates. After an independent login succeeds, restore the literal to `false` in
another signed change without changing the protected resources.

The bootstrap password is stored in KMS-encrypted state and saved plans. Treat
both outputs as private: hand them off through a mode-0600 file outside a Git
repository, replace the password at first sign-in, register the required security
information, and prove a fresh independent administrator login before converting
the existing owner. The private conversion receipt then requires Azure CLI to be
authenticated as this exact account and read-validates its direct, tenant-root
Global Administrator assignment. The read needs the documented delegated
`RoleManagement.Read.Directory` permission (or `Directory.Read.All`); it never
requests a Graph write permission. Do not print outputs in CI, chat, PRs, or logs.

Validate before planning:

```sh
cd IaC
terragrunt stack generate
cd operator/entra-emergency-global-admin
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
```

Before the first apply, use a separate signed, reviewed change to set
`local.emergency_global_admin_enabled` to `true`. Build the initial private saved
plan from that merged tree, then run its JSON allowlist before applying the exact
plan bytes. The checker accepts only the random password, cloud-only user and
Global Administrator assignment creates; it rejects later reconciliations.

```sh
plan_dir="$(mktemp -d)"
chmod 0700 "$plan_dir"
trap 'rm -rf "$plan_dir"' EXIT
plan="$plan_dir/entra-emergency-global-admin.tfplan"
plan_json="$plan_dir/entra-emergency-global-admin.json"

terragrunt --log-disable init -reconfigure -no-color
terragrunt --log-disable plan -input=false -lock-timeout=5m -out="$plan" -no-color
terragrunt --log-disable show -json "$plan" > "$plan_json"
python3 -I ../../../scripts/verify-entra-emergency-global-admin-plan.py "$plan_json"
terragrunt --log-disable apply -no-color "$plan"
```

The [AzureAD 3.9.0 directory role assignment resource](https://github.com/hashicorp/terraform-provider-azuread/blob/v3.9.0/docs/resources/directory_role_assignment.md)
requires a Global Administrator or Privileged Role Administrator for an
interactive operator. Do not grant that permission to CI. Microsoft documents
cloud-only emergency accounts and permanent Global Administrator assignment as
the recovery pattern; this active assignment does not use PIM or a paid license.
