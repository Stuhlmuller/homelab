# HOME-30 evidence packet v1

Status: implementation submitted; QA reproduction, Auditor review and delegated
scope decisions pending. No self-approval, control closure or operating claim.

| Field | Value |
| --- | --- |
| Issue / control | HOME-30 / SCOPE-01: maintain and reconcile a versioned system boundary |
| Preliminary criteria | CC2.1, CC3.1–CC3.2, CC8.1; category applicability proposed in `../../scope.md`, final mapping belongs to HOME-37 |
| PR | https://github.com/Stuhlmuller/homelab/pull/1154 — no close intent |
| Immutable implementation revision | `a3c592e353c654b5fed28b6424036c2d1d74f35c` |
| Current-main/source baseline | `58ecf587d3069fb8e504ac319e2bec2de05785c0`, fetched again immediately before collection |
| Collection UTC | 2026-10-04T01:48:06.638676+00:00 |
| Collector | SOC 2 Security Evidence Engineer, agent `01e5e4fd-3ecb-48f5-beda-66bd765e474b` |
| Scope / period | Committed source at baseline; point-in-time design preparation only; no observation period or live sampling |
| Tools | Python 3.13.15, Git 2.39.5; connected GitHub API tools for PR discovery/publication (connector version not exposed) |
| Evidence version | HOME-30-v1; first packet, no prior version superseded |

## Changed files and rationale

- `docs/compliance/soc2/scope.md`: proposed system description, commitments,
  boundaries, all five category decisions, roles, flows, unknowns and change procedure.
- `scripts/soc2-scope-inventory.py`: deterministic source-population collection
  and comparison without emitting configuration values or contacting live systems.
- `scripts/ci/soc2-scope-inventory-test.py`: synthetic detection of source drift
  and evidence-output minimization.
- `docs/compliance/soc2/evidence/HOME-30-v1/inventory.json`: complete population
  of 501 committed entries, 49 groups, 41 literal registration paths.
- `docs/compliance/soc2/evidence/HOME-30-v1/open-prs.json`: 29 open PRs observed
  during preparation; titles/URLs only, no third-party comment bodies.
- `docs/knowledge-base/operations/soc2-readiness.md` and `00-home.md`: durable
  navigation to the boundary and its limits.
- This packet, `validation.json` and `SHA256SUMS`: dated commands/results,
  source samples and artifact integrity. Evidence-only additions follow the
  implementation revision; final delivery receipt binds the complete PR head.

## Reconciliation of overlapping work

HOME-30 had no comments, existing runs or linked PR at entry. HOME-29 was already
in progress. Current main matched the CSO's observed SHA. GitHub search returned
29 open PRs, recorded in `open-prs.json`; filename lists were inspected for
#1153, #1152, #1151, #1141, #1125, #1124, #1123, #1120, #1116 and #1113.

Recovery proposals #1113 (HOME-2), #1116 (HOME-3), #1120 (HOME-4), #1141
(HOME-21) and Harbor #1123–1125 remain proposed evidence/control work. None
is counted as an effective operating control. Wazuh #1153 is a staged platform
proposal, absent from baseline; this scope does not select or authorize it.
Fleet #1152, Harbor #1151 and Multica #1150 change dependencies/runtime behavior
and require recollection if merged. Renovate updates can also alter tree hashes.

This work avoids their runtime, workflow and shared architecture files. The
single additive `00-home.md` navigation entry overlaps several documentation
PRs; retain both entries during any later reconciliation. No other proposed
changed filename intersects the ten reviewed filename lists. Recheck at merge;
this dated overlap inspection is not a permanent conflict-free guarantee.

## Population, samples and test results

Collection includes every committed Git tree entry under `clusters/`, `IaC/`,
`.talos/`, `.github/workflows/`, `builds/` and `policy/`; no random sample is used
for population hashing. Digests cover sorted path/mode/object-ID records, not
runtime health. External chart expansion, generated resources and live objects
are not enumerated by this collector.

Six judgmental source samples in `validation.json` cover registration, AI/state,
secret-provider scope, persistent storage and Talos/Kubernetes configuration:

| Sample | Inspection conclusion |
| --- | --- |
| `IaC/terragrunt.stack.hcl` | Literal app registrations and main-tracking GitOps sources support the delivery boundary; 41 registrations, not 41 proven running services |
| `clusters/homelab/apps/langfuse/values.yaml` | Web memory reservation includes 2Gi; state/telemetry service remains in scope |
| `clusters/homelab/apps/langfuse/datastores.yaml` | Stateful database declarations and NFS claims support confidentiality/availability inclusion |
| `clusters/homelab/apps/external-secrets/cluster-secret-store.yaml` | AWS provider and namespace-scoped store support a secret-provider trust crossing; no secret values collected |
| `clusters/homelab/platform/storage/kustomization.yaml` | Platform storage composition includes NFS and local runtime storage resources |
| `.talos/patches/kubernetes-1.34.11.yaml` | Declared Kubernetes version patch; does not establish live node version |

`validation.json` records exact argument arrays, stdout, stderr and exit status.
All six recorded commands exit 0. Two unittest methods exercise deterministic
collection, matching baseline acceptance, detection of modification/addition/
deletion (each checker exit 1), exclusion of untracked private material, absence
of a synthetic sensitive value in output, and rejection of an invalid revision.
The expected invalid-revision Git diagnostic appears on stderr; it is a passing
negative test, not a failed collection. Python compilation and diff whitespace
checks pass. No test uses real sensitive data.

Reproduction at the implementation revision:

```sh
git checkout --detach a3c592e353c654b5fed28b6424036c2d1d74f35c
python3 scripts/soc2-scope-inventory.py --revision 58ecf587d3069fb8e504ac319e2bec2de05785c0
python3 scripts/soc2-scope-inventory.py --revision HEAD --check docs/compliance/soc2/evidence/HOME-30-v1/inventory.json
python3 -I scripts/ci/soc2-scope-inventory-test.py
python3 -m py_compile scripts/soc2-scope-inventory.py scripts/ci/soc2-scope-inventory-test.py
git diff --check 58ecf587d3069fb8e504ac319e2bec2de05785c0 HEAD
```

At the final PR head, also run `sha256sum -c
docs/compliance/soc2/evidence/HOME-30-v1/SHA256SUMS` from repository root.
SHA256SUMS covers the changed artifacts except itself; the delivery receipt
records its digest and final commit. JSON duration/timestamps need not be byte
identical on reproduction; inventory and artifact digests must match.

## Exceptions, residual risk and next gates

- Full Nix/static/policy gates and the repository secret-scan wrapper were
  unavailable: `nix`, `terragrunt`, `rg` and `gh` are absent. Focused Python,
  whitespace and source review are recorded, not represented as full CI.
- HTTPS Git push failed for missing local credentials. The connected GitHub
  app created the same content tree and PR. Commit signing/protection policy
  must be satisfied before a separately authorized merge; no bypass requested.
- CI result is not collected in this packet; no CI pass is asserted.
- Source completeness does not prove deployment completeness, chart output,
  enforcement, current hardware health or recovery. Known single-control-plane,
  NAS concentration, capacity and network-enforcement gaps remain with the
  CSO/control owners. No residual risk is accepted by the implementer.
- D1–D7 scope decisions require CSO synthesis and delegated approval. Actual
  users/commitments, provider roster, privacy purpose/retention and recovery
  objectives require owner evidence. They must not be fabricated to close HOME-30.
- QA must reproduce at the final immutable head, reconcile the six samples
  and verify output minimization. Auditor review follows QA and records ACCEPTED
  or CHANGES_REQUESTED. CSO alone closes after acceptance and merge/approved
  exception. HOME-29 remains in progress; stages 2–5 remain in backlog.

Rollout: review and separately authorize merging documentation/collector only.
There are no desired-state edits or automatic new jobs. Rollback: reviewed
revert of these artifacts while preserving prior evidence and decision history;
no data deletion, workload change or secret rotation is necessary.

Sanitization: only public repository paths, counts, hashes, synthetic test
diagnostics and role identifiers are retained. Secret values, personal records,
private keys, raw backup contents and recovery material were excluded. Source
samples were recorded as hashes and bounded conclusions, never raw dumps.
No operating or post-deployment evidence is claimed.
