# Unlocked identity implementation: T048–T049

Scope completed: AdGuard-only pure identity validation and read-only collection,
plus synthetic fixtures. Applied `.agents/skills/speckit-implement/SKILL.md` in
this bounded implementation turn. Preconditions: clean separate amendment
analysis; requirements 16/16, deployment-quality 24/24 and unlocked-tailnet 12/12
checklist items complete. Setup resolved the existing feature; existing Python
and secret/state ignore patterns verified. Extensions declare `hooks: {}`; no
before/after hooks were applicable.

## Changes

- `scripts/adguard-check.py`: `validate_local_mode` requires explicit boolean
  mode, expected tailnet and Running/Online/non-expired local observation.
  `validate_unlocked_peer` validates fixed Service ownership and ready Pod,
  matching proxy Self/local Peer identity, stable/numeric IDs, nonzero public key,
  map-key binding, network-map membership, name/tag and tailnet addresses.
  Optional disabled Lock NodeKey must match the corresponding status key.
- `inspect_adguard_peer` reads only the fixed AdGuard Service/managed proxy and
  existing local Mac binary through the bounded sanitized wrapper, rereads the
  Service and local mode, and emits explicit unlocked unsigned evidence.
  Enabled mode delegates to the unchanged shared strict signer/target helpers,
  requires signed=true and appends lock_enabled=true.
- `scripts/ci/adguard-check-test.py`: 11 new tests with negative subcases cover
  required fields, malformed/disagreeing/changing modes, identity and ownership,
  offline/expired state, peer uniqueness/map binding, zero key, optional key
  consistency, command shape, Service changes and strict locked delegation.

## Validation

1. Before implementation, `python3 -I scripts/ci/adguard-check-test.py PeerIdentity`
   failed as expected: 11 tests, 93 errors/subcases for the missing functions.
2. First implementation run exposed fixture aliasing (one reused lock object
   represented several observations); independent copies corrected the synthetic
   observations. No production/API query occurred.
3. `python3 -I scripts/ci/adguard-check-test.py PeerIdentity`: 11 tests pass.
4. `nix develop --command python3 -I scripts/ci/adguard-check-test.py`: 23 tests
   pass, including existing rendered-source snapshot checks. One project Nix
   invocation; no additional package installation was needed.
5. `python3 -I scripts/ci/tailscale-ingress-sign-test.py`: 30 tests pass. Printed
   argparse denials and signature messages are expected mocked fixture output,
   not live signing evidence.
6. `git diff --check`: pass.

Marked only T048 and T049 complete. Shared signer and its tests are unchanged;
no credentials, runtime manifests, DNS policy, PR or commit changed. The new
collector is deliberately not wired into snapshot acceptance yet. T050–T051
must add direct/cutover mode-drift fixtures and integrate mode-aware snapshots in
the next distinct implementation turn. Current direct acceptance still follows
its existing locked-only path until that integration is complete.

Stop: no implementation beyond T049, no live operations or acceptance claim.
Owner: coordinator for the next scoped turn. No background runner remains.
