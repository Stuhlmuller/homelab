# DNS cutover preparation

- Existing goal/issue: #1842; this continues T037, not a new feature.
- PR #1870 merged as `3aaf6085f15facf050d6d6b26991a5efdedb77d1` after all
  required CI passed; all introduced commits and the merge were verified.
- Owner reports direct Mac acceptance exit 0 at
  `a249d5a9f126349004f524087cc508a30697835d`: UDP/TCP filtering, private DNS
  and authenticated administration passed. The diagnostic wrapper printed only
  subprocess names/errors and retained all checks. An earlier timeout/start
  failure did not recur; its cause is unknown.
- Owner reports isolated replacement and fresh configuration/credential restore
  passed using the pinned image with local Podman. Receipt is private mode 0600;
  containers were removed and the VM stopped. Production storage was untouched.
  This is isolated replacement evidence, not a production restart receipt.
- Tailnet Lock remains disabled; identity acceptance requires no signing.
- Source changes only global resolvers to observed `100.79.255.15`, enables
  local override and exit-node use, and preserves MagicDNS/search paths/split DNS.
- Merge does not apply the administrator-owned unit. T038 requires a fresh
  encrypted saved plan and the unchanged guarded helper on current main.
- Global DNS activation, actual rollback execution and normal-client/exit-node
  acceptance remain unverified. T039 and final convergence remain open.
- No credential or private receipt contents are copied into this checkpoint.

## Source validation

- Parsed the actual before/after HCL with `hcl2json`; the unchanged
  `validate_transition` accepts exactly the observed address and preserved fields.
- 23 saved-plan/cutover tests and 26 acceptance checker tests passed.
- OpenTofu formatting, changed Markdown lint, OpenWiki and diff checks passed.
- Independent read-only review found no material findings.
- No live administrator plan has run in cloud; the existing Mac credential
  custody and encrypted backend remain required for activation.
