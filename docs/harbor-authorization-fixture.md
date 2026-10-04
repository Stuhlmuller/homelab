# HOME-57 disposable Harbor authorization proposal

**HOLD. Repository-only proposal; no server fixture has been provisioned or
executed.** This is an independently owned companion to SRE's #1163 at
`5e094909dd90404b6dcedf79bf5f72ca4bc70c44`. Integrate this branch's changes,
not a replacement for SRE's transition/lifecycle work. HOME-59 requires verified
TLS on every credential-bearing production hop and grants no gateway-only
exception. This fixture does not establish that production transport design.

## Delivered fixture and runner

- `scripts/fixtures/harbor-authorization/values.yaml`: a standalone disposable
  chart-values proposal, **not an overlay on production values**. Internal
  database/Valkey, ephemeral storage, no Trivy/database downloads, no public
  ingress, verified client TLS, internal TLS enabled. External fixture TLS and
  the fixture administrator use newly generated, test-only Secret references.
  No production Secret, ESO, SSM, IAM, PVC, gateway or kubeconfig is an input.
- `scripts/fixtures/harbor-authorization/lock.json`: chart 1.19.2 / Harbor
  2.15.2, archive SHA-256 and eight component image digest pins. Seven pins match
  the reviewed repository; the internal database pin was resolved from the
  upstream Docker registry's v2.15.2 manifest. The chart archive was read from
  [the official chart repository](https://helm.goharbor.io/harbor-1.19.2.tgz).
  Record the actual rendered/runtime image inventory before approving execution;
  a desired-state lock alone is not runtime evidence.
- `scripts/harbor-authorization-fixture.py`: standard-library runner with an
  offline default. Configuration has `execution_enabled: false`, no decision,
  and no environment record. Execution refuses those conditions **before any
  credential read or network access**. No workflow automatically runs it.
- `scripts/ci/harbor-authorization-fixture-test.py`: offline tests of failure
  classification, state assertions, pagination, protocol boundaries, endpoint
  guards and execution gates. These run in the existing static gate and do not
  instantiate Harbor or provide server authorization evidence.

The runner uses only `https://127.0.0.1:8443`, pinned fixture CA bytes, IP SAN
verification, TLS 1.2 minimum, and direct sockets. It ignores proxy environment
settings. Redirects, remote registry token realms and remote upload Locations
are rejected. There is no HTTP/insecure fallback or automatic request retry.
**Loopback is not proof of isolation:** an operator could forward production to
loopback. Decision Desk must verify an isolated disposable environment and its
connection path; the script's guards do not replace that evidence.

On an approved empty server, setup refuses existing repositories, robots or
projects other than empty default `library`. It creates private `homelab`, public
`mirror`, private `qa-private-other` and public `qa-public-other`. Both allowed
projects have 102 repositories and 101 distinct artifacts in `nested/seed`,
exercising both 100-entry pagination boundaries. There are 206 repositories and
406 seeded image references across the four projects. OCI config and manifests
are deterministic and contain no layers, executables or real workload data.
Scanning is deliberately disabled for this initial RBAC subset.

Setup creates the exact proposed `vulnerability-robot.json` identity, checks
immutable ID/name, enabled state, system level, 30-day expiry and returned
project permissions. The generated robot secret remains only in process memory.
One additional robot is created by the administrator positive control. Local
helper restrictions are not a security boundary: the runner directly calls
Harbor and registry APIs with the collector credential, bypassing its Client.

## Assertions implemented

| Area | Evidence the runner requires |
| --- | --- |
| Allowed reads | Both project's repository and nested artifact pages match independently read administrator fixture IDs/digests and exact expected counts. |
| Cross-project | Administrator confirms private targets exist; collector receives 403 plus Harbor authorization error, anonymous private access fails, public controls succeed. |
| Global listing | Exhaust pages of `/projects` and `/repositories`; no unrelated private project/repository appears. A filtered 200 is not failure. |
| Admin reads | `/users` and `/configurations` deny the collector while the administrator succeeds. |
| Repository/artifact/tag mutations | PUT requires the requested description; DELETE requires the exact repository ID/artifact digest to disappear; POST requires exactly one new tag with the requested name and artifact/repository IDs. Other observed records must remain identical. |
| Robot administration | POST requires exactly one new ID matching the response and requested name/scope/lifetime fields; PUT requires the exact requested permissions. Other robot records remain identical. Administrator scope restoration uses the same field-specific oracle. |
| Configuration | PUT toggles project-creation restriction only on the disposable instance; verify denial, unchanged value, effective positive control and restore. |
| Registry pulls | Existing private manifest and config blob deny the collector while administrator succeeds. Public mirror content matches successful anonymous baseline. |
| Registry pushes | Valid manifest PUT denies collector, preserves artifact inventory, then administrator creates the expected tag. Upload POST/PATCH/PUT deny collector; valid administrator upload sessions provide positive targets; append/commit preserve upload offset and blob absence after denials, then controls append/commit exact bytes. |
| Authentication | Private read succeeds immediately before denied requests, distinguishing bad credentials from authorization. Wrong password and administrator-disabled identity must return 401. |

REST denial requires **403 plus FORBIDDEN/DENIED**. Registry denial may be
401/403 with UNAUTHORIZED/DENIED after a successful private REST identity
control. A token-service 200 is not acceptance: the runner uses the token on the
actual registry request. Invalid bodies, missing targets, conflict, proxy-cache
405, redirects, timeouts and server errors fail the case, rather than counting
as denied access. Projects are ordinary repositories to avoid proxy-cache
restrictions masquerading as RBAC. This differs from the production mirror and
must be recorded as a fixture limitation.

For denied upload initiation, the observable assertions are no upload Location
and unchanged artifact references. They do **not** prove absence of an orphaned
upload on disk; backend state inspection remains required if that stronger
claim is needed. The full-state comparisons intentionally tolerate no unrelated
mutations: disable automatic scans and other actors or treat drift as an
inconclusive run. Do not weaken comparisons to make the fixture pass.

The original positive-control check accepted any changed observation. Independent
review reproduced a false pass when only `update_time` changed. The corrected
oracle requires the operation-specific effect above; a timestamp alone cannot
satisfy it. Only the mutated target's `update_time` may differ incidentally;
unrelated timestamps and unrequested target fields remain protected. Configuration
checks compare the entire map against the exact one-value change and restore.
Registry manifest checks bind the new tag to the exact artifact/repository and
cross-check tag-list and artifact-summary readbacks. These are bounded observed
collections, not a claim to inspect every server object or backend byte.

HOME-62's separate [issuer capability proposal](harbor-issuer-capability-proposal.md)
prepares direct-API cases and offline evidence oracles only. It does not add an
issuer credential reader, network adapter or execution path to this general
collector fixture. The existing administrator input remains **test-only** for
the independently approved disposable server; it must never be a reusable
production management credential. No supported production custody path is
established by either proposal.

## Full-acceptance cases still requiring fixture integrations

The runner always emits `overall_acceptance: incomplete` and exits **2** after
a successful implemented subset. Exit **1** means a gate/test/transport failed;
exit **0** is only the offline contract check. Never convert exit 2 into full
acceptance or use `continue-on-error` to hide it.

1. **Scan creation and summary oracle:** add a repository-owned deterministic
   scanner adapter, pinned image and synthetic reports. Register it only in the
   approved fixture. POST `/api/v2.0/projects/{P}/repositories/{R}/artifacts/{D}/scan`
   with the collector must return authorization denial, preserve scan report/task
   state, then the administrator's identical POST must return 202 and create a
   new task. Obtain completed reports with known critical counts including zero
   and confirm both paginated GET totals match the real collector. This proposal
   neither registers a scanner nor claims scan-create denial coverage.
2. **Expiry:** prepare a separately reviewed pre-aged robot/database fixture
   compatible with Harbor 2.15.2, or approve a longer-lived disposable test across
   actual expiry. Harbor's documented minimum positive duration is one day;
   a 20-minute run must not falsely call disablement an expiry test. Do not alter
   the host/cluster clock or bypass the real authorizer. Verify success before
   expiry, 401 after, and administrator confirmation of exact identity/expiry.
3. **Collector integration:** mount only the fixture robot in the actual collector
   image, inject a second-project failure, and prove unchanged last-success,
   no partial fresh totals, stale totals removed after 360 seconds and real
   `/metrics` HTTP 503. Restore the same scope and observe two healthy intervals.
   Prometheus/Grafana alert routing needs its own synthetic integration.
4. **Transport/isolation:** negative CA/SAN/expiry/plaintext and rotation tests on
   every HOME-59 credential hop plus HOME-3's final every-node/replacement-Pod
   matrix remain distinct. Chart internal TLS enabled is not verified upstream
   identity validation. This fixture has no shared Istio/Octelium gateway and
   cannot establish their behavior.

These are explicit unimplemented integrations, not optional waivers. The
initial authorization subset provides useful narrower evidence and cannot
release HOME-57 by itself.

## Exact request prepared for Decision Desk

**Requested decision:** authorize preparation of a one-shot disposable test
environment and one execution of the implemented authorization subset, only
after the following activation record is reviewed. No provisioning or execution
is authorized by this document or by approval to prepare repository code.

Scope proposed for approval:

- Owner: Homelab QA & Release Engineer; SRE reviews the environment provisioning
  revision. One isolated existing test machine/VM, maximum 4 vCPU, 8 GiB RAM,
  20 GiB ephemeral disk, four-hour lifetime. No new paid resource or external
  commitment. If unavailable, return to Decision Desk; do not reuse production.
- Pin and approve the disposable Kubernetes/runtime provisioning revision and
  node image separately. No production routes, credentials, host Docker socket,
  kubeconfig, cloud credentials, NFS/PVCs, or metadata-service access. Permit
  public image/chart downloads during setup only; isolate egress before tests.
  Bind the fixture service solely to 127.0.0.1:8443 on that machine. No public
  Ingress/LoadBalancer, DNS changes or cluster registration.
- Use only the chart archive and eight images in `lock.json` and the standalone
  values. Generate a test-only CA and server certificate with IP SAN 127.0.0.1,
  create fixture TLS/admin Secrets through the reviewed provisioning code, and
  supply mode-0600 administrator JSON `{username,password}` plus CA file. Do not
  use the chart's example administrator password, production passwords or shared
  robot secrets. Keep credentials, generated Helm render Secrets and logs private.
- Approve creation of the four exact projects and 406 seeded image references,
  the scoped collector robot and one positive-control robot; administrator test
  mutations are limited to those resources and the disposable configuration
  toggle. No real artifacts, users, external registries or production mutations.
- One serialized invocation, no automatic retries, 20-minute request deadline
  with an independent outer 25-minute process timeout. Stop on the first
  unexpected result. Do not retry partial setup or adopt existing resources.
- Destroy the **entire dedicated environment** through its approved provisioning
  teardown within four hours, including credentials, chart-generated keys,
  volumes and uploads. Teardown must run after success, failure or timeout and
  be verified by the provisioning owner. The runner intentionally does not
  delete arbitrary Kubernetes resources or promise cleanup after process death.
  A failed teardown is a blocker, not permission to target a shared environment.
- Preserve only sanitized case IDs/verdicts, lock/runtime image digests, reviewed
  revision, start/end times, fixed failure category and disposal confirmation.
  No API response bodies, passwords, bearer tokens, manifests or raw logs are
  uploaded. Record server authorization separately from HTTP proxy behavior.

Required activation record: exact **signed** candidate SHA; approved environment
provisioning/teardown SHA; Decision Desk issue; chart archive digest; observed
component image map exactly matching `lock.json`; owner and disposal deadline;
fixture CA SHA-256; evidence that instance is empty, synthetic-only and has no
production routes. Populate `environment_record` and turn `execution_enabled`
on only in that separately reviewed activation change. `--expected-sha` must
match the clean checked-out revision. Code cannot authenticate a decision or
runtime isolation assertion: the approval record and independent review matter.

Commands for that **later approved revision only**, using private runtime paths
outside the checkout (placeholders are not approved execution inputs):

```sh
timeout 25m python3 -I scripts/harbor-authorization-fixture.py --execute \
  --expected-sha <signed-approved-sha> \
  --admin-file <private-disposable-admin-json> --ca-file <fixture-ca-file>
```

Provisioning/teardown code, environment selection and that activation record are
not yet supplied; therefore this request is **prepared, not execution-ready**.
No production lifecycle workflow dispatch, merge, rollout or residual-risk
acceptance is included. SRE retains #1163 integration; Recovery retains its
separate cutover/revocation proposal.

## Safe local validation

```sh
python3 -I scripts/harbor-authorization-fixture.py
python3 -I scripts/ci/harbor-authorization-fixture-test.py
python3 -I scripts/ci/harbor-vulnerability-exporter-test.py
python3 -I scripts/ci/harbor-authorization-render-check.py --chart <verified-harbor-1.19.2.tgz>
git diff --check
```

The pinned [Harbor OpenAPI contract](https://github.com/goharbor/harbor/blob/v2.15.2/api/v2.0/swagger.yaml)
defines fixture requests; source inspection and mocked tests cannot establish
that the server accepts the fixture or enforces the proposed permissions.

The optional render check requires Helm and PyYAML (pinned in
`scripts/fixtures/harbor-authorization/requirements.txt`; install in an isolated
virtual environment). It verifies the archive
hash before rendering, keeps generated Secret material only in process memory,
and asserts the exact eight-image inventory and absence of public routing,
persistent/host volumes or host networking. Rendering is local only and does
not provision a fixture or establish its runtime trust configuration.
