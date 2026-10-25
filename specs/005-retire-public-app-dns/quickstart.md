# Quickstart: Validate App Subdomain DNS Retirement

Use [the cutover contract](contracts/cutover.md) for the exact scope and
evidence fields. This guide starts after the private resolver, restricted
tailnet DNS setting, and Traefik routes from
[`004-tailnet-service-dns`](../004-tailnet-service-dns/) are deployed.
The current private resolver check covers 29 names, including the apex and two
staged Enterprise names. Public deletion selects only the 26 non-apex names
from the fixed first 27 migration entries.

## Local checks before the retirement PR

From the repository root:

```sh
bash -n scripts/tailscale-private-dns.sh
python3 -I scripts/ci/tailscale-private-dns-test.py
python3 -I scripts/ci/tailnet-dns-check-test.py
python3 -I scripts/ci/tailnet-dns-test.py --initial-migration
nix develop --command bash scripts/ci/static-checks.sh --offline-verified
```

Expected: the helper is syntactically valid; the retirement fixtures prove
that only 26 exact names' A/AAAA/CNAME can be deleted, while the apex and
unrelated records survive; the private resolver still approves all 29 names;
repository validation passes. Record unavailable tools or checks rather than
claiming they passed.

## Read-only live acceptance

Use the reviewed `main` checkout on the trusted operator Mac with read-only
Kubernetes access and the correct tailnet profile. Confirm Argo reports the
DNS and Traefik Applications Synced/Healthy and observe the DNS Service IP:

```sh
kubectl -n argocd get application tailnet-dns traefik
kubectl -n tailnet-dns get deployment,service,pod
kubectl -n tailnet-dns get service tailnet-dns -o json
python3 -I scripts/tailnet-dns-check.py --server DNS_TAILNET_IPV4
python3 -I scripts/tailscale-private-dns-check.py --retire-private --check
```

Replace `DNS_TAILNET_IPV4` with the observed Service tailnet IPv4. The direct
checker verifies the signed proxy and all 29 current approved answers over UDP/TCP;
the retirement route check verifies current Traefik Service addresses and the
original 27 HTTPS paths. Bare `--check` also probes the two staged Enterprise
backends; their readiness is a separate rollout gate.
It accepts a backend error for an intentionally stopped app only when reviewed
source and the live Deployment both declare zero replicas.
Confirm the owner's restricted `stinkyboi.com` nameserver is active, then test
all 29 names through an ordinary client's OS DNS path, including a concrete
Cordium wildcard child. Record Fleet setup denial and device check-in, fresh
Harbor node pulls, native API, Cordium reconnect, and public callback results
using the [ingress runbook](../../clusters/homelab/apps/traefik/CUTOVER.md).
For the callback gate, retire the unused Codex Review Helper hook through the
reviewed `scripts/n8n-github-webhooks.py --retire-helper --execute` path, then
require its ID and callback path to be absent and fresh successful Emergency
Bot and Policy Bot deliveries. Do not publish the inactive helper workflow.
Review known off-tailnet callers of each of the 26 names and record
`migrated` or `accepted_loss` for each name in the private evidence. Do not
mark a confirmation true merely because a script ran.

Capture public apex A/MX/TXT and any existing CAA, the zone's NS/SOA,
intentionally public names, and the four legacy names. Keep these read-only
results outside the public repository as the comparison baseline. Check public
DNS-01 readiness before deletion and again after the old TTL:

```sh
dig +trace stinkyboi.com NS
dig @<CLOUDFLARE_NS> stinkyboi.com SOA +norecurse +noall +comments +answer
kubectl -n cert-manager wait externalsecret/cert-manager-cloudflare-api-token --for=condition=Ready --timeout=30s
kubectl wait clusterissuer/letsencrypt-cloudflare --for=condition=Ready --timeout=30s
kubectl -n traefik wait certificate/traefik --for=condition=Ready --timeout=30s
kubectl -n istio-system wait certificate/stinkyboi-wildcard --for=condition=Ready --timeout=30s
kubectl get clusterissuer letsencrypt-cloudflare -o jsonpath='{.spec.acme.solvers[0].selector.dnsZones[0]}{"\n"}'
kubectl get clusterissuer letsencrypt-cloudflare -o jsonpath='{.spec.acme.solvers[0].dns01.cloudflare.apiTokenSecretRef.name}{" "}{.spec.acme.solvers[0].dns01.cloudflare.apiTokenSecretRef.key}{"\n"}'
kubectl -n cert-manager get externalsecret cert-manager-cloudflare-api-token -o jsonpath='{.spec.target.name}{" "}{.spec.data[0].remoteRef.key}{"\n"}'
kubectl -n traefik get certificate traefik -o jsonpath='{.spec.issuerRef.name}{"\n"}'
kubectl -n istio-system get certificate stinkyboi-wildcard -o jsonpath='{.spec.issuerRef.name}{"\n"}'
```

Use a Cloudflare nameserver shown in the parent delegation for
`<CLOUDFLARE_NS>`. The trace must show Cloudflare delegation and the direct SOA
query must show an authoritative `aa` response. The four Ready checks must
succeed on both passes. The non-secret reference outputs must match the
pre-cutover snapshot and reviewed source:
[`issuer.yaml`](../../clusters/homelab/apps/cert-manager/issuer.yaml) must keep
the `stinkyboi.com` Cloudflare DNS-01 solver pointing to
`cloudflare-api-token` key `token`;
[`externalsecret.yaml`](../../clusters/homelab/apps/cert-manager/externalsecret.yaml)
must keep its SSM reference and target Secret; the
[Traefik](../../clusters/homelab/apps/traefik/certificate.yaml) and
[Istio](../../clusters/homelab/apps/istio/certificate.yaml) Certificates must
keep `letsencrypt-cloudflare` as issuer. These checks do not trigger renewal.

Before any deletion, inspect the complete paginated public-zone
wildcard/CNAME/NS inventory and effective authoritative public answers for all
26 target names and a concrete Cordium child. The helper blocks a relevant
child NS delegation before the first DELETE; it does not traverse or change
child zones. An out-of-set wildcard or CNAME chain that could still answer a
target after its exact record is removed, or an incomplete check, also blocks
execution. It also requires the selected Cloudflare API zone's nameservers to
match the parent delegation and aborts if a TTL reply fails or is not
authoritative. Preserve conflicting records pending a separate reviewed scope.

## Preview and execute

After the helper change is merged to `main`, from a clean checkout of that
reviewed commit:

```sh
mkdir -p -m 700 ~/.local/state/homelab
scripts/tailscale-private-dns.sh --retire-private --dry-run \
  --baseline-out ~/.local/state/homelab/app-subdomain-retirement.json
```

Expected: the preview lists only exact A/AAAA/CNAME records for 26 non-apex
names, the largest old authoritative TTL, and a private evidence template.
The public apex must not appear in `checked_names` or `baseline_records`.
Complete the evidence from current checks and review every proposed Cloudflare
record ID, type, and owner. Confirm the pre-delete wildcard/CNAME/NS guard passes.
Other owners and non-address records at selected owners remain untouched. A
wrong owner returned for an exact-name query or a changed target baseline
blocks execution. A previous 27-name evidence file is invalid.

Run the write only when every contract gate passes:

```sh
scripts/tailscale-private-dns.sh --retire-private --execute \
  --expected-sha REVIEWED_MAIN_SHA \
  --evidence ~/.local/state/homelab/app-subdomain-retirement.json
```

Replace `REVIEWED_MAIN_SHA` with `git rev-parse HEAD` from that exact merged
`main` checkout. Execution rechecks live records, the wildcard/CNAME/NS guard,
signed private DNS, normal client lookups, and HTTPS before any DELETE. It
re-reads full record fields after the zone scan immediately before deletion. A
wrong-owner response, changed target baseline, or failed preflight stops the
write. If a partial run fails,
investigate it and retry through the same helper and evidence; never patch
Cloudflare by hand.

## Verify and recover

Wait the helper's reported old maximum TTL from the last deletion. Query each
of the 26 owner names and `dns-preflight.cordium.stinkyboi.com` for A, AAAA,
and CNAME at the effective authoritative nameservers (following any child
delegation) and a public recursive resolver. Every answer section must be
empty. A CNAME chain or broader wildcard response is a failure requiring a
separate reviewed decision.
Compare apex and unrelated public answers with the pre-cutover snapshot and
re-run normal tailnet DNS, HTTPS, and critical caller checks. Repeat the
Cloudflare delegation, ExternalSecret, ClusterIssuer, and both Certificate
checks above; compare the DNS-01 solver and secret references with reviewed
source.

If private DNS fails, run `scripts/tailnet-dns-check.py` again, inspect Argo,
resolver Pods, Service status, and the signed proxy, then restore the failed
repository declaration through Terragrunt/Argo or re-sign the fixed proxy.
Retired subdomains must not receive public app addresses during a controlled
resolver outage check. The apex intentionally retains a public address
answer; its outage behavior is outside that guarantee. Do not republish retired app
records as an outage repair. A policy reversal requires a separate reviewed
change.
