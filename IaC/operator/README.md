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

`github-actions-role-policy` attaches one managed policy to the existing
`Github-TF-State` role. The grant is limited to the ten exact managed-policy
slots `homelab-ssm-parameter-reader-00` through `-09` and attachments to the
exact `homelab-ssm-parameter-readers` group. Tagged creation must retain the
homelab project tag and the repository's standard tag-key set. The role cannot
manage this bootstrap policy, its own attachment, or another role.

The same unit adopts the existing `external-secrets_aws-ssm-auth` IAM user,
removes direct managed and inline user policies, and applies an operator-owned
permissions boundary. The boundary caps the user's effective permissions at
`GetParameter`/`GetParameters` under `/homelab/*` and decrypt/describe access
to the regional runtime-secret KMS key. Group policy changes therefore cannot
turn the reader credential into unrelated AWS access.

Use an AWS administrator profile only as the credential selector:

```sh
aws sso login --profile <administrator-profile>
cd IaC/operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
terragrunt --log-disable validate -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable init -reconfigure -no-color
```

On the first rollout, or if the encrypted operator state must be reconstructed,
list the state and import the existing IAM user when its address is absent. The
import must happen before the first plan so OpenTofu adopts the user instead of
attempting to create a duplicate:

```sh
AWS_PROFILE=<administrator-profile> terragrunt --log-disable state list
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_user.external_secrets' external-secrets_aws-ssm-auth
```

Do not repeat the import when `state list` already contains
`aws_iam_user.external_secrets`. Save, review, and apply the same plan:

```sh
AWS_PROFILE=<administrator-profile> terragrunt --log-disable plan -out=plan.out -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable show -no-color plan.out
AWS_PROFILE=<administrator-profile> terragrunt --log-disable apply -no-color plan.out
```

After the operator apply succeeds, rerun the protected `Terragrunt Apply`
workflow. Its short-lived OIDC role can then create, version, tag, attach, and
delete only the declared SSM reader policy family.

Do not destroy this unit while `IaC/live/aws-ssm-parameters` still manages that
policy family or the cluster uses the External Secrets IAM user. The user has
`prevent_destroy`; removing the bootstrap grant or boundary first would prevent
safe reconciliation or restore the broader direct-policy risk.
