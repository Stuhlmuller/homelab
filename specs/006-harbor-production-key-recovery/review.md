# Focused local signer review

Base9bf484b63e87068f8abcc510922626cdab30f025; no publication/real signing.
Two read-only review agents followed code-review standards/spec axes. They
inspected source only and performed no commands/tests/private reads/edits.
Root executed the inert tests and repaired findings. Final vote-preservation
restriction was acknowledged from the supplied delta,not independently retested.

## Standards

Initial:P2 future publication task lacked required authored OpenWiki update;
P3 CLI contract compressed option/value tokens. Added explicit uncheckedT010
native authored-page update gate and correctly spaced runnable command. Closed.
No remaining standards blocker identified; extra abstraction not recommended.

## Spec

Initial:P2 fixed125second creation bound began before durable preparation;
a Mac/storage suspension could strand a valid complete outcome. Reproduced
with a failing test. Now persist observed completion in finally; if lost after
a kill,recovery's observation supplies upper bound. Exact current provider key,
Mac,trust delta/metadata/votes,private capture and cache proof remain mandatory.
Suspension and lost-stamp regressions pass. Reviewer closed the finding.

## Validation and residual limits

22 mocked tests pass,including strict scope/pins,safe stdin/output,private
permissions/symlinks,nonzero/timeout/interruption,partial output,delayed netmap,
cache conflicts,post-cache-write interruption,time-bound repair and authority
vote mismatches. Ruff,bash syntax,whitespace and SpecKit prerequisite checks pass.
No P0/P1 or unresolved source/spec finding reported. No broad tests/live CI rerun.

Remote grant may precede any wrapper output. A lost/partial capture cannot be
reconstructed from public authority metadata. Intent stays blocking; no blind
signing retry,automatic deletion or authority retirement. This is an explicit
operational limit requiring separately approved exact recovery,not claimed live
acceptance. A new pre-auth authority persists beyond authkey expiry/secret
removal and carries the existing apply identity's cluster-admin/broaderTCP443.

Standards:2 findings closed;Spec:1 finding closed. No unresolved blocker reported.
