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
	not write_only_external_secrets_auth(change)
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

write_only_external_secrets_auth(change) if {
	change.address == "kubernetes_secret_v1.this"
	after := planned_after(change)
	metadata := object.get(after, "metadata", [])
	count(metadata) == 1
	metadata[0].name == "aws-ssm-auth"
	metadata[0].namespace == "external-secrets"
	metadata[0].labels["app.kubernetes.io/managed-by"] == "terragrunt"
	metadata[0].annotations["homelab.rst.io/secret-source"] == "aws-ssm-parameter-store"
	object.get(after, "type", "") == "Opaque"
	empty_or_absent_map(after, "data")
	empty_or_absent_map(after, "binary_data")
	object.get(after, "data_wo_revision", 0) >= 1
	some resource in terraform_configuration_resources
	resource.address == change.address
	resource.mode == "managed"
	resource.type == change.type
	expressions := object.get(resource, "expressions", {})
	object_has_key(expressions, "data_wo")
	object_has_key(expressions, "data_wo_revision")
	not object_has_key(expressions, "data")
	not object_has_key(expressions, "binary_data")
	not object_has_key(expressions, "binary_data_wo")
	not object_has_key(expressions, "binary_data_wo_revision")
}

terraform_configuration_resources contains resource if {
	root_module := object.get(object.get(input, "configuration", {}), "root_module", {})
	some index
	resource := object.get(root_module, "resources", [])[index]
}

object_has_key(value, key) if {
	_ := value[key]
}

empty_or_absent_map(value, key) if {
	object.get(value, key, null) == null
}

empty_or_absent_map(value, key) if {
	object.get(value, key, {}) == {}
}

action_deletes(actions) if {
	some action in actions
	action == "delete"
}
