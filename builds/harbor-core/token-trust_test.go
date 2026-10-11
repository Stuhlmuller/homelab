package homelabcompat

import (
	"encoding/json"
	registrytoken "github.com/docker/distribution/registry/auth/token"
	"github.com/docker/libtrust"
	"testing"
)

func TestTokenJWKTrustUsesKeyMaterial(t *testing.T) {
	trusted, err := libtrust.GenerateECP256PrivateKey()
	if err != nil {
		t.Fatal(err)
	}
	attacker, err := libtrust.GenerateECP256PrivateKey()
	if err != nil {
		t.Fatal(err)
	}
	options := registrytoken.VerifyOptions{TrustedKeys: map[string]libtrust.PublicKey{trusted.KeyID(): trusted.PublicKey()}}
	for _, tc := range []struct {
		name    string
		key     libtrust.PublicKey
		allowed bool
	}{
		{"trusted", trusted.PublicKey(), true}, {"attacker using trusted kid", attacker.PublicKey(), false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			data, err := tc.key.MarshalJSON()
			if err != nil {
				t.Fatal(err)
			}
			var jwk map[string]any
			if err := json.Unmarshal(data, &jwk); err != nil {
				t.Fatal(err)
			}
			jwk["kid"] = trusted.KeyID()
			data, err = json.Marshal(jwk)
			if err != nil {
				t.Fatal(err)
			}
			raw := json.RawMessage(data)
			token := registrytoken.Token{Header: &registrytoken.Header{RawJWK: &raw}}
			key, err := token.VerifySigningKey(options)
			if tc.allowed {
				if err != nil || key.KeyID() != trusted.KeyID() {
					t.Fatalf("trusted key rejected: %v", err)
				}
			} else if err == nil {
				t.Fatal("attacker key accepted under trusted kid")
			}
		})
	}
}
