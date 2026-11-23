#!/usr/bin/env ruby
require "yaml"
require "open3"
require "tmpdir"

root = File.expand_path("../..", __dir__)
canary = "clusters/homelab/apps/traefik/canary"

def check(condition, message)
  raise message unless condition
end

render, stderr, status = Open3.capture3("kubectl", "kustomize", canary, chdir: root)
check(status.success?, "canary Kustomize render failed: #{stderr}")
objects = YAML.load_stream(render)
find = ->(kind) { objects.find { |item| item["kind"] == kind } }
pod = find.call("StatefulSet").fetch("spec").fetch("template")
spec = pod.fetch("spec")
containers = spec.fetch("containers").to_h { |c| [c.fetch("name"), c] }
traefik = containers.fetch("traefik")
tailscale = containers.fetch("tailscale")
labels = pod.fetch("metadata").fetch("labels")
selector = find.call("Service").fetch("spec").fetch("selector")
live_name = "traefik"

check(labels == selector, "headless Service must select only the canary Pod")
check(labels["app.kubernetes.io/name"] != live_name, "canary matches live Traefik Service name")
check(labels["app.kubernetes.io/instance"] != live_name, "canary matches live Traefik instance")
check(!labels.key?("app.kubernetes.io/controller"), "canary must not carry live controller label")
check(find.call("Service").fetch("spec").fetch("clusterIP") == "None", "canary Service must be headless")
check(find.call("Service").fetch("spec").fetch("ports").map { |p| p["port"] } == [9000], "canary Service exposes a route port")

live_kustomization = YAML.load_file(File.join(root, "clusters/homelab/apps/traefik/kustomization.yaml"))
check(live_kustomization.fetch("resources").none? { |r| r.include?("canary") }, "live Kustomization includes canary")
live_values = YAML.load_file(File.join(root, "clusters/homelab/apps/traefik/values.yaml"))
check(live_values.fetch("service").values.all? { |service| service["controller"] == "traefik" }, "live Service controller selectors changed")
%w[clusters/homelab/apps/traefik/values.yaml IaC/homelab/us-west-2/apps/traefik/stack.hcl].each do |path|
  check(!File.read(File.join(root, path)).include?("traefik-sidecar-canary"), "live source references canary: #{path}")
end
check(!File.read(File.join(root, "IaC/homelab/us-west-2/apps/traefik/stack.hcl")).include?("clusters/homelab/apps/traefik/canary"), "Argo registers canary path")

check(spec.fetch("automountServiceAccountToken") == false, "automatic ServiceAccount token mount enabled")
check(spec.fetch("serviceAccountName") == "traefik-sidecar-canary", "canary state RBAC shares live identity")
check(spec.fetch("nodeSelector").fetch("kubernetes.io/hostname") == "acer", "canary placement drifted from measured existing-node candidate")
check(find.call("ServiceAccount").fetch("automountServiceAccountToken") == false, "canary ServiceAccount automount enabled")
pod_security = spec.fetch("securityContext")
check(pod_security.fetch("runAsNonRoot") && pod_security.fetch("runAsUser") == 65532 && pod_security.fetch("runAsGroup") == 65532 && pod_security.fetch("fsGroup") == 65532 && pod_security.fetch("seccompProfile").fetch("type") == "RuntimeDefault", "restricted Pod security missing")
namespace = YAML.load_file(File.join(root, "clusters/homelab/apps/traefik/namespace.yaml"))
check(namespace.dig("metadata", "labels", "pod-security.kubernetes.io/enforce") == "restricted", "canary namespace permits privileged Pod security")
check(namespace.dig("metadata", "labels", "istio.io/dataplane-mode") == "ambient", "canary direct-ingress policy will not apply")
containers.each_value do |container|
  security = container.fetch("securityContext")
  check(security.fetch("allowPrivilegeEscalation") == false && security.fetch("readOnlyRootFilesystem"), "#{container['name']} security context weakened")
  check(security.fetch("capabilities").fetch("drop") == ["ALL"], "#{container['name']} keeps capabilities")
  check(container.fetch("image").match?(/@sha256:[0-9a-f]{64}\z/), "#{container['name']} image is not digest pinned")
  %w[requests limits].each do |bound|
    check(container.fetch("resources").fetch(bound).keys.sort == %w[cpu memory], "#{container['name']} #{bound} incomplete")
  end
end

args = traefik.fetch("args")
%w[web websecure funnel registry].each do |entrypoint|
  check(args.any? { |arg| arg.start_with?("--entrypoints.#{entrypoint}.address=127.0.0.1:") }, "#{entrypoint} listener is not loopback bound")
end
check(tailscale.fetch("args").include?("--tun=userspace-networking"), "Tailscale requires kernel networking")
check(tailscale.fetch("args").include?("--state=kube:traefik-sidecar-canary-state"), "durable state contract changed")
check(tailscale.fetch("image") == "harbor.stinkyboi.com/mirror/docker.io/tailscale/tailscale:v1.102.3@sha256:8c42c4574ab066384fcb72f69e086a2ff1dd3652eb6f56856cee34bcf0d2f680", "Tailscale image differs from the pinned Harbor mirror")

mounts = containers.transform_values { |c| c.fetch("volumeMounts").map { |v| v.fetch("name") } }
check((mounts.fetch("traefik") & %w[tailscale-api tailscale-auth tailscale-run tailscale-var]).empty?, "Traefik can mount Tailscale credentials")
check((%w[tailscale-api tailscale-auth] - mounts.fetch("tailscale")).empty?, "Tailscale credential mounts missing")
token_sources = spec.fetch("volumes").find { |v| v["name"] == "tailscale-api" }.fetch("projected").fetch("sources")
check(token_sources.any? { |source| source.key?("serviceAccountToken") }, "explicit Tailscale token missing")
check(!objects.any? { |item| item["kind"] == "Secret" }, "Argo must not own mutable Tailscale state")
route_map = objects.find { |item| item["kind"] == "ConfigMap" && item.dig("metadata", "name") == "traefik-sidecar-canary-routes" }
check(route_map, "canary route ConfigMap missing")
%w[routes.yaml tls.yaml].each do |file|
  source = File.binread(File.join(root, canary, file))
  check(source == File.binread(File.join(root, "clusters/homelab/apps/traefik", file)), "canary #{file} drifted from live route source")
  check(route_map.fetch("data").fetch(file) == source, "rendered canary #{file} differs from source")
end
check(spec.fetch("volumes").find { |v| v["name"] == "dynamic" }.fetch("projected").fetch("sources").first.fetch("configMap").fetch("name") == "traefik-sidecar-canary-routes", "canary mounts live route ConfigMap")

role = find.call("Role").fetch("rules")
check(role.any? { |rule| rule["verbs"] == ["create"] && !rule.key?("resourceNames") }, "create-only Secret rule missing")
check(role.any? { |rule| rule["verbs"].sort == %w[get patch update] && rule["resourceNames"] == ["traefik-sidecar-canary-state"] }, "state Secret access is not exact-name scoped")
check(role.flat_map { |rule| rule["verbs"] }.sort == %w[create get patch update], "state Role has unexpected verbs")
check(find.call("RoleBinding").fetch("subjects").map { |subject| subject["name"] } == ["traefik-sidecar-canary"], "state Role is granted to live Traefik")
policy = find.call("AuthorizationPolicy").fetch("spec")
check(policy.fetch("selector").fetch("matchLabels") == labels, "direct ingress DENY misses canary")
check(policy.fetch("action") == "DENY", "direct ingress policy does not deny")
check(policy.fetch("rules").first.fetch("to").first.fetch("operation").fetch("ports").sort == %w[80 443 8000 8080 8443 9443].sort, "direct ingress deny ports changed")
check(!objects.any? { |item| item["kind"] == "ExternalSecret" }, "unapproved canary ExternalSecret rendered")
auth = YAML.load_file(File.join(root, canary, "auth-externalsecret.yaml")).fetch("spec")
check(auth.fetch("target").fetch("name") == "traefik-sidecar-canary-auth", "auth Secret name changed")
check(auth.fetch("data").first.fetch("secretKey") == "auth-key" && auth.fetch("data").first.fetch("remoteRef").fetch("key") == "/homelab/tailscale/traefik-sidecar-canary-auth-key", "file-backed auth contract changed")

activation = File.read(File.join(root, canary, "activate.sh"))
check(activation.include?("--tcp=443 tcp://127.0.0.1:8443"), "Serve is not HTTPS-only raw TCP to loopback")
check(!activation.include?("--tcp=80"), "Serve exposes unreviewed HTTP port")
check(activation.index('"Running"') < activation.index("--auth-key=file:"), "persisted identity is not checked before auth key")
shell = ENV.fetch("PATH").split(File::PATH_SEPARATOR).map { |dir| File.join(dir, "sh") }.find { |path| File.executable?(path) }
check(shell, "test requires sh on PATH")

Dir.mktmpdir("tc-", "/tmp") do |dir|
  socket_path = File.join(dir, "tailscaled.sock")
  auth_path = File.join(dir, "auth-key")
  script = File.join(dir, "activate.sh")
  state = File.join(dir, "state.json")
  log = File.join(dir, "calls.log")
  bin = File.join(dir, "bin")
  Dir.mkdir(bin)
  File.write(File.join(bin, "tailscale"), <<~SH)
    #!#{shell}
    printf '%s\n' "$*" >> "$MOCK_LOG"
    case "$*" in
      *'status --json'*) cat "$MOCK_STATE" ;;
      *' up '*|*' up') printf '%s\n' '{"BackendState":"Running"}' > "$MOCK_STATE" ;;
    esac
  SH
  File.chmod(0755, File.join(bin, "tailscale"))
  File.write(script, activation.gsub("/run/tailscale/tailscaled.sock", socket_path).gsub("/var/run/secrets/tailscale-auth/auth-key", auth_path).gsub('test -S "$socket"', 'test -e "$socket"'))
  File.chmod(0755, script)
  File.write(socket_path, "mock socket")
  begin
    [{name: "restored", state: "Running", auth: false, expect_up: false},
     {name: "stopped", state: "Stopped", auth: false, expect_up: true},
     {name: "new", state: "NeedsLogin", auth: true, expect_up: true}].each do |scenario|
      File.write(state, %({"BackendState":"#{scenario[:state]}"}))
      File.write(log, "")
      if scenario[:auth]
        File.write(auth_path, "test-only")
      elsif File.exist?(auth_path)
        File.delete(auth_path)
      end
      env = {"PATH" => "#{bin}:#{ENV.fetch('PATH')}", "MOCK_LOG" => log, "MOCK_STATE" => state}
      _stdout, error, result = Open3.capture3(env, shell, script)
      check(result.success?, "#{scenario[:name]} startup failed: #{error}")
      calls = File.read(log)
      check(calls.include?("serve --yes --bg --tcp=443 tcp://127.0.0.1:8443"), "#{scenario[:name]} did not configure TCP Serve")
      check(calls.include?(" up ") == scenario[:expect_up], "#{scenario[:name]} used auth key incorrectly")
      if scenario[:expect_up]
        check(calls.include?("--hostname=homelab-ingress-canary --advertise-tags=tag:homelab-ingress-canary --accept-dns=false --netfilter-mode=off"), "#{scenario[:name]} lost non-default Tailscale settings")
        check(calls.include?("--auth-key=file:") == scenario[:auth], "#{scenario[:name]} used auth key incorrectly")
      end
    end
  end
end

puts "Traefik sidecar canary source is dormant and isolated"
