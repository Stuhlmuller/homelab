# Validation Guide: Homelab Actions Cost Control

1. Read the live `main` ruleset and `homelab-plan` environment with an authorized settings-capable connection. Compare required context names and reviewer rule to the declared `github-iac` HCL. Do not display secret values.
2. Before a GitHub settings apply, inspect the github-iac plan. Confirm the only environment protection change is removal of `homelab-plan` reviewers; `homelab-production`, environment credentials, and ruleset checks remain unchanged.
3. Parse all edited workflows, run the repository static policy and `python3 -I scripts/ci/speckit-check.py`, then run `git diff --check` in both repositories. Use the declared github-iac validation path for its HCL.
4. On a representative PR, verify `policy-bot: main`, `Lint`, `repo`, `Analyze (python)`, `analyze-actions`, `release-dry-run`, and `Terragrunt Gate` are emitted and terminal. For a trusted IaC PR, verify the plan job does not wait for reviewer approval. For a fork PR, verify plan credentials are never injected.
5. On `main`, verify matching push jobs still run. Verify exact-SHA dispatch jobs still enforce their branch and SHA guards. Compare Actions run counts before/after for optional PR events and the five-minute Image automation schedule.
6. If a required context becomes absent or a secret boundary changes, revert the exact workflow or github-iac desired-state commit through its normal protected path.
