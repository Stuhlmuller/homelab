package main

import rego.v1

delete_parameter(name) := {
	"address": sprintf("aws_ssm_parameter.this[%q]", [name]),
	"index": name,
	"name": "this",
	"mode": "managed",
	"type": "aws_ssm_parameter",
	"provider_name": "registry.opentofu.org/hashicorp/aws",
	"action_reason": "delete_because_each_key",
	"change": {
		"actions": ["delete"],
		"before": {
			"name": name,
			"id": name,
			"arn": sprintf("arn:aws:ssm:us-west-2:716182248480:parameter%s", [name]),
			"type": "SecureString",
		},
		"after": null,
		"after_unknown": {},
	},
}

valid_plan := {
	"format_version": "1.2",
	"errored": false,
	"resource_changes": [
		delete_parameter("/homelab/argocd-image-updater/github-app/id"),
		delete_parameter("/homelab/argocd-image-updater/github-app/installation-id"),
		delete_parameter("/homelab/argocd-image-updater/github-app/private-key"),
		delete_parameter("/homelab/github-actions-runner/registration-token"),
	],
}

first := valid_plan.resource_changes[0]

replace_first(entry) := object.union(valid_plan, {
	"resource_changes": array.concat([entry], array.slice(valid_plan.resource_changes, 1, 4)),
})

add_entry(entry) := object.union(valid_plan, {"resource_changes": array.concat(valid_plan.resource_changes, [entry])})

test_exact_plan_allowed if {
	count(deny) == 0 with input as valid_plan
}

test_noop_with_unchanged_state_allowed if {
	count(deny) == 0 with input as add_entry({
		"address": "aws_iam_policy.retained",
		"change": {"actions": ["no-op"], "before": {"id": "same"}, "after": {"id": "same"}},
	})
}

test_reject_missing_extra_or_duplicate_deletes if {
	every candidate in [
		object.union(valid_plan, {"resource_changes": array.slice(valid_plan.resource_changes, 1, 4)}),
		add_entry(delete_parameter("/homelab/other")),
		replace_first(valid_plan.resource_changes[1]),
	] {
		count(deny) == 1 with input as candidate
	}
}

test_reject_wrong_provider_address_or_cause if {
	every change in [
		{"provider_name": "registry.opentofu.org/other/aws"},
		{"address": "aws_ssm_parameter.generated[\"fixture\"]"},
		{"module_address": "module.other"},
		{"previous_address": "aws_ssm_parameter.this[\"/moved\"]"},
		{"deposed": "prior"},
		{"action_reason": "delete_because_no_resource_config"},
	] {
		count(deny) == 1 with input as replace_first(object.union(first, change))
	}
}

test_reject_wrong_region_account_name_id_or_type if {
	every change in [
		{"arn": replace(first.change.before.arn, "us-west-2", "us-east-1")},
		{"arn": replace(first.change.before.arn, "716182248480", "111111111111")},
		{"name": "/homelab/other"},
		{"id": "/homelab/other"},
		{"type": "String"},
	] {
		entry := object.union(first, {
			"change": object.union(first.change, {"before": object.union(first.change.before, change)}),
		})
		count(deny) == 1 with input as replace_first(entry)
	}
}

test_reject_replacement_after_value_or_unexpected_action if {
	every change in [
		{"actions": ["create", "delete"]},
		{"actions": ["delete", "create"]},
		{"actions": ["forget"]},
		{"after": {"name": "/homelab/other"}},
		{"after_unknown": {"name": true}},
	] {
		count(deny) == 1 with input as replace_first(object.union(first, {"change": object.union(first.change, change)}))
	}
	every actions in [["delete"], ["create"], ["update"], ["read"], ["forget"]] {
		count(deny) == 1 with input as add_entry({"address": "unrelated", "change": {"actions": actions}})
	}
}

test_reject_pseudo_noop_and_moves if {
	every entry in [
		{"address": "a", "change": {"actions": ["no-op"], "before": 1, "after": 2}},
		{"address": first.address, "change": {"actions": ["no-op"], "before": 1, "after": 1}},
		{"address": "a", "previous_address": "b", "change": {"actions": ["no-op"], "before": 1, "after": 1}},
		{"address": "a", "change": {"actions": ["no-op"], "before": 1, "after": 1, "importing": {"id": "existing"}}},
		{"address": "a", "change": {"actions": ["no-op"], "before": 1, "after": 1, "generated_config": "generated"}},
	] {
		count(deny) == 1 with input as add_entry(entry)
	}
}

test_reject_drift_deferred_changes_outputs_and_errored_plan if {
	every change in [
		{"resource_drift": [first]},
		{"deferred_changes": [first]},
		{"action_invocations": [first]},
		{"output_changes": {"output": {"actions": ["update"]}}},
		{"errored": true},
		{"complete": false},
		{"applyable": false},
	] {
		count(deny) == 1 with input as object.union(valid_plan, change)
	}
}
