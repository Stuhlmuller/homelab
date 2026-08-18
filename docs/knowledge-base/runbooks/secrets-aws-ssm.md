# AWS SSM Secret References

Tags: #runbook #secrets #aws

Canonical runbook: [`docs/secrets-aws-ssm.md`](../../secrets-aws-ssm.md)

Commit SSM paths, ExternalSecret contracts, and safe placeholders only. Runtime
values stay outside git; External Secrets materializes application credentials
after the repository-managed bootstrap secret is available.

## Multica PostgreSQL Password Rotation

The Multica chart reads `POSTGRES_PASSWORD` when the built-in PostgreSQL data
directory is initialized. On a retained, already-initialized PVC, refreshing
`multica-secrets` does not change the existing `multica` database role
password. The generated SSM value is owned by the
`IaC/live/aws-ssm-parameters` OpenTofu stack, so do not hand-edit
`/homelab/multica/postgres-password`; the next apply would restore the
repository-owned generated value.

Rotate it through a reviewed change window so the generated parameter, database
role, and consumers move together.

1. Open a reviewed PR that changes the declared rotation trigger or keeper for
   `/homelab/multica/postgres-password` in
   `IaC/live/aws-ssm-parameters`. If the generated-parameter workflow does not
   have an explicit keeper yet, add one before rotating.
2. Plan and apply that stack so OpenTofu writes the new SecureString value to
   SSM.
3. Pause Multica writes through GitOps, such as a reviewed change that
   disables automated sync or scales the backend in desired state, then wait for
   Argo CD to report the paused state. Do not rely on manual `kubectl scale`
   while automated self-heal is enabled.
4. Read the new value from SSM in an operator shell without printing it in
   history or logs, then exec into the PostgreSQL pod while the old Secret still
   works and run `ALTER USER multica WITH PASSWORD '<new-password>';` through
   `psql` as the database superuser.
5. Bump `homelab.stuhlmuller.dev/generated-secret-revision` on
   `clusters/homelab/apps/multica/externalsecret.yaml` so External Secrets
   refreshes `multica-secrets` from SSM.
6. Confirm the target Secret contains the new version, then restart the backend
   and PostgreSQL pods so both read the refreshed Secret.
7. Verify backend readiness, login/signup, and a simple workspace read/write
   before reopening writes.

If any step fails after the role password changes, either complete the Secret
refresh and pod restart or revert the rotation PR, re-apply the generated
parameter stack, and run another `ALTER USER` back to the restored password
before bringing the backend up.

See [[../architecture/secrets-and-identity]] and [[../workloads/inventory]].
