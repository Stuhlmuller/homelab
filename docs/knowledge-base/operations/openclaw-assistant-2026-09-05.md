# OpenClaw assistant rollout, September 5

## Desired state

[PR 963](https://github.com/Stuhlmuller/homelab/pull/963) configures Astra via
the existing Codex harness, managed workspace instructions, an owner Discord
briefing, daytime health checks, and bounded daily improvements. Argo observed
merged revision `2c089558100fd09de969cda78bf3633cde6fe0b1` and created its
replacement Pod. PR 964 subsequently bounded doctor runtime and replaced that
Pod during bootstrap; verification follows the replacement. Both migration
markers survived. Runtime acceptance remains open until verified below.

The live scheduler inventory contained five enabled jobs. Reconciliation
replaces Grafana auto-triage and the older daily improvement loop while
preserving their history and unrelated security, memory, and research jobs.
Exact retired identities are in the app's `assistant/retired-jobs.json`.

## Startup performance finding

- **Evidence:** The prerequisite workspace-migration Pod spent about nine
  minutes building/copying the operator toolbox and about twenty minutes in
  bootstrap. Between 14:25 and 14:29 UTC, consecutive configuration commands
  took roughly twenty seconds each and emitted `slow SQLite transaction hold`.
  Doctor completed the remaining state migration and verified preserved session
  identities at 14:39 UTC.
- **Evidence:** The gateway reported ready at 14:41 UTC, but the Pod remained
  unready and emitted `slow SQLite transaction lock wait` and delayed liveness
  diagnostics before the assistant rollout replaced it. A gateway-ready log
  alone is not proof of HTTP readiness or responsive Discord operation.
- **Impact:** Repeated Pod replacement incurs substantial downtime. The
  retained state is QNAP-backed; the exact cause of transaction contention is
  not yet established. Do not attribute it solely to NAS latency from these
  logs.
- **Next steps:** Measure the proxy `/` response, CPU throttling, active
  automation workload, and shared SQLite transaction contention after startup.
  Profile or batch configuration writes through reviewed bootstrap code. Keep
  verified backups and session-preservation gates; do not interrupt migration
  or patch live state to obtain a green readiness signal.

## Acceptance evidence

Confirmed before rollout: pinned OpenClaw config validation, installer and
scheduler regression tests, full static checks, exact Helm/Kustomize renders,
300 rendered Kubernetes policy assertions, lint, secret scanning, and required
GitHub checks passed.

A read-only inspection of all 19 current session metadata rows found no
explicit model or provider overrides, so no session-route migration is needed.

The replacement Pod completed bootstrap at 15:18 UTC without a restart. Its
persistent default is `openai/gpt-6-astra` with an empty fallback list; managed
workspace installation and pinned-runtime config validation passed. Discord's
plugin was enabled. Gateway readiness and model execution remain separate checks.

At 15:21 UTC the gateway returned HTTP 200 and reconciliation recorded `ready`.
The Pod reached 2/2 Running with zero restarts. Public automation inventory
confirmed all three Astra declarations with Pacific schedules and Discord
delivery, and both overlapping legacy jobs disabled.

An actual gateway-backed Astra turn failed with `Unknown model` from the Codex
runtime. Configured model presence is insufficient: its catalog entry reports
`available: false`. The bundled Codex is `0.151.0`; OpenAI added Astra support
in `0.153.1`. The follow-up pins `0.153.2` with verified release digests and
selects that binary through the plugin's supported app-server command setting.
Source inspection confirms OpenClaw `2026.9.1` requests hidden models;
`2026.8.2` does not. The follow-up therefore upgrades the gateway and installs
the exact matching official Codex plugin, retaining the native binary override.
A verified offline `pre-2026.9.1` archive precedes the new runtime commands.
Actual post-upgrade inference still needs testing.

Still required: successful Astra inference, confirmed Discord delivery, and a
successful bounded health check using real homelab tools after the runtime fix.

## Sources

- `clusters/homelab/apps/openclaw/README.md`
- `clusters/homelab/apps/openclaw/assistant/`
- [[workloads/application-notes#OpenClaw]]
- [[architecture/storage-and-state]]
