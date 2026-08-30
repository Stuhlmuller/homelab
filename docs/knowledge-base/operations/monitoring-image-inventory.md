# Monitoring Image Inventory

Tags: #operations #security #monitoring

Related: [[continuous-improvement]], [[validation-gates]], [[workloads/inventory]].

## Scope and Provenance

Initial metadata-only follow-up for [#791][issue], observed 2026-08-30 at
03:29 UTC: exactly six configured Prometheus-stack identities, without scans,
execution, live inspection or manifest changes. Digest resolution alone does
not establish package coverage or a clean image. The later manual scan results
below are separate evidence; no version or pin changes were made.

Repository base: `021a510698be3e7f88bd672301717e4f6e76841b` (#921).
[The declared Application source][stack] pins `kube-prometheus-stack` `85.2.0`,
release `prometheus`, namespace `monitoring`, with [repository values][values].
Those values have no image overrides and match main commit
`b408a858877e3a53c5bbe9da93a927ae6dfabc0e`. They disable bundled Grafana and
node-exporter; neither is part of this inventory.

Source inspection used the previously cached chart at
`/private/tmp/helm-fix791/charts/prometheus/kube-prometheus-stack`:
chart `85.2.0`, operator appVersion `v0.90.1`, and kube-state-metrics subchart
`7.3.0` / appVersion `2.18.0`. See [upstream chart source][chart].
The metadata phase did not render or fetch another chart version.

## Configured Images and Immutable Resolution

Each full reference below pins the **multi-platform index**. The separate
Linux/amd64 digest identifies the child manifest for the subsequent
audit. Registry response bytes, digest headers, child descriptors and image
configuration digests were checked; all six configurations report
`os: linux`, `architecture: amd64`.

1. [Prometheus][prometheus-registry], explicit Prometheus CR `spec.image`:
   `quay.io/prometheus/prometheus:v3.11.3-distroless@sha256:cff72a3f49918f41c4b5c8a6174dd8433036bebf7878120da538b3720ba3fa0d`.
   Linux/amd64:
   `sha256:a1868e471c843677013c5fa2f569011e70d49b9e8f690719ea750b458840ec6d`.
2. [Alertmanager][alertmanager-registry], explicit Alertmanager CR `spec.image`:
   `quay.io/prometheus/alertmanager:v0.32.1@sha256:51a825c2a40acc3e338fdd00d622e01ec090f72be2b3ea46be0839cd47a4d286`.
   Linux/amd64:
   `sha256:82c38dcc97cd0fbf5d5e31ddfb304dbb3a6e411194477de5de82ec71b328bb40`.
3. [Prometheus Operator][operator-registry], Deployment container:
   `quay.io/prometheus-operator/prometheus-operator:v0.90.1@sha256:52a6a92d915ea2fa94314748d99db7a94922e3fe63274f6182fc033b9126b573`.
   Linux/amd64:
   `sha256:c8aed26b2a0858b4beed8d6bc2215f7f6bdc6c96dd4de8e6e246c0a5b7a7876b`.
4. [Config reloader][reloader-registry], operator-generated init/sidecar image:
   `quay.io/prometheus-operator/prometheus-config-reloader:v0.90.1@sha256:693faa0b87243cddca2cffb13586e4e2778b0cdf319cb2e601ba7af3fd19ef7d`.
   Linux/amd64:
   `sha256:af7715ef28e2cc413a6a850b5f928f185245dbb38359156eca3d5f1eb676b93f`.
5. [kube-state-metrics][ksm-registry], subchart Deployment container:
   `registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.18.0@sha256:1545919b72e3ae035454fc054131e8d0f14b42ef6fc5b2ad5c751cafa6b2130e`.
   Linux/amd64:
   `sha256:e780845683dabd141d25d88a9d7221b567844832bf4f48d1c52f081861174661`.
6. [Webhook certgen][certgen-registry], admission create/patch hook Jobs:
   `ghcr.io/jkroepke/kube-webhook-certgen:1.8.2@sha256:e133b64c08377a107298ac3352504bd3cd21f13282bc2aac099a88a7888b3f54`.
   Linux/amd64:
   `sha256:5258ef7a9c3130b6ac380142b8af23845de9ec668f2498480288fce22503c6df`.

The [operator template][operator-template] derives the operator and reloader
tags from chart appVersion because their chart image tags are empty. It passes
`--prometheus-config-reloader=quay.io/prometheus-operator/prometheus-config-reloader:v0.90.1`.
The operator then creates reloader init/sidecar containers for both
[Prometheus][prometheus-generated] and [Alertmanager][alertmanager-generated].
The optional Prometheus/Alertmanager default-base-image flags are not set by
these values; the CRs already specify their images explicitly. Counting only
ordinary Deployment container fields would miss these generated workload paths.

Thanos is not configured in the Prometheus CR; its unused operator default is
outside this six-image scope. No claim is made about the remaining chart-default
inventory or live Pods.

## Existing Draft

[Draft #820][draft] (`eb70a03418d5fa547f93dceb9cbf034ccc4beb1a` at inspection)
already proposes digest pins for **all six identities above**. Every proposed
index digest matches this public-registry resolution. This is overlapping
evidence for that draft, not a reason for a parallel pin PR or a claim that its
pins are already deployed. Leave its code and values unchanged in this pass.

Pinning alone does not establish scanner coverage. Drafts #921 (`021a5106`)
and #922 (`022cbbb5`) extract **zero** references from #820's monitoring values:
all six pins use native chart `image.sha` fields, which the scoped extractor
does not support, with registry/repository/tag inherited from chart defaults.
Merging those defaults still yields zero extracted references. Rendered
manifests expose five images; the reloader remains in an operator argument.
This is part of #791's existing Helm/generated-image gap, not a new parser
defect. The package-coverage guard cannot detect an image omitted from its input.

Retained local metadata, not committed:
`/private/tmp/homelab-monitoring-791.Nt1ByQ/registry-metadata.json` records full
references, index/amd64/config digests, public endpoints and checks. Resolution
ran with inherited environment cleared and no credential-file access. GHCR
required one anonymous pull-token challenge, held only in memory; no account
credentials, image layers, package databases or scanners were used in that
metadata phase.

## Manual Scan Results

At 03:36 UTC on 2026-08-30, a separate manual audit scanned exactly these six
Linux/amd64 images once with Trivy `0.74.0`, built with Go `1.26.7`. Policy:
`HIGH,CRITICAL`, `--ignore-unfixed`, no ignore-file exceptions. The existing DB
was reused unchanged: `UpdatedAt: 2026-08-30T01:19:05.633371843Z`.
All six reports had positive package inventories and exit status **1**;
none passed the vulnerability gate. [Issue #926][findings-issue] tracks fixes.

| Component           | Embedded Go | HIGH | CRITICAL | Raw rows |
| ------------------- | ----------- | ---- | -------- | -------- |
| Prometheus          | 1.26.2      | 34   | 0        | 66       |
| Alertmanager        | 1.26.2      | 35   | 0        | 68       |
| Prometheus Operator | 1.25.8      | 26   | 0        | 26       |
| Config reloader     | 1.25.8      | 35   | 0        | 35       |
| kube-state-metrics  | 1.25.5      | 39   | 2        | 41       |
| Webhook certgen     | 1.26.2      | 21   | 0        | 21       |

HIGH/CRITICAL counts deduplicate `(VulnerabilityID, PkgName, FixedVersion)`
within each image; raw rows include repeated findings across binaries. These
are package/module-version matches, not proof of reachable vulnerable code,
runtime preconditions, exploitability or deployment. Positive package coverage
does not prove complete filesystem or advisory coverage.

kube-state-metrics has two CRITICAL matches: [CVE-2025-68121][go-critical]
in Go `1.25.5` (minimum fix on that branch: `1.25.7`) and
[CVE-2026-33186][grpc-critical] in `google.golang.org/grpc` `1.75.1`
(minimum fix: `1.79.3`). Their runtime preconditions are not established here;
these minimum fixes do not clear the other HIGH findings.

Retained local scan evidence, not committed:
`/private/tmp/homelab-monitoring-scans-791.bFNM7C/audit-evidence.json` and
`findings.json`, with `reports/1.json` through `reports/6.json` in the same
directory, in the image order above. Evidence records exact references,
report hashes, invocation, DB identity, package counts and each exit status.

Next: under [#926][findings-issue], validate compatible patched candidates with
positive package inventories and no fixable HIGH/CRITICAL findings under the
unchanged policy. Verify generated/hook image extraction and rollout gates
before accepting changes. These six manual scans do not fix continuous CI
coverage for all 24 omitted chart-default identities; the pins remain in
[draft #820][draft]. No parallel pin PR or live change is part of this note.

[issue]: https://github.com/Stuhlmuller/homelab/issues/791
[stack]: ../../../IaC/terragrunt.stack.hcl
[values]: ../../../clusters/homelab/apps/prometheus/values.yaml
[chart]: https://github.com/prometheus-community/helm-charts/tree/kube-prometheus-stack-85.2.0/charts/kube-prometheus-stack
[operator-template]: https://github.com/prometheus-community/helm-charts/blob/kube-prometheus-stack-85.2.0/charts/kube-prometheus-stack/templates/prometheus-operator/deployment.yaml
[prometheus-generated]: https://github.com/prometheus-operator/prometheus-operator/blob/v0.90.1/pkg/prometheus/server/statefulset.go
[alertmanager-generated]: https://github.com/prometheus-operator/prometheus-operator/blob/v0.90.1/pkg/alertmanager/statefulset.go
[prometheus-registry]: https://quay.io/v2/prometheus/prometheus/manifests/sha256:cff72a3f49918f41c4b5c8a6174dd8433036bebf7878120da538b3720ba3fa0d
[alertmanager-registry]: https://quay.io/v2/prometheus/alertmanager/manifests/sha256:51a825c2a40acc3e338fdd00d622e01ec090f72be2b3ea46be0839cd47a4d286
[operator-registry]: https://quay.io/v2/prometheus-operator/prometheus-operator/manifests/sha256:52a6a92d915ea2fa94314748d99db7a94922e3fe63274f6182fc033b9126b573
[reloader-registry]: https://quay.io/v2/prometheus-operator/prometheus-config-reloader/manifests/sha256:693faa0b87243cddca2cffb13586e4e2778b0cdf319cb2e601ba7af3fd19ef7d
[ksm-registry]: https://registry.k8s.io/v2/kube-state-metrics/kube-state-metrics/manifests/sha256:1545919b72e3ae035454fc054131e8d0f14b42ef6fc5b2ad5c751cafa6b2130e
[certgen-registry]: https://ghcr.io/v2/jkroepke/kube-webhook-certgen/manifests/sha256:e133b64c08377a107298ac3352504bd3cd21f13282bc2aac099a88a7888b3f54
[draft]: https://github.com/Stuhlmuller/homelab/pull/820
[findings-issue]: https://github.com/Stuhlmuller/homelab/issues/926
[go-critical]: https://pkg.go.dev/vuln/GO-2026-4337
[grpc-critical]: https://github.com/grpc/grpc-go/security/advisories/GHSA-p77j-4mvh-x3m3
