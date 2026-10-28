// Copyright Octelium Labs, LLC. All rights reserved.
// Licensed under the AGPL-3.0 license.

package components

import (
	"encoding/json"
	"fmt"
	"testing"
)

func TestHomelabRenderServiceUpstreamPolicy(t *testing.T) {
	policy := getServiceUpstreamNetworkPolicy()
	data, err := json.Marshal(policy)
	if err != nil {
		t.Fatal(err)
	}
	fmt.Printf("HOMELAB_POLICY_RENDER:%s\n", data)
}
