# k8s-gateway 4.0.0 test package

`k8s-gateway-4.0.0.tgz` is the upstream Helm release package, copied from the
`pages` branch of `k8s-gateway/k8s_gateway` at commit
`fe3f85f37a129eae31273cc1219c33b3d2a9409b`, path
`k8s-gateway-4.0.0.tgz` (Git blob `3329d86c9dd2cba7918ebbbe7f628ea5077489a9`).
Its SHA-256 is
`dbffe7bbd71919d4a204be6821fa9266483824335dc593b319a4b9a156f9ebca`,
the same package hash reviewed in `scripts/config/harbor-helm-charts.json`.
The corresponding Codeberg OCI chart manifest digest remains pinned as
`sha256:b02209df03b08706179875b6e1887cb6064a589b591a0ce1e809a354811e37a7`.

The test prefers the public OCI chart and verifies its manifest digest. If the
registry fetch fails, it verifies this exact package hash before rendering the
same values and asserting the same Kubernetes resource contract. A changed or
missing package fails closed. The upstream project is licensed under Apache-2.0.
