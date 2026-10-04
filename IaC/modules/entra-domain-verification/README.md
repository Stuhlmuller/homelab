# Entra custom-domain verification

This operator-only module reads the existing `stuhlmuller.net` Entra domain,
reads its Microsoft-generated TXT verification record, and performs the Graph
verification action only after a separate DNS-owned change publishes that exact
record. It cannot create, delete, federate, or make a domain default.

AzureAD 3.9.0 has no domain resource, so the module uses the generic MSGraph
**data source** for the existing domain. With `verify_domain = false`, it makes
only Graph GET requests; it has no managed resource or state adoption.

The module requires the existing domain to remain `Managed`, non-default, and
non-initial. `forceTakeover` is always false. It neither configures Microsoft
365 mail services nor changes Google Workspace, MX, SPF, DKIM, DMARC, Google
SSO, existing Google accounts, or Entra accounts other than the separately
declared pilot user.

## Two-stage operator rollout

The committed catalog input starts with `verify_domain = false`. From reviewed,
signed `main`, use an Entra Domain Name Administrator or higher and the normal
AWS backend credentials:

```sh
cd IaC
terragrunt stack generate
cd operator/entra-stuhlmuller-domain
terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color

umask 077
domain_plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-entra-domain.XXXXXX")"
trap 'rm -rf -- "$domain_plan_dir"' EXIT
terragrunt --log-disable init -reconfigure -lockfile=readonly -no-color
terragrunt --log-disable plan -input=false -lock-timeout=5m \
  -out="$domain_plan_dir/read.tfplan" -no-color
terragrunt --log-disable show -json "$domain_plan_dir/read.tfplan" >"$domain_plan_dir/read.json"
jq -e '[.resource_changes[]? | select(.mode == "managed")] | length == 0' "$domain_plan_dir/read.json"
jq -r '.planned_values.outputs.verification_txt_record.value |
  "type=TXT name=\(.name) value=\(.value) ttl=\(.ttl)"' "$domain_plan_dir/read.json"
```

The first plan must contain no managed-resource actions, and it must not be
applied. The returned value is scoped to this domain and is the source of truth
for one apex TXT record; preserve every existing TXT record, including SPF, and
all Google MX/service records.

`stuhlmuller.net` DNS is not currently owned by a repository Terraform unit.
Add the returned TXT through the DNS owner's reviewed declarative workflow;
do not use a web-console workaround. Once both authoritative nameservers return
the exact value, commit `verify_domain = true`, repeat the protected review and
operator saved-plan process. Review a plan containing only the one
`msgraph_resource_action.verify` create and its reads, then apply those exact
saved bytes and confirm `domain_status.verified` is true. Keep
`verify_domain = true` afterward: the action has `prevent_destroy` so its state
cannot be dropped and accidentally replayed. That Graph action does not
configure Microsoft 365 mail services.

Only after verification succeeds may the separate
`operator/entra-stuhlmuller-pilot-user` unit create the one cloud-only pilot.
Its guard rejects an absent, unverified, federated, default, or initial UPN
domain. This keeps all existing Google and Entra users outside the pilot.

References: [Microsoft Graph verification records](https://learn.microsoft.com/en-us/graph/api/domain-list-verificationdnsrecords?view=graph-rest-1.0), [verify action](https://learn.microsoft.com/en-us/graph/api/domain-verify?view=graph-rest-1.0), and [MSGraph resource data](https://github.com/microsoft/terraform-provider-msgraph/blob/v0.5.0/docs/data-sources/resource.md).
