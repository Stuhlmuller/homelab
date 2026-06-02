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
	not truthy(object.get(annotations, "homelab.rst.io/public-funnel-reviewed", "false"))
	kind := object.get(input, "kind", "<unknown>")
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("%s %q enables Tailscale Funnel without homelab.rst.io/public-funnel-reviewed=true", [kind, name])
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

forbidden_public_funnel_prefixes := {
	"/webhook-test",
	"/webhook-test/",
	"/webhook-waiting",
	"/webhook-waiting/",
}

deny contains msg if {
	input.kind == "Ingress"
	metadata := object.get(input, "metadata", {})
	annotations := object.get(metadata, "annotations", {})
	truthy(object.get(annotations, "homelab.rst.io/public-funnel", "false"))
	rule := object.get(object.get(input, "spec", {}), "rules", [])[_]
	http := object.get(rule, "http", {})
	backend_path := object.get(http, "paths", [])[_]
	path := object.get(backend_path, "path", "")
	path in forbidden_public_funnel_prefixes
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("public Funnel Ingress %q must not expose non-production webhook path %q", [name, path])
}

deny contains msg if {
	input.kind == "VirtualService"
	metadata := object.get(input, "metadata", {})
	route := object.get(object.get(input, "spec", {}), "http", [])[_]
	match := object.get(route, "match", [])[_]
	object.get(match, "gateways", [])[_] == "istio-system/n8n-webhook-funnel"
	uri := object.get(match, "uri", {})
	path := object.get(uri, "exact", object.get(uri, "prefix", ""))
	path in forbidden_public_funnel_prefixes
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("VirtualService %q must not route non-production webhook path %q through the public n8n funnel", [name, path])
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
