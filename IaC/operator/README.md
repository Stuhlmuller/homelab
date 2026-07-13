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

Use an AWS administrator profile only as the credential selector:

```sh
aws sso login --profile <administrator-profile>
cd IaC/operator/github-actions-role-policy
AWS_PROFILE=<administrator-profile> terragrunt --log-disable init -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable plan -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable apply -no-color -auto-approve
```

After the operator apply succeeds, rerun the protected `Terragrunt Apply`
workflow. Its short-lived OIDC role can then create, version, tag, attach, and
delete only the declared SSM reader policy family.

Do not destroy this unit while `IaC/live/aws-ssm-parameters` still manages that
policy family. Removing the bootstrap grant first prevents the protected apply
role from reconciling or safely deleting those resources.
