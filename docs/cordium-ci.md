# Cordium CI execution

`.github/workflows/cordium-check.yml` orchestrates a disposable Cordium
workspace from a GitHub-hosted runner. The repository checks execute inside
Cordium; this does not register a GitHub self-hosted runner or autoscaler.
Live acceptance remains pending until the gates below pass. On 2026-09-12 the
fixed native read-only preview authenticated successfully and found all three
dedicated CI resources absent; no resources were changed.

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
by a successful create response and polls for up to one minute to verify its
absence afterward, accommodating asynchronous controller deletion.

The 50-minute GitHub job bounds its preparation steps to 11 minutes total
and its execution step to 38 minutes. Execution captures a 36-minute deadline
before entering Nix, so environment and transport setup consume the same
budget as workspace work. Startup is capped at five minutes, the repository
gate at 20 minutes, and every API call at the remaining work budget. Work stops
three minutes before that captured deadline: two minutes remain for deletion
and absence verification, then one for logout and transport cleanup. An
expired setup budget fails before creating a workspace. The execution step
also leaves two minutes beyond the captured deadline before forced termination.

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
3. Reconcile only the three CI resources with the fixed operator command below.
   The NOFX native transport helper must already be merged; broad catalog apply
   is not this rollout path.
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

## Fixed native catalog reconciliation

The operator path reuses the pinned CLI and verified TLS carrier from
[NOFX reconciliation](octelium-nofx-reconciliation.md). Install its pinned client
first and use an existing private operator session. Preview current presence
and exact declared-spec equality without applying anything:

```sh
nix develop --command python3 -I scripts/cordium-ci-reconcile.py
```

Use `--homedir /PRIVATE/OPERATOR_LOGIN` only to select an existing login.
An authenticated `NotFound` response means the fixed resource is absent;
transport, authorization, or malformed-response errors fail the preview.
The output contains only resource names and status booleans, not credentials
or live resource bodies. Use an already trusted checkout for the preview:
Python isolation prevents local module shadowing, but cannot validate a flake
before `nix develop` evaluates it.

After review, merge, repository validation, and checkout of the exact current
main commit, run:

```sh
(
set -euo pipefail
reviewed_main_sha=FULL_REVIEWED_MAIN_SHA
checkout_status="$(git status --porcelain=v1 --untracked-files=all --ignore-submodules=none)"
checkout_sha="$(git rev-parse HEAD)"
remote_main_sha="$(git ls-remote https://github.com/Stuhlmuller/homelab.git refs/heads/main | cut -f1)"
test -z "$checkout_status"
test "$checkout_sha" = "$reviewed_main_sha"
test "$remote_main_sha" = "$reviewed_main_sha"
nix develop --command python3 -I scripts/cordium-ci-reconcile.py \
  --execute --expected-sha "$reviewed_main_sha"
)
```

The command rejects a dirty checkout or differing local, expected, and remote
main commits before inspecting the catalog or opening transport. The caller's
subshell performs those checks before evaluating Nix or repository Python;
the helper repeats them before native operations. All three operator helpers
require `python3 -I` before importing other modules. The reconciler selects
exactly `homelab-cordium-ci-execution` (Policy), `homelab-cordium-ci-oidc`
(IdentityProvider), and `homelab-cordium-ci` (User). It applies the restrictive
policy first, then the provider, then the workload User. Each native apply
receives a private one-resource manifest and an explicit kind filter; no
other catalog resource is applied or pruned. Credentials, live secret material,
backup schedulers, and unrelated identities are outside this command's scope.

It repeats all three applies, requires each second apply to report no changes,
and verifies each returned specification equals its committed declaration.
Any partial failure remains a failed rollout; inspect read-only and rerun this
same reviewed command after resolving the cause. Do not repair with a broad
catalog apply. Successful installation does not prove GitHub OIDC denial,
remote execution, cleanup, or audit acceptance; complete the rollout gates
above before claiming the CI path deployed. Run the default preview again
for independent verification after execution.

## Rollback

Stop dispatching this optional workflow and wait for active runs to finish.
Inspect the dedicated user's workspace inventory and remove only confirmed
disposable workspaces through the Cordium lifecycle before retiring its owner.
Existing required repository checks remain independent.

In a reviewed retirement commit, remove `cordium-check.yml` and the three CI
catalog definitions, but retain `scripts/cordium-ci-retire.py` and its shared
`scripts/octelium-nofx-reconcile.py` guard. Normal catalog
reapplication does not prune absent native resources. Using an operator admin
session, run the fixed retirement path from that commit:

```sh
python3 -I scripts/cordium-ci-retire.py --homedir /PRIVATE/OPERATOR_LOGIN
(
set -euo pipefail
reviewed_main_sha=FULL_REVIEWED_RETIREMENT_SHA
checkout_status="$(git status --porcelain=v1 --untracked-files=all --ignore-submodules=none)"
checkout_sha="$(git rev-parse HEAD)"
remote_main_sha="$(git ls-remote https://github.com/Stuhlmuller/homelab.git refs/heads/main | cut -f1)"
test -z "$checkout_status"
test "$checkout_sha" = "$reviewed_main_sha"
test "$remote_main_sha" = "$reviewed_main_sha"
python3 -I scripts/cordium-ci-retire.py --homedir /PRIVATE/OPERATOR_LOGIN \
  --execute --expected-sha "$reviewed_main_sha"
)
```

The helper refuses execution from a dirty checkout or when local, expected,
and remote main commits differ, before reading the catalog or deleting anything.
It also refuses retirement while the workflow or CI catalog definitions remain.
Unmerged or local-only removals cannot authorize retirement. It removes only
`homelab-cordium-ci-oidc`, `homelab-cordium-ci`, and
`homelab-cordium-ci-execution`, in that order, and verifies each is absent.
Authentication/network errors are failures, not evidence of absence. Repeating
it skips already-absent objects. Keep the helper until retirement is verified.
Restore previous Cordium capacity limits through Argo CD only if reverting that
capacity decision is intended. OpenClaw execution uses a separate future
identity and is not enabled by this CI workflow.
