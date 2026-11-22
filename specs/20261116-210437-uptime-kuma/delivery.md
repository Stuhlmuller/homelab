# Image prerequisite delivery

- PR: <https://github.com/Stuhlmuller/homelab/pull/1848>
- Owner: uptime-kuma; branch codex/uptime-kuma-images.
- Signed head: 5c7e0e294ac37597d0a4837e22080564cf6c42c7 (both introduced commits GitHub valid).
- Last observed base: 15bfe27955e755a24617d9dd00bfbd7803da30d6.
- No review threads; configured approval count zero; policy-bot successful.
- Required repo and Terragrunt checks still running at this checkpoint.
- Protected merge and publication are NOT complete; no receipt or consumer rollout claimed.
- Next: fresh exact-head checks and server mergeability, protected squash, verify
  signed single-parent main commit, dispatch fixed uptime-kuma scope at exact
  current main, record complete authenticated pull receipt and bundle hash.

The delivery helper flags REST-only policy-bot issuer as unverified. GraphQL
marks its successful status isRequired=true. Do not infer identity from status
creator; inspect authoritative server acceptance with current protected rules
before normal merge. No rule or helper changes are in scope.

Image CI correction: first head failed because admission image catalog must
exactly match publisher inventory. Signed follow-up synchronizes it; local
image-rewrite check now passes226 reviewed sources. Initial local full gate
failed the same assertion; it was not a successful full run. New head CI is
running. Harbor compatibility job133848402206 in run44026624069 fails private
runtime audit validation:remediation; this is existing Harbor image audit,
not Kuma image execution, and is not repaired by weakening its gate.

Second static failure: reviewed credential workflow SHA in
scripts/ci/offline-static-checks.sh also required refresh (separate canonical
serialization from Rego hash). Signed commit c99d073207ee138d50bd8e7845ef13a85299764b
updates only that exact hash, computed by the guard's yq|jq-cS|sha256sum.
CI for that head is pending; no checks or publication claimed complete.
Harbor-specific source/log diagnosis transferred to coordinator; this worker
retains sole PR aggregate/check ownership. Harbor remediation classification
means scanner findings have fixed/available remediation under scan checker
lines186–190. Normal protected merge remains blocked until applicable gates.

Network-policy job133852756165/run44027956057 diagnosis: dependency download
from cache.nixos.org resumed then HTTP416, so botocore/Checkov closure could
not be realized; policy did not run. Job-specific rerun API returned403
"workflow run containing this job is already running". Retry only when run
completes; do not modify policy or repeatedly rerun unchanged failures.

## Protected image merge

PR1848 merged normally at b6063d41c993ec575c667134fa97818d5a5591b9,
2026-11-17T06:23:14Z. All3introduced commits and single-parent merge signed/
verified; reachable from main. Fresh rules require7contexts, all passed with
required-context evidence; no threads/draft/review block. Harbor-core audit is
optional and unrelated; it remains failed validation:remediation and was not
skipped, changed or represented as healthy. Normal expected-head squash used
no admin bypass.

Dispatched fixed uptime-kuma publication at exactmain b6063d41c993ec575c667134fa97818d5a5591b9.
Publication pending, T005 unchecked. Bundle SHA256 a8e7996bcadcb0bf5d7743aa5dbc4f7bb1e322ab40081b2e6835e1f81b9fe0d1.

```json
{
  "scripts/config/harbor-images.json": "e074a04f9fba66f590115b5ca076348663d2b50ddd0db467cdddf4e5807657d2",
  ".github/workflows/harbor-mirror.yml": "8d5fa8b42789e9fcc3541fa535dd68578e52072f66f54c1f93a5fca22b2f65b4",
  "scripts/ci/harbor-publish.sh": "fb1a1c95e1ba5f5d2ec38784af7ae5b02d3542360aff2f491a7c55855dc511c0",
  "scripts/ci/install-kubeconfig.sh": "ac63ebfe1cb972271215b1f24a51770ab28ffded8075d1319e6c88e0f276b1db",
  "flake.nix": "1906dc1e72b3aa2a7bed2880b060ba3074adc1e03fed6f1c672434ae22bc2cb8",
  "flake.lock": "04883336b243447d1042c8292999c7b834ffa7d6309c802f1ed34ad81cb2d8cb",
  "scripts/config/harbor-uptime-kuma-images.json": "a14e86feae374ea0778478bdb17a7fa6ca79049883959d3b5cc706624c068939"
}
```

Publication run: <https://github.com/Stuhlmuller/homelab/actions/runs/44030881358>
Title and head bind uptime-kuma scope to exactb6063d41 main; currently in progress.

## Publication receipt and consumer delivery

Fixed-scope publication run44030881358 succeeded on exact main
b6063d41c993ec575c667134fa97818d5a5591b9. Copy job133868791047 emitted the
public receipt at 2026-11-17T07:09:45.6179215Z: selected inventory copied with
matching digests and complete authenticated Harbor pulls; upstream retained.
This closes image publication proof, subject to unchanged bundle comparison
at consuming merge.

Consumer PR: <https://github.com/Stuhlmuller/homelab/pull/1850>. Introduced
commits cbe92f72623e141e47cc8795fc075c0925da94be,
771b7bac5dd8e0cb90fd93ce61b118cd343bb729 and
9cb322dfb872dd8b1ee751ccef211b9133c7a9ca have verified valid signatures.
The latter two change review-note layout only; focused Markdown lint passed.

Local static session64879 failed fetching an OpenWiki npm dependency with
HTTP503; bounded retry94546 is pending. Live read-only preflight identified
Traefik Synced with successful operation and ready/current generation4
Deployment. No unrelated ingress mutation or deployment occurred.


## Protected delivery and deployment readiness

PR1850 merged normally on 2026-11-17 at 08:32:47 UTC, signed merge
1dfeb92a3654bae7a927c8adf4ed454347820dd7, sole parent b6063d41, reachable main.
All four introduced commits were verified signed; all seven required contexts
passed, with no reviews/threads required or unresolved. Optional Harbor audit
still reports its existing remediation finding and was not treated as a gate.
Kuma image publication matched the consuming merge bundle exactly.

First targeted apply44047731567 passed static checks but stopped at the
precredential current-main guard after unrelated AdGuard PR1851 advanced main.
No checkout, credentials or live apply occurred in that failed job. Inspected
new signed main ec53ed3d3b9b2397bf41abfd8935561e8e5d5b67: Kuma manifests,
IaC, apply workflow/script and scoped image inventory were byte unchanged.
The normal exact-main retry44050500579 completed successfully, both static and
Terragrunt Apply. No guard was bypassed and no ad hoc cluster mutation occurred.

At 09:12 UTC, Argo uptime-kuma was Synced/Healthy with successful operation,
chart4.4.0 and both Git source revisions ec53ed3d. Deployment had one ready Pod;
app and reconciler were Ready, both init containers exited0, and both runtime
containers reported the pinned Harbor digest7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9.
Both5Gi PVCs were Bound, owner ExternalSecret Ready, reconciler health command
exited0. First-backup and restore-verification Jobs each completed successfully;
their native evidence is still to be inspected in the separate acceptance stage.

T025 is complete. T026–T028 remain pending: private UI authentication, exhaustive
coverage/observations and failure/recovery, retained IDs/history across the
code-owned replacement, backup/restore evidence, and runtime convergence.
Nightly scheduled execution has not yet been observed. Working branch for
acceptance evidence/follow-up changes is codex/uptime-kuma-acceptance based on
current main; original implementation PR remains merged.
