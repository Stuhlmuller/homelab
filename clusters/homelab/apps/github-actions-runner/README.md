# GitHub Actions Runner

The in-cluster GitHub Actions runner is retired. Keep the inert retirement
ConfigMap while the Argo CD Application remains registered so automated
pruning can delete the previous runner Deployment, ExternalSecret,
ClusterSecretStore, and script ConfigMap. A non-empty source avoids Argo CD's
automatic-sync safety block for an application that would prune every object.

Diagnostics and live CI use GitHub-hosted runners plus the Octelium workload
credential path documented in `docs/ci-cd.md`.
