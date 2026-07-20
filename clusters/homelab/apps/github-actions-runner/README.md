# GitHub Actions Runner

The in-cluster GitHub Actions runner is retired. Keep this empty Kustomize
source while the Argo CD Application remains registered so automated pruning can
delete the previous runner Deployment, privileged namespace, ExternalSecret,
ClusterSecretStore, and script ConfigMap.

Diagnostics and live CI use GitHub-hosted runners plus the Octelium workload
credential path documented in `docs/ci-cd.md`.
