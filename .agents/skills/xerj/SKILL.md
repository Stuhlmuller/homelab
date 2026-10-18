---
name: xerj
description: Search an existing XERJ node for indexed code, reference corpora, documents, or structured data. Use when the user requests XERJ or an indexed corpus is relevant; do not invoke for ordinary exact-file searches.
---

# XERJ

Use the configured `mcp__xerj` tools when available. Read the tool schema at call time; use the installed CLI only when MCP cannot perform the requested operation. Do not install XERJ, start a node, download a corpus, or index files unless the task calls for it. An index may lag the working tree, so verify any code you change against the current source.

For this repository's pinned corpora, index prefixes, and refresh workflow, read [XERJ reference coding](../../../docs/xerj-reference-coding.md).

## Choose the query

- For code in an autoindexed tree, call `xerj_search` with a plain-string `query`; this ranks definitions and returns passages with file and line. For a known symbol, use the CLI's `xerj def` if available. Use `rg` for exact text, file discovery, and checks against the live checkout.
- For reference coding, use `xerj_code_search` on a named local corpus, or `xerj_hub_ask` / `xerj_hub_def` for a pinned hub pack. Inspect the cited source before adapting an approach. A no-match is not evidence that no implementation exists. Respect each hit's licence warning; treat restricted-licence source as approach-only.
- For structured data, call `xerj_map` to get actual index names, fields, and
  types. Use `xerj_plan` for a natural-language filter when it fits, then send
  its validated query to `xerj_search`; otherwise use query DSL against mapped
  fields. Use `xerj_semantic_search`, `xerj_hybrid_search`, or
  `xerj_vector_search` only when lexical search does not fit the question and
  the index supports the needed field.
- Use `xerj_brain_*` for an existing second brain and `xerj_memory_*` only when the task concerns links or durable memory. Store or retire facts only with task authorization and source evidence.

Keep results bounded with `size`, `k`, or `max_tokens`; cite source paths and
lines when reporting findings. If a reference corpus is stale, refresh it
through its declared workflow rather than silently overriding the freshness
check. Do not request `rerank` on local or sensitive material without user
agreement: it sends returned document text to an external provider. Default
XERJ embeddings are lexical, so do not describe semantic results as neural
unless that mode is confirmed.

For installation, indexing, and version-specific details, consult the [XERJ agent guide](https://xerj.org/llms.txt), [repository](https://github.com/xerj-org/xerj), and local `xerj --help`.
