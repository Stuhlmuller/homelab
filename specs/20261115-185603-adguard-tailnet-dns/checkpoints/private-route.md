# T021–T022 private administration route source

Prior separate convergence on T015 reviewed direct-check code, source/peer/config
binding, enabled membership, query deadline and no false client proof against the
spec/plan and five constitution principles. No new corrective findings and no
files changed. This transcribes that review in the next implementation pass.

US3 source follows completed US1 and is independent of US2 source. Implementing
its private route now makes the direct checker's authenticated API dependency
concrete; US2 cutover remains gated by all source and live checks. No task or
requirement dependency changed.

Added failing AdGuard route/backend/TLS and private-name inventory fixtures, then
implemented the exact websecure-only router and adguard-admin.automation backend
on3000. Added adguard.stinkyboi.com to Traefik's approved annotation and private
resolver view together. No Funnel change, certificate expansion or new Service.
App README documents the staged URL. Existing wildcard covers this first-level
name; live TLS/auth still pending, not inferred from source.

All12 route tests and private DNS declarations/mutation contract pass after
initial missing-route/name failures. Logs /workspace/adguard-progress/
adguard-routes-red.log and adguard-routes-final.log. git diff --check passes.
Full Helm render and integration gate remain T030; actual TLS/auth/privacy
checks remain T023/T024 and liveT036. T021/T022 complete; next separate scoped
convergence, then T023/T024. Publisher43777917412 still copying/verifying under
sole watcher80837; T003 remains pending. No consuming merge or live changes.
No Notion updates. Hooks empty.
