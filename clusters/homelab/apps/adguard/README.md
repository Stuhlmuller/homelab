# AdGuard Home

Image publication, deployment, peer identity verification and live acceptance are
tracked separately; this application does not change global Tailscale DNS.

One AdGuard Home v0.107.80 replica answers UDP/TCP 53 through the operator-owned
`adguard-dns` LoadBalancer (`homelab-adguard`, `tag:homelab-ingress`). The separate
`adguard-admin` ClusterIP serves authenticated HTTP on port 3000 behind the
private Traefik route at `https://adguard.stinkyboi.com`. Its approved name is
declared in both Traefik and the private DNS view; the existing wildcard
certificate covers it. Neither Service exposes a public endpoint or an
administration port through the DNS LoadBalancer.

After deployment, use a clean checkout of current `main` on the owner Mac.
Verify the online proxy identity and observed Service address, then run the
direct DNS and authenticated administration acceptance below before DNS cutover.

The runtime uses UID/GID 65534, a read-only root, no privilege escalation and only
`NET_BIND_SERVICE`. Its upstream binary carries file capabilities, so run it
directly: a shell wrapper can discard the capability before exec. The isolated
runtime fixture tests the direct launch with privileged-port protection enabled.
TCP probes establish listener readiness, not a loaded blocklist or successful
upstream resolution. Global DNS must wait for functional acceptance with an
enabled, nonempty filter.

The default AdGuard DNS filter refreshes daily. Blocking returns `0.0.0.0`/`::`
with TTL 10. General DNS uses the existing Cloudflare malware-filtering servers;
private `stinkyboi.com` queries use the numeric cluster-local `tailnet-dns`
Service address resolved at startup. There is no fallback resolver. Per-source
rate limiting is disabled because operator proxies can aggregate client traffic.
Query history, file query logs, statistics and automatic client discovery are off.

The NetworkPolicy declares DNS ingress from Tailscale, administration from
Traefik, cluster/private DNS, the two public upstreams and public HTTPS filter
downloads. The existing Flannel installation does **not** enforce NetworkPolicy.
Actual external access relies on tailnet grants, device authentication and administration
authentication; this manifest is not evidence of enforced Pod isolation.

The generated SSM `/homelab/adguard/admin-password` credential is 32 ASCII
characters. ESO renders only its bcrypt hash for user `admin`. Never print or
commit the password. `OnChange` refresh uses the ExternalSecret revision
annotation; change the Deployment config revision too when rolling out a new
credential or configuration. Startup validates schema 34 and the single bcrypt
user, resolves the fixed private DNS Service, then atomically writes mode-0600
configuration into a memory-backed emptyDir. UI edits are transient: Git plus
the protected SSM credential are the authoritative recovery sources.

The remote-reference conversion, decoding and metadata defaults are explicit so
External Secrets admission does not leave the Application OutOfSync.

The retained 1Gi `nfs-default` claim stores replaceable filter/work cache. Recreate
keeps one writer; Argo prune/delete protection preserves the claim. Failed filter
refreshes must preserve usable cache. Recovery and DNS rollback acceptance are
required before switching client DNS; never delete the claim or credential to
undo a DNS change.

Local synthetic checks (no production credentials or DNS policy changes):

```sh
nix develop --command python3 -I scripts/ci/adguard-test.py
nix develop --command python3 -I scripts/ci/adguard-runtime-test.py
nix develop --command python3 -I scripts/ci/adguard-check-test.py
```

The runtime test needs the catalog-pinned upstream image in local Docker. It
creates isolated temporary fixture containers with loopback-published ports,
synthetic DNS/filter servers and synthetic credentials, then removes them. It
does not prove Harbor publication, Tailscale reachability, or client DNS adoption.

The direct acceptance helper requires the deployed private HTTPS route, the
owner Mac connected to the expected tailnet, and a clean checkout of verified
current `main`. Supply
the observed Service address and an owner-only mode-0600 file containing the
protected admin credential; never put that value on the command line:

```sh
python3 -I scripts/adguard-check.py --server <observed-tailnet-ip> --password-file <private-file>
```

The helper matches the Mac's current peer to the exact Service-owned ready
proxy. Stable device ID, numeric NodeID, node key, hostname, tag and addresses
must agree; the peer must be online and present in the network map. Missing or
malformed observations, wrong ownership, expired peers and identity changes
fail acceptance. Read-only status checks are repeated around identity collection.

It reads live resources and the authenticated filter API, verifies an enabled
list actually blocks the selected test name, checks ten blocked/permitted A
queries per transport plus AAAA/NXDOMAIN and the private-name inventory, then
rechecks source/configuration/endpoint identity. Each DNS query has one attempt
and a hard three-second subprocess deadline. It performs no Kubernetes writes or
DNS policy changes. HTTPS administration checks validate the certificate,
authenticate the expected admin, require disabled history/statistics, and verify
that anonymous protected reads and an intentionally invalid configuration-write
request are rejected. The invalid value cannot alter a setting even if
authentication is missing. Authenticated first-run setup must also be unavailable.
The helper refuses redirects and environment proxies for these credential-bearing
requests. This direct result does not claim normal-client acceptance.

Use the UI to inspect settings. Persistent configuration changes belong in the
ExternalSecret template and deployment revision marker, delivered through GitOps;
UI edits are reset on replacement. Credential rotation follows the existing SSM
custody path and the two revision markers, never a public issue or command argument.

The staged DNS cutover helper uses the existing administrator-owned
`operator/tailscale-access` unit and its encrypted saved plans. It has no CI
administrator credential. The cutover source selects the observed `100.79.255.15` address; merging it does
not apply the administrator unit. After it reaches reviewed current `main`,
create a fresh saved plan using the
[provider runbook](../../../../IaC/terragrunt-catalog/modules/tailscale-access/README.md).
Keep the plan and receipt outside the checkout, in an owned mode-0700 directory,
with mode-0600 files. Preview from the project shell with its temporary parser:

```sh
nix develop --command nix shell --inputs-from . --no-update-lock-file --no-write-lock-file nixpkgs#hcl2json --command \
  python3 -I scripts/adguard-dns-cutover.py --mode cutover \
  --plan <private-saved-plan> --receipt <private-receipt.json> \
  --server <observed-tailnet-ip> --password-file <private-admin-file>
```

Adding `--execute` repeats all checks before applying that exact saved plan. The
helper compares the complete live policy with the source baseline pinned before
this deployment, verifies that only global DNS/override change, reruns direct
DNS/admin acceptance, and rechecks current main, configuration, Service/peer,
plan digest and live policy. It enforces a 300-second validation window and
60-second final interval, retaining native provider state locks and encryption.
The source baseline is explicit in the helper; unrelated DNS drift is rejected.

The private receipt records the prior/desired policies and the attempted plan
before any apply. A lost response never triggers an automatic retry: preview
inspects live policy; execution can record that inspection. If the desired policy
is already active, no write is repeated. If the prior policy remains, a newly
generated plan after inspection is required. Unrelated or unreadable policy
remains uncertain. Keep the receipt for rollback/recovery; it is not a substitute
for fresh checks.

For deliberate rollback, merge source restoring the exact captured prior DNS
policy, then generate a new saved plan in the same administrator unit. Use the
original protected cutover receipt:

```sh
nix develop --command nix shell --inputs-from . --no-update-lock-file --no-write-lock-file nixpkgs#hcl2json --command \
  python3 -I scripts/adguard-dns-cutover.py --mode rollback \
  --plan <private-rollback-plan> --receipt <original-private-receipt.json>
```

Preview is read-only; `--execute` repeats the rollback checks and applies the exact
restoration plan. This mode does not require the AdGuard address, password, peer,
DNS, filter or UI health. It verifies current reviewed source, the recorded
activation's ancestor source, the full live policy and the prior policy before
applying. Missing receipt, unrelated drift or unreviewed private-DNS changes fail.
The same timing bounds and uncertain-write inspection rules apply. If prior DNS
is already restored, it reports a no-op and the plan may be omitted. The cutover
record is retained and rollback evidence is added separately inside it; storage,
Secrets and the AdGuard peer are untouched. Administrator control-plane access
is still necessary; this does not repair an unavailable private DNS resolver.

After cutover, use `scripts/adguard-check.py --mode client` with the same
`--server` and `--password-file`, plus a new `--receipt` path in a private0700
directory outside the checkout. Run in the temporary parser shell above. This
adapter supports the owner Mac: it checks Tailscale DNS acceptance,
`scutil` resolver presence and full live DNS policy, then uses native
`socket.getaddrinfo` for ten blocked/permitted samples, private names and MagicDNS.
It clears macOS caches before samples using `dscacheutil` and a HUP to
`mDNSResponder`; root or existing noninteractive sudo permission is necessary.
No browser-specific encrypted-DNS bypass is tested.

The private client receipt records OS/daemon version, cache method, device and
exit-node mode. Missing/unsupported client evidence fails; direct-server receipts
cannot count as client proof. Automatic exit-node selection is currently
unsupported. A manually selected existing exit node requires client1.88.1+ and
matching online identity. Without a selected exit node, its behavior remains
explicitly unverified: repeat the same client command after selecting an existing
authorized exit node. This helper does not select or create one. Other operating
systems remain unverified rather than borrowing a successful cloud fixture result.

## Client setup and blocking limits

After global DNS activation, the client must be connected to this tailnet and
accept its DNS settings (the Tailscale client option commonly called **Use
Tailscale DNS settings**). A browser or application using its own Secure DNS,
DNS-over-HTTPS or DNS-over-TLS resolver can bypass AdGuard. To use this service,
configure that application to use the system resolver; do not assume a passing
system-DNS check also tested every browser. Hard-coded addresses and other VPNs
can also take traffic outside this DNS path. This deployment does not enforce or
intercept application DNS.

DNS filtering blocks names, not individual requests or page elements. It can
block a listed advertising domain, but cannot distinguish an ad from wanted
content served from the same domain. Blocking that shared domain can break the
site, and permitting it can leave ads visible. Unlisted advertising domains,
embedded first-party ads and cosmetic page elements may remain. This is not a
promise to remove every ad or tracker, including video ads.

Cached DNS answers and existing connections can temporarily preserve the previous
behavior after activation or a filter change. Allow cached answers to expire or
clear the affected operating-system and application caches, then reconnect and
repeat acceptance. The macOS checker clears system caches for its samples; it
does not establish browser-cache or application-specific DNS acceptance.

There is one filtering resolver and no automatic unfiltered fallback. After
activation, its outage can prevent new public-name lookups until service is
restored or the guarded DNS rollback runs. Cached connections may continue;
existing private split-DNS and MagicDNS settings remain separate. Keep an
independent administrator control-plane access path for recovery. The macOS and
selected-exit-node evidence limits described above still apply.

## Isolated recovery verification

Git owns the initialized configuration; `/homelab/adguard/admin-password` in
AWS SSM owns the administrator credential. Preserve administrator access to
AWS and encrypted IaC state independently of tailnet DNS. The retained work PVC
contains replaceable filter cache, not an authoritative settings backup. UI
configuration edits are replaced by the Git template on pod replacement.

From a clean verified main checkout, with the pinned Harbor image already in
local Docker, run:

```sh
python3 -I scripts/adguard-recovery.py --receipt /private/operator/adguard-recovery.json
```

Use a new receipt in an owned mode-0700 directory outside the repository.
The helper checks the AWS account, reads the exact SSM parameter privately,
and reconstructs the template three times. Disposable containers test initial
startup, replacement after a local configuration change, and restore with an
empty work directory. It verifies administrator authentication, disabled history,
filter membership, and blocked/permitted DNS over UDP and TCP. Containers bind
only loopback, use scratch directories, and never mount production storage.
Only credential ARN/version metadata enters the mode-0600 receipt.

The operator needs working control-plane DNS independently of a failed AdGuard
instance, local Docker, AWS access, and the project development tools. Preload
the reviewed image before an outage; the helper never implicitly pulls an image.
A fresh restore also needs access to the published filter list. Production has
no unfiltered fallback. During an outage, use the DNS rollback command above
through the existing administrator path before repairing service.

Recovery accepts the direct Kubernetes endpoint `https://10.1.0.199:6443` or the
declared authenticated operator proxy
`https://homelab-tailscale-operator.tail67beb.ts.net`. TLS verification must remain
enabled for the selected endpoint. The helper records and rechecks that endpoint;
it does not create a Kubernetes identity or grant access. The direct/client
acceptance helpers require the owner Mac connected to the expected tailnet.

The receipt proves isolated configuration, authentication, and filtering recovery.
It preserves the private resolver address but does not prove connectivity from
Docker to the cluster-private resolver, production PVC recovery, or normal client
DNS. Run the live direct and client checks separately. Synthetic CI recovery
results do not establish that a live protected-source recovery has passed.

Successful source tests do not establish live DNS, administration, recovery or
normal-client acceptance.
