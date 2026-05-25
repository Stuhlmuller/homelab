package main

import rego.v1

homelab_repo_urls := {
	"https://github.com/Stuhlmuller/homelab.git",
	"git@github.com:Stuhlmuller/homelab.git",
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

truthy(value) if {
	lower(sprintf("%v", [value])) == "true"
}
