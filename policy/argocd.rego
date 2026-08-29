package main

import rego.v1

deny contains msg if {
	input.kind == "AppProject"
	object.get(object.get(input, "metadata", {}), "name", "") == "homelab-workloads"
	object.get(object.get(input, "spec", {}), "clusterResourceWhitelist", null) != []
	msg := "AppProject homelab-workloads must explicitly deny every cluster-scoped resource"
}

deny contains msg if {
	input.kind == "Application"
	some source in application_sources
	repo_url := object.get(source, "repoURL", "")
	git_source(source)
	not repo_url in homelab_repo_urls
	revision := object.get(source, "targetRevision", "")
	not regex.match("^[0-9a-f]{40}$", revision)
	name := object.get(object.get(input, "metadata", {}), "name", "<unknown>")
	msg := sprintf("Application %q external Git source must use an exact commit SHA", [name])
}

application_sources contains source if {
	source := object.get(object.get(input, "spec", {}), "source", {})
	object.get(source, "repoURL", "") != ""
}

application_sources contains source if {
	some source in object.get(object.get(input, "spec", {}), "sources", [])
}

git_source(source) if {
	object.get(source, "path", "") != ""
}

git_source(source) if {
	object.get(source, "ref", "") != ""
}
