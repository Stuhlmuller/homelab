# HOME-57 credential projection candidate

Unregistered; do not apply or add to the Harbor base before the approved
activation revision. This projects only the dedicated lifecycle envelope's
`secret` property, never the issuer or Harbor administrator credential.

Render only:

```sh
kustomize build clusters/homelab/apps/harbor/credential-candidate
```

The sentinel parameter intentionally lacks a password. Rendering does not
establish a Ready Secret or authorize issuance. See the
[lifecycle contract](../../../../../docs/harbor-vulnerability-credential-lifecycle.md)
and [transition gates](../../../../../docs/harbor-vulnerability-exporter-transition.md).


The candidate now uses namespace-scoped SecretStore `harbor-vulnerability-reader`
and separate `harbor-vulnerability-reader-auth` credential references. No auth
Secret or IAM principal is supplied. The parameter catalog excludes shared
reader access; the dedicated read-only policy is proposed separately. A missing
credential must fail closed. Do not source it from shared `aws-ssm`.

See [custody and boundary evidence](../../../../../docs/harbor-credential-custody.md).
The shared ESO controller and Harbor Secret/Pod administrators remain trusted;
a namespace-scoped store is not controller-compromise isolation. Reader-key
provisioning, rotation and effective IAM/RBAC require separate approved artifacts.
