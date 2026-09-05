# Monitoring Upgrade Candidates

Tags: #operations #security #monitoring

Related: [[monitoring-image-inventory]], [[validation-gates]].

## Decision

As of 2026-08-30, [kube-prometheus-stack `88.6.1`][bundle-release] is the latest
stable bundle, versus the repository's `85.2.0`. Subsequent manual scans passed
Prometheus and certgen but failed Alertmanager, Operator, reloader and KSM.
**The whole bundle is not accepted and [#926][issue] remains open.**

The initial source-only phase used public release APIs, versioned text and
baseline reports; it fetched no chart archives or image layers and ran no scans.
The separately authorized manual image phase is recorded below. Neither phase
changed pins or live state. Repository base:
`021a510698be3e7f88bd672301717e4f6e76841b`.

## Stable Bundle

[Chart metadata][chart] and [default values][values] select the following;
kube-state-metrics comes from [subchart `8.4.1`][ksm-chart]. Each component is
also its project's latest non-prerelease release at inspection:
[Prometheus][prom-release], [Alertmanager][alert-release],
[Operator/reloader][operator-release], [kube-state-metrics][ksm-release] and
[certgen][certgen-release]. Repository names remain those in
[[monitoring-image-inventory]]; resolved candidate digests follow below.

| Component          | Current tag        | Candidate tag      |
| ------------------ | ------------------ | ------------------ |
| Prometheus         | v3.11.3-distroless | v3.14.0-distroless |
| Alertmanager       | v0.32.1            | v0.34.0            |
| Operator           | v0.90.1            | v0.93.1            |
| Config reloader    | v0.90.1            | v0.93.1            |
| kube-state-metrics | v2.18.0            | v2.20.0            |
| Webhook certgen    | 1.8.2              | 1.8.8              |

## Initial Source-Level Security Comparison

Baseline: the six failed scans in [[monitoring-image-inventory]], with retained
`/private/tmp/homelab-monitoring-scans-791.bFNM7C/findings.json` and
`audit-evidence.json`. Comparisons below concern their package/module-version
matches, not vulnerable symbol presence, runtime preconditions or exploitability.
Source requirements are not proof of the contents of a published image.

- **Prometheus:** [tagged dependencies][prom-mod] declare `x/net 0.57.0`,
  `x/crypto 0.54.0`, `x/text 0.40.0`, `jsonparser 1.1.2`, OpenTelemetry SDK
  `1.44.0` and gRPC `1.82.1`, meeting the baseline's non-stdlib fix thresholds.
  [Promu selects Go `1.26`][prom-build], not an immutable patch version;
  `go.mod`'s `1.25.8` is the minimum language/toolchain requirement.
- **Alertmanager:** [tagged dependencies][alert-mod] similarly update net,
  crypto, text, SDK and gRPC, but retain `x/mod 0.38.0`. This is below `0.40.0`
  for [CVE-2026-56864][mod-6180] and [CVE-2026-56865][mod-6179].
  [Promu selects Go `1.26`][alert-build], without binding its patch version.
- **Operator/reloader:** [tagged dependencies][operator-mod] select
  `prometheus 0.313.1`, above the baseline's `0.311.3` fixes, plus
  `x/net 0.57.0`, `x/crypto 0.54.0` and `x/text 0.40.0`.
  The [source build configuration][operator-build] selects Go `1.26`;
  this did not establish the image's patch version. Keep the pair together.
- **kube-state-metrics:** the [release notes][ksm-release] state Go `1.26.6`.
  [Source][ksm-mod] updates net/crypto/text to `0.57.0`/`0.54.0`/`0.40.0`
  and SDK to `1.43.0`. Go `1.26.6` and gRPC `1.79.3` meet the baseline's two
  CRITICAL minimum fixes, but gRPC remains below `1.82.1` for the HIGH
  [GHSA-hrxh-6v49-42gf][grpc-high]. A complete gate pass is not established.
- **Certgen:** [source][certgen-mod] requires Go `1.27.0`, `x/net 0.58.0`
  and `x/text 0.41.0`; its [publish workflow][certgen-build] selects Go from
  that file. These initially identified a candidate requiring image inspection.

Other or newly included packages may still fail policy. In particular,
passing source-version comparisons must not be described as a clean scan.

## Actual Candidate Scans

Six sequential Linux/amd64 scans ran once each on 2026-08-30, 04:10:16–04:10:34
UTC, without operational errors. Policy remained
`HIGH,CRITICAL --ignore-unfixed`, with no ignore-file exceptions.
Scanner: Trivy `0.74.0`, built with `go1.26.7-X:jsonv2`; binary SHA-256:
`ad80cb91e207f1b0febe2901be37a05030ff39387d75cc678b50a9314ee4c61c`.
The same baseline DB was reused, unchanged before/after the batch:
`UpdatedAt: 2026-08-30T01:19:05.633371843Z`, SHA-256:
`e7128e686d6a579d2f90411ef30ba787b8e13ee225d30a87aecff285a78c528f`.

| Component          | H/C | Raw | Pkgs | Image Go | Exit |
| ------------------ | --- | --- | ---- | -------- | ---- |
| Prometheus         | 0/0 | 0   | 444  | 1.26.6   | 0    |
| Alertmanager       | 2/0 | 2   | 229  | 1.26.6   | 1    |
| Operator           | 8/0 | 8   | 163  | 1.26.5   | 1    |
| Config reloader    | 8/0 | 8   | 115  | 1.26.5   | 1    |
| kube-state-metrics | 1/0 | 1   | 109  | 1.26.6   | 1    |
| Webhook certgen    | 0/0 | 0   | 51   | 1.27.0   | 0    |

All six have positive package inventories; two pass this policy, four fail.
H/C deduplicates `(VulnerabilityID, PkgName, FixedVersion)` per image; Raw retains
repeated findings, and Pkgs counts per-target records, not unique packages.
Neither positive coverage nor a policy pass establishes complete coverage or
absence of all vulnerabilities.

Actual scans confirm the two Alertmanager `x/mod` HIGHs and the one KSM gRPC
HIGH identified above. Each Operator/reloader binary embeds Go `1.26.5` and
retains eight stdlib HIGHs fixed on branch `1.26.6`:
`CVE-2026-33818`, `CVE-2026-39821`, `CVE-2026-46600`, `CVE-2026-56853`,
`CVE-2026-56858`, `CVE-2026-56859`, `CVE-2026-56860`, `CVE-2026-56862`.
These are package-version findings, not demonstrated runtime exploitability.

Immutable index references and their Linux/amd64 child manifests:

1. `quay.io/prometheus/prometheus:v3.14.0-distroless@sha256:50c707e96da5ade383cb1707790576480485e93de06aa60ad8802cb5f744bd0a`
   amd64:
   `sha256:934c331c7aa29ffdb23b4befec6f34321c518453e63713d741d8ac1737c8e049`.
2. `quay.io/prometheus/alertmanager:v0.34.0@sha256:690c7b525f4367aa91f73e2f91c632206d32e97c6384bdbf2fb7a861b420340d`
   amd64:
   `sha256:268d4bf0e4bc0fe6dbdef6a59ce81a2918c88458bf8edf7dd0572ad372a093e6`.
3. `quay.io/prometheus-operator/prometheus-operator:v0.93.1@sha256:e52bb28fd41c98dd407c7a8cba8bdcfe7eabd7447e250afaf1fe7bb816dedbff`
   amd64:
   `sha256:43b87fc949b56f035ff5bf0b228054e753c10801cdf32ebfe0a6448014f80353`.
4. `quay.io/prometheus-operator/prometheus-config-reloader:v0.93.1@sha256:428f088fe6fe07ab138bda92113664b04848a1dc408e4d3680a60ecdb55d1a65`
   amd64:
   `sha256:a8ef925b324babee5da12ff39dc9754c655a0374e84cc072b3ea5625f8349e9c`.
5. `registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.20.0@sha256:42cfe3723a5f058171c627537fb57a3ea0f26e4380fa18555a95cb1a1b4cfc5b`
   amd64:
   `sha256:01171220c7c059afc85034ffe687bfe7249e41c0cc46fbe9a5128503ceee3016`.
6. `ghcr.io/jkroepke/kube-webhook-certgen:1.8.8@sha256:cd85a621724cd9043a5b46a784578fa159437712f920166389fce830554e1c44`
   amd64:
   `sha256:5c5ed49776ac3a295c723de1f9743158a4e72f08c456e88e93536d41c815f03b`.

Retained evidence: `/private/tmp/homelab-monitoring-candidates-926.j8FG9i/`
contains `scope.json`, `audit-evidence.json`, `findings.json`, full invocation
and `reports/1.json` through `reports/6.json` in the order above. Index, child,
config and report hashes were checked. Audit evidence SHA-256:
`ead664e371d4319465f6e2f559eaae5656854bad048a748f85f4ac466eb45151`.

## Compatibility and Acceptance Gates

- [Chart `kubeVersion`][chart] is `>=1.25.0-0`, admitting documented Kubernetes
  `1.34.1`; this is stricter than its README's `1.19+`. The
  [Operator compatibility notes][compat] also require Kubernetes `1.25+`.
  These are admission/support bounds, not tested homelab compatibility.
- Operator and [kube-state-metrics][ksm-compat] use client-go `0.36.3`;
  certgen uses `0.37.0`. KSM maps this release to Kubernetes `1.36`, versus
  `1.34` for the existing `2.18.0`. Shared API compatibility is conditional;
  neither the [client-go matrix][client-compat] nor this research establishes
  full resource parity on `1.34.1`. Operator's documented primary test versions
  are Prometheus `3.13.1` and Alertmanager `0.33.1`, older than this bundle.
- The [85→86→87→88 upgrade notes][upgrade] require corresponding Operator CRD
  updates. Review CRD ordering through the repository-owned Argo path before
  rollout; upstream manual mutation examples do not authorize live commands.
  Preserve existing PVCs, retention, selectors and the runtime config Secret.
  The query check below found no matching repo-owned expression change.
  A rollback must retain data and account for CRD compatibility, not merely
  revert the chart number.

Next: the four failing images still need patched candidates and passing scans.
Even the two passing images require reviewed compatibility and relevant
render/CRD/configuration checks before any proposed upgrade is accepted.
[Draft #820][draft] covers baseline pins; avoid a parallel pin PR. No rollout
or whole-bundle acceptance is implied, and continuous CI coverage is unchanged.

## Repository Query Compatibility Check

Source-only follow-up on 2026-08-30 found **no concrete breaking match** in
40 stored PromQL expressions: 19 [Grafana alert queries][repo-alerts], four
[Prometheus rules][repo-rules] and 17 queries across the three
[repository dashboard files][repo-dashboards]. No expression change is proposed.

- [KSM's changed `kube_pod_status_reason` emission][ksm-changes] has no caller.
  The CrashLoopBackOff rule uses the different
  `kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} > 0`.
- [Alertmanager's removed `alertmanager_marked_alerts`, changed failure-reason
  labels and removed `auto-gomaxprocs` flag][alert-changes] have no callers or
  configured flags in these directories.
- [Prometheus's duration-function renames and optional start-timestamp
  semantics][prom-changes] do not match the queries or enabled features.
  Existing `max(...)` expressions use aggregation, not renamed duration
  functions; ordinary `rate`/`increase` remain without the opt-in flag.
- The existing `max(up{job="kube-state-metrics"}) or vector(0)` still matches
  the candidate subchart's source job-label default: both cached `7.3.0` and
  [candidate `8.4.1`][ksm-monitor] use `app.kubernetes.io/name`, with no repo
  override. No changed-label caller was identified.

This checks candidate compatibility of repo-owned definitions only. Imported
Grafana.com dashboard contents and upstream-generated rules were not fetched
or audited; no candidate render, rule execution or live validation occurred.

[issue]: https://github.com/Stuhlmuller/homelab/issues/926
[bundle-release]: https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-88.6.1
[chart]: https://github.com/prometheus-community/helm-charts/blob/kube-prometheus-stack-88.6.1/charts/kube-prometheus-stack/Chart.yaml
[values]: https://github.com/prometheus-community/helm-charts/blob/kube-prometheus-stack-88.6.1/charts/kube-prometheus-stack/values.yaml
[ksm-chart]: https://github.com/prometheus-community/helm-charts/blob/kube-state-metrics-8.4.1/charts/kube-state-metrics/Chart.yaml
[prom-release]: https://github.com/prometheus/prometheus/releases/tag/v3.14.0
[alert-release]: https://github.com/prometheus/alertmanager/releases/tag/v0.34.0
[operator-release]: https://github.com/prometheus-operator/prometheus-operator/releases/tag/v0.93.1
[ksm-release]: https://github.com/kubernetes/kube-state-metrics/releases/tag/v2.20.0
[certgen-release]: https://github.com/jkroepke/kube-webhook-certgen/releases/tag/v1.8.8
[prom-mod]: https://github.com/prometheus/prometheus/blob/v3.14.0/go.mod
[prom-build]: https://github.com/prometheus/prometheus/blob/v3.14.0/.promu.yml
[alert-mod]: https://github.com/prometheus/alertmanager/blob/v0.34.0/go.mod
[alert-build]: https://github.com/prometheus/alertmanager/blob/v0.34.0/.promu.yml
[operator-mod]: https://github.com/prometheus-operator/prometheus-operator/blob/v0.93.1/go.mod
[operator-build]: https://github.com/prometheus-operator/prometheus-operator/blob/v0.93.1/.github/env
[ksm-mod]: https://github.com/kubernetes/kube-state-metrics/blob/v2.20.0/go.mod
[certgen-mod]: https://github.com/jkroepke/kube-webhook-certgen/blob/v1.8.8/go.mod
[certgen-build]: https://github.com/jkroepke/kube-webhook-certgen/blob/v1.8.8/.github/workflows/ci.yaml
[mod-6180]: https://pkg.go.dev/vuln/GO-2026-6180
[mod-6179]: https://pkg.go.dev/vuln/GO-2026-6179
[grpc-high]: https://github.com/grpc/grpc-go/security/advisories/GHSA-hrxh-6v49-42gf
[compat]: https://github.com/prometheus-operator/prometheus-operator/blob/v0.93.1/Documentation/getting-started/compatibility.md
[ksm-compat]: https://github.com/kubernetes/kube-state-metrics/blob/v2.20.0/README.md#compatibility-matrix
[client-compat]: https://github.com/kubernetes/client-go/blob/v0.36.3/README.md#compatibility-matrix
[upgrade]: https://github.com/prometheus-community/helm-charts/blob/kube-prometheus-stack-88.6.1/charts/kube-prometheus-stack/UPGRADE.md
[draft]: https://github.com/Stuhlmuller/homelab/pull/820
[repo-alerts]: ../../../clusters/homelab/apps/grafana/values.yaml
[repo-rules]: ../../../clusters/homelab/apps/prometheus/argocd-prometheusrules.yaml
[repo-dashboards]: ../../../clusters/homelab/apps/grafana/dashboards
[ksm-changes]: https://github.com/kubernetes/kube-state-metrics/blob/v2.20.0/CHANGELOG.md
[alert-changes]: https://github.com/prometheus/alertmanager/blob/v0.34.0/CHANGELOG.md
[prom-changes]: https://github.com/prometheus/prometheus/blob/v3.14.0/CHANGELOG.md
[ksm-monitor]: https://github.com/prometheus-community/helm-charts/blob/kube-state-metrics-8.4.1/charts/kube-state-metrics/templates/servicemonitor.yaml
