// Copyright Octelium Labs, LLC. All rights reserved.
// Licensed under the Apache License, Version 2.0.

package genesis

import (
	"encoding/json"
	"fmt"
	"testing"
)

func TestHomelabRenderWorkspacePolicy(t *testing.T) {
	policy := (&Genesis{}).getWSNetworkPolicy()
	data, err := json.Marshal(policy)
	if err != nil {
		t.Fatal(err)
	}
	fmt.Printf("HOMELAB_POLICY_RENDER:%s\n", data)
}
