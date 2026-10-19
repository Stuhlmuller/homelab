# Quickstart: Validate Private Tailnet Service DNS

This historical guide remains the 27-name **private resolver** rollout and
owner handoff. Its original public-record retirement instructions are
superseded by the [26-name app subdomain cutover](../005-retire-public-app-dns/quickstart.md),
which preserves the public apex and zone. The
[DNS publication contract](contracts/dns-publication.md) still defines private
answers and approval.

## Local prerequisites and render

Use the reviewed checkout, Helm, Kustomize, Python 3, `dig`, `kubectl`, Terragrunt and the repo's Nix toolchain. The DNS image must have a verified Harbor publication receipt before merging its consuming Argo source.

```sh
python3 -I scripts/ci/tailnet-dns-test.py
python3 -I scripts/ci/tailnet-dns-test.py --initial-migration
helm template tailnet-dns oci://codeberg.org/k8s-gateway/charts/k8s-gateway \
  --version 4.0.0 --namespace tailnet-dns \
  -f clusters/homelab/platform/tailnet-dns/values.yaml >/tmp/tailnet-dns-render.yaml
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

After the image is published and reviewed source is merged, use the normal Terragrunt/Argo delivery path. Run the signer and read-only checker from the configured trusted signer Mac with read-only Kubernetes access; use a separate ordinary tailnet member client to prove its UDP/TCP 53 reachability. Inspect rather than mutate live objects:

```sh
kubectl -n argocd get application tailnet-dns
kubectl -n tailnet-dns get deployment,service,pod
kubectl -n tailnet-dns get service tailnet-dns -o json
kubectl -n traefik get service traefik-private -o json
python3 -I scripts/tailscale-ingress-sign.py --dns-only
python3 -I scripts/tailscale-ingress-sign.py --dns-only --execute
```

Expected: Argo is Synced/Healthy at reviewed `main`, resolver Pods are Ready, `tailnet-dns` has one published Tailscale IPv4, `traefik-private` has its current published IPv4, and the fixed signer reports the DNS proxy signed without disabling Tailnet Lock. Use the exact resolver IP observed above as `<DNS_TAILNET_IP>`:

```sh
dig @<DNS_TAILNET_IP> stinkyboi.com A +noall +comments +answer
dig @<DNS_TAILNET_IP> stinkyboi.com A +tcp +noall +comments +answer
dig @<DNS_TAILNET_IP> stinkyboi.com MX +noall +answer
dig @<DNS_TAILNET_IP> mastodon.stinkyboi.com A +noall +answer
python3 -I scripts/tailnet-dns-check.py --server <DNS_TAILNET_IP> --initial-handoff
```

Expected: UDP and TCP A answers for the apex match the private Traefik Service IPv4; all 26 exact names and a real Cordium wildcard child pass the full check; approved AAAA queries have no public
address; apex MX/TXT and unrelated public hosts match their public baselines. Direct A responses must be local/private, not public fallthrough. Check representative HTTPS URLs and unchanged Traefik
restrictions. The initial 27 answers prove the Service watch publishes approved names; the offline declaration test covers future paired add/change/remove. Record the verified resolver IP and peer
identity in private rollout evidence. Check live convergence on the first later reviewed name change.

## Read-only health check and recovery

From the trusted signer Mac with tailnet and read-only Kubernetes access, re-run `python3 -I scripts/tailnet-dns-check.py --server <DNS_TAILNET_IP>` when DNS is suspected unhealthy and after any
recovery. The routine check follows current approved Service-annotation names rather than freezing the migration inventory. A failure identifies the affected query or path; inspect Argo Application
health, resolver Pods, the DNS Service's current status IP and the proxy's signed Tailnet Lock identity. Restore the failed declaration through reviewed Argo/Terragrunt desired state, or re-sign the
fixed proxy identity if its key rotated. Re-run direct UDP/TCP queries and the current approved-name check before testing normal OS DNS and HTTPS. Keep retired public records absent during resolver
recovery.

## Owner handoff and later cutover

**Pause here for the owner.** Give the verified IP and ask the owner to add it as a **restricted `stinkyboi.com` nameserver** in tailnet DNS. If the owner uses an exit node for these clients, enable `Use with exit node` for that nameserver. No global nameserver or public record change is part of this handoff.

After the owner reports the setting active, verify normal OS resolution from an ordinary tailnet client (for example with Python `socket.getaddrinfo`, not only `dig @server`), existing HTTPS, Fleet,
Harbor node pulls, native Cordium/API clients and Funnel callback restrictions. Then follow the current [26-name retirement gates](../005-retire-public-app-dns/contracts/cutover.md) and ingress runbook. The apex retains public A and mail records, while all 27 approved names retain private answers. If any gate fails,
keep the selected public records and restore private resolution through Argo/Terragrunt and the fixed signer.
