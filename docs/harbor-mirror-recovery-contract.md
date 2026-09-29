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
5. For one approved node, capture and normalize every persistent configuration
   document with the pinned parser; replace only `machine.registries.mirrors`
   with the reviewed upstream map. Reject all other changes, document loss,
   unexpected mirror content and strict-validation failures. Repeat trust,
   identity, boot and full-config race checks immediately before applying.
6. Apply once with `no-reboot`, then compare complete normalized persistent
   readback and the boot identity. Bound each request and the whole operation.
   Stop the sequence on any failure. An apply timeout or readback failure is
   an **unknown applied state**, requiring authorized read-only reconciliation;
   do not automatically retry, revert, or advance to another node.

No implementation of steps 1–6 is shipped here. Current rollback remains
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

## Approval, unrun gates and limits

Before production behavior changes, Rodman must approve the exact reviewed
implementation revision, authenticated bundle digest, expiry/revocation policy,
target identities/endpoints, private credential reference, node order and
incident scope. Independent security review belongs to HOME-14. HOME-15 owns
activation evidence and recovery inventory coordination with HOME-2; this
proposal neither duplicates backup work nor declares those gates satisfied.

Required later evidence, not collected here:

- Full pinned-tool static gate (`nix develop --command bash scripts/ci/static-checks.sh`);
  Nix is absent in this review environment. Real parser validation is unrun.
- A reviewed offline implementation and independent negative tests of its
  verifier, identity handling, expiry, missing tools and tampered artifacts.
- Approved non-production drills for combined GitHub/DNS/Harbor outage, advanced
  main and unavailable `.199`, with target-local authenticated access. Include
  certificate expiry and worker restart boundaries, not only warm-worker success.
- Separate approval for any production inspection that accesses credentials
  or private machine configs, followed by explicit approval for any mutation
  or fault injection. Record per-node identity, version, config-diff decision,
  unchanged boot ID and readback result in sanitized receipts.
- Independently available required bootstrap images/tools and private artifacts;
  matched Harbor DB/blob/key backups and restore evidence through HOME-2.

Proposed target for Rodman and HOME-15 to ratify: restore upstream transport on
one surviving, authenticated worker within 30 minutes of incident declaration,
including approval and bundle retrieval. Record time to approval, verification,
apply and readback separately. This is an unmeasured acceptance target, not an
RTO promise; whole-cluster and Harbor data recovery need separate targets.

Rollback only restores transport for configured public upstream registries.
It cannot restore unavailable upstream artifacts, Internet/DNS, private-only
images, the sole control plane, Harbor database/blob/key consistency or NAS
data. It is not air-gapped bootstrap. Re-enabling strict mirrors is a new
activation using reviewed current main and publication checks; never do it
automatically after recovery. Retain mirror blobs throughout.
