# Application source delivery review

T031 draft preparation follows the separately completed read-only scheduling
analysis: source review/draft CI may overlap publication; ready/merge still require
T003. Source covers FR001-018 through workload, credential/route, targeted apply,
fixed trusted signer, direct/client checks, guarded cutover/rollback and isolated
recovery. Runtime proof remains pending. No global DNS values change in this PR.

Task-lifecycle bounded reviews: workload/credentials/routes and helper/evidence/
rollback/recovery reviewers independently reviewed source. One P2 found implicit
NodePort allocation. T045 adds allocateLoadBalancerNodePorts:false with a red/green
manifest assertion. Follow-up reviews found no remaining actionable P0/P1/P2.

Main advanced to ec53ed3d3b9b2397bf41abfd8935561e8e5d5b67 including Kuma PR1850
and scoped publisher PR1851. The preserved feature stash is
daf4b1978dfa3a49620d51294f68a60515ed8f16. Twelve overlapping paths were resolved
preserving both apps' TLS routes/names, credentials, policies and targeted apply
prerequisites. Separate reviewers verified those combined paths. T046 adds exact
AdGuard Deployment readiness coverage to Kuma's exhaustive catalog; no claim of
DNS filtering follows from that monitor. Existing sources/predicates stay intact.

Validation after integration:11 manifest/init tests,41 targeted apply tests,
12 route tests,private DNS declarations,62-app/55-monitor catalog,36 catalog
regression tests,448 manifest policies,offline static,OpenWiki,secret scan and
whitespace checks passed. NodePort assertion failed before its fix. The catalog
fixture's synthetic-retirement expected count was corrected after its first run.
Earlier runtime/helper/signing tests remain applicable to their unchanged source;
full required CI will check this exact integrated commit. Local logs are outside
Git in /workspace/adguard-progress/adguard-kuma-*.

Prerequisite PR1851 merged through protections at signed ec53ed3d with sole parent
1dfeb92a3654bae7a927c8adf4ed454347820dd7. All seven required checks passed; policy
bot was confirmed required/successful through GraphQL. The optional Harbor audit
repeated its recorded baseline validation:remediation failure; no bypass was used.
Scoped publication run44049807119 is in progress, not a success receipt.

Draft exit conditions: final publication receipt, including T047 toolchain
prerequisite (the app's bind.dnsutils flake addition changes the defined publication
bundle); exact-head required CI, protected review and activation prerequisites.
T047 must move the toolchain addition ahead of the final publication dispatch;
current in-progress run alone cannot close that final bundle gate. After source
merge, targeted Terragrunt dispatch, valid operator OAuth, trusted peer signing,
live DNS/admin/recovery and actual-client acceptance remain. Existing stored
operator OAuth returned401; no CI rotation path or administrator authority has
been established. No app deployment, credential repair or DNS cutover claimed.


## Draft CI repair and toolchain prerequisite

[Draft PR1852](https://github.com/Stuhlmuller/homelab/pull/1852) opened at signed
9476d8873af39bb30a43bedfefb0e461ad9e5aac. Separate T045/T046 convergence was clean.
[Toolchain PR1853](https://github.com/Stuhlmuller/homelab/pull/1853) stages the
identical one-line DNS utility addition plus ordering documentation; its lock
file is unchanged. `dig -v` reports 9.20.22, x86_64-linux flake evaluation without
build passed, and OpenWiki/whitespace passed. Required CI and merge remain pending.

The app lint job found 33 E701/E702 compound-line violations in four Python
files, plus Markdown URL/line-length errors in feature records. Expanded only
the reported Python statements and proved identical parsed syntax trees before
and after; no executable behavior changed. Ruff passes with the repository's
CI config. Markdown passes for all 47 feature files with the same CI rules.
Initial local Markdown invocation used default rules, then an unsupported config
filename; the final invocation used an external CLI2 wrapper containing the
unchanged repository rules and passed. No exemptions or rule changes were made.
