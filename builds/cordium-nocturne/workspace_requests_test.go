package controller

import (
	"testing"

	"github.com/octelium/octelium/apis/main/cordiumv1"
	"google.golang.org/protobuf/encoding/protojson"
	corev1 "k8s.io/api/core/v1"
)

func TestHomelabWorkspaceReservesItsLimits(t *testing.T) {
	for _, limits := range []string{`{}`, `{"memory":{"megabytes":2048},"cpu":{"millicores":2000}}`} {
		ws := &cordiumv1.Workspace{}
		input := `{"metadata":{"name":"reservation-test","uid":"test-uid"},"spec":{},"status":{"limit":` + limits + `}}`
		if err := protojson.Unmarshal([]byte(input), ws); err != nil {
			t.Fatal(err)
		}
		pod := (&Controller{}).newPodSpec(ws)
		if pod.HostUsers == nil || *pod.HostUsers {
			t.Error("workspace must use its own user namespace")
		}
		if len(pod.Containers) != 1 || pod.Containers[0].Name != "workspace" {
			t.Fatalf("expected workspace container, got %v", pod.Containers)
		}
		for _, container := range pod.Containers {
			for _, name := range []corev1.ResourceName{corev1.ResourceMemory, corev1.ResourceCPU} {
				request, limit := container.Resources.Requests[name], container.Resources.Limits[name]
				if request.Sign() <= 0 || limit.Sign() <= 0 {
					t.Fatalf("%s quantity missing or nonpositive", name)
				}
				if request.Cmp(limit) != 0 {
					t.Errorf("%s request=%s limit=%s", name, request.String(), limit.String())
				}
			}
		}
	}
}
