#!/usr/bin/env bash
set -euo pipefail

# Declaration inventory only: no state, cluster discovery, hook execution or plugins.
# The caller owns fresh source copies and the initially empty, per-run shared cache.
die() {
  echo "Helm inventory: $*" >&2
  exit 1
}

local_path() {
  local root="$1" relative="$2" resolved
  [[ "$relative" =~ ^[a-zA-Z0-9_.-]+(/[a-zA-Z0-9_.-]+)*$ && "/$relative/" != *'/../'* ]] || die "unsupported local path: $relative"
  resolved="$(realpath "$root/$relative")" || die "missing path: $relative"
  [[ "$resolved" == "$root/"* && -e "$resolved" ]] || die "path escapes its source: $relative"
  printf '%s\n' "$resolved"
}

isolated_helm() {
  env -i PATH="$PATH" HELM_PLUGINS="$cache/empty" DOCKER_CONFIG="$cache/empty" \
    helm --kubeconfig /dev/null --registry-config "$cache/empty/registry.json" \
    --repository-config "$cache/empty/repositories.yaml" --repository-cache "$cache/indexes" "$@"
}

isolated_git() {
  env -i PATH="$PATH" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 \
    git -c credential.helper= -c core.hooksPath=/dev/null -c core.askPass=/bin/false \
    -c protocol.allow=never -c protocol.https.allow=always "$@"
}

stamp_namespace() {
  [[ "$1" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || die "invalid inventory namespace"
  # Context for image extraction only; this output must never be applied.
  yq 'select(. != null) | .metadata.annotations."homelab.stuhlmuller.dev/inventory-namespace" = "'"$1"'"' "$2"
}

fetch_chart() {
  local source="$1" repo chart revision subpath key directory archive
  repo="$(jq -r '.repoURL' <<<"$source")"
  chart="$(jq -r '.chart // ""' <<<"$source")"
  revision="$(jq -r '.targetRevision' <<<"$source")"
  subpath="$(jq -r '.path // ""' <<<"$source")"
  [[ -z "$chart" ]] || subpath="" # Remote chart identity is repo/chart/version, not Argo's normalized path.
  key="$(printf '%s\n' "$repo" "$chart" "$revision" "$subpath" | sha256sum | cut -d ' ' -f 1)" || die "chart cache key failed"
  directory="$cache/charts/$key"
  mkdir -p "$directory" || die "chart cache unavailable"
  if [[ -z "$chart" ]]; then
    [[ "$repo" == https://github.com/rancher/local-path-provisioner.git && "$revision" =~ ^[0-9a-f]{40}$ ]] || die "unsupported Git chart or mutable revision"
    if [[ ! -f "$directory/ready" ]]; then
      isolated_git init --bare --quiet "$directory/git" >&2 || die "Git chart initialization failed"
      isolated_git -C "$directory/git" fetch --quiet --depth=1 --no-tags "$repo" "$revision" >&2 || die "Git chart fetch failed"
      [[ "$(isolated_git -C "$directory/git" rev-parse FETCH_HEAD)" == "$revision" ]] || die "Git chart revision mismatch"
      # No checkout: tracked attributes cannot invoke filters or hooks.
      isolated_git -C "$directory/git" archive "$revision" >"$directory/source.tar" || die "Git chart archive failed"
      mkdir -p "$directory/source" || die "Git chart destination unavailable"
      tar -xf "$directory/source.tar" -C "$directory/source" || die "Git chart extraction failed"
      [[ -z "$(find "$directory/source" -type l -print -quit)" ]] || die "Git chart contains unsupported symlinks"
      local_path "$directory/source" "$subpath/Chart.yaml" >/dev/null || die "Git chart is missing"
      touch "$directory/ready" || die "Git chart cache completion failed"
    fi
    echo "Chart bytes $(sha256sum "$directory/source.tar")" >&2
    local_path "$directory/source" "$subpath"
  else
    [[ "$chart" =~ ^[a-z0-9][a-z0-9-]*$ && "$revision" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+([-+][a-zA-Z0-9.-]+)?$ ]] || die "unsupported chart name or non-exact version"
    [[ "$repo" =~ ^(https://|oci://)?[a-zA-Z0-9.-]+\.[a-zA-Z]+(/[a-zA-Z0-9_.-]+)*/?$ ]] || die "unsupported public chart repository"
    if [[ ! -f "$directory/chart.tgz" ]]; then
      if [[ "$repo" == https://* ]]; then
        isolated_helm pull --repo "$repo" --version "$revision" --destination "$directory" -- "$chart" >&2 || die "public Helm chart pull failed"
      else
        isolated_helm pull --version "$revision" --destination "$directory" -- "oci://${repo#oci://}/$chart" >&2 || die "public OCI chart pull failed"
      fi
      archive="$(find "$directory" -maxdepth 1 -type f -name '*.tgz')"
      [[ -n "$archive" && "$archive" != *$'\n'* ]] || die "expected one chart archive"
      mv "$archive" "$directory/chart.tgz" || die "chart cache publication failed"
    fi
    echo "Chart bytes $(sha256sum "$directory/chart.tgz")" >&2
    printf '%s\n' "$directory/chart.tgz"
  fi
}

render_record() {
  local record="$1" source release namespace kube_version chart file entry name value index=0
  local args=(template --dry-run=client --include-crds)
  jq -e '
    def name: type == "string" and test("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$");
    . as $r | (.source.helm // {}) as $h |
    ($r.source | (has("kustomize") or has("directory") or has("ref")) | not) and
    ($r.namespace | name and length <= 63) and
    (($h.releaseName // $r.name) | name and length <= 53) and
    (if $h | has("releaseName") then $h.releaseName | name else true end) and
    (($h | keys) - ["releaseName", "valueFiles", "values", "valuesObject", "parameters", "skipSchemaValidation", "kubeVersion"] | length == 0) and
    (if $h | has("valueFiles") then $h.valueFiles | type == "array" else true end) and
    ($h.valueFiles // [] | type == "array" and all(.[]; type == "string" and startswith("$values/"))) and
    (if $h | has("values") then $h.values | type == "string" else true end) and
    (if $h | has("valuesObject") then $h.valuesObject | type == "object" else true end) and
    (if $h | has("skipSchemaValidation") then $h.skipSchemaValidation | type == "boolean" else true end) and
    (if $h | has("kubeVersion") then $h.kubeVersion | type == "string" else true end) and
    ($h.kubeVersion // "1.34.1" | type == "string" and test("^[0-9]+\\.[0-9]+\\.[0-9]+$")) and
    (if $r | has("values") then $r.values | type == "array" and all(.[]; type == "string") else true end) and
    (if $h | has("parameters") then $h.parameters | type == "array" else true end) and
    ($h.parameters // [] | type == "array" and all(.[];
      (keys - ["name", "value", "forceString"] | length == 0) and
      (.name | type == "string" and test("^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$")) and
      (.value | type == "string" and (test("[[:cntrl:],{}\\\\$]") | not)) and
      (if has("forceString") then .forceString | type == "boolean" else true end)) and
      (map(.name) | length == (unique | length)))
  ' <<<"$record" >/dev/null || die "unsupported Helm options or argument shape"
  source="$(jq -c '.source' <<<"$record")"
  release="$(jq -r '.source.helm.releaseName // .name' <<<"$record")"
  namespace="$(jq -r '.namespace' <<<"$record")"
  kube_version="$(jq -r '.source.helm.kubeVersion // "1.34.1"' <<<"$record")"
  chart="$(fetch_chart "$source")" || die "chart acquisition failed"
  args+=(--namespace "$namespace" --kube-version "$kube_version")
  [[ "$(jq -r '.source.helm.skipSchemaValidation // false' <<<"$record")" != true ]] || args+=(--skip-schema-validation)
  jq -c '.source.helm.valueFiles // [] | .[]' <<<"$record" >"$work/value-files.jsonl"
  while IFS= read -r entry; do
    jq -e '[.refs[]? | select(.ref == "values")] | length == 1 and
      (.[0] | .repoURL == "https://github.com/Stuhlmuller/homelab.git" and .targetRevision == "main" and (.path // ".") == ".")' <<<"$record" >/dev/null || die "unbound or unsupported values reference"
    file="$(jq -r '.' <<<"$entry")"
    file="$(local_path "$tree" "${file#\$values/}")" || die "invalid values file"
    [[ -f "$file" ]] || die "values reference is not a file"
    args+=(-f "$file")
  done <"$work/value-files.jsonl"
  jq -c '.values // [] | .[]' <<<"$record" >"$work/inline-values.jsonl"
  while IFS= read -r entry; do
    file="$work/values-$index.yaml"
    jq -r '.' <<<"$entry" >"$file"
    args+=(-f "$file")
    index=$((index + 1))
  done <"$work/inline-values.jsonl"
  # Argo CD ignores values entirely when valuesObject is present.
  if jq -e '.source.helm | has("valuesObject")' <<<"$record" >/dev/null; then
    jq '.source.helm.valuesObject' <<<"$record" >"$work/override.yaml"
    args+=(-f "$work/override.yaml")
  elif jq -e '.source.helm | has("values")' <<<"$record" >/dev/null; then
    jq -r '.source.helm.values' <<<"$record" >"$work/override.yaml"
    args+=(-f "$work/override.yaml")
  fi
  jq -c '.source.helm.parameters // [] | .[]' <<<"$record" >"$work/parameters.jsonl"
  while IFS= read -r entry; do
    name="$(jq -r '.name' <<<"$entry")"
    value="$(jq -r '.value' <<<"$entry")"
    if [[ "$(jq -r '.forceString // false' <<<"$entry")" == true ]]; then
      args+=(--set-string "$name=$value")
    else
      args+=(--set "$name=$value")
    fi
  done <"$work/parameters.jsonl"
  echo "Rendering $release in $namespace; offline Kubernetes $kube_version (not live capabilities)" >&2
  # Includes hook YAML without executing hooks. Missing chart dependencies fail;
  # never use dependency-update, which could resolve a different dependency set.
  isolated_helm "${args[@]}" -- "$release" "$chart" >"$work/chart.yaml" || die "Helm rendering failed: $release"
  yq -o=json -I=0 'select(.apiVersion == "argoproj.io/v1alpha1" and .kind == "Application")' "$work/chart.yaml" |
    jq -se 'length == 0' >/dev/null || die "Helm-generated Applications require explicit inventory support"
  stamp_namespace "$namespace" "$work/chart.yaml"
  printf '\n---\n'
}

# The queue deliberately grows while reading; each Kustomize path is visited once.
# shellcheck disable=SC2094
main() {
  (($# == 2)) || die "usage: $0 <fresh-source-tree> <shared-empty-cache-dir> | --self-check"
  tree="$(realpath "$1")"
  cache="$(realpath "$2")"
  [[ -f "$tree/IaC/terragrunt.stack.hcl" && -d "$cache" && "$cache" != / && ! -e "$tree/.git" && "$cache" != "$tree" && "$cache" != "$tree/"* ]] || die "expected fresh source and separate cache directories"
  [[ -z "$(find "$tree" -type l -print -quit)" ]] || die "source symlinks are unsupported"
  [[ -z "$(find "$tree/IaC" -path '*/.catalog' -prune -o -name terragrunt.hcl -print)" ]] || die "source contains stale generated units"
  work="$(mktemp -d "$cache/render.XXXXXX")"
  mkdir -p "$cache/empty" "$cache/indexes" "$cache/charts"
  env -i PATH="$PATH" terragrunt --log-disable --working-dir "$tree/IaC" stack generate >&2
  env -i PATH="$PATH" terragrunt --log-disable --working-dir "$tree/IaC/live/argocd-apps" \
    render --all --json --write=false --parallelism 1 --no-stack-generate --no-filters-file \
    --no-auto-init --tf-path /usr/bin/false >"$work/units.jsonl"
  jq -c '.inputs.manifest' "$work/units.jsonl" >"$work/apps.jsonl"
  [[ -s "$work/apps.jsonl" ]] || die "empty Application inventory"
  env -i PATH="$PATH" terragrunt --log-disable --working-dir "$tree/IaC/bootstrap/argocd" \
    render --json --write=false --no-stack-generate --no-filters-file --no-auto-init --tf-path /usr/bin/false >"$work/bootstrap.json"
  local app source path key record bootstrap_app
  bootstrap_app="$(jq -er '.locals.self_management_application_manifest | select(type == "string")' "$work/bootstrap.json")"
  [[ "$bootstrap_app" == "$tree/"* ]] || die "bootstrap Application path is outside its source"
  bootstrap_app="$(realpath "$bootstrap_app")"
  [[ "$bootstrap_app" == "$tree/"* && -f "$bootstrap_app" ]] || die "bootstrap Application path escapes its source"
  yq -o=json -I=0 '.' "$bootstrap_app" >>"$work/apps.jsonl"
  # Process nested Applications from their effective Kustomize output. A source
  # path is rendered once per tree; newly found children join the same queue.
  while IFS= read -r app; do
    jq -e '.apiVersion == "argoproj.io/v1alpha1" and .kind == "Application"' <<<"$app" >/dev/null || die "invalid Application inventory"
    jq -c 'if (.spec.sources // [] | length) > 0 then .spec.sources[] else .spec.source end' <<<"$app" >"$work/sources.jsonl"
    while IFS= read -r source; do
      jq -e 'type == "object" and (keys - ["repoURL", "targetRevision", "chart", "path", "helm", "ref", "directory", "kustomize"] | length == 0)' <<<"$source" >/dev/null || die "unsupported Application source"
      if jq -e 'has("chart") or has("helm")' <<<"$source" >/dev/null; then
        record="$(jq -cn --argjson app "$app" --argjson source "$source" '{name:$app.metadata.name,namespace:$app.spec.destination.namespace,source:$source,refs:($app.spec.sources // [])}')"
        render_record "$record"
      elif jq -e 'has("ref")' <<<"$source" >/dev/null; then
        jq -e '.ref == "values" and .repoURL == "https://github.com/Stuhlmuller/homelab.git" and .targetRevision == "main" and (.path // ".") == "." and .directory == {include:".argocd-values-ref-placeholder.yaml"}' <<<"$source" >/dev/null || die "unsupported reference source"
      else
        jq -e '.repoURL == "https://github.com/Stuhlmuller/homelab.git" and .targetRevision == "main" and (.kustomize // {}) == {} and (has("directory") | not)' <<<"$source" >/dev/null || die "unsupported generated source"
        path="$(local_path "$tree" "$(jq -r '.path' <<<"$source")")" || die "invalid Kustomize path"
        key="$(printf '%s\n' "$path" "$(jq -r '.spec.destination.namespace' <<<"$app")" | sha256sum | cut -d ' ' -f 1)"
        if [[ ! -f "$work/kustomize-$key.yaml" ]]; then
          env -i PATH="$PATH" kubectl --kubeconfig /dev/null kustomize "$path" >"$work/kustomize-$key.yaml"
          yq -o=json -I=0 'select(.apiVersion == "argoproj.io/v1alpha1" and .kind == "Application")' "$work/kustomize-$key.yaml" >>"$work/apps.jsonl"
          stamp_namespace "$(jq -r '.spec.destination.namespace' <<<"$app")" "$work/kustomize-$key.yaml"
          printf '\n---\n'
        fi
      fi
    done <"$work/sources.jsonl"
  done <"$work/apps.jsonl"
  jq -e '.inputs | (keys - ["name","namespace","repository","chart","chart_version","values","create_namespace","wait","wait_for_jobs","timeout","project_name","tags","aws_region","kms_key_id","kms_key_spec","kms_region"] | length == 0)' "$work/bootstrap.json" >/dev/null || die "unsupported bootstrap Helm inputs"
  record="$(jq -c '.inputs | {name,namespace,values,source:{repoURL:.repository,chart,targetRevision:.chart_version,helm:{}}}' "$work/bootstrap.json")"
  render_record "$record"
}

self_check() (
  cache="$(realpath "$(mktemp -d)")"
  trap '[[ ! -d "$cache" ]] || rm -rf -- "$cache"' EXIT
  tree="$cache/tree"
  work="$cache/work"
  mkdir -p "$tree" "$work" "$cache/empty" "$cache/indexes" "$cache/fixture/templates"
  printf 'apiVersion: v2\nname: fixture\nversion: 1.0.0\n' >"$cache/fixture/Chart.yaml"
  printf '%s\n' 'apiVersion: v1' 'kind: ConfigMap' 'metadata:' '  name: {{ .Release.Name }}' '  namespace: {{ .Release.Namespace }}' 'data:' '  image: {{ .Values.image | quote }}' '  winner: {{ .Values.winner | quote }}' '  kind: {{ kindOf .Values.flag | quote }}' '  ignored: {{ .Values.ignored | default "absent" | quote }}' >"$cache/fixture/templates/test.yaml"
  printf 'image: first\nwinner: first\n' >"$tree/first.yaml"
  printf 'image: second\nwinner: second\n' >"$tree/second.yaml"
  isolated_helm package --destination "$cache" -- "$cache/fixture" >&2
  (
    isolated_helm() {
      while (($# > 1)); do
        if [[ "$1" == --destination ]]; then
          cp "$cache/fixture-1.0.0.tgz" "$2/fixture-1.0.0.tgz"
          printf '.\n' >>"$cache/pulls"
          return
        fi
        shift
      done
      return 1
    }
    first="$(fetch_chart '{"repoURL":"https://example.com/charts","chart":"fixture","targetRevision":"1.0.0","path":"."}')"
    second="$(fetch_chart '{"repoURL":"https://example.com/charts","chart":"fixture","targetRevision":"1.0.0"}')"
    [[ "$first" == "$second" && "$(wc -l <"$cache/pulls" | tr -d ' ')" == 1 ]]
  ) || die "chart cache reuse self-check failed"
  if (fetch_chart '{"repoURL":"https://github.com/rancher/local-path-provisioner.git","targetRevision":"main","path":"chart"}') >/dev/null 2>&1; then die "self-check accepted a mutable Git revision"; fi
  fetch_chart() { printf '%s\n' "$cache/fixture"; }
  local record rendered invalid
  # shellcheck disable=SC2016
  record='{"name":"fixture","namespace":"test","refs":[{"ref":"values","repoURL":"https://github.com/Stuhlmuller/homelab.git","targetRevision":"main"}],"source":{"helm":{"valueFiles":["$values/first.yaml","$values/second.yaml"],"values":"ignored: present","valuesObject":{"image":"object"},"parameters":[{"name":"image","value":"parameter"},{"name":"flag","value":"false","forceString":true}]}}}'
  rendered="$(render_record "$record")" || die "self-check render failed"
  yq -o=json 'select(.kind == "ConfigMap")' <<<"$rendered" | jq -e '.metadata.name == "fixture" and .metadata.namespace == "test" and .metadata.annotations["homelab.stuhlmuller.dev/inventory-namespace"] == "test" and .data == {image:"parameter",winner:"second",kind:"string",ignored:"absent"}' >/dev/null
  rendered="$(render_record "$(jq -c '.values=["image: first\nwinner: first", "image: last\nwinner: last"] | .source.helm={parameters:[{name:"flag",value:"false"}]}' <<<"$record")")" || die "bootstrap values self-check failed"
  yq -o=json 'select(.kind == "ConfigMap")' <<<"$rendered" | jq -e '.data.image == "last" and .data.winner == "last" and .data.kind == "bool"' >/dev/null
  # shellcheck disable=SC2016
  for invalid in \
    '.source.helm.postRenderer="/bin/false"' \
    '.source.helm.releaseName="--bad"' \
    '.source.helm.valueFiles=["https://example.com/values.yaml"]' \
    '.source.helm.valueFiles=["$values/../outside.yaml"]' \
    '.source.helm.valueFiles=["$values/*.yaml"]' \
    '.refs[0].repoURL="https://example.com/other.git"' \
    '.source.helm.parameters[0].value="one,two=three"'; do
    if (render_record "$(jq -c "$invalid" <<<"$record")") >/dev/null 2>&1; then
      die "self-check accepted unsupported input: $invalid"
    fi
  done
  ln -s /etc/hosts "$tree/outside.yaml"
  if (local_path "$tree" outside.yaml) >/dev/null 2>&1; then die "self-check accepted a path escape"; fi
  if (
    isolated_helm() { return 42; }
    render_record "$record"
  ) >/dev/null 2>&1; then die "self-check ignored a Helm failure"; fi
  echo "Helm renderer self-check passed" >&2
)

if [[ "${1:-}" == --self-check ]]; then
  (($# == 1)) || die "--self-check takes no arguments"
  self_check
else
  main "$@"
fi
