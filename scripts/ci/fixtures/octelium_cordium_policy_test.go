// Runs inside the pinned upstream octovigil package, not against a live cluster.
package octovigil

import (
	"context"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/octelium/octelium/apis/main/corev1"
	"github.com/octelium/octelium/cluster/common/celengine"
	"github.com/octelium/octelium/cluster/vigil/vigil/modes/httpg/httputils"
	"github.com/octelium/octelium/pkg/common/pbutils"
)

func TestHomelabCordiumBoundary(t *testing.T) {
	ctx := context.Background()
	engine, err := celengine.New(ctx, &celengine.Opts{})
	if err != nil {
		t.Fatal(err)
	}
	server := &Server{celEngine: engine}
	data, err := os.ReadFile(os.Getenv("HOMELAB_POLICY_FIXTURE"))
	if err != nil {
		t.Fatal(err)
	}
	policy := &corev1.Policy{}
	if err := pbutils.UnmarshalJSON(data, policy); err != nil {
		t.Fatal(err)
	}
	rules := make([]*policyRule, 0, len(policy.Spec.Rules))
	for _, rule := range policy.Spec.Rules {
		rules = append(rules, &policyRule{rule: rule, attrs: policy.Spec.Attrs.AsMap()})
	}
	request := func(method, path string) map[string]any {
		req := httptest.NewRequest(method, "https://kubernetes.example.invalid"+path, nil)
		parsed, err := httputils.ParseKubernetesRequest(req)
		if err != nil {
			t.Fatal(err)
		}
		// Same field mapping as pinned preauth.go:205-225, with real protobuf
		// serialization so empty group/namespace/subresource fields are omitted.
		kubernetes, err := pbutils.ConvertToMap(&corev1.RequestContext_Request_Kubernetes{
			Http: &corev1.RequestContext_Request_HTTP{Method: req.Method, Path: req.URL.Path},
			Verb: parsed.Verb, ApiPrefix: parsed.APIPrefix, ApiGroup: parsed.APIGroup,
			ApiVersion: parsed.APIVersion, Namespace: parsed.Namespace,
			Resource: parsed.Resource, Subresource: parsed.Subresource, Name: parsed.Name,
		})
		if err != nil {
			t.Fatal(err)
		}
		return map[string]any{
			"user":    map[string]any{"metadata": map[string]any{"name": "homelab-cordium-user"}, "spec": map[string]any{"type": "HUMAN"}},
			"session": map[string]any{"status": map[string]any{"type": "CLIENT"}},
			"service": map[string]any{"metadata": map[string]any{"name": "kubernetes-api.homelab"}, "spec": map[string]any{"mode": "KUBERNETES"}},
			"request": map[string]any{"kubernetes": kubernetes},
		}
	}
	allows := func(input map[string]any) bool {
		result, err := server.doGetDecision(ctx, input, rules)
		if err != nil {
			t.Fatal(err)
		}
		return result.effect == corev1.Policy_Spec_Rule_ALLOW
	}
	assertDecision := func(name, method, path string, want bool) {
		t.Helper()
		t.Run(name, func(t *testing.T) {
			if got := allows(request(method, path)); got != want {
				t.Fatalf("%s %s: allow=%v, want %v", method, path, got, want)
			}
		})
	}
	// Every permitted resource must support get/list/watch in an explicit namespace.
	for _, group := range []struct {
		prefix    string
		resources []string
	}{
		{"/api/v1", []string{"events", "pods", "services"}},
		{"/apis/apps/v1", []string{"daemonsets", "deployments", "replicasets", "statefulsets"}},
		{"/apis/batch/v1", []string{"cronjobs", "jobs"}},
	} {
		for _, resource := range group.resources {
			path := group.prefix + "/namespaces/cordium/" + resource
			for _, suffix := range []string{"", "/example", "?watch=true"} {
				assertDecision(resource+suffix, "GET", path+suffix, true)
			}
			assertDecision(resource+"-all-namespaces", "GET", group.prefix+"/"+resource, false)
		}
	}
	for _, path := range []string{"/api", "/api/v1", "/apis", "/apis/apps/v1", "/apis/batch/v1"} {
		assertDecision("discovery"+path, "GET", path, true)
		assertDecision("discovery-post"+path, "POST", path, false)
		assertDecision("discovery-head"+path, "HEAD", path, false)
	}
	for _, resource := range []string{"secrets", "configmaps", "serviceaccounts", "persistentvolumeclaims", "endpoints", "futurethings"} {
		assertDecision(resource, "GET", "/api/v1/namespaces/cordium/"+resource, false)
	}
	for _, path := range []string{
		"/api/v1/nodes", "/api/v1/namespaces", "/api/v1/persistentvolumes",
		"/apis/rbac.authorization.k8s.io/v1/namespaces/cordium/roles",
		"/apis/rbac.authorization.k8s.io/v1/clusterroles",
		"/apis/apiextensions.k8s.io/v1/customresourcedefinitions",
		"/apis/example.invalid/v1/namespaces/cordium/widgets",
		"/apis/example.invalid/v1/namespaces/cordium/deployments",
		"/apis/apps/v1/namespaces/cordium/deployments/example/scale",
		"/apis/batch/v1/namespaces/cordium/jobs/example/status",
		"/apis/apps/v2/namespaces/cordium/deployments",
		"/apis/discovery.k8s.io/v1/namespaces/cordium/endpointslices",
		"/api/v2/namespaces/cordium/pods",
		"/metrics", "/debug/pprof/", "/readyz", "/healthz", "/version", "/openapi/v2", "/openapi/v3",
		"/apis/rbac.authorization.k8s.io/v1", "/api/v1/namespaces//pods",
	} {
		assertDecision(path, "GET", path, false)
	}
	for _, resource := range []string{"subjectaccessreviews", "selfsubjectaccessreviews", "localsubjectaccessreviews", "selfsubjectrulesreviews"} {
		for _, method := range []string{"GET", "POST"} {
			assertDecision(resource+method, method, "/apis/authorization.k8s.io/v1/"+resource, false)
		}
	}
	assertDecision("tokenreview", "POST", "/apis/authentication.k8s.io/v1/tokenreviews", false)
	for _, sub := range []string{"exec", "attach", "log", "proxy", "portforward", "ephemeralcontainers", "status", "unknown"} {
		for _, method := range []string{"GET", "POST"} {
			assertDecision(sub+method, method, "/api/v1/namespaces/cordium/pods/example/"+sub, false)
		}
	}
	assertDecision("service-proxy", "GET", "/api/v1/namespaces/cordium/services/example/proxy", false)
	assertDecision("token", "POST", "/api/v1/namespaces/cordium/serviceaccounts/example/token", false)
	for _, method := range []string{"POST", "PUT", "PATCH", "DELETE", "HEAD"} {
		assertDecision(method, method, "/api/v1/namespaces/cordium/pods/example", false)
	}
	for _, field := range []struct{ parent, section, key, value string }{
		{"user", "metadata", "name", "someone-else"},
		{"user", "spec", "type", "WORKLOAD"},
		{"session", "status", "type", "CLIENTLESS"},
		{"service", "metadata", "name", "kubernetes-api-ci.default"},
		{"service", "spec", "mode", "HTTP"},
	} {
		input := request("GET", "/api/v1/namespaces/cordium/pods")
		input[field.parent].(map[string]any)[field.section].(map[string]any)[field.key] = field.value
		if allows(input) {
			t.Errorf("accepted wrong %s/%s/%s", field.parent, field.section, field.key)
		}
	}
	for _, field := range []string{"namespace", "subresource", "apiGroup"} {
		input := request("GET", "/api/v1/namespaces/cordium/pods")
		input["request"].(map[string]any)["kubernetes"].(map[string]any)[field] = ""
		if allows(input) {
			t.Errorf("accepted malformed explicitly empty %s", field)
		}
	}
	for _, field := range []string{"apiPrefix", "apiVersion", "resource", "namespace", "verb", "http"} {
		input := request("GET", "/api/v1/namespaces/cordium/pods")
		delete(input["request"].(map[string]any)["kubernetes"].(map[string]any), field)
		if allows(input) {
			t.Errorf("accepted absent required field %s", field)
		}
	}
	for _, field := range []string{"user", "session", "service", "request"} {
		input := request("GET", "/api/v1/namespaces/cordium/pods")
		delete(input, field)
		if allows(input) {
			t.Errorf("accepted absent identity/request field %s", field)
		}
	}
	owner := request("DELETE", "/api/v1/namespaces/example")
	owner["user"].(map[string]any)["metadata"].(map[string]any)["name"] = "homelab-owner"
	if !allows(owner) {
		t.Error("owner access changed")
	}
}
