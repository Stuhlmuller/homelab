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
