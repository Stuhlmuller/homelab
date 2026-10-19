<!-- markdownlint-disable MD013 -->
# Renovate Runner Contract

This is a scheduled workload contract. It exposes no HTTP endpoint or new API.

## Discovery and policy

| Input | Required behavior |
| --- | --- |
| Schedule | Hourly UTC CronJob; concurrencyPolicy Forbid; starting deadline 15 minutes; active deadline below the one-hour App-token lifetime. |
| Scope | GitHub platform; autodiscover accessible repositories; filter to Stuhlmuller/*; include owned forks; skip archived repositories. Missing App access to an otherwise eligible owned repository is a cutover-blocking coverage gap. |
| Installation | The existing Renovate App must be installed for all non-archived repositories owned by Stuhlmuller and auto-cover new ownership. Compare accessible inventory with owner inventory before cutover and after ownership changes. |
| Config-free repository | onboarding false and requireConfig optional; use the committed global policy immediately. |
| Repository config | Honor each repository's Renovate file and Renovate's normal precedence; keep existing global best-practices, replacements, security, labels, lockfile, vulnerability, exclusion, and auto-merge settings. |
| Writes | Propose changes as the existing App. Auto-merge only when the effective policy and repository protection permit it. Never write directly to a protected default branch. |

The migration begins with the CronJob suspended and full dry-run mode committed in its global config. Verify ExternalSecret projection while suspended, remove the temporary transfer write grant, then unsuspend through reviewed GitOps so the first Job cannot see placeholder credentials. The separate Stuhlmuller/renovate workflow remains until full dry-run parity is proven. Delete that workflow, including manual dispatch, before removing dry-run mode through another reviewed GitOps change.

**Permission review**: Compare the existing App installation grants with [Renovate's GitHub App permission guidance](https://docs.renovatebot.com/modules/platform/github/#running-as-a-github-app) before cutover. Repository permissions are Administration read; Checks, Commit statuses, Contents, Issues, Pull requests, and Workflows read/write; Dependabot alerts and Metadata read. Merge queues read/write applies only when a managed repository uses a merge queue. Organization Members read is required for the Stuhlmuller organization. Do not broaden the App grant without a reviewed need. The Pod has no Kubernetes API credential or cluster write permission; the External Secrets controller alone reads the declared SSM parameters.

## Credential boundary

| Item | Contract |
| --- | --- |
| Source parameters | SSM SecureString names /homelab/renovate/github-app/issuer-id and /homelab/renovate/github-app/private-key; values never enter git or plan output. |
| Transfer | A manually dispatched workflow merged to protected Stuhlmuller/renovate main reads its existing GitHub Actions secrets and assumes a dedicated AWS OIDC role. Trust is limited to `repo:Stuhlmuller/renovate:ref:refs/heads/main`; the workflow checks the expected current main SHA before transfer. Write policy names only the two parameter ARNs and required encryption action. Remove transfer write access after Secret projection is verified, before scheduling starts. |
| Kubernetes projection | ExternalSecret in automation produces a namespaced Secret with issuer-id and private-key file keys; mount read-only with restrictive file mode. The Pod receives no default service-account token. |
| App exchange | The committed global config reads the files, signs a short-lived App JWT in memory, resolves the Stuhlmuller installation, and requests one installation token at Job start. Never persist the JWT, key, or token on the cache PVC, logs, process arguments, or Pod environment. Fail closed if issuer, installation, or token exchange fails. |
| Rotation | First restore the temporary transfer grant through reviewed IaC, then update only the declared SSM values through a reviewed credential workflow, refresh the ExternalSecret, verify a later Job mints a token under the same App identity, and retire the grant again. |
| Legacy key retirement | After deleting the old workflow and draining its runs, retire only the companion repository-level `RENOVATE_PRIVATE_KEY` Actions secret from exact reviewed `main` with the guarded script. Require transferred SSM SecureString versions, a later Ready ExternalSecret projection, no same-name organization or environment secret, and a post-delete receipt showing the key absent and zero nonterminal old runs. A historical workflow run can be rerun at its original revision, so workflow deletion alone does not remove the old writer. |
| Rollback key restore | First suspend the cluster CronJob through reviewed GitOps and verify Argo CD synced to that exact homelab `main` revision with no pending or active Renovate Job or Pod. From exact reviewed companion `main`, the guarded restore script reads the fixed SSM private-key path and restores only the repository Actions secret; verify its receipt before restoring the old workflow through a reviewed PR. The restore path must work during an ExternalSecret outage. |

The existing workflow calls its issuer secret RENOVATE_APP_ID but passes it as a client-id input. Implementation must verify whether that value is the App client ID or numeric App ID and use the matching GitHub JWT issuer without printing the value.

## Cache, outcomes, and alerts

| Item | Contract |
| --- | --- |
| Storage | One retained, protected nfs-default PVC mounted at /cache/renovate, set as Renovate's cacheDir in committed config. Clones and working files use an ephemeral baseDir. |
| Reuse | Enable Renovate repository extraction and private-package metadata caches; retain Renovate's default soft/hard refresh and expiry. A second Job, including after Pod replacement, must reuse valid entries and revalidate expired ones. |
| Loss | A missing or corrupt cache may be rebuilt by Renovate. No repository state or credential lives only in the cache; no backup is required. PVC reset, if needed, is a reviewed desired-state change. |
| Evidence | Kubernetes Job timestamps/status show start, completion, and duration; access-restricted Renovate logs show per-repository outcomes and errors. Never publish logs containing private repository names or package metadata. |
| Alerting | Existing failed-Job alert covers failed attempts. Renovate-specific signals detect a missed hourly start, a scheduled Job without success by its deadline, and a missing CronJob after Application registration. |

## Cutover invariant

At steady state, one runner can write to each eligible repository. Full dry runs can coexist with the legacy daily writer because they make no GitHub changes. After dry-run parity and the last legacy run, delete the complete legacy workflow in the companion repository and verify that neither its schedule nor manual trigger nor any nonterminal run across scheduled and manual events remains. Nonterminal includes requested, pending, queued, waiting, and in-progress runs. Keep the cluster runner in full dry-run mode if deletion, drainage, or guarded key retirement is delayed. Enable cluster writes through reviewed GitOps only after a current post-delete receipt proves the old repository Actions key absent and every old run drained; rerun the guard if companion `main` moves. Verify the first write-enabled run's discovery, PR identity, and effective auto-merge behavior. This sequencing allows a short no-writer gap but never two available writers. For rollback, suspend cluster writes through reviewed GitOps, verify the CronJob and all Jobs and Pods have drained, restore the Actions key through the guarded fixed-source path, then restore the legacy workflow through a reviewed companion change.

## Acceptance evidence boundary

The seven-day latency percentage is a pre-registered, stratified dependency sample, not a claim about every dependency in the fleet. A read-only observer with no shared Renovate cache records upstream last-absent/first-present brackets; GitHub proposal or timestamped deferral data supplies the outcome. Controlled canary releases are counted separately. The raw ledger is restricted and never committed. Cache reuse requires the same datasource key in two distinct scheduled Pods and a cache-hit marker verified against the pinned Renovate image, or an independent mock-registry request counter. A mocked repository add/remove sequence proves discovery logic; live owner/App inventory parity and an all-repositories installation selection prove current access, but a real ownership transition remains a later operational check.
