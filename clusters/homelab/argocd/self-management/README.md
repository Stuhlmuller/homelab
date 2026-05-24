# Argo CD Self-Management

This directory is the repository-owned desired-state path for Argo CD managing
its own steady-state configuration in the `homelab` cluster.

Terragrunt owns only the first seed:

- Install the Argo CD Helm release.
- Create the `argocd-self-management` Application.
- Leave the first handoff in manual validation mode.

After the first sync is verified, Argo CD owns changes under this directory.
Enable automated prune and self-heal only by editing repository desired state,
reviewing the change, and applying it through the documented workflow. Do not
patch the live Application as the permanent fix for source path, revision, or
sync policy changes.
