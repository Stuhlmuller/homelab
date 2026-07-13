package main

import rego.v1

homelab_repo_urls := {
	"https://github.com/Stuhlmuller/homelab.git",
	"git@github.com:Stuhlmuller/homelab.git",
}

required_pod_security_labels := {
	"pod-security.kubernetes.io/enforce",
	"pod-security.kubernetes.io/enforce-version",
	"pod-security.kubernetes.io/audit",
	"pod-security.kubernetes.io/audit-version",
	"pod-security.kubernetes.io/warn",
	"pod-security.kubernetes.io/warn-version",
}

deny contains msg if {
	input.kind == "Secret"
	name := object.get(object.get(input, "metadata", {}), "name", "<unknown>")
	msg := sprintf("raw Kubernetes Secret %q must not be committed; use ExternalSecret, encrypted secret material, or a CI-injected secret path", [name])
}

deny contains msg if {
	input.kind == "Namespace"
	metadata := object.get(input, "metadata", {})
	labels := object.get(metadata, "labels", {})
	some key in required_pod_security_labels
	not has_nonempty_label(labels, key)
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("namespace %q must set %s", [name, key])
}

deny contains msg if {
	input.kind == "Namespace"
	metadata := object.get(input, "metadata", {})
	labels := object.get(metadata, "labels", {})
	object.get(labels, "pod-security.kubernetes.io/audit", "") != "restricted"
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("namespace %q must audit Pod Security violations at restricted", [name])
}

deny contains msg if {
	input.kind == "Namespace"
	metadata := object.get(input, "metadata", {})
	labels := object.get(metadata, "labels", {})
	object.get(labels, "pod-security.kubernetes.io/warn", "") != "restricted"
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("namespace %q must warn on Pod Security violations at restricted", [name])
}

deny contains msg if {
	input.kind == "Namespace"
	metadata := object.get(input, "metadata", {})
	labels := object.get(metadata, "labels", {})
	labels["pod-security.kubernetes.io/enforce"] == "privileged"
	annotations := object.get(metadata, "annotations", {})
	not has_nonempty_annotation(annotations, "homelab.rst.io/privileged-namespace-justification")
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("privileged namespace %q must document why privileged Pod Security is required", [name])
}

deny contains msg if {
	metadata := object.get(input, "metadata", {})
	annotations := object.get(metadata, "annotations", {})
	truthy(object.get(annotations, "homelab.rst.io/public-funnel", "false"))
	kind := object.get(input, "kind", "<unknown>")
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("%s %q enables Tailscale Funnel; external callbacks must use the Octelium public connector path instead", [kind, name])
}

deny contains msg if {
	metadata := object.get(input, "metadata", {})
	annotations := object.get(metadata, "annotations", {})
	truthy(object.get(annotations, "homelab.rst.io/public-callback", "false"))
	not truthy(object.get(annotations, "homelab.rst.io/public-callback-reviewed", "false"))
	kind := object.get(input, "kind", "<unknown>")
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("%s %q exposes an unauthenticated callback path without homelab.rst.io/public-callback-reviewed=true", [kind, name])
}

deny contains msg if {
	metadata := object.get(input, "metadata", {})
	annotations := object.get(metadata, "annotations", {})
	truthy(object.get(annotations, "homelab.rst.io/public-callback", "false"))
	not has_nonempty_annotation(annotations, "homelab.rst.io/public-callback-purpose")
	kind := object.get(input, "kind", "<unknown>")
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("%s %q exposes an unauthenticated callback path without homelab.rst.io/public-callback-purpose", [kind, name])
}

deny contains msg if {
	public_external_route
	not octelium_access_plane
	kind := object.get(input, "kind", "<unknown>")
	name := object.get(object.get(input, "metadata", {}), "name", "<unknown>")
	msg := sprintf("%s %q exposes a public route and must declare homelab.rst.io/access-plane=octelium", [kind, name])
}

deny contains msg if {
	input.kind == "Application"
	spec := object.get(input, "spec", {})
	source := object.get(spec, "source", {})
	source.repoURL in homelab_repo_urls
	object.get(source, "targetRevision", "") != "main"
	name := object.get(object.get(input, "metadata", {}), "name", "<unknown>")
	msg := sprintf("Application %q must target the homelab repository default branch main", [name])
}

deny contains msg if {
	input.kind == "Application"
	spec := object.get(input, "spec", {})
	sources := object.get(spec, "sources", [])
	some index
	source := sources[index]
	source.repoURL in homelab_repo_urls
	object.get(source, "targetRevision", "") != "main"
	name := object.get(object.get(input, "metadata", {}), "name", "<unknown>")
	msg := sprintf("Application %q source %d must target the homelab repository default branch main", [name, index])
}

has_nonempty_annotation(annotations, key) if {
	value := object.get(annotations, key, "")
	count(trim(value, " ")) > 0
}

has_nonempty_label(labels, key) if {
	value := object.get(labels, key, "")
	count(trim(value, " ")) > 0
}

truthy(value) if {
	lower(sprintf("%v", [value])) == "true"
}

octelium_access_plane if {
	annotations := object.get(object.get(input, "metadata", {}), "annotations", {})
	object.get(annotations, "homelab.rst.io/access-plane", "") == "octelium"
}

public_external_route if {
	input.kind == "VirtualService"
	host := object.get(object.get(input, "spec", {}), "hosts", [])[_]
	public_hostname(host)
}

public_external_route if {
	input.kind == "Gateway"
	server := object.get(object.get(input, "spec", {}), "servers", [])[_]
	host := object.get(server, "hosts", [])[_]
	public_hostname(host)
}

public_external_route if {
	input.kind == "Ingress"
	object.get(object.get(input, "spec", {}), "ingressClassName", "") == "tailscale"
}

public_external_route if {
	input.kind == "Ingress"
	object.get(object.get(input, "spec", {}), "ingressClassName", "") != "compass-discovery"
	host := ingress_hosts(input)[_]
	public_hostname(host)
}

public_hostname(host) if {
	clean := trim(lower(sprintf("%v", [host])), "*.")
	clean == "stinkyboi.com"
}

public_hostname(host) if {
	clean := trim(lower(sprintf("%v", [host])), "*.")
	endswith(clean, ".stinkyboi.com")
}

public_hostname(host) if {
	clean := trim(lower(sprintf("%v", [host])), "*.")
	endswith(clean, ".ts.net")
}

ingress_hosts(ingress) := hosts if {
	spec := object.get(ingress, "spec", {})
	rule_hosts := [host |
		rule := object.get(spec, "rules", [])[_]
		host := object.get(rule, "host", "")
		host != ""
	]
	tls_hosts := [host |
		tls := object.get(spec, "tls", [])[_]
		host := object.get(tls, "hosts", [])[_]
		host != ""
	]
	hosts := array.concat(rule_hosts, tls_hosts)
}

external_secret_allowed_prefixes := {
	"ai": {"/homelab/litellm/", "/homelab/openclaw/", "/homelab/grafana/openclaw-alert-hook-token"},
	"affine": {"/homelab/affine/"},
	"argocd": {"/homelab/argocd/", "/homelab/argocd-image-updater/"},
	"automation": {"/homelab/n8n/", "/homelab/policy-bot/"},
	"cert-manager": {"/homelab/cert-manager/"},
	"github-actions-runner": {"/homelab/github-actions-runner/"},
	"media": {"/homelab/deluge/", "/homelab/media-postgres/"},
	"monitoring": {"/homelab/grafana/"},
	"octelium-client": {"/homelab/octelium/"},
	"octelium-public": {"/homelab/octelium/"},
	"octelium-storage": {"/homelab/octelium/"},
	"tailscale": {"/homelab/tailscale/"},
}

deny contains msg if {
	input.kind == "ExternalSecret"
	metadata := object.get(input, "metadata", {})
	namespace := object.get(metadata, "namespace", "default")
	allowed := external_secret_allowed_prefixes[namespace]
	key := external_secret_remote_keys(input)[_]
	not remote_ref_key_allowed(key, allowed)
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("ExternalSecret %q in namespace %q references SSM key %q outside its allowed application prefixes", [name, namespace, key])
}

deny contains msg if {
	input.kind == "ExternalSecret"
	metadata := object.get(input, "metadata", {})
	namespace := object.get(metadata, "namespace", "default")
	not external_secret_allowed_prefixes[namespace]
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("ExternalSecret %q uses ClusterSecretStore in namespace %q without an approved SSM prefix policy", [name, namespace])
}

deny contains msg if {
	input.kind == "ExternalSecret"
	metadata := object.get(input, "metadata", {})
	item := object.get(object.get(input, "spec", {}), "dataFrom", [])[_]
	find := object.get(item, "find", {})
	count(find) > 0
	path := object.get(find, "path", "")
	count(trim(path, " ")) == 0
	name := object.get(metadata, "name", "<unknown>")
	namespace := object.get(metadata, "namespace", "default")
	msg := sprintf("ExternalSecret %q in namespace %q uses dataFrom.find without a scoped SSM path", [name, namespace])
}

remote_ref_key_allowed(key, allowed) if {
	some allowed_key in allowed
	endswith(allowed_key, "/")
	startswith(key, allowed_key)
}

remote_ref_key_allowed(key, allowed) if {
	some allowed_key in allowed
	not endswith(allowed_key, "/")
	key == allowed_key
}

external_secret_remote_keys(secret) := keys if {
	spec := object.get(secret, "spec", {})
	data_keys := [key |
		item := object.get(spec, "data", [])[_]
		key := object.get(object.get(item, "remoteRef", {}), "key", "")
		key != ""
	]
	extract_keys := [key |
		item := object.get(spec, "dataFrom", [])[_]
		key := object.get(object.get(item, "extract", {}), "key", "")
		key != ""
	]
	find_keys := [key |
		item := object.get(spec, "dataFrom", [])[_]
		key := object.get(object.get(item, "find", {}), "path", "")
		key != ""
	]
	keys := array.concat(array.concat(data_keys, extract_keys), find_keys)
}
