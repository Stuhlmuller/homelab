<!-- markdownlint-disable MD013 -->
# Verification and Cutover: Cluster Renovate

Use this after implementation. Apply only reviewed repository desired state through the existing Terragrunt, protected CI, and Argo CD paths. Commands below that inspect the cluster are read-only.

## Before the first cluster run

1. Record the current Stuhlmuller/renovate workflow/config commit, latest successful run, App PR author, and accessible repository count. Verify the App installation covers all owned repositories, including future additions. Do not paste private repository names into public reports.
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

Merge the CronJob suspended with Renovate full dry-run mode committed in its global config. Confirm ExternalSecret readiness and target Secret metadata while suspended, then remove the temporary transfer grant. Unsuspend through a reviewed GitOps change only after both checks pass. Argo CD then creates hourly Jobs; the legacy daily GitHub Action remains the only writer. Inspect status and logs from two consecutive Jobs, including a new Pod using the same PVC:

```sh
kubectl get application renovate -n argocd
kubectl get externalsecret renovate -n automation
kubectl get cronjob renovate -n automation
kubectl get jobs -n automation -l app.kubernetes.io/name=renovate
kubectl logs -n automation job/<completed-renovate-job> --timestamps
```

Expect owner-filtered discovery, all App-accessible eligible repositories, no onboarding PR for a config-free repository, and no GitHub writes. Verify the PVC remains bound across distinct Pod UIDs; record a scoped TRACE package-cache hit for the same datasource key or an independent mock-registry request count, using the marker in the pinned image. A shorter second run alone is insufficient. Add a temporary homelab custom-manager fixture that watches GitHub Releases from Stuhlmuller/renovate. Warm that lookup, publish its next controlled release through a reviewed companion workflow, and confirm a later scheduled scan sees it after normal cache refresh. Remove the fixture and canary workflow through reviewed changes after acceptance. Keep TRACE logs private. If the App sees fewer repositories than the owner inventory or its installation does not select all repositories, stop cutover and add a reviewed, repository-owned access-management path before changing the installation.

The mock discovery fixture above proves the add/remove rule; it does not claim
that a real owner transfer occurred.

## Retire the old workflow and enable writes

1. After full dry-run parity is proven and the last 00:00 UTC legacy run finishes, merge the reviewed companion Stuhlmuller/renovate change that deletes the entire legacy workflow, including schedule and workflow_dispatch. Verify no nonterminal legacy run remains across scheduled and manual events, including requested, pending, queued, waiting, or in-progress states, and no new run is possible. If deletion cannot merge or runs have not drained, keep the cluster runner in full dry-run mode.
2. Only after the old workflow is absent, remove full dry-run mode in a reviewed homelab GitOps change. Wait for a scheduled Job to finish. Check its start/end timestamps, per-repository outcomes, one eligible PR or explicit deferral, existing App author, and current auto-merge policy under repository protection. Confirm no overlapping Jobs. The interval between deletion and the first write-enabled Job is a planned no-writer gap.
3. Before the seven-day window, freeze a reproducible sample from the baseline dependency inventory across every active datasource class and public/private sources where present. Reconcile the temporary read-only observer and protected ledger through GitOps; it must not mount the production Renovate cache or write to GitHub. Poll sampled upstream versions every 15 minutes, retaining private last-absent/first-present evidence. Compare the conservative last-absent bound with GitHub PR or timestamped policy-deferral evidence. Report the sample denominator, event count, outages, timing-ambiguous cases, and canary separately; fewer than ten eligible natural events is inconclusive. Compare planned hourly starts with actual starts: at least 95% within 15 minutes, no overlaps, and at least 95% of eligible sampled versions proposed or explicitly deferred within four hours. Check failed-Job and freshness alerts, including a missed-cycle test through a reviewed temporary schedule suspension if needed. Remove the observer and ledger through reviewed GitOps desired state after retaining safe aggregate evidence. Retain an operational follow-up to verify the first real owner add/remove transition.

In the companion checkout, run its workflow lint and redacted secret scan on the transfer workflow and the removal of the legacy Renovate workflow before merging those changes.

Useful read-only checks:

```sh
kubectl get cronjob renovate -n automation -o yaml
kubectl describe job <completed-renovate-job> -n automation
kubectl get pvc -n automation
gh run list --repo Stuhlmuller/renovate --workflow renovate.yml --limit 10
```

If a run fails, inspect Job conditions, ExternalSecret status, and restricted logs; correct the declared configuration and let the next hourly run retry. If the cache is corrupt, change the PVC lifecycle through reviewed desired state and allow Renovate to rebuild it. For rollback, suspend the cluster CronJob in GitOps, verify no pending or active write-enabled Job remains, then restore the legacy workflow through a reviewed companion PR. Preserve the cache unless its contents caused the failure.
