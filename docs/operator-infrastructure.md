# Operator-owned infrastructure

`IaC/homelab/us-west-2/operator` contains declarative prerequisites that require focused operator
review, including automation identity permissions and recovery storage. These
units use the shared remote state and repository modules, but the GitHub
plan/apply workflows do not traverse this directory.

Run an operator unit only with a reviewed administrator session, after its
format, validation, and plan checks pass. This separation prevents a compromised
workflow from widening the permissions of its own AWS role while keeping the
bootstrap policy reproducible and reviewable.

## Entra CI provider identities

`azuread-ci-identities` declares separate GitHub OIDC identities for protected
plans and production applies, including federation and Microsoft Graph grants.
Use the existing human Azure CLI operator to bootstrap this unit; CI must not
traverse it or own either provider application. No client secret or paid license
is needed. Follow the [provider runbook](entra-terraform-provider.md)
for encrypted plans, stable application ownership, environment protection,
credential-selector publication and real CI acceptance.

## Entra `stuhlmuller.net` pilot

`entra-owner-mail` is a state-only retirement unit for the failed mail-only
Graph PATCH. It accepts no private inputs and must not call Graph. The patch
cannot release the owner's SMTP alias, so it is not a route to the required
UPN and must not be restored.

`entra-stuhlmuller-domain` reads the existing Entra domain through the Microsoft
Graph provider, reads the Microsoft-generated TXT verification record, and
verifies it only after the DNS owner has published that record. It is
intentionally an operator unit: verification requires tenant-wide domain
authority that the CI identities must not receive.

The unit requires a managed, non-default and non-initial domain and sends the
standard bodyless Graph verification request, which defaults to
`forceTakeover = false`. It cannot create, delete, federate, make a default
domain, configure Microsoft 365 mail services, or change Google Workspace.
The companion `entra-stuhlmuller-pilot-user` unit retains only the isolated
`rodman.mac@stuhlmuller.net` cloud user, with no group, role, license,
Fleet-console assignment, mailbox, or effect on other accounts. It must not
create or rename `rodman@stuhlmuller.net`.

`entra-emergency-global-admin` declares one cloud-only
`homelab-emergency-admin@<tenant>.onmicrosoft.com` recovery account and its
permanent Global Administrator assignment. Its source-controlled
`emergency_global_admin_enabled` literal defaults to false, so direct and
run --all apply/destroy commands exclude it. A separate signed, reviewed change
may set it true after explicit authorization; its reviewed plan must create only
the user, bootstrap password, and assignment. Test a fresh login, then restore
the literal to false without changing the protected resources before conversion.

The exact target is the existing external owner converted in place to an
internal Entra user through the supported Entra admin-center flow. Terraform
first changes all ownership and Fleet-assignment lookups to immutable object IDs
so the conversion keeps ownership and grants. Create and test an independent
cloud-only Global Administrator before converting the sole owner. The only
permitted portal action is bounded by the private, Graph-read-only
[`entra-owner-conversion.py`](../scripts/entra-owner-conversion.py)
prepare/attest transaction; it does not automate the conversion. The complete
order, Fleet local-recovery migration, and live acceptance checks are in the
[Fleet Free runbook](../clusters/homelab/apps/fleet/FREE-ENTRA.md). No
support case, Exchange license, or alias workaround is required.

## Etcd Offsite Backup Storage

`etcd-backup-storage` owns a dedicated private, versioned S3 bucket in
`us-east-1` using the existing account and AWS-managed S3 encryption key. Its
only lifecycle cleanup removes incomplete multipart uploads after seven days;
completed backup versions have no automatic expiration. No CI permissions
change. Follow the [focused saved-plan workflow](etcd-offsite-storage.md)
with an existing administrator session. Generic CI validates this unit offline
but does not live-plan or apply it. Bucket creation does not publish snapshots
or prove offsite recovery; those verification steps remain separate.

## GitHub Actions apply-role policy

`github-actions-role-policy` owns the existing `Github-TF-State` role trust and
attaches one managed policy. Trust is limited to the protected plan and
production environments in `Stuhlmuller/homelab` and
`Stuhlmuller/github-iac`.
The managed permission grant is limited to the ten exact managed-policy slots
`homelab-ssm-parameter-reader-00` through `-09` and attachments to the exact
`homelab-ssm-parameter-readers` group, plus `kms:DescribeKey` on the resolved
current runtime-secret key. This metadata-only grant adds no cryptographic or
key-administration actions. The role cannot manage this bootstrap
policy, its own attachment, or another role.

The same operator unit declares a dedicated `homelab-langfuse-raw-inventory`
OIDC role trusted only by `Stuhlmuller/homelab` jobs in the
`homelab-production` environment. That environment's main-only branch policy
and the inventory workflow's exact-main guard are required because the OIDC
environment subject itself does not identify a branch. The unprotected
`homelab-plan` environment and companion `github-iac` repository cannot assume
this role. Its inline policy grants bucket versioning and encryption
inspection, version listing, and exact-version reads only for the bucket named
in `IaC/langfuse-blob-storage.hcl`. KMS decrypt is limited to the regional
S3 key resolved from `alias/aws/s3`, called through S3 with that bucket's
encryption context. The bucket-owner precondition rejects a mismatched account
or region. This source change grants no live permission until an administrator
reviews and applies a saved plan for the operator unit. The trust-only rollout
below targets only the shared `Github-TF-State` role and does not create this
inventory role. Historical objects encrypted with a different key or context
require a separately reviewed grant before the protected inventory can pass.

For this dedicated role, generate the stack and validate the operator unit as
described below, then use an administrator profile for a private, un-targeted
saved plan from `IaC/homelab/us-west-2/operator/github-actions-role-policy`.
The managed changes must be exactly these two creates, with no drift, import,
or moved address. The generic PR Terragrunt plan does not include this unit.
Keep the plan and JSON private; review the full saved plan and apply those same
bytes only after this source is merged to `main`:

```sh
cd IaC
terragrunt stack generate
cd homelab/us-west-2/operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
terragrunt --log-disable run --no-auto-init -- test -no-color
operator_profile="<administrator-profile>"
AWS_PROFILE="$operator_profile" terragrunt --log-disable init -reconfigure -no-color
umask 077
inventory_plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/langfuse-inventory-role.XXXXXX")"
trap 'rm -rf -- "$inventory_plan_dir"' EXIT
AWS_PROFILE="$operator_profile" terragrunt --log-disable plan -input=false \
  -lock-timeout=5m -out="$inventory_plan_dir/role.tfplan" -no-color \
  >"$inventory_plan_dir/plan.log" 2>&1
AWS_PROFILE="$operator_profile" terragrunt --log-disable show -json \
  "$inventory_plan_dir/role.tfplan" >"$inventory_plan_dir/plan.json"
jq -e '
  ([.resource_drift[]? | select(.change.actions != ["no-op"])] | length) == 0 and
  ([.resource_changes[]? |
    select(.previous_address != null or .change.importing != null)] | length) == 0 and
  ([.resource_changes[]? |
    select(.mode == "managed" and .change.actions != ["no-op"]) |
    {address, actions: .change.actions}] | sort_by(.address)) == [
      {address: "aws_iam_role.langfuse_raw_inventory", actions: ["create"]},
      {address: "aws_iam_role_policy.langfuse_raw_inventory", actions: ["create"]}
    ]
' "$inventory_plan_dir/plan.json"
AWS_PROFILE="$operator_profile" terragrunt --log-disable show -no-color \
  "$inventory_plan_dir/role.tfplan"
# After reviewing the full plan and verifying this source is on main:
AWS_PROFILE="$operator_profile" terragrunt --log-disable apply -no-color \
  "$inventory_plan_dir/role.tfplan"
```

After apply, check the dedicated role's trust and inline policy through IAM
read-only calls and require a fresh full-unit no-op plan before dispatching
the protected raw-version inventory. The inventory alone is not a complete
Langfuse backup.

The same unit adopts the existing `external-secrets_aws-ssm-auth` IAM user,
removes direct managed and inline user policies, and applies an operator-owned
permissions boundary. The boundary caps the user's effective permissions at
`GetParameter`/`GetParameters` under `/homelab/*` and decrypt/describe access
to the regional runtime-secret KMS key. An explicit deny blocks direct requests
made with temporary STS credentials, preventing a copied long-term key from
minting a session that survives rotation. AWS forward access sessions are exempt
from that deny so SSM can decrypt SecureStrings through KMS; the existing SSM
and exact KMS-key allow rules still constrain access. Group policy changes
therefore cannot turn the reader credential into unrelated AWS access.

Use an AWS administrator profile only as the credential selector. Before
changing trust, create and protect `github-iac-plan` and
`github-iac-production`, store the required secrets in those environments,
remove their repository-scoped copies, and merge the workflow jobs that name
the environments. Replacing the old pull-request and branch subjects before
that bootstrap temporarily disables the current `github-iac` plan and apply
jobs.

### Trust-only rollout

Validate without the remote backend, then initialize the operator state with
administrator credentials:

```sh
set -euo pipefail
operator_profile="<administrator-profile>"
aws sso login --profile "$operator_profile"
cd IaC/homelab/us-west-2/operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
AWS_PROFILE="$operator_profile" terragrunt --log-disable init -reconfigure -no-color
```

Run the remaining trust-only blocks in this same shell so the profile and
private temporary paths remain available.

The encrypted state key is
`IaC/homelab/operator/github-actions-role-policy/terraform.tfstate`. Import the
existing role only when its exact address is absent. Import changes state, not
the live IAM role; repeating it after the address exists is an error.

```sh
operator_plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-role-trust.XXXXXX")"
chmod 0700 "$operator_plan_dir"
operator_plan="$operator_plan_dir/github-actions-role-trust.tfplan"
operator_plan_json="$operator_plan_dir/github-actions-role-trust.json"
operator_state_list="$operator_plan_dir/operator-state-list.txt"

cleanup_operator_plan() {
  test ! -d "$operator_plan_dir" || rm -rf -- "$operator_plan_dir"
}
trap cleanup_operator_plan EXIT

AWS_PROFILE="$operator_profile" terragrunt --log-disable state list \
  >"$operator_state_list"
if ! grep -Fxq 'aws_iam_role.github_actions' "$operator_state_list"; then
  AWS_PROFILE="$operator_profile" terragrunt --log-disable import \
    -lock-timeout=5m 'aws_iam_role.github_actions' Github-TF-State
fi

AWS_PROFILE="$operator_profile" terragrunt --log-disable state show -no-color \
  'aws_iam_role.github_actions' >"$operator_plan_dir/role-state-before.txt"
grep -Eq '^[[:space:]]*id[[:space:]]*=[[:space:]]*"?Github-TF-State"?$' \
  "$operator_plan_dir/role-state-before.txt"
```

Save a plan for only the role. The JSON gate rejects creation, deletion,
replacement, imports, another managed resource, changes to non-trust role
attributes, a wildcard, or any subject outside the four protected
environments. Review the human-readable plan before approving the prompt and
applying those exact bytes.

```sh
AWS_PROFILE="$operator_profile" terragrunt --log-disable plan \
  -input=false -lock-timeout=5m \
  -target='aws_iam_role.github_actions' \
  -out="$operator_plan" -no-color
AWS_PROFILE="$operator_profile" terragrunt --log-disable show -json \
  "$operator_plan" >"$operator_plan_json"

jq -e '
  def as_array: if type == "array" then . else [.] end;
  [.resource_changes[] | select(.mode == "managed")] as $changes
  | ($changes | length) == 1
  and $changes[0].address == "aws_iam_role.github_actions"
  and ($changes[0].change.actions == ["no-op"] or
       $changes[0].change.actions == ["update"])
  and $changes[0].change.before.id == "Github-TF-State"
  and $changes[0].change.after.id == "Github-TF-State"
  and (($changes[0].change.importing // null) == null)
  and (($changes[0].previous_address // null) == null)
  and (($changes[0].change.before | del(.assume_role_policy)) ==
       ($changes[0].change.after | del(.assume_role_policy)))
  and (($changes[0].change.after.assume_role_policy | fromjson) as $policy
    | ($policy.Statement | as_array) as $statements
    | ($statements | length) == 1
    and $statements[0].Effect == "Allow"
    and ($statements[0].Action | as_array) == ["sts:AssumeRoleWithWebIdentity"]
    and ($statements[0].Principal | keys) == ["Federated"]
    and ($statements[0].Principal.Federated | as_array) == [
      ($changes[0].change.after.arn |
        sub(":role/.*$"; ":oidc-provider/token.actions.githubusercontent.com"))
    ]
    and ($statements[0].Condition | keys) == ["StringEquals"]
    and ($statements[0].Condition.StringEquals | keys | sort) == [
      "token.actions.githubusercontent.com:aud",
      "token.actions.githubusercontent.com:sub"
    ]
    and ($statements[0].Condition.StringEquals[
      "token.actions.githubusercontent.com:aud"] | as_array) ==
      ["sts.amazonaws.com"]
    and ($statements[0].Condition.StringEquals[
      "token.actions.githubusercontent.com:sub"] | as_array | sort) == ([
        "repo:Stuhlmuller/github-iac:environment:github-iac-plan",
        "repo:Stuhlmuller/github-iac:environment:github-iac-production",
        "repo:Stuhlmuller/homelab:environment:homelab-plan",
        "repo:Stuhlmuller/homelab:environment:homelab-production"
      ] | sort))
' "$operator_plan_json"

AWS_PROFILE="$operator_profile" terragrunt --log-disable show -no-color \
  "$operator_plan"
printf 'Apply this exact trust-only plan? Type apply: '
read -r operator_confirmation
test "$operator_confirmation" = apply
AWS_PROFILE="$operator_profile" terragrunt --log-disable apply -no-color \
  "$operator_plan"
```

Verify that live IAM has one allow statement, the required audience, and only
the four environment subjects:

```sh
aws --profile "$operator_profile" iam get-role \
  --role-name Github-TF-State \
  --output json >"$operator_plan_dir/live-role-trust.json"
jq -e '
  def as_array: if type == "array" then . else [.] end;
  .Role as $role
  | ($role.AssumeRolePolicyDocument.Statement | as_array) as $statements
  | ($statements | length) == 1
  and $statements[0].Effect == "Allow"
  and ($statements[0].Action | as_array) == ["sts:AssumeRoleWithWebIdentity"]
  and ($statements[0].Principal | keys) == ["Federated"]
  and ($statements[0].Principal.Federated | as_array) == [
    ($role.Arn |
      sub(":role/.*$"; ":oidc-provider/token.actions.githubusercontent.com"))
  ]
  and ($statements[0].Condition | keys) == ["StringEquals"]
  and ($statements[0].Condition.StringEquals | keys | sort) == [
    "token.actions.githubusercontent.com:aud",
    "token.actions.githubusercontent.com:sub"
  ]
  and ($statements[0].Condition.StringEquals[
    "token.actions.githubusercontent.com:aud"] | as_array) ==
    ["sts.amazonaws.com"]
  and ($statements[0].Condition.StringEquals[
    "token.actions.githubusercontent.com:sub"] | as_array | sort) == ([
      "repo:Stuhlmuller/github-iac:environment:github-iac-plan",
      "repo:Stuhlmuller/github-iac:environment:github-iac-production",
      "repo:Stuhlmuller/homelab:environment:homelab-plan",
      "repo:Stuhlmuller/homelab:environment:homelab-production"
    ] | sort)
' "$operator_plan_dir/live-role-trust.json"
```

Then verify approved plan and production jobs in both repositories can assume
the role. A job without one of these environments must receive
`AccessDenied`. Keep issue `#786` open until those live checks pass.

Rollback through code: create a reviewed forward commit restoring the prior
exact subjects, rerun this same targeted saved-plan path, and verify live IAM.
Do not update the trust policy with the AWS CLI, remove the imported state
address, or run a destroy. The prior `github-iac` pull-request and `main`
subjects are broader than the environment subjects, so use that rollback only
while repairing the protected workflows.

### Legacy archive session-duration rollout

The protected OpenClaw Enterprise legacy job can run for six hours. Its AWS
credential action requests a seven-hour web-identity session, leaving one hour
between the job timeout and credential expiry. The operator-owned
`Github-TF-State` role must allow the same 25,200-second maximum before retrying
`publish-archive`; the default one-hour role session expired during a large
multipart upload. The trust-only gate above deliberately rejects this different
role change. Other workflows keep their current session requests.

After the reviewed source merges, use an administrator session and this exact
role-only saved-plan path. Stop if the plan changes trust, another role
attribute, or any other managed resource. Keep plan files private; do not use
the GitHub Actions apply role to change its own maximum.

```sh
set -euo pipefail
operator_profile="<administrator-profile>"
aws sso login --profile "$operator_profile"
cd IaC
terragrunt stack generate
cd operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
terragrunt --log-disable run --no-auto-init -- test -no-color
AWS_PROFILE="$operator_profile" terragrunt --log-disable init -reconfigure -no-color

umask 077
duration_plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-role-duration.XXXXXX")"
trap 'rm -rf -- "$duration_plan_dir"' EXIT
AWS_PROFILE="$operator_profile" terragrunt --log-disable state list \
  >"$duration_plan_dir/state-list.txt"
grep -Fxq 'aws_iam_role.github_actions' "$duration_plan_dir/state-list.txt"
AWS_PROFILE="$operator_profile" terragrunt --log-disable plan -input=false \
  -lock-timeout=5m -target='aws_iam_role.github_actions' \
  -out="$duration_plan_dir/role.tfplan" -no-color \
  >"$duration_plan_dir/plan.log" 2>&1
AWS_PROFILE="$operator_profile" terragrunt --log-disable show -json \
  "$duration_plan_dir/role.tfplan" >"$duration_plan_dir/plan.json"

jq -e '
  [.resource_changes[]? | select(.mode == "managed" and .change.actions != ["no-op"])] as $changes
  | ($changes | length) == 1
  and $changes[0].address == "aws_iam_role.github_actions"
  and $changes[0].change.actions == ["update"]
  and $changes[0].change.before.id == "Github-TF-State"
  and $changes[0].change.after.id == "Github-TF-State"
  and $changes[0].change.before.max_session_duration == 3600
  and $changes[0].change.after.max_session_duration == 25200
  and (($changes[0].change.importing // null) == null)
  and (($changes[0].previous_address // null) == null)
  and (($changes[0].change.before | del(.max_session_duration)) ==
       ($changes[0].change.after | del(.max_session_duration)))
' "$duration_plan_dir/plan.json"

AWS_PROFILE="$operator_profile" terragrunt --log-disable show -no-color \
  "$duration_plan_dir/role.tfplan"
AWS_PROFILE="$operator_profile" terragrunt --log-disable apply -no-color \
  "$duration_plan_dir/role.tfplan"
test "$(aws --profile "$operator_profile" iam get-role \
  --role-name Github-TF-State --query Role.MaxSessionDuration --output text)" = 25200
```

The archived source and incomplete multipart upload remain untouched. Retry
the protected `publish-archive` stage with the same completed `archive_ref`, a
new workflow run ID, and fresh exact-main SHA only after the live IAM maximum
is verified. The backup bucket's declared lifecycle removes abandoned multipart
uploads; no manual S3 cleanup is part of this path.

### Full-unit reconciliation

Changes to the managed policy, attachment, External Secrets boundary, or IAM
user require an un-targeted operator plan. Import
`aws_iam_user.external_secrets` as `external-secrets_aws-ssm-auth` first only
when that address is absent, then review and apply the same full saved plan.
Do not use the trust-only target for those changes.

### Renovate App credential transfer and role retirement

The one-time transfer uses the temporary
`homelab-renovate-credential-transfer` role. Its OIDC trust accepts only
`Stuhlmuller/renovate` on `refs/heads/main`; that repository's active main
ruleset and the transfer workflow's exact-current-SHA check guard dispatch.
The companion repository has no protected GitHub environment. The role can
describe SSM parameter metadata to confirm both placeholders before writing;
AWS does not resource-scope `DescribeParameters`, so the workflow filters the
two exact names. It can only write the two declared
`/homelab/renovate/github-app/` SecureStrings and encrypt their values through
the current SSM KMS key. It has no `GetParameter`, decrypt, or IAM grant. The
companion workflow carries the role ARN directly
in reviewed source. Do not grant that repository the existing
`Github-TF-State` apply role. This module removes the temporary role after
the credential transfer; later rotation requires a reviewed reintroduction
with the same scope.

For a later rotation, restore the exact role and policy in a reviewed PR.
After that change merges, generate the stack, run backend-free validation and
`boundary.tftest.hcl`, then use an administrator profile for a private,
un-targeted saved plan. It must show exactly the transfer role and inline
policy being created; stop on unrelated changes. Review the private plan
before applying the saved bytes. Do not attach it to a public PR.

```sh
cd IaC
terragrunt stack generate
cd operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
terragrunt --log-disable run --no-auto-init -- test -no-color
operator_profile="<administrator-profile>"
AWS_PROFILE="$operator_profile" terragrunt --log-disable init -reconfigure -no-color
umask 077
transfer_plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/renovate-role-plan.XXXXXX")"
AWS_PROFILE="$operator_profile" terragrunt --log-disable plan -input=false \
  -lock-timeout=5m -out="$transfer_plan_dir/role.tfplan" -no-color \
  >"$transfer_plan_dir/plan.log" 2>&1
AWS_PROFILE="$operator_profile" terragrunt --log-disable show -json \
  "$transfer_plan_dir/role.tfplan" >"$transfer_plan_dir/plan.json"
jq -e '
  [.resource_changes[] | select(.mode == "managed" and .change.actions != ["no-op"])
   | {address, actions: .change.actions}] | sort_by(.address) == [
    {address: "aws_iam_role.renovate_transfer", actions: ["create"]},
    {address: "aws_iam_role_policy.renovate_transfer", actions: ["create"]}
  ]
' "$transfer_plan_dir/plan.json"
AWS_PROFILE="$operator_profile" terragrunt --log-disable show -no-color \
  "$transfer_plan_dir/role.tfplan"
AWS_PROFILE="$operator_profile" terragrunt --log-disable apply -no-color \
  "$transfer_plan_dir/role.tfplan"
```

First verify the SSM unit created both placeholders as `SecureString` under
`alias/aws/ssm` through its own reviewed apply. Then merge the companion
transfer workflow, dispatch it with the exact current `main` SHA, and verify
only SSM parameter versions and ExternalSecret readiness; never print values.
Before merging this retirement change, require both parameter versions to
advance beyond the placeholders, a later ExternalSecret refresh, and no
active Renovate Job. Keep the CronJob suspended until both projected keys are
ready and the transfer grant is gone.

On 2026-10-19, companion transfer run `39196912858` succeeded at reviewed
`main` commit `9e2a9f98931022317c3ee8dc0cf9997fadb53201`. Both declared
SecureStrings reached version 2. The `automation/renovate` ExternalSecret
refreshed afterward at 03:56:19 UTC with `Ready=True`, and its target Secret
resource version changed. The CronJob remained suspended with no Renovate Job.
These metadata checks establish the transfer gate; removing the role still
requires the exact saved-plan apply below.

For retirement, repeat backend-free validation and the private, un-targeted
saved-plan sequence above with this reviewed source. Replace the create gate
with an exact deletion gate:

```sh
jq -e '
  [.resource_changes[] | select(.mode == "managed" and .change.actions != ["no-op"])
   | {address, actions: .change.actions}] | sort_by(.address) == [
    {address: "aws_iam_role.renovate_transfer", actions: ["delete"]},
    {address: "aws_iam_role_policy.renovate_transfer", actions: ["delete"]}
  ]
' "$transfer_plan_dir/plan.json"
```

Stop on unrelated changes. Apply only the reviewed saved bytes, verify a
fresh full-unit no-op plan, then delete the private plan directory.

On 2026-10-19, after [#1390](https://github.com/Stuhlmuller/homelab/pull/1390)
merged, the operator applied a private, un-targeted saved plan whose only
managed-resource changes deleted `aws_iam_role.renovate_transfer` and
`aws_iam_role_policy.renovate_transfer`. The apply succeeded; a read-only IAM
role lookup returned `NoSuchEntity`, and a fresh full-unit plan reported no
changes. The [hourly Renovate CronJob](../clusters/homelab/apps/renovate/cronjob.yaml)
is now declared unsuspended in [full dry-run mode](../clusters/homelab/apps/renovate/config.js);
the legacy Action remains the only writer pending parity and cutover.

The September 29, 2026 Langfuse apply reached SSM refresh but failed because
the workflow role's KMS grant still named the former runtime key, not the
current `alias/aws/ssm` target. Reconcile the existing managed policy through
this administrator-owned unit; CI must not widen its own permissions. For this
correction, require a saved plan whose only managed-resource change is the
additional exact-key `kms:DescribeKey` statement in
`aws_iam_policy.parameter_reader_administration`. Stop if trust, attachments,
the External Secrets user/boundary, or any other resource would change.
On September 30, 2026 PDT (October 1 UTC), the reviewed saved plan was applied
and a fresh full-unit plan was a no-op. The CI policy simulation allows
`kms:DescribeKey` on the current SSM key and leaves `kms:Decrypt` and
`kms:ScheduleKeyDeletion` implicitly denied.

### Langfuse blob-storage bootstrap

On September 30, 2026 PDT (October 1 UTC), an administrator applied the
reviewed 12-resource `IaC/homelab/us-west-2/apps/langfuse/blob-storage` bootstrap through that
unit's normal remote state. A fresh plan was a no-op; live checks confirmed all
four bucket public-access blocks, bucket versioning, and both exact S3 SSM
parameters as current SecureStrings under `alias/aws/ssm`. Future reconciliation
must use that same remote state and a reviewed saved plan. Do not hand-create a
partial identity or put it in a separate state: the secret-bearing access-key
resource and its SSM parameters must remain under the same unit's lifecycle.

After a reviewed operator apply adds the pending grant, CI can use only
`iam:GetUser`, `iam:ListAccessKeys`, and `iam:GetUserPolicy` on
`arn:aws:iam::716182248480:user/homelab/homelab-langfuse-s3` for normal
Langfuse-user refresh. This additional grant has no IAM create, write, tag,
delete, rotate, wildcard, or other-user access. Any future Langfuse IAM
lifecycle or credential-rotation change is operator-owned: review and apply it
through the same remote-state saved-plan path, rather than broadening CI.

After backend-disabled initialization, run the offline boundary regression with
`terragrunt --log-disable run --no-auto-init -- test -no-color`. It evaluates
the provider-generated policy with synthetic credentials and a plan only;
Terragrunt backend auto-initialization must stay disabled for this check.

After the full operator apply succeeds, rerun the protected `Terragrunt Apply`
workflow. Its short-lived OIDC role can then create, version, tag, attach, and
delete only the declared SSM reader policy family.

After a boundary correction, verify `kubectl -n octelium get externalsecret
cordium-agent-auth -o yaml` reports `Ready=True` and a new refresh time within
five minutes. Cordium polls SSM periodically; unchanged `OnChange` secrets can
retain older success statuses without exercising current KMS permissions.

Do not destroy this unit while `IaC/homelab/us-west-2/shared/aws-ssm-parameters` still manages that
policy family or the cluster uses the External Secrets IAM user. The user has
`prevent_destroy`; removing the bootstrap grant or boundary first would prevent
safe reconciliation or restore the broader direct-policy risk.

## State bucket request costs

`state-bucket-encryption` adopts the existing state bucket's encryption
configuration and enables S3 Bucket Keys. It preserves the default KMS key,
explicit backend KMS key, and SSE-C block. It never owns the bucket or objects.
See [State encryption](../openwiki/operations/state-encryption.md)
for the focused plan/apply path, verification, and declarative rollback.
