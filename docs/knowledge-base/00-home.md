# Homelab Knowledge Base

Open `docs/knowledge-base` as an Obsidian vault. The vault is committed as
plain Markdown so it can be reviewed in pull requests and read without
Obsidian.

This knowledge base is the connective tissue between repo source files,
runbooks, and implementation decisions. It does not replace code, Terragrunt
state, Kubernetes manifests, or the detailed runbooks in `docs/`. When a note
and a source file disagree, fix the source of truth first, then update the note
in the same change.

## Start Here

- [[architecture/cluster-topology]] records the current Talos and Kubernetes
  shape.
- [[architecture/gitops-flow]] explains how changes move from git to the
  cluster.
- [[architecture/storage-and-state]] tracks durable state and backup gates.
- [[architecture/secrets-and-identity]] records secret and identity boundaries.
- [[workloads/inventory]] lists app ownership, paths, dependencies, and state.
- [[patterns/new-application]] is the checklist for adding a new workload.
- [[patterns/new-platform-service]] is the checklist for shared platform
  services.
- [[patterns/new-terragrunt-unit]] is the checklist for new Terragrunt units.
- [[operations/validation-gates]] collects validation expectations.
- [[operations/change-log]] captures knowledge-base updates as the homelab
  evolves.

## Update Rule

For every substantive change, update the smallest useful set of notes:

1. Read this index and any note related to the code or docs being changed.
2. Make the repository source change first.
3. Update affected knowledge-base links, inventories, decisions, and validation
   evidence.
4. Add an entry to [[operations/change-log]] when the change creates, removes,
   renames, or materially changes an app, platform dependency, workflow,
   topology assumption, secret contract, or storage requirement.
5. Mark unverified or environment-specific facts explicitly instead of writing
   them as general guidance.

## Public-Repo Boundary

Do not record secrets, raw credentials, private keys, Talos secrets, kubeconfigs,
token values, raw certificate material, or private-only hostnames here. Safe
references such as ExternalSecret names, SSM parameter paths, public runbook
paths, and known homelab LAN addresses already documented in the repo are fine.
