# Catalog evidence

Read-only snapshot 2026-11-17: 55 registered source apps, 56 live Applications,
60-name union; adding Kuma gives 61 classified entries. The catalog validator
checks all current source stack names and optionally accepts kubectl Applications
JSON for current live-name coverage. No live resources were changed.

Kube-state-metrics ServiceMonitor `monitoring/prometheus-kube-state-metrics`
has no endpoint interval override. The generated Prometheus resource
`prometheus-kube-prometheus-prometheus` has scrapeInterval 30s, inherited from
pinned kube-prometheus-stack 85.2.0 in the Prometheus stack. Consequently every
raw KSM input is eligible only up to 60 seconds after its own sample timestamp.
Deluge's committed ServiceMonitor explicitly uses 45s, giving a 90s bound.
Neither query response time nor Kuma's 60s polling interval substitutes for
source observation cadence. Changing the chart cadence requires catalog review.

`argocd/live` is an existing fixture Application, with source
`https://example.invalid/fixture.git`, path `fixture/live`, revision `main`.
It has no workload source in this repository and Unknown/Unknown status.
It is classified retired fixture without deleting or repairing it.

Workload identities come from current live resource tracking annotations and
owning committed stack/manifest sources. Dynamically named workspace and
connector resources are not separate app inventory entries. Cordium covers its
stable controllers; Octelium covers stable controllers and active enterprise
owned Deployments. Enterprise rscstore is currently unready; its monitor must
report down rather than excluding the component. OpenClaw's stopped runtime is
not claimed up: its remaining retirement-reader is explicitly monitored.
Mastodon similarly covers still-active PostgreSQL/Redis, not stopped web workers.
Kiali includes the operator and its managed dashboard Deployment.

Direct endpoints follow committed probes: n8n `/healthz/readiness` (DB-aware),
Bazarr `/api/system/ping`, Arr `/initialize.json`, Langfuse `/api/public/ready`,
Fleet `/healthz`, NOFX backend `/api/health` and frontend `/health`. Exact HTTP200
and zero redirects are required. These supplement readiness; no claim of a user
transaction or private ingress availability is inferred from backend health.
Deluge additionally requires both existing authenticated-RPC and VPN metrics.
Renovate hourly success must be within 7200s, allowing one additional schedule
period; its source metrics still require normal 60s freshness.

## Executed validation

All 61 classified apps and 54 monitors pass the catalog validator, including
current read-only live Applications union.22 negative tests pass. All 45
Prometheus monitor predicates were POSTed through a temporary localhost
kubectl port-forward to existing Prometheus: all parsed/evaluated successfully,
43 returned 1, and two returned 0: Octelium Enterprise (existing unready
component) and Kuma (not deployed yet). This proves missing/unhealthy targets
are not manufactured healthy. The temporary port-forward was stopped; no live
configuration or workload was modified. This is query-contract evidence,
not completed Kuma observations or private owner-access acceptance.

JSON-query monitors use native supported POST with form-urlencoded query body,
keeping 54 app/service-boundary monitors rather than one monitor per component.
The fixed Prometheus URL avoids HTTP GET URI limits. Catalog size is 609KB;
the rendered combined catalog/adapter ConfigMap has623630 data bytes and
650293 encoded object bytes, safely below the1MiB limit.
