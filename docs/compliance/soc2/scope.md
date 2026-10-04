# HOME-30 system scope — version 1, proposed

Review baseline: `58ecf587d3069fb8e504ac319e2bec2de05785c0`, 2026-10-04 UTC.
This is an internal Trust Services Criteria-aligned readiness self-assessment.
It is not a CPA examination, SOC 2 report, certification, or attestation.
All decisions below await delegated approval; no management approval is inferred.

## Goal, commitments and decision record

The repository describes a personal Kubernetes homelab and educational control
surface. It does not establish contractual services to user entities. Recommend
a self-assessment until the CSO obtains an owner statement about actual users,
contracts, service commitments and processing purposes. Family access and agent
workloads do not by themselves settle the service-organization question.

Recommend point-in-time control-design preparation at this revision, not a claim
of Type 1 examination completion. No Type 2 observation period is approved or
started. Historical runbook observations are context, not current operating
evidence. HOME-36 must later establish period start/end, population, sampling and
continuous evidence before making operating-effectiveness claims.

Proposed internal commitments are controlled and reviewed infrastructure changes,
authorized access, protection of nonpublic state, recoverability and traceable
automation. These are assessment objectives, not guarantees already achieved.
No contractual uptime, RTO, RPO, retention, financial-performance or processing
SLA is established here. HOME-34 and HOME-43 must propose measurable objectives.

| Decision | Recommendation and reason | Approval record |
| --- | --- | --- |
| D1 service/report goal | Internal self-assessment; user-entity contracts unverified | Pending CSO synthesis and Decision Desk decision |
| D2 time boundary | Revision-bound design preparation; no operating period | Pending delegated decision |
| D3 Security | Include common criteria across the entire boundary | Pending delegated decision |
| D4 Availability | Include: NAS, single control plane, capacity and recovery are material dependencies | Pending delegated decision |
| D5 Confidentiality | Include: credentials, prompts, uploads, databases and backups are nonpublic | Pending delegated decision |
| D6 Processing Integrity | Retain for assessment: trading, webhooks, jobs, GitOps and backup transformations need accuracy/authorization tests; HOME-43 refines scope | Pending delegated decision |
| D7 Privacy | Retain for assessment: identity, family-device metadata, telemetry and user content may include personal information; HOME-44 verifies purposes/lifecycle without collecting real records | Pending delegated decision |

No category is excluded in this proposal. A later exclusion requires evidence,
criterion-level rationale, affected data flows, residual risk and delegated
approval. Novel or cross-domain disagreements go to Decision Review Lead.
Serious legal/privacy/security risk acceptance follows the reviewed CEO escalation
route; routine scope decisions do not. Record decision-maker role, UTC date,
issue reference, accepted version and rationale here through a new PR.

Reference framework: [AICPA 2017 Trust Services Criteria, revised points of focus
2022](https://www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022).
HOME-30's proposed control SCOPE-01 supports CC2.1 (system information), CC3.1–CC3.2
(objectives and risk identification) and CC8.1 (changes). This is a preliminary
mapping for HOME-37 review, not a determination of criterion compliance.

## Boundary and inventory

The boundary includes all committed cluster desired state, infrastructure,
Talos patches, build sources, workflow definitions and policies in the generated
[source inventory](evidence/HOME-30-v1/inventory.json). It has 501 entries in
49 path groups and 41 literal Argo CD app registrations. Every group is included
for review, even when retired, suspended or a recovery candidate. Counts are
source artifacts, not Kubernetes objects, deployed services or active users.

`scripts/soc2-scope-inventory.py` hashes the complete Git tree population under
six explicit roots and extracts literal stack registration paths. It does not
render Helm/HCL, follow external charts, infer namespace ownership, or query
live state. Names and file counts are public repository metadata; source values
are never output. An unregistered directory is not automatically excluded.
`metrics-server` illustrates why registration and directory counts differ: it
uses a remote chart. `cordium-bootstrap` and recovery overlays illustrate why
directories are not necessarily top-level Applications.

| System layer | In-scope population and source | Boundary/verification limit |
| --- | --- | --- |
| Physical and cluster | One documented Talos/Kubernetes cluster, one control plane and three workers; QNAP NAS, node disks, LAN router, power and Internet dependencies; `docs/knowledge-base/architecture/cluster-topology.md`, `.talos/patches`, `clusters/homelab/platform` | Historical four-node topology; current hardware, firmware, physical access and health not inspected |
| Control plane and delivery | GitHub repository/actions, OpenTofu/Terragrunt, Argo CD; `IaC/terragrunt.stack.hcl`, `.github/workflows`, `policy` | Source review does not prove branch protection, approvals, state permissions or successful apply |
| Network/access | Octelium cluster/public/enterprise/storage, Istio, Multus, DNS, temporary Tailscale fallback, cert-manager | Application authentication and public callback exceptions require per-route validation; NetworkPolicy files do not prove enforcement |
| Platform | External Secrets, Harbor, storage, Crossplane, metrics-server, Prometheus, Grafana, Kiali, descheduler, policy-bot | Identity, registry, telemetry and backup dependencies remain in scope even if an app is suspended |
| AI and development | Cordium/bootstrap, Multica, OpenClaw, LiteLLM, Langfuse, Compass | Agent code execution, uploads, prompts, traces, databases and runtime identities; no personal content sampled |
| User services | AFFiNE, n8n and PostgreSQL, Fleet, NOFX, OctoBot, Dispatcharr, Deluge, Prowlarr, Radarr, Sonarr, media PostgreSQL | Include retained data and recovery paths; no trading or device enrollment performed |
| Retired/candidate sources | argocd-image-updater, github-actions-runner prune placeholders; grafana-alert-cleanup, media-postgres-recovery and nested restore candidates | Presence does not mean running; retained data, identities and unsafe reactivation remain review concerns |

The existing [workload inventory](../../knowledge-base/workloads/inventory.md)
provides namespace, dependencies and persistence per application. Source code
wins over historical prose. AFFiNE/Dispatcharr suspension and retained PVCs must
remain visible in the assessment; they are not evidence of secure data disposal.

## Data classes, dependencies and flows

| Class | Examples and handling expectation | Review owner |
| --- | --- | --- |
| Public | Source, runbooks, sanitized counts/hashes | Repository maintainer |
| Internal operational | Metrics, logs, job status, system inventory | Operations/control owners |
| Confidential | Prompts, uploads, workflows, trading state, database and backup contents | Service owner; HOME-41 |
| Restricted authentication/recovery | Tokens, private keys, encryption keys, credentials, kubeconfigs, backup recovery material | Identity/recovery owner; never evidence attachments |
| Potential personal information | Identity claims, family-device metadata, user content, trace identifiers | HOME-44; purposes and retention still unknown |

```text
Maintainer -> GitHub PR/review/CI -> Terragrunt/OpenTofu -> Argo CD -> cluster workloads
                                              |                       |
                                              v                       v
                                        cloud state/IAM          NAS/local disks
User/device -> external DNS/tunnel -> Octelium/Istio -> app authentication -> service
                       Entra identity --------^                         |
AWS SSM -> External Secrets -> workload secret mounts                    v
AI clients -> LiteLLM -> external model providers; telemetry -> Langfuse/storage
Automation/webhooks <-> GitHub and external providers -> n8n/agents/trading services
Cluster/app state -> declared backup jobs -> NAS and separately gated offsite paths
```

| Trust crossing | Exchanged data and dependency | Complementary responsibility / unknown |
| --- | --- | --- |
| Repository/CI to cluster/cloud | Desired state, artifacts, deployment identity; GitHub, registries/charts, AWS | Maintainers review source and protect credentials; verify protections and grants independently |
| Internet to private services | Requests/callbacks through Cloudflare DNS/tunnel, Octelium and Istio | Users protect endpoints and authenticate; native app routes need their own checks; no blanket authentication claim |
| Identity/secret providers | Entra identity claims, AWS SSM secret material, certificate issuance | Provider availability and account recovery outside cluster; HOME-33 verifies contracts and account controls |
| AI/agent egress | Prompts, code, tool results; model APIs including OpenRouter; messaging integrations | Operators minimize transmitted data and review provider retention; exact permitted data and provider list unapproved |
| Trading/media/device providers | Exchange requests, content queries and device management; Fleet/Apple dependencies | Operators authorize consequential actions; funds, licenses and device-owner consent unverified |
| Workloads to persistence/recovery | Databases, blobs, logs, NAS/local state, backup artifacts | Retention is not independent backup; operator must prove restore, custody and recovery-key availability |
| Physical LAN/power/ISP | Management access, NAS traffic, connectivity | Physical owner controls hardware and network; no facilities or ISP assurance obtained |

These are dependency interfaces, not an assertion that supplier controls were
examined. Supplier internals and unrelated household endpoints are outside direct
implementation scope; their access, data exchanges and failure consequences stay
in scope. Fleet-managed endpoint posture requires an explicit enrollment boundary.

## Roles and limitations

CSO owns scope synthesis, sequencing and closure after independent acceptance.
The Security Evidence Engineer prepares code/evidence and cannot approve it.
Homelab QA reproduces the exact revision; Third Party Auditor reviews separately
and records ACCEPTED or CHANGES_REQUESTED as an internal readiness verdict.
Decision Desk owns ordinary delegated decisions; Decision Review Lead handles
cross-domain disputes and reviews any CEO escalation. Operators hold execution
authority only when separately granted. HOME-31 must establish the final owner
matrix and compensating review for single-person operation.

Open unknowns: actual users/contracts, complete external-provider roster,
live-versus-declared drift, enforcement of isolation, restore coverage,
service-specific retention and recovery objectives, device enrollment and
physical controls. No live access, secret reads, deployments, provider selection,
permission changes or risk acceptance occurred in HOME-30.

## Scope change and reproduction procedure

1. The proposer opens a HOME issue with changed service/data/flow, purpose,
   boundary impact, risks and rollback. Use the current main SHA and inspect
   open PRs, including pending control work.
2. Run the collector at the proposed revision and compare with the prior packet.
   Any source-population mismatch requires reconciliation; never replace a
   baseline merely to make the comparison pass. Reconcile chart/rendered and
   live populations separately when authorized.
3. Update this versioned description, applicability decisions, dependency/owner
   mapping and evidence packet. Preserve prior packets and explicitly supersede
   them. CSO routes decisions to the delegated owner; record approval, not intent.
4. QA reproduces before Auditor review. Requested changes require a new packet.
   Only CSO closes after acceptance plus merge or an approved exception.
5. Recheck current main before merge and recollect if inputs changed. This PR
   grants no merge or live execution authority. Roll back documentation/tooling
   through a reviewed revert; retain the evidence history. No workload rollback
   is needed because runtime configuration is unchanged.

From repository root:

```sh
python3 scripts/soc2-scope-inventory.py --revision 58ecf587d3069fb8e504ac319e2bec2de05785c0 --check docs/compliance/soc2/evidence/HOME-30-v1/inventory.json
python3 scripts/soc2-scope-inventory.py --revision HEAD --check docs/compliance/soc2/evidence/HOME-30-v1/inventory.json
python3 -I scripts/ci/soc2-scope-inventory-test.py
git diff --check
```

The checker is an explicit review command, not an enforced CI or merge gate.
The current change introduces no new platform or recurring automation.
