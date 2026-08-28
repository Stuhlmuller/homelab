package main

import rego.v1

homelab_repo_urls := {
	"https://github.com/Stuhlmuller/homelab.git",
	"git@github.com:Stuhlmuller/homelab.git",
}

required_pod_security_labels := {
	"pod-security.kubernetes.io/enforce",
	"pod-security.kubernetes.io/enforce-version",
	"pod-security.kubernetes.io/audit",
	"pod-security.kubernetes.io/audit-version",
	"pod-security.kubernetes.io/warn",
	"pod-security.kubernetes.io/warn-version",
}

deny contains msg if {
	input.kind == "Secret"
	name := object.get(object.get(input, "metadata", {}), "name", "<unknown>")
	msg := sprintf("raw Kubernetes Secret %q must not be committed; use ExternalSecret, encrypted secret material, or a CI-injected secret path", [name])
}

deny contains msg if {
	input.kind == "Namespace"
	metadata := object.get(input, "metadata", {})
	labels := object.get(metadata, "labels", {})
	some key in required_pod_security_labels
	not has_nonempty_label(labels, key)
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("namespace %q must set %s", [name, key])
}

deny contains msg if {
	input.kind == "Namespace"
	metadata := object.get(input, "metadata", {})
	labels := object.get(metadata, "labels", {})
	object.get(labels, "pod-security.kubernetes.io/audit", "") != "restricted"
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("namespace %q must audit Pod Security violations at restricted", [name])
}

deny contains msg if {
	input.kind == "Namespace"
	metadata := object.get(input, "metadata", {})
	labels := object.get(metadata, "labels", {})
	object.get(labels, "pod-security.kubernetes.io/warn", "") != "restricted"
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("namespace %q must warn on Pod Security violations at restricted", [name])
}

deny contains msg if {
	input.kind == "Namespace"
	metadata := object.get(input, "metadata", {})
	labels := object.get(metadata, "labels", {})
	labels["pod-security.kubernetes.io/enforce"] == "privileged"
	annotations := object.get(metadata, "annotations", {})
	not has_nonempty_annotation(annotations, "homelab.rst.io/privileged-namespace-justification")
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("privileged namespace %q must document why privileged Pod Security is required", [name])
}

deny contains msg if {
	metadata := object.get(input, "metadata", {})
	annotations := object.get(metadata, "annotations", {})
	truthy(object.get(annotations, "homelab.rst.io/public-funnel", "false"))
	kind := object.get(input, "kind", "<unknown>")
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("%s %q enables Tailscale Funnel; external callbacks must use the Octelium public connector path instead", [kind, name])
}

deny contains msg if {
	metadata := object.get(input, "metadata", {})
	annotations := object.get(metadata, "annotations", {})
	truthy(object.get(annotations, "homelab.rst.io/public-callback", "false"))
	not truthy(object.get(annotations, "homelab.rst.io/public-callback-reviewed", "false"))
	kind := object.get(input, "kind", "<unknown>")
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("%s %q exposes an unauthenticated callback path without homelab.rst.io/public-callback-reviewed=true", [kind, name])
}

deny contains msg if {
	metadata := object.get(input, "metadata", {})
	annotations := object.get(metadata, "annotations", {})
	truthy(object.get(annotations, "homelab.rst.io/public-callback", "false"))
	not has_nonempty_annotation(annotations, "homelab.rst.io/public-callback-purpose")
	kind := object.get(input, "kind", "<unknown>")
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("%s %q exposes an unauthenticated callback path without homelab.rst.io/public-callback-purpose", [kind, name])
}

deny contains msg if {
	public_external_route
	not octelium_access_plane
	kind := object.get(input, "kind", "<unknown>")
	name := object.get(object.get(input, "metadata", {}), "name", "<unknown>")
	msg := sprintf("%s %q exposes a public route and must declare homelab.rst.io/access-plane=octelium", [kind, name])
}

deny contains msg if {
	input.kind == "Application"
	spec := object.get(input, "spec", {})
	source := object.get(spec, "source", {})
	source.repoURL in homelab_repo_urls
	object.get(source, "targetRevision", "") != "main"
	name := object.get(object.get(input, "metadata", {}), "name", "<unknown>")
	msg := sprintf("Application %q must target the homelab repository default branch main", [name])
}

deny contains msg if {
	input.kind == "Application"
	spec := object.get(input, "spec", {})
	sources := object.get(spec, "sources", [])
	some index
	source := sources[index]
	source.repoURL in homelab_repo_urls
	object.get(source, "targetRevision", "") != "main"
	name := object.get(object.get(input, "metadata", {}), "name", "<unknown>")
	msg := sprintf("Application %q source %d must target the homelab repository default branch main", [name, index])
}

deny contains msg if {
	cordium_bootstrap_application
	annotations := object.get(object.get(input, "metadata", {}), "annotations", {})
	object.get(annotations, "argocd.argoproj.io/hook", "") != ""
	msg := "Application cordium-bootstrap must be a normal resource, not a hook"
}

deny contains msg if {
	cordium_bootstrap_application
	annotations := object.get(object.get(input, "metadata", {}), "annotations", {})
	object.get(annotations, "argocd.argoproj.io/sync-wave", "") != "1"
	msg := "Application cordium-bootstrap must run at parent Sync wave 1"
}

deny contains msg if {
	cordium_bootstrap_application
	object.get(object.get(input, "metadata", {}), "finalizers", []) != ["resources-finalizer.argocd.argoproj.io"]
	msg := "Application cordium-bootstrap must cascade tracked bootstrap resources on removal"
}

deny contains msg if {
	cordium_bootstrap_application
	source := object.get(object.get(input, "spec", {}), "source", {})
	object.get(source, "path", "") != "clusters/homelab/apps/cordium-bootstrap"
	msg := "Application cordium-bootstrap must isolate the bootstrap source path"
}

deny contains msg if {
	cordium_bootstrap_application
	sync_policy := object.get(object.get(input, "spec", {}), "syncPolicy", {})
	retry := object.get(sync_policy, "retry", {})
	object.get(retry, "limit", -1) != 0
	msg := "Application cordium-bootstrap must disable retries so every genesis attempt gets a fresh operation timeout"
}

deny contains msg if {
	cordium_genesis_bootstrap_identity
	annotations := object.get(object.get(input, "metadata", {}), "annotations", {})
	object.get(annotations, "argocd.argoproj.io/hook", "") != "PostSync"
	msg := sprintf("%s cordium-genesis must be a PostSync hook so bootstrap privilege does not exist during normal Sync", [input.kind])
}

deny contains msg if {
	cordium_genesis_bootstrap_identity
	annotations := object.get(object.get(input, "metadata", {}), "annotations", {})
	object.get(annotations, "argocd.argoproj.io/hook-delete-policy", "") != "BeforeHookCreation"
	msg := sprintf("%s cordium-genesis must use BeforeHookCreation for repeatable bootstrap", [input.kind])
}

deny contains msg if {
	cordium_genesis_bootstrap_identity
	annotations := object.get(object.get(input, "metadata", {}), "annotations", {})
	object.get(annotations, "argocd.argoproj.io/sync-wave", "") != "-1"
	msg := sprintf("%s cordium-genesis must run immediately before genesis at PostSync wave -1", [input.kind])
}

deny contains msg if {
	cordium_genesis_cleanup_role
	rules := object.get(input, "rules", [])
	count(rules) != 1
	msg := sprintf("%s cordium-genesis-cleanup must have exactly one least-privilege rule", [input.kind])
}

deny contains msg if {
	cordium_genesis_cleanup_role
	rule := object.get(input, "rules", [])[_]
	not cordium_genesis_cleanup_rule_allowed(input.kind, rule)
	msg := sprintf("%s cordium-genesis-cleanup may only delete the named cordium-genesis bootstrap resource", [input.kind])
}

deny contains msg if {
	input.kind == "Job"
	metadata := object.get(input, "metadata", {})
	object.get(metadata, "name", "") == "cordium-genesis-cleanup"
	annotations := object.get(metadata, "annotations", {})
	object.get(annotations, "argocd.argoproj.io/hook", "") != "PostSync,SyncFail"
	msg := "Job cordium-genesis-cleanup must run as both PostSync and SyncFail"
}

deny contains msg if {
	input.kind == "Job"
	metadata := object.get(input, "metadata", {})
	object.get(metadata, "name", "") == "cordium-genesis-cleanup"
	annotations := object.get(metadata, "annotations", {})
	object.get(annotations, "argocd.argoproj.io/hook-delete-policy", "") != "BeforeHookCreation,HookSucceeded"
	msg := "Job cordium-genesis-cleanup must use BeforeHookCreation,HookSucceeded for repeatable cleanup"
}

deny contains msg if {
	input.kind == "Job"
	metadata := object.get(input, "metadata", {})
	object.get(metadata, "name", "") == "cordium-genesis-cleanup"
	annotations := object.get(metadata, "annotations", {})
	object.get(annotations, "argocd.argoproj.io/sync-wave", "") != "1"
	msg := "Job cordium-genesis-cleanup must run at wave 1"
}

deny contains msg if {
	input.kind == "Job"
	metadata := object.get(input, "metadata", {})
	object.get(metadata, "name", "") == "cordium-genesis-cleanup"
	pod_spec := object.get(object.get(object.get(input, "spec", {}), "template", {}), "spec", {})
	object.get(pod_spec, "serviceAccountName", "") != "cordium-genesis-cleanup"
	msg := "Job cordium-genesis-cleanup must use its dedicated cleanup ServiceAccount"
}

deny contains msg if {
	input.kind == "Job"
	metadata := object.get(input, "metadata", {})
	object.get(metadata, "name", "") == "cordium-genesis-cleanup"
	pod_spec := object.get(object.get(object.get(input, "spec", {}), "template", {}), "spec", {})
	object.get(pod_spec, "automountServiceAccountToken", false) != true
	msg := "Job cordium-genesis-cleanup must mount its dedicated ServiceAccount token"
}

deny contains msg if {
	input.kind == "Job"
	metadata := object.get(input, "metadata", {})
	object.get(metadata, "name", "") == "cordium-genesis"
	spec := object.get(input, "spec", {})
	object.get(spec, "activeDeadlineSeconds", 0) != 720
	msg := "Job cordium-genesis must fail after 720 seconds so SyncFail cleanup runs before the Argo CD timeout"
}

cordium_genesis_bootstrap_identity if {
	input.kind in {"ServiceAccount", "ClusterRole", "ClusterRoleBinding"}
	object.get(object.get(input, "metadata", {}), "name", "") == "cordium-genesis"
}

cordium_bootstrap_application if {
	input.kind == "Application"
	object.get(object.get(input, "metadata", {}), "name", "") == "cordium-bootstrap"
}

cordium_genesis_cleanup_role if {
	input.kind in {"Role", "ClusterRole"}
	object.get(object.get(input, "metadata", {}), "name", "") == "cordium-genesis-cleanup"
}

cordium_genesis_cleanup_rule_allowed("Role", rule) if {
	rule == {
		"apiGroups": [""],
		"resources": ["serviceaccounts"],
		"resourceNames": ["cordium-genesis"],
		"verbs": ["delete"],
	}
}

cordium_genesis_cleanup_rule_allowed("ClusterRole", rule) if {
	rule == {
		"apiGroups": ["rbac.authorization.k8s.io"],
		"resources": ["clusterroles", "clusterrolebindings"],
		"resourceNames": ["cordium-genesis"],
		"verbs": ["delete"],
	}
}

has_nonempty_annotation(annotations, key) if {
	value := object.get(annotations, key, "")
	count(trim(value, " ")) > 0
}

has_nonempty_label(labels, key) if {
	value := object.get(labels, key, "")
	count(trim(value, " ")) > 0
}

truthy(value) if {
	lower(sprintf("%v", [value])) == "true"
}

octelium_access_plane if {
	annotations := object.get(object.get(input, "metadata", {}), "annotations", {})
	object.get(annotations, "homelab.rst.io/access-plane", "") == "octelium"
}

public_external_route if {
	input.kind == "VirtualService"
	gateway := object.get(object.get(input, "spec", {}), "gateways", [])[_]
	gateway != "mesh"
}

public_external_route if {
	input.kind == "Gateway"
}

public_external_route if {
	input.kind == "Ingress"
	object.get(object.get(input, "spec", {}), "ingressClassName", "") != "compass-discovery"
}

external_secret_allowed_prefixes := {
	"ai": {"/homelab/litellm/", "/homelab/multica/", "/homelab/openclaw/", "/homelab/grafana/openclaw-alert-hook-token"},
	"affine": {"/homelab/affine/"},
	"argocd": {"/homelab/argocd/"},
	"automation": {"/homelab/n8n/", "/homelab/policy-bot/"},
	"cert-manager": {"/homelab/cert-manager/"},
	"github-actions-runner": {"/homelab/github-actions-runner/"},
	"media": {"/homelab/deluge/", "/homelab/media-postgres/"},
	"monitoring": {"/homelab/grafana/"},
	"nofx": {"/homelab/nofx/"},
	"octelium": {"/homelab/cordium/"},
	"octelium-client": {"/homelab/octelium/"},
	"octelium-public": {"/homelab/octelium/"},
	"octelium-storage": {"/homelab/octelium/"},
	"tailscale": {"/homelab/tailscale/"},
}

deny contains msg if {
	input.kind == "ExternalSecret"
	metadata := object.get(input, "metadata", {})
	namespace := object.get(metadata, "namespace", "default")
	allowed := external_secret_allowed_prefixes[namespace]
	key := external_secret_remote_keys(input)[_]
	not remote_ref_key_allowed(key, allowed)
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("ExternalSecret %q in namespace %q references SSM key %q outside its allowed application prefixes", [name, namespace, key])
}

deny contains msg if {
	input.kind == "ExternalSecret"
	metadata := object.get(input, "metadata", {})
	namespace := object.get(metadata, "namespace", "default")
	not external_secret_allowed_prefixes[namespace]
	name := object.get(metadata, "name", "<unknown>")
	msg := sprintf("ExternalSecret %q uses ClusterSecretStore in namespace %q without an approved SSM prefix policy", [name, namespace])
}

deny contains msg if {
	input.kind == "ExternalSecret"
	metadata := object.get(input, "metadata", {})
	item := object.get(object.get(input, "spec", {}), "dataFrom", [])[_]
	find := object.get(item, "find", {})
	count(find) > 0
	path := object.get(find, "path", "")
	count(trim(path, " ")) == 0
	name := object.get(metadata, "name", "<unknown>")
	namespace := object.get(metadata, "namespace", "default")
	msg := sprintf("ExternalSecret %q in namespace %q uses dataFrom.find without a scoped SSM path", [name, namespace])
}

remote_ref_key_allowed(key, allowed) if {
	some allowed_key in allowed
	endswith(allowed_key, "/")
	startswith(key, allowed_key)
}

remote_ref_key_allowed(key, allowed) if {
	some allowed_key in allowed
	not endswith(allowed_key, "/")
	key == allowed_key
}

external_secret_remote_keys(secret) := keys if {
	spec := object.get(secret, "spec", {})
	data_keys := [key |
		item := object.get(spec, "data", [])[_]
		key := object.get(object.get(item, "remoteRef", {}), "key", "")
		key != ""
	]
	extract_keys := [key |
		item := object.get(spec, "dataFrom", [])[_]
		key := object.get(object.get(item, "extract", {}), "key", "")
		key != ""
	]
	find_keys := [key |
		item := object.get(spec, "dataFrom", [])[_]
		key := object.get(object.get(item, "find", {}), "path", "")
		key != ""
	]
	keys := array.concat(array.concat(data_keys, extract_keys), find_keys)
}
