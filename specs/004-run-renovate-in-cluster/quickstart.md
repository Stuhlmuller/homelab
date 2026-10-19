<!-- markdownlint-disable MD013 -->
# Verification and Cutover: Cluster Renovate

Use this after implementation. Apply only reviewed repository desired state through the existing Terragrunt, protected CI, and Argo CD paths. Commands below that inspect the cluster are read-only.

## Before the first cluster run

1. Record the current Stuhlmuller/renovate workflow/config commit, latest successful run, App PR author, and accessible repository count. Verify the App installation covers all owned repositories, including future additions. Compare actual App grants with the documented Administration-read parity exception in contracts/runner-contract.md; verify first write-enabled outcomes rather than assuming private protection settings. Do not paste private repository names into public reports.
2. Review and merge the SSM placeholder and dedicated OIDC transfer-role changes. Review the private saved plan through the existing protected apply path; secret-bearing shared-unit plans are not public PR artifacts.
3. Dispatch the reviewed, fixed-target transfer workflow in Stuhlmuller/renovate. Confirm only the declared SSM parameter metadata. Never read or print the Secret value.
4. Publish and verify the digest-pinned Renovate image through the declared Harbor mirror workflow before merging the consuming CronJob. Confirm the Argo CD Application points at main and the automation namespace is allowed.

## Static gate

Run from the homelab checkout after manifests and stack registration exist:

```sh
terragrunt --working-dir IaC stack generate
terragrunt hcl fmt --check
terragrunt hcl validate
kubectl kustomize clusters/homelab/apps/renovate
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
```

Inspect the generated Renovate Application with the render command from docs/argocd-app-onboarding.md. Run the affected non-secret Terragrunt plans through scripts/ci/terragrunt-plan.sh; use the protected private saved-plan path for shared SSM and IAM units. Validate the global Renovate config and mock App-token exchange without live credentials. A failed render, policy check, or plan blocks deployment.

Run the pinned Renovate discovery/config-resolution fixture before cutover. It
uses a temporary npm install and local fake GitHub API; no App credential or
GitHub write is needed. The fixture must pass with A, then A plus config-free
B, then A again:

```sh
renovate_fixture_dir="$(mktemp -d)"
nix develop --command npm --cache "$renovate_fixture_dir/npm-cache" --prefix "$renovate_fixture_dir" install --ignore-scripts --no-audit --no-fund --no-package-lock renovate@44.167.4
nix develop --command node scripts/ci/renovate-discovery-path-test.mjs "$renovate_fixture_dir/node_modules/renovate"
nix develop --command node scripts/ci/renovate-cache-recovery-test.mjs "$renovate_fixture_dir/node_modules/renovate"
```

## Dry-run gate

Merge the CronJob suspended with Renovate full dry-run mode committed in its global config. Confirm ExternalSecret readiness and target Secret metadata while suspended, then remove the temporary transfer grant. Unsuspend through a reviewed GitOps change only after both checks pass. Argo CD then creates hourly Jobs; the legacy daily GitHub Action remains the only writer. Inspect status and logs from the cold Job and two later scheduled Jobs using the same PVC:

```sh
kubectl get application renovate -n argocd
kubectl get externalsecret renovate -n automation
kubectl get cronjob renovate -n automation
kubectl get jobs -n automation -l app.kubernetes.io/name=renovate
kubectl logs -n automation job/<completed-renovate-job> --timestamps
```

Expect owner-filtered discovery, all App-accessible eligible repositories, no onboarding PR for a config-free repository, and no GitHub writes. Verify the PVC remains bound across distinct Pod UIDs; record a scoped package-cache hit for the same datasource key or an independent mock-registry request count, using the marker in the pinned image. A shorter second run alone is insufficient. The temporary custom manager and canary file already live in Stuhlmuller/renovate; its v0.0.1 release is published. Confirm the first cold lookup, then a hit for the same github-releases datasource key in two consecutive hourly scheduled Pods with distinct UIDs. Only the exact `Returning cached value` marker is temporarily remapped from TRACE to INFO. Inspect restricted logs for namespace `github-releases-datasource-v2` and key `https://api.github.com/:Stuhlmuller:renovate` in both warm Pods. Keep the hourly schedule and normal cache freshness rules. Publish v0.0.2 only through the reviewed companion workflow and confirm a later scheduled scan sees it after normal cache refresh. Remove the companion fixture, canary rule, and workflow through a reviewed PR after acceptance; delete renovate.json only if it remains canary-only. Remove the log remap through a reviewed homelab PR before enabling writes. The INFO record retains `namespace` and `key`, which can identify private repositories or packages. Keep raw records in restricted Pod logs; publish only aggregate cache-hit results and Pod UIDs, never raw lines or keys in PRs, issues, or CI output. If the App sees fewer repositories than the owner inventory or its installation does not select all repositories, stop cutover and add a reviewed, repository-owned access-management path before changing the installation.

The mock discovery fixture above proves the add/remove rule; it does not claim
that a real owner transfer occurred.

## Retire the old workflow and enable writes

1. After full dry-run parity is proven and the last 00:00 UTC legacy run finishes, merge the reviewed companion Stuhlmuller/renovate change that deletes the entire legacy workflow, including schedule and workflow_dispatch. Verify no nonterminal legacy run remains across scheduled and manual events, including requested, pending, queued, waiting, or in-progress states. If deletion cannot merge or runs have not drained, keep the cluster runner in full dry-run mode.
2. From exact reviewed companion `main`, run `scripts/retire-renovate-actions-key.py` to remove only the repository-level `RENOVATE_PRIVATE_KEY` Actions secret. Require its current-main receipt: both SSM SecureStrings are past placeholder versions, the ExternalSecret refreshed later and is Ready, no same-name organization or environment secret exists, the old key is absent, and zero nonterminal old runs remain. Repeat the guard if companion `main` moves. Historical workflow revisions can be rerun, so do not enable cluster writes while the old key exists.
3. Only after that receipt, remove full dry-run mode in a reviewed homelab GitOps change. Wait for a scheduled Job to finish. Check its start/end timestamps, per-repository outcomes, one eligible PR or explicit deferral, existing App author, and current auto-merge policy under repository protection. Confirm no overlapping Jobs. The interval between deletion and the first write-enabled Job is a planned no-writer gap.
4. Before the seven-day window, freeze a reproducible sample from the baseline dependency inventory across every active datasource class and public/private sources where present. Reconcile the temporary read-only observer and protected ledger through GitOps; it must not mount the production Renovate cache or write to GitHub. Poll sampled upstream versions every 15 minutes, retaining private last-absent/first-present evidence. Compare the conservative last-absent bound with GitHub PR or timestamped policy-deferral evidence. Report the sample denominator, event count, outages, timing-ambiguous cases, and canary separately; fewer than ten eligible natural events is inconclusive. Compare planned hourly starts with actual starts: at least 95% within 15 minutes, no overlaps, and at least 95% of eligible sampled versions proposed or explicitly deferred within four hours. Check failed-Job and freshness alerts, including a missed-cycle test through a reviewed temporary schedule suspension if needed. Remove the observer and ledger through reviewed GitOps desired state after retaining safe aggregate evidence. Retain an operational follow-up to verify the first real owner add/remove transition.

In the companion checkout, run its workflow lint and redacted secret scan on the transfer workflow and the removal of the legacy Renovate workflow before merging those changes.

Useful read-only checks:

```sh
kubectl get cronjob renovate -n automation -o yaml
kubectl describe job <completed-renovate-job> -n automation
kubectl get pvc -n automation
gh run list --repo Stuhlmuller/renovate --workflow renovate.yml --limit 10
```

If a run fails, inspect Job conditions, ExternalSecret status, and restricted logs; correct the declared configuration and let the next hourly run retry. If the cache is corrupt, change the PVC lifecycle through reviewed desired state and allow Renovate to rebuild it. For rollback, suspend the cluster CronJob through reviewed GitOps and verify Argo CD synced to that exact homelab `main` revision with no pending or active Renovate Job or Pod. From exact reviewed companion `main`, use `scripts/restore-renovate-actions-key.py` to restore only the repository Actions private-key secret from its fixed SSM path, and verify its receipt before restoring the legacy workflow through a reviewed PR. This restore works during an ExternalSecret outage. Preserve the cache unless its contents caused the failure.
