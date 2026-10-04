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
