# Unregistered Harbor TLS candidate

Use `scripts/harbor-tls-render.py --check` for offline verification or
`--write-public-candidate` for the allowlisted public chart overrides. Values
alone retain the chart's insecure API proxy verification override. The candidate
Kustomization and Application source patch remain unregistered and disabled.
No provisioning, credentials or activation is authorized.

See [materialization and alerts](../../../../docs/harbor-tls-materialization-and-alerts.md)
for public trust inputs, client ports, phased reload deltas and acceptance checks.

See [the integration contract](../../../../docs/harbor-tls-and-recovery-integration.md)
for exact SAN/trust names, disabled recovery, HOME-62 rejection, test evidence
limits, client migration and remaining GitOps materialization/custody gates.
