# T023–T024 private administration and privacy acceptance

Prior separate scoped route convergence inspected T021/T022 exact route/backend,
private annotation/view, TLS wildcard and existing Funnel boundary. No new
findings or source writes; five constitution principles remain satisfied for
source preparation. This transcribes that result in the following implementation.

Added initialized-auth/history runtime fixture and live private-admin checks.
The helper uses normal verified HTTPS, fixed origin, private file credential,
no environment proxies and no redirects. Requires expected authenticated admin,
disabled query log/statistics, anonymous protected GET and invalid POST denied
401/403, and authenticated first-run setup unavailable403/404. The POST uses an
invalid boolean type, so it cannot mutate settings even with broken auth; a400
response therefore fails the authentication gate. No successful live config write.
No live history data is fetched; runtime-only synthetic fixture additionally
checks empty query history, zero statistics and absent on-disk querylog files.

A new admin-validator fixture first failed before implementation. All8 checker
tests and6 pinned-image runtime tests now pass. Last runtime rerun includes zero
statistics assertion;3-file Checkov secret scan reports0 findings. git diff
--check passes. Logs /workspace/adguard-progress/adguard-admin-red.log,
adguard-admin-final.log and adguard-admin-runtime-final.log. Pinned API behavior
was inspected directly with synthetic local runtime: querylog config omits the
file_enabled field, which remains explicitlyfalse in source; authenticated
setup rejection and disabled counters are runtime-tested.

README explains HTTPS/auth checks, invalid unauthenticated request, private
credential custody and GitOps-authoritative persistent changes. Direct internal
receipt now has admin_acceptance=true only after the added checks; it still
explicitly has client_acceptance=false. T023/T024 complete at source/fixture
level, no live acceptance. AllUS3 source complete. Next separate convergence on
this increment, thenUS2/US4 source and integration. T003 publisher43777917412 still
copying/verifying under sole watcher80837. No AdGuard deployment/signing/DNS
mutation or Notion updates. Hooks empty.
