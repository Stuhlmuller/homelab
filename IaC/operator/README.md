# Operator-owned infrastructure

`IaC/operator` contains declarative prerequisites that a protected automation
identity must not be allowed to change for itself. These units use the shared
remote state and repository modules, but the GitHub plan/apply workflows do not
traverse this directory.

Run an operator unit only with a reviewed administrator session, after its
format, validation, and plan checks pass. This separation prevents a compromised
workflow from widening the permissions of its own AWS role while keeping the
bootstrap policy reproducible and reviewable.

## GitHub Actions apply-role policy

`github-actions-role-policy` owns the existing `Github-TF-State` role trust and
attaches one managed policy. Trust is limited to the protected plan and
production environments in `Stuhlmuller/homelab` and
`Stuhlmuller/github-iac`.
The permission grant is limited to the ten exact managed-policy slots
`homelab-ssm-parameter-reader-00` through `-09` and attachments to the exact
`homelab-ssm-parameter-readers` group. The role cannot manage this bootstrap
policy, its own attachment, or another role.

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
cd IaC/operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
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

### Full-unit reconciliation

Changes to the managed policy, attachment, External Secrets boundary, or IAM
user require an un-targeted operator plan. Import
`aws_iam_user.external_secrets` as `external-secrets_aws-ssm-auth` first only
when that address is absent, then review and apply the same full saved plan.
Do not use the trust-only target for those changes.

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

Do not destroy this unit while `IaC/live/aws-ssm-parameters` still manages that
policy family or the cluster uses the External Secrets IAM user. The user has
`prevent_destroy`; removing the bootstrap grant or boundary first would prevent
safe reconciliation or restore the broader direct-policy risk.

## State bucket request costs

`state-bucket-encryption` adopts the existing state bucket's encryption
configuration and enables S3 Bucket Keys. It preserves the default KMS key,
explicit backend KMS key, and SSE-C block. It never owns the bucket or objects.
See [KMS audit and rollout](../../docs/knowledge-base/operations/kms-cost-audit-2026-09-05.md)
for the focused plan/apply path, verification, and declarative rollback.

## Legacy KMS key retirement

`legacy-kms-retirement` owns only the adopted legacy key and its alias. Its
final desired state schedules deletion with a 30-day window. The active
east-region OpenTofu key is outside this unit. Dependency audit and archive
verification are complete; applying the saved retirement plan requires the
explicit exact-key approval recorded in the [KMS audit](../../docs/knowledge-base/operations/kms-cost-audit-2026-09-05.md).
