package main

import rego.v1

sensitive_delete_resource_types := {
	"aws_kms_key",
	"aws_ssm_parameter",
	"kubernetes_secret",
	"kubernetes_secret_v1",
}

deny contains msg if {
	some change in terraform_resource_changes
	change.type in sensitive_delete_resource_types
	action_deletes(change.change.actions)
	msg := sprintf("Terraform plan must not delete sensitive resource %q of type %s", [change.address, change.type])
}

deny contains msg if {
	some change in terraform_resource_changes
	change.type in {"kubernetes_secret", "kubernetes_secret_v1"}
	not action_deletes(change.change.actions)
	msg := sprintf("Terraform resource %q must not manage raw Kubernetes Secret data; use ExternalSecret or CI-injected material", [change.address])
}

deny contains msg if {
	some change in terraform_resource_changes
	change.type == "kubernetes_manifest"
	manifest := planned_after(change).manifest
	manifest.kind == "Secret"
	name := object.get(object.get(manifest, "metadata", {}), "name", "<unknown>")
	msg := sprintf("Terraform resource %q must not manage raw Kubernetes Secret manifest %q", [change.address, name])
}

deny contains msg if {
	some change in terraform_resource_changes
	change.type == "kubernetes_manifest"
	manifest := planned_after(change).manifest
	manifest.kind == "Application"
	source := object.get(object.get(manifest, "spec", {}), "source", {})
	source.repoURL in homelab_repo_urls
	object.get(source, "targetRevision", "") != "main"
	name := object.get(object.get(manifest, "metadata", {}), "name", "<unknown>")
	msg := sprintf("Terraform-planned Application %q must target the homelab repository default branch main", [name])
}

deny contains msg if {
	some change in terraform_resource_changes
	change.type == "kubernetes_manifest"
	manifest := planned_after(change).manifest
	manifest.kind == "Application"
	sources := object.get(object.get(manifest, "spec", {}), "sources", [])
	some index
	source := sources[index]
	source.repoURL in homelab_repo_urls
	object.get(source, "targetRevision", "") != "main"
	name := object.get(object.get(manifest, "metadata", {}), "name", "<unknown>")
	msg := sprintf("Terraform-planned Application %q source %d must target the homelab repository default branch main", [name, index])
}

deny contains msg if {
	some change in terraform_resource_changes
	change.type == "aws_kms_key"
	after := planned_after(change)
	after.enable_key_rotation != true
	msg := sprintf("Terraform resource %q must enable KMS key rotation", [change.address])
}

deny contains msg if {
	some change in terraform_resource_changes
	change.type == "aws_kms_key"
	after := planned_after(change)
	object.get(after, "deletion_window_in_days", 0) < 30
	msg := sprintf("Terraform resource %q must keep a KMS deletion window of at least 30 days", [change.address])
}

deny contains msg if {
	some change in terraform_resource_changes
	change.type == "aws_ssm_parameter"
	after := planned_after(change)
	after.type != "SecureString"
	msg := sprintf("Terraform resource %q must store SSM parameters as SecureString", [change.address])
}

terraform_resource_changes contains change if {
	some index
	change := object.get(input, "resource_changes", [])[index]
}

planned_after(change) := after if {
	after := object.get(object.get(change, "change", {}), "after", null)
	after != null
}

action_deletes(actions) if {
	some action in actions
	action == "delete"
}
