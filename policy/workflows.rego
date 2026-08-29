package main

import rego.v1

deny contains msg if {
	events := workflow_events
	has_event(events, "pull_request_target")
	name := object.get(input, "name", "<unnamed workflow>")
	msg := sprintf("workflow %q must not use pull_request_target for infrastructure checks", [name])
}

deny contains msg if {
	permissions := object.get(input, "permissions", {})
	is_string(permissions)
	permissions == "write-all"
	msg := "workflow-wide write-all permissions are forbidden"
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	permissions := object.get(job, "permissions", {})
	is_string(permissions)
	permissions == "write-all"
	msg := sprintf("workflow job %q must not use write-all permissions", [job_name])
}

deny contains msg if {
	permissions := object.get(input, "permissions", {})
	is_object(permissions)
	some permission, value in permissions
	value == "write"
	msg := sprintf("workflow-wide %q write permission is forbidden; scope it to one non-live job", [permission])
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
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	steps := object.get(job, "steps", [])
	some index
	step := steps[index]
	uses := object.get(step, "uses", "")
	startswith(uses, "docker://")
	not docker_action_digest_pinned(uses)
	msg := sprintf("workflow job %q step %d must pin its Docker action image by SHA-256 digest", [job_name, index])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	steps := object.get(job, "steps", [])
	some index
	step := steps[index]
	uses := lower(sprintf("%v", [object.get(step, "uses", "")]))
	startswith(uses, "actions/upload-artifact@")
	msg := sprintf("workflow job %q step %d must not upload public-repository artifacts", [job_name, index])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	image := job_container_image(job)
	not image_digest_pinned(image)
	msg := sprintf("workflow job %q must pin its container image by SHA-256 digest", [job_name])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	services := object.get(job, "services", {})
	some service_name, service in services
	image := object.get(service, "image", "")
	image != ""
	not image_digest_pinned(image)
	msg := sprintf("workflow job %q service %q must pin its image by SHA-256 digest", [job_name, service_name])
}

deny contains msg if {
	env := object.get(input, "env", {})
	some key, value in env
	credential_context_reference(value)
	msg := sprintf("workflow-level environment variable %q must not contain a credential; scope it to one step", [key])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	env := object.get(job, "env", {})
	some key, value in env
	credential_context_reference(value)
	msg := sprintf("workflow job %q environment variable %q must not contain a credential; scope it to one step", [job_name, key])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	steps := object.get(job, "steps", [])
	some index
	step := steps[index]
	run := object.get(step, "run", "")
	segment := workflow_run_segments(run)[_]
	kubectl_command(segment)
	not approved_public_kubectl_command(segment)
	msg := sprintf("workflow job %q step %d must not emit unapproved Kubernetes command output", [job_name, index])
}

deny contains msg if {
	live_homelab_workflow
	not workflow_step_env_has("OCTELIUM_AUTH_TOKEN")
	name := object.get(input, "name", "<unnamed workflow>")
	msg := sprintf("workflow %q touches live homelab access but does not provide an Octelium clientless access token", [name])
}

deny contains msg if {
	live_homelab_workflow
	not workflow_step_env_has_value("KUBE_API_SERVER_URL", "https://kubernetes-api-ci.stinkyboi.com")
	name := object.get(input, "name", "<unnamed workflow>")
	msg := sprintf("workflow %q must reach Kubernetes through the Octelium clientless endpoint", [name])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	steps := object.get(job, "steps", [])
	some index
	run := object.get(steps[index], "run", "")
	sensitive_command_run(run)
	not private_live_output(run)
	msg := sprintf("workflow job %q step %d must withhold sensitive command output from public logs", [job_name, index])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	job_sensitive_command(job)
	permissions := object.get(job, "permissions", {})
	some permission, value in permissions
	value == "write"
	permission != "id-token"
	msg := sprintf("live workflow job %q must not have %q write permission", [job_name, permission])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	job_sensitive_command(job)
	steps := object.get(job, "steps", [])
	some index
	uses := object.get(steps[index], "uses", "")
	startswith(uses, "actions/upload-artifact@")
	msg := sprintf("live workflow job %q step %d must not upload artifacts", [job_name, index])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	steps := object.get(job, "steps", [])
	some index
	run := lower(sprintf("%v", [object.get(steps[index], "run", "")]))
	contains(run, "scripts/ci/octelium-private-kubernetes-apply.sh")
	env := object.get(steps[index], "env", {})
	object.get(env, "OCTELIUM_CATALOG_AUTH_TOKEN", null) == null
	msg := sprintf("Octelium catalog workflow job %q step %d must use its one-use catalog credential", [job_name, index])
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

docker_action_digest_pinned(uses) if {
	regex.match("^docker://[^[:space:]@]+@sha256:[0-9a-f]{64}$", uses)
}

image_digest_pinned(image) if {
	regex.match("^[^[:space:]@]+@sha256:[0-9a-f]{64}$", image)
}

credential_context_reference(value) if {
	is_string(value)
	contains(value, "${{")
	regex.match(`(^|[^A-Za-z0-9_.])(secrets|github)([^A-Za-z0-9_]|$)`, lower(value))
}

job_container_image(job) := image if {
	container := object.get(job, "container", "")
	is_string(container)
	image := container
	image != ""
}

job_container_image(job) := image if {
	container := object.get(job, "container", {})
	is_object(container)
	image := object.get(container, "image", "")
	image != ""
}

kubectl_command(segment) if {
	regex.match(`(^|[[:space:]"'(])kubectl([[:space:]]|$)`, segment)
}

approved_public_kubectl_command(segment) if {
	regex.match(`^[[:space:]]*kubectl[[:space:]]+--request-timeout=15s[[:space:]]+version[[:space:]]*$`, segment)
}

approved_public_kubectl_command(segment) if {
	regex.match(`kubectl[^;&|]*[[:space:]](>|1>)[[:space:]]*/dev/null([[:space:]]|$)`, segment)
}

workflow_run_segments(run) := regex.split(`\r?\n|[;&|]+`, regex.replace(lower(sprintf("%v", [run])), `\\\r?\n`, " "))

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
	jobs := object.get(input, "jobs", {})
	some _, job in jobs
	steps := object.get(job, "steps", [])
	some index
	live_cluster_command_count(object.get(steps[index], "run", "")) > 0
}

job_sensitive_command(job) if {
	steps := object.get(job, "steps", [])
	some index
	sensitive_command_run(object.get(steps[index], "run", ""))
}

shell_live_command_pattern := `(?m)^[\t ]*(if[\t ]+![\t ]+)?(exec[\t ]+)?(nix[\t ]+develop[\t ]+--command[\t ]+)?((/usr/bin/)?env[\t ]+|command[\t ]+)?(bash|sh|zsh)[\t ]+(\./)?scripts/ci/(install-kubeconfig|terragrunt-plan|terragrunt-apply|octelium-private-kubernetes-apply)\.sh([\t ;]|$)`

direct_live_command_pattern := `(?m)^[\t ]*(if[\t ]+![\t ]+)?(exec[\t ]+)?(\./)?scripts/ci/(install-kubeconfig|terragrunt-plan|terragrunt-apply|octelium-private-kubernetes-apply)\.sh([\t ;]|$)`

kubectl_command_pattern := `(?m)(^|[^A-Za-z0-9_.-])["']?kubectl["']?[\t ]+`

kubectl_local_render_pattern := `(?m)(^|[^A-Za-z0-9_.-])kubectl[\t ]+kustomize([\t ;]|$)`

talos_command_pattern := `(?m)(^|[^A-Za-z0-9_.-])["']?talosctl["']?[\t ]+`

aws_command_pattern := `(?m)(^|[^A-Za-z0-9_.-])["']?aws["']?[\t ]+`

iac_command_pattern := `(?m)(^|[^A-Za-z0-9_.-])["']?(terraform|tofu|terragrunt)["']?[\t ]+`

iac_local_validation_pattern := `(?m)(^|[^A-Za-z0-9_.-])["']?((terraform|tofu)["']?[\t ]+(fmt|validate)|terragrunt["']?[\t ]+(hcl[\t ]+(fmt|validate)|stack[\t ]+generate))([^A-Za-z0-9_-]|$)`

helm_command_pattern := `(?m)(^|[^A-Za-z0-9_.-])["']?helm["']?[\t ]+`

helm_local_render_pattern := `(?m)(^|[^A-Za-z0-9_.-])["']?helm["']?[\t ]+template([\t ;]|$)`

octeliumctl_command_pattern := `(?m)(^|[^A-Za-z0-9_.-])["']?octeliumctl["']?[\t ]+`

dynamic_command_pattern := `(?m)^[\t ]*(if[\t ]+![\t ]+)?(exec[\t ]+)?(nix[\t ]+develop[\t ]+--command[\t ]+)?((/usr/bin/)?env[\t ]+|command[\t ]+)?["']?(\$[A-Za-z_{(]|\x60)`

private_wrapper_start := "if ! nix develop --command bash >\"$private_log\" 2>&1 <<'EOF'\n"

live_script_command_count(run) := count(regex.find_all_string_submatch_n(shell_live_command_pattern, run, -1)) + count(regex.find_all_string_submatch_n(direct_live_command_pattern, run, -1))

live_cluster_command_count(run) := (count(regex.find_all_string_submatch_n(kubectl_command_pattern, run, -1)) - count(regex.find_all_string_submatch_n(kubectl_local_render_pattern, run, -1))) + count(regex.find_all_string_submatch_n(talos_command_pattern, run, -1))

unapproved_kubectl_command_count(run) := count([segment |
	segment := workflow_run_segments(run)[_]
	kubectl_command(segment)
	not approved_public_kubectl_command(segment)
])

iac_command_count(run) := count(regex.find_all_string_submatch_n(iac_command_pattern, run, -1)) - count(regex.find_all_string_submatch_n(iac_local_validation_pattern, run, -1))

helm_command_count(run) := count(regex.find_all_string_submatch_n(helm_command_pattern, run, -1)) - count(regex.find_all_string_submatch_n(helm_local_render_pattern, run, -1))

sensitive_command_count(run) := live_script_command_count(run) + unapproved_kubectl_command_count(run) + count(regex.find_all_string_submatch_n(talos_command_pattern, run, -1)) + count(regex.find_all_string_submatch_n(aws_command_pattern, run, -1)) + iac_command_count(run) + helm_command_count(run) + count(regex.find_all_string_submatch_n(octeliumctl_command_pattern, run, -1)) + count(regex.find_all_string_submatch_n(dynamic_command_pattern, run, -1))

sensitive_command_run(run) if {
	sensitive_command_count(run) > 0
}

private_live_output(run) if {
	wrapped := split(run, private_wrapper_start)
	count(wrapped) == 2
	closed := split(wrapped[1], "\nEOF\n")
	count(closed) == 2
	body := closed[0]
	tail := closed[1]
	sensitive_command_count(body) > 0
	sensitive_command_count(run) == sensitive_command_count(body)
	regex.match(`(?m)^[\t ]*private_log="\$\(mktemp\)"[\t ]*$`, run)
	regex.match(`(?m)^[\t ]*trap[\t ]+'rm -f "\$private_log"'[\t ]+EXIT[\t ]*$`, run)
	regex.match(`(?m)^[\t ]*umask[\t ]+077[\t ]*$`, body)
	private_live_tail(tail)
}

private_live_tail(tail) if {
	lines := [trim(line, " \t\r") | line := split(tail, "\n")[_]; trim(line, " \t\r") != ""]
	count(lines) == 5
	lines[0] == "then"
	safe_withheld_echo(lines[1])
	lines[2] == "exit 1"
	lines[3] == "fi"
	safe_withheld_echo(lines[4])
}

safe_withheld_echo(line) if {
	startswith(line, `echo "`)
	endswith(line, `"`)
	count(split(line, "\"")) == 3
	contains(lower(line), "withheld")
	not contains(line, "$")
	not contains(line, "`")
	not contains(line, "\\")
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

workflow_step_env_has_value(key, expected) if {
	jobs := object.get(input, "jobs", {})
	some _, job in jobs
	steps := object.get(job, "steps", [])
	some index
	step := steps[index]
	env := object.get(step, "env", {})
	sprintf("%v", [object.get(env, key, "")]) == expected
}
