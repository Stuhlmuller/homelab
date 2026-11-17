# T018–T019 normal-client acceptance source

Prior separate rollback convergence confirmed independent eligibility/no AdGuard
health dependency and no additional findings or writes. Transcribed here.

Added macOS normal-client adapter using existing trusted Mac/Tailscale paths,
status/preferences, daemon version and scutil resolver evidence. Requires the
intended tailnet, online client and CorpDNS acceptance. Records actual device,
OS/version, exit-node selection and cache method; rejects unsupported OS,
missing preferences, mismatched/offline selected exit or version<1.88.1.
Automatic exit-node selection is explicitly unsupported. No selected exit means
exit-node coverage remains unverified, even when normal-client samples pass.
No exit-node configuration/deployment is performed.

Client mode freshly runs direct/admin checks and reads actual full DNS policy
against current source. Native socket.getaddrinfo (isolated child,3s deadline)
then checks10 blocked/permitted pairs, private-name inventory and known client
MagicDNS identity. dscacheutil flush plus mDNSResponder HUP precedes each pair
and private/MagicDNS query; requires root or existing noninteractive sudo access.
Rereads client mode/policy/source/endpoint before producing client evidence.
Separate system_sample_count_per_name and mode/client-acceptance/cache metadata
prevent direct receipts from counting as normal-client acceptance. CLI can create
new private receipts outside the repository; no overwrite of old evidence.

Shared DNSReader/source-policy functions extracted from cutover without changing
its provider/credential guards; reader caches its scoped token within an invocation.
Updated actual CLI in feature quickstart and app README, including temporary
hcl2json shell, credential/receipt flags, cache permissions and unverified cases.

Red fixtures first showed missing adapters/evidence validator and then missing
exit-node preference rejection. Full12 checker tests and21 cutover tests passed;
final four focused client tests rerun after adding explicit system sample count
and strict missing/automatic exit-mode handling, all pass. Targeted3-file secret
scan0findings; git diff --check passes. Logs adguard-client-red.log,
adguard-client-receipt-red.log, adguard-client-mode-red.log,
adguard-client-verified.log and adguard-client-mode-final.log. An attempted README
patch matched no line and made no change; actual documentation was appended afterward.

Upstream v1.102.4 CLI version.go and ipn/prefs.go inspected. Prefs ExitNodeID/IP
are explicit fields (not omitted), AutoExitNode has distinct semantics; source
copies in /workspace/adguard-progress/upstream. Existing macOS carrier already
uses the same native cache flush operations. No actual Mac/client acceptance was
run in this Linux workspace. T039 remains pending; fixtures do not satisfy it.

T018/T019 source complete. Next separate scoped client convergence, then T020
provider expectations andT027/T028 isolated recovery. All live rollout/delivery
stillpending. Publisher43777917412 solewatcher80837 stillcopying/verifying at last
observation. No live AdGuard/signing/DNS changes or Notion writes. Hooks empty.
