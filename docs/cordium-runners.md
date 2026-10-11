# Cordium GitHub Actions runners

The migration routes every repository-owned workflow job to
`[self-hosted, Linux, X64, cordium]`. There is no hosted-runner fallback.
The static workflow gate rejects a local job with any other selector,
including newly added workflows. Reusable workflow callers delegate their
runner choice to the called workflow.

GitHub-managed workflows are also in scope. Live inspection on 2026-10-11 found
`dynamic/github-code-quality/codeql` configured with standard hosted runners.
Its selection must become `runner_type: labeled`, `runner_label: cordium` through
the fixed reconciler in [bootstrap PR #1278](https://github.com/Stuhlmuller/homelab/pull/1278).
Preserve its languages, configured state and AI findings setting. The legacy
dynamic code-scanning registry entry remains listed, but default setup is
`not-configured`; keep the repository-owned advanced scan.

## Activation hold

Do not merge the selector change until a repository-owned runner provisioner
is deployed and a canary succeeds. Inspection on 2026-10-10 found zero
repository runners, and all 33 jobs across 18 workflows used hosted runners.
The existing Cordium workspace check does not register an Actions runner.
Cordium upstream provides workspace APIs, but no GitHub runner controller.

The existing `homelab-cordium-ci` identity accepts only the manual workspace
check on reviewed `main`; it cannot provision the complete runner fleet.
The retired SSM registration token is not a renewable runner credential.
Repository administration is available through the operator's GitHub CLI;
organization runner administration is unavailable with its current scopes.
Use repository-scoped runners for this migration.

The GitHub Terraform provider has no App creation resource. Bootstrap the
private organization App from the committed
[manifest](examples/github/cordium-runner-app.json), then manage its installed
repository association with `github_app_installation_repositories` in
`github-iac`. Limit installation to `homelab`. Administration write permits
runner registration; Actions read permits queue inspection. Webhooks and user
OAuth are disabled. Capture the generated private key outside the checkout,
then inject it through the declared secret path; never place it in Terraform
inputs or public git. The loopback redirect is only for one-time bootstrap.

On 2026-10-10, App `5270069` (`stuhlmuller-cordium-runners`) was created and
installation `170148721` was limited to `homelab`. An authenticated App-token
probe verified that exact repository selection and found zero runners.
Key authentication succeeded. The initial manifest credential capture failed
while writing the response; a replacement key was captured and verified.
The first unused key remains registered and needs explicit retirement after
replacement-key custody is established. Bootstrap files and keys stay outside
the checkout. Runner deployment and workflow cutover remain pending.

## Required provisioning contract

- A repository-owned controller creates disposable Cordium Workspaces and
  registers one-job ephemeral Actions runners. Renew registration using a
  dedicated GitHub App with repository administration permission. Keep its
  private key file-backed, outside runner Workspaces and job containers.
- Give the controller its own narrow Cordium identity. Do not reuse the human,
  agent, or OIDC check identity. Do not clone a PR branch in the controller.
- Delete the runner Workspace and PVC after each job, including failure and
  cancellation; reconcile interrupted cleanup before creating another runner.
  Prevent untrusted jobs from reaching controller credentials, other runner
  state, Kubernetes credentials, or the homelab LAN. The privileged Cordium
  workspace boundary needs explicit verification before allowing public PRs.
- Use an Ubuntu 24.04 x86_64 runner image with Node action prerequisites, Git,
  Bash, sudo, Python toolcache support, Nix installation support, and Docker
  daemon compatibility. Super-Linter is a Docker action; image builds and the
  ClickHouse quarantine check also need Docker. A Docker CLI alone is
  insufficient. Validate Docker inside Cordium's rootless Podman runtime;
  never mount a node's Docker socket.
- Start with one job at a time. `zimaboard-1` has 3950m CPU and approximately
  7.1 GiB allocatable memory, shared with existing workloads. Its disposable
  local storage and existing one-active-workspace-per-user limit constrain
  capacity. Increase limits only through reviewed ClusterConfig and resource
  changes supported by measured headroom.

## Acceptance and cutover

1. Validate and publish the runner image through the declared image build path.
   Deploy the controller, secret references, identity policy, and Workspace
   definition through reviewed repository code before switching job selectors.
2. Register the canary with a temporary label. Dispatch a reviewed canary
   workflow to that label and verify GitHub's job `runner_name`, runner labels,
   Cordium Workspace identity, node placement, and exact checkout SHA.
3. Exercise JavaScript and Docker actions, Docker builds, Nix, Python setup,
   protected environment/OIDC jobs, failure propagation, cancellation, and
   runner/Workspace/PVC deletion. Verify denied access from an untrusted job.
4. Run every migrated workflow's applicable acceptance path, using existing
   exact-SHA and environment approval guards. Do not dispatch production writes
   solely to test scheduling. A protected dry run must establish compatibility
   before the next authorized write is used as delivery evidence.
5. Merge the selector change only after the pool is online and the required
   checks pass on its exact head. Inspect job metadata after merge to prove
   all workflows execute in Cordium; YAML selectors alone do not prove this.
   Include generated Code Quality jobs and its configuration readback, plus all
   bootstrap workflows added by #1278, beyond the original 33-job inventory.

Rollback through a reviewed commit restoring the prior hosted selectors and
the workflow security hashes and gate. Wait for active jobs and verify
disposable runner cleanup before retiring the provisioner or its credentials.
