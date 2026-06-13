# Cordium

Cordium is bootstrapped into the self-hosted Octelium Cluster with the upstream
`cordium-genesis` component. The Argo CD app runs the genesis command as a
version-pinned sync hook so the Cordium controllers and managed services are
created from the same reviewed desired-state path as the rest of the homelab.

The deployed runtime is split intentionally:

- Human access uses the Octelium `homelab-cordium-user` HUMAN identity and the
  public `cordium` WEB Service at `https://cordium.stinkyboi.com`.
- Agent access uses the Octelium `homelab-cordium-agent` WORKLOAD identity and
  the `cordium-agent-api.homelab` gRPC Service for automation.
- Workspace defaults stay with upstream Cordium until this repository adds a
  reviewed Cordium-native workspace configuration resource.

The hook image is pinned to Cordium `0.12.7`. Upstream genesis creates the
long-running Cordium `nocturne` and `rscserver` Deployments and registers the
`apiserver` and `portal` managed services with Octelium. The Argo CD app keeps
the hook and RBAC visible in git; the generated Octelium/Cordium runtime
resources remain owned by Octelium controllers.

## Activation

Apply the Octelium service catalog after the PR merges:

```sh
octeliumctl apply --domain stinkyboi.com docs/examples/octelium/homelab-services.yaml
```

Argo CD then syncs the `cordium` Application and runs the genesis hook. If the
hook needs to be rerun after a Cordium upgrade, bump
`homelab.rst.io/cordium-genesis-revision` on the Job template.

Create a workload credential for automation after the `homelab-cordium-agent`
User exists:

```sh
octeliumctl create cred \
  --user homelab-cordium-agent \
  --policy homelab-cordium-agent-api-access \
  homelab-cordium-agent
```

Store that token outside git wherever the caller that drives agent workspaces
expects it. Do not reuse a human browser session token for agent automation.

## Validation

```sh
kubectl -n octelium get job cordium-genesis
kubectl -n octelium logs job/cordium-genesis
kubectl -n octelium get deploy,svc -l octelium.com/app=cordium
octeliumctl get svc cordium
octeliumctl get svc cordium-agent-api.homelab
curl -I https://cordium.stinkyboi.com
```

The expected steady state includes ready Cordium controller pods in the
`octelium` namespace and an Octelium-protected browser route for
`cordium.stinkyboi.com`.

## Rollback

Disable or delete the `cordium` Argo CD Application first so the hook does not
recreate resources. Then remove the Octelium catalog entries for `cordium`,
`cordium-agent-api.homelab`, `homelab-cordium-user`, and
`homelab-cordium-agent` if the platform is being retired.
