package main

import rego.v1

deny contains msg if {
	events := workflow_events
	has_event(events, "pull_request_target")
	not native_receipt_provenance_workflow
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
	live_homelab_workflow
	not workflow_step_env_has("OCTELIUM_AUTH_TOKEN")
	name := object.get(input, "name", "<unnamed workflow>")
	msg := sprintf("workflow %q touches live homelab access but does not provide an Octelium clientless access token", [name])
}

deny contains msg if {
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
	step := steps[index]
	uses := object.get(step, "uses", "")
	some prefix in {"actions/upload-artifact@", "chainguard-actions/actions-upload-artifact@"}
	startswith(uses, prefix)
	not encrypted_harbor_diagnostic(job_name, job, step)
	not native_receipt_artifact(job_name, job, step)
	msg := sprintf("live workflow job %q step %d must not upload artifacts", [job_name, index])
}

encrypted_harbor_diagnostic(job_name, job, step) if {
	job_name == "mirror"
	some command in job.steps
	trim(object.get(command, "run", ""), "\n") == harbor_mirror_private_run
	step == harbor_encrypted_diagnostic_step
}

harbor_encrypted_diagnostic_step := {
	"name": "Retain Only Encrypted Failure Diagnostic",
	"if": "failure()",
	"uses": "chainguard-actions/actions-upload-artifact@ebf8f2543b7189e9a67dcac1af8cabbc5d7a3fd6",
	"with": {
		"name": "harbor-publication-error-${{ github.run_id }}-${{ github.run_attempt }}",
		"path": "${{ runner.temp }}/harbor-publication-error.gpg",
		"if-no-files-found": "ignore",
		"retention-days": 1,
		"include-hidden-files": false,
	},
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

workflow_events := object.get(input, "on", object.get(input, "true", object.get(input, true, {})))

# This checker runs only trusted base-branch code and reads a receipt-only PR
# as bounded API data. Any shape change must also update the exact workflow hash.
native_receipt_provenance_workflow if {
	count(input) == 5
	object.get(input, "name", "") == "Verify Native Chainguard Receipt Provenance"
	object.get(input, "concurrency", {}) == {"group": "native-chainguard-receipt-provenance", "cancel-in-progress": false}
	workflow_events == {
		"push": {"branches": ["main"]},
		"pull_request_target": {"branches": ["main"], "types": ["opened", "reopened", "synchronize"]},
	}
	object.get(input, "permissions", {}) == {}
	jobs := object.get(input, "jobs", {})
	jobs == {"verify": native_receipt_provenance_job}
}

native_receipt_provenance_job := {
	"name": "Native Chainguard Receipt Provenance",
	"runs-on": "ubuntu-24.04",
	"timeout-minutes": 20,
	"permissions": {"actions": "read", "contents": "read", "pull-requests": "read", "statuses": "write"},
	"steps": [
		{
			"name": "Check Out Trusted Base",
			"uses": "chainguard-actions/actions-checkout@9b08549f11b1cea64a914e482f95fa1413656505",
			"with": {
				"ref": "${{ github.event.pull_request.base.sha || github.sha }}",
				"fetch-depth": 1,
				"persist-credentials": false,
			},
		},
		{
			"name": "Verify Changed Native Receipt State",
			"if": "github.event_name == 'pull_request_target'",
			"env": {
				"BASE_SHA": "${{ github.event.pull_request.base.sha }}",
				"HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
				"GH_TOKEN": "${{ github.token }}",
			},
			"run": `set -euo pipefail
umask 077
token_file="$(mktemp)"
trap 'rm -f "$token_file"' EXIT
printf '%s' "$GH_TOKEN" >"$token_file"
report_status() {
  gh api -X POST "repos/${GITHUB_REPOSITORY}/statuses/${HEAD_SHA}" \
    -f state="$1" -f context='Native Chainguard Receipt Provenance' \
    -f description='Protected receipt state verification' >/dev/null
}
report_status pending
if [[ "$(gh api "repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha)" == "$BASE_SHA" ]] && \
  python3 -I scripts/ci/harbor-native-chainguard-receipt-import.py verify-pull-request \
  --base-sha "$BASE_SHA" --head-sha "$HEAD_SHA" \
  --token-file "$token_file" && \
  [[ "$(gh api "repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha)" == "$BASE_SHA" ]]; then
  report_status success
else
  report_status failure
  exit 1
fi
`,
		},
		{
			"name": "Revalidate Open Pull Requests After Main Moves",
			"if": "github.event_name == 'push'",
			"env": {"GH_TOKEN": "${{ github.token }}"},
			"run": `set -euo pipefail
umask 077
token_file="$(mktemp)"
pulls_file="$(mktemp)"
trap 'rm -f "$token_file" "$pulls_file"' EXIT
printf '%s' "$GH_TOKEN" >"$token_file"
gh api --paginate "repos/${GITHUB_REPOSITORY}/pulls?state=open&base=main&per_page=100" >"$pulls_file"
jq -r '.[].head.sha' "$pulls_file" |
while IFS= read -r head_sha; do
  [[ "$head_sha" =~ ^[0-9a-f]{40}$ ]] || exit 1
  [[ "$(gh api "repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha)" == "$GITHUB_SHA" ]] || exit 0
  gh api -X POST "repos/${GITHUB_REPOSITORY}/statuses/${head_sha}" \
    -f state=pending -f context='Native Chainguard Receipt Provenance' \
    -f description='Rechecking receipt against current main' >/dev/null
  if python3 -I scripts/ci/harbor-native-chainguard-receipt-import.py verify-pull-request \
    --base-sha "$GITHUB_SHA" --head-sha "$head_sha" \
    --token-file "$token_file" && \
    [[ "$(gh api "repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha)" == "$GITHUB_SHA" ]]; then
    state=success
  else
    state=failure
  fi
  [[ "$(gh api "repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha)" == "$GITHUB_SHA" ]] || exit 0
  gh api -X POST "repos/${GITHUB_REPOSITORY}/statuses/${head_sha}" \
    -f state="$state" -f context='Native Chainguard Receipt Provenance' \
    -f description='Protected receipt state verification' >/dev/null
done
`,
		},
	],
}

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
	workflow_run_contains("scripts/ci/harbor-native-chainguard-receipt.sh")
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

shell_live_command_pattern := `(?m)^[\t ]*(if[\t ]+![\t ]+)?(exec[\t ]+)?(nix[\t ]+develop[\t ]+--command[\t ]+)?((/usr/bin/)?env[\t ]+|command[\t ]+)?(bash|sh|zsh)[\t ]+(\./)?scripts/ci/(install-kubeconfig|terragrunt-plan|terragrunt-apply|octelium-private-kubernetes-apply|harbor-publish|harbor-native-chainguard-receipt)\.sh([\t ;]|$)`

direct_live_command_pattern := `(?m)^[\t ]*(if[\t ]+![\t ]+)?(exec[\t ]+)?(\./)?scripts/ci/(install-kubeconfig|terragrunt-plan|terragrunt-apply|octelium-private-kubernetes-apply|harbor-publish|harbor-native-chainguard-receipt)\.sh([\t ;]|$)`

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

live_cluster_command_count(run) := count(regex.find_all_string_submatch_n(kubectl_command_pattern, run, -1)) - count(regex.find_all_string_submatch_n(kubectl_local_render_pattern, run, -1)) + count(regex.find_all_string_submatch_n(talos_command_pattern, run, -1))

iac_command_count(run) := count(regex.find_all_string_submatch_n(iac_command_pattern, run, -1)) - count(regex.find_all_string_submatch_n(iac_local_validation_pattern, run, -1))

helm_command_count(run) := count(regex.find_all_string_submatch_n(helm_command_pattern, run, -1)) - count(regex.find_all_string_submatch_n(helm_local_render_pattern, run, -1))

sensitive_command_count(run) := live_script_command_count(run) + live_cluster_command_count(run) + count(regex.find_all_string_submatch_n(aws_command_pattern, run, -1)) + iac_command_count(run) + helm_command_count(run) + count(regex.find_all_string_submatch_n(octeliumctl_command_pattern, run, -1)) + count(regex.find_all_string_submatch_n(dynamic_command_pattern, run, -1))

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

# Harbor exposes only the reviewed publisher's fixed status fields. Keep this
# exception exact: other private wrappers cannot print arbitrary files or logs.
private_live_output(run) if {
	trim(run, "\n") == harbor_mirror_private_run
}

# The native receipt is a bounded, nonsecret attestation. Its exact workflow
# command and sole artifact are reviewed together below.
private_live_output(run) if {
	trim(run, "\n") == native_receipt_private_run
}

native_receipt_private_run := `set -euo pipefail
umask 077
private_log="$(mktemp)"
trap 'rm -f "$private_log"' EXIT
if ! nix develop --command bash scripts/ci/harbor-native-chainguard-receipt.sh >"$private_log" 2>&1; then
  echo '::error::Native Harbor receipt verification failed; private transport and registry output withheld.'
  exit 1
fi
jq -e '
  .schema_version == 1 and .kind == "native-chainguard-receipts-v1" and
  (.receipts | type == "array" and length == 2 and all(.[]; .consumer_access == true))
' "$RUNNER_TEMP/harbor-native-chainguard-receipt.json" >/dev/null
echo 'Native private Chainguard imports passed digest, platform, scan, and authenticated-pull verification.'`

native_receipt_artifact(job_name, job, step) if {
	object.get(input, "name", "") == "Verify Native Chainguard Harbor Imports"
	job_name == "receipt"
	steps := object.get(job, "steps", [])
	some index
	step == steps[index]
	index > 0
	trim(object.get(steps[index - 1], "run", ""), "\n") == native_receipt_private_run
	count(step) == 3
	object.get(step, "name", "") == "Upload Native Receipt"
	object.get(step, "uses", "") == "chainguard-actions/actions-upload-artifact@ebf8f2543b7189e9a67dcac1af8cabbc5d7a3fd6"
	options := object.get(step, "with", {})
	count(options) == 5
	object.get(options, "name", "") == "harbor-native-chainguard-receipt-${{ github.sha }}"
	object.get(options, "path", "") == "${{ runner.temp }}/harbor-native-chainguard-receipt.json"
	object.get(options, "if-no-files-found", "") == "error"
	object.get(options, "retention-days", 0) == 30
	object.get(options, "include-hidden-files", true) == false
}

harbor_mirror_private_run := `set -euo pipefail
umask 077
private_log="$(mktemp)"
public_status="$RUNNER_TEMP/harbor-mirror-status"
rm -f "$public_status"
trap 'rm -f "$private_log" "$public_status"' EXIT
if ! nix develop --command bash >"$private_log" 2>&1 <<'EOF'
set -euo pipefail
umask 077
case "$IMAGE_SCOPE" in
  all)
    bash scripts/ci/harbor-publish.sh mirror
    ;;
  fleet)
    bash scripts/ci/harbor-publish.sh mirror-fleet
    ;;
  mastodon)
    bash scripts/ci/harbor-publish.sh mirror-mastodon
    ;;
  bazarr)
    bash scripts/ci/harbor-publish.sh mirror-bazarr
    ;;
  chainguard)
    bash scripts/ci/harbor-publish.sh mirror-chainguard
    ;;
  traefik)
    bash scripts/ci/harbor-publish.sh mirror-traefik
    ;;
  *) exit 2 ;;
esac
EOF
then
  if [[ -f "$public_status" ]] && sha256sum --check --status <<<'444001e5fdae377b6490f41b62434c19f353824469517aa46fd512fd8bcb45a3  scripts/ci/harbor-publish.sh' 2>/dev/null; then
    cat "$public_status"
  fi
  echo "::error::Harbor mirror failed; private transport and registry output withheld."
  exit 1
fi
echo "Selected inventory copied with matching digests and complete authenticated Harbor pulls; upstream sources retained; private output withheld."`

private_live_tail(tail) if {
	lines := [trim(line, " \t\r") | line := split(tail, "\n")[_]; trim(line, " \t\r") != ""]
	count(lines) == 5
	lines[0] == "then"
	safe_withheld_echo(lines[1])
	lines[2] == "exit 1"
	lines[3] == "fi"
	safe_withheld_echo(lines[4])
}

private_live_tail(tail) if {
	lines := [trim(line, " \t\r") | line := split(tail, "\n")[_]; trim(line, " \t\r") != ""]
	count(lines) == 8
	lines[0] == "then"
	lines[1] == `if sha256sum --check --status <<<'aed6c96d6e74935108029cc3ee115bd68e1e4f8ca381380d413d67198c2fb15c  scripts/ci/terragrunt-plan-stage.sh' 2>/dev/null; then`
	lines[2] == `bash scripts/ci/terragrunt-plan-stage.sh <"$private_log"`
	lines[3] == "fi"
	safe_withheld_echo(lines[4])
	lines[5] == "exit 1"
	lines[6] == "fi"
	safe_withheld_echo(lines[7])
}

private_live_tail(tail) if {
	lines := [trim(line, " \t\r") | line := split(tail, "\n")[_]; trim(line, " \t\r") != ""]
	count(lines) == 8
	lines[0] == "then"
	lines[1] == `if sha256sum --check --status <<<'a6cbd46213ab38cdae557b56cb1e763ea7d0fdef6fa6ff7b9e071b582f51f865  scripts/ci/terragrunt-apply-stage.sh' 2>/dev/null; then`
	lines[2] == `bash scripts/ci/terragrunt-apply-stage.sh <"$private_log"`
	lines[3] == "fi"
	safe_withheld_echo(lines[4])
	lines[5] == "exit 1"
	lines[6] == "fi"
	safe_withheld_echo(lines[7])
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

workflow_env_value(key) := value if {
	env := object.get(input, "env", {})
	value := sprintf("%v", [object.get(env, key, "")])
}
