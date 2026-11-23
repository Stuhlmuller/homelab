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

The DNS contract and runtime fixture render this package after verifying its
SHA-256. The protected Harbor chart publisher pulls the upstream package,
verifies the same hash, and repeats the check with a reader pull from the
private mirror used by Argo CD. Missing or changed bytes fail validation.
The upstream project is licensed under Apache-2.0; its license text is included
as `k8s-gateway-LICENSE`.
