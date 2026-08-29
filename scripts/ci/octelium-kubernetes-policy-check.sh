#!/usr/bin/env bash
set -euo pipefail

catalog="${1:-docs/examples/octelium/homelab-services.yaml}"

# Octelium v0.35 parses these Kubernetes request fields here:
# https://github.com/octelium/octelium/blob/v0.35.0/cluster/vigil/vigil/modes/httpg/httputils/k8s.go
policy="$({ yq ea -o=json -I=0 '[.]' "$catalog"; } | jq -ce '
  [.[] | select(
    .kind == "Policy" and
    .metadata.name == "homelab-private-kubernetes-access"
  )] |
  if length == 1 then .[0] else error("expected exactly one private Kubernetes Policy") end
')"

jq -e '
  .spec == {
    "attrs": {
      "cordiumDiscoveryPaths": ["/api", "/api/v1", "/apis", "/apis/apps/v1", "/apis/batch/v1"],
      "cordiumCoreResources": ["events", "pods", "services"],
      "cordiumAppsResources": ["daemonsets", "deployments", "replicasets", "statefulsets"],
      "cordiumBatchResources": ["cronjobs", "jobs"]
    },
    "rules": [
      {
        "name": "cordium-sensitive-read-deny",
        "effect": "DENY",
        "condition": {"all": {"of": [
          {"match": "ctx.user.metadata.name == \"homelab-cordium-user\""},
          {"match": "ctx.user.spec.type == \"HUMAN\""},
          {"match": "ctx.session.status.type == \"CLIENT\""},
          {"match": "ctx.service.metadata.name == \"kubernetes-api.homelab\""},
          {"match": "ctx.service.spec.mode == \"KUBERNETES\""},
          {"any": {"of": [
            {"match": "ctx.request.kubernetes.resource in [\"secrets\", \"configmaps\", \"serviceaccounts\", \"tokenreviews\", \"subjectaccessreviews\", \"selfsubjectaccessreviews\", \"localsubjectaccessreviews\", \"selfsubjectrulesreviews\"]"},
            {"match": "ctx.request.kubernetes.subresource in [\"proxy\", \"log\", \"exec\", \"attach\", \"portforward\", \"ephemeralcontainers\", \"token\"]"}
          ]}}
        ]}}
      },
      {
        "name": "operator-client",
        "effect": "ALLOW",
        "condition": {"all": {"of": [
          {"match": "ctx.user.spec.type == \"HUMAN\""},
          {"match": "ctx.session.status.type == \"CLIENT\""},
          {"match": "ctx.service.metadata.name == \"kubernetes-api.homelab\""},
          {"match": "ctx.service.spec.mode == \"KUBERNETES\""},
          {"match": "ctx.user.metadata.name == \"homelab-owner\""}
        ]}}
      },
      {
        "name": "cordium-read-only-resources",
        "effect": "ALLOW",
        "condition": {"all": {"of": [
          {"match": "ctx.user.spec.type == \"HUMAN\""},
          {"match": "ctx.session.status.type == \"CLIENT\""},
          {"match": "ctx.service.metadata.name == \"kubernetes-api.homelab\""},
          {"match": "ctx.service.spec.mode == \"KUBERNETES\""},
          {"match": "ctx.user.metadata.name == \"homelab-cordium-user\""},
          {"match": "ctx.request.kubernetes.http.method == \"GET\""},
          {"match": "ctx.request.kubernetes.verb in [\"get\", \"list\", \"watch\"]"},
          {"match": "has(ctx.request.kubernetes.namespace)"},
          {"match": "!has(ctx.request.kubernetes.subresource)"},
          {"any": {"of": [
            {"all": {"of": [
              {"match": "ctx.request.kubernetes.apiPrefix == \"api\""},
              {"match": "!has(ctx.request.kubernetes.apiGroup)"},
              {"match": "ctx.request.kubernetes.apiVersion == \"v1\""},
              {"match": "ctx.request.kubernetes.resource in attrs.cordiumCoreResources"}
            ]}},
            {"all": {"of": [
              {"match": "ctx.request.kubernetes.apiPrefix == \"apis\""},
              {"match": "ctx.request.kubernetes.apiGroup == \"apps\""},
              {"match": "ctx.request.kubernetes.apiVersion == \"v1\""},
              {"match": "ctx.request.kubernetes.resource in attrs.cordiumAppsResources"}
            ]}},
            {"all": {"of": [
              {"match": "ctx.request.kubernetes.apiPrefix == \"apis\""},
              {"match": "ctx.request.kubernetes.apiGroup == \"batch\""},
              {"match": "ctx.request.kubernetes.apiVersion == \"v1\""},
              {"match": "ctx.request.kubernetes.resource in attrs.cordiumBatchResources"}
            ]}}
          ]}}
        ]}}
      },
      {
        "name": "cordium-read-only-discovery",
        "effect": "ALLOW",
        "condition": {"all": {"of": [
          {"match": "ctx.user.spec.type == \"HUMAN\""},
          {"match": "ctx.session.status.type == \"CLIENT\""},
          {"match": "ctx.service.metadata.name == \"kubernetes-api.homelab\""},
          {"match": "ctx.service.spec.mode == \"KUBERNETES\""},
          {"match": "ctx.user.metadata.name == \"homelab-cordium-user\""},
          {"match": "ctx.request.kubernetes.http.method == \"GET\""},
          {"match": "ctx.request.kubernetes.verb == \"get\""},
          {"match": "!has(ctx.request.kubernetes.resource)"},
          {"match": "!has(ctx.request.kubernetes.subresource)"},
          {"match": "ctx.request.kubernetes.http.path in attrs.cordiumDiscoveryPaths"}
        ]}}
      }
    ]
  }
' >/dev/null <<<"$policy"

jq -e '
  .spec.attrs as $attrs |
  def member($items; $value): ($items | index($value)) != null;
  def request($overrides): {
    userName: "homelab-cordium-user",
    userType: "HUMAN",
    sessionType: "CLIENT",
    serviceName: "kubernetes-api.homelab",
    serviceMode: "KUBERNETES",
    httpMethod: "GET",
    verb: "list",
    apiPrefix: "api",
    apiVersion: "v1",
    namespace: "cordium",
    resource: "pods",
    path: "/api/v1/namespaces/cordium/pods"
  } + $overrides;
  def discovery($path; $apiPrefix):
    request({verb: "get", apiPrefix: $apiPrefix, path: $path}) |
    del(.apiGroup, .apiVersion, .namespace, .resource, .subresource);
  def cordiumAllows:
    .userName == "homelab-cordium-user" and
    .userType == "HUMAN" and
    .sessionType == "CLIENT" and
    .serviceName == "kubernetes-api.homelab" and
    .serviceMode == "KUBERNETES" and
    .httpMethod == "GET" and
    (
      (
        .verb == "get" and
        (has("resource") | not) and (has("subresource") | not) and
        member($attrs.cordiumDiscoveryPaths; .path)
      ) or
      (
        member(["get", "list", "watch"]; .verb) and
        has("namespace") and
        (has("subresource") | not) and
        (
          (.apiPrefix == "api" and (has("apiGroup") | not) and .apiVersion == "v1" and
            member($attrs.cordiumCoreResources; .resource)) or
          (.apiPrefix == "apis" and .apiGroup == "apps" and .apiVersion == "v1" and
            member($attrs.cordiumAppsResources; .resource)) or
          (.apiPrefix == "apis" and .apiGroup == "batch" and .apiVersion == "v1" and
            member($attrs.cordiumBatchResources; .resource))
        )
      )
    );
  [
    {name: "get pod", want: true, request: request({verb: "get"})},
    {name: "list service", want: true, request: request({resource: "services"})},
    {name: "watch event", want: true, request: request({verb: "watch", resource: "events"})},
    {name: "list deployment", want: true, request: request({apiPrefix: "apis", apiGroup: "apps", resource: "deployments"})},
    {name: "list daemonset", want: true, request: request({apiPrefix: "apis", apiGroup: "apps", resource: "daemonsets"})},
    {name: "list replicaset", want: true, request: request({apiPrefix: "apis", apiGroup: "apps", resource: "replicasets"})},
    {name: "list statefulset", want: true, request: request({apiPrefix: "apis", apiGroup: "apps", resource: "statefulsets"})},
    {name: "list job", want: true, request: request({apiPrefix: "apis", apiGroup: "batch", resource: "jobs"})},
    {name: "list cronjob", want: true, request: request({apiPrefix: "apis", apiGroup: "batch", resource: "cronjobs"})},
    {name: "discover core groups", want: true, request: discovery("/api"; "")},
    {name: "discover core v1", want: true, request: discovery("/api/v1"; "")},
    {name: "discover named groups", want: true, request: discovery("/apis"; "")},
    {name: "discover apps v1", want: true, request: discovery("/apis/apps/v1"; "apis")},
    {name: "discover batch v1", want: true, request: discovery("/apis/batch/v1"; "apis")},
    {name: "all namespaces", want: false, request: (request({}) | del(.namespace))},
    {name: "namespace", want: false, request: (request({resource: "namespaces"}) | del(.namespace))},
    {name: "secret", want: false, request: request({resource: "secrets"})},
    {name: "configmap", want: false, request: request({resource: "configmaps"})},
    {name: "endpoints", want: false, request: request({resource: "endpoints"})},
    {name: "endpoint slice", want: false, request: request({apiPrefix: "apis", apiGroup: "discovery.k8s.io", resource: "endpointslices"})},
    {name: "service account", want: false, request: request({resource: "serviceaccounts"})},
    {name: "node", want: false, request: (request({resource: "nodes"}) | del(.namespace))},
    {name: "persistent volume", want: false, request: (request({resource: "persistentvolumes"}) | del(.namespace))},
    {name: "RBAC role", want: false, request: request({apiPrefix: "apis", apiGroup: "rbac.authorization.k8s.io", resource: "roles"})},
    {name: "RBAC cluster role", want: false, request: (request({apiPrefix: "apis", apiGroup: "rbac.authorization.k8s.io", resource: "clusterroles"}) | del(.namespace))},
    {name: "CRD", want: false, request: (request({apiPrefix: "apis", apiGroup: "apiextensions.k8s.io", resource: "customresourcedefinitions"}) | del(.namespace))},
    {name: "custom resource", want: false, request: request({apiPrefix: "apis", apiGroup: "example.invalid", resource: "widgets"})},
    {name: "authorization review", want: false, request: (request({httpMethod: "POST", verb: "create", apiPrefix: "apis", apiGroup: "authorization.k8s.io", resource: "subjectaccessreviews"}) | del(.namespace))},
    {name: "pod log", want: false, request: request({verb: "get", subresource: "log"})},
    {name: "pod exec", want: false, request: request({httpMethod: "POST", verb: "create", subresource: "exec"})},
    {name: "pod attach", want: false, request: request({httpMethod: "POST", verb: "create", subresource: "attach"})},
    {name: "pod port-forward", want: false, request: request({httpMethod: "POST", verb: "create", subresource: "portforward"})},
    {name: "service proxy", want: false, request: request({verb: "get", resource: "services", subresource: "proxy"})},
    {name: "service-account token", want: false, request: request({httpMethod: "POST", verb: "create", resource: "serviceaccounts", subresource: "token"})},
    {name: "status subresource", want: false, request: request({verb: "get", subresource: "status"})},
    {name: "create", want: false, request: request({httpMethod: "POST", verb: "create"})},
    {name: "update", want: false, request: request({httpMethod: "PUT", verb: "update"})},
    {name: "patch", want: false, request: request({httpMethod: "PATCH", verb: "patch"})},
    {name: "delete", want: false, request: request({httpMethod: "DELETE", verb: "delete"})},
    {name: "future core resource", want: false, request: request({resource: "futurethings"})},
    {name: "future apps version", want: false, request: request({apiPrefix: "apis", apiGroup: "apps", apiVersion: "v2", resource: "deployments"})},
    {name: "metrics", want: false, request: discovery("/metrics"; "")},
    {name: "debug", want: false, request: discovery("/debug/pprof/"; "")},
    {name: "health", want: false, request: discovery("/readyz"; "")},
    {name: "OpenAPI", want: false, request: discovery("/openapi/v3"; "")},
    {name: "version", want: false, request: discovery("/version"; "")},
    {name: "POST discovery", want: false, request: (discovery("/api"; "") + {httpMethod: "POST", verb: "post"})},
    {name: "wrong user", want: false, request: request({userName: "someone-else"})},
    {name: "clientless session", want: false, request: request({sessionType: "CLIENTLESS"})},
    {name: "wrong service", want: false, request: request({serviceName: "kubernetes-api-ci.default"})}
  ] |
  map(select((.request | cordiumAllows) != .want)) |
  if length == 0 then true else error("policy boundary mismatch: " + (map(.name) | join(", "))) end
' >/dev/null <<<"$policy"

echo "Octelium Cordium Kubernetes policy boundary passed."
