# Harbor mirror recovery contract (proposal)

HOME-13 prepares HOME-12 acceptance items 2–3. This is a proposed contract,
not an implemented offline recovery command or authorization to operate.
Production helper behavior and current-main activation gates are unchanged.
Baseline: `a5b296da70068a666a526ff4b3656361d01157aa`.

## Current boundary

`scripts/talos-harbor-mirrors.py` checks clean reviewed current main twice
before execution, including rollback. GitHub outage, workstation DNS failure,
or advanced main stops rollback. All remote Talos requests use `.199` as the
endpoint even for worker targets. Rollback avoids Kubernetes readiness and
Harbor publication, but still needs that endpoint and valid Talos credentials.
These are source observations, not evidence of mirror activation or live health.

The existing boot UUID check establishes boot continuity, not independently
enrolled machine identity. A future recovery path must strengthen identity
validation without weakening credential, mirror-only diff, strict validation,
pre-apply race, no-reboot or persistent-config readback safeguards.

## Version-specific endpoint evidence

Inspected Talos v1.11.3 source at
`a0243ef77e6532ed2919689d305eeaf97458c0a1`:

- [APID router](https://github.com/siderolabs/talos/blob/a0243ef77e6532ed2919689d305eeaf97458c0a1/internal/app/apid/pkg/director/director.go):
  with forwarding disabled, a single target recognized as local reaches the
  local backend. Other targets fail with `no request forwarding`.
- [TLS provider](https://github.com/siderolabs/talos/blob/a0243ef77e6532ed2919689d305eeaf97458c0a1/internal/app/apid/pkg/provider/provider.go)
  requires mutual TLS. [APID setup](https://github.com/siderolabs/talos/blob/a0243ef77e6532ed2919689d305eeaf97458c0a1/internal/app/apid/main.go)
  only enables remote forwarding when a client certificate is available.
- [API certificate controller](https://github.com/siderolabs/talos/blob/a0243ef77e6532ed2919689d305eeaf97458c0a1/internal/app/machined/pkg/controllers/secrets/api.go)
  obtains worker server certificates through a remote trustd generator using
  control-plane endpoints. Direct worker access is not independent certificate
  issuance or cold-start recovery.

Inference: an already-running worker with usable server certificates may serve
authenticated local recovery requests without `.199` proxying. Source alone
does not establish this homelab's certificate validity, address/SAN match,
authorization, firewall reachability, restart survival or supported outage
duration. No worker endpoint was contacted for this review. Never use insecure
mode or assume workers can proxy to other nodes.

## Proposed bounded recovery path

Prepare and review a separate rollback-only implementation before approving
production use. Keep activation on the existing exact-current-main path.
The offline recovery path must not be a generic gate-skipping flag.

1. While dependencies are available, release an immutable bundle containing
   exact reviewed source, rollback patch, public node/endpoint inventory and
   all tools plus their runtime dependencies. Pin talosctl 1.11.3, Python, yq
   and the remaining toolchain by verified artifact digests and platform.
   A lockfile requiring downloads during an outage is insufficient. Retain
   an independently accessible copy; test it on a clean disconnected host.
2. Authenticate a manifest that binds every file, tool, full source revision,
   permitted target, rollback operation, expiry and approval reference. Pin
   its digest or verification key outside the bundle through independent
   review. A manifest stored next to editable files is not a trust anchor.
   Reject missing/extra files, symlinks, changed bytes and unapproved revisions;
   verify before executing bundled code and again before apply. Prevent local
   replacement between verification and use. Specify expiry, revocation and
   supersession handling without relying on GitHub; if freshness cannot be
   established from the approved offline record, stop.
3. Keep credentials outside the public bundle. Select one explicit private
   Talos config, with no environment/default fallback. Authenticate and check
   server identity and client validity/authorization before config capture;
   reject stale credentials without renewing them implicitly. Record the
   credential renewal dependency and usable certificate window privately.
   Do not print credentials, certificate material or captured machine configs.
4. Enroll a per-target endpoint and stable machine identity in advance using
   authorized evidence. Prefer the target's literal IP for local requests when
   separately verified; require endpoint/target correspondence, verified TLS,
   actual server version and enrolled machine identity. Boot UUID is an
   additional continuity check. Reject unexpected identities and endpoint
   substitutions. No automatic endpoint discovery or insecure fallback.
5. Require an approved maintenance window and named operator, with evidenced
   exclusion of every concurrent configuration writer for the target throughout
   capture, apply and readback. Record the exclusion mechanism, owner and release
   condition; if exclusion cannot be established or is lost, stop. A last-moment
   recapture alone leaves a read-to-apply race and is not writer exclusion.
   For one approved node, capture and normalize every persistent configuration
   document with the pinned parser; replace only `machine.registries.mirrors`
   with the reviewed upstream map. Reject all other changes, document loss,
   unexpected mirror content and strict-validation failures. Repeat trust,
   identity, boot and full-config race checks immediately before applying.
6. Apply once with `no-reboot`, then compare complete normalized persistent
   readback and the boot identity. Bound each request and the whole operation.
   Stop the sequence on any failure. An apply timeout or readback failure is
   an **unknown applied state**, requiring authorized read-only reconciliation;
   do not automatically retry, revert, or advance to another node.
7. Record successful equality/boot checks as **config restored** only. Require
   a separately approved, initially uncached, digest-pinned public upstream image
   pull through the target's restored containerd registry configuration before
   recording **transport recovered**. Approval must name the target, runtime
   namespace, platform, upstream reference/digest, permitted egress and bounded
   pull procedure. Establish initial cache absence without deleting caches;
   if already cached, stop and obtain approval for a different probe. Correlate
   the completed digest-verified pull with sanitized origin/transport evidence
   showing an actual upstream request and transfer, not a cache hit or Harbor
   response. A workstation pull or persistent-config equality is insufficient.
   Missing approval, unavailable evidence, timeout or pull failure leaves
   transport unproven; retain the config result without claiming recovery.

No implementation of steps 1–7 is shipped here. Current rollback remains
unavailable in the demonstrated GitHub/control-plane failure cases. Do not
manually edit out checks or use ad hoc apply commands to bridge the gap.

## Synthetic evidence and reproduction

From this PR's pinned commit (recorded in the issue handoff), run:

```sh
python3 -I scripts/ci/talos-harbor-mirrors-test.py
git diff --check
```

The existing static CI gate already invokes this test. One unittest contains
45 named subcases (29 existing, 16 added); success is `Ran 1 test ... OK`.
All commands are intercepted by a strict mock, with synthetic configs in
temporary directories. No real credentials, DNS faults, Talos calls or writes
to infrastructure occur. JSON fixtures stand in for yq/Talos parsing.

| Added scenarios | Expected evidence |
| --- | --- |
| GitHub unavailable; DNS unavailable; main advanced, activation and rollback | Current-main gate fails before apply |
| GitHub unavailable or main advanced at the second rollback gate | Candidate validates but no apply occurs |
| Control-plane endpoint unavailable; stale credential rejected | Authenticated boot read fails before config capture; no alternate endpoint attempted |
| Dirty rollback checkout; tampered revision | Clean-checkout or reviewed-SHA gate rejects; no apply |
| Unintended config change; lost document; concurrent config change | Mirror-only or race check rejects before apply |
| Rollback readback mismatch | Exactly the attempted application is observed; success is withheld |

GitHub/DNS cases inject Git exit 128; endpoint/credential cases inject Talos
command failure. They prove error propagation, not DNS behavior or certificate
validation. Dirty/tampered cases model current checkout gates, not a working
signed-bundle verifier. Existing subcases retain rollback reboot detection,
private temporary-file cleanup and no Kubernetes/Harbor dependency assertions.
The proposed offline bundle and direct-worker success path remain untested
until implemented. A passing test suite is not outage recovery proof.

## Required future test matrix

These are mandatory requirements for the future recovery implementation, not
additional passing cases in the current 45-subcase suite. Implement and review
them with that path; never weaken production/current-main gates to make outage
tests pass. Use synthetic credentials/configs and a disconnected tool environment.

| Area | Required cases and acceptance evidence |
| --- | --- |
| Authenticity and membership | Reject forged signatures, substituted signer/trust anchor, missing/extra manifest members, changed bytes, path traversal, symlinks and replacement between verification and use; no unverified code/tool execution or apply. |
| Authority | Reject withdrawn, expired, superseded, unverifiable-freshness, wrong-action and wrong-target approval; reject replacement-map, egress, operator/window or deadline mismatches before apply. |
| Tools | Reject missing, altered, wrong-platform or wrong-digest tools/runtime dependencies, including PATH substitution; demonstrate verified tool closure on a clean disconnected host without downloads. |
| Credentials and identity | Reject wrong CA, wrong node, reused address, endpoint substitution, invalid SAN, expired/not-yet-valid client or server certificate and unauthorized client; test certificate renewal and worker restart boundaries without insecure fallback or implicit renewal. |
| Configuration and exclusion | Reject unexpected existing mirrors, unrelated changes, dropped documents and real strict-parser/normalization failures; test competing writers both before and after recapture, unavailable/lost exclusion and expiry of the maintenance window. No apply when the preconditions fail. |
| Execution and uncertain state | Inject apply timeout, lost response, readback failure and whole-operation deadline expiry. Prove no automatic retry, revert or next-node advance. Reinvocation after uncertain state must refuse another apply until separately authorized read-only reconciliation establishes state and renewed approval permits it. |
| Completion and timing | Distinguish config restored from transport recovered; reject cached/wrong-digest/wrong-origin probes, missing transport evidence and pull timeout/failure. Test a successful initially uncached upstream pull and measure the full incident-to-transport interval including approval/retrieval. Never delete caches to manufacture evidence. |
| CLI confidentiality and cleanup | Exercise the real CLI entry point with synthetic private sentinels in child stdout/stderr and exception messages; capture both CLI streams and require sanitization on success/failure. Verify restricted scratch and cleanup on handled interruption as well as ordinary exits. |
| Outage success and boundaries | Demonstrate combined GitHub/DNS/Harbor and sole-endpoint outage recovery via the approved target-local endpoint with advanced main, using valid offline authority. Preserve activation rejection and all safety checks. Separate mock evidence, real pinned-parser/tool evidence and later approved operational drills. |

## Approval, unrun gates and limits

Before production behavior changes, Rodman must approve the exact reviewed
implementation revision, authenticated bundle digest, expiry/revocation policy,
target identities/endpoints, private credential reference, node order and
incident scope. Bind approval to the full replacement mirror map, restored
upstream egress, named operator/maintenance window and concurrent-writer exclusion
mechanism, per-request and whole-operation deadlines, timeout/stop conditions,
unknown-state reconciliation and the accepted recovery limits below. Approve the
transport probe separately with the exact step 7 scope; config-change approval
alone does not authorize a pull. Independent security review belongs to HOME-14. HOME-15 owns
activation evidence and recovery inventory coordination with HOME-2; this
proposal neither duplicates backup work nor declares those gates satisfied.

Required later evidence, not collected here:

- Full pinned-tool static gate (`nix develop --command bash scripts/ci/static-checks.sh`);
  Nix is absent in this review environment. Real parser validation is unrun.
- Repository signed-commit gate remains outstanding: the reviewed candidate
  commits are unsigned. Documentation or synthetic tests do not waive it.
- A reviewed offline implementation and independent negative tests of its
  complete required future test matrix above, including the real CLI and parsers.
- Approved non-production drills for combined GitHub/DNS/Harbor outage, advanced
  main and unavailable `.199`, with target-local authenticated access. Include
  certificate expiry and worker restart boundaries, not only warm-worker success.
- Separate approval for any production inspection that accesses credentials
  or private machine configs, followed by explicit approval for any mutation
  or fault injection. Record per-node identity, version, config-diff decision,
  unchanged boot ID and readback result in sanitized receipts. Include approval
  references, window/operator, exclusion acquisition/release and any uncertain
  state. Record config restored and transport recovered as separate outcomes;
  the latter requires the separately approved probe's initial cache-absence,
  exact digest/platform, upstream transfer evidence and completion timestamp.
- Independently available required bootstrap images/tools and private artifacts;
  matched Harbor DB/blob/key backups and restore evidence through HOME-2.

Proposed target for Rodman and HOME-15 to ratify: restore upstream transport on
one surviving, authenticated worker within 30 minutes of incident declaration,
including approval and bundle retrieval. Record time to approval, verification,
apply, readback and verified upstream pull completion separately. Stop the
30-minute clock only at evidenced transport recovery, not apply/readback. If the
pull cannot be approved or proven, the transport target is not established.
This is an unmeasured acceptance target, not an
RTO promise; whole-cluster and Harbor data recovery need separate targets.

Rollback can only restore transport for configured public upstream registries;
configuration restoration alone does not prove that transport works.
It cannot restore unavailable upstream artifacts, Internet/DNS, private-only
images, the sole control plane, Harbor database/blob/key consistency or NAS
data. It is not air-gapped bootstrap. Re-enabling strict mirrors is a new
activation using reviewed current main and publication checks; never do it
automatically after recovery. Retain mirror blobs throughout.
