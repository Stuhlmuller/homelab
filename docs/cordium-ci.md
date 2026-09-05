# Cordium CI execution

`.github/workflows/cordium-check.yml` orchestrates a disposable Cordium
workspace from a GitHub-hosted runner. The repository checks execute inside
Cordium; this does not register a GitHub self-hosted runner or autoscaler.
Live acceptance remains pending until the gates below pass.

## Identity and transport

The catalog declares `homelab-cordium-ci-oidc`, `homelab-cordium-ci`, and
`homelab-cordium-ci-execution`. GitHub signs a short-lived assertion for
`https://stinkyboi.com`. Authentication requires the exact repository and
owner IDs, `main`, the `cordium-check.yml` workflow, and a manual dispatch.
A catch-all post-authentication denial rejects assertions outside that rule.
The job intentionally has no GitHub environment: its OIDC subject must remain
`repo:Stuhlmuller/homelab:ref:refs/heads/main`.

The dedicated workload identity can create, start, inspect, execute in, and
delete its own workspaces. A priority `-4` denial excludes other Cordium
methods before the upstream broad MainService allowance. It receives no
bootstrap management credential. Its session duration is bounded to one hour
and one concurrent session; cleanup requests logout, but the pinned client
does not propagate server-side logout failures.

Native CLI traffic uses the reviewed Cloudflare TCP carrier at
`octelium-transport.stinkyboi.com`. The CI wrapper copies the pinned Nix
`cloudflared` binary, grants only low-port binding, and runs it without root
on loopback port 443. A marked hosts entry directs the canonical API hostname
to that listener. Inner TLS still validates the canonical API certificate.
The wrapper removes its hosts entry, process, and private login files on exit.
This wrapper is restricted to Linux GitHub Actions runners and must not run
on an operator workstation. The native exec API does not depend on a nested
workspace browser hostname or its wildcard certificate.

## Workspace lifecycle

`.cordium/workspace.yaml` pins the Nix image and public repository, with
2 CPU, 2 GiB memory, and 10 GB local storage. The helper accepts only an exact
40-character commit SHA, refuses a preexisting workspace inventory, creates
an ephemeral workspace, waits for readiness, verifies its checked-out SHA,
and executes `bash scripts/ci/static-checks.sh` through `nix develop`.
Remote failure remains a failed job. Cleanup deletes only the workspace named
by a successful create response and verifies its absence afterward.

Cordium's cluster configuration limits every user to four stored workspaces
and one active workspace. These limits also affect interactive users; they
bound concurrent pressure on the small worker. The workflow additionally
serializes runs for its shared workload identity. Workspace containers run
inside the existing privileged Cordium worker boundary, so this path accepts
reviewed main only and never untrusted pull-request code.

GitHub force cancellation or an ambiguous create response can leave a
workspace behind. The next run fails its empty-inventory preflight instead of
deleting unknown work. Inspect the dedicated identity and use the documented
Cordium workspace lifecycle to remove the identified disposable workspace;
do not delete unrelated Kubernetes resources. Workspace data is disposable
and has no backup contract.

## Rollout and acceptance

1. Merge the reviewed transport and CI changes after their checks pass.
2. Reconcile Tunnel DNS through `octelium-public-tunnel.yml` and pass
   `scripts/octelium-tunnel-check.py`. Let Argo CD apply the Cordium limits.
3. Apply the reviewed native catalog through the documented Octelium catalog
   workflow, then verify the dedicated identity and policy are present.
4. Dispatch the exact current main commit:

   ```sh
   gh workflow run cordium-check.yml --ref main -f expected_sha=FULL_MAIN_SHA
   ```

5. Require the actual repository gate to pass remotely, the exact SHA to match,
   and the workspace and its disposable storage to be removed. Verify access
   and execution records through the authenticated audit console.
6. Exercise denied wrong-workflow/ref assertions and a forbidden Cordium
   method before treating the identity boundary as live-verified. Verify a
   failed remote command still fails CI while cleanup succeeds. Reconnect and
   sustained exec remain separate transport acceptance gates.

The local subprocess tests cover lifecycle ordering, wrong checkout rejection,
remote exit status, cleanup failure, invalid creation names, and retained
workspace rejection. They do not prove cluster policy enforcement, available
capacity, remote Nix permissions, or live transport stability.

## Rollback

Stop dispatching this optional workflow; existing required repository checks
remain independent. Revert its repository-owned workflow and policy grant
through a reviewed PR and reconcile the native catalog. Restore the previous
Cordium limits through Argo CD only if reverting that capacity decision is
intended. Do not delete workspace storage until the owner confirms it is
disposable. OpenClaw execution uses a separate future identity and is not
enabled by this CI workflow.
