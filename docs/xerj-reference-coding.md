# XERJ Reference Coding

XERJ runs on the operator workstation. Its clones and indices live under
`~/.xerj-code/`; it does not change the cluster. The flake pins the
checksum-verified XERJ release. It can fetch the same pinned archive through
the public GitHub release asset API when the browser download endpoint fails.
Enter `nix develop .#xerj`, then start an authenticated,
loopback-only node in a terminal:

```sh
xerj --data-dir ~/.xerj-code/data
```

[XERJ v1.0.0-rc.104](https://github.com/xerj-org/xerj/blob/v1.0.0-rc.104/engine/crates/xerj-common/src/localauth.rs#L20-L44)
publishes a pointer to the local admin key for each loopback port. Check for
`using the admin key at` in the `autoindex` startup output. If indexing
returns 401, check the node URL and its pointer under `~/.xerj/by-port/`.

Codex runs the flake package from this repository's `main` branch through
[`.codex/config.toml`](../.codex/config.toml).
The absolute Nix executable path lets desktop MCP hosts start it without a shell `PATH`.
The packaged MCP command keeps node startup under operator control. Start
the node before running a search in Codex. The MCP server reads its
credential from the local key file.

## Reference sources

The manifests in [`scripts/config/xerj-corpora/`](../scripts/config/xerj-corpora/)
pin the source revisions. `homelab-peer` is a Talos, Terragrunt, and Argo CD
homelab; `argo-cd`, `talos`, and `terragrunt` are the upstream implementations.
Import and index one corpus at a time:

```sh
xerj corpus add --from scripts/config/xerj-corpora/argo-cd.json
cp scripts/config/xerj-corpora/argo-cd.xerjignore \
  ~/.xerj-code/corpora/argo-cd/.xerjignore
xerj corpus index argo-cd
xerj code argo-cd "How are sync waves ordered and health checked?"
```

Repeat for `talos`, `terragrunt`, and `homelab-peer`, copying each matching
`.xerjignore` before indexing. The peer needs no ignore file. `corpus add`
clones the manifest's pinned commit. The pinned peer `LICENSE` is Unlicense,
although XERJ v1.0.0-rc.96 reports `UNKNOWN`; its manifest records the review.
Talos is `MPL-2.0`. Check licence terms before reusing code.

The Argo CD ignore file leaves 1,435 implementation files in the index. Its
bulk documentation, UI, manifests, tests, and resource customization
fixtures stay in the pinned clone. During initial setup, XERJ rc.96 timed
out verifying the full repository's largest dataset. If an earlier index
failed, rerun `corpus index argo-cd --fresh` after copying the ignore file. The Talos and
Terragrunt ignore files similarly keep their runtime source
searchable without the bulk test fixtures, UI, and documentation.

Before writing nontrivial code with an upstream or peer analogue, run
`xerj code <corpus> "<problem>"`, read the returned source at its cited line,
then adapt the relevant approach. A miss means search the clone or official
documentation before deciding no example exists. XERJ's default search is
lexical, so use terms that appear in the source.
If `xerj code` reports a corpus older than 30 days, run
`xerj corpus index <corpus> --fresh` before searching again. The manifest keeps
the cloned source at its pinned revision.

## This checkout

Index the working tree separately from reference corpora. The `--no-graph`
generation reconciles later changes within its existing dataset schema. XERJ
skips hidden paths during a root walk. Index the visible tree first:

```sh
xerj autoindex . --prefix homelab-local-v4 \
  --state-dir ~/.xerj-code/autoindex-state/homelab-local-v4 \
  --no-graph --workers 4 --no-default-stubs
```

The `--no-default-stubs` flag keeps lockfile contents searchable. XERJ rc.104
resolves the dotted Octelium annotation during structured indexing
and catalog finalization. Start with the new prefix and state directory
above because a reconciliation of the old generation can keep the previous
name-card dataset for unchanged YAML. Keep the old generation until a search
against the new index returns the Octelium entries.
[Upstream fix](https://github.com/xerj-org/xerj/pull/3035)

Make searchable text cards from Git-tracked hidden files. Indexing hidden
directories directly would bypass the parent `.gitignore` and could include
private Talos files. Use a fresh prefix and state directory for the cards
after the script removes the legacy Octelium card:

```sh
python3 scripts/xerj-tracked-source-cards.py
xerj autoindex ~/.xerj-code/local-source \
  --prefix homelab-tracked-source-v2 \
  --state-dir ~/.xerj-code/autoindex-state/homelab-tracked-source-v2 \
  --no-graph
```

Refresh these indices after source changes. If XERJ refuses a new dataset
schema, build and verify a new prefix and state directory before retiring the
old one. Search the checkout through Codex's `xerj_search` MCP tool with
`index: homelab-local-v4-*` and `query: "<problem>"` for definition-first
ranking. Use `index: homelab-tracked-source-v2-*` for hidden-file cards. Read the
cited repository path as the source of truth. `xerj corpus list` shows
which reference corpora are loaded.
XERJ treats autoindex exit `3` as success with skipped junk; an exit `1` or `4`
needs attention. `corpus index` can return `0` while reporting an inner
autoindex exit `1`; check its coverage message before using that corpus.
