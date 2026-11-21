# kagent

Argo CD renders the pinned kagent CRD and runtime Helm charts into the
`kagent` namespace. The controller watches that namespace. The
`homelab-assistant` uses Go ADK and LiteLLM's `openrouter/free` route. Bundled
agents, cluster tools, and MCP servers are disabled.

Access the UI through Kubernetes RBAC with
`kubectl -n kagent port-forward svc/kagent-ui 8080:8080`, then open
`http://localhost:8080`. Istio ambient authorization restricts ingress to authenticated
workloads in the namespace. A matching NetworkPolicy covers packet filtering
when the cluster policy engine is enabled. The UI and controller use the upstream unauthenticated mode, so
keep the forwarded listener on loopback and restrict namespace membership.

External Secrets creates the dedicated inference key and PostgreSQL
credentials from generated SSM parameters. The database uses an
`emptyDir`. Session history is disposable and is lost when the database pod
is replaced. Agent and model definitions live in Git.

After Argo CD syncs, verify both ExternalSecrets and the controller, UI,
database, and generated agent deployments are Ready. Forward the UI, select
`homelab-assistant`, and ask it to explain a Kubernetes readiness probe.
Confirm the reply and the corresponding LiteLLM generation attributed to
`kagent`. Roll back the workload through a reviewed Git revert. Keep shared
CRDs until their custom resources have been removed through GitOps.
