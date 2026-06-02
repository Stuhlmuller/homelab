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

external_secret_allowed_prefixes := {
	"ai": {"/homelab/litellm/", "/homelab/openclaw/", "/homelab/grafana/openclaw-alert-hook-token"},
	"argocd": {"/homelab/argocd/", "/homelab/argocd-image-updater/"},
	"automation": {"/homelab/n8n/", "/homelab/policy-bot/"},
	"cert-manager": {"/homelab/cert-manager/"},
	"media": {"/homelab/deluge/", "/homelab/media-postgres/"},
	"monitoring": {"/homelab/grafana/"},
	"octelium-client": {"/homelab/octelium/"},
	"tailscale": {"/homelab/tailscale/"},
}

deny contains msg if {
	input.kind == "ExternalSecret"
	metadata := object.get(input, "metadata", {})
	namespace := object.get(metadata, "namespace", "default")
	allowed := external_secret_allowed_prefixes[namespace]
	item := object.get(object.get(input, "spec", {}), "data", [])[_]
	key := object.get(object.get(item, "remoteRef", {}), "key", "")
	key != ""
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

remote_ref_key_allowed(key, allowed) if {
	some prefix in allowed
	startswith(key, prefix)
}
