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
		replace(harbor_mirror_private_run, "142b09d057099c3271a5fd211659c48a4c2097d407cebe3fc8e3289c6d62b66b", "0000000000000000000000000000000000000000000000000000000000000000"),
		replace(harbor_mirror_private_run, "scripts/ci/harbor-publish.sh'", "scripts/ci/other.sh'"),
		replace(harbor_mirror_private_run, "harbor-publish.sh mirror", "harbor-publish.sh publish"),
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
