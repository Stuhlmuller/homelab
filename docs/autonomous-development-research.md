# Autonomous development research and decisions

Research snapshot: 2026-11-01. Improve existing delivery work with scoped task
records and revision-bound verification. Retain existing owners; add no runner,
subscription, dependency, or copied scripts. Runtime continuation remains
unverified until an actual post-session wakeup completes authorized work.

## Baseline

The repository already separates [Terragrunt registration and Argo delivery](../openwiki/architecture/gitops-flow.md),
uses [Nix](../flake.nix), and provides [specialist skills](../openwiki/operations/agent-workflows.md).
The [apply workflow](../.github/workflows/terragrunt-apply.yml) checks exact current
`main`, serializes production applies, and uses a protected environment.
These are source-confirmed controls, not proof of successful live execution.

[PR #1795](https://github.com/Stuhlmuller/homelab/pull/1795) addresses delivery
ownership through protected merge. [PR #1796](https://github.com/Stuhlmuller/homelab/pull/1796)
adds dependency ordering and durable ownership across worktrees. Both were open
at inspection; #1796 explicitly limits coordination to one Git common directory
and leaves heartbeat activation until merge. Reuse that work and its owner.
Independent hosts must not mistake a local claim for a distributed lease.

Existing [issue #815](https://github.com/Stuhlmuller/homelab/issues/815) tracks
applying reviewed plan artifacts; [issue #889](https://github.com/Stuhlmuller/homelab/issues/889)
tracks runtime dependency health. Their historical details need current source
verification before repair; open issues alone do not prove every finding remains.
The [Enterprise candidate](../clusters/homelab/apps/openclaw-enterprise/README.md)
has explicit activation/recovery gates. Preserve those gates and deferred work.

## Research evidence

- [OpenAI harness engineering](https://openai.com/index/harness-engineering/)
  reports an internal application experiment. Useful mechanisms: a short
  instruction map, repository knowledge, isolated worktrees, and observable
  behavior. Its throughput and merge-risk choices are not infrastructure targets.
- [Anthropic long-running harnesses](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)
  documents compaction and premature-completion failures. Adapt durable progress,
  incremental work, and functional checks; do not import its application runner.
- [Anthropic evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)
  separates transcripts from actual outcomes and discusses repeated trials.
  Our inference: interruption, duplicates, stale evidence, and failed rollout
  should be executable acceptance cases, not confidence scores.
- [Agent Skills specification](https://agentskills.io/specification) defines
  frontmatter and progressive disclosure. Host support varies; experimental
  `allowed-tools` metadata must not substitute for CI permissions or RBAC.
- [Handbook Core Pillars](https://www.agentic-dev.org/handbook/framework/core-pillars)
  proposes scoped workbenches, explicit specs, and gated routing. This is design
  guidance, not independent reliability evidence. The requested handbook landing
  page was inaccessible; this official chapter was readable. Its microVM and
  organizational model would add unnecessary machinery for this increment.
- [Activeloop](https://www.activeloop.ai/resources/scaling-agents-20-prs-a-day/)
  exposed its title, author/date, and contents only; the requested
  [LinkedIn article](https://www.linkedin.com/pulse/how-i-scaled-agents-safely-merge-20-prs-day-sasun-hambardzumyan-5ur7c?tl=en)
  failed to load. Treat them as one apparent syndicated account, not independent
  studies. “20 PRs/day” is an unverified author claim; no decision relies on it.

## Candidate decisions

<!-- markdownlint-disable MD013 -->

| Candidate | Decision and fit | Cost / maintenance | Failure mode / proof required |
| --- | --- | --- | --- |
| Existing #1795/#1796 delivery work | **Adapt**; preserve owner and continuation mechanism | Existing infrastructure | Disabled runner, stale claim, lost event; prove post-session recovery |
| Scoped issue and lifecycle skill | **Adopt**; required issue-form fields, durable evidence and next action | Small documentation surface | Fields do not validate truth or grant authority; verify evidence at each stage |
| Existing skills and OpenWiki | **Adapt**; link focused runbooks | Existing checks; no new store | Stale instructions; source and live evidence remain authoritative |
| GitHub concurrency and IaC locks | **Adapt**; reuse existing write lanes | No new lock service | Pending events replaced; claims across hosts need explicit coordination |
| Exact revision and functional verification | **Adopt**; deterministic checks plus service-specific probe | Small verifier and fixtures | Healthy wrong revision or broken user path; reject uncertainty |
| Spec Kit upgrade / additional hooks | **Defer**; keep existing planning workflow | Migration and extension testing | New upstream APIs cannot be assumed installed |
| Multica as universal runner | **Defer**; retain integration owner | Existing service, added qualification work | Shutdown/handoff reports require canaries |
| Enterprise activation | **Defer**; preserve staged gates | Identity, storage, recovery burden | Activation without recovery or credentials proof |
| New framework, memory database, paid API | **Reject this increment**; no demonstrated need | New cost and operations | More credentials and failure surfaces |
| LLM-only review / success grading | **Reject**; use as supplementary review | Additional tokens | Shared blind spots; executable acceptance is decisive |

<!-- markdownlint-enable MD013 -->

[GitHub concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
defaults can replace pending runs. Keep durable work records and reconcile
current state after events. Serialization must cover all writers; retain
[OpenTofu state locking](https://opentofu.org/docs/language/state/locking/).

## Upstream activity and documented failures

[Spec Kit v1.2.5](https://github.com/github/spec-kit/releases/tag/v1.2.5)
(October 28) includes workflow/extension changes;
[issue #5199](https://github.com/github/spec-kit/issues/5199) reports hidden Git
credential prompts stalling automation. This supports bounded execution, not
an inference that the installed version has that defect.

[Multica v0.7.2](https://github.com/multica-ai/multica/releases/tag/v0.7.2)
(October 30) includes targeted retries. Open reports
[#9773](https://github.com/multica-ai/multica/issues/9773),
[#9772](https://github.com/multica-ai/multica/issues/9772), and
[#9720](https://github.com/multica-ai/multica/issues/9720) describe shutdown,
idle-handler, and delegation stalls. They were read, not reproduced locally.

[Argo CD releases](https://github.com/argoproj/argo-cd/releases) show maintained
release branches. Open [#28701](https://github.com/argoproj/argo-cd/issues/28701)
reports full sync inheriting a selective filter while reporting success. Inspect
operation details and actual resources; its manual workaround is not authorized.

## Ranked follow-up and pilot measures

1. Finish #1795/#1796 and prove interruption recovery with their existing owner.
   Highest expected intervention reduction; low additional maintenance.
2. Close the reviewed-plan requirement in #815 through its existing workstream.
   Highest apply-integrity value; moderate artifact/state-validation effort.
3. Complete dependency-health acceptance in #889. High reliability value;
   moderate bounded-wait and failure-fixture effort.
4. Qualify recovery and existing runners before broader unattended execution.
   High impact, higher maintenance; preserve explicit activation gates.

These rankings are engineering judgment, not measured savings. Worktrees isolate
files, not shared resources or data. Git reversal is not data recovery; require
applicable backup/restore evidence and a recovery record outside the worker
cluster. [Argo sync semantics](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
support bounded retries; Synced alone does not establish functional success.

Measure interventions after initial authorization, unattended completions,
stalled handoffs, recovery passes/attempts, runner duration, and model usage.
Unknown cost stays unknown. A successful pilot proves its tested path, not a
general completion rate.
