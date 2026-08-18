# AWS SSM Secret References

Tags: #runbook #secrets #aws

Canonical runbook: [`docs/secrets-aws-ssm.md`](../../secrets-aws-ssm.md)

Commit SSM paths, ExternalSecret contracts, and safe placeholders only. Runtime
values stay outside git; External Secrets materializes application credentials
after the repository-managed bootstrap secret is available.

## Multica PostgreSQL Password Rotation

The Multica chart reads `POSTGRES_PASSWORD` when the built-in PostgreSQL data
directory is initialized. On a retained, already-initialized PVC, changing
`/homelab/multica/postgres-password` and refreshing `multica-secrets` does not
change the existing `multica` database role password. Rotate it with a reviewed
change window so the database role and consumers move together.

1. Write the new generated password to
   `/homelab/multica/postgres-password` in AWS SSM Parameter Store without
   committing the value.
2. Pause Multica writes by scaling the backend Deployment to zero or using an
   approved maintenance gate.
3. Exec into the PostgreSQL pod with the old Secret still mounted and run
   `ALTER USER multica WITH PASSWORD '<new-password>';` through `psql` as the
   database superuser. Do not print the password in shell history or logs.
4. Bump `homelab.stuhlmuller.dev/generated-secret-revision` on
   `clusters/homelab/apps/multica/externalsecret.yaml` so External Secrets
   refreshes `multica-secrets` from SSM.
5. Confirm the target Secret contains the new version, then restart the backend
   and PostgreSQL pods so both read the refreshed Secret.
6. Verify backend readiness, login/signup, and a simple workspace read/write
   before reopening writes.

If any step fails after the role password changes, either complete the Secret
refresh and pod restart or immediately restore the old SSM value and run another
`ALTER USER` back to the old password before bringing the backend up.

See [[../architecture/secrets-and-identity]] and [[../workloads/inventory]].
