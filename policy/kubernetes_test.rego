package main

import rego.v1

test_rejects_tailscale_subnet_router if {
	violations := deny with input as {
		"apiVersion": "tailscale.com/v1alpha1",
		"kind": "Connector",
		"metadata": {"name": "homelab-exit-node"},
		"spec": {"exitNode": true, "subnetRouter": {"advertiseRoutes": ["10.1.0.0/24"]}},
	}
	some msg in violations
	contains(msg, "homelab access must use Octelium")
}

test_rejects_tailscale_app_connector if {
	violations := deny with input as {
		"apiVersion": "tailscale.com/v1alpha1",
		"kind": "Connector",
		"metadata": {"name": "app-connector"},
		"spec": {"appConnector": {}},
	}
	some msg in violations
	contains(msg, "only exit-node egress is allowed")
}

test_rejects_tailscale_ingress if {
	violations := deny with input as {
		"apiVersion": "networking.k8s.io/v1",
		"kind": "Ingress",
		"metadata": {"name": "tailnet-app"},
		"spec": {"ingressClassName": "tailscale"},
	}
	some msg in violations
	contains(msg, "exposes homelab access through Tailscale")
}

test_rejects_tailscale_load_balancer if {
	violations := deny with input as {
		"apiVersion": "v1",
		"kind": "Service",
		"metadata": {"name": "tailnet-app"},
		"spec": {"type": "LoadBalancer", "loadBalancerClass": "tailscale"},
	}
	some msg in violations
	contains(msg, "exposes homelab access through Tailscale")
}

test_rejects_tailscale_expose_annotation if {
	violations := deny with input as {
		"apiVersion": "v1",
		"kind": "Service",
		"metadata": {"name": "tailnet-app", "annotations": {"tailscale.com/expose": "true"}},
		"spec": {},
	}
	some msg in violations
	contains(msg, "exposes homelab access through Tailscale")
}

test_rejects_tailscale_fqdn_egress_service if {
	violations := deny with input as {
		"apiVersion": "v1",
		"kind": "Service",
		"metadata": {"name": "tailnet-egress", "annotations": {"tailscale.com/tailnet-fqdn": "db.example.com"}},
		"spec": {},
	}
	some msg in violations
	contains(msg, "only exit-node egress is allowed")
}

test_rejects_tailscale_ip_egress_service if {
	violations := deny with input as {
		"apiVersion": "v1",
		"kind": "Service",
		"metadata": {"name": "tailnet-egress", "annotations": {"tailscale.com/tailnet-ip": "100.64.0.1"}},
		"spec": {},
	}
	some msg in violations
	contains(msg, "only exit-node egress is allowed")
}

test_rejects_tailscale_legacy_ip_egress_service if {
	violations := deny with input as {
		"apiVersion": "v1",
		"kind": "Service",
		"metadata": {"name": "tailnet-egress", "annotations": {"tailscale.com/ts-tailnet-target-ip": "100.64.0.1"}},
		"spec": {},
	}
	some msg in violations
	contains(msg, "only exit-node egress is allowed")
}

test_rejects_tailscale_access_proxy_group if {
	violations := deny with input as {
		"apiVersion": "tailscale.com/v1alpha1",
		"kind": "ProxyGroup",
		"metadata": {"name": "tailnet-api"},
		"spec": {"type": "kube-apiserver"},
	}
	some msg in violations
	contains(msg, "exceeds exit-node-only use; use Octelium")
}

test_rejects_tailscale_ingress_proxy_group if {
	violations := deny with input as {
		"apiVersion": "tailscale.com/v1alpha1",
		"kind": "ProxyGroup",
		"metadata": {"name": "tailnet-ingress"},
		"spec": {"type": "ingress"},
	}
	some msg in violations
	contains(msg, "exceeds exit-node-only use; use Octelium")
}

test_rejects_tailscale_egress_proxy_group if {
	violations := deny with input as {
		"apiVersion": "tailscale.com/v1alpha1",
		"kind": "ProxyGroup",
		"metadata": {"name": "tailnet-egress"},
		"spec": {"type": "egress"},
	}
	some msg in violations
	contains(msg, "exceeds exit-node-only use; use Octelium")
}

test_rejects_gateway_attached_non_octelium_external_route if {
	violations := deny with input as {
		"apiVersion": "networking.istio.io/v1",
		"kind": "VirtualService",
		"metadata": {"name": "exposed"},
		"spec": {
			"hosts": ["exposed.example.com"],
			"gateways": ["istio-system/external-gateway"],
		},
	}
	some msg in violations
	contains(msg, "must declare homelab.rst.io/access-plane=octelium")
}

test_allows_mesh_only_internal_route if {
	violations := deny with input as {
		"apiVersion": "networking.istio.io/v1",
		"kind": "VirtualService",
		"metadata": {"name": "internal-mesh"},
		"spec": {
			"hosts": ["backend.default.svc.cluster.local"],
			"gateways": ["mesh"],
		},
	}
	count(violations) == 0
}

test_allows_gatewayless_internal_route if {
	violations := deny with input as {
		"apiVersion": "networking.istio.io/v1",
		"kind": "VirtualService",
		"metadata": {"name": "internal-default-mesh"},
		"spec": {"hosts": ["backend.default.svc.cluster.local"]},
	}
	count(violations) == 0
}

test_allows_explicit_discovery_ingress if {
	violations := deny with input as {
		"apiVersion": "networking.k8s.io/v1",
		"kind": "Ingress",
		"metadata": {"name": "compass-discovery"},
		"spec": {
			"ingressClassName": "compass-discovery",
			"rules": [{"host": "exposed.example.com"}],
		},
	}
	count(violations) == 0
}

test_rejects_hooked_cordium_bootstrap_application if {
	resource := cordium_bootstrap_app("1", ["resources-finalizer.argocd.argoproj.io"], "clusters/homelab/apps/cordium-bootstrap", 0)
	resource_with_hook := object.union(resource, {
		"metadata": object.union(resource.metadata, {
			"annotations": object.union(resource.metadata.annotations, {"argocd.argoproj.io/hook": "PostSync"}),
		}),
	})
	violations := deny with input as resource_with_hook
	some msg in violations
	contains(msg, "must be a normal resource")
}

test_rejects_early_cordium_bootstrap_application if {
	resource := cordium_bootstrap_app("0", ["resources-finalizer.argocd.argoproj.io"], "clusters/homelab/apps/cordium-bootstrap", 0)
	violations := deny with input as resource
	some msg in violations
	contains(msg, "parent Sync wave 1")
}

test_rejects_orphaning_cordium_bootstrap_application if {
	resource := cordium_bootstrap_app("1", [], "clusters/homelab/apps/cordium-bootstrap", 0)
	violations := deny with input as resource
	some msg in violations
	contains(msg, "must cascade tracked bootstrap resources")
}

test_rejects_shared_cordium_bootstrap_source if {
	resource := cordium_bootstrap_app("1", ["resources-finalizer.argocd.argoproj.io"], "clusters/homelab/apps/cordium", 0)
	violations := deny with input as resource
	some msg in violations
	contains(msg, "must isolate the bootstrap source path")
}

test_allows_isolated_cordium_bootstrap_application if {
	resource := cordium_bootstrap_app("1", ["resources-finalizer.argocd.argoproj.io"], "clusters/homelab/apps/cordium-bootstrap", 0)
	violations := deny with input as resource
	count(violations) == 0
}

test_rejects_retried_cordium_bootstrap_application if {
	resource := cordium_bootstrap_app("1", ["resources-finalizer.argocd.argoproj.io"], "clusters/homelab/apps/cordium-bootstrap", 5)
	violations := deny with input as resource
	some msg in violations
	contains(msg, "must disable retries")
}

test_rejects_persistent_cordium_genesis_identity if {
	resource := cordium_bootstrap_identity({})
	violations := deny with input as resource
	some msg in violations
	contains(msg, "must be a PostSync hook")
}

test_allows_ephemeral_cordium_genesis_identity if {
	resource := cordium_bootstrap_identity({
		"argocd.argoproj.io/hook": "PostSync",
		"argocd.argoproj.io/hook-delete-policy": "BeforeHookCreation",
		"argocd.argoproj.io/sync-wave": "-1",
	})
	violations := deny with input as resource
	count(violations) == 0
}

test_rejects_presync_cordium_genesis_identity if {
	resource := cordium_bootstrap_identity({
		"argocd.argoproj.io/hook": "PreSync",
		"argocd.argoproj.io/hook-delete-policy": "BeforeHookCreation",
		"argocd.argoproj.io/sync-wave": "-1",
	})
	violations := deny with input as resource
	some msg in violations
	contains(msg, "must be a PostSync hook")
}

test_rejects_late_cordium_genesis_identity if {
	resource := cordium_bootstrap_identity({
		"argocd.argoproj.io/hook": "PostSync",
		"argocd.argoproj.io/hook-delete-policy": "BeforeHookCreation",
		"argocd.argoproj.io/sync-wave": "0",
	})
	violations := deny with input as resource
	some msg in violations
	contains(msg, "PostSync wave -1")
}

test_rejects_unscoped_cordium_cleanup_role if {
	resource := cordium_cleanup_role({
		"apiGroups": ["rbac.authorization.k8s.io"],
		"resources": ["clusterroles", "clusterrolebindings"],
		"verbs": ["delete"],
	})
	violations := deny with input as resource
	some msg in violations
	contains(msg, "may only delete the named cordium-genesis")
}

test_rejects_cordium_cleanup_role_with_create if {
	resource := cordium_cleanup_role({
		"apiGroups": ["rbac.authorization.k8s.io"],
		"resources": ["clusterroles", "clusterrolebindings"],
		"resourceNames": ["cordium-genesis"],
		"verbs": ["delete", "create"],
	})
	violations := deny with input as resource
	some msg in violations
	contains(msg, "may only delete the named cordium-genesis")
}

test_allows_named_cordium_cleanup_role if {
	resource := cordium_cleanup_role({
		"apiGroups": ["rbac.authorization.k8s.io"],
		"resources": ["clusterroles", "clusterrolebindings"],
		"resourceNames": ["cordium-genesis"],
		"verbs": ["delete"],
	})
	violations := deny with input as resource
	count(violations) == 0
}

test_rejects_early_cordium_cleanup_job if {
	resource := cordium_cleanup_job("PostSync,SyncFail", "BeforeHookCreation,HookSucceeded", "0", true)
	violations := deny with input as resource
	some msg in violations
	contains(msg, "wave 1")
}

test_rejects_success_only_cordium_cleanup_job if {
	resource := cordium_cleanup_job("PostSync", "BeforeHookCreation,HookSucceeded", "1", true)
	violations := deny with input as resource
	some msg in violations
	contains(msg, "both PostSync and SyncFail")
}

test_rejects_nonrepeatable_cordium_cleanup_job if {
	resource := cordium_cleanup_job("PostSync,SyncFail", "HookSucceeded", "1", true)
	violations := deny with input as resource
	some msg in violations
	contains(msg, "BeforeHookCreation,HookSucceeded")
}

test_rejects_unauthenticated_cordium_cleanup_job if {
	resource := cordium_cleanup_job("PostSync,SyncFail", "BeforeHookCreation,HookSucceeded", "1", false)
	violations := deny with input as resource
	some msg in violations
	contains(msg, "must mount its dedicated ServiceAccount token")
}

test_allows_fail_closed_cordium_cleanup_job if {
	resource := cordium_cleanup_job("PostSync,SyncFail", "BeforeHookCreation,HookSucceeded", "1", true)
	violations := deny with input as resource
	count(violations) == 0
}

test_rejects_unbounded_cordium_genesis_job if {
	resource := cordium_genesis_job({})
	violations := deny with input as resource
	some msg in violations
	contains(msg, "must fail after 720 seconds")
}

test_allows_bounded_cordium_genesis_job if {
	resource := cordium_genesis_job({"activeDeadlineSeconds": 720})
	violations := deny with input as resource
	count(violations) == 0
}

cordium_bootstrap_app(wave, finalizers, path, retry_limit) := {
	"apiVersion": "argoproj.io/v1alpha1",
	"kind": "Application",
	"metadata": {
		"name": "cordium-bootstrap",
		"finalizers": finalizers,
		"annotations": {"argocd.argoproj.io/sync-wave": wave},
	},
	"spec": {
		"syncPolicy": {"retry": {"limit": retry_limit}},
		"source": {
			"repoURL": "https://github.com/Stuhlmuller/homelab.git",
			"targetRevision": "main",
			"path": path,
		},
	},
}

cordium_bootstrap_identity(annotations) := {
	"apiVersion": "rbac.authorization.k8s.io/v1",
	"kind": "ClusterRole",
	"metadata": {
		"name": "cordium-genesis",
		"annotations": annotations,
	},
}

cordium_cleanup_role(rule) := {
	"apiVersion": "rbac.authorization.k8s.io/v1",
	"kind": "ClusterRole",
	"metadata": {"name": "cordium-genesis-cleanup"},
	"rules": [rule],
}

cordium_cleanup_job(hook, delete_policy, wave, automount) := {
	"apiVersion": "batch/v1",
	"kind": "Job",
	"metadata": {
		"name": "cordium-genesis-cleanup",
		"annotations": {
			"argocd.argoproj.io/hook": hook,
			"argocd.argoproj.io/hook-delete-policy": delete_policy,
			"argocd.argoproj.io/sync-wave": wave,
		},
	},
	"spec": {
		"template": {
			"spec": {
				"automountServiceAccountToken": automount,
				"serviceAccountName": "cordium-genesis-cleanup",
			},
		},
	},
}

cordium_genesis_job(spec) := {
	"apiVersion": "batch/v1",
	"kind": "Job",
	"metadata": {"name": "cordium-genesis"},
	"spec": spec,
}
