# Octelium and Cordium capability research — 2026-09-05

Scope: official current documentation, pinned upstream source, and repository
configuration. This note does not claim live activation. See
[[audit-2026-09-04]], [[continuous-improvement]], and
[[../architecture/secrets-and-identity]].

## Product and version boundaries

The products are **Octelium** and **Cordium**. The repository's console is
`https://console.stinkyboi.com`; developer access is
`https://cordium.stinkyboi.com`, with applications below
`*.cordium.stinkyboi.com`. These names are checked by
`scripts/octelium-e2e-check.sh`.

Repository pins are Octelium Core **0.35.0**
(`scripts/octelium-cluster-bootstrap.sh`), Enterprise **0.22.0**
(`scripts/octelium-enterprise-package.sh`), and Cordium **0.12.7**
(`clusters/homelab/apps/cordium/README.md`). Upstream Cordium's latest release
was **0.14.0**, published August 29. Current `/latest/` documentation is a
capability reference, not proof every field works on the deployed versions.
[Official Cordium release](https://github.com/octelium/cordium/releases/tag/v0.14.0).

## Supported capabilities and useful homelab applications

| Capability | Finding and application |
| --- | --- |
| Access security | Octelium fronts browser applications, APIs, Kubernetes, databases, SSH, and other resources with identity and request policies. Continue expressing homelab access as native Services and policies. It can also front LLM and MCP endpoints. [Overview](https://octelium.com/docs/octelium/latest/overview/intro). |
| Developer environments | Cordium provides browser terminals, CLI, SSH, and reproducible workspaces from images, repositories, Dockerfiles, or devcontainers. Reuse the repository toolchain and one workspace definition. [Cordium overview](https://octelium.com/docs/cordium/latest/overview/intro). |
| CI execution | Official CI examples run build/test lifecycle tasks in a workspace, with failure-abort behavior and resource limits. They do **not** document GitHub runner registration or a native Actions autoscaler. A GitHub job invoking Cordium can execute the actual checks remotely; this remains a hosted orchestrator with a Cordium execution target. [CI example](https://octelium.com/docs/cordium/latest/examples/cicd). |
| Agent execution | Workspaces obtain dedicated Octelium session identities; infrastructure access can be correlated with their owner and workspace context. OpenClaw can use the same CLI or API. No official OpenClaw-specific adapter was established by this research. [AI agents](https://octelium.com/docs/cordium/latest/overview/ai-agents). |
| Programmatic control | Cordium exposes gRPC and Go, TypeScript/JavaScript, and Python clients. Prefer its existing CLI for a small homelab integration. [APIs and SDKs](https://octelium.com/docs/cordium/latest/use/api). |
| Security visibility | Octelium emits L7 access logs and component telemetry over OTLP. Keep Prometheus/Grafana for node, workload, capacity, and backup monitoring; Octelium access visibility does not establish those checks. [Visibility](https://octelium.com/docs/octelium/latest/management/core/visibility). |

Enterprise advertises console queries, authentication events, resource-change
audit records, SSH replay, metrics, and OTLP exports. It also offers JIT access,
SCIM/directory sync, KMS integration, and DNS/TLS automation. Prioritize the
already-installed console/logging path and existing identity integration;
additional directories and regions have no demonstrated homelab need. Device
posture integration is marked **Soon**, so do not treat it as available.
[Enterprise capabilities](https://octelium.com/enterprise).

## Concrete execution path

Cordium **0.12.7 source** confirms `create workspace` supports `--file`,
`--start`, `--ephemeral`, `--checkout`, and `--out json`.
`exec` supports `--no-stdin`, `--workdir`, and propagates the remote command's
nonzero exit status. Creation alone is not evidence tests passed; wait for the
workspace to run, execute checks, preserve status, then perform bounded cleanup.
[Pinned creation source](https://github.com/octelium/cordium/blob/v0.12.7/client/cordium/commands/create/workspace/cmd.go),
[pinned exec source](https://github.com/octelium/cordium/blob/v0.12.7/client/cordium/commands/exec/cmd.go).

The execution command shape is:

```sh
cordium exec WORKSPACE --domain stinkyboi.com --no-stdin \
  --workdir /workspace/repo -- COMMAND ARGUMENTS
```

Use a committed workspace spec for image, resource bounds, and setup. Current
documentation supports `spec.repository.cloneOptions.checkout` for an exact
commit, `spec.runtime.tasks` with `type: ON_CREATE` and
`onFailure: ON_FAILURE_ABORT`, and `.cordium/workspace.yaml` repository config.
Validate the selected schema against the pinned server before adoption.
[Workspace configuration](https://octelium.com/docs/cordium/latest/use/config).

Interactive sessions use `cordium run --file PATH --domain stinkyboi.com`.
`--rm` deletes the workspace after terminal exit. SSH and file-copy commands
require an Octelium client connection; they are not a substitute for repairing
the public route. [CLI](https://octelium.com/docs/cordium/latest/use/cli).

The new optional `cordium-check.yml` workflow uses a GitHub-hosted orchestrator
and remote Cordium execution; see [the CI runbook](../../cordium-ci.md). Live
acceptance remains pending. OpenClaw's values and ExternalSecret contain no
Cordium integration.
The existing `homelab-cordium-agent` credential serves ClusterConfig bootstrap:
do not hand that management credential to builds or OpenClaw. Declare separate
least-privileged execution identities and their repository-owned secret or
assertion contracts. GitHub OIDC is supported through an
`oidcIdentityToken` provider with issuer
`https://token.actions.githubusercontent.com`; restrict accepted repository,
workflow/ref, audience, and permissions before exposing it to CI.
[Workload identity providers](https://octelium.com/docs/octelium/latest/management/core/identity-providers).

## Console audit acceptance

The required OTLP receiver address is
`octelium-collector.octelium.svc:8080`.
`clusters/homelab/apps/octelium-enterprise/resources.yaml` already declares that
Service, the Enterprise collector, logstore, metricstore, and console proxies.
Do not add a second collector merely because the console is empty.
[Receiver contract](https://octelium.com/docs/octelium/latest/management/core/visibility).

Trace the existing pipeline: service-proxy emission → collector endpoints and
export → logstore ingestion → Enterprise query API → authorized console view.
Prove a uniquely identifiable allowed/denied request appears with timestamp,
identity, Service, and decision. Separately verify an authentication event and
a repository-owned resource-change audit event. Access logs and resource-change
audit logs are different evidence. Check retention and durable storage; healthy
pods and a login page alone prove neither ingestion nor query results.
[Console logging capabilities](https://octelium.com/enterprise).

## Gates before claiming completion

- Repair the known public Octelium gRPC and Cordium nested-wildcard TLS paths;
  they currently block the intended external control and developer experience.
- Reconcile NOFX's native catalog drift through the declared apply path.
- Run a GitHub workflow whose remote workspace checks demonstrably pass, then
  verify a deliberate failing check fails the GitHub job and cleanup occurs.
- Demonstrate a human development session and an OpenClaw-owned execution
  session, including denied access outside their declared policies.
- Confirm matching console telemetry for those sessions, with persistent
  queryable events rather than only collector stdout.
- Bound concurrency and memory. The homelab's Cordium pods are privileged
  outer containers on `zimaboard-1`, with disposable local workspace storage;
  rootless inner containers do not erase that host trust boundary. Do not run
  arbitrary fork-PR code with privileged homelab credentials. Source:
  `clusters/homelab/apps/cordium/README.md` and
  [[../architecture/storage-and-state]].

Validation: read-only source and documentation review; pinned CLI source
inspection. Local CLI help was also checked, but that binary identifies as an
untagged development commit, so it does not prove release compatibility. No
live resources or credentials changed, and no runtime acceptance is claimed.

## Live follow-up evidence

On September 5, the existing Enterprise collector, logstore, metricstore, and
Cordium controller Deployments were Ready. A temporary read-only port-forward
to collector metrics showed 10,686 accepted and exported log records, zero
refused records, and an empty log queue. This proves transport to logstore,
not retention, query correctness, or visibility in the console. The diagnostic
forward was stopped after inspection.

The browser sign-in flow reproduced a console redirect to the unresolvable
`console.octelium.stinkyboi.com` hostname. A browser-user-agent curl GET
reproduces HTTP 303 with a login `redirect` query pointing to that nested name.
The old curl HEAD check returned 401 and missed the browser behavior. The
end-to-end script now probes the console with a browser user agent and checks
its login return destination.

Core 0.35.0 builds this redirect from the canonical managed Service hostname
unless `status.managedService.forwardHost` is true and a valid forwarded host
is present. Read-only native-resource projection found that flag absent on
`console.octelium`; do not mutate generated status to repair it. Neither Enterprise 0.22.0 nor current 0.29.0 exposes a supported alias setting.
The repository now declares a narrow Envoy response filter for this exact
unauthorized console login redirect, preserving path/query and authentication.
Runtime rollout and authenticated console query validation remain pending.
Sources: [EE 0.22.0 genesis](https://github.com/octelium/octelium-ee/blob/v0.22.0/cluster/genesis/genesis/cmd_init.go#L237),
[EE 0.29.0 genesis](https://github.com/octelium/octelium-ee/blob/v0.29.0/cluster/genesis/genesis/cmd_init.go#L230).
Source: `cluster/vigil/vigil/modes/httpg/middlewares/auth/denied.go` at
[Core v0.35.0](https://github.com/octelium/octelium/blob/v0.35.0/cluster/vigil/vigil/modes/httpg/middlewares/auth/denied.go).
