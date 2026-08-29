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
	violations := deny with input as workflow_with_live_run(`nix develop --command kubectl kustomize "$overlay" >/dev/null 2>&1`)
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
	contains(artifact_msg, "must not upload public-repository artifacts")
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
	base := workflow_with_live_run(withheld_live_run)
	workflow := object.union(base, {"jobs": {"test": object.union(base.jobs.test, {
		"steps": array.concat(base.jobs.test.steps, [{"uses": "actions/upload-artifact@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]),
	})}})
	violations := deny with input as workflow
	some msg in violations
	contains(msg, "must not upload public-repository artifacts")
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
		"steps": [{"run": run, "env": {
			"KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com",
			"OCTELIUM_AUTH_TOKEN": "test",
		}}],
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

test_rejects_public_artifact_upload if {
	violations := deny with input as workflow_with_step({"uses": "actions/upload-artifact@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
	some msg in violations
	contains(msg, "must not upload public-repository artifacts")
}

test_rejects_pages_artifact_upload if {
	violations := deny with input as workflow_with_step({"uses": "actions/upload-pages-artifact@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
	some msg in violations
	contains(msg, "must not upload public-repository artifacts")
}

test_rejects_local_composite_action if {
	violations := deny with input as workflow_with_step({"uses": "./.github/actions/public-artifact-wrapper"})
	some msg in violations
	contains(msg, "must not upload public-repository artifacts")
}

test_rejects_local_reusable_workflow if {
	violations := deny with input as {
		"name": "Local reusable workflow",
		"jobs": {"fixture": {"uses": "./.github/workflows/public-artifact-wrapper.yml"}},
	}
	some msg in violations
	contains(msg, "must not call a local workflow")
}

test_rejects_direct_grafana_diagnostics_with_actions_override if {
	violations := deny with input as workflow_with_step({"run": "GITHUB_ACTIONS=false bash scripts/grafana-diagnostics.sh"})
	some msg in violations
	contains(msg, "must not invoke private Grafana diagnostics")
}

test_rejects_literal_indirect_grafana_diagnostics if {
	violations := deny with input as workflow_with_step({"run": `diagnostics=scripts/grafana-diagnostics
GITHUB_ACTIONS=false bash "${diagnostics}.sh"`})
	some msg in violations
	contains(msg, "must not invoke private Grafana diagnostics")
}

test_rejects_backslash_grafana_diagnostics if {
	violations := deny with input as workflow_with_step({"run": `GITHUB_ACTIONS=false bash scripts/grafana\-diagnostics.sh`})
	some msg in violations
	contains(msg, "must not invoke private Grafana diagnostics")
}

test_rejects_parameter_concatenated_grafana_diagnostics if {
	violations := deny with input as workflow_with_step({"run": "GITHUB_ACTIONS=false bash scripts/grafana${EMPTY}-diagnostics.sh"})
	some msg in violations
	contains(msg, "must not invoke private Grafana diagnostics")
}

test_rejects_unbraced_parameter_grafana_diagnostics if {
	violations := deny with input as workflow_with_step({"run": "GITHUB_ACTIONS=false bash scripts/grafana$EMPTY-diagnostics.sh"})
	some msg in violations
	contains(msg, "must not invoke private Grafana diagnostics")
}

test_rejects_kubernetes_yaml_output if {
	violations := deny with input as workflow_with_step({"run": "kubectl get pods -o yaml"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_multiline_kubernetes_logs if {
	violations := deny with input as workflow_with_step({"run": "kubectl -n monitoring \\\nlogs grafana"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_stderr_only_suppression if {
	violations := deny with input as workflow_with_step({"run": "kubectl get pods -o yaml 2>/dev/null"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_later_unsuppressed_command if {
	violations := deny with input as workflow_with_step({"run": "kubectl get pods >/dev/null; kubectl get secrets -o yaml"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_version_argument_bypass if {
	violations := deny with input as workflow_with_step({"run": "kubectl get secret version -o yaml"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_apply_object_output if {
	violations := deny with input as workflow_with_step({"run": "kubectl apply --dry-run=server -f secret.yaml -o yaml"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_allows_kubernetes_version_probe if {
	violations := deny with input as workflow_with_step({"run": "kubectl --request-timeout=15s version >/dev/null 2>&1"})
	count(violations) == 0
}

test_allows_absolute_kubernetes_version_probe if {
	violations := deny with input as workflow_with_step({"run": "/usr/bin/kubectl --request-timeout=15s version >/dev/null 2>&1"})
	count(violations) == 0
}

test_rejects_absolute_kubernetes_output if {
	violations := deny with input as workflow_with_step({"run": "/usr/bin/kubectl get secrets >/dev/null 2>&1"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_concatenated_kubernetes_executable if {
	violations := deny with input as workflow_with_step({"run": "kube'ctl' get secrets >/dev/null 2>&1"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_empty_ansi_quote_kubernetes_executable if {
	violations := deny with input as workflow_with_step({"run": "kube$''ctl get secrets >/dev/null 2>&1"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_backslash_kubernetes_executable if {
	violations := deny with input as workflow_with_step({"run": `kube\ctl get secrets >/dev/null 2>&1`})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_backtick_kubernetes_substitution if {
	violations := deny with input as workflow_with_step({"run": "echo `kubectl get secrets -o yaml`"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_parameter_concatenated_kubernetes_executable if {
	violations := deny with input as workflow_with_step({"run": "kube${EMPTY}ctl get secrets >/dev/null 2>&1"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_unbraced_parameter_kubernetes_executable if {
	violations := deny with input as workflow_with_step({"run": "kub\"$EMPTY\"ectl get secrets >/dev/null 2>&1"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_stdout_only_kubernetes_version_probe if {
	violations := deny with input as workflow_with_step({"run": "kubectl --request-timeout=15s version >/dev/null"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_quoted_kubernetes_redirection_operator if {
	violations := deny with input as workflow_with_step({"run": "kubectl --request-timeout=15s version >/dev/null '2>&1'"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_kubernetes_redirection_reroute if {
	violations := deny with input as workflow_with_step({"run": "kubectl --request-timeout=15s version >/dev/null 2>&1 >>\"$GITHUB_STEP_SUMMARY\""})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_kubernetes_stderr_reroute if {
	violations := deny with input as workflow_with_step({"run": "kubectl --request-timeout=15s version >/dev/null 1>&2"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_suppressed_kubernetes_existence_check if {
	violations := deny with input as workflow_with_step({"run": "if kubectl -n external-secrets get secret aws-ssm-auth >/dev/null 2>&1; then true; fi"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

test_rejects_suppressed_kubernetes_apply if {
	violations := deny with input as workflow_with_step({"run": "kubectl apply -f namespace.yaml >/dev/null 2>&1"})
	some msg in violations
	contains(msg, "must not emit unapproved Kubernetes command output")
}

workflow_with_step(step) := {
	"name": "Public Output Fixture",
	"jobs": {"fixture": {"steps": [object.union(step, {"env": {
		"KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com",
		"OCTELIUM_AUTH_TOKEN": "test",
	}})]}},
}
