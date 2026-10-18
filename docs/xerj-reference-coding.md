# XERJ Reference Coding

XERJ runs on the operator workstation. Its clones and indices live under
`~/.xerj-code/`; it does not change the cluster. Install the checksum-verified
binary using the [XERJ install guide](https://xerj.org/docs/install), then start
an authenticated, loopback-only node in a terminal:

```sh
~/.local/bin/xerj --data-dir ~/.xerj-code/data
```

Codex connects through [`.codex/config.toml`](../.codex/config.toml). The MCP
server reads the local key file at startup; no credential belongs in git. The
node must be running when Codex searches.

## Reference sources

The manifests in [`scripts/config/xerj-corpora/`](../scripts/config/xerj-corpora/)
pin the source revisions. `homelab-peer` is a Talos, Terragrunt, and Argo CD
homelab; `argo-cd`, `talos`, and `terragrunt` are the upstream implementations.
Import and index one corpus at a time:

```sh
~/.local/bin/xerj corpus add --from scripts/config/xerj-corpora/argo-cd.json
cp scripts/config/xerj-corpora/argo-cd.xerjignore \
  ~/.xerj-code/corpora/argo-cd/.xerjignore
XERJ_API_KEY="$(cat ~/.xerj-code/data/admin.key)" ~/.local/bin/xerj corpus index argo-cd
XERJ_API_KEY="$(cat ~/.xerj-code/data/admin.key)" \
  ~/.local/bin/xerj code argo-cd "How are sync waves ordered and health checked?"
```

Repeat for `talos`, `terragrunt`, and `homelab-peer`, copying each matching
`.xerjignore` before indexing. The peer needs no ignore file. `corpus add`
clones the manifest's pinned commit. The pinned peer `LICENSE` is Unlicense,
although XERJ v1.0.0-rc.96 reports `UNKNOWN`; its manifest records the review.
Talos is `MPL-2.0`. Check licence terms before reusing code.

The Argo CD ignore file leaves 1,435 implementation files in the index. Its
bulk documentation, UI, manifests, tests, and resource customization
fixtures stay in the pinned clone. XERJ rc.96 times out verifying the full
repository's largest dataset, and two resource customization fixtures also
trigger an annotation-sort bug. If an earlier index failed, rerun
`corpus index argo-cd --fresh` after copying the ignore file. The Talos and
Terragrunt ignore files similarly keep their runtime source
searchable without the bulk test fixtures, UI, and documentation.

Before writing nontrivial code with an upstream or peer analogue, run
`xerj code <corpus> "<problem>"`, read the returned source at its cited line,
then adapt the relevant approach. A miss means search the clone or official
documentation before deciding no example exists. XERJ's default search is
lexical, so use terms that appear in the source.

## This checkout

Index the working tree separately from reference corpora. The `--no-graph`
generation reconciles later changes within its existing dataset schema. XERJ
skips hidden paths during a root walk. Index the visible tree first:

```sh
XERJ_API_KEY="$(cat ~/.xerj-code/data/admin.key)" \
  ~/.local/bin/xerj autoindex . --prefix homelab-local-v2 \
  --state-dir ~/.xerj-code/autoindex-state/homelab-local-v2 \
  --no-graph --workers 4 \
  --stub 'clusters/homelab/apps/octelium-enterprise/resources.yaml'
```

XERJ v1.0.0-rc.96 fails catalog finalization when it sorts the Octelium YAML
annotation `metadata_annotations_octelium.com/last-upgrade`. The `--stub` flag
keeps that path in the root index as a name card. Make searchable text cards
for that YAML and tracked hidden paths. Indexing hidden directories directly
would bypass the parent `.gitignore` and could include private Talos files.
The cards include only files tracked by this public repository:

```sh
python3 scripts/xerj-tracked-source-cards.py
XERJ_API_KEY="$(cat ~/.xerj-code/data/admin.key)" \
  ~/.local/bin/xerj autoindex ~/.xerj-code/local-source \
  --prefix homelab-tracked-source \
  --state-dir ~/.xerj-code/autoindex-state/homelab-tracked-source \
  --no-graph
```

Refresh these indices after source changes. If XERJ refuses a new dataset
schema, build and verify a new prefix and state directory before retiring the
old one. Search the checkout with
`XERJ_API_KEY="$(cat ~/.xerj-code/data/admin.key)" ~/.local/bin/xerj search --prefix homelab "<problem>"`;
use the cited repository path as the source of truth. The same credential prefix
on `~/.local/bin/xerj corpus list` shows which reference corpora are loaded.
XERJ treats autoindex exit `3` as success with skipped junk; an exit `1` or `4`
needs attention. `corpus index` can return `0` while reporting an inner
autoindex exit `1`; check its coverage message before using that corpus.
