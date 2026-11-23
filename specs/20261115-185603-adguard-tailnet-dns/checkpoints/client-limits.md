# T044 client-facing limits

The preceding separate integration convergence reviewed FR016/018/019/SC006,
three integration plan decisions and five constitution principles. One MEDIUM
partial gap remained: the operational runbook named untested browser DNS but did
not explain practical domain-based limits or application bypass prerequisites.
It appended T044 only; spec/plan and previous task entries were preserved.

Added client setup and blocking limits to the AdGuard README, linked from the
owning ingress wiki. It explains tailnet DNS acceptance; application DoH/DoT,
hard-coded address and alternate VPN bypasses; same-domain ad/content tradeoffs;
cache/connection effects; and one-resolver public-query outage behavior with no
unfiltered fallback. Preserves private split-DNS/MagicDNS separation and existing
macOS/exit-node evidence limits. Does not promise all ads/tracking are removed.
No runtime, DNS, resource, credential, test or dependency changes.

OpenWiki links/navigation/frontmatter/entrypoints and git diff --check passed.
No new tests needed for these explanatory paragraphs. Prior full local validation
remains applicable to unchanged implementation. T044 complete; next separate
scoped convergence on this documentation correction. Hooks remain empty.

No live deployment or DNS change. AWS managed OIDC exchange and authenticated
Harbor publication remain blocked. The encrypted diagnostic is preserved outside
Git; the configured GPG home/private-key directory is absent. Requested OIDC
repair/reconnection and the existing administrator machine/private GPG home for
the recorded encryption recipient, explicitly no pasted/uploaded keys. Answers
pending. No repeated AWS or publisher action attempted. User's OIDC preference
and no-Notion instruction remain in force.
