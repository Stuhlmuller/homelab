# Integration validation record

The preceding separate T027/T028 recovery convergence was clean: reviewed
FR007/FR017/SC005/US4AC3, isolated reconstruction/private version custody and all
five constitution principles; no findings or writes. Recovery evidence is in
checkpoints/recovery.md. T029 authored documentation is complete in all five
named cross-cutting files. Generated wiki artifacts were not edited.

Initial T030 validation attempts: The first full `nix run --no-update-lock-file
--no-write-lock-file .#validate` failed on the canary route copy. Updated
clusters/homelab/apps/traefik/canary/routes.yaml to exactly match the reviewed
live-source route file, preserving the existing byte-equality test. The second
full run passed all preceding offline fixtures, including AdGuard, route,
signing, private DNS, targeted apply and recovery tests, but failed the exact
credential-bearing workflow hash in offline-static-checks.sh.

Reviewed the complete validate.yml: the only introduced change is a repository
job step running the isolated pinned-image AdGuard fixture. No permission,
credential exposure, event, action pin, existing job or credentialed-job inventory
changed. Updated only validate.yml's normalized JSON SHA256 in the existing
security hash table. This keeps the exact-hash enforcement; no check bypass.
A third complete run must validate this repaired source. Logs outside the repo:
adguard-integration.log and adguard-integration-repaired.log record both failures.
No full-gate pass, real backend plan or live deployment is claimed.

Earlier focused evidence remains: 11 manifest/init,12 checker,21 cutover/rollback,
4 recovery-boundary,7 pinned-image runtime,30 signing,34 targeted apply,3 SSM and
6 Tailscale module tests passed. Module tests used mocked providers/backend-free
init; real SSM and administrator DNS plans require their existing authorized
credential paths. Local AWS config has no named profile, and the conventional
homelab Tailscale administrator directory is absent. The declared apply pipeline
owns live planning; do not invent a successful local real-backend plan.

Read-only prerequisite checks November16 found external-secrets, tailscale,
tailnet-dns, platform-storage and Harbor Synced/Healthy at48e8b9e4. Traefik has a
ready1/1 Deployment but remains Synced/Progressing: codex-signer has no LB address
or proxyPod. Operator logs repeatedly report OAuth401/API token invalid when
provisioning it. Existing proxies being ready does not prove new enrollment.
The existing tailscale-operator-oauth-rotate.py path requires an Owner/Admin API
key file and a named AWS SSM-authorized profile. User was asked asynchronously
for the administrator environment or existing private paths/profile, not secret
values; answer pending. No repair attempted without those credentials. The
owning ingress wiki records the incident and declared repair path. T033 remains
open. T003 publication run43777917412 remains pending, sole watcher80837.

Next: finish repaired full gate, record exact result, separate integration
convergence, then protected delivery when publication succeeds. No Notion writes.


## Completed local validation, November 17 UTC

The resumed full validation completed all three Nix checks: offline-tests,
manifest-policy and openwiki-setup, along with stack generation and HCL
format/validation. Store outputs are recorded in adguard-integration-resumed.log.
The subsequent signature test stopped because the restarted environment lacked
nix-store; the offline check itself passed. Supplied Nix2.34.7 ephemerally through
the project devShell and locked nixpkgs29916453413845e54a65b8a1cf996842300cd299.
No global installation, flake or lock edit. The resumed static script used its
declared --offline-verified option, preserving the completed Nix checks. Signed
cache import passed, unknown-key and unsigned imports were rejected.

Static validation then passed its remaining regression tests and stopped at a
Gitleaks false positive in a provider CHANGELOG under the prior backend-free
aws-ssm-parameters .terraform test cache. Moved that generated provider directory
and the equivalent tailscale-access provider cache outside the checkout into
private/provider-test-cache under the progress directory. No scanner rule or
source exemption changed. Full repository/history secret scan then passed.

Executed the unchanged remaining Checkov section from static-checks.sh and the
final conftest-policies.sh command through the project shell. Terraform/Kubernetes
scans passed; secrets scan selected1695files with25existing reviewed findings and
zero unreviewed findings. Conftest passed39406/39406 checks with zero warnings,
failures or exceptions. Remaining-static execution exited0. These are completed
phases after two environment/cache corrections, not a claim that the initial
single nix-run invocation exited0. Logs are adguard-static-resumed.log,
adguard-secret-scan-final.log and adguard-remaining-static.log in the private
workspace progress directory.

Application/code/docs diff SHA256 excluding specs and active-feature metadata:
5bab8b9f4eea3fc85816878c344cbce1c493a33a48b52e0160be950ae0873081,
base48e8b9e4627f4a37f30d00f2d28b96d64133996e. Runtime fixture7tests and all focused
checks listed above remain valid; only documentation, mirrored canary route and
workflow-review hash changed afterward. T030 source validation is complete with
real-backend-plan/live-acceptance limitations still explicit. Next separate
scoped integration convergence, then T031 only after T003 publication succeeds.

Correction to prior access assumption: the user directs using the managed cloud
AWS OIDC connection. Its v1 manifest selects profileAWS and the managed config,
not ~/.aws/config. Retained inherited auth/proxy/CA bindings. Both STS regions
and a metadata-only exact SSM DescribeParameters call fail; the latter returns
503 identity_exchange_failed even after environment restart. Connection metadata
reports ready but actual AWS access is not verified. No static AWS keys requested,
no SSM values read, no AWS writes. Real plans remain unavailable until the managed
identity exchange works. Do not assume a new Tailscale client must be minted until
existing protected SSM credential state can be checked safely.
