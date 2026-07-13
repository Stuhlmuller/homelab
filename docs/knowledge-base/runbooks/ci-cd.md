# CI/CD

Tags: #runbook #ci #github-actions

Canonical runbook: [`docs/ci-cd.md`](../../ci-cd.md)

Pull requests run static checks and scoped Terragrunt plans; pushes to `main`
run the protected apply workflow. AWS, Azure, Kubernetes, and Octelium
credentials remain GitHub environment inputs, while desired state stays in
repository-owned files.

See [[../operations/validation-gates]] and [[../architecture/gitops-flow]].
