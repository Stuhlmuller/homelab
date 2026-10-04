# HOME-62 issuer capability evidence proposal

**Disabled, unexecuted, and not an accepted issuer design.** Prepared independently
from integration `d141fa44a7f5992faf9904afa7f1441d2606f470`. HOME-62 rejected the
one-day system issuer. Its production workflow/helper hard stops remain unchanged;
neither offline results nor a changed acceptance flag can revive it.

`scripts/harbor-issuer-capability-plan.py` produces non-secret synthetic identity
recipes and **54 cases: 36 direct API mutations and 18 session-boundary cases**.
It compiles exact method/path/body requests from observed synthetic IDs and
implements offline postcondition/evidence checks. It contains no credential
reader, HTTP client, provisioning code, workflow or dispatch. `--execute` always
refuses. Its output marks every server case `unexecuted` and authority acceptance
false. Unit tests fabricate evidence to test the oracle, not the Harbor authorizer.

## Isolated identity graph

Each case starts with a fresh copy of a separately approved, synthetic-only
Harbor 2.15.2 fixture. Reuse the chart/image lock from the
[collector fixture proposal](harbor-authorization-fixture.md), not production
storage, credentials, routes, hooks or Secrets. The existing general runner is
not the issuer executor and receives no issuer/operator credentials.

| Alias | Fixture authority and provenance |
| --- | --- |
| `issuer` | Synthetic copy of the **rejected** one-day proposal: system robot create/read/list/update plus list permissions in homelab/mirror. Research subject only. |
| `child` | Created by that synthetic issuer with the collector's two project list scopes and requested 30-day lifetime. Immutable ID/creator relationship recorded. |
| `unrelated` | Independent synthetic system robot created by the disposable custodian, not by the issuer. Same narrow read scopes make its old/new credential usable as controls. |
| `project-homelab`, `project-mirror` | Separate project-level robot-management alternatives, with only that project's robot create/read/list/update and repository/artifact list. These are hypotheses, not approved replacements. |
| `project-child-homelab`, `project-child-mirror` | Independent read-only project identities for same-project and cross-project controls. |
| `session-subject` | Distinct synthetic read identity additionally allowed private homelab registry pull, solely to provide a usable bearer-session baseline. Never substitute these permissions into the real collector or rejected issuer. |

All names have `home62-` fixture suffixes, with Harbor's appropriate system or
project prefix. The compiler rejects missing/extra aliases, ID aliasing,
unexpected baseline grants/lifetimes, and a child/unrelated creator mismatch.
The future provisioning adapter must independently verify creators, permissions,
expiry, names and IDs; naming alone is not an isolation or custody boundary.
Both project-management alternatives need authenticated private-project read
controls. Use a separately approved private-mirror variant for that assertion;
the general fixture's public mirror cannot prove it. That read integration is
explicitly not implemented by this mutation planner.

## Direct-server capability table

| Subject and operation | Exact API recipe | Operation-specific evidence |
| --- | --- | --- |
| Intended child / unrelated system robot refresh | PATCH `/api/v2.0/robots/{id}`, body `{}` | Independent observer binds exact ID; old Basic works before, fails after an allowed refresh, and newly returned secret works. Denied refresh must preserve metadata and old-credential usability. Secret values stay with the isolated adapter. |
| Intended child / unrelated update and disable | PUT same path, complete existing update fields plus changed description or `disable:true` | Exact requested field in independent readback; all other identity metadata preserved except target update timestamp. |
| Issuer self / child permission expansion | PUT with added system `robot:delete`; child also tests unrelated-private-project repository:list | Exact added grant persists without extra grants; compare the entire identity graph. A 200 with timestamp-only change fails. |
| Issuer self / child lifetime expansion | PUT with duration increment (1→2 or 30→31) and separately `-1` | Persisted duration **and** creation-relative expiry match the request, or `expires_at=-1`. No inference from a success status alone. |
| Child creation ceiling | POST `/api/v2.0/robots` with narrow baseline; then separate extra-system, extra-project, 31-day and never-expiring cases | Exactly one new ID matching response/readback; exact name, permissions, requested duration and calculated expiry; unrelated identities unchanged. |
| Project alternatives | PATCH refresh / PUT disable against own-project, other-project and system identities; own-project self permission/lifetime expansion | Valid administrator controls distinguish authorizer denial from invalid requests. Self expansion adds repository:delete **within the same project**; no structurally invalid project→system scope substitution. |

The request compiler retains name and level for PUT and changes no target ID.
The pinned [robot handler](https://github.com/goharbor/harbor/blob/v2.15.2/src/server/v2.0/handler/robot.go#L343)
rejects level/name changes and multiple scopes for project-level identities;
such validation errors must not masquerade as authorization denial. It also
calculates changed lifetime from creation time, which the oracle checks. The
source trace remains evidence about code, not observed server capability.

Each direct case needs a valid actor baseline and independently successful
observer reads. Bind evidence to the exact compiled request fingerprint and
initial identity graph. Require the **identical valid administrator request**
with the same initial state and verified postcondition. A separately approved
pair of isolated copies of the same fixture checkpoint can provide identical
IDs and metadata for the actor and administrator controls; no checkpoint or
reset adapter is delivered here. Never reuse a self-expanded actor for later
cases or reset real/compromised credentials to manufacture controls.

Classify an observed 403 with FORBIDDEN/DENIED and unchanged state as
`denied-with-controls`. Classify a successful mutation only after its exact
postcondition as `capability-present`, **not safe/approved**. A 401, 400, 404,
409, redirect, timeout, failed positive control, unknown response or changed
unrelated state is inconclusive. Lost-create-response, cancellation or observer
failure stays UNKNOWN: no retry, adoption, assumed denial or cleanup claim.
Evidence objects containing secret/password/token/cookie/authorization fields
are rejected by the offline API; it is not a sanitizer for raw response dumps.

## Session survival cases

For issuer, child and distinct session subject, prepare rotation, disable and
actual expiry boundaries, each with registry bearer and API-session recipes.
Before a boundary, prove the **same session** can access an existing private
resource and anonymous access cannot. Independently verify the subject ID and
boundary; replay the exact request/session handle afterward. Record sanitized
timestamps, credential/session expiry and status/error attribution, never token,
cookie, Basic header or response-secret material. Also test fresh Basic before
and old Basic after; those observations cannot substitute for old-session replay.

Every denial now requires two independent authenticated 200 controls to the same
private target, bracketing that observation within five seconds on either side
on a common monotonic clock. Both controls use the same independent identity and
opaque session reference, distinct from the boundary subject and replay session.
This is an offline evidence contract, not approval of a polling cadence or window.
Missing, failed, stale, one-sided or aliased controls make the case inconclusive,
including an earlier denial followed by an otherwise valid final observation.

`baseline_context`, every probe and each control bind `request_sha256` (exact
method/path/body), `target_id` (immutable private object identity),
`private_revision` (independently verified privacy/ACL state), and `route_sha256`
(origin, TLS peer/trust and routing configuration identity). Changes or missing
bindings are inconclusive. Probe subject/session references must remain fixed.
Controls attest `authenticated_access` and all responses attest
`authenticated_origin`; redirect, proxy, transport and routing failures cannot
be classified as session termination. Each denial must carry a nonempty sanitized
`error_code`, `error_classification_verified`, and the normalized class
`session-invalid` or `session-expired`. Generic FORBIDDEN/permission denial is
inconclusive, even with HTTP 403 and a successful independent control.

These fields are synthetic receipt assertions, **not cryptographic proof**.
The future separately approved adapter must establish target/privacy continuity,
authenticated origin and independent access, and validate a protocol-specific
mapping from actual pinned-server responses to session error classes. No such
adapter or verified error mapping is supplied. A boolean or raw status supplied
by an untrusted reporter cannot establish runtime acceptance. Unsupported or
ambiguous server errors remain inconclusive; no grants may be added to force a
control to pass. Custody/environment/signing prerequisites remain with HOME-66.

The offline oracle reports surviving sessions separately from rejection of old
Basic credentials. It flags usability after declared session expiry and requires
observation through expiry plus measured clock skew for a complete record. A
single 401/403 or process termination never proves immediate/global revocation.
Sampled denials establish only the tested resource/time intervals; record polling
cadence and do not claim continuous revocation or coverage of other routes.

The original issuer/collector may have no usable private registry token or
supported API cookie session. A missing baseline makes that case **inconclusive**,
not proof of revocation. Do not add issuer grants or use public mirror pulls to
force a success. The separate session subject probes Harbor's session behavior
but cannot prove unsupported issuer session semantics. Natural expiry needs a
pre-aged, separately reviewed synthetic checkpoint or a longer approved window;
no host clock mutation or fake authorizer is proposed.

## Remaining blockers and ownership

All 54 server cases are unexecuted. A direct-server adapter, supported custody
path, checkpoint/identity provisioning and verified teardown are **not supplied**.
The current general fixture's four-hour disposal and 20-minute execution proposal
cannot silently cover one-day natural expiry or a newly discovered long session.
Return exact bounds and observed lifetimes to Decision Desk before execution.

SRE owns replacement authentication/custody and effective reader/writer controls;
Recovery owns hook-safe stop/sync and executable recovery/readback contracts.
QA supplies this request/oracle proposal, not reusable management credentials or
an admin fallback. Fixture custodians and independent observers, exact signed
revisions, isolated environment/transport evidence, provisioning/checkpoint and
teardown revisions, and bounded execution approval are still required. Expanding
authority or accepting residual risk returns to HOME-62 review.

HOME-59 all-hop proxy/runtime/rotation evidence, HOME-3 enforcement, scan/expiry
and collector/alert integration, signing and full validation remain open. No
fixture or production execution approval is requested on the strength of this
offline proposal.

Offline checks:

```sh
python3 -I scripts/harbor-issuer-capability-plan.py
python3 -I scripts/ci/harbor-issuer-capability-plan-test.py
python3 -I scripts/ci/harbor-authorization-fixture-test.py
```
