# AWS SSM Secret References

Tags: #runbook #secrets #aws

Canonical runbook: [`docs/secrets-aws-ssm.md`](../../secrets-aws-ssm.md)

Commit SSM paths, ExternalSecret contracts, and safe placeholders only. Runtime
values stay outside git; External Secrets materializes application credentials
after the repository-managed bootstrap secret is available.

See [[../architecture/secrets-and-identity]] and [[../workloads/inventory]].
