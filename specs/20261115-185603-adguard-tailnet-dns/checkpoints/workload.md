# Direct filtering workload source — T008–T013

2026-11-16. Canonical branch feat/adguard-tailnet-dns, base
48e8b9e4627f4a37f30d00f2d28b96d64133996e. Unmerged source only.

The preceding separate foundation convergence reviewed T004–T007 and the five
constitution principles without corrections or artifact changes. This records
that result; it does not claim convergence for the new workload increment.

Implemented the pinned AdGuard workload, DNS-only Tailscale LoadBalancer,
private ClusterIP administration, retained 1Gi NFS cache, intended NetworkPolicy,
and an explicit note that current Flannel does not enforce that policy. Main
process launches directly as UID65534 with read-only root, no service account
token, ALL capabilities dropped except NET_BIND_SERVICE. Init validates schema34,
exact single bcrypt admin and upstreams, resolves the fixed private resolver and
atomically writes mode0600 configuration. ESO renders a generated32-character
SSM credential through bcrypt with OnChange/revision-driven reconciliation.
Query history, statistics and discovery are disabled. No credential was read.

Added manifest/init fixtures and actual pinned-image runtime fixtures before
implementation (red evidence retained in adguard-manifest-red.log and
adguard-runtime-red.log). Runtime checks exercise UDP/TCP blocking, permitted
A/AAAA, private answers, NXDOMAIN, private SERVFAIL isolation, empty-cache
readiness rejection and active plus disk-cache retention on failed refresh.
The exact capability profile works with direct binary startup; the initial
shell wrapper dropped capabilities and was replaced in the fixture. Docker uses
local unix:///var/run/docker.sock; synthetic ports bind localhost. Fixtures use
the public upstream image at the identical pinned digest, not a claim of Harbor
publication. Manifest suite is in offline checks, runtime suite in required repo CI.

Policy initially rejected the SSM path; added an exact automation/adguard-config
credential exception with positive and negative tests, no namespace-wide prefix.
Validation: 11 manifest/init tests and4 runtime tests pass;147 policy unit tests
and488 rendered workload/workflow checks pass; Checkov7 selected manifests/workflow
has0 unreviewed findings; actionlint and140-image-reference coverage pass;
git diff --check passes. A secret scanner flagged the synthetic fixture string;
replaced it with deliberately weak repeated fixture data, reran both suites and
the4-file secret scan, all pass with0 findings. No scanner suppression added.
Logs: /workspace/adguard-progress/adguard-workload-checks.log,
adguard-policy-final.log and adguard-fixture-final.log.

T003 remains pending: publication run43777917412 was still copying/verifying
images at00:58UTC, monitored solely by watcher80837. No consuming merge, live
SSM/Application or DNS change occurred. T014 onward remain pending.
Next separate turn: scoped convergence on T008–T013, then direct endpoint and
read-only live acceptance support. Continue the same publication watcher.
No Notion updates, as requested. Extension hooks are empty.
