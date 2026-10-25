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
	not encrypted_oce_diagnostic(job_name, job, step)
	msg := sprintf("live workflow job %q step %d must not upload artifacts", [job_name, index])
}

deny contains msg if {
	object.get(input, "name", "") == "OpenClaw Enterprise Operations"
	not approved_openclaw_operations
	msg := "OpenClaw Enterprise operations require exact protected stages, permissions, and script hashes"
}

deny contains msg if {
	object.get(input, "name", "") == "OpenClaw Enterprise Operations"
	not approved_openclaw_enterprise_operation
	msg := "OpenClaw Enterprise stages require exact dispatch, current-main guard, serialized permission scope, and blocked helper hash"
}

deny contains msg if {
	object.get(input, "name", "") == "OpenClaw Enterprise Startup Candidate"
	not approved_openclaw_startup
	msg := "OpenClaw Enterprise startup requires exact-main protected create, fixed source hash, and private output"
}

approved_openclaw_startup if {
	dispatch := object.get(workflow_events, "workflow_dispatch", {})
	count(object.keys(workflow_events)) == 1
	protected_workflow_run_settings
	count(dispatch.inputs) == 1
	dispatch.inputs.expected_sha.required == true
	input.permissions == {}
	input.concurrency == {"group": "openclaw-enterprise-startup-production", "cancel-in-progress": false}
	count(input.jobs) == 2
	static := input.jobs["static-policy"]
	static["runs-on"] == "ubuntu-24.04"
	static.permissions == {"contents": "read"}
	count(static.steps) == 4
	static.steps[0].name == "Verify Dispatch Commit"
	static.steps[0].env == {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}"}
	contains(static.steps[0].run, `test "${ACTUAL_REF}" = refs/heads/main`)
	contains(static.steps[0].run, `test "${ACTUAL_SHA}" = "${EXPECTED_SHA}"`)
	static.steps[3].name == "Run Static Checks"
	contains(static.steps[3].run, "nix develop --command bash scripts/ci/static-checks.sh --offline-verified")
	job := input.jobs.startup
	job.needs == ["static-policy"]
	job.if == "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main'"
	job.environment.name == "homelab-production"
	job.permissions == {"contents": "read"}
	count(job.steps) == 4
	[job.steps[0].name, job.steps[1].name, job.steps[2].name, job.steps[3].name] == ["Verify Current Main Before Credentials", "Check Out Repository", "Install Nix", "Create Or Attest Fixed Startup Secret"]
	verify := job.steps[0]
	verify.env == {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}
	trim(verify.run, "\n") == openclaw_startup_main_check
	run := job.steps[3]
	run.env == {"EXPECTED_SHA": "${{ inputs.expected_sha }}", "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}"}
	trim(run.run, "\n") == openclaw_startup_private_run
}

openclaw_startup_main_check := `set -euo pipefail
test "${ACTUAL_REF}" = refs/heads/main
test "${ACTUAL_SHA}" = "${EXPECTED_SHA}"
test "${ACTUAL_SHA}" = "$(gh api "repos/${GH_REPO}/git/ref/heads/main" --jq .object.sha)"`

openclaw_startup_private_run := `set -euo pipefail
private_log="$(mktemp)"
trap 'rm -f "$private_log"' EXIT
if ! nix develop --command bash >"$private_log" 2>&1 <<'EOF'
set -euo pipefail
umask 077
bash scripts/ci/install-kubeconfig.sh
sha256sum --check --status <<<'1ea9b290420dfbb2db5ce70331c16f664b91b6cffbb3618bb38b9d492cbf22a8  scripts/openclaw-enterprise-startup.py'
python3 -I scripts/openclaw-enterprise-startup.py --execute --expected-sha "$EXPECTED_SHA"
EOF
then
  echo "::error::Startup candidate blocked; private cluster diagnostics withheld."
  exit 1
fi
echo "Reviewed startup Secret created or attested; private details withheld."`

deny contains msg if {
	object.get(input, "name", "") == "Platform Maintenance"
	not approved_platform_maintenance
	msg := "Platform maintenance requires exact protected stages, current-main verification, permissions, and script hash"
}

approved_platform_maintenance if {
	dispatch := object.get(workflow_events, "workflow_dispatch", {})
	count(object.keys(workflow_events)) == 1
	protected_workflow_run_settings
	count(dispatch.inputs) == 11
	dispatch.inputs.stage.options == ["inspect", "firewall-baseline", "firewall-baseline-recover", "placement", "canary-admit", "canary-admit-recover", "canary-release", "qualify", "ownership-capture", "ownership-approve", "owned-cleanup", "talos-1.11.6", "talos-1.12.12", "talos-1.13.11", "talos-1.14.4", "kubernetes-1.35.9"]
	dispatch.inputs.baseline_source_sha.required == false
	dispatch.inputs.baseline_source_sha.type == "string"
	dispatch.inputs.baseline_run_id.required == false
	dispatch.inputs.baseline_run_id.type == "string"
	dispatch.inputs.placement_run_id.required == false
	dispatch.inputs.placement_run_id.type == "string"
	dispatch.inputs.admission_run_id.required == false
	dispatch.inputs.admission_run_id.type == "string"
	dispatch.inputs.cleanup_run_id.required == false
	dispatch.inputs.cleanup_run_id.type == "string"
	dispatch.inputs.expected_sha.required == true
	count(object.keys(input)) == 5
	input.permissions == {}
	input.env == {"KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com"}
	count(object.keys(input.jobs)) == 2
	static := input.jobs["static-policy"]
	count(object.keys(static)) == 4
	static.name == "Validate Platform Stage Source"
	static.permissions == {"contents": "read"}
	static["runs-on"] == "ubuntu-24.04"
	count(static.steps) == 4
	count(object.keys(static.steps[0])) == 3
	static.steps[0].name == "Verify Dispatch Commit"
	static.steps[0].env == {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "RUN_STAGE": "${{ inputs.stage }}"}
	trim(static.steps[0].run, "\n") == platform_maintenance_dispatch_check
	static.steps[1] == platform_maintenance_static_checkout
	static.steps[2] == platform_maintenance_install_nix
	count(object.keys(static.steps[3])) == 2
	static.steps[3].name == "Run Static Checks"
	trim(static.steps[3].run, "\n") == platform_maintenance_static_checks
	job := input.jobs.maintenance
	count(object.keys(job)) == 9
	job.name == "Protected Platform Stage"
	job["timeout-minutes"] == 120
	job.needs == ["static-policy"]
	job["runs-on"] == "ubuntu-24.04"
	job.environment.name == "homelab-production"
	job.concurrency == {"group": "platform-maintenance-production", "cancel-in-progress": false}
	job.permissions == {"contents": "read", "id-token": "write"}
	job.if == "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main'"
	count(job.steps) == 6
	[job.steps[0].name, job.steps[1].name, job.steps[2].name, job.steps[3].name, job.steps[4].name, job.steps[5].name] == ["Verify Current Main Commit Before Credentials", "Check Out Repository", "Install Nix", "Recheck Current Main Commit Before AWS Credentials", "Configure AWS Credentials", "Run Reviewed Platform Stage"]
	verify := job.steps[0]
	count(object.keys(verify)) == 3
	verify.env == {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "RUN_STAGE": "${{ inputs.stage }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}
	trim(verify.run, "\n") == platform_maintenance_owner_main_check
	job.steps[1] == platform_maintenance_private_checkout
	job.steps[2] == platform_maintenance_install_nix
	recheck := job.steps[3]
	count(object.keys(recheck)) == 3
	recheck.env == {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}
	trim(recheck.run, "\n") == platform_maintenance_main_check
	job.steps[4] == platform_maintenance_aws_credentials
	some run in job.steps
	run.name == "Run Reviewed Platform Stage"
	count(object.keys(run)) == 3
	run.env == platform_maintenance_private_env
	trim(run.run, "\n") == platform_maintenance_private_run
}

platform_maintenance_dispatch_check := `test "${ACTUAL_REF}" = refs/heads/main
test "${ACTUAL_SHA}" = "${EXPECTED_SHA}"
if [ "$RUN_STAGE" = ownership-approve ] || [ "$RUN_STAGE" = canary-admit-recover ]; then
  test "$GITHUB_ACTOR_ID" = 57728706
  test "$GITHUB_RUN_ATTEMPT" = 1
fi`

platform_maintenance_static_checks := `git fetch --no-tags origin main
cache_policy="${RUNNER_TEMP}/nix-cache-policy.json"
git show origin/main:scripts/config/nix-cache.json >"$cache_policy"
bash scripts/ci/nix-checks.sh --policy "$cache_policy"
nix develop --command bash scripts/ci/static-checks.sh --offline-verified
nix develop --command python3 -I scripts/ci/platform-maintenance-stage-test.py`

platform_maintenance_static_checkout := {"name": "Check Out Repository", "uses": "chainguard-actions/actions-checkout@9b08549f11b1cea64a914e482f95fa1413656505", "with": {"fetch-depth": 2, "persist-credentials": false}}
platform_maintenance_private_checkout := {"name": "Check Out Repository", "uses": "chainguard-actions/actions-checkout@9b08549f11b1cea64a914e482f95fa1413656505", "with": {"fetch-depth": 0, "persist-credentials": false}}
platform_maintenance_install_nix := {"name": "Install Nix", "uses": "chainguard-actions/cachix-install-nix-action@043d5ae37e81d3c6b1604becbdc6aefbdc9fa909", "with": {"enable_kvm": false, "github_access_token": "${{ secrets.GITHUB_TOKEN }}"}}
platform_maintenance_aws_credentials := {"name": "Configure AWS Credentials", "uses": "chainguard-actions/aws-actions-configure-aws-credentials@2ea09546a514e2cbdbe87dd880db44555f7d3508", "with": {"aws-region": "us-east-1", "mask-aws-account-id": true, "role-session-name": "homelab-platform-${{ github.run_id }}", "role-to-assume": "${{ vars.AWS_ROLE_TO_ASSUME_HOMELAB || secrets.AWS_ROLE_TO_ASSUME_HOMELAB }}", "unset-current-credentials": true}}
platform_maintenance_private_env := {"RUN_STAGE": "${{ inputs.stage }}", "BASELINE_SOURCE_SHA": "${{ inputs.baseline_source_sha }}", "BASELINE_RUN_ID": "${{ inputs.baseline_run_id }}", "PLACEMENT_RUN_ID": "${{ inputs.placement_run_id }}", "ADMISSION_RUN_ID": "${{ inputs.admission_run_id }}", "CLEANUP_RUN_ID": "${{ inputs.cleanup_run_id }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "QUALIFICATION_RUN_ID": "${{ inputs.qualification_run_id }}", "EVIDENCE_SOURCE_SHA": "${{ inputs.evidence_source_sha }}", "CAPTURE_RUN_ID": "${{ inputs.capture_run_id }}", "REVIEWED_SNAPSHOT_SHA256": "${{ inputs.reviewed_snapshot_sha256 }}", "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}", "OCE_OCTELIUM_CLIENT_AUTH_TOKEN": "${{ secrets.OCE_OCTELIUM_CLIENT_AUTH_TOKEN }}", "OCE_TALOSCONFIG_B64": "${{ secrets.OCE_TALOSCONFIG_B64 }}", "OCE_CONTROLPLANE_CONFIG_B64": "${{ secrets.OCE_CONTROLPLANE_CONFIG_B64 }}", "OCE_WORKER_CONFIG_B64": "${{ secrets.OCE_WORKER_CONFIG_B64 }}", "GH_TOKEN": "${{ github.token }}"}

platform_maintenance_main_check := `set -euo pipefail
test "$ACTUAL_REF" = refs/heads/main
test "$ACTUAL_SHA" = "$EXPECTED_SHA"
test "$ACTUAL_SHA" = "$(gh api "repos/${GH_REPO}/git/ref/heads/main" --jq .object.sha)"`

platform_maintenance_owner_main_check := `set -euo pipefail
test "$ACTUAL_REF" = refs/heads/main
test "$ACTUAL_SHA" = "$EXPECTED_SHA"
if [ "$RUN_STAGE" = ownership-approve ] || [ "$RUN_STAGE" = canary-admit-recover ]; then
  test "$GITHUB_ACTOR_ID" = 57728706
  test "$GITHUB_RUN_ATTEMPT" = 1
fi
test "$ACTUAL_SHA" = "$(gh api "repos/${GH_REPO}/git/ref/heads/main" --jq .object.sha)"`

platform_maintenance_private_run := `set -euo pipefail
private_log="$(mktemp)"
trap 'rm -f "$private_log"' EXIT
if ! nix develop --command bash >"$private_log" 2>&1 <<'EOF'
set -euo pipefail
umask 077
talosctl version --client >/dev/null
sha256sum --check --status <<<'dd0ce17cc573acff38974b0dca233a8708adbf2ae988578837adce27823acddb  scripts/ci/platform-maintenance-stage.sh'
bash scripts/ci/platform-maintenance-stage.sh
EOF
then
  echo "::error::Platform stage blocked; private transport, receipt, and cluster diagnostics withheld."
  exit 1
fi
echo "Platform stage completed; private receipts withheld."`

approved_openclaw_operations if {
	dispatch := object.get(workflow_events, "workflow_dispatch", {})
	count(object.keys(workflow_events)) == 1
	protected_workflow_run_settings
	count(dispatch.inputs) == 6
	dispatch.inputs.expected_sha.required == true
	dispatch.inputs.legacy_stage.options == ["none", "inventory", "publish-inventory", "archive", "publish-archive", "verify", "prepare-restore", "resume-restore", "network-preflight", "publish-discord-cache", "transfer-discord-cache"]
	dispatch.inputs.legacy_stage.default == "none"
	dispatch.inputs.enterprise_stage.options == ["none", "bind-installation", "full-sync", "reconcile", "stop", "verification", "restore", "acceptance"]
	dispatch.inputs.enterprise_stage.default == "none"
	count(input.jobs) == 4
	approved_openclaw_legacy_operation
	approved_openclaw_enterprise_operation
}

approved_openclaw_legacy_operation if {
	job := input.jobs.legacy
	job["runs-on"] == "ubuntu-24.04"
	job.needs == ["static-policy"]
	job.environment.name == "homelab-production"
	job.concurrency == {"group": "openclaw-enterprise-operations-production", "cancel-in-progress": false, "queue": "max"}
	job["timeout-minutes"] == 360
	job.permissions == {"actions": "read", "contents": "read", "id-token": "write"}
	job.if == "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main' && inputs.legacy_stage != 'none' && inputs.enterprise_stage == 'none'"
	count(job.steps) == 8
	[job.steps[0].name, job.steps[1].name, job.steps[2].name, job.steps[3].name, job.steps[4].name, job.steps[5].name, job.steps[6].name, job.steps[7].name] == ["Verify Current Main Commit Before Credentials", "Check Out Repository", "Install Nix", "Verify Prior Restore Run", "Verify Protected Inputs", "Verify AWS Role Input", "Configure AWS Credentials", "Run Legacy Stage"]
	job.steps[0].env == {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}
	trim(job.steps[0].run, "\n") == platform_maintenance_main_check
	job.steps[1].uses == "chainguard-actions/actions-checkout@9b08549f11b1cea64a914e482f95fa1413656505"
	job.steps[1].with == {"fetch-depth": 0, "persist-credentials": false}
	job.steps[2].uses == "chainguard-actions/cachix-install-nix-action@043d5ae37e81d3c6b1604becbdc6aefbdc9fa909"
	job.steps[2].with == {"enable_kvm": false, "github_access_token": "${{ secrets.GITHUB_TOKEN }}"}
	provenance := [step | step := job.steps[_]; step.name == "Verify Prior Restore Run"]
	count(provenance) == 1
	provenance[0] == job.steps[3]
	provenance[0].env == {"RUN_STAGE": "${{ inputs.legacy_stage }}", "PRIOR_RUN_ID": "39988927652", "ARCHIVE_REF": "${{ inputs.archive_ref }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "GH_TOKEN": "${{ github.token }}"}
	trim(provenance[0].run, "\n") == openclaw_resume_provenance_run
	credentials := [step | step := job.steps[_]; step.name == "Configure AWS Credentials"]
	count(credentials) == 1
	credentials[0] == job.steps[6]
	credentials[0].if == "inputs.legacy_stage != 'network-preflight'"
	credentials[0]["with"]["role-duration-seconds"] == 25200
	job.steps[4].name == "Verify Protected Inputs"
	job.steps[4].env == {"OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}"}
	trim(job.steps[4].run, "\n") == `test -n "$OCTELIUM_AUTH_TOKEN"`
	job.steps[5].name == "Verify AWS Role Input"
	job.steps[5].if == "inputs.legacy_stage != 'network-preflight'"
	job.steps[5].env == {"AWS_APPLY_ROLE_ARN": "${{ vars.AWS_ROLE_TO_ASSUME_HOMELAB || secrets.AWS_ROLE_TO_ASSUME_HOMELAB }}"}
	trim(job.steps[5].run, "\n") == `test -n "$AWS_APPLY_ROLE_ARN"`
	some step in job.steps
	step.name == "Run Legacy Stage"
	step == job.steps[7]
	step.env == {"RUN_STAGE": "${{ inputs.legacy_stage }}", "BASELINE_REF": "${{ inputs.baseline_ref }}", "ARCHIVE_REF": "${{ inputs.archive_ref }}", "CACHE_REF": "${{ inputs.cache_ref }}", "OPENCLAW_RESUME_PROVENANCE": "${{ runner.temp }}/oce-resume-provenance.json", "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}
	contains(step.run, `export OPENCLAW_PHASE_FILE="${RUNNER_TEMP}/openclaw-phase"`)
	contains(step.run, "set -euo pipefail\numask 077\n")
	contains(step.run, "if [[ \"$RUN_STAGE\" == resume-restore ]]; then\n  export PRIOR_RUN_ID=39988927652\nfi\n")
	contains(step.run, `if [[ "$RUN_STAGE" == network-preflight ]]; then
  printf '%s\n' network-access >"$OPENCLAW_PHASE_FILE"
fi`)
	contains(step.run, `if [[ "$RUN_STAGE" == network-preflight ]]; then
  printf '%s\n' network-source >"$OPENCLAW_PHASE_FILE"
fi`)
	contains(step.run, concat("", [`sha256sum --check --status <<<'4020ebdc7b66a6e74477f4b6ea679e97aed3080bffa64b687936b1fbdbf22aa0  scripts/ci/openclaw-enterprise-operations.sh'`, "\n", `sha256sum --check --status <<<'24e540b78832995a011f37441701dc98167dc905fafb391c098d43e6db41e278  scripts/ci/openclaw-legacy-netns-preflight.py'`, "\n", `sha256sum --check --status <<<'71dffb033928d510d91a252b056ce540c8a377314b44dafb2b732d6fa8822d79  scripts/ci/openclaw-enterprise-upload.py'`, "\n", `sha256sum --check --status <<<'c32a6d36d561e9f3903193aae0bbbea0db66ee4bb19aa146be20ec55605a6708  scripts/ci/openclaw-enterprise-download.py'`, "\n", `sha256sum --check --status <<<'be00c82ecc835d07b2a0da4b002ec075d81e998a6bf98a643269e89d218b3a59  scripts/openclaw-discord-offline-cache.py'`, "\n", `sha256sum --check --status <<<'2f94ac3ba85ed358056672640beb2f1656021e598a944d67760ece086718320b  scripts/ci/openclaw-discord-cache-publication.py'`, "\n", `bash scripts/ci/openclaw-enterprise-operations.sh "$RUN_STAGE"`, "\n"]))
}


approved_openclaw_enterprise_operation if {
	dispatch := object.get(workflow_events, "workflow_dispatch", {})
	count(dispatch.inputs) == 6
	dispatch.inputs.expected_sha.required == true
	dispatch.inputs.enterprise_stage.options == ["none", "bind-installation", "full-sync", "reconcile", "stop", "verification", "restore", "acceptance"]
	dispatch.inputs.enterprise_stage.default == "none"
	input.permissions == {}
	count(input.jobs) == 4
	static := input.jobs["static-policy"]
	static.permissions == {"contents": "read"}
	count(static.steps) == 4
	static.steps[0].env == {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "LEGACY_STAGE": "${{ inputs.legacy_stage }}", "ENTERPRISE_STAGE": "${{ inputs.enterprise_stage }}", "BASELINE_REF": "${{ inputs.baseline_ref }}", "ARCHIVE_REF": "${{ inputs.archive_ref }}", "CACHE_REF": "${{ inputs.cache_ref }}"}
	trim(static.steps[0].run, "\n") == openclaw_dispatch_guard
	contains(static.steps[3].run, "nix develop --command bash scripts/ci/static-checks.sh --offline-verified")
	job := input.jobs.enterprise
	job["runs-on"] == "ubuntu-24.04"
	job["timeout-minutes"] == 150
	job.needs == ["static-policy"]
	job.if == "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main' && inputs.legacy_stage == 'none' && inputs.enterprise_stage != 'none' && inputs.enterprise_stage != 'bind-installation'"
	job.concurrency == {"group": "openclaw-enterprise-operations-production", "cancel-in-progress": false, "queue": "max"}
	job.environment.name == "homelab-production"
	job.permissions == {"contents": "read"}
	count(job.steps) == 5
	[job.steps[0].name, job.steps[1].name, job.steps[2].name, job.steps[3].name, job.steps[4].name] == ["Verify Current Main Commit Before Credentials", "Check Out Repository", "Install Nix", "Recheck Current Main Commit Before Enterprise Stage", "Run Fixed Enterprise Stage"]
	job.steps[0].env == {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}
	trim(job.steps[0].run, "\n") == platform_maintenance_main_check
	job.steps[1].uses == "chainguard-actions/actions-checkout@9b08549f11b1cea64a914e482f95fa1413656505"
	job.steps[1].with["persist-credentials"] == false
	job.steps[1].with["fetch-depth"] == 0
	job.steps[2].uses == "chainguard-actions/cachix-install-nix-action@043d5ae37e81d3c6b1604becbdc6aefbdc9fa909"
	job.steps[2].with == {"enable_kvm": false, "github_access_token": "${{ secrets.GITHUB_TOKEN }}"}
	job.steps[3].env == job.steps[0].env
	trim(job.steps[3].run, "\n") == platform_maintenance_main_check
	job.steps[4].env == {"RUN_STAGE": "${{ inputs.enterprise_stage }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}
	trim(job.steps[4].run, "\n") == openclaw_enterprise_stage_run
	binding := input.jobs.binding
	binding["runs-on"] == "ubuntu-24.04"
	binding.needs == ["static-policy"]
	binding.if == "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main' && inputs.legacy_stage == 'none' && inputs.enterprise_stage == 'bind-installation'"
	binding.concurrency == {"group": "openclaw-enterprise-operations-production", "cancel-in-progress": false, "queue": "max"}
	binding.environment.name == "homelab-production"
	binding.permissions == {"contents": "read"}
	binding["timeout-minutes"] == 30
	count(binding.steps) == 5
	[binding.steps[0].name, binding.steps[1].name, binding.steps[2].name, binding.steps[3].name, binding.steps[4].name] == ["Verify Current Main Commit Before Credentials", "Check Out Repository", "Install Nix", "Recheck Current Main Commit Before Binding", "Bind Reviewed Installation"]
	binding.steps[0].env == job.steps[0].env
	trim(binding.steps[0].run, "\n") == platform_maintenance_main_check
	binding.steps[1].uses == "chainguard-actions/actions-checkout@9b08549f11b1cea64a914e482f95fa1413656505"
	binding.steps[1].with["persist-credentials"] == false
	binding.steps[2].uses == "chainguard-actions/cachix-install-nix-action@043d5ae37e81d3c6b1604becbdc6aefbdc9fa909"
	binding.steps[2].with.enable_kvm == false
	binding.steps[3].env == job.steps[0].env
	trim(binding.steps[3].run, "\n") == platform_maintenance_main_check
	binding.steps[4].env == {"EXPECTED_SHA": "${{ inputs.expected_sha }}", "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}"}
	trim(binding.steps[4].run, "\n") == openclaw_enterprise_binding_run
}

openclaw_dispatch_guard := `set -euo pipefail
test "$ACTUAL_REF" = refs/heads/main
test "${ACTUAL_SHA}" = "${EXPECTED_SHA}"
case "${LEGACY_STAGE}:${ENTERPRISE_STAGE}" in
  inventory:none|publish-inventory:none|archive:none|publish-archive:none|verify:none|prepare-restore:none|resume-restore:none|network-preflight:none|publish-discord-cache:none|transfer-discord-cache:none|none:bind-installation|none:full-sync|none:reconcile|none:stop|none:verification|none:restore|none:acceptance) ;;
  *) echo '::error::Choose exactly one fixed operation stage.'; exit 2 ;;
esac
if [[ "$ENTERPRISE_STAGE" != none ]]; then
  test -z "$BASELINE_REF"
  test -z "$ARCHIVE_REF"
  test -z "$CACHE_REF"
fi
if [[ "$LEGACY_STAGE" != transfer-discord-cache ]]; then
  test -z "$CACHE_REF"
fi
if [[ "$LEGACY_STAGE" == resume-restore ]]; then
  test "$ARCHIVE_REF" = '9f64b56a15c8a1c1b81606e0fa751157b09f47fb/39501240221'
  test -z "$BASELINE_REF"
fi
if [[ "$LEGACY_STAGE" == network-preflight ]]; then
  test -z "$BASELINE_REF"
  test -z "$ARCHIVE_REF"
fi
if [[ "$LEGACY_STAGE" == publish-discord-cache ]]; then
  test -z "$BASELINE_REF"
  test -z "$ARCHIVE_REF"
  test -z "$CACHE_REF"
fi
if [[ "$LEGACY_STAGE" == transfer-discord-cache ]]; then
  [[ "$CACHE_REF" =~ ^[0-9a-f]{40}/[1-9][0-9]*$ ]]
  test -z "$BASELINE_REF"
  test -z "$ARCHIVE_REF"
fi`

openclaw_resume_provenance_run := `set -euo pipefail
if [[ "$RUN_STAGE" == resume-restore ]]; then
  sha256sum --check --status <<<'ac9b3903723c7cede72cb01642b31cdd3a88b31c2cf2e4efe56e282d21af1555  scripts/ci/openclaw-enterprise-resume-provenance.py'
  python3 -I scripts/ci/openclaw-enterprise-resume-provenance.py \
    --prior-run-id "$PRIOR_RUN_ID" --archive-ref "$ARCHIVE_REF" \
    --current-sha "$EXPECTED_SHA" \
    --receipt "${RUNNER_TEMP}/oce-resume-provenance.json"
fi`

openclaw_enterprise_stage_run := `set -euo pipefail
umask 077
private_log="$(mktemp)"
trap 'rm -f "$private_log"' EXIT
if ! {
  sha256sum --check --status <<<'73fb944f151cb4f5e20e2a7c92125e03592f46564c93afe786bc0fe923020cd2  scripts/ci/openclaw-enterprise-stage.sh' &&
  sha256sum --check --status <<<'a88d78253ddde75057b0aa915e5d29f956fe35330384eee9888bf900eea52b73  scripts/ci/openclaw-enterprise-journal-operator.py' &&
  sha256sum --check --status <<<'23c559b68da241fd6658ed46b7af5021368d2990b60d11bb41eb0efd1c21124c  scripts/ci/openclaw-enterprise-full-sync.sh' &&
  timeout 140m nix develop --command bash scripts/ci/openclaw-enterprise-stage.sh "$RUN_STAGE"
} >"$private_log" 2>&1; then
  echo '::error::Enterprise stage blocked; private diagnostics withheld.'
  exit 1
fi
echo 'Enterprise stage passed; private receipts withheld.'`

openclaw_enterprise_binding_run := `set -euo pipefail
umask 077
private_log="$(mktemp)"
chmod 600 "$private_log"
trap 'rm -f "$private_log"' EXIT
if ! {
  ulimit -f 1024 &&
  sha256sum --check --status <<<'fedf388eaee3a30d53858e2e5141b6ed737307c7e9f8e7a0008588056a136996  scripts/openclaw-enterprise-bind-installation.py' &&
  test "$(jq -r '.bootstrap.serviceKeyFile // empty' scripts/config/openclaw-enterprise.json)" = /private/openclaw-enterprise/bootstrap/initial-admin-service-key.json &&
  test -f /private/openclaw-enterprise/bootstrap/initial-admin-service-key.json &&
  test -s /private/openclaw-enterprise/bootstrap/initial-admin-service-key.json &&
  test "$(stat -c '%u:%a' /private/openclaw-enterprise/bootstrap/initial-admin-service-key.json)" = "$(id -u):600" &&
  test -n "$OCTELIUM_AUTH_TOKEN" &&
  timeout 10m nix develop --command bash <<'EOF'
set -euo pipefail
umask 077
bash scripts/ci/install-kubeconfig.sh
python3 -I scripts/openclaw-enterprise-bind-installation.py --expected-sha "$EXPECTED_SHA" --credential-file /private/openclaw-enterprise/bootstrap/initial-admin-service-key.json
EOF
} >"$private_log" 2>&1; then
  echo '::error::Enterprise Installation binding blocked; private diagnostics withheld.'
  exit 1
fi
echo 'Enterprise Installation binding verified; private receipts withheld.'`

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

encrypted_oce_diagnostic(job_name, job, step) if {
	job_name == "publish"
	some command in job.steps
	trim(object.get(command, "run", ""), "\n") == oce_image_private_run
	step == oce_encrypted_diagnostic_step
}

oce_encrypted_diagnostic_step := {
	"name": "Retain Only Encrypted Failure Diagnostic",
	"if": "failure()",
	"uses": "chainguard-actions/actions-upload-artifact@ebf8f2543b7189e9a67dcac1af8cabbc5d7a3fd6",
	"with": {
		"name": "oce-image-error-${{ github.run_id }}-${{ github.run_attempt }}",
		"path": "${{ runner.temp }}/oce-image-error.gpg",
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

protected_workflow_run_settings if {
	not "defaults" in object.keys(input)
	input.env == {"KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com"}
	every _, job in input.jobs {
		not "defaults" in object.keys(job)
		not "env" in object.keys(job)
		every step in job.steps {
			not "shell" in object.keys(step)
			not "working-directory" in object.keys(step)
			env := object.get(step, "env", {})
			not "BASH_ENV" in object.keys(env)
			not "ENV" in object.keys(env)
		}
	}
}

# This checker runs only trusted base-branch code and reads a receipt-only PR
# as bounded API data. Any shape change must also update the exact workflow hash.
native_receipt_provenance_workflow if {
	count(input) == 5
	object.get(input, "name", "") == "Verify Native Chainguard Receipt Provenance"
	object.get(input, "concurrency", {}) == {"group": "native-chainguard-receipt-provenance", "cancel-in-progress": false}
	workflow_events == {
		"push": {"branches": ["main"]},
		"pull_request_target": {"branches": ["main"], "types": ["opened", "reopened", "synchronize", "edited"]},
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
				"ref": "main",
				"fetch-depth": 1,
				"persist-credentials": false,
			},
		},
		{
			"name": "Revalidate Open Pull Requests Against Current Main",
			"env": {"GH_TOKEN": "${{ github.token }}"},
			"run": `set -euo pipefail
umask 077
base_sha="$(git rev-parse HEAD)"
[[ "$(gh api "repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha)" == "$base_sha" ]] || exit 1
token_file="$(mktemp)"
pulls_file="$(mktemp)"
all_heads_file="$(mktemp)"
heads_file="$(mktemp)"
trap 'rm -f "$token_file" "$pulls_file" "$all_heads_file" "$heads_file"' EXIT
printf '%s' "$GH_TOKEN" >"$token_file"
gh api --paginate "repos/${GITHUB_REPOSITORY}/pulls?state=open&base=main&per_page=100" >"$pulls_file"
jq -r '.[].head.sha' "$pulls_file" >"$all_heads_file"
if [[ "$GITHUB_EVENT_NAME" == pull_request_target ]]; then
  event_head="$(jq -er '.pull_request.head.sha' "$GITHUB_EVENT_PATH")"
  [[ "$event_head" =~ ^[0-9a-f]{40}$ ]] || exit 1
  grep -Fxq -- "$event_head" "$all_heads_file" || exit 1
  printf '%s\n' "$event_head" >"$heads_file"
else
  [[ "$GITHUB_EVENT_NAME" == push ]] || exit 1
  while IFS= read -r head_sha; do
    [[ "$head_sha" =~ ^[0-9a-f]{40}$ ]] || exit 1
    # Any unreadable or changed native state still needs verification.
    if python3 -I scripts/ci/harbor-native-chainguard-receipt-import.py native-receipts-unchanged \
      --base-sha "$base_sha" --head-sha "$head_sha" --token-file "$token_file"; then
      continue
    fi
    printf '%s\n' "$head_sha" >>"$heads_file"
  done <"$all_heads_file"
fi
pending_failed=0
while IFS= read -r head_sha; do
  [[ "$head_sha" =~ ^[0-9a-f]{40}$ ]] || exit 1
  marked=0
  for attempt in 1 2 3; do
    if gh api -X POST "repos/${GITHUB_REPOSITORY}/statuses/${head_sha}" \
      -f state=pending -f context='Native Chainguard Receipt Provenance' \
      -f description='Rechecking receipt against current main' >/dev/null; then
      marked=1
      break
    fi
    [[ "$attempt" == 3 ]] || sleep 2
  done
  [[ "$marked" == 1 ]] || pending_failed=1
done <"$heads_file"
[[ "$pending_failed" == 0 ]] || exit 1
[[ "$(gh api "repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha)" == "$base_sha" ]] || exit 0
status_failed=0
while IFS= read -r head_sha; do
  if python3 -I scripts/ci/harbor-native-chainguard-receipt-import.py verify-pull-request \
    --base-sha "$base_sha" --head-sha "$head_sha" \
    --token-file "$token_file" && \
    [[ "$(gh api "repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha)" == "$base_sha" ]]; then
    state=success
  else
    state=failure
  fi
  [[ "$(gh api "repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha)" == "$base_sha" ]] || exit 0
  if ! gh api -X POST "repos/${GITHUB_REPOSITORY}/statuses/${head_sha}" \
    -f state="$state" -f context='Native Chainguard Receipt Provenance' \
    -f description='Protected receipt state verification' >/dev/null; then
    status_failed=1
  fi
done <"$heads_file"
exit "$status_failed"
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

azuread_plan_private_wrapper_start := `private_dir="$(mktemp -d)"
chmod 700 "$private_dir"
private_log="$private_dir/plan.log"
azuread_report="$private_dir/azuread-report.json"
trap 'rm -rf -- "$private_dir"' EXIT
if ! HOMELAB_AZUREAD_PLAN_REPORT_FILE="$azuread_report" nix develop --command bash >"$private_log" 2>&1 <<'EOF'
`

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

# The AzureAD plan report can contain provider diagnostics, so keep it and the
# plan log inside the same private directory and expose only the verified helper.
private_live_output(run) if {
	wrapped := split(run, azuread_plan_private_wrapper_start)
	count(wrapped) == 2
	closed := split(wrapped[1], "\nEOF\n")
	count(closed) == 2
	body := closed[0]
	tail := closed[1]
	sensitive_command_count(body) > 0
	sensitive_command_count(run) == sensitive_command_count(body)
	regex.match(`(?m)^[\t ]*umask[\t ]+077[\t ]*$`, body)
	azuread_plan_private_live_tail(tail)
}

# The PR plan streams the CLI's redacted human output. Its report and saved
# plans remain in private temporary files; allow only this reviewed command.
private_live_output(run) if {
	trim(run, "\n") == visible_terragrunt_plan_run
}

visible_terragrunt_plan_run := `private_dir="$(mktemp -d)"
chmod 700 "$private_dir"
azuread_report="$private_dir/azuread-report.json"
trap 'rm -rf -- "$private_dir"' EXIT
HOMELAB_AZUREAD_PLAN_REPORT_FILE="$azuread_report" nix develop --command bash <<'EOF'
set -euo pipefail
umask 077
echo "::group::Kubeconfig setup"
bash scripts/ci/install-kubeconfig.sh
echo "::group::Kubernetes API check"
kubectl --request-timeout=15s version >/dev/null
echo "::group::Argo CD bootstrap plan"
bash scripts/ci/terragrunt-plan.sh
EOF`

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

private_live_output(run) if {
	trim(run, "\n") == openclaw_enterprise_binding_run
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

private_live_output(run) if {
	trim(run, "\n") == oce_image_private_run
}

oce_image_private_run := `set -euo pipefail
umask 077
private_log="$(mktemp)"
trap 'rm -f "$private_log"' EXIT
if ! nix develop --command bash >"$private_log" 2>&1 <<'EOF'
set -euo pipefail
umask 077
bash scripts/ci/harbor-publish.sh publish-openclaw-enterprise
EOF
then
  python3 -I scripts/ci/harbor-encrypt-diagnostic.py "$private_log" \
    "$RUNNER_TEMP/oce-image-error.gpg" >/dev/null 2>&1 || true
  phase=unclassified
  if [[ -f "$GITHUB_STEP_SUMMARY" ]]; then
    phase_line="$(tail -n 1 "$GITHUB_STEP_SUMMARY")"
    if [[ "$phase_line" == "Enterprise image publication failed at phase: "* ]]; then
      candidate="${phase_line#*phase: }"
      case "$candidate" in
        preflight|private-route|harbor-auth|cleanup|signing-prepare|signing-create|signing-wait|signing-key|signature-verify|receipt|push-controller|push-runtime|push-cli|push-operator|upload-verify-controller|upload-verify-runtime|upload-verify-cli|upload-verify-operator|authenticated-pull-controller|authenticated-pull-runtime|authenticated-pull-cli|authenticated-pull-operator)
          phase="$candidate" ;;
      esac
    fi
  fi
  echo "::error::Enterprise image publication failed at phase: $phase; private transport and registry output withheld."
  exit 1
fi
echo "Pinned Enterprise controller/runtime/CLI/operator images published, signed, and fully pulled; private output withheld."`

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
  harbor)
    bash scripts/ci/harbor-publish.sh mirror-harbor
    ;;
  renovate)
    bash scripts/ci/harbor-publish.sh mirror-renovate
    ;;
  dns)
    bash scripts/ci/harbor-publish.sh mirror-dns
    ;;
  litellm)
    bash scripts/ci/harbor-publish.sh mirror-litellm
    ;;
  prometheus)
    bash scripts/ci/harbor-publish.sh mirror-prometheus
    ;;
  *) exit 2 ;;
esac
EOF
then
  if [[ -f "$public_status" ]] && sha256sum --check --status <<<'0febfbc3f20f53a529ea2a83c451432bcdc20e76c82fae4a03bf307c85d6cef3  scripts/ci/harbor-publish.sh' 2>/dev/null; then
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
	lines == [
		"then",
		`phase="$(cat "$OPENCLAW_PHASE_FILE" 2>/dev/null || true)"`,
		`case "$phase" in preflight|network-access|network-source|network-current-main|network-stopped-reader|network-namespace|network-postcheck|baseline|baseline-s3-read|baseline-mounted-compare|baseline-source-status|publication|publication-lookup|publication-lookup-denied|publication-lookup-failed|publication-lookup-response|publication-archive-result|publication-source-validation|publication-destination-absence|publication-source-size|publication-upload|publication-source-read|publication-s3-create|publication-s3-part|publication-s3-complete|publication-digest|publication-version|publication-archive-head|publication-archive-metadata|publication-receipt-upload|publication-receipt-head|publication-restore-prepare|publication-restore-archive|publication-restore-archive-source-range|publication-restore-archive-reader-transfer|publication-restore-archive-finalize|publication-restore-receipt|publication-restore-receipt-source-range|publication-restore-receipt-reader-transfer|publication-restore-receipt-finalize|verification|verification-archive-download|verification-archive-download-source-range|verification-archive-download-reader-transfer|verification-archive-download-finalize|verification-receipt-download|verification-receipt-download-source-range|verification-receipt-download-reader-transfer|verification-receipt-download-finalize|verification-restore|cache-build|cache-publication|cache-transfer)`,
		`echo "::error::Legacy operation failed in ${phase}; private cluster and archive diagnostics withheld." ;;`,
		`*) echo "::error::Legacy operation failed; private cluster and archive diagnostics withheld." ;;`,
		"esac",
		`rm -f "$OPENCLAW_RESUME_PROVENANCE"`,
		"exit 1",
		"fi",
		`rm -f "$OPENCLAW_RESUME_PROVENANCE"`,
		`echo "Legacy operation completed; private receipts withheld."`,
	]
}

azuread_plan_private_live_tail(tail) if {
	lines := [trim(line, " \t\r") | line := split(tail, "\n")[_]; trim(line, " \t\r") != ""]
	count(lines) == 8
	lines[0] == "then"
	lines[1] == `if sha256sum --check --status <<<'16be86dcc7b37efa6de69d01d093e8d866bf50f2af8f43258f5a17d45f67ecc0  scripts/ci/terragrunt-plan-stage.sh' 2>/dev/null; then`
	lines[2] == `HOMELAB_AZUREAD_PLAN_REPORT_FILE="${azuread_report:-}" bash scripts/ci/terragrunt-plan-stage.sh <"$private_log"`
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
