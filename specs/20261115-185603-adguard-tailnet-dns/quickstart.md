# Validation and rollout guide

Source helpers are implemented incrementally; live rollout remains unverified.
Run from the repository root. Preserve protected main, existing credentials and
private receipt handling. Stop dependent actions when a gate fails.

## Source and fixture checks

```sh
kubectl kustomize clusters/homelab/apps/adguard >/tmp/adguard-rendered.yaml
python3 -I scripts/ci/adguard-test.py
python3 -I scripts/ci/adguard-runtime-test.py
python3 -I scripts/ci/adguard-dns-cutover-test.py
python3 -I scripts/ci/traefik-routes-test.py
python3 -I scripts/ci/tailnet-dns-test.py
python3 -I scripts/ci/terragrunt-apply-test.py
python3 -I scripts/ci/openwiki-check.py
git diff --check
```

Use repository Nix tooling and relevant validation-runbook commands for HCL,
rendering, generated registration, image coverage, secret policy and signer
fixtures. Runtime fixture uses the pinned image, exact security context and
synthetic credentials. Prove startup/authentication, both DNS transports,
private failure isolation, failed filter refresh retention, privacy settings,
replacement and isolated restore. Never connect fixture writers to production.

## Delivery prerequisites

Merge/publish the image inventory prerequisite first; retain exact publisher
run and full-pull receipts. Then merge consuming app source. On the targeted
apply path require namespace/AppProject/ESO/NFS and upstream applications ready;
resolve Traefik's observed Progressing status before declaring this gate passed.
Dispatch existing terragrunt-apply workflow at exact main with argocd_app=adguard
once its new targeted path is tested and delivered.

```sh
kubectl --request-timeout=10s -n automation get deployment adguard
kubectl --request-timeout=10s -n automation get externalsecret adguard-config
kubectl --request-timeout=10s -n automation get pvc adguard-work
kubectl --request-timeout=10s -n automation get service adguard-dns
python3 scripts/verify-gitops.py --application adguard --expected-sha <deployed-sha> --deployment automation/adguard
```

Do not print Secret data. On the existing trusted Mac, preview and execute the
fixed AdGuard signing target using reviewed main. Verify online signed identity
and Service address, then run direct checks and private UI authentication:

```sh
python3 -I scripts/tailscale-ingress-sign.py --adguard-only
python3 -I scripts/tailscale-ingress-sign.py --adguard-only --execute
python3 -I scripts/adguard-check.py --server <observed-adguard-tailnet-ip> --password-file <private-admin-file> --receipt <new-private-direct-receipt>
```

Capture protected configuration recovery source versions and restore an isolated
instance; repeat effective settings/authentication/blocking checks. The live
Service address is discovered here, not invented during planning.

## DNS cutover and user acceptance

Only after the direct receipt passes, commit the observed global nameserver IP,
exit-node use and DNS override, preserving existing private routing/MagicDNS.
Merge through protected delivery. From the existing administrator environment,
generate an encrypted saved plan using the tailscale-access runbook and validate
it through the new cutover helper before execution. Do not grant workload CI
administration rights. Inspect the actual plan for drift and unrelated changes.

```sh
python3 -I scripts/adguard-dns-cutover.py --mode cutover --plan <private-saved-plan> --receipt <private-cutover-receipt> --server <observed-ip> --password-file <private-admin-file>
python3 -I scripts/adguard-dns-cutover.py --mode cutover --plan <private-saved-plan> --receipt <private-cutover-receipt> --server <observed-ip> --password-file <private-admin-file> --execute
```

Execution reruns the required direct acceptance, bounded to 300 seconds, then
requires apply within 60 seconds of completion. It rechecks source/config/endpoint,
live policy and plan digest immediately before mutation. Old receipts or a plan
file timestamp cannot replace this sequence. Regenerate/revalidate on any drift.

Read back actual tailnet DNS. On at least one authorized client accepting DNS,
record OS and Tailscale version, cache treatment and exit-node mode. Run 10 fresh
blocked/permitted system-resolver checks, private inventory and MagicDNS checks.
Repeat with an existing authorized exit node (client >=1.88.1) when available;
otherwise report that coverage as unverified. Recheck deployed revision.

The implemented client adapter uses the existing trusted Mac, native
`socket.getaddrinfo`, `scutil --dns`, live Tailscale status/preferences and daemon
version. It requires Tailscale DNS acceptance and verifies the active full policy
against source. It flushes macOS DNS caches before each sample pair and each
private/MagicDNS query; this needs root or existing noninteractive `sudo` access
for `dscacheutil` and `killall -HUP mDNSResponder`. Missing access, unsupported OS,
missing exit-node status or an unsupported selected-exit client fails acceptance.
It does not select or deploy an exit node. No selected exit node means that
coverage is explicitly unverified, even if normal-client samples pass.

Use the project's temporary parser shell for source-policy reads. The receipt
must be a new file outside the repository in an existing private0700 directory:

```sh
nix develop --command nix shell --inputs-from . --no-update-lock-file --no-write-lock-file nixpkgs#hcl2json --command \
  python3 -I scripts/adguard-check.py --mode client --server <observed-ip> \
  --password-file <private-admin-file> --receipt <new-private-client-receipt>
```

This performs fresh direct/admin checks first, then normal OS resolver samples,
and rereads client mode, full DNS policy and source/endpoint. Direct receipts
cannot satisfy client acceptance. The same temporary shell supplies `hcl2json`
for both cutover and rollback examples above/below; it does not change the flake.

## Recovery

A failed pre-cutover check leaves current DNS unchanged. For post-cutover DNS
failure, use reviewed rollback source restoring the captured prior globals and
override through the explicit rollback mode:

```sh
python3 -I scripts/adguard-dns-cutover.py --mode rollback --plan <private-rollback-plan> --receipt <original-private-cutover-receipt>
python3 -I scripts/adguard-dns-cutover.py --mode rollback --plan <private-rollback-plan> --receipt <original-private-cutover-receipt> --execute
```

This mode validates current-main restoration source, captured prior policy,
recorded activated policy, fresh live policy and exact DNS-only plan digest.
It must work when AdGuard and its peer are unavailable; no AdGuard DNS/UI or
filter-health prerequisite applies. The same timing bounds and unrelated-drift
protections remain. A previously completed restoration is a no-op. Missing
administrator connectivity or an unknown prior policy is still a real blocker.
Confirm policy readback, then assess public/private/MagicDNS client resolution
separately. Keep volumes and secrets. Recover app settings
from pinned Git plus protected credential custody; verify restored behavior.
