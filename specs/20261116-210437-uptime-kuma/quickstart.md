# Validation and rollout guide

Run these implemented helpers from repository root using the repository's Nix shell
when a required binary is absent. Never install packages into runtime Pods.

## Before delivery

```sh
python3 scripts/ci/uptime-kuma-check.py
nix develop --command python3 -I scripts/ci/uptime-kuma-check-test.py
node --test scripts/ci/uptime-kuma-test.js
python3 -I scripts/ci/uptime-kuma-backup-test.py
bash scripts/ci/uptime-kuma-integration.sh
bash scripts/ci/uptime-kuma-backup-integration.sh
kubectl kustomize clusters/homelab/apps/uptime-kuma
helm template uptime-kuma app-template \
  --repo https://bjw-s-labs.github.io/helm-charts --version 4.4.0 \
  --namespace monitoring --values clusters/homelab/apps/uptime-kuma/values.yaml
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
```

Required behavior tests: duplicate/unknown/missing app coverage, stale/missing
metrics (including a 15-second source scrape: age 30 seconds is eligible, age
31 seconds fails even though below 120), login redirect rejection, unowned
monitor preservation, repeated add
ack uncertainty, no-op second reconciliation, retired monitor pause, existing
account preservation and failed login. Run real native API tests against the
pinned image with disposable data and no cluster credentials. Test SQLite online
backup while WAL writes occur; restore into isolated storage and verify history.
Render and plan the generated app unit; exercise targeted apply/mirror negative
tests before enabling the new fixed scope. Record unavailable checks honestly.

## Protected delivery

Deliver image prerequisite first through normal PR checks and merge. Set
`reviewed_sha` to exact current reviewed main, then:

```sh
gh workflow run harbor-mirror.yml --ref main \
  -f expected_sha="$reviewed_sha" -f image_scope=uptime-kuma
```

Wait for successful complete publication/pull receipt. Deliver consuming app
source next. Refresh exact main after merge; ensure prerequisites are actually
Synced/Healthy, local-node headroom exists and required storage is available.

```sh
gh workflow run terragrunt-apply.yml --ref main \
  -f expected_sha="$reviewed_sha" -f argocd_app=uptime-kuma
```

Use the protected saved-plan lane; inspect failures and correct source. Do not
force-sync, patch resources or inject credentials manually.

## Functional acceptance

```sh
python3 scripts/verify-gitops.py --application uptime-kuma \
  --expected-sha "$reviewed_sha" --deployment monitoring/uptime-kuma
kubectl -n monitoring get externalsecret uptime-kuma-admin
kubectl -n monitoring get pvc uptime-kuma-local uptime-kuma-backups
kubectl -n monitoring exec deployment/uptime-kuma -c reconciler -- \
  node /config/reconcile.js verify
kubectl -n monitoring exec deployment/uptime-kuma -c reconciler -- \
  node /config/reconcile.js acceptance
```

The last command executes the repository-owned bounded test fixture; it is not
permission to mutate other live apps. Verify every active monitor has at least
three observations, and reconcile the current live Application-name union
against committed coverage. Existing failed targets may correctly show down;
record those separately. Open the private hostname from a mesh client, sign in,
confirm visible history and test an unauthenticated administrative API request
is denied. Never put credentials or private screenshots in public receipts.

Run `once` twice through the sidecar and require the second pass to report zero
changes and unchanged IDs. Perform the planned one-time restart by changing a
repository rollout annotation through normal GitOps; verify saved history.
Require the declared initial backup and isolated restore Jobs to succeed with
checksums, native login and saved observations. Check a scheduled backup also
runs when its first window arrives; report scheduling separately if outside the
acceptance window. Repeat revision verification after behavior checks.

Rollback uses reviewed desired state, retains all PVCs and pauses the writer
before any database restore. Match image/schema to backup. Record final revision,
coverage counts, known target outages, test receipts and recovery limitations in
the same issue; no completion based solely on Argo health.

## Restore execution-fence acceptance (P1 repair)

The existing Docker `--network none` test still proves filesystem/SQLite behavior;
it cannot prove the deployed Job's network safety. The implemented backup
integration script also exercises the following network-enabled fixture, without production credentials or external services:

1. Use a disposable bridge network with verifier and independently counted
   probe/notification sinks. Prove connectivity from the verifier's network
   namespace. Seed a native account, active HTTP monitor, notification binding,
   history, and enabled updater/tunnel settings in disposable data. A separate
   unfenced positive-control copy must generate the expected sink requests;
   never use a production target or real tunnel token.
2. Capture archive hash and original account/monitor/history evidence. Run verify
   on another clone with the network enabled. Observe for at least two configured
   monitor intervals, covering native startup. Native login and saved-history/ID
   checks must succeed, every monitor must remain paused, and probe/notification
   sink counts must remain unchanged. The untouched archive hash must match.
3. Exercise actual pinned updater and cloudflared startup guards with instrumented
   test doubles/counters for their external call/launch boundary. Positive controls
   with unsafe settings prove the counters observe execution; fenced settings
   yield zero updater HTTP calls and zero tunnel launches. The test does not
   contact public updater/tunnel services. Confirm the native image's source hash
   or exact expected guard semantics, so a changed pin cannot silently reuse proof.
4. Negative cases: unknown schema/columns, duplicate setting keys, missing or
   incorrect post-fence settings, post-fence active/null flags, remaining notification
   bindings, process spawn before fence success, and inherited NODE_OPTIONS or
   tunnel/proxy overrides. Every case must fail before native server startup;
   intentional mutation of any fence operation must fail the tests.
5. Rendered Job must use dedicated uptime-kuma-restore identity without API-token
   mount or backend grants, only read-only backups/config/credential and emptyDir
   writable data; no production PVC. Keep declared deny-all policies but label
   current enforcement limits. Native server binds loopback only, and verification
   invokes no setup/reconcile/resume/test-notification/settings-write operations.

Record this as application execution fencing, not general network isolation.
If a startup pathway remains unassessed or the fixture cannot prove suppression,
leave the restore acceptance incomplete and repair the owning design/source.
