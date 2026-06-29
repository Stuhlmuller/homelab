package main

import rego.v1

deny contains msg if {
	events := workflow_events
	has_event(events, "pull_request_target")
	name := object.get(input, "name", "<unnamed workflow>")
	msg := sprintf("workflow %q must not use pull_request_target for infrastructure checks", [name])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	uses := object.get(job, "uses", "")
	uses != ""
	external_action_reference(uses)
	not sha_pinned(uses)
	msg := sprintf("reusable workflow job %q must pin external workflow references to a full commit SHA", [job_name])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	steps := object.get(job, "steps", [])
	some index
	step := steps[index]
	uses := object.get(step, "uses", "")
	uses != ""
	external_action_reference(uses)
	not sha_pinned(uses)
	msg := sprintf("workflow job %q step %d must pin external action references to a full commit SHA", [job_name, index])
}

deny contains msg if {
	live_homelab_workflow
	not workflow_run_contains("scripts/ci/connect-octelium.sh")
	name := object.get(input, "name", "<unnamed workflow>")
	msg := sprintf("workflow %q touches live homelab access but does not connect through Octelium first", [name])
}

deny contains msg if {
	live_homelab_workflow
	not workflow_run_contains("scripts/ci/disconnect-octelium.sh")
	name := object.get(input, "name", "<unnamed workflow>")
	msg := sprintf("workflow %q touches live homelab access but does not tear down Octelium sessions", [name])
}

deny contains msg if {
	live_homelab_workflow
	value := workflow_env_value("OCTELIUM_KUBE_SERVICE")
	value != "kubernetes-api.ci"
	name := object.get(input, "name", "<unnamed workflow>")
	msg := sprintf("workflow %q must publish Kubernetes through Octelium Service kubernetes-api.ci", [name])
}

deny contains msg if {
	live_homelab_workflow
	value := workflow_env_value("KUBE_API_SERVER_URL")
	value != "https://127.0.0.1:16443"
	name := object.get(input, "name", "<unnamed workflow>")
	msg := sprintf("workflow %q must reach Kubernetes through the Octelium loopback listener", [name])
}

workflow_events := object.get(input, "on", object.get(input, true, {}))

has_event(events, event) if {
	events == event
}

has_event(events, event) if {
	is_array(events)
	events[_] == event
}

has_event(events, event) if {
	is_object(events)
	events[event]
}

external_action_reference(uses) if {
	not startswith(uses, "./")
	not startswith(uses, "docker://")
}

sha_pinned(uses) if {
	regex.match("^[^@]+@[0-9a-f]{40}$", uses)
}

live_homelab_workflow if {
	workflow_run_contains("scripts/ci/install-kubeconfig.sh")
}

live_homelab_workflow if {
	workflow_run_contains("scripts/ci/terragrunt-plan.sh")
}

live_homelab_workflow if {
	workflow_run_contains("scripts/ci/terragrunt-apply.sh")
}

live_homelab_workflow if {
	workflow_step_env_has("KUBE_CONFIG_B64")
}

workflow_run_contains(needle) if {
	jobs := object.get(input, "jobs", {})
	some _, job in jobs
	steps := object.get(job, "steps", [])
	some index
	step := steps[index]
	run := lower(sprintf("%v", [object.get(step, "run", "")]))
	contains(run, lower(needle))
}

workflow_step_env_has(key) if {
	jobs := object.get(input, "jobs", {})
	some _, job in jobs
	steps := object.get(job, "steps", [])
	some index
	step := steps[index]
	env := object.get(step, "env", {})
	object.get(env, key, null) != null
}

workflow_env_value(key) := value if {
	env := object.get(input, "env", {})
	value := sprintf("%v", [object.get(env, key, "")])
}
