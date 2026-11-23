# Quickstart: Validate Private Tailnet Service DNS

This historical guide remains the 27-name **private resolver** rollout and
owner handoff. Its original public-record retirement instructions are
superseded by the [26-name app subdomain cutover](../005-retire-public-app-dns/quickstart.md),
which preserves the public apex and zone. The
[DNS publication contract](contracts/dns-publication.md) still defines private
answers and approval.

## Local prerequisites and render

Use the reviewed checkout, Helm, Kustomize, Python 3, `dig`, `kubectl`, Terragrunt and the repo's Nix toolchain. The DNS image and chart must have verified Harbor publication receipts before merging their consuming Argo source.

```sh
python3 -I scripts/ci/tailnet-dns-test.py
python3 -I scripts/ci/tailnet-dns-test.py --render >/tmp/tailnet-dns-render.yaml
kustomize build clusters/homelab/platform/tailnet-dns >/tmp/tailnet-dns-platform.yaml
nix flake check --no-build --all-systems
bash scripts/ci/nix-checks.sh
nix develop --command bash scripts/ci/static-checks.sh --offline-verified
```

Expected: the permanent focused test checks route/annotation parity, wildcard, Service selector and rendered ports; the explicit first-rollout check additionally requires the 27 migration names.
Helm/Kustomize render with no errors; repository validation passes. Review the rendered Service for both UDP/TCP 53, the existing `tag:homelab-ingress` and the direct Harbor digest, and the rendered
RBAC for Service-only watches. Verify the current tailnet policy still assigns that tag to the operator and allows ordinary members to reach port 53. Run the affected Terragrunt formatting and
saved-plan gate before applying its new Application; treat any unavailable gate as recorded rollout evidence rather than success.

## Resolver rollout and direct queries

After the image is published and reviewed source is merged, use the normal Terragrunt/Argo delivery path. Use an authorized tailnet member client to prove UDP/TCP 53 reachability with direct queries. Inspect rather than mutate live objects:

```sh
kubectl -n argocd get application tailnet-dns
kubectl -n tailnet-dns get deployment,service,pod
kubectl -n tailnet-dns get service tailnet-dns -o json
kubectl -n traefik get service traefik-private -o json
```

Expected: Argo is Synced/Healthy at reviewed `main`, resolver Pods are Ready, `tailnet-dns` has one published Tailscale IPv4, `traefik-private` has its current published IPv4. Use the exact resolver IP observed above as `<DNS_TAILNET_IP>`:

```sh
dig @"<DNS_TAILNET_IP>" stinkyboi.com A +noall +comments +answer +time=3 +tries=1 +notcp +ignore
dig @"<DNS_TAILNET_IP>" stinkyboi.com A +tcp +noall +comments +answer +time=3 +tries=1
dig @"<DNS_TAILNET_IP>" stinkyboi.com MX +noall +answer +time=3 +tries=1 +notcp +ignore
dig @"<DNS_TAILNET_IP>" mastodon.stinkyboi.com A +noall +answer +time=3 +tries=1 +notcp +ignore
```

Follow the complete [direct resolver verification](../../docs/networking-tailnet-ingress.md#direct-resolver-verification)
for the current approved-name inventory, exact peer/Service identity, private A/AAAA expectations and public forwarding checks.

Expected: UDP and TCP A answers for the apex match the private Traefik Service IPv4; all exact approved names and a concrete Cordium wildcard child match direct queries; approved AAAA queries have no public
address; apex MX/TXT and unrelated public hosts match their public baselines. Direct A responses must be local/private, not public fallthrough. Check representative HTTPS URLs and unchanged Traefik
restrictions. The initial 27 answers prove the Service watch publishes approved names; the offline declaration test covers future paired add/change/remove. Record the verified resolver IP and peer
identity in private rollout evidence. Check live convergence on the first later reviewed name change.

## Read-only health check and recovery

From an authorized tailnet client, query current approved names over UDP/TCP.
Inspect Argo health, resolver Pods, the DNS Service address and online proxy
identity. Restore failed declarations through reviewed Argo/Terragrunt desired
state, then repeat direct queries, ordinary OS resolution and HTTPS. Keep retired
public records absent during resolver recovery.

## Owner handoff and later cutover

**Pause here for the owner.** Give the verified IP and ask the owner to add it as a **restricted `stinkyboi.com` nameserver** in tailnet DNS. If the owner uses an exit node for these clients, enable `Use with exit node` for that nameserver. No global nameserver or public record change is part of this handoff.

After the owner reports the setting active, verify normal OS resolution from an ordinary tailnet client (for example with Python `socket.getaddrinfo`, not only `dig @server`), existing HTTPS, Fleet,
Harbor node pulls, native Cordium/API clients and Funnel callback restrictions. Then follow the current [26-name retirement gates](../005-retire-public-app-dns/contracts/cutover.md) and ingress runbook. The apex retains public A and mail records, while all 27 approved names retain private answers. If any gate fails,
keep the selected public records and restore private resolution through Argo/Terragrunt.
