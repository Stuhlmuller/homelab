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

Verify the package and setup behavior with:

```sh
nix build .#checks.$(nix eval --raw --impure --expr builtins.currentSystem).openwiki-setup
nix build .#checks.$(nix eval --raw --impure --expr builtins.currentSystem).openwiki-recovery
```

The checks exercise setup and a complete native recovery lifecycle in disposable
Git repositories.
To roll back this integration, restore the prior `.codex/config.toml` npm
command and remove the local Nix package. Wiki pages and Claims are unaffected.
