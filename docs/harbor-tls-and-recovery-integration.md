# HOME-57 integration: TLS and operator recovery

**Repository-only candidate. HOLD merge and activation.** Integrates QA #1164
`bbd4165fd21251ec89a284588f2967ffe5935862` and Recovery #1165
`50a2ce441aa36b78defc6bfc17e1dd89d348697f`, preserving their commits and artifacts.
Main was reconciled at `0ad30199ed7fde70832410af39db74dbbbc1ba19`, including Wazuh
#1153 and Langfuse #1167. Recovery's interruption limits remain proposals.
Neither those artifacts nor the checks here establish server authorization.

## HOME-59 transport implementation

The unregistered `clusters/homelab/apps/harbor-tls-candidate/values.yaml` enables
frontend and internal TLS on pinned Harbor chart 1.19.2/application 2.15.2.
`scripts/harbor-tls-render.py` verifies the chart archive SHA-256 before rendering
the current base plus that overlay. It fails closed if expected chart resources,
upstreams or the one insecure API override differ. The chart's
`templates/nginx/configmap-https.yaml` explicitly turns API verification off;
enabling `internalTLS` alone does not meet HOME-59.

The renderer removes that override, configures CA verification and explicit SNI
for every proxy location, disables upstream retries, and removes the plaintext
redirect listener and Service port. Configuration changes get a Pod-template
checksum. Separate cert-manager Certificate resources specify each component's
identity, private key rotation and 90-day leaf/30-day renewal lead time. An
unregistered CA Issuer references an externally supplied CA Secret; this tool
does not create a trust root or access existing keys.

| Hop | Connect destination | Verified peer identity and trust |
| --- | --- | --- |
| Collector → gateway | Existing gateway Service:443 | `harbor.stinkyboi.com`, public roots in collector image, TLS ≥1.2; existing collector code |
| Gateway → frontend | `harbor.harbor.svc.cluster.local:443` | DestinationRule SIMPLE TLS; SNI and SAN `harbor-frontend.harbor.svc.cluster.local`; gateway-local CA-only Secret `harbor-frontend-trust` |
| Frontend → core | `harbor-core:443` | NGINX `$proxy_host=core` maps to `harbor-core`; explicit CA verification, SNI and TLS ≥1.2 |
| Frontend → portal | `harbor-portal:443` | NGINX `$proxy_host=portal` maps to `harbor-portal`; same verification; unmatched upstream fails name verification |

NGINX receives **only public CA bytes** through ConfigMap `harbor-backend-trust`
key `ca.crt`, mounted read-only. Gateway Secret `harbor-frontend-trust` in
`istio-system` must contain only `ca.crt`, not a private key. The CA private key
stays exclusively in `harbor/harbor-internal-ca`. Each leaf Secret holds its own
`tls.crt`, `tls.key`, `ca.crt`; no leaf or gateway wildcard private key is copied
between workloads. The frontend leaf has the SAN above; internal components
have short, namespace-Service and full Service SANs.

**Missing activation plumbing:** a reviewed CA creation/custody and public trust
distribution path; Argo materialization/post-render integration; exact rotation
revisions; enforced port/identity policies; and client migration. The renderer
supports `--check` only and suppresses generated Helm secret content. Its
40-resource in-memory result is an inspectable implementation, not an apply
artifact. No candidate is registered in the Application or stack. Do not use
an ad hoc apply or introduce a controller/plugin to bypass these prerequisites.

Offline verification (inside the repository Nix shell with PyYAML):

```sh
python3 -I scripts/harbor-tls-render.py --chart /path/to/harbor-1.19.2.tgz --check
python3 -I scripts/ci/harbor-tls-test.py --chart /path/to/harbor-1.19.2.tgz
python3 -I scripts/ci/harbor-vulnerability-recovery-test.py
```

`scripts/ci/harbor-check.sh` also runs the TLS tests and QA render checker on
its downloaded, hash-verified chart. Tests inspect the real Helm-rendered NGINX
configuration, trust mount, Service, DestinationRule and Certificate identities;
mutations removing verification/trust or reopening HTTP must fail. Ephemeral
loopback certificates test correct SAN/trust success, untrusted CA, wrong SAN
and plaintext failures at each of the four identity contracts. These use Python
TLS, **not running Envoy, NGINX or Harbor**, and do not prove generated Envoy
configuration, SDS namespace access, image trust stores or runtime reloads.

Before acceptance, the separately approved isolated topology must run the pinned
proxy images and Harbor. Capture sanitized Envoy cluster TLS context (SNI, exact
SAN matcher and SDS validation context), NGINX effective configuration, and
peer-chain fingerprints without credentials. Verify each hop independently:
healthy read positive control; wrong CA/SAN, expired/missing leaf/trust and
plaintext negative controls; no synthetic Authorization bytes reaching the
failed upstream; no redirect/retry fallback. Complete leaf rotation with
unchanged CA and then staged CA rotation (old+new trust, new leaves, verified
traffic, old trust removal, old leaf rejection). Explicitly restart/revise
NGINX and Harbor Pods through approved GitOps because mounted certificates and
subPath configuration do not establish reload. Confirm gateway SDS rotation.
No runtime rotation or expiry result is supplied by the local tests.

## HOME-62 replacement custody and recovery contract

HOME-62 **rejected** the one-day system issuer as a containment boundary.
The historical issuer payload and algorithm remain for source review only.
The credential workflow job is hard-disabled and helper execution rejects even
if all JSON gates become true. No reusable management credential may be injected
into this general runner; do not reinterpret timeout or expiry as server-side
ID confinement. No replacement authentication/custody path is established yet.

The proposed fallback is an operator-mediated session, not another service or
broker. Before implementation, name the supported login mechanism and custodian,
its actual broad server authority, signed procedure revision, exact operation,
immutable robot ID (or separately reviewed first issuance), observed SSM version,
absolute credential expiry, approval start/end, isolated ephemeral custody and
independent termination verifier. General CI must never receive the Harbor
management credential. The exact single-parameter SSM/ESO/IAM contract in the
[lifecycle document](harbor-vulnerability-credential-lifecycle.md) is retained
as a proposal; transferring it to a new custody path requires a new IAM/OIDC
review, not silently reusing the rejected workflow. SSM has no CAS; enforce one
approved writer outside the helper and freeze on any version drift.

`scripts/harbor-vulnerability-recovery.py` is a standalone, metadata-only
planner with **no network, credential reader or mutation adapter**. Its committed
contract has every execution/authority switch false; `--execute` always fails.
`--evidence` accepts only the exact fields shown by the synthetic tests. No
password, token or raw server response belongs in that file. It identifies
required evidence/actions, never reports a disable or recovery as performed.

| Observed state | Required separately protected procedure |
| --- | --- |
| Known exact enabled ID, matching name/scopes | Approve disable for that ID only; preserve permissions/duration; independently GET exact ID and verify disabled. No enumeration/name adoption or automatic retry. |
| Lost mutation response or unknown outcome | Retain zero exporter; independent ID/SSM/audit readback; do not repeat POST/PATCH/PUT or infer success from job failure. |
| Disabled or expired identity | Retain disabled; reconcile expiry and current secret custody. Fresh secret plus absolute-expiry review if secret lost/expired; normal renewal is not a repair path. |
| SSM version/envelope-ID drift | Freeze publication; reconcile provenance and sole-writer ownership; never overwrite or restore an older parameter version automatically. |
| Secret refreshed but SSM not confirmed | Keep robot disabled; independent version/identity and custody evidence; secret lost means new separately approved rotation, not old-token restoration. |
| SSM published but enable/ESO uncertain | Keep zero exporter; verify exact envelope version and ESO projection without printing values; separately approve enable only after current-token proof and TTL checks. |
| Issuer unavailable | Route named custodian and HOME-62 authority review; no admin fallback into CI. |
| Suspected compromise | Disable exact identity, contain consumers, independently test old credential and existing bearer/session survival; separately revoke issuer/child. Availability rollback never restores compromised credentials. |

Stopping Pods or disabling an identity is not proof of bearer revocation.
Every session must return sanitized exact-ID before/after metadata, approval
record, audit-event references, SSM versions, expiry and independent containment
receipt. Unknown outcomes remain unknown. Five-minute mutation, 20-minute
cutover and 15-minute renewal interruption bounds are **unapproved proposals**.
No automatic enable, retry, name adoption, old-secret restoration or new robot
creation is implemented by this planner.

## Capability evidence still required

Extend QA's pinned fixture under separate review; its current collector-denial
suite cannot establish issuer containment. The following is a proposed matrix,
not observed permission results:

| Direct server capability | Target positive control | Boundary evidence |
| --- | --- | --- |
| Exact-ID refresh/update/disable | Intended child changes and exact readback | Unrelated system robot: denial plus unchanged secret/state, followed by authorized control |
| Issuer self-update | Authorized disposable admin can update | Issuer self permission expansion, duration extension and never-expiring duration; trace persistence, not only handler checks |
| Child create/update | Exact two project list scopes | Extra project/system permissions and excessive lifetime; unchanged state for denied mutations |
| Project-scoped alternative | Both required project reads | Enumerate project-wide residual authority; self/unrelated changes and cross-project denial; no accepted substitute yet |
| Expiry/revocation | Credential works before boundary | Old Basic and previously minted bearer requests after expiry/disable/rotation; independently observed termination |

Require valid identical admin positive controls, isolated identities, current
state observations before/after and pinned-source tracing beyond the handler.
Do not add a fixture execution switch or dispatch based on this matrix.

## Integration and operational blockers

- HOME-3 #1116 remains `7eaf44c2fa6b6cb7eb2b20e084ba3ed1d70d9a98`, open;
  refresh its additive matrix with exporter→gateway443, gateway→frontend8443,
  frontend→core8443/portal8443 and chart-internal TLS destinations. Verify actual
  Service target ports, all nodes and Pod identities before enforcing. Existing
  8080/5000 policies are not migrated by this candidate. Shared gateway/DNS and
  local-node exceptions remain residual trust; L3/L4 allowlists cannot prove
  credential non-exfiltration. Wazuh is now on main and must be in the matrix.
- #1156 advanced to `b6f332a14dac69861a17a325450fbfbf8096cee6`; account for its
  caller graph separately. #1159 `ffe29338564e4819c370b9e4bd925c2384fd5b16` and
  #1162 `1d1caad4305c256201c521442dc98507b0f29b52` still overlap inventory/CI/KB;
  preserve their gates. PyYAML Nix changes also overlap #1116/#1162.
- Wider Harbor changes affect bootstrap/backup/signing hooks, OCI push/pull,
  token issuance, UI, jobservice, registry, scanners and metrics. Inventory every
  HTTP client and trust mount; no client may fall back to plaintext. No backup
  restoration/readiness or client compatibility is established here. Preserve
  all PVCs. Scope this TLS candidate to the collector's HTTP path; database and
  Redis transport are not claimed encrypted.
- Retain Recovery's exporter-only zero delta and prove all old admin-mounted
  Pods/ReplicaSets are gone before starting a robot Pod. Full Harbor sync may
  run bootstrap/backup hooks; approve exact hook behavior, not an overlay apply.
  First cutover has no accepted robot/TLS rollback; safe fallback is zero
  exporter plus visible alerts, never the old admin-over-HTTP revision.
- Missing: approved issuer/custody design; concrete disposable environment
  provision/teardown revisions; real server-denial, proxy/TLS rotation, expiry,
  alert-routing and independent expiry-watch evidence; signed integration and
  operational revisions. Full Nix/static/policy/provider checks remain required.

Decision Desk execution approval is **not requested yet**: the environment and
operational artifacts are not concrete. Once those and independent reviews
exist, present one exact environment/run/teardown request (QA's ≤4 CPU/8 GiB/
20 GiB, 20-minute run/25-minute outer bound, dispose ≤4h), then distinct exact
signed cutover, renewal and compromise-recovery requests with named observers,
IDs, SSM versions and interruption limits. HOME-62 owns replacement authority;
HOME-59's all-hop requirement is already decided. No serious risk acceptance or
CEO escalation is requested while HOLD is available.
