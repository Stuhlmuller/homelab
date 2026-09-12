# Manual n8n Paired Checkpoint

The repository can capture the stopped n8n instance directory and its complete
PostgreSQL 14 cluster as one private off-NAS set. The inactive maintenance
profiles preserve existing images, PVCs, Argo CD Applications, Terragrunt state
keys, and resource owners. This path has **not yet run against production**.
A successful capture proves archive integrity and observed clean shutdown;
application restore, activation, external integrations, recurrence, offsite
retention, and alert delivery remain unverified.

## Ownership And Phases

`scripts/n8n-paired-checkpoint.py` uses the normal generated
`IaC/live/argocd-apps/n8n` and `n8n-postgres` units. It renders their current
committed manifests, selects only a closed profile, creates a fresh plan for
each transition, verifies that the plan updates exactly its existing
`kubernetes_manifest.this`, and applies that saved plan. Resume commands are
prepared code paths; their plans are generated only after preceding state
changes finish. There is no alternate state owner or imperative scaling.

| Phase | n8n Application | PostgreSQL Application |
| --- | --- | --- |
| Normal | Original values and routes | Original StatefulSet at 1 |
| Stop app | Helm replicas 0; existing routes return 503 | Original StatefulSet at 1 |
| Cold | App remains stopped | Cold overlay sets replicas 0 |
| Capture | App remains stopped | Cold overlay plus two read-only reader Pods |
| Remove readers | App remains stopped | `recovery-cold`: cold overlay at prepared SHA; Argo prunes readers |
| Resume database | App remains stopped | `recovered`: original StatefulSet at prepared SHA; wait SQL readiness |
| Resume app | `recovered`: original values and routes at prepared SHA | Original StatefulSet at prepared SHA |
| Unpin | Original values and routes on `main` | Original StatefulSet on `main` |

Normal and capture profiles use `main`. Recovery explicitly pins this
repository's Git sources to the full prepared commit SHA; this temporary
recovery exception preserves the reviewed images, values and overlays without
an operator-side GitHub fetch. Helm chart versions remain unchanged. Argo CD
still needs its existing cached sources or repository access to reconcile.

Run this maintenance serially and pause merges affecting the homelab until it
finishes. Both Applications must report the prepared main revision during
capture; a revision change invalidates it. The ordinary catalog hook refuses
n8n plan/apply/destroy while either Application carries an active maintenance
marker, including while service is recovered at the pinned SHA. The serial
runner's permit binds exact saved-plan bytes, the fixed profile and observed
previous markers. A separate `unpin` step fetches current main and verifies
unchanged n8n sources, checkpoint scripts and IaC before restoring `main` and
clearing markers.
Existing backend locks still serialize each unit's apply.
This is an operator workflow, not a distributed lock service: old checkouts or
an independent actor bypassing the documented path are outside its contract.

## Prepare Before The Outage

Merge the reviewed code, pass required checks and the local gate, fetch current
main into a clean isolated checkout, generate the stack, and make existing AWS
SSO and Kubernetes access usable before starting. Do not run this from an
unmerged feature branch. Keep the same checkout and private session directory
available through resume and unpin. Do not advance the prepared checkout while
the session is active; recovery profiles are bound to its exact revision.

```sh
nix develop --command bash scripts/ci/static-checks.sh
python3 scripts/n8n-paired-checkpoint.py prepare \
  --destination /Users/OPERATOR/.local/share/homelab/n8n-checkpoints \
  --talosconfig /Users/OPERATOR/.talos/config \
  --talosctl /opt/homebrew/bin/talosctl
```

Create the destination beforehand with mode 0700 on durable private storage
outside every Git checkout. Temporary/cache directories are rejected. Paths shown are
operator examples; the Talos binary must match the current cluster's 1.11.3
client. Preparation performs metadata-only inspection, requires healthy
original writer identities, unchanged node boot IDs, Bound Retain NFS claims,
and at least 1 GiB free locally. It prints a unique mode 0700 session directory.
Both Applications must be Healthy and Synced at the prepared revision, with
Argo's compared sources/destination matching their current specs; capture
checks this again before the first stop. A pending chart rollout whose old Pods
remain ready cannot establish the original image baseline for maintenance.
Both original Pods must have every regular container ready with zero restarts,
at preparation and immediately before capture. This establishes a clean
starting state; recovery instead requires current readiness and the prepared
images, with observed cumulative restart counts recorded in its receipt.
Preparation and capture compare each rendered base against the complete live
Application spec;
unapplied or stale generated settings must be reconciled through the ordinary
owner before maintenance. Normalization is limited to known default source
paths, absent/empty destination name and namespace annotations, and integer
types for retry limit/backoff factor. Chart values, namespace, sync policy and
ignored differences must otherwise match exactly.
Both original generated `terragrunt.hcl` files must also match the committed
catalog template byte-for-byte at preparation and capture. This verifies the
ordinary-plan maintenance guard itself; matching rendered specs alone cannot
detect a pre-guard generated unit. Missing or edited files require fresh stack
generation before an outage.
No snapshot, pod, or phase change occurs during preparation.

Keep free space comfortably above the combined source size. The September 7
metadata estimate was about 217 MiB; that estimate can become stale. Streaming
also stops at the 128 MiB local reserve. Each archive has a 300-second remote
command limit and a 320-second client deadline plus one second to reap it.
Both reader Pods have a 3600-second deadline and sleep for 3590 seconds.
Their last required live use is the second archive stream: the budget includes
900 seconds of remaining provider apply, 240 for reconciliation, 120 for reader
readiness, 50 for the first fence, two 321-second streams and up to 90 seconds
of synchronous Kubernetes predicate overrun, totaling 2042 seconds. This leaves
more than 15 minutes for the first archive's local validation/hash and other
local I/O. Local validation has no hard deadline, so this is a conservative
allowance, not a guarantee that arbitrarily slow storage can finish. The fixture
checks rendered Pod lifetimes against the helper's actual command bounds.
Later reader-removal plans and applies need readers absent at completion, not
still running; they do not extend the required live-reader window. These bounds limit
failed capture work, not the total outage: GitOps reconciliation, workload
drain, provider calls and NFS stalls can take longer. There is no established
recovery-time objective yet.

After independent review of the prepared source and normal-unit plans, execute:

```sh
python3 scripts/n8n-paired-checkpoint.py capture \
  --session-directory /absolute/private/n8n-pair-SESSION
```

## Capture Proof And Failure Handling

The Pod watch starts before each stop and must observe exit 0 without a signal
for every original application container. Missing terminal status, timeout,
SIGKILL, changed identity, or an expired watch rejects capture. Kubernetes
absence is followed by authenticated Talos container inspection on every node;
node boot IDs and claim/PV identities must remain unchanged. No node process,
credential, workflow or provider content is inspected.

The reader Pods mount only their individual source claims read-only, without
service-account tokens or source permission changes. The n8n reader runs as
UID 1000; the database reader runs as the existing UID 65534. The pinned PG 14
utility image never starts a server. It requires a clean `pg_controldata`
`shut down` state, includes the whole PostgreSQL PVC root and WAL, and refuses
external tablespaces, links, special files or nested mounts. The entire n8n
instance tree is archived, including any legacy SQLite sidecars, without
interpreting or rewriting them.

The observer repeatedly checks source writers, nodes, claims, current phase
and revision through both streams and reader removal. It rejects failed or
expired observations. The remote command checks source metadata before and
after tar; the operator consumes all archive members without extraction,
rejects unsafe entries, matches each full-file digest to the remote stream
checksum, and fsyncs files and parent
directories. `paired-capture.json` is published exclusively after both streams
succeed, readers disappear, and the final source fence passes. An archive or
partial directory without that receipt is not an accepted pair.

Normal command failures and interrupts enter the same database-then-app resume
path. Timed-out or interrupted operator commands run in owned process groups:
the runner sends TERM, waits up to two seconds, then sends KILL to surviving
group members and allows two seconds to reap the command. Recovery starts only
after cleanup succeeds. A cleanup failure reports the group ID and blocks
automatic recovery; establish that the earlier command has stopped before
retrying. Reader removal must finish before database restart. If nodes cannot
be reached or writer state remains uncertain, automatic resume stops rather
than creating another possible writer. Preserve the session and use the same
reviewed code after healthy source fencing is available:

```sh
python3 scripts/n8n-paired-checkpoint.py resume \
  --session-directory /absolute/private/n8n-pair-SESSION
```

Resume retains all candidate archives and original claims. It verifies the
prepared images, PostgreSQL SQL readiness and n8n database-aware readiness.
Cumulative restart counts do not block service recovery;
resume and both unpin receipt paths record each observed Pod and its container
restart counts from the same readiness check. It does not fetch GitHub: both
Applications retain the prepared SHA and maintenance markers after service
returns. This also applies
after a successful capture. Verify both public n8n entry paths and scheduled
automation behavior separately after return to service.

Once GitHub is reachable, return to normal reconciliation:

```sh
python3 scripts/n8n-paired-checkpoint.py unpin \
  --session-directory /absolute/private/n8n-pair-SESSION
```

Unpin first requires healthy original workloads, fetches current main and
checks the five n8n source/maintenance directories, both checkpoint scripts and
the complete `IaC` tree against the prepared commit. The conservative IaC
check includes shared configuration, catalog units and Application modules;
even an unrelated IaC change requires review before unpinning.
Before either normal apply, it fsyncs the fetched revision to the private
`unpin-target.json` session record. It returns PostgreSQL, then n8n, to `main`
through fresh original-unit plans. Keep merges paused: if main advances during
a partial unpin, the retry preserves that target and stops for source review.
If the fetch fails or those sources changed, the existing healthy state is
preserved; during a partial retry, PostgreSQL may already follow `main`. Review
and resolve the source difference before retrying. A
partial unpin resumes with the remaining Application; an already-normal retry
records completion only after both original workloads are ready and both
Applications have reconciled to the recorded target, without another GitHub
request. Before any unpin target exists, normal completion requires the prepared
revision. Argo's compared sources and destination must match the desired profile;
a stale pinned `Synced` status cannot prove that returning to `main` completed,
even when both references resolve to the same SHA. Resume and the final unpin
step also recheck both workloads before writing completion receipts. Retain the
target record with the session; an invalid or unreadable record fails closed.
Do not start another
capture until both markers are normal. Failed captures are not retried in
place: resume, unpin, prepare a new session and retain the failed evidence.
No archive is automatically restored, overwritten, uploaded or pruned.

## Source And Limits

PostgreSQL's [filesystem backup guidance](https://www.postgresql.org/docs/14/backup-file.html)
requires a stopped server and the complete cluster. Physical recovery depends
on compatible PostgreSQL version/platform. This checkpoint does not establish
full application recovery or lossless external workflow delivery. The contract
assumes these are the only writers on the declared claims; external NFS clients
are not inventoried. The repository does not currently prove QNAP snapshot
coverage, so a NAS snapshot must not be substituted for this matched capture.
