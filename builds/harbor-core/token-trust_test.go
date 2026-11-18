package homelabcompat

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"testing"
	"time"

	registrytoken "github.com/distribution/distribution/v3/registry/auth/token"
	"github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
)

func TestTokenJWKTrustUsesKeyMaterial(t *testing.T) {
	trusted, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	attacker, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	options := registrytoken.VerifyOptions{
		TrustedIssuers:    []string{"harbor"},
		AcceptedAudiences: []string{"registry"},
		TrustedKeys:       map[string]crypto.PublicKey{"trusted": &trusted.PublicKey},
	}
	now := time.Now()
	claims := registrytoken.ClaimSet{
		Issuer: "harbor", Subject: "test-user",
		Audience:   registrytoken.AudienceList{"registry"},
		Expiration: now.Add(time.Minute).Unix(),
		NotBefore:  now.Add(-time.Minute).Unix(),
		IssuedAt:   now.Unix(),
	}
	for _, tc := range []struct {
		name    string
		key     *ecdsa.PrivateKey
		allowed bool
	}{
		{"trusted", trusted, true},
		{"attacker using trusted kid", attacker, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			jwk := jose.JSONWebKey{Key: &tc.key.PublicKey, KeyID: "trusted"}
			signer, err := jose.NewSigner(jose.SigningKey{Algorithm: jose.ES256, Key: tc.key},
				(&jose.SignerOptions{}).WithHeader("jwk", jwk))
			if err != nil {
				t.Fatal(err)
			}
			raw, err := jwt.Signed(signer).Claims(claims).Serialize()
			if err != nil {
				t.Fatal(err)
			}
			token, err := registrytoken.NewToken(raw, []jose.SignatureAlgorithm{jose.ES256})
			if err != nil {
				t.Fatal(err)
			}
			verified, err := token.Verify(options)
			if tc.allowed {
				if err != nil || verified.Subject != claims.Subject {
					t.Fatalf("trusted token rejected: %v", err)
				}
			} else if err == nil {
				t.Fatal("attacker signature accepted under trusted kid")
			}
		})
	}
}
