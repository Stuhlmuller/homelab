# CI/CD

Tags: #runbook #ci #github-actions

Canonical runbook: [`docs/ci-cd.md`](../../ci-cd.md)

Pull requests always emit the aggregate `Terragrunt Gate`; only trusted changes
to live inputs enter the protected plan environment. Pushes to `main` emit an
exact-SHA apply request, and an operator dispatches the protected apply. AWS,
Azure, Kubernetes, and Octelium credentials remain GitHub environment inputs,
while desired state stays in repository-owned files.

Release automation installs its exact integrity-locked npm dependency graph.
The pull-request preview uses a tokenless local bare repository; only the
`main` publisher receives the step-scoped GitHub release token.

See [[../operations/validation-gates]] and [[../architecture/gitops-flow]].
