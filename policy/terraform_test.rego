package main

import rego.v1

test_allows_only_archived_ssm_key_retirement if {
	change := {
		"address": "aws_kms_key.this[0]",
		"type": "aws_kms_key",
		"change": {
			"actions": ["delete"], "after": null,
			"before": {
				"arn": "arn:aws:kms:us-west-2:716182248480:key/d3332190-27f9-4b5b-867d-ccccc3e5efc8",
				"key_id": "d3332190-27f9-4b5b-867d-ccccc3e5efc8",
				"deletion_window_in_days": 30,
			},
		},
	}
	archived_ssm_key_retirement(change)
	violations := deny with input as {"resource_changes": [change]}
	count(violations) == 0
	wrong_key := object.union(change.change.before, {"key_id": "other"})
	not archived_ssm_key_retirement(object.union(change, {"change": object.union(change.change, {"before": wrong_key})}))
	short_window := object.union(change.change.before, {"deletion_window_in_days": 7})
	not archived_ssm_key_retirement(object.union(change, {"change": object.union(change.change, {"before": short_window})}))
	not archived_ssm_key_retirement(object.union(change, {"change": object.union(change.change, {"actions": ["delete", "create"]})}))
}

test_rejects_sensitive_resource_destroy_plans if {
	every resource_type in {"aws_kms_key", "aws_ssm_parameter", "kubernetes_secret", "kubernetes_secret_v1"} {
		plan := {"resource_changes": [{
			"address": sprintf("%s.this", [resource_type]),
			"type": resource_type,
			"change": {"actions": ["delete"], "after": null},
		}]}
		violations := deny with input as plan
		some msg in violations
		contains(msg, "must not delete sensitive resource")
	}
}

test_allows_expected_write_only_external_secrets_auth if {
	plan := secret_plan("kubernetes_secret_v1.this", "aws-ssm-auth", "external-secrets", null, null, 1, true, false)
	violations := deny with input as plan
	count(violations) == 0
}

test_allows_expected_write_only_external_secrets_auth_empty_maps if {
	plan := secret_plan("kubernetes_secret_v1.this", "aws-ssm-auth", "external-secrets", {}, {}, 1, true, false)
	violations := deny with input as plan
	count(violations) == 0
}

test_rejects_readable_external_secrets_auth_data if {
	plan := secret_plan("kubernetes_secret_v1.this", "aws-ssm-auth", "external-secrets", {"access-key-id": "secret"}, null, 1, true, false)
	violations := deny with input as plan
	some msg in violations
	contains(msg, "must not manage raw Kubernetes Secret data")
}

test_rejects_readable_external_secrets_auth_binary_data if {
	plan := secret_plan("kubernetes_secret_v1.this", "aws-ssm-auth", "external-secrets", null, {"credential": "secret"}, 1, true, false)
	violations := deny with input as plan
	some msg in violations
	contains(msg, "must not manage raw Kubernetes Secret data")
}

test_rejects_wrong_write_only_secret if {
	plan := secret_plan("kubernetes_secret_v1.this", "other", "external-secrets", null, null, 1, true, false)
	violations := deny with input as plan
	some msg in violations
	contains(msg, "must not manage raw Kubernetes Secret data")
}

test_rejects_missing_write_only_revision if {
	plan := secret_plan("kubernetes_secret_v1.this", "aws-ssm-auth", "external-secrets", null, null, 0, true, false)
	violations := deny with input as plan
	some msg in violations
	contains(msg, "must not manage raw Kubernetes Secret data")
}

test_rejects_missing_write_only_data_expression if {
	plan := secret_plan("kubernetes_secret_v1.this", "aws-ssm-auth", "external-secrets", null, null, 1, false, false)
	violations := deny with input as plan
	some msg in violations
	contains(msg, "must not manage raw Kubernetes Secret data")
}

test_rejects_wrong_write_only_address if {
	plan := secret_plan("module.other.kubernetes_secret_v1.this", "aws-ssm-auth", "external-secrets", null, null, 1, true, false)
	violations := deny with input as plan
	some msg in violations
	contains(msg, "must not manage raw Kubernetes Secret data")
}

test_rejects_wrong_write_only_namespace if {
	plan := secret_plan("kubernetes_secret_v1.this", "aws-ssm-auth", "default", null, null, 1, true, false)
	violations := deny with input as plan
	some msg in violations
	contains(msg, "must not manage raw Kubernetes Secret data")
}

test_rejects_binary_write_only_revision_expression if {
	plan := secret_plan("kubernetes_secret_v1.this", "aws-ssm-auth", "external-secrets", null, null, 1, true, true)
	violations := deny with input as plan
	some msg in violations
	contains(msg, "must not manage raw Kubernetes Secret data")
}

secret_plan(address, name, namespace, raw_data, raw_binary_data, revision, has_data_wo, has_binary_revision) := {
	"resource_changes": [{
		"address": address,
		"type": "kubernetes_secret_v1",
		"change": {
			"actions": ["create"],
			"after": {
				"metadata": [{
					"name": name,
					"namespace": namespace,
					"labels": {"app.kubernetes.io/managed-by": "terragrunt"},
					"annotations": {"homelab.rst.io/secret-source": "aws-ssm-parameter-store"},
				}],
				"type": "Opaque",
				"data": raw_data,
				"binary_data": raw_binary_data,
				"data_wo_revision": revision,
			},
		},
	}],
	"configuration": {
		"root_module": {
			"resources": [{
				"address": address,
				"mode": "managed",
				"type": "kubernetes_secret_v1",
				"name": "this",
				"expressions": secret_expressions(has_data_wo, has_binary_revision),
			}],
		},
	},
}

secret_expressions(true, false) := {
	"data_wo": {"references": ["local.secret_data"]},
	"data_wo_revision": {"references": ["var.data_revision"]},
	"metadata": {"references": ["var.name", "var.namespace"]},
}

secret_expressions(false, false) := {
	"data_wo_revision": {"references": ["var.data_revision"]},
	"metadata": {"references": ["var.name", "var.namespace"]},
}

secret_expressions(true, true) := {
	"binary_data_wo_revision": {"constant_value": 1},
	"data_wo": {"references": ["local.secret_data"]},
	"data_wo_revision": {"references": ["var.data_revision"]},
	"metadata": {"references": ["var.name", "var.namespace"]},
}
