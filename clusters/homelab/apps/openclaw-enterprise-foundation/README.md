# OpenClaw Enterprise Foundation

This directory prepares only the two namespace and secret boundaries. No Argo
Application currently registers it. `openclaw-agents` is an external namespace
reserved for one fresh OCE tenant; the upstream worker rejects a foreign
NetworkPolicy there. OCE owns its tenant policies and eventual agent claim.

The three tenant RoleBindings assume Helm release `oce` in `openclaw-system`.
Keep that release name when adding the Enterprise Application. The six
ExternalSecrets use exact SSM parameters and `OnChange`; advance their
`generated-secret-revision` annotations during rotation. The model parameter
still contains a placeholder until the owner's protected credential workflow
runs. Do not activate the agent from this declaration.

Storage placement, PostgreSQL TLS/roles and backup, candidate inputs, private
routes, and registration await their separate reviewed tasks and live gates.
Validate this dormant boundary with
`nix develop --command python3 -I scripts/ci/openclaw-enterprise-foundation-test.py`.
