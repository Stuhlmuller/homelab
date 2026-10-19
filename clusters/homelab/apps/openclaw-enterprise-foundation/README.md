# OpenClaw Enterprise Foundation

This directory prepares dormant namespace, secret and PostgreSQL TLS boundaries.
No Argo Application currently registers it. `openclaw-agents` is an external
namespace reserved for one fresh OCE tenant. The upstream worker rejects a
foreign NetworkPolicy there. OCE owns its tenant policies and eventual agent claim.

The three tenant RoleBindings assume Helm release `oce` in `openclaw-system`.
Keep that release name when adding the Enterprise Application. The seven
ExternalSecrets use exact SSM parameters and `OnChange`; advance their
`generated-secret-revision` annotations during rotation. The model parameter
still contains a placeholder until the owner's protected credential workflow
runs. `occ-database` assembles separate TLS-verified URLs from the generated
alphanumeric application/migration passwords; only those two URL keys reach
their respective stock chart consumers. The planned PostgreSQL Service is
`occ-postgres` and its CA mount is `/etc/openclaw/database-ca/tls.crt`.
Do not activate the agent from this declaration.

The separate `occ-postgres-root` certificate is retained as database recovery
material; cert-manager issues a server certificate only for the private Service
FQDN in the URL. The reviewed `occ-plugin` startup bytes live at
`../openclaw-enterprise/installation.yaml`. The protected
`openclaw-enterprise-startup` workflow creates and verifies only the immutable
`occ-installation-startup-980de11bbc688a33741a19c9093f613e` Secret after
this namespace exists and before the Enterprise Application is registered.
The application PreSync hook checks its exact bytes and chart checksum. No raw
Secret is rendered or committed. Storage placement,
PostgreSQL workload/roles and backup, private routes, and registration await
their separate reviewed tasks and live gates.
Validate this dormant boundary with
`nix develop --command python3 -I scripts/ci/openclaw-enterprise-foundation-test.py`.
