# Multica GitHub integration

The dedicated private `rstuhlmuller-multica` GitHub App serves the self-hosted
Multica deployment. Install it on **only `rstuhlmuller/minecraft-schematics`**
under the personal `rstuhlmuller` account. This is the Block Library repository;
`rstuhlmuller/blocklibrary` is not its GitHub name.

The reviewed configuration is
[`github-app-manifest.json`](../clusters/homelab/apps/multica/github-app-manifest.json).
It grants read-only metadata, contents, pull requests, checks, and statuses.
This integration provides repository discovery and PR/CI metadata. It does not
provide Git push credentials to the agent runtime; that is a separate identity.

## Bootstrap before activation

1. Merge the SSM placeholder/credential-publication prerequisites first. Apply
   `IaC/live/aws-ssm-parameters` through the protected Terragrunt workflow and
   inspect its plan; it manages shared secrets, not only Multica. Do not merge
   the activation change while any of the four parameters is missing or still
   `REPLACE_ME`.
2. Register the dedicated App using GitHub's
   [manifest flow](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest)
   and the committed manifest. A local registration receiver may supply a
   loopback `redirect_url` and random `state` for this one-time exchange; these
   are not the installed App's setup URL. Keep the conversion response private
   in an owner-only file outside the repository. It contains `id`, `slug`,
   `pem`, and `webhook_secret`. Do not paste it in chat, logs, or a PR.
3. From a clean checkout of the reviewed current `main`, validate then publish:

   ```sh
   chmod 600 /private/path/multica-app.json
   python3 -I scripts/multica-github-secrets.py /private/path/multica-app.json
   python3 -I scripts/multica-github-secrets.py /private/path/multica-app.json --apply
   ```

   The publisher writes only the four declared `SecureString` parameters under
   `/homelab/multica/github-app/` in `us-west-2`, using `alias/aws/ssm`. It checks
   all targets before writing and never prints values. Writes are not atomic;
   if publication fails, rerun with the same private file before activation.
   OpenTofu ignores later changes to these externally issued values. Never
   reuse another workload's App or credentials.
4. Merge the activation change, which creates
   `ai/multica-backend-github-secrets`, switches the backend chart's
   `existingSecret`, and adds the exact callback routes. The new Secret name
   rolls the backend under Argo CD; a Helm `lookup` checksum cannot reliably
   observe external Secret rotation during Argo rendering. PostgreSQL and the
   runtime init container keep their current Secrets.
5. In Multica, choose **Settings → Code → Connect GitHub**. Install on the
   personal account with **Only select repositories → minecraft-schematics**.
   Start from Multica so the setup redirect contains its signed workspace state.
   Then use **Pick from GitHub** to add the repository and link it to the desired
   project's Resources.

GitHub registration and installation require the owner's browser session and
approval of the displayed repository access. The configuration is prepared;
registration, secret publication, deployment, installation, and live acceptance
are not implied by a passing render or a merged prerequisite PR.

## Callback boundary

Cloudflare's existing `multica.stinkyboi.com` Tunnel route retains Octelium for
normal UI, authentication, API, and WebSocket requests. Only exact paths
`/api/webhooks/github` and `/api/github/setup` route to Istio with the internal
Host `multica-github.stinkyboi.com`; this name needs no public DNS record.
The dedicated VirtualService allows only POST webhook and GET setup requests,
with no catch-all or retry policy. It forwards through the existing frontend
proxy, preserving the current mesh client permissions.

Multica v0.4.29 checks webhook SHA-256 HMAC before processing events and verifies
the setup callback's signed workspace state. Unsigned webhooks must fail.
The Cloudflare configuration revision changes with the routing table so both
tunnel pods actually reload it. Keep the fixed-code login behind Octelium.

## Validation and live acceptance

```sh
nix develop --command python3 -I scripts/ci/multica-github-check.py
nix develop --command bash scripts/ci/static-checks.sh
kubectl -n ai wait --for=condition=Ready externalsecret/multica-backend-github-secrets --timeout=2m
kubectl -n ai rollout status deployment/multica-backend --timeout=5m
curl -i -X POST https://multica.stinkyboi.com/api/webhooks/github \
  -H 'Content-Type: application/json' -H 'X-GitHub-Event: ping' --data '{}'
curl -I https://multica.stinkyboi.com/
```

Require backend `401 invalid signature` for the unsigned webhook, and an
Octelium denial for anonymous normal app access. Missing/invalid setup state
must redirect with `github_error` and create no connection. Require a signed
GitHub ping delivery to return 200, the authorized repository to appear in the
picker, and an existing PR's CI to load. Do not create a real PR merely to test.

## Rollback and rotation

Revert the activation change: restore `existingSecret: multica-backend-secrets`
and remove the callback-specific Tunnel rule/VirtualService. Advance the Tunnel
configuration revision again. Keep database/uploads PVCs and the original
backend Secret. Disconnect the installation in Multica and revoke its GitHub
repository access when retiring the integration; neither GitOps rollback nor
Multica Disconnect uninstalls the GitHub App.

For rotation, validate/publish the replacement App credentials through the same
script, then change the ExternalSecret revision and its target Secret name plus
the chart reference together through Git. Coordinate webhook-secret changes
with GitHub to avoid rejecting deliveries during the transition.
