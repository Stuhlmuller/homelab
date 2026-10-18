package homelabcompat

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/goharbor/harbor/src/common"
	"github.com/goharbor/harbor/src/lib"
	"github.com/goharbor/harbor/src/lib/config"
	_ "github.com/goharbor/harbor/src/pkg/config/inmemory"
	harborcsrf "github.com/goharbor/harbor/src/server/middleware/csrf"
)

func TestBrowserCSRFCompatibility(t *testing.T) {
	config.InitWithSettings(map[string]any{common.ExtEndpoint: "https://harbor.test"})
	handler := harborcsrf.Middleware()(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusNoContent) }))
	cases := []struct {
		name, method, path, site, origin string
		session                          bool
		expected                         int
	}{
		{"safe read", "GET", "/c/login", "cross-site", "https://attacker.test", false, 204},
		{"same origin UI", "POST", "/c/login", "same-origin", "https://harbor.test", false, 204},
		{"cross site UI", "POST", "/c/login", "cross-site", "https://attacker.test", false, 403},
		{"same site subdomain", "POST", "/c/login", "same-site", "https://sub.harbor.test", false, 403},
		{"origin fallback allowed", "POST", "/c/login", "", "https://harbor.test", false, 204},
		{"origin fallback denied", "POST", "/c/login", "", "http://attacker.test", false, 403},
		{"nonbrowser UI", "POST", "/c/login", "", "", false, 204},
		{"session API denied", "DELETE", "/api/v2.0/projects/fixture", "cross-site", "https://attacker.test", true, 403},
		{"session API allowed", "DELETE", "/api/v2.0/projects/fixture", "same-origin", "https://harbor.test", true, 204},
		{"non-session API preserved", "POST", "/api/v2.0/projects", "cross-site", "https://attacker.test", false, 204},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			req := httptest.NewRequest(c.method, "https://harbor.test"+c.path, nil)
			req.Header.Set("Sec-Fetch-Site", c.site)
			req.Header.Set("Origin", c.origin)
			req.Header.Set("X-Harbor-CSRF-Token", "legacy-client-token")
			req = req.WithContext(lib.WithCarrySession(req.Context(), c.session))
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, req)
			if response.Code != c.expected {
				t.Fatalf("status %d, want %d", response.Code, c.expected)
			}
			if (c.session || c.path == "/c/login") && response.Header().Get("X-Harbor-CSRF-Token") == "" {
				t.Fatal("legacy token header missing")
			}
		})
	}
}
