# Staged Tailscale cutover

The foundation deploys parallel Traefik ingress and operator utilities. Cutover
uses two separate source changes so DNS does not strand CI or operator access:

- **Phase 2a, before DNS:** after Traefik, both Funnel proxies, certificates,
  and provider-owned policy pass live acceptance, remove the legacy DNS writer
  and its restoration workflow. Switch internal API/Harbor CoreDNS, n8n's
  advertised webhook URL, and the additive Cordium/Traefik NetworkPolicies.
  Existing CI and native operator transport remain available.
- **Phase 2b, after DNS:** after Mac migration and normal canonical DNS/API
  acceptance, switch all eight CI workflows and the shared native operator
  transport to Tailscale. Publish and verify the scoped CI identity bindings
  before merging this change.

The new Funnel route must work before the n8n rollout: restarting n8n can
re-register external hooks using its new URL. CoreDNS and access policies move
before public DNS so in-cluster Octelium callers already have working API and
Harbor paths. Keep the existing Octelium routes, Cloudflare Tunnel Deployment,
legacy callback names, native catalog, credentials, and owned Mac backups until
replacement acceptance. Fleet has no Funnel route.

## Before execution

Merge the reviewed source and use a clean checkout of the exact current `main`.
Confirm Traefik and both Funnel proxies are synced and healthy, certificates are
Ready, and the private ingress Service publishes the unique online
`homelab-ingress.tail67beb.ts.net` peer. Before DNS changes, reconnect the Mac's
existing authorized Tailscale profile without changing Desktop or its carrier:

```sh
python3 -I scripts/multica-desktop-connect.py --resume-only
```

This verifies the saved tailnet and owner before reconnecting, then requires the
ingress peer online. Complete the Desktop/carrier migration only at step 5.

The DNS utility uses the existing `octelium-nofx-reconcile.py` reviewed-main
guard only. Keep its old native transport through phase 2a; changing that
shared transport before DNS and Mac migration would strand its existing callers.

Run local checks before executing any utility:

```sh
nix develop --command python3 -I scripts/ci/tailscale-private-dns-test.py
nix develop --command python3 -I scripts/ci/octelium-macos-api-carrier-test.py
nix develop --command python3 -I scripts/ci/multica-desktop-connect-test.py
nix develop --command python3 -I scripts/ci/policy-bot-webhook-test.py
nix develop --command python3 -I scripts/ci/n8n-github-webhooks-test.py
```

## Cutover order

1. Keep working operator access. Before changing Harbor DNS, converge the
   reviewed Talos host-only registry mapping and prove image pulls from every
   node. Converge any required internal CoreDNS, application access, and n8n
   `WEBHOOK_URL` changes through the reviewed phase 2a GitOps change. Confirm
   n8n uses `https://n8n-webhook.tail67beb.ts.net/` after its rollout.
2. Phase 2a removes the legacy `octelium-public-tunnel.yml` DNS-restoration
   workflow and `octelium-public-dns.sh`. Wait for any in-flight run to finish
   before writing private DNS. Keep the tunnel Deployment running for remaining
   legacy callers and rollback; neither deleted writer may restore public CNAMEs.
3. Verify private TLS and upstream readiness at each published mesh address,
   then preview the fixed DNS changes:

   ```sh
   python3 -I scripts/tailscale-private-dns-check.py --check
   scripts/tailscale-private-dns.sh --dry-run
   ```

4. Apply DNS from the reviewed clean checkout:

   ```sh
   scripts/tailscale-private-dns.sh --execute --expected-sha '<merged-main-sha>'
   ```

   The helper writes and reads back only the fixed application/control DNS-only
   A/AAAA records. It preserves old CI, callback, and carrier names, plus
   unrelated DNS record types. It reports the largest observed old authoritative
   TTL. A failed write can leave partial DNS changes; inspect and rerun the same
   idempotent command. Successful API readback is not client acceptance.
5. On the existing Mac, migrate as the signed-in user:

   ```sh
   python3 -I scripts/multica-desktop-connect.py --resume-tailscale
   ```

   This can resume only the verified saved Tailscale profile. It validates
   authenticated canonical Multica access and native API TLS/gRPC before
   retiring owned local transports. It preserves current token/profile data,
   backs up owned files, and restores the current carrier state if canonical
   API validation fails after removing the hosts override. Restart Multica,
   verify both runtimes, then check authenticated Octelium status and an actual
   Cordium action/reconnection. Keep `octelium-macos-api-carrier.py install`
   available for reviewed rollback until acceptance.
6. Wait at least the reported old TTL after the last DNS write, then verify:

   ```sh
   python3 -I scripts/tailscale-private-dns-check.py --verify-dns
   ```

   This requires authoritative answers, normal OS resolution, canonical TLS,
   native gRPC/gRPC-Web, and upstream readiness. It deliberately runs separately
   from DNS writes: the old Mac hosts stanza must first be removed by step 5.
7. Once Funnel is reachable from outside the mesh and its root/admin paths fail,
   preview and migrate the fixed GitHub callbacks:

   ```sh
   python3 -I scripts/policy-bot-webhook.py
   python3 -I scripts/n8n-github-webhooks.py
   python3 -I scripts/policy-bot-webhook.py --execute --expected-sha '<merged-main-sha>'
   python3 -I scripts/n8n-github-webhooks.py --execute --expected-sha '<merged-main-sha>'
   ```

   Policy Bot uses its existing GitHub App identity. n8n changes only repository
   hooks `589400612` and `636944763`. Both helpers preserve secrets and settings,
   preflight without triggering workflows, and save non-secret cutover receipts
   under `~/.local/state/homelab`. Do not delete these receipts before acceptance.
   After naturally occurring deliveries, require fresh success:

   ```sh
   python3 -I scripts/policy-bot-webhook.py --require-delivery
   python3 -I scripts/n8n-github-webhooks.py --require-delivery
   ```

   These checks never trigger an event or redelivery. Both delivery ID and
   timestamp must be newer than the saved cutover. Old successes do not count.
8. Merge phase 2b only after the operator's normal DNS/API path passes step 6
   and the provider-owned CI identity bindings are published. Verify a protected
   plan and apply, the plan identity's real admission-denial check, and Cordium
   native execution/denial/cleanup from the runner. The same change moves the
   shared native operator transport; retain the legacy catalog and credentials
   until those acceptance checks pass.

## Final retirement

Require all private app checks, Fleet device check-in, Harbor pulls, migrated CI,
fresh signed callback deliveries, and Cordium execution/reconnection before a
separate retirement change. That change removes old application/native catalog
routes, obsolete credentials, the Cloudflare Tunnel, and finally legacy DNS.
This preparation DNS helper has no legacy-route retirement action.

Until then, preserve Enterprise PVCs, Cordium state, existing credentials, and
owned Mac backups. Roll back through reviewed desired-state changes or the
retained carrier installer; never restore an old desktop token/profile backup
without checking it against the current working credentials. See the
[Traefik acceptance guide](README.md#validation-and-cutover) for route boundaries.
