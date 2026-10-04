package main

import rego.v1

test_wazuh_deletions_require_external_retirement_capability if {
	changes := [wazuh_retirement_change(name) |
		some name in {"indexer-admin-password", "api-password", "dashboard-password", "agent-enrollment-password"}
	]
	ordinary := deny with input as {"resource_changes": changes}
	count(ordinary) == 4
	input_only := deny with input as {"resource_changes": changes, "wazuh_retirement": true}
	count(input_only) == 4
	every capability in [false, null, "true", 1, {"authorized": true}] {
		violations := deny with input as {"resource_changes": changes} with data.wazuh_retirement as capability
		count(violations) == 4
	}
}

test_allows_four_wazuh_parameter_retirements if {
	changes := [wazuh_retirement_change(name) |
		some name in {"indexer-admin-password", "api-password", "dashboard-password", "agent-enrollment-password"}
	]
	count(changes) == 4
	every change in changes {
		wazuh_ssm_parameter_retirement(change) with data.wazuh_retirement as true
	}
	violations := deny with input as {"resource_changes": changes} with data.wazuh_retirement as true
	count(violations) == 0
}

test_rejects_other_wazuh_parameter_addresses_and_resource_types if {
	change := wazuh_retirement_change("api-password")
	patches := [
		{"address": "aws_ssm_parameter.this[\"/homelab/wazuh/api-password\"]"},
		{"address": "module.other.aws_ssm_parameter.generated[\"/homelab/wazuh/api-password\"]"},
		{"address": "aws_ssm_parameter.generated[\"/homelab/wazuh/dashboard-password\"]"},
		{"type": "aws_kms_key"},
		{"type": "kubernetes_secret"},
		{"type": "kubernetes_secret_v1"},
	]
	every patch in patches {
		candidate := object.union(change, patch)
		not wazuh_ssm_parameter_retirement(candidate) with data.wazuh_retirement as true
		violations := deny with input as {"resource_changes": [candidate]} with data.wazuh_retirement as true
		some msg in violations
		contains(msg, "must not delete sensitive resource")
	}
	not wazuh_ssm_parameter_retirement(object.union(change, {"type": "other_resource"})) with data.wazuh_retirement as true
}

test_rejects_other_wazuh_parameter_identities if {
	change := wazuh_retirement_change("api-password")
	patches := [
		{"name": "/homelab/wazuh/dashboard-password"},
		{"name": "/homelab/other/api-password"},
		{"type": "String"},
		{"region": "us-east-1"},
		{"arn": "arn:aws:ssm:us-east-1:716182248480:parameter/homelab/wazuh/api-password"},
		{"arn": "arn:aws:ssm:us-west-2:000000000000:parameter/homelab/wazuh/api-password"},
		{"arn": "arn:aws:ssm:us-west-2:716182248480:parameter/homelab/wazuh/dashboard-password"},
	]
	invalid_before := array.concat(
		[object.union(change.change.before, patch) | some patch in patches],
		[object.remove(change.change.before, {field}) | some field in {"name", "type", "region", "arn"}],
	)
	every before in invalid_before {
		candidate := {
			"address": change.address, "type": change.type,
			"change": {"actions": ["delete"], "after": null, "before": before},
		}
		not wazuh_ssm_parameter_retirement(candidate) with data.wazuh_retirement as true
		violations := deny with input as {"resource_changes": [candidate]} with data.wazuh_retirement as true
		some msg in violations
		contains(msg, "must not delete sensitive resource")
	}
}

test_rejects_other_parameter_names_and_wazuh_prefixes if {
	every name in {"password", "api-password/extra", "../other/api-password", "api-password-extra"} {
		change := wazuh_retirement_change(name)
		not wazuh_ssm_parameter_retirement(change) with data.wazuh_retirement as true
		violations := deny with input as {"resource_changes": [change]} with data.wazuh_retirement as true
		some msg in violations
		contains(msg, "must not delete sensitive resource")
	}
}

test_rejects_wazuh_parameter_replacements_and_nonnull_after if {
	change := wazuh_retirement_change("api-password")
	every patch in [{"actions": ["delete", "create"]}, {"actions": ["create", "delete"]}, {"after": {}}] {
		candidate := object.union(change, {"change": object.union(change.change, patch)})
		not wazuh_ssm_parameter_retirement(candidate) with data.wazuh_retirement as true
		violations := deny with input as {"resource_changes": [candidate]} with data.wazuh_retirement as true
		some msg in violations
		contains(msg, "must not delete sensitive resource")
	}
	not wazuh_ssm_parameter_retirement({
		"address": change.address, "type": change.type,
		"change": object.remove(change.change, {"after"}),
	}) with data.wazuh_retirement as true
	not wazuh_ssm_parameter_retirement(object.union(change, {"change": object.union(change.change, {"actions": ["create"]})})) with data.wazuh_retirement as true
}

wazuh_retirement_change(name) := {
	"address": sprintf("aws_ssm_parameter.generated[\"/homelab/wazuh/%s\"]", [name]),
	"type": "aws_ssm_parameter",
	"change": {
		"actions": ["delete"], "after": null,
		"before": {
			"name": sprintf("/homelab/wazuh/%s", [name]),
			"type": "SecureString",
			"region": "us-west-2",
			"arn": sprintf("arn:aws:ssm:us-west-2:716182248480:parameter/homelab/wazuh/%s", [name]),
		},
	},
}

test_legacy_retirement_excludes_active_opentofu_key if {
	before := {
		"arn": "arn:aws:kms:us-west-2:716182248480:key/959539ca-5646-435c-8ae4-aec13b0f0607",
		"key_id": "959539ca-5646-435c-8ae4-aec13b0f0607",
		"deletion_window_in_days": 30,
	}
	change := {
		"address": "aws_kms_key.legacy[0]", "type": "aws_kms_key",
		"change": {"actions": ["delete"], "after": null, "before": before},
	}
	archived_legacy_key_retirement(change)
	violations := deny with input as {"resource_changes": [change]}
	count(violations) == 0
	active := object.union(before, {
		"arn": "arn:aws:kms:us-east-1:716182248480:key/3e554210-f903-4175-b547-11adae504a99",
		"key_id": "3e554210-f903-4175-b547-11adae504a99",
	})
	active_change := object.union(change, {"change": object.union(change.change, {"before": active})})
	active_violations := deny with input as {"resource_changes": [active_change]}
	some msg in active_violations
	contains(msg, "must not delete sensitive resource")
	not archived_legacy_key_retirement(object.union(change, {"change": object.union(change.change, {"before": object.union(before, {"deletion_window_in_days": 7})})}))
}

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
