# Research: Homelab Actions Cost Control

## Decisions

### Keep required PR contexts

**Decision**: Retain PR events for the workflows producing `Lint`, `repo`, `analyze-actions`, `release-dry-run`, and `Terragrunt Gate`, plus the separate `Analyze (python)` and `policy-bot: main` producers.  
**Rationale**: `Stuhlmuller/github-iac/Stuhlmuller/repositories/terragrunt.hcl` lists all seven as strict required checks in ruleset `14700233`; removing an event without changing that rule leaves PR merges pending.  
**Alternative considered**: Disable every PR run. Rejected because it conflicts with protected merge behavior and loses premerge security checks.

### Limit optional events

**Decision**: Treat NOFX Images, OpenClaw native config, and Image automation PR events as candidates for removal. Keep matching main push events. Image automation's five-minute schedule is the largest obvious recurring cost; disabling it also disables the `observe` alert. Keep the weekly CodeQL schedule until its security value is weighed against the small weekly cost.  
**Rationale**: These optional contexts do not appear in the required-check list.  
**Alternative considered**: Change required ruleset contexts. Rejected because unnecessary for this narrow cost reduction.

### Change the declared environment owner

**Decision**: Remove only `homelab-plan` required reviewers in github-iac desired state after verifying module behavior.  
**Rationale**: `Stuhlmuller/github-iac/Stuhlmuller/repositories/terragrunt.hcl` declares user ID `57728706` for the plan environment. Homelab workflow merely references the environment.  
**Alternative considered**: Delete `environment:` from the job. Rejected because it would break environment credentials and OIDC trust.

The module's `dynamic "reviewers"` block is emitted only when the `reviewers` value is non-null. Omitting the key from the `homelab-plan` object therefore omits the required-reviewer block in declared configuration; the exact provider plan must still confirm the live change.

### Reuse headless diagnostics

**Decision**: Preserve `.github/workflows/homelab-diagnostics.yml` as the existing read-only, exact-main-SHA diagnostic lane.  
**Rationale**: Its dispatch verifies the SHA, uses the protected environment, checks Grafana readiness through Octelium, and withholds private logs. It does not offer a broad cluster inventory.

## Evidence gap

Live GitHub settings were not read in this checkout: `gh auth status` reports invalid `GH_TOKEN`, and anonymous `api.github.com` requests failed at the proxy with HTTP 403. The declared HCL and dated runbook establish intended settings. Re-read the actual ruleset and environment with an authorized settings-capable connection before changing the environment.
