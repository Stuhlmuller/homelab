# Candidate shape check for a future, separately protected SSM retirement lane.
# Ordinary Conftest selects policy/ and never loads this package.
package main

import rego.v1

parameter_names := {
	"/homelab/github-actions-runner/registration-token",
	"/homelab/argocd-image-updater/github-app/id",
	"/homelab/argocd-image-updater/github-app/installation-id",
	"/homelab/argocd-image-updater/github-app/private-key",
}

deny contains "SSM retirement needs exactly four specified SecureString deletions and no other changes" if {
	not retirement_plan
}

retirement_plan if {
	input.format_version == "1.2"
	input.errored == false
	object.get(input, "complete", true) == true
	object.get(input, "applyable", true) == true
	count(object.get(input, "resource_drift", [])) == 0
	count(object.get(input, "deferred_changes", [])) == 0
	count(object.get(input, "action_invocations", [])) == 0
	count(object.get(input, "output_changes", {})) == 0
	is_array(input.resource_changes)
	count({item.address | some item in input.resource_changes; is_string(item.address)}) == count(input.resource_changes)
	every item in input.resource_changes {
		object.get(item.change, "importing", null) == null
		object.get(item.change, "generated_config", null) == null
		allowed_change(item)
	}
	deletes := [item | some item in input.resource_changes; item.change.actions == ["delete"]]
	count(deletes) == count(parameter_names)
	{item.index | some item in deletes} == parameter_names
}

allowed_change(item) if approved_delete(item)

allowed_change(item) if {
	item.change.actions == ["no-op"]
	item.change.before == item.change.after
	object.get(item.change, "after_unknown", {}) == {}
	object.get(item, "previous_address", item.address) == item.address
	object.get(item, "deposed", "") == ""
}

approved_delete(item) if {
	item.index in parameter_names
	item.address == sprintf("aws_ssm_parameter.this[%q]", [item.index])
	item.mode == "managed"
	item.type == "aws_ssm_parameter"
	item.name == "this"
	item.provider_name in {"registry.terraform.io/hashicorp/aws", "registry.opentofu.org/hashicorp/aws"}
	object.get(item, "module_address", "") == ""
	object.get(item, "deposed", "") == ""
	object.get(item, "previous_address", item.address) == item.address
	item.action_reason == "delete_because_each_key"
	item.change.actions == ["delete"]
	item.change.before.name == item.index
	item.change.before.id == item.index
	item.change.before.type == "SecureString"
	item.change.before.arn == sprintf("arn:aws:ssm:us-west-2:716182248480:parameter%s", [item.index])
	item.change.after == null
	object.get(item.change, "after_unknown", {}) == {}
}
