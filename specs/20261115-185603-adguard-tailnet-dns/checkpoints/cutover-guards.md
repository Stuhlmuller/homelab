# US2 cutover guards increment — T016/T017 partial

Prior separate T041 convergence confirmed the corrected sources/revisions binding,
project/destination and negative fixture coverage, with no new findings or writes.
This transcribes it in the next implementation pass. US2 work has now started.

Added scripts/adguard-dns-cutover.py pure validation functions and five behavioral
fixture tests. Red evidence first showed absent implementation; all5 now pass.
Guards canonicalize the full known DNS policy and reject missing/unknown fields,
unknown values, unrelated resource/output/drift changes, deletion/replacement,
changed singleton ID or inconsistent planned values. Cutover preserves all split
DNS/MagicDNS/search paths while selecting exactly the observed tailnet resolver
with local override and exit-node use. Timing checks enforce300s full validation,
60s final interval, no negative/nonfinite/backwards clocks, invalid persisted
timestamps and changed source/config/Service/peer/plan/live-policy bindings.

IMPORTANT: T016/T017 remain unchecked. Execution/live-state/source/receipt adapters
and uncertain-write behavioral fixtures are NOT implemented. CLI deliberately
fails with no mutation available. Do not merge or claim cutover readiness.
No offline integration entry yet until the complete helper contract is built.
Logs /workspace/adguard-progress/adguard-cutover-red.log and
adguard-cutover-guards.log. git diff --check passes. Next separate scoped
convergence on pure guards, then finishT016/T017 adapters/negative fixtures;
rollbackT025/T026 follows their dependencies. No live changes or Notion.

Research coverage: read complete pinned provider resource_dns_configuration.go
v0.29.2; DNS provider schema uses five policy fields plus computedid and
use_with_exit_node defaultsfalse. Go dependency tailscale clientv2.9.0 resolves to
<https://github.com/tailscale/tailscale-client-go-v2> at4f50555a6c6f6f231f85b4f54767ac49bf590416.
Read its DNSConfiguration structs and Configuration/SetConfiguration functions:
GET /tailnet/-/dns/configuration returns nameservers, splitDNS, searchPaths,
preferences with camelCase booleans. Existing guarded OAuth api_request supports
read-only token/API calls without environment proxies or redirects. Admin OAuth
custody and encrypted terragrunt saved-plan runbook already read. No credential
values read. Source references saved under /workspace/adguard-progress/upstream/.

Temporary parser provisioning: hcl2json missing from project devShell, supplied
through nested nix shell --inputs-from . nixpkgs#hcl2json with lock writes/updates
disabled. Verified project nixpkgs29916453413845e54a65b8a1cf996842300cd299,
Nix2.20.6; packagehcl2json0.6.9 (binary version reports devel). Successfully parsed
actual module main.tf to /workspace/adguard-progress/tailscale-source.json. HCL
JSON resource.homelab is a one-element list; nameserver use_with_exit_node is
absent when defaultfalse, so source adapter must fill that specific provider
default without accepting unknown plan values. Flake/lock unchanged. Helpers can
require hcl2json on PATH with the documented temporary shell for operator runs;
no global installation or permanent dependency change needed.

Publisher43777917412 remains owned by watcher80837. Last observed copy/verify
step pending. No T003 completion claim.
