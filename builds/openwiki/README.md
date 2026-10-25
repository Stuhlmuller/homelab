# OpenWiki MCP package

The project MCP server runs the upstream OpenWiki 0.7.0 npm release through
`nix run .#openwiki`. `package-lock.json` pins the exact dependency graph; its
OpenWiki package integrity matches `skills-lock.json`. The Nix package installs
that release and patches one upstream setup call: `openwiki_begin(mode=update)`
does not rewrite an existing `AGENTS.md` managed block or create a scheduled
workflow. `mode=init` still uses upstream setup, including its workflow. This
repository uses update because it preserves the migrated wiki.

The patch preserves this repository's on-demand OpenWiki policy while
[upstream issue #742](https://github.com/langchain-ai/openwiki/issues/742)
remains unresolved. Keep the package version, lockfile, Nix dependency hash,
integration receipt, and MCP command aligned when upgrading. After an upgrade,
recheck whether the patch is still needed.

Verify the package and setup behavior with:

```sh
nix build .#checks.$(nix eval --raw --impure --expr builtins.currentSystem).openwiki-setup
```

The check exercises native upstream setup with and without workflow creation.
To roll back this integration, restore the prior `.codex/config.toml` npm
command and remove the local Nix package. Wiki pages and Claims are unaffected.
