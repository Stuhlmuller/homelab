# T020 provider expectations

Prior separate client convergence reviewed actual native resolver use, explicit
metadata/cache/exit-mode checks and unverified-client handling; no new findings
or writes. This transcribes that result in the next implementation pass.

Added module-local tests/fixtures/adguard-dns-cutover.json with explicit
fixture_only marker, synthetic observed100.99.0.1 and complete prior/desired
policies. Existing cutover/rollback fixtures now consume this shared expectation.
The future policy has one global resolver, override and exit-node use, preserving
full split DNS/MagicDNS/search fields. No fixture address entered active main.tf.
Added mocked provider assertion that active source still matches the prior policy
until actual observed-IP cutoverT037; that future task must update this assertion
with actual reviewed runtime evidence, not the synthetic address.

All21 Python cutover/rollback tests pass with the fixture. An initial multiline
HCL expression lacked parentheses; fmt rejected it before initialization. Fixed
and formatted it, then backend-free init and all6 Tailscale module tests passed.
Native provider locks/cache remain ignored per repo policy, no flake/lock changes.
Logs adguard-provider-expectations.log and adguard-provider-expectations-final.log.
git diff --check passes. No live backend plan/apply or DNS mutation.

T020 source complete. Next separate scoped provider-expectations convergence,
then isolated recoveryT027 and recovery docsT028. Initial recovery consideration:
local isolated runtime can preserve the actual cluster-local private upstream in
config and verify filtering/admin, while private routing is separately verified
by live direct acceptance; never claim a local Docker check proves cluster-local
private routing. Must reconstruct from Git plus protected credential source
versions and retain no production browsing data. No recovery helper written yet.
No live changes or Notion; publisher43777917412 solewatcher80837 still pending
copy/verify at last observation. Hooks empty.
