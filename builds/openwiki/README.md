# OpenWiki MCP package

The project MCP server runs the reviewed `main` Nix app through
`nix run github:Stuhlmuller/homelab#openwiki`. `package-lock.json` pins the
exact upstream OpenWiki 0.7.0 dependency graph; its
OpenWiki package integrity matches `skills-lock.json`. The Nix package installs
that release and patches two upstream update paths. `openwiki_begin(mode=update)`
preserves this repository's `AGENTS.md` policy and does not create a scheduled
workflow. It also routes Markdown/verified-Claim hash mismatches into mandatory
native page jobs instead of failing while fast-forwarding page coverage. The
old Claim hash stays unchanged until that page is reviewed and submitted.
`mode=init` still uses upstream setup, including its workflow.

The `main` reference prevents an unreviewed checkout from supplying executable
MCP code at startup. For local package tests, use `nix run .#openwiki`.

The patch preserves this repository's on-demand OpenWiki policy while
[upstream issue #742](https://github.com/langchain-ai/openwiki/issues/742)
remains unresolved. Keep the package version, lockfile, Nix dependency hash,
integration receipt, and MCP command aligned when upgrading. After an upgrade,
recheck whether the patch is still needed.

Verify the package and setup behavior with:

```sh
nix build .#checks.$(nix eval --raw --impure --expr builtins.currentSystem).openwiki-setup
```

The check exercises native upstream setup with and without workflow creation,
then proves a wiki-only Markdown edit requires a page job without advancing
unverified Claim coverage.
To roll back this integration, restore the prior `.codex/config.toml` npm
command and remove the local Nix package. Wiki pages and Claims are unaffected.
