# Continuous Improvement

Tags: #operations #security #reliability #stewardship

Source: `AGENTS.md`

This homelab should improve continuously through small, reviewable changes.
Agents should treat it as home turf: notice weak assumptions, hardening
opportunities, reliability gaps, missing validation, and operational friction
before they become incidents.

## Stewardship Loop

1. Start from source-backed context: relevant code, runbooks, knowledge-base
   notes, and read-only live inspection when the question depends on current
   cluster reality.
2. Prefer repo-owned desired state over manual repair. Express fixes in
   Terragrunt, OpenTofu, Helm values, Kustomize/manifests, scripts, or docs
   before any rollout.
3. Keep improvements small enough to review. Security and reliability work is
   better as a steady stream of scoped PRs than a rare sweeping rewrite.
4. Validate with the smallest gate that proves the change, then record any
   unavailable validation plainly.
5. Update this vault whenever a finding, decision, source path, risk, or
   follow-up matters beyond the current chat.
6. Own PR follow-through for Claw-authored work: push the branch, open the PR,
   monitor required checks, resolve merge blockers, and merge when repository
   policy allows. PR creation is not the finish line.
7. Use Conventional Commits for Claw-authored commit messages and PR titles so
   release automation and reviewers can classify changes consistently.

## Finding Format

Record findings in the most specific affected note when one exists. Use this
page for cross-cutting or not-yet-owned findings.

- **Status:** open, planned, fixed, accepted risk, or obsolete.
- **Area:** workload, platform service, Talos, networking, storage, CI/CD,
  secrets, observability, or agent runtime.
- **Evidence:** source path, command, PR, or read-only observation.
- **Risk:** what could fail, leak, drift, or become hard to operate.
- **Next step:** concrete repo-owned action or validation gate.

## Current Standing Order

Rodman asked Claw to continue making security and reliability improvements as
needed, to treat the homelab as home, and to mark findings in
`docs/knowledge-base/`. This page is the durable capture point for that work
when a more specific note does not already own the finding.

Rodman also expects Claw to make sure Claw-authored PRs actually get merged.
Merging to `main` is the handoff to the repository's Terragrunt/GitOps apply
path, so check and merge ownership is part of the operational work.

Claw-authored commits and PR titles should use Conventional Commit format, for
example `docs: update homelab runbook` or `fix: tighten openclaw network
policy`.

## Open Findings

- **Status:** open
- **Area:** agent runtime
- **Evidence:** OpenClaw pod currently runs on an NFS-backed PVC where files can
  appear as `nobody:nogroup`; PR #296 configures workspace scratch paths and
  Git safe-directory state in pod bootstrap.
- **Risk:** future agent work can hit Git ownership checks or brittle cleanup
  paths if runtime setup drifts from the PVC ownership model.
- **Next step:** after PR #296 syncs, verify the rolled pod has
  `GIT_CONFIG_GLOBAL=/data/openclaw/gitconfig`, can run `git status` in
  `/data/openclaw/workspace`, and has
  `/data/openclaw/workspace/.openclaw/trash`.
- **Status:** fixed
- **Area:** agent runtime
- **Evidence:** Rodman requires Claw to sign all commits. The current OpenClaw
  image lacks `gpg` and `ssh-keygen`; PR #297 configured pod bootstrap to
  provide a persistent SSH signing helper and key.
- **Risk:** unsigned commits weaken auditability for agent-authored
  infrastructure changes.
- **Next step:** after PR #297 syncs, verify the rolled pod has
  `commit.gpgsign=true` and that future Claw branch commits show a good SSH
  signature before push.
- **Status:** open
- **Area:** CI/CD
- **Evidence:** the repository currently accepts squash merges only. GitHub
  creates the final squash commit on `main`, while Claw's branch commits are
  locally SSH-signed before push.
- **Risk:** GitHub's squash commit may not carry Claw's local SSH signature,
  which can blur the "all Claw commits are signed" rule unless the repository
  policy or merge workflow explicitly accounts for it.
- **Next step:** decide whether to keep squash-only merges with GitHub-signed
  mainline commits, allow rebase/merge methods that preserve Claw-signed branch
  commits, or add a bot-supported path for signed squash commits.

- **Status:** fixed
- **Area:** secrets / CI/CD
- **Evidence:** June 2026 security audit found the retired
  `IaC/modules/kubernetes-secret-from-ssm` path read decrypted SSM values into a
  Kubernetes Secret resource, which put provider credentials in OpenTofu state.
  This change removes that stack, installs `external-secrets/aws-ssm-auth` from
  protected CI secrets with `scripts/ci/install-external-secrets-aws-auth.sh`,
  and adds stronger secret scanning.
- **Risk:** decrypted External Secrets AWS provider credentials could otherwise
  be exposed to anyone or anything with access to OpenTofu state, plan caches, or
  CI artifacts.
- **Next step:** rotate the External Secrets IAM access key after confirming any
  older state object that contained the Kubernetes Secret data has been removed.
- **Status:** fixed
- **Area:** networking / platform service
- **Evidence:** June 2026 security audit found privileged namespace audit/warn
  labels set to `privileged` and the public n8n Funnel exposing test and waiting
  webhook paths. This change moves privileged namespaces to restricted audit/warn
  mode, removes `/webhook-test` and `/webhook-waiting` from the public Funnel,
  and adds Conftest policies for those routes and ExternalSecret SSM prefixes.
- **Risk:** broad public or privileged paths increase the blast radius of chart
  drift, compromised workloads, or unauthenticated webhook probing.
- **Next step:** continue splitting the Deluge VPN privilege exception into a
  dedicated namespace and add app-level NetworkPolicies where missing.
- **Status:** open
- **Area:** platform service / GitOps
- **Evidence:** June 2026 security audit found remaining structural hardening
  work: the shared Argo CD AppProject can still deploy cluster-scoped RBAC,
  Kiali remains anonymous/view-only on the tailnet, several app-template
  workloads need explicit restricted container security contexts, and remote
  Terragrunt catalog modules are still referenced by the mutable `0.4.0` tag.
- **Risk:** these are reviewability, reconnaissance, and lateral-movement risks
  that are larger than a single safe patch.
- **Next step:** split AppProjects, add Kiali identity controls, harden compatible
  app-template values, and pin or vendor remote modules once the immutable commit
  for `terragrunt-catalog` tag `0.4.0` can be verified.
