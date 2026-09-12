# Validation Gates

Tags: #operations #validation

## Default Gate

Run the smallest validation that proves the change and record unavailable
checks in the PR or final response.

Deleted-unit cleanup is limited to deployed units under `IaC/bootstrap` and
`IaC/live`, including removals from the explicit stack. Catalog templates and
`IaC/operator` are never retired by the workflow. Every saved destroy plan must
pass the same Conftest policy as ordinary plans before production applies it;
protected resource deletion cannot bypass policy through unit removal.
Synthetic retirement units reuse the canonical Kubernetes and Helm connection
configuration. Encrypted-state retirement remains gated on the decoder work in
[PR #837](https://github.com/Stuhlmuller/homelab/pull/837).

For most repo changes, start with:

```sh
terragrunt hcl fmt --check
terragrunt hcl validate
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
git diff --check
```

The static gate runs `scripts/ci/job-alert-recovery-check.py` with the Nix-pinned
promtool against the actual Job recovery rules. Its synthetic histories cover
failure/success ordering, false/unknown condition gauges and transitions to true,
overlap, later failed runs, namespace isolation,
missing metrics, conflicting owners, duplicate recovered and unrecovered
scrapes, target turnover during a pending alert, recreated names, and
the existing 15-minute firing hold after five-minute group detection. The check
also requires the custom rule's
Kustomize registration, the chart-default replacement switch, and matching
15-day retention. Live rollout must leave one healthy `KubeJobFailed` rule;
see `clusters/homelab/apps/prometheus/README.md` for verification and rollback.

Operator-owned AWS bootstrap units require a focused backend-free validation
and an administrator-authenticated plan before apply:

```sh
cd IaC/operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable init -reconfigure -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable state list
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_role.github_actions' Github-TF-State
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_user.external_secrets' external-secrets_aws-ssm-auth
umask 077
plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-operator.XXXXXX")"
trap 'rm -rf -- "$plan_dir"' EXIT
AWS_PROFILE=<administrator-profile> terragrunt --log-disable plan \
  -out="$plan_dir/plan.out" -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable show -no-color "$plan_dir/plan.out"
AWS_PROFILE=<administrator-profile> terragrunt --log-disable apply -no-color "$plan_dir/plan.out"
```

Run each import only on the first rollout, or during state recovery, when
`state list` does not contain its address: `aws_iam_role.github_actions` or
`aws_iam_user.external_secrets`. Backend-free validation deliberately leaves
the working directory detached from shared state, so the authenticated
`init -reconfigure` must precede every import, production plan, or apply from
that directory.

The GitHub workflow role must not plan or apply `IaC/operator`; those units own
the permissions that protect the workflow from self-administration.
Keep `--no-auto-init` on the backend-free validation and test commands;
otherwise Terragrunt can initialize the real S3 backend before running them.

## GitHub Workflow Checks

Workflow changes are covered by `scripts/ci/conftest-policies.sh` and
`policy/workflows.rego`. External `uses:` references must be pinned to a full
40-character commit SHA; keep an optional trailing version comment when it helps
reviewers map the immutable pin back to the upstream release tag.

The pull-request `Terragrunt Gate` is an always-present aggregate. Its
unprivileged static job runs for every PR and owns live-scope detection. Only a
trusted same-repository PR whose diff contains a declared live input may enter
the `homelab-plan` environment; forks and other changes must leave the live job
skipped. The aggregate fails unless static checks succeed and the applicable
live plan or same-repository skip-note job has the expected result. Keep the
exact workflow contract asserted in `scripts/ci/static-checks.sh`.
That assertion pins the normalized live-scope and aggregate-gate bodies by
SHA-256 and pins each credentialed job as normalized JSON, so comments, dead
code, or added post-authentication steps cannot satisfy the check. Its closed
inventory rejects new environment-, secret-, token-, or write-permission jobs
until their complete job definition is reviewed and hashed. Conftest also
rejects direct live `kubectl`, `talosctl`, AWS, Terragrunt, OpenTofu, Terraform,
or non-rendering Helm output and any command after the private-log wrapper;
credentials stay scoped to the one live step.

The Tunnel DNS workflow is also bound to an explicit reviewed main SHA and
included in that closed credentialed-workflow inventory. It uses only the
existing production AWS role and Cloudflare rule-removal secret, with private
API output withheld. Validate its full definition before updating the hash.

The local secret hook rejects common plan/state filenames and inspects ZIP
members or JSON structure for OpenTofu plan/state signatures, including staged
blobs whose working-tree file was removed.

Do not require a new Actions context in ruleset `14700233` before the workflow
that emits it is merged. First observe `Terragrunt Gate` on a no-live-plan PR, a
trusted live-plan PR, and a fork; then add only that context while preserving
the existing required checks and verify a fresh no-live-plan PR does not
deadlock.

The CodeQL workflow in `.github/workflows/codeql.yml` runs on pushes
and pull requests targeting `main` and on its weekly schedule. It has one
buildless `actions` analysis job because this repository has no compiled
application source. Treat it as CI/CD security automation: workflow edits
should pass the static policy gate locally before relying on GitHub's code
scanning result.

For docs-only or knowledge-base-only changes, focused Markdown and whitespace
checks are acceptable when the infrastructure graph is untouched:

```sh
git diff --check -- AGENTS.md ONBOARDING.md docs/knowledge-base .agents/skills
rg -n \
  "password|token|secret|api[_-]?key|PRIVATE KEY|BEGIN CERTIFICATE|kubeconfig" \
  docs/knowledge-base .agents/skills
```

## Kubernetes Source Checks

Use the renderer that matches the changed source:

```sh
kubectl kustomize clusters/homelab/apps/<app>
kubectl kustomize clusters/homelab/platform/<service>
helm template <release> <chart> -f clusters/homelab/apps/<app>/values.yaml
kubectl diff --server-side -k clusters/homelab/apps/<app>
```

For image automation changes, render the retirement source, validate Renovate,
and confirm no image bypasses digest policy:

```sh
kubectl kustomize clusters/homelab/apps/argocd-image-updater
npx --yes --package renovate renovate-config-validator renovate.json
nix develop --command bash scripts/ci/static-checks.sh
```

For `platform-dns` changes, render the overlay and compare upstream answers
before rollout. After Argo CD syncs, verify CoreDNS contains the intended
resolvers and a workload pod receives a public answer rather than a sinkhole:

```sh
kubectl kustomize clusters/homelab/platform/dns
dig +short A iptorrents.com @1.1.1.1
kubectl -n kube-system get configmap coredns -o yaml
kubectl -n media exec deployment/prowlarr -c app -- getent ahostsv4 iptorrents.com
```

## Octelium Cutover Checks

Before running `octops init`, validate the self-hosted Cluster prerequisites:

```sh
kubectl kustomize clusters/homelab/platform/multus
kubectl kustomize clusters/homelab/apps/octelium-storage
kubectl kustomize clusters/homelab/apps/octelium-cluster
kubectl kustomize clusters/homelab/apps/octelium-public
bash -n \
  scripts/octelium-gateway-dns.sh \
  scripts/octelium-public-dns.sh \
  scripts/octelium-cloudflare-origin-port.sh \
  scripts/octelium-entra-oidc.sh
scripts/octelium-cluster-bootstrap.sh --help
```

After a Multus rollout or burst of Octelium service pod replacements, verify
all Multus pods remain ready and below their 512Mi memory limit. A daemon at its
limit plus `multus-shim` timeouts means the Octelium ingress can lose every
endpoint while Argo CD still reports `platform-multus` healthy.

```sh
kubectl -n kube-system rollout status daemonset/kube-multus-ds
kubectl -n kube-system top pod -l app=multus --containers
kubectl -n octelium get events --field-selector reason=FailedCreatePodSandBox
```

After the prerequisite apps are applied, `scripts/octelium-cluster-bootstrap.sh`
checks the Multus CRD, Multus DaemonSet rollout, Octelium node labels, and
PostgreSQL/Redis readiness before it calls `octops init` in front-proxy mode.
The `octelium-cluster` app renders the Istio front-door route, its HTTP/2
upstream `DestinationRule`, and the scoped console login-return `EnvoyFilter`
in `istio-system`; it must not create the
`octelium` namespace because Octelium genesis owns that namespace during
bootstrap. The bootstrap wrapper applies the required privileged Pod Security
labels to the namespace after `octops` creates it.

The filter rewrites only the exact unauthorized browser login redirect for
`console.stinkyboi.com`. Validate its rendered Lua with the static gate and
the public browser probe in `scripts/octelium-e2e-check.sh`, then verify
authenticated page rendering and audit queries. Revalidate Envoy compatibility
when upgrading Istio. Automated pruning is disabled for this app: rollback
must commit an empty `spec.configPatches` list and adjust the filter test gate,
as described in `clusters/homelab/apps/octelium-cluster/README.md`; deleting
the file alone leaves the live filter installed.

Before declaring Octelium-backed app UI access healthy, the replacement path
must pass:

```sh
nix develop --command python3 scripts/octelium-tunnel-check.py
scripts/octelium-e2e-check.sh
```

The transport probe resolves the browser API through `1.1.1.1` and validates
its gRPC-Web status-16 trailer. A trailers-only response may carry that status
in its headers with an empty body, as the
[gRPC-Web protocol](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-WEB.md)
permits. The September 12 audit reproduced this response from the healthy
public endpoint; requiring a body trailer incorrectly failed the transport
gate. Nonempty responses still require their final trailer frame, and the
probe retains its HTTP/2, content-type, status and TLS checks.
The probe parses the final HTTP response in curl's header dump, excluding
informational and proxy CONNECT responses. It requires one actual content-type
field with the expected media type; optional parameters are permitted.
Duplicate status or content-type fields cannot satisfy the gate. Native gRPC
may return status in its actual HTTP trailers, while a nonempty gRPC-Web body
must carry its sole status in the final body trailer frame.
It separately starts a temporary TCP carrier
and requires verified origin TLS, HTTP/2, and native gRPC status 16. Generic
HTTP responses and local listener readiness do not pass. The catalog checks
still require authenticated `octeliumctl` with a configured native transport
or the existing private route. Also verify authenticated console rendering,
audit queries, and real Cordium execution/reconnects before declaring recovery.

Before treating Tailscale as unnecessary for Kubernetes access, validate both
human paths from outside the homelab. On the operator workstation, run
`octelium connect -d`, generate the client kubeconfig with `octelium config
kubernetes-api.homelab`, run its printed export, set the file to mode `0600`,
and require `kubectl --request-timeout=15s get nodes` to succeed. Repeat the
config, mode, and `kubectl` check inside a Cordium Workspace, whose client
session is created automatically. Also require Secret reads and a server-side
dry-run create to be denied there; Cordium has restricted read-only access.
Keep the Tailscale fallback until both pass; Talos transport is a separate
retirement gate.

Pass `--octelium-context` and `--homelab-context` when the Octelium control
plane and homelab connector live in different Kubernetes clusters.

CI/CD Octelium changes should also pass shell syntax checks for
`scripts/ci/install-kubeconfig.sh`, `scripts/octelium-ci-credential.sh`, and
`scripts/octelium-ci-kubeconfig-secret.sh`. Validate that
`docs/examples/octelium/homelab-services.yaml` parses and contains Service
`kubernetes-api-ci` plus core `ClusterConfig` `default` with human
`maxPerUser: 32`, and that User `homelab-ci` keeps matching 30-day clientless
Session and access-token lifetimes before applying it with `octeliumctl`.
Apply the `ClusterConfig` with `--include ClusterConfig` before the normal
catalog apply because the include flag replaces the default resource-kind list.
The static gate requires manual Homelab Diagnostics and Terragrunt Apply
dispatches to carry an exact expected `main` SHA and fail before work when the
resolved workflow commit differs. Every push to `main` runs only the cancellable
`Terragrunt Apply Request` check; it uses no protected environment, stored
secret, or OIDC permission and prints the exact dispatch command plus active
apply links without opening a production approval. The protected apply's first
post-approval step requires the expected, workflow, and current `main` SHAs to
match before credentials or live commands.
The live job retains only the newest pending run and never cancels an
in-progress apply. GitHub's native environment/concurrency queue cannot enforce
an automatic approval SLA; strict expiry needs an externally hosted GitHub App
deployment-protection rule with a durable lease. Until then, dispatch only when
a reviewer is ready to approve.

The focused Octelium private Kubernetes workflow has the same exact-`main`,
current-head, production-approval, serialized-run, private-log, static, and
Conftest gates. Its fixed helper extracts exactly
`Policy/homelab-private-kubernetes-access` and
`Service/kubernetes-api.homelab`, never prunes, and requires a second apply to
report no changes. The lifecycle helper installs cleanup before creating its
30-minute, one-authentication Credential, binds its watch to the unique run it
dispatches, and verifies Credential, Session, and GitHub-secret revocation on
exit. See `docs/ci-cd.md`.

The gate checks the Octelium control plane, IdentityProvider `entra`, private
`kubernetes-api.homelab` Service, synced
workload credential, ready connector replica, and
`ambient.istio.io/redirection=enabled` on every active connector pod. It also
checks Cluster/API/portal TLS responses, the complete homelab WEB Service
catalog, public DNS for each existing
`*.stinkyboi.com` app hostname, and HTTPS access to each app hostname through
Octelium public WEB access. It requires AFFiNE's anonymous Service mode, NOFX's
`homelab-human-web-access` policy, and unauthenticated NOFX `/` and `/api/health`
responses to carry Octelium's `401` denial header. It also validates AFFiNE's
native-client CORS preflight plus public `serverConfig` GraphQL query, confirms
AFFiNE rejects an unauthenticated workspace query, and ensures every other
public app Service remains non-anonymous. App hostnames
must not resolve to private
Octelium service IPs or the old Tailscale wildcard. The same script probes the
Cordium nested workspace wildcard for valid edge TLS and probes the reviewed
callback hostnames for public DNS and path-limited reachability; the
n8n expected-negative webhook probe must see an n8n webhook response body, not
only a generic HTTP 404 from Cloudflare or the Istio gateway, while the Policy
Bot webhook probe must use the POST shape GitHub sends and require the app-level
HTTP 400 webhook validation response, not just any non-404 response.

Rendered Kubernetes policy also enforces the access contract:
`policy/kubernetes.rego` rejects Tailscale Funnel and classifies every
gateway-attached `VirtualService`, every `Gateway`, and every `Ingress` except
the explicit `compass-discovery` class as externally reachable by default.
Those resources must declare `homelab.rst.io/access-plane: octelium`; only
gatewayless or mesh-only `VirtualService` resources and Compass discovery
entries are exempt. The policy also requires reviewed
`homelab.rst.io/public-callback-*` annotations for unauthenticated callback
hosts such as `n8n-webhook.stinkyboi.com` and
`policy-bot-hook.stinkyboi.com`. Run `scripts/ci/conftest-policies.sh` after
changing route manifests or the Octelium public tunnel/DNS host list.

The script must report failed probes as `FAIL:` lines and finish with a nonzero
exit code when any check fails. Keep expected-negative probes inside guarded
conditionals and avoid empty-array expansion under `set -u`, so macOS Bash 3.2
does not exit before the failure summary.

## Istio Ambient Recovery

Use these read-only checks after node recovery or an ambient configuration
rollout. All must pass before closing the readiness finding; connector access
alone is insufficient. Keep raw logs outside git.

Require every node Ready and both DaemonSets fully updated, observed, and
available on every node, with no misscheduled instances:

```sh
(
set -euo pipefail
kubectl get nodes -o json | jq -e '
  (.items | length) > 0 and
  all(.items[]; any(.status.conditions[]; .type == "Ready" and .status == "True"))'
ambient_node_count="$(kubectl get nodes -o json | jq '.items | length')"
kubectl -n istio-system get ds istio-cni-node ztunnel -o json |
  jq -e --argjson n "$ambient_node_count" '
    (.items | length) == 2 and all(.items[];
      .status.observedGeneration == .metadata.generation and
      .status.desiredNumberScheduled == $n and
      .status.updatedNumberScheduled == $n and
      .status.numberReady == $n and .status.numberAvailable == $n and
      .status.numberMisscheduled == 0)'
)
```

Check the live CNI ConfigMap, the rolled CNI Pods' configuration references,
every ztunnel Pod's IPv6 setting, active connector enrollment, and Argo state:

```sh
(
set -euo pipefail
kubectl -n istio-system get cm istio-cni-config -o json |
  jq -e '.data.AMBIENT_IPV6 == "false"'
kubectl -n istio-system get pods -l k8s-app=istio-cni-node -o json |
  jq -e '(.items | length) > 0 and all(.items[];
    .metadata.annotations["homelab.rst.io/ambient-ip-family"] == "ipv4" and
    any(.spec.containers[] | select(.name == "install-cni") | .envFrom[]?;
      .configMapRef.name == "istio-cni-config"))'
kubectl -n istio-system get pods -l app=ztunnel -o json |
  jq -e '(.items | length) > 0 and all(.items[];
    any(.spec.containers[] | select(.name == "istio-proxy") | .env[]?;
      .name == "IPV6_ENABLED" and .value == "false"))'
kubectl -n octelium-client get pods -l app.kubernetes.io/instance=octelium-client -o json |
  jq -e '[.items[] | select(.status.phase != "Succeeded" and .status.phase != "Failed")] as $pods |
    ($pods | length) > 0 and all($pods[];
      .metadata.annotations["ambient.istio.io/redirection"] == "enabled" and
      any(.status.conditions[]; .type == "Ready" and .status == "True"))'
kubectl -n argocd get application istio -o json |
  jq -e '.status.sync.status == "Synced" and .status.health.status == "Healthy"'
)
```

Query the existing Prometheus service through the Kubernetes API. This helper
uses the operator's kubeconfig and does not expose Prometheus publicly. Capture
one UTC endpoint for every query and the later log check; keep
`ambient_window_end` available until all checks finish:

```sh
ambient_window_end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
(
set -euo pipefail
test -n "$ambient_window_end"
ambient_promql() {
  kubectl get --raw "/api/v1/namespaces/monitoring/services/http:prometheus-kube-prometheus-prometheus:9090/proxy/api/v1/query?$(
    python3 -c 'import sys, urllib.parse; print(urllib.parse.urlencode({"query": sys.argv[1], "time": sys.argv[2]}))' \
      "$1" "$ambient_window_end"
  )" | jq -e 'if .status != "success" then error("Prometheus query failed") else .data.result end'
}
ambient_ds_uids="$(kubectl -n istio-system get ds istio-cni-node ztunnel -o json | jq -ce '
  def text: type == "string" and length > 0;
  if (.items | type) == "array" and (.items | length) == 2 and
     ([.items[].metadata.name] | sort) == ["istio-cni-node", "ztunnel"] and
     all(.items[]; .kind == "DaemonSet" and .metadata.namespace == "istio-system" and
       .metadata.deletionTimestamp == null and (.metadata.uid | text)) and
     ([.items[].metadata.uid] | unique | length) == 2
  then [.items[].metadata.uid] | sort else error("Invalid ambient DaemonSet inventory") end')"
ambient_pods="$(kubectl -n istio-system get pods -o json | jq -ce --argjson owners "$ambient_ds_uids" '
  def text: type == "string" and length > 0;
  if (.items | type) != "array" then error("Invalid Pod inventory") else .items end |
  [.[] | select(.metadata.deletionTimestamp == null and
      .status.phase != "Failed" and .status.phase != "Succeeded") |
    .status.phase as $phase | (.metadata.ownerReferences // []) as $refs |
    if .kind == "Pod" and .metadata.namespace == "istio-system" and
       (.metadata.name | text) and (.metadata.uid | text) and
       (["Pending", "Running", "Unknown"] | index($phase)) != null and
       ($refs | type) == "array" and all($refs[];
         (.kind | text) and (.name | text) and (.uid | text))
    then . else error("Malformed live Pod identity or owner") end |
    [$refs[] | select(.uid as $uid | $owners | index($uid))] as $matching |
    select(($matching | length) > 0) |
    [$refs[] | select(.controller == true)] as $controllers |
    if ($matching | length) == 1 and $controllers == $matching and
       $matching[0].kind == "DaemonSet"
    then [.metadata.namespace, .metadata.name, .metadata.uid, $matching[0].uid]
    else error("Ambiguous ambient Pod controller") end] as $pods |
  if ($pods | length) > 0 and ([$pods[][3]] | sort | unique) == $owners and
     ([$pods[] | .[0:2]] | unique | length) == ($pods | length) and
     ([$pods[][2]] | unique | length) == ($pods | length)
  then [$pods[] | .[0:3]] | sort else error("Missing or duplicate ambient Pods") end')"
ambient_promql 'min_over_time(kube_pod_status_ready{namespace="istio-system",pod=~"(ztunnel|istio-cni-node)-.*",condition="true"}[24h])' |
  jq -e --argjson expected "$ambient_pods" '
    if ([.[] | [.metric.namespace, .metric.pod, .metric.uid]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) == 1)
    then . else error("Missing, replaced or unhealthy readiness series") end'
ambient_promql 'count_over_time(kube_pod_status_ready{namespace="istio-system",pod=~"(ztunnel|istio-cni-node)-.*",condition="true"}[24h])' |
  jq -e --argjson expected "$ambient_pods" '
    if ([.[] | [.metric.namespace, .metric.pod, .metric.uid]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) >= 2880)
    then . else error("Missing or incomplete readiness history") end'
ambient_promql 'sum by (namespace, pod, pod_uid) (increase(prober_probe_total{namespace="istio-system",pod=~"(ztunnel|istio-cni-node)-.*",probe_type="Readiness",result="failed"}[24h]))' |
  jq -e --argjson expected "$ambient_pods" '
    if ([.[] | [.metric.namespace, .metric.pod, .metric.pod_uid]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) == 0)
    then . else error("Missing probe history or observed probe failures") end'
ambient_promql 'count_over_time(prober_probe_total{namespace="istio-system",pod=~"(ztunnel|istio-cni-node)-.*",probe_type="Readiness",result="failed"}[24h])' |
  jq -e --argjson expected "$ambient_pods" '
    if ([.[] | [.metric.namespace, .metric.pod, .metric.pod_uid]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) >= 2880)
    then . else error("Missing or incomplete probe history") end'
ambient_nodes="$(kubectl get nodes -o json | jq -ce '
  [.items[] | [.metadata.name,
    (([.status.addresses[] | select(.type == "InternalIP" and (.address | contains(":") | not)) | .address][0]) + ":10250")]] |
  sort | unique | if length > 0 then . else error("No expected kubelet targets") end')"
ambient_ksm_selector="$(kubectl -n monitoring get service prometheus-kube-state-metrics -o json |
  jq -er '.spec.selector | to_entries | map("\(.key)=\(.value)") | join(",") | select(length > 0)')"
ambient_ksm="$(kubectl -n monitoring get pods -l "$ambient_ksm_selector" -o json | jq -ce '
  [.items[] | select(.metadata.deletionTimestamp == null and
    .status.phase != "Failed" and .status.phase != "Succeeded") |
    [.metadata.name, (.status.podIP + ":8080")]] |
  sort | unique | if length > 0 then . else error("No expected kube-state-metrics targets") end')"
ambient_promql 'min_over_time(up{job="kube-state-metrics"}[24h])' |
  jq -e --argjson expected "$ambient_ksm" '
    if ([.[] | [.metric.pod, .metric.instance]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) == 1)
    then . else error("Missing, replaced or unhealthy kube-state-metrics targets") end'
ambient_promql 'count_over_time(up{job="kube-state-metrics"}[24h])' |
  jq -e --argjson expected "$ambient_ksm" '
    if ([.[] | [.metric.pod, .metric.instance]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) >= 2880)
    then . else error("Missing or incomplete kube-state-metrics history") end'
ambient_promql 'min_over_time(up{job="kubelet",metrics_path="/metrics/probes"}[24h])' |
  jq -e --argjson expected "$ambient_nodes" '
    if ([.[] | [.metric.node, .metric.instance]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) == 1)
    then . else error("Missing, replaced or unhealthy kubelet probe targets") end'
ambient_promql 'count_over_time(up{job="kubelet",metrics_path="/metrics/probes"}[24h])' |
  jq -e --argjson expected "$ambient_nodes" '
    if ([.[] | [.metric.node, .metric.instance]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) >= 2880)
    then . else error("Missing or incomplete kubelet probe scrape history") end'
)
```

The subshell stops at the first failed command without changing the caller's
shell options. Each assertion must exit zero; empty results, bad values, and
short observation windows fail. Require readiness minimum `1` and failed-probe
increase `0` for every current CNI and ztunnel Pod. At the declared 30-second
scrape cadence, each readiness and failed-probe counter series needs at least
2,880 samples over 24 hours. Exporter `up` checks require the same coverage and
match each live Pod/node and scrape address; the current IPv4 endpoints use
ports 8080 and 10250. Every expected target must remain `up == 1`.
All four readiness/probe assertions match namespace, Pod name and UID against
current nonterminal, nondeleting Pods controlled by the live DaemonSet UIDs.
Read-only inspection confirmed the readiness `uid` and prober `pod_uid` labels;
the probe aggregation retains that identity. Invalid/empty inventory, missing
series, gaps, counter absence, or a replacement with less than 24 hours
of observation do not prove recovery. If scrape cadence or target identity
changed, establish equivalent complete coverage before closing the finding;
do not replace missing data with zero.

Inspect all CNI and ztunnel logs for the same 24-hour window. Save current logs
privately and print only their first/last timestamps when assessing retention:

```sh
ambient_logs="$(umask 077; mktemp -d)"
(
set -euo pipefail
umask 077
test -n "$ambient_logs"
test -d "$ambient_logs"
kubectl -n istio-system get pods -o json | jq -er '
  [.items[] | select(any(.metadata.ownerReferences[]?;
    .kind == "DaemonSet" and (.name == "istio-cni-node" or .name == "ztunnel"))) |
    [.metadata.name, .spec.containers[0].name]] |
  if length > 0 then .[] | @tsv else error("No ambient Pods to collect") end' |
  while IFS="$(printf '\t')" read -r ambient_pod ambient_container; do
    kubectl -n istio-system logs "$ambient_pod" -c "$ambient_container" --timestamps \
      > "$ambient_logs/$ambient_pod.current.log"
    test -s "$ambient_logs/$ambient_pod.current.log"
  done
for ambient_file in "$ambient_logs"/*.log; do
  test -s "$ambient_file"
  awk 'NR == 1 {print FILENAME, "first", $1} END {print FILENAME, "last", $1}' "$ambient_file"
done
)
```

The directory variable remains available to later commands. Any failed fetch,
empty log or empty Pod inventory exits nonzero; discard that incomplete capture
and rerun the block before assessing retention.

`kubectl logs --since=24h` alone cannot establish that rotated records still
cover the window. If any current log starts too recently, identify its Pod UID,
node InternalIP, and container name with
`kubectl -n istio-system get pod POD -o json` and
`kubectl get node NODE -o json`. Use authenticated Talos access to list
`/var/log/pods/istio-system_<pod>_<uid>/<container>/` on that node:

```sh
talosctl --endpoints 10.1.0.199 --nodes NODE_INTERNAL_IP ls POD_LOG_DIRECTORY
talosctl --endpoints 10.1.0.199 --nodes NODE_INTERNAL_IP read ROTATED_LOG_PATH > "$ambient_logs/rotated.log"
```

Replace the uppercase placeholders with the observed values. Preserve distinct
local filenames for each Pod/rotation; decompress `.gz` files before inspection.
If a container restarted, include its previous logs. Require a complete retained
file chain covering the observation window on every node. Missing older files
leave the log gate unverified even if current readiness is healthy.

Search the collected, uncompressed logs for readiness failures and the observed
IPv6 bind/route signatures using the same captured endpoint:

```sh
python3 scripts/istio-ambient-log-check.py \
  --window-end "$ambient_window_end" "$ambient_logs"
```

Exit `0` means no in-window signatures; `1` means a matching failure; `2` means
invalid or incomplete input. The helper checks `(end - 24h, end]`, matching
Prometheus range boundaries, with nanosecond precision. It accepts UTC `Z`
timestamps from `kubectl logs --timestamps` and complete CRI `F` records from
Talos. Malformed timestamps, partial CRI `P` records, unreadable/empty files,
compressed files, symlinks, nested directories, and an empty inventory fail
closed. Keep only the uncompressed log files in this private directory.

Older and future signatures are excluded; every input record must still parse.
Output contains only the window and aggregate counts, never raw log messages.
This signature check does not establish Pod identity or retained rotation
coverage: the preceding gates remain required. Record the observation window
and aggregate verdicts; never commit raw logs or substitute a shorter window
for this recovery gate.

## Policy Bot Checks

Repository-local `.policy.yml` changes need Policy Bot validation, not just YAML
parsing:

```sh
policy-bot validate -p .policy.yml
curl -sS --fail-with-body https://policy-bot.stinkyboi.com/api/validate -T .policy.yml
```

Use the live endpoint when the local binary and Docker validator are
unavailable.

## Terragrunt Checks

Generate explicit stack units before focused validation:

```sh
cd IaC
terragrunt stack generate
```

Focused unit validation:

```sh
cd IaC/live/<stack>/<unit>
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable validate -no-color
terragrunt --log-disable plan -no-color
```

Explicit stack validation:

```sh
cd IaC
terragrunt stack run plan
```

The pull request workflow renders temporary Terragrunt plans to policy JSON and
runs Terraform-plan Conftest policy during `scripts/ci/terragrunt-plan.sh`. It
then runs `scripts/ci/conftest-policies.sh` for static YAML policy checks. Plan
details and live command output are withheld from the public PR and Actions
logs. Run the same order locally when reproducing a failure.

CI plan and apply scripts call `terragrunt stack generate` before filtering
units. When `IaC/terragrunt.stack.hcl`, `IaC/.catalog`, or `IaC/modules`
changes, the scripts plan or apply the matching generated unit groups instead
of relying on `--filter-affected` against ignored generated `terragrunt.hcl`
files. Stack, catalog, module, shared root/provider, and tracked generated-group
changes such as provider locks use the local `*` because each command runs from
its generated-unit root. Plan-only toolchain, Terraform-policy, and execution-
script changes also refresh every plan without widening production apply scope.
Affected-only runs combine the repository-relative group with the Git selector
so Terragrunt cannot queue another unit group. Intentional operator plans use
mode `0700` temporary directories. CI may save plans in generated unit caches
for exact apply and policy checks; its scripts use `umask 077` and delete those
files on exit. Normal local `terragrunt plan` commands do not write plan
artifacts into generated caches.
Production Argo CD Application registration saves each affected plan, evaluates
the Terraform policy JSON, rejects manifest replacement/deletion, then applies
that exact plan. A protected manual dispatch may set one exact `argocd_app` unit
name to reconcile committed desired state without widening the run to its group
or running any unrelated production apply phase. Manual production and
diagnostic dispatches reject every ref except `refs/heads/main`; the production
environment independently limits deployments to the `main` branch.
Deleted-unit handling compares tracked units and explicit-stack paths at
the base and head revisions, so a catalog migration at the same path is not a
destroy while removing a stack block still retires its state. The production
Azure credential gate compares AzureAD unit sources and stack blocks plus the
normalized shared root source they consume. It ignores only the
forbidden legacy root plan-output directive; every other root source change
fails closed. Unrelated stack changes do not require Azure credentials.

Production applies resolve their affected-unit base from the newest successful
historical push apply or full dispatch. Full runs are named `Full @ <sha>`;
targeted runs are named `Targeted <app> @ <sha>` and never advance that
checkpoint. A missing, unreachable, or non-ancestor result fails closed so an
apply cannot become the new successful checkpoint while skipping an unknown
deleted-unit range. Manual-dispatch secret scans cover `HEAD^..HEAD`; the
working-tree Gitleaks scan still covers the complete checkout.

GitHub-hosted live jobs depend on the Octelium clientless Kubernetes route. If
that route is the failed dependency, restore reviewed
`IaC/live/kubernetes-node-labels` state from a trusted LAN machine with a direct
`https://10.1.0.199:6443` kubeconfig, shared-backend AWS credentials, a saved
Terragrunt plan, and the Terraform-plan Conftest gate documented in
`docs/ci-cd.md`. No repository kubeconfig secret is part of that recovery path.

The trusted GitHub Actions PR plan job is serialized with a shared concurrency
group because it reads the same OpenTofu S3 backend state across pull requests.
Do not treat a queued PR plan as unhealthy; it is waiting for the live-state
lock lane. Same-PR replacement runs also queue instead of canceling in-progress
plans, because interrupting OpenTofu while it holds an S3 backend lock can leave
a stale lock that blocks later plans.

## Live Rollout Rule

Do not mutate live cluster, Talos, cloud, Argo CD, or secret-manager state until
the relevant validation has passed or the unavailable validation is recorded
with the risk. Desired state must be represented in the repo before applying it.

## Source Files

- `docs/validation-runbook.md`
- `.agents/skills/terragrunt-workflows/SKILL.md`

## OpenClaw doctor state gate

The static gate permits one exact noninteractive pinned doctor repair after
backup verification. Bootstrap tests require configuration restoration on
success and failure, plus session preservation and config validation before
the separate completion marker. A private config snapshot also repairs an
interrupted doctor before the next bootstrap applies desired configuration;
generic doctor changes must not persist unrelated skill-policy rewrites.

The one-time doctor process has a ten-minute timeout and 30-second kill grace
period. Timeout is tested as a failed migration, with config restored and no
completion marker. This bounds the previously observed NFS session scan.

### Post-start session lifecycle

The pre-import identity inventory is a migration gate, not an immutable runtime
inventory. OpenClaw 2026.8.2 replaces legacy managed Memory Dreaming Promotion
jobs with declaration-keyed jobs; removing the old job also removes its base
cron session. A later exact-key comparison can therefore report an intentional
missing legacy entry after the migration itself passed.

Before classifying an absent entry as data loss, check its job ownership, the
replacement declaration, retained migration reports, and backup. Do not relax
the bootstrap preservation gate or recreate retired sessions manually. Keep
gateway readiness, channel authentication, and backup retention as separate
acceptance checks.

Source: pinned upstream
[managed dreaming reconciliation](https://github.com/openclaw/openclaw/blob/v2026.8.2/extensions/memory-core/src/dreaming.ts),
[cron mutations](https://github.com/openclaw/openclaw/blob/v2026.8.2/src/cron/service/ops-mutations.ts),
and [base-session retirement](https://github.com/openclaw/openclaw/blob/v2026.8.2/src/cron/session-reaper.ts).
