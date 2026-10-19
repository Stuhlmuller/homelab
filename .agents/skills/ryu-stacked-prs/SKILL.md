---
name: ryu-stacked-prs
description: Manage stacked GitHub or GitLab pull requests with Ryu and Jujutsu. Use when creating, updating, or syncing a Ryu stack, including continuing dependent work while a parent PR awaits merge.
---

# Ryu Stacked PRs

Ryu submits PRs; Jujutsu (`jj`) owns the commit graph and bookmarks. Use this skill for a JJ-backed repository. In a Git-only checkout, choose JJ setup deliberately before using Ryu; do not silently change the repository's workflow.

1. Inspect `ryu --version`, the relevant command's `--help`, `jj status`, `jj log`, bookmarks, and existing PR heads and bases. Ryu's CLI is evolving; prefer the installed help over remembered flags. Check the repository's PR and branch-protection rules.
2. Give each reviewable change its own JJ commit and bookmark. For follow-on work waiting on a parent PR merge, base the new change on the parent's bookmark and keep the parent's change out of the child PR diff. Waiting for that merge need not block authorized work on the child.
3. Track the exact bookmarks to submit with `ryu track <bookmark>`. This is Ryu submission tracking, separate from JJ's remote bookmark tracking. Preview with `ryu submit <leaf-bookmark> --dry-run`; verify the proposed PR order, branch bases, and changed files. Submit with `--confirm` when PR creation or updates are authorized. Use `--draft` when the new PR is not ready for review.
4. Prefer a narrow submission: `--only` for one bookmark whose parent already has a PR, or `--update-only` when creating new PRs is out of scope. Avoid `--all` unless every bookmark in the range belongs to the requested stack. Inspect the resulting PRs and confirm each child targets its parent branch, with the bottom PR targeting the intended trunk branch.
5. After a parent merges, fetch the updated trunk and use JJ to rebase the remaining changes onto it, excluding the merged parent from the stack. Inspect the graph, then preview and resubmit the affected bookmarks. Verify child PR bases and diffs again; rebasing or pushing may require fresh CI, signatures, and approvals. Merge each PR only through its repository's normal protected path.

`ryu submit` and `ryu sync` can push bookmarks and create or update PRs. `ryu sync` fetches first and may change local state. Use `ryu sync --confirm` to inspect its post-fetch plan before authorizing remote changes; `--dry-run` skips the fetch and may preview stale state. Ryu does not replace review, validation, or merge requirements.

For command details, see the [Ryu project](https://github.com/dmmulroy/jj-ryu) and the installed `ryu ... --help` output.
