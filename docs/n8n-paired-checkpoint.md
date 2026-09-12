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
| Remove readers | App remains stopped | Cold overlay; Argo prunes readers |
| Resume database | App remains stopped | Original StatefulSet at 1; wait SQL readiness |
| Resume app | Original values and routes | Original StatefulSet at 1 |

All remote source revisions remain `main`. Run this maintenance serially and
pause merges affecting the homelab until it finishes. The operator requires
both Applications to report the prepared main revision; a revision change
invalidates capture. The ordinary catalog hook refuses n8n plan/apply/destroy
while either Application carries an active maintenance marker. The serial
runner's permit binds exact saved-plan bytes, the fixed profile and observed
previous markers. Resume first verifies that current main has unchanged n8n
source directories, allowing unrelated merges without adopting an unreviewed
image or storage change. Existing backend locks still serialize each unit's apply.
This is an operator workflow, not a distributed lock service: old checkouts or
an independent actor bypassing the documented path are outside its contract.

## Prepare Before The Outage

Merge the reviewed code, pass required checks and the local gate, fetch current
main into a clean isolated checkout, generate the stack, and make existing AWS
SSO and Kubernetes access usable before starting. Do not run this from an
unmerged feature branch. Keep the same checkout and private session directory
available through resume.

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
No snapshot, pod, or phase change occurs during preparation.

Keep free space comfortably above the combined source size. The September 7
metadata estimate was about 217 MiB; that estimate can become stale. Streaming
also stops at the 128 MiB local reserve. Each archive has a 300-second remote
command limit; the reader Pods have a 900-second lifetime. These bounds limit
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
path. Reader removal must finish before database restart. If nodes cannot be
reached or writer state remains uncertain, automatic resume stops rather than
creating another possible writer. Preserve the session and use the same
reviewed code after healthy source fencing is available:

```sh
python3 scripts/n8n-paired-checkpoint.py resume \
  --session-directory /absolute/private/n8n-pair-SESSION
```

Resume retains all candidate archives and original claims. It verifies the
original images, PostgreSQL SQL readiness, n8n database-aware readiness and
zero new restarts. Failed captures are not retried in place: resume, prepare a
new session and retain the failed evidence. Verify both public n8n entry paths
and scheduled automation behavior separately after return to service. No
archive is automatically restored, overwritten, uploaded or pruned.

## Source And Limits

PostgreSQL's [filesystem backup guidance](https://www.postgresql.org/docs/14/backup-file.html)
requires a stopped server and the complete cluster. Physical recovery depends
on compatible PostgreSQL version/platform. This checkpoint does not establish
full application recovery or lossless external workflow delivery. The contract
assumes these are the only writers on the declared claims; external NFS clients
are not inventoried. The repository does not currently prove QNAP snapshot
coverage, so a NAS snapshot must not be substituted for this matched capture.
