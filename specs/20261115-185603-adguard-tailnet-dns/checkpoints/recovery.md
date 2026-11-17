# T027–T028 isolated recovery

The preceding separate T020 convergence was clean and made no changes. This
implementation adds scripts/adguard-recovery.py as a sibling because local
Docker recovery needs distinct lifecycle and credential custody from live checks.
Source remains unmerged on feat/adguard-tailnet-dns, base48e8b9e4. No live SSM
credential read, recovery drill, application deployment, signing or DNS mutation.

The helper reconstructs the actual ESO template through private Helm input,
checks declared AWS account and exact SSM SecureString identity/version, and
records metadata only. Clean verified main, authenticated control-plane address,
private resolver Service UID/IP, pinned locally cached image and unchanged source
versions bind the receipt. Local Unix Docker only; random loopback ports; scratch
storage; main nonroot/readonly/capability restrictions; no production mounts.
It tests initial state, replacement after a disposable local configuration change,
and fresh-cache restore. Private routing and client acceptance remain explicitly
false in the isolated result and require separate live gates. Retained PVC cache
is not authoritative settings backup. Three runbooks document source custody,
independent control-plane access, image preloading, rollback and proof limits.

The initial runtime test failed on unsupported DNS port argument and cleanup
ownership. Added bounded optional port support and restored scratch directory
ownership after deleting all files; seed shell now fails on any failed operation.
A second run revealed dig absent from the project shell. Added bind.dnsutils to
flake.nix because the declared runtime CI and operator checker require it, with
no lock change. Final recovery reconstructs source template on each of three
factory invocations and tests the actual pinned upstream image, not Harbor
publication. All7 container tests and12 checker tests pass in
/workspace/adguard-progress/adguard-recovery-final.log. Four offline boundary
tests pass (wrong account before credential read, exact protected parameter and
metadata, remote Docker rejection, invalid ports). They are registered offline.
OpenWiki links and git whitespace checks pass;3-file targeted Gitleaks has zero
findings in adguard-recovery-boundaries.log. No full integration gate claimed.

T027/T028 source complete. Next separate scoped recovery convergence, then
T029 cross-cutting docs andT030 complete integration checks. T003 publisher
43777917412 remains pending copy/verify; solewatcher80837 owns polling. Consuming
merge still waits on actual authenticated publication plus full validation.
T036 must run real protected-source recovery. User declined all Notion writes.
Hooks remain empty. Preserve spec/plan/checklists; no requirement change.
