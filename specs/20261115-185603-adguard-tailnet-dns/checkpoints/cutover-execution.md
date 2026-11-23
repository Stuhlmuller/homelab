# T016–T017 cutover implementation

Prior separate T042 convergence confirmed exact/nonempty binding keys with no
new findings or writes. This transcribes that pass. Completed the cutover helper
and tests after the partial pure-guard increment; T016/T017 now complete in source.

CLI defaults to preview, uses fixed administrator unit/native encrypted saved-plan
show/apply, existing private OAuth custody and scoped DNS API reads. No workload
CI administrator scopes. Current source and pinned prior source48e8b9e4 are parsed
with temporary hcl2json; actual baseline parsing verified the two Cloudflare
globals, overridefalse, MagicDNStrue and retained split/exit-node policy. The
baseline must be an ancestor of reviewed clean signed current main. The actual
observed AdGuard IP enters source only atT037, not now.

Fresh plan inspection validates only one fully-known DNS update with matching
before/after/current source, no unrelated actions/output/drift/replacement.
Fresh DNS/admin acceptance then binds current/deployed/config source, exact
Service UID/IP and peer, saved-plan bytes and full live/desired policies.
Final reads must agree within300s full check and60s final interval; clocks and
future evidence fail closed. Native locks/encryption are retained. A local
advisory lock serializes receipt users. Owned regular0600 files in owned0700
external directories protect plan/receipt data. Plan hash is checked around
show and immediately before native apply. No raw plan/credential output.

Before apply an atomic private receipt records policies/plan/source/evidence.
Any apply failure is inspected against actual policy; no automatic retry.
Applied outcomes are verified, uncertain outcomes remain pending, confirmed
unchanged policy requires a different plan generated after inspection. Repeated
execute on an observed applied receipt writes no tailnet policy. Timeout handling
terminates the entire subprocess group before reporting uncertainty. Rollback
is intentionally not implemented untilT025/T026, still pending.

Red fixture evidence precedes engine/adapters. All14 cutover tests pass, including
all binding drift surfaces, temporal guards, exact transition, malformed/unrelated
plans, filesystem/last-moment hash checks, preview no writes, lost response,
unreadable outcome and inspected-new-plan recovery. Actual pinned prior source
parsed through hcl2json stdin successfully. Targeted2-file secret scan0findings;
git diff --check passes. Logs adguard-cutover-engine-red.log,
adguard-cutover-adapters-red.log, adguard-cutover-final.log and
adguard-cutover-engine-final.log under /workspace/adguard-progress.
Registered tests in offline suite, documented exact temporary-Nix CLI and recovery
semantics in app README. Flake/lock unchanged.

No real saved plan/apply/API DNS writes or live acceptance attempted. Source is
unmerged. Publisher43777917412 still copying/verifying, sole watcher80837. Next
separate scoped convergence onT016/T017, then rollbackT025/T026 and remaining
client/recovery source. No Notion updates; hooks empty.
