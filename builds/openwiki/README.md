# OpenWiki MCP package

The project MCP server runs the reviewed `main` Nix app through
`nix run github:Stuhlmuller/homelab#openwiki`. `package-lock.json` pins the
exact upstream OpenWiki 0.7.0 dependency graph; its
OpenWiki package integrity matches `skills-lock.json`. The Nix package installs
that release with reviewed local patches. `openwiki_begin(mode=update)` does not
rewrite an existing `AGENTS.md` managed block or create a scheduled workflow.
`mode=init` still uses upstream setup, including its workflow. Repository updates
also fail closed when a Git changed-path query cannot prove page coverage.

The `main` reference prevents an unreviewed checkout from supplying executable
MCP code at startup. For local package tests, use `nix run .#openwiki`.

The patch preserves this repository's on-demand OpenWiki policy while
[upstream issue #742](https://github.com/langchain-ai/openwiki/issues/742)
remains unresolved. Keep the package version, lockfile, Nix dependency hash,
integration receipt, and MCP command aligned when upgrading. After an upgrade,
recheck whether the patch is still needed.

For a reviewed missing-baseline repair, `openwiki_begin(mode="update")` accepts
`recoverPageBaselines: [{page, gitHead}]` with exact current manifest entries.
Each selected page becomes a mandatory full-review PageJob. Inspect its complete
Claims set and explicitly confirm, update, or retract every existing Claim ID.
The run refuses deletion, skip, source drift, or an unreachable target Git commit;
only a completed page job with new durable provenance can replace its baseline.
Omit this option for ordinary updates. Fetch available historical objects first.
Pages absent from the page manifest or lacking a Git baseline automatically
require the same inspected full-review job. A complete `.last-update.json`
cannot seed missing per-page coverage.

Completed pages also record a content-addressed map of verified, model-visible
source paths and per-path digests. The map covers file bytes, symlink targets,
kind, and executable mode; it excludes OpenWiki and
ignored paths. Git HEAD and status remain separate run-drift checks. Native
updates persist each map once and retain it while any page references it.
Publication requires every visible path to be tracked, present, and byte/mode
equivalent to its committed HEAD blob. Local dirty or untracked source cannot
be published in the page manifest. This repository has no Git content filters;
a checkout that transforms committed bytes fails closed until normalized.
On a fresh `init`, the first begin may install AGENTS/workflow setup and return
`commit and retry`; commit that setup through the normal signed PR path, then
begin again. It creates no wiki run state before that retry.
Comparing maps gives exact changed paths after squash merges, unrelated merges,
or unavailable old commits. Dirty and untracked paths also require successful
Git queries; failed reads or queries never count as unchanged coverage. Older
entries without a map keep their Git-history requirement and can use reviewed
full-page baseline recovery. `.openwikiignore` always counts as source even
when its own rules name it.

Verify the package and setup behavior with:

```sh
nix build .#checks.$(nix eval --raw --impure --expr builtins.currentSystem).openwiki-setup
nix build .#checks.$(nix eval --raw --impure --expr builtins.currentSystem).openwiki-recovery
```

The checks exercise setup and a complete native recovery lifecycle in disposable
Git repositories.
To roll back this integration, restore the prior `.codex/config.toml` npm
command and remove the local Nix package. Wiki pages and Claims are unaffected.
