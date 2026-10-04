# Harbor recovery security gates (HOME-14)

Independent design review for HOME-12, 2026-09-29. Baseline and remote main
were both `a5b296da70068a666a526ff4b3656361d01157aa`. This records acceptance
requirements, not approval of a candidate, an implemented offline recovery path,
or evidence of live activation. Review the eventual candidate separately at its
exact revision when requested. No secret material or live infrastructure was read.

## Findings and evidence

- **High, availability:** `scripts/talos-harbor-mirrors.py:27-35,145,185`
  requires online current-main equality even for rollback. GitHub loss or
  advanced main prevents execution from a previously reviewed clean checkout.
  `:148` fixes the Talos proxy endpoint to `10.1.0.199` for every target.
  Losing that endpoint prevents this helper reaching surviving workers. These
  are source-proven limitations, conditional on needing this recovery path.
- **High, trust requirement for any offline replacement:** a SHA or checksum
  supplied alongside mutable files does not authenticate their reviewer or
  publisher. Existing clean/current-main checks are not a standalone signed
  recovery-bundle verifier. Removing them without a separately trusted,
  rollback-only authorization would weaken the boundary.
- **High, identity requirement:** rollback compares Talos boot UUIDs
  (`:131-135,150-153,186,197`). This establishes continuity during a run,
  not enrollment of the intended physical node. Kubernetes identity checks are
  intentionally absent during rollback. An authenticated cluster member or
  matching hostname/IP alone must not authorize another machine's recovery.
- **Preserve existing controls:** explicit private client selection and pinned
  Talos client (`:139-143`); full-document normalization and mirrors-only
  comparison (`:104-115,162-183`); recapture before apply (`:188-191`);
  no-reboot application and full readback (`:192-198`). The recapture narrows
  but does not eliminate the interval in which another writer can change config.
- **Separate transport from recovery:** `docs/harbor-image-mirroring.md`,
  Bootstrap and recovery, documents in-cluster cold-start and public
  Cloudflare/Octelium transport. The rollback patch restores upstream endpoints;
  it cannot restore Harbor-only private images, registry state, credentials,
  upstream availability or the lost sole control plane. A failed public route
  is not authorization to expose a replacement route.

## Pass/fail contract for a future candidate

Every row is mandatory within the declared recovery scenario. Missing evidence
means **not accepted**, even if the helper exits successfully. Requirements here
are proposed gates; they do not claim that the current helper implements them.

| Gate | Pass | Fail / stop |
| --- | --- | --- |
| Bundle authenticity | Offline verification against a separately enrolled public trust root binds the manifest, reviewed source revision, helper, patches, parser/runtime dependencies, target policy and rollback-only action. An independently held approved digest may anchor an explicitly reviewed equivalent scheme. | Trust root or expected digest comes only from the supplied bundle; unsigned/untrusted manifest; altered or omitted member; unsupported format. Never execute bundled code before trusted verification. |
| Freshness and authorization | Rodman's bounded authorization names the exact bundle, targets, recovery action and validity window; the operator checks a separately maintained withdrawal/replacement record and compatibility with current target state. | Arbitrary old signed bundle, expired approval, unknown revocation status under the chosen contract, clock ambiguity, or changed cluster identity. Signature validity alone is insufficient. |
| Tool closure | Verified local Talos 1.11.3, Python, yq and all runtime dependencies run without fetching GitHub, Nix caches, packages or Harbor; PATH and writable executable substitution are excluded. | A version string is the only binary integrity check; startup downloads anything; a verified file can be replaced before use. |
| Credentials | Explicit selected private client file; certificate validity, trusted cluster CA and authorization succeed for each exact endpoint/target. Private custody works without cluster/NAS/public-route recovery. | Missing/expired/not-yet-valid or wrong-cluster credentials; fallback to ambient context; insecure TLS or maintenance-mode access. No automatic renewal or rotation. |
| Node and endpoint binding | Independently recorded enrollment binds cluster identity, target node and authenticated endpoint; a version-specific identity mechanism rejects replacement nodes and wrong proxy targets. Boot continuity is additionally checked. | IP, hostname or boot UUID is the sole enrollment proof; server identity mismatch; target reached through an unapproved proxy. If robust binding cannot be demonstrated, stop. |
| Outage scope | With GitHub, Harbor, Kubernetes API and the public Harbor route unavailable, the approved rollback path reaches the declared surviving target through its verified local endpoint. Specify dependencies on LAN, upstream registries, DNS, time and certificate lifecycle. | Recovery secretly requires the failed proxy, public tunnel, online verifier or package service. Direct-worker recovery across certificate expiry/restart is assumed rather than demonstrated. |
| Configuration scope | Preserve every document and all fields except the exact approved `machine.registries.mirrors` replacement; validate strictly with the pinned real parser; recapture immediately before apply and exclude concurrent writers operationally. | Changes to credentials, TLS, registry auth, networking, storage, role or extra documents; normalized drift; unrecognized source mirrors erased without review; missing writer exclusion. |
| Execution | Explicit execution opt-in, one named node, bounded timeouts, no reboot, no retries that blindly reapply. Approval covers the full replacement map and restored upstream egress. | Dry-run mutation, multi-node expansion, unapproved endpoint/registry, reboot/drain, image deletion, broad upstream exposure beyond the reviewed patch. |
| Completion | Full persistent-config readback equals the validated candidate and boot identity is unchanged. A separately approved, initially uncached digest-pinned image pull demonstrates upstream transport without deleting caches. | Apply succeeds but readback fails, boot changes, or probe only hits cache. Report uncertain/partial state; stop the sequence and preserve evidence, never claim success or automatically re-enable mirrors. |
| Confidentiality | Restricted scratch and sanitized fixed-category errors; authored synthetic secret sentinels never appear in stdout/stderr, exceptions, attachments, metrics or CI artifacts. | Raw config, credentials, tokens, private backup content or command output reaches a public surface. |
| Activation boundary | Existing activation/publication current-main checks remain intact. Offline authority is only the approved rollback action. | Offline mode enables mirrors, publishes images, changes trust roots, rotates credentials or restores data. |

## Required synthetic negative tests

Tests must assert whether **any mutation occurred**, which endpoint/identity was
selected, the failure stage, and that private sentinels were absent from output.
Use authored fixtures and local mock services; no production credentials or live
fault injection. Passing a mocked refusal test is not successful outage recovery.

1. **Authenticity:** modify each bundle member, its checksum and manifest; swap
   the signer/trust root; use unknown signer, withdrawn or expired approval,
   wrong target/action, path traversal, symlink escape, missing dependency and
   substituted executable. All must reject before credential access/mutation.
   Also replace a file after verification to test use-time integrity.
2. **Dependency outages:** separately fail GitHub DNS, HTTPS and advanced-main
   checks, Harbor/public DNS/tunnel, Kubernetes API and `.199`; then combine
   failures. Existing activation must still refuse. A future approved offline
   rollback must succeed against a synthetic surviving authenticated target
   with no GitHub/Harbor/Kubernetes calls; unavailable target must stop boundedly.
3. **Authentication/identity:** missing client file, ambient client selection,
   expired/future certificate, wrong CA/server identity, unauthorized client,
   wrong node behind proxy, reused IP/hostname, changed enrollment and mid-run
   reboot. Assert no insecure fallback and no unintended apply. Add Talos
   version-specific certificate renewal/restart boundary tests separately.
4. **Config integrity:** unrelated field change, extra/dropped document, registry
   credentials/TLS modification, unexpected mirror entry, parser default
   changes, failed strict validation and concurrent change before apply. Assert
   zero mutation on failure and preserve full-document semantics. Use real pinned
   Talos/yq on synthetic multi-document fixtures, beyond JSON parser mocks.
5. **Partial execution:** timeout before/during apply, lost response, failed
   readback, changed boot, corrupted readback and repeated invocation. After a
   possibly successful write, report uncertainty and stop; no blind retry or
   automatic strict-mirror reactivation. Dry-run must never apply or pull.
6. **Privacy:** put canary secrets in all synthetic subprocess failure streams
   and config documents; check sanitized reporting, private scratch modes and
   cleanup on handled interruption. Document limits for uncatchable termination.

## Documented recovery prerequisites only

This inventory names references, not values. Existence, independent custody,
freshness, access and usability were **not verified**. HOME-2 owns backup
publication/recovery; HOME-15 owns activation evidence and recovery timing.

| Material | Documented source and boundary | Missing proof |
| --- | --- | --- |
| Talos operator client, cluster trust and machine recovery material | Explicit `.talos/talosconfig` or selected private file; mirror runbook and repository AGENTS.md. Do not open or package real machine configs in public evidence. | Independent accessible custody, current credential lifetime/authorization, enrolled node inventory and tested authenticated route for each target. |
| Bootstrap tools and artifacts | Mirror catalog, upstream references, Talos client pin, `flake.nix`/`flake.lock`; mirror runbook says fresh bootstrap starts upstream. | Verified offline tool closure and availability of every required image/platform digest outside Harbor. A lockfile is not a local executable copy. |
| Harbor DB/blob/key set | `clusters/homelab/apps/harbor/README.md:76-110,117-180`; DB local on acer, dumps and blobs on QNAP. Preserve matched DB/blob capture, `/homelab/harbor/secret-key`, documented SSM secret contract and `harbor-token-signing` key/certificate. | Independently retrieved matched versions, retained keys, tested PostgreSQL 18/Harbor restore and private artifact authentication. Same-NAS dumps do not establish independent recovery. |
| Image-signing identity | `harbor-image-signing` Secret, encrypted off-node etcd backup, independently held public key and `scripts/config/harbor-signing.json`; [[harbor-oci]]. This key is separate from Harbor token signing and is absent from DB/blob backups. | Matched recoverable key backup and independent historical signature verification; restore before cert-manager regenerates identity. This signer is not automatically authorized to sign recovery bundles. |
| Private NOFX images | `docs/nofx-private-images.md`, [[../architecture/secrets-and-identity]]: Harbor read-only `harbor-pull`, retained GHCR recovery with `/homelab/nofx/ghcr-read-token`. | Availability of each required current digest and valid private pull credentials independently of Harbor. Historical GHCR copies do not prove newer Harbor-only builds exist there. Registry and pull-secret changes require separate GitOps approval. |
| AWS/IaC and identity bootstrap | [[../architecture/secrets-and-identity]] and HOME-2: SSM values remain external, encrypted OpenTofu state depends on its key, AWS/operator access must survive cluster/NAS/Octelium loss. Public-route rebuilding also needs Cloudflare/Octelium credentials and identity dependencies. | Independent authorized retrieval of specific secret/state/key versions, without relying on the failed route. No secret discovery or export is authorized by this review. |
| Octelium and app state | HOME-2 `docs/application-recovery.md` at `66de4860068adb0c60a348c2e598e08dde415f65`: DB plus applicable Redis/package state and external root/encryption/identity material; paired DB/blob contracts for other apps. | Existing independent copies remain unknown; application behavior and measured RPO/RTO remain unproven. Restore containment belongs to HOME-3 before any sensitive-data drill. |

HOME-2 [PR #1113](https://github.com/Stuhlmuller/homelab/pull/1113) was open,
unmerged at the revision above. Its staged publication and synthetic validation
are not evidence that a Harbor recovery set exists. Reuse that work; do not
create another backup destination or duplicate its delegation.

## Exact approval and later evidence boundaries

Rodman must authorize a concrete execution record naming: reviewed commit and
bundle digest; enrolled targets and endpoint routes; action and full mirror diff;
credential reference (never value); validity window; node order; timeout/stop
conditions; maintenance/concurrent-writer exclusion; recovery target and accepted
limits; and the operator who executes. The proposed HOME-13 30-minute worker
transport target is not ratified or measured here. Record start/end and scope;
it is not a whole-cluster or private-data recovery objective.

Separate concrete approvals remain required for merge/deployment, mirror
enablement/disablement, new or changed routes/services, permission changes,
credential access/rotation, spending, real sensitive-data restores, destructive
actions and live fault injection. Existing mirror state must not be changed
automatically. Emergency urgency is not an approval bypass.

Before execution, agree a tested stop/recovery procedure: keep working operator
access, preserve caches/PVCs/blobs and private evidence, stop on uncertain state,
and inspect through the surviving approved route. Re-enabling strict mirrors
requires a new approved normal activation with current-main/publication gates;
never automatically restore a transport configuration that caused the outage.
The current helper's post-apply failure can leave the change applied.

Later operational acceptance needs authorized per-node mirror readback,
authenticated endpoint/identity evidence under the claimed outage scenario,
uncached transport proof, unchanged boot/full-config evidence, measured timing,
and independently retrieved recovery sets with enforced restore containment.
Public evidence contains only sanitized outcomes and source references.

## Validation and review status

The existing baseline regression passed locally:
`python3 -I scripts/ci/talos-harbor-mirrors-test.py` (one unittest, 29 named
synthetic subcases). External commands and parsers are mocked. This does not
test an offline bundle verifier, actual Talos authentication, live TLS or real
parser compatibility. Nix is unavailable, so the full repository gate was not
run. No live operation, secret read, restore or fault injection was performed.

HOME-13 [draft PR #1123](https://github.com/Stuhlmuller/homelab/pull/1123) was
open/unmerged at `78e4b59ae89879a87c9a45c7ec8a4d610f3cde8d`; its reported
45-subcase result belongs to its author, not this independent baseline run.
Candidate implementation review is deferred until requested. CI results were
not collected. HOME-12 operational security acceptance remains **not proven**.

Related: [[harbor-oci]], [[../architecture/storage-and-state]],
[[../architecture/secrets-and-identity]], [[../runbooks/runtime-isolation]].
