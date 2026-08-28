package main

import rego.v1

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
