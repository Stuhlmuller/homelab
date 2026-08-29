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
	jobs := object.get(input, "jobs", {})
	some job_id, job in jobs
	octelium_credential_job(job)
	not octelium_kube_job_ids[job_id]
	msg := sprintf("Octelium credential job %q must use an exact protected job ID and structural contract", [job_id])
}

deny contains msg if {
	env := object.get(input, "env", {})
	some key, value in env
	credential_context_reference(value)
	msg := sprintf("workflow-level environment variable %q must not contain a credential; scope it to one step", [key])
}

deny contains msg if {
	env := object.get(input, "env", {})
	some key in {"KUBE_API_SERVER_URL", "OCTELIUM_AUTH_TOKEN"}
	object.get(env, key, null) != null
	msg := sprintf("workflow-level %s is forbidden; Octelium credentials must remain step-local", [key])
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
	some job_id, job in jobs
	environment := raw_job_environment_name(job)
	contains(environment, "${{")
	msg := sprintf("job %q must use a literal GitHub environment name", [job_id])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_id, job in jobs
	environment := job_environment_name(job)
	protected_environment_names[environment]
	key := protected_job_key(job_id, job)
	object.get(protected_job_hashes, key, null) == null
	msg := sprintf("job %q uses protected environment %q without an exact structural contract", [job_id, environment])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_id in octelium_kube_job_ids
	job := object.get(jobs, job_id, null)
	job != null
	job_environment_name(job) != octelium_kube_job_environments[job_id]
	msg := sprintf("Octelium credential job %q must keep its exact protected environment", [job_id])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_id, job in jobs
	key := protected_job_key(job_id, job)
	expected := object.get(protected_job_hashes, key, null)
	expected != null
	actual := protected_job_contract_hash(job)
	actual != expected
	msg := sprintf("protected job %q must match its exact structural contract; reviewed hash %s, actual hash %s", [job_id, expected, actual])
}

deny contains msg if {
	jobs := object.get(input, "jobs", {})
	some job_id in octelium_kube_job_ids
	job := object.get(jobs, job_id, null)
	job != null
	not protected_job_env_is_exact(job)
	msg := sprintf("protected job %q must keep the exact effective Octelium endpoint and token only on install_kubeconfig", [job_id])
}

deny contains msg if {
	not protected_job_workflow
	live_homelab_workflow
	not workflow_step_env_has("OCTELIUM_AUTH_TOKEN")
	name := object.get(input, "name", "<unnamed workflow>")
	msg := sprintf("workflow %q touches live homelab access but does not provide an Octelium clientless access token", [name])
}

deny contains msg if {
	not protected_job_workflow
	live_homelab_workflow
	value := workflow_env_value("KUBE_API_SERVER_URL")
	value != "https://kubernetes-api-ci.stinkyboi.com"
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

deny contains msg if {
	not protected_job_workflow
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	steps := object.get(job, "steps", [])
	some index
	step := steps[index]
	live_homelab_step(step)
	not canonical_live_homelab_step(job, step)
	msg := sprintf("workflow job %q step %d must use one exact allowlisted live homelab invocation with a safe Bash repository-root context", [job_name, index])
}

deny contains msg if {
	not protected_job_workflow
	jobs := object.get(input, "jobs", {})
	some job_name, job in jobs
	steps := object.get(job, "steps", [])
	some index
	step := steps[index]
	live_homelab_step(step)
	not preceding_kubeconfig_preflight(job, steps, index)
	msg := sprintf("workflow job %q step %d must follow the exact scripts/ci/install-kubeconfig.sh preflight step", [job_name, index])
}

deny contains msg if {
	not protected_job_workflow
	name := object.get(input, "name", "")
	spec := expected_live_workflows[name]
	not expected_live_workflow_contract(spec)
	msg := sprintf("workflow %q must keep its exact allowlisted live job, step, command, and preflight order", [name])
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

iac_command_count(run) := count(regex.find_all_string_submatch_n(iac_command_pattern, run, -1)) - count(regex.find_all_string_submatch_n(iac_local_validation_pattern, run, -1))

helm_command_count(run) := count(regex.find_all_string_submatch_n(helm_command_pattern, run, -1)) - count(regex.find_all_string_submatch_n(helm_local_render_pattern, run, -1))

sensitive_command_count(run) := (((((live_script_command_count(run) + live_cluster_command_count(run)) + count(regex.find_all_string_submatch_n(aws_command_pattern, run, -1))) + iac_command_count(run)) + helm_command_count(run)) + count(regex.find_all_string_submatch_n(octeliumctl_command_pattern, run, -1))) + count(regex.find_all_string_submatch_n(dynamic_command_pattern, run, -1))

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

live_homelab_workflow if {
	jobs := object.get(input, "jobs", {})
	some _, job in jobs
	steps := object.get(job, "steps", [])
	some index
	live_homelab_step(steps[index])
}

live_homelab_step(step) if {
	lines := step_run_lines(step)
	some index
	live_homelab_command(trim_space(lines[index]))
}

canonical_live_homelab_step(job, step) if {
	run := trim_space(sprintf("%v", [object.get(step, "run", "")]))
	run in canonical_live_runs
	live_step_requires_preflight_success(step)
	step_execution_context_is_safe(job, step)
}

preceding_kubeconfig_preflight(job, steps, index) if {
	index > 0
	live_step := steps[index]
	live_step_requires_preflight_success(live_step)
	previous := index - 1
	step := steps[previous]
	run := trim_space(sprintf("%v", [object.get(step, "run", "")]))
	run == "nix develop --command bash scripts/ci/install-kubeconfig.sh"
	preflight_if_is_unconditional(step)
	preflight_stops_on_error(step)
	step_execution_context_is_safe(job, step)
}

preflight_if_is_unconditional(step) if {
	value := lower(trim_space(sprintf("%v", [object.get(step, "if", true)])))
	value in {"true", "${{ true }}"}
}

preflight_stops_on_error(step) if {
	value := lower(trim_space(sprintf("%v", [object.get(step, "continue-on-error", false)])))
	value in {"false", "${{ false }}"}
}

live_step_requires_preflight_success(step) if {
	value := lower(trim_space(sprintf("%v", [object.get(step, "if", "success()")])))
	value in {"success()", "${{ success() }}"}
}

step_execution_context_is_safe(job, step) if {
	workflow_defaults := object.get(object.get(input, "defaults", {}), "run", {})
	job_defaults := object.get(object.get(job, "defaults", {}), "run", {})
	shell := object.get(step, "shell", object.get(job_defaults, "shell", object.get(workflow_defaults, "shell", "bash")))
	working_directory := object.get(step, "working-directory", object.get(job_defaults, "working-directory", object.get(workflow_defaults, "working-directory", ".")))
	shell == "bash"
	working_directory == "."
}

step_run_lines(step) := split(normalize_shell_run(sprintf("%v", [object.get(step, "run", "")])), "\n")

normalize_shell_run(run) := normalized if {
	lowered := lower(run)
	joined := replace(lowered, "\\\n", "")
	unquoted := replace(replace(joined, "'", ""), "\"", "")
	unescaped := replace(unquoted, "\\", "")
	normalized := regex.replace(unescaped, "/+", "/")
}

live_homelab_command(command) if {
	contains(command, "scripts/ci/terragrunt-plan.sh")
}

live_homelab_command(command) if {
	contains(command, "scripts/ci/terragrunt-apply.sh")
}

live_homelab_command(command) if {
	contains(command, "scripts/ci/grafana-diagnostics.sh")
}

live_homelab_command(command) if {
	tokens := regex.split("[[:space:];|&]+", command)
	some index
	kubectl_token(tokens[index])
	next := index + 1
	next < count(tokens)
	normalize_shell_token(tokens[next]) != "kustomize"
}

kubectl_token(token) if {
	normalized := normalize_shell_token(token)
	normalized == "kubectl"
}

kubectl_token(token) if {
	normalized := normalize_shell_token(token)
	endswith(normalized, "/kubectl")
}

normalize_shell_token(token) := trim(token, "'\"()$`{}[]")

canonical_live_runs := {
	"nix develop --command bash scripts/ci/grafana-diagnostics.sh",
	"nix develop --command bash scripts/ci/terragrunt-apply.sh",
	"nix develop --command bash scripts/ci/terragrunt-plan.sh",
}

expected_live_workflows := {
	"Homelab Diagnostics": {
		"job": "grafana",
		"run": "nix develop --command bash scripts/ci/grafana-diagnostics.sh",
		"step": "Run Grafana Diagnostics Through Octelium",
	},
	"Terragrunt Apply": {
		"job": "terragrunt-apply",
		"run": "nix develop --command bash scripts/ci/terragrunt-apply.sh",
		"step": "Run Live Terragrunt Apply",
	},
	"Terragrunt Plan": {
		"job": "terragrunt-plan",
		"run": "nix develop --command bash scripts/ci/terragrunt-plan.sh",
		"step": "Run Live Terragrunt Plan",
	},
}

expected_live_workflow_contract(spec) if {
	jobs := object.get(input, "jobs", {})
	job := object.get(jobs, spec.job, {})
	steps := object.get(job, "steps", [])
	indices := [index |
		some index
		step := steps[index]
		object.get(step, "name", "") == spec.step
	]
	count(indices) == 1
	index := indices[0]
	step := steps[index]
	trim_space(sprintf("%v", [object.get(step, "run", "")])) == spec.run
	canonical_live_homelab_step(job, step)
	preceding_kubeconfig_preflight(job, steps, index)
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

octelium_kube_job_ids := {
	"grafana",
	"terragrunt-apply",
	"terragrunt-plan",
}

octelium_kube_job_environments := {
	"grafana": "homelab-plan",
	"terragrunt-apply": "homelab-production",
	"terragrunt-plan": "homelab-plan",
}

protected_environment_names := {
	"homelab-plan",
	"homelab-production",
}

protected_job_hashes := {
	"homelab-plan/grafana": "2ff2298abd93caaef9ced19a489bc49549faa38d4471840d3ea4943b9b3c445c",
	"homelab-plan/terragrunt-plan": "4bc1a23149451f23ffb8165eaec3dbac89a096160ececb5c96ff6e1c84a5b590",
	"homelab-production/octelium-catalog": "d47f50f740a5a179ff54900268c4c6ea80cc25ef25351aa7e8731a6588c8c3c2",
	"homelab-production/reconcile": "af9013aac772acd57fd52b0b40f8fe612ad4bbc9b7e13396287c455b3360df36",
	"homelab-production/remove": "5543b29c3637895b1ce5f0c4bb6efcee3e508095adb20f03773990332089a6f1",
	"homelab-production/terragrunt-apply": "cf786bb2e820cbc4cff9c08de3a97e92a3ba7ae1e0688f3bb0c368401ec67ecf",
}

octelium_endpoint := "https://kubernetes-api-ci.stinkyboi.com"

octelium_token_expression := "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}"

protected_job_workflow if {
	jobs := object.get(input, "jobs", {})
	some job_id in octelium_kube_job_ids
	object.get(jobs, job_id, null) != null
}

protected_job_key(job_id, job) := sprintf("%s/%s", [job_environment_name(job), job_id])

job_environment_name(job) := lower(raw_job_environment_name(job))

raw_job_environment_name(job) := name if {
	environment := object.get(job, "environment", {})
	is_object(environment)
	name := object.get(environment, "name", "")
}

raw_job_environment_name(job) := environment if {
	environment := object.get(job, "environment", "")
	is_string(environment)
}

octelium_credential_job(job) if {
	some path, value
	walk(job, [path, value])
	is_string(value)
	contains(lower(value), "octelium_ci_auth_token")
}

octelium_credential_job(job) if {
	some path, value
	walk(job, [path, value])
	is_string(value)
	contains(lower(value), lower(octelium_endpoint))
}

protected_job_contract_hash(job) := crypto.sha256(json.marshal(protected_job_payload(job)))

protected_job_payload(job) := {
	"job": object.union(
		object.remove(job, {"name", "steps"}),
		{"steps": object.get(job, "steps", [])},
	),
	"workflow": object.remove(input, {"jobs", "name"}),
}

protected_job_env_is_exact(job) if {
	preflight := job_step(job, "install_kubeconfig")
	live := job_step(job, "live")
	effective_env_value(job, preflight, "KUBE_API_SERVER_URL") == octelium_endpoint
	effective_env_value(job, preflight, "OCTELIUM_AUTH_TOKEN") == octelium_token_expression
	effective_env_value(job, live, "KUBE_API_SERVER_URL") == null
	effective_env_value(job, live, "OCTELIUM_AUTH_TOKEN") == null
}

job_step(job, id) := step if {
	steps := object.get(job, "steps", [])
	some index
	step := steps[index]
	object.get(step, "id", "") == id
}

effective_env_value(job, step, key) := value if {
	workflow_value := object.get(object.get(input, "env", {}), key, null)
	job_value := object.get(object.get(job, "env", {}), key, workflow_value)
	value := object.get(object.get(step, "env", {}), key, job_value)
}
