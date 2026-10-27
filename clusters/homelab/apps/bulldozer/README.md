# Bulldozer

Bulldozer is the Stuhlmuller GitHub App that squash-merges eligible PRs after
GitHub permits the merge. Its repository-wide default considers every PR.
`allow_merge_with_no_checks: true` includes repositories without required checks;
there, a PR may merge without CI if GitHub allows it. Where branch rules require
reviews or checks, GitHub enforces them.
The branch-update feature is disabled to avoid extra CI churn.

This Deployment runs one replica after credential projection. Create a dedicated GitHub App owned by
Stuhlmuller and install it on **all repositories**. Set `BULLDOZER_APP_ID` and
`BULLDOZER_PRIVATE_KEY` as protected `Stuhlmuller/homelab` Actions secrets,
then dispatch `bulldozer-credential.yml` with exact current `main` after the
SSM placeholders exist. The fixed-target workflow stores both values before
this Deployment is enabled. Do not reuse Policy Bot's App: it has a different webhook
and permissions. GitHub App creation and installation are external registration
steps; the Argo Application alone cannot perform them.

Set the App webhook to
`https://bulldozer-hook.tail67beb.ts.net/api/github/hook`, using the generated
`/homelab/bulldozer/github-app/webhook-secret` as its secret. Grant repository
Administration read, Checks read, Contents read/write, Issues read/write,
Metadata read, Pull requests read/write, and Commit statuses read. Subscribe to
Check run, Commit comment, Pull request, Status, Push, Issue comment, Pull
request review, and Pull request review comment events. Use the App's numeric
ID for `integration-id`, not its installation ID.

SSM owns these SecureStrings:

- `/homelab/bulldozer/github-app/integration-id`
- `/homelab/bulldozer/github-app/webhook-secret`
- `/homelab/bulldozer/github-app/private-key`

External Secrets renders them into the file-mounted `bulldozer-config` Secret.
`refreshPolicy: OnChange` means an SSM correction needs a reviewed metadata
change to `externalsecret.yaml` to refresh the rendered Secret. The app has no
persistent data; retain the App identity and webhook secret during rollback.

The public Funnel host accepts only `/api/github/hook`; Bulldozer verifies the
GitHub webhook signature. Root, metrics, and other API paths are not public.
After merging the manifests, use the protected full Terragrunt apply to create
the SSM parameters and register the Argo Application,
verify Argo Synced/Healthy and the ExternalSecret Ready, then check the Funnel
route before setting the App webhook. Merge this one-replica change only after
the real credentials have been projected and the ExternalSecret is Ready. Require a successful signed GitHub
delivery and an eligible PR merging under its actual repository rules.

Private repositories on the current GitHub plan cannot enforce rulesets through
the API. Their otherwise mergeable PRs are included even without required
checks, as requested by the owner. Add enforceable branch rules before relying
on CI or reviews to gate those merges.

Render and route checks:

```sh
kubectl kustomize clusters/homelab/apps/bulldozer
kubectl kustomize clusters/homelab/apps/traefik
python3 -I scripts/ci/traefik-routes-test.py
kubectl -n automation get deploy/bulldozer svc/bulldozer externalsecret/bulldozer-config
curl -sS -o /dev/null -w '%{http_code}\n' https://bulldozer-hook.tail67beb.ts.net/
```

The root probe should return 404. It checks the route boundary, not a signed
delivery. Roll back by reverting the reviewed GitOps and Terragrunt change;
disable the GitHub App webhook or uninstall the App only if routing cannot be
restored without dropping deliveries.
