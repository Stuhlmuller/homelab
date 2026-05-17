# Homelab Monorepo

This repository manages a Debian-based Nomad homelab running on three Zima
boards plus one Acer control-plane node:

- `acer` at `10.1.0.199`
- `zimaboard-0` at `10.1.0.200`
- `zimaboard-1` at `10.1.0.201`
- `zimaboard-2` at `10.1.0.202`

It is organized as a monorepo for the full lifecycle:

- `ansible/` bootstraps the hosts, installs Docker, Consul, Nomad, and
  Tailscale, and renders the base configuration.
- `terraform/` contains the Terragrunt/OpenTofu live stack that registers Nomad
  jobs, variables, and CSI volumes.
- `nomad/` contains the source jobspecs that run workloads behind Traefik.
- `scripts/` contains validation and operator workflows.
- `.codex/skills/` contains project-local Codex skills that wrap the validated
  live-operations scripts.
- `tests/` contains repository-level regression checks that run without
  requiring a live cluster.
- `docs/` contains architecture notes and deployment runbooks.

## Layout

```text
homelab/
├── .codex/
│   └── skills/
├── AGENTS.md
├── flake.nix
├── ansible/
│   ├── inventories/production/
│   ├── playbooks/
│   └── roles/
├── docs/
│   ├── architecture.md
│   └── runbooks/
├── nomad/
│   └── jobs/
├── scripts/
├── terraform/
│   ├── live/homelab/
│   └── root.hcl
└── tests/
```

## Current stack

- Nomad and Consul run as server+client on each node.
- Traefik terminates HTTPS and discovers services from Consul tags.
- Shared persistent storage is delivered through the NFS CSI plugin and the
  `shared-data` volume.
- FleetDM runs as a single Nomad service on `nomad-primary` with node-local
  persistent state under the `fleetdm_data` host volume and public HTTPS at
  `fleet.stinkyboi.com`.
- Tailscale is managed as host software so the entire LAN remains reachable over
  the tailnet.
- `acer` is the primary Nomad and HTTP ingress node on the LAN.
- `zimaboard-0` continues to advertise the `10.1.0.0/24` subnet into
  Tailscale and is the declared Tailscale exit node until the new primary has
  completed first-time tailnet enrollment; the Debian hosts themselves do not
  accept tailnet routes during bootstrap.
- Traefik is pinned to `nomad-primary` so `80` and `443` stay stable on the
  designated ingress node.
- Traefik also publishes the Nomad and Consul UIs at
  `nomad.stinkyboi.com` and `consul.stinkyboi.com`.
- All in-repo OpenTofu modules use enforced KMS-backed state and plan
  encryption.
- Secret values live in AWS SSM Parameter Store and are synced into Nomad
  variables at apply time.
- Runtime workloads consume secret files or `_FILE` paths instead of injecting
  secret values directly into task environments.

## Validation

Run these checks before planning or applying:

```bash
nix run .#validate
```

That target runs:

- repository unit tests
- Nomad jobspec validation
- Terragrunt HCL formatting checks
- OpenTofu module validation
- Ansible layout checks
- project-local skill metadata validation

## Project-local skills

Operational shell entry points are also wrapped as project-local skills under
`.codex/skills/` so future Codex runs can discover and reuse the same codified
workflow:

- `survey-homelab` for read-only cluster inspection
- `validate-homelab` for local and live validation gates
- `bootstrap-homelab` for rolling Ansible bootstrap and Tailscale repair
- `deploy-homelab` for end-to-end live rollout orchestration
- `unlock-opentofu-state` for stale Terragrunt/OpenTofu lock recovery

## Bootstrap flow

1. Review and update `ansible/inventories/production/group_vars/all.yml`.
2. Bootstrap the Debian hosts:

   ```bash
   pipx inject ansible boto3 botocore
   ansible-playbook -i ansible/inventories/production/hosts.yml ansible/playbooks/bootstrap.yml
   ```

3. Create or update the required AWS SSM parameters before planning:
   - `/homelab/dokploy/postgres_password`
   - `/homelab/fleetdm/mysql_password`
   - `/homelab/fleetdm/mysql_root_password`
   - `/homelab/fleetdm/server_private_key`
   - `/homelab/paperclip/better_auth_secret`
   - `/homelab/paperclip/openrouter_api_key`
   - `/homelab/paperclip/postgres_password`
   - `/homelab/policy-bot/github_app_integration_id`
   - `/homelab/policy-bot/github_app_private_key`
   - `/homelab/policy-bot/github_app_webhook_secret`
   - `/homelab/policy-bot/github_oauth_client_id`
   - `/homelab/policy-bot/github_oauth_client_secret`
   - `/homelab/policy-bot/sessions_key`
   - `/homelab/traefik/cf_dns_api_token`
   Ensure `TG_KMS_KEY_ID` points at the OpenTofu encryption key if you are not
   using the default homelab KMS key.
4. Plan the Nomad infrastructure:

   ```bash
   terragrunt run --all --working-dir terraform/live/homelab plan
   ```

5. Apply once the plan is clean.

GitHub Actions expects the `AWS_ROLE_TO_ASSUME_HOMELAB` repo variable plus the
`TS_AUTH_KEY` repo secret, the preferred CI fallback for locked tailnets. If
`TS_AUTH_KEY` is not set, the workflows use the `TS_OAUTH_CLIENT_ID` and
`TS_OAUTH_SECRET` repo secrets for the Tailscale GitHub Action OAuth client,
and can still fall back to the legacy `TAILSCALE_AUTH_KEY_SSM_PARAMETER` repo
variable. Same-repo pull
requests that touch the live stack run a full Terragrunt plan and refresh a
managed section in the PR description with the latest summary and workflow-run
link. Fork pull requests only run the non-privileged validation workflow.

The Ansible bootstrap no longer enrolls fresh Tailscale nodes from AWS SSM.
It will reapply Tailscale settings only when the host already has a reusable
node key. If a host has never joined the tailnet before, complete
`tailscale up` on that host manually before rerunning bootstrap.

## Live operations

Codified live checks and deployment entry points:

- `nix run .#validate` validates the repository and script syntax locally.
- `nix run .#validate-ssm` validates AWS auth and required SSM parameters.
- `nix run .#validate-live-cluster` validates host reachability and Nomad/Consul health.
- `nix run .#validate-live-workloads` validates Nomad jobs, Nomad variables, Tailscale,
  Traefik, Dokploy, FleetDM, Paperclip, and Policy Bot after deployment.
- `nix run .#deploy-live` runs the local validators, live preflight checks, rolling
  bootstrap, OpenTofu plan/apply, and live smoke checks.
- The `Homelab Deploy` workflow runs `./scripts/deploy-live.sh --skip-bootstrap`,
  so CI applies Terragrunt with the same strict live gates but never bootstraps
  hosts automatically.

When a node is intentionally unavailable and you still need a quorum-safe
rollout to the healthy servers, use:

```bash
ALLOW_DEGRADED_CLUSTER=1 ./scripts/deploy-live.sh
```

## Policy Bot

`policy-bot` stays on the public Traefik ingress at
`https://policy-bot.stinkyboi.com`, but only these paths are routed
publicly:

- `/api/github/auth`
- `/api/github/hook`
- `/details/*`
- `/static/*`

Before the Nomad job can start successfully, create a GitHub App and store the
generated credentials in AWS SSM Parameter Store using the names above. In the
GitHub App settings, use these URLs:

- User authorization callback URL:
  `https://policy-bot.stinkyboi.com/api/github/auth`
- Webhook URL:
  `https://policy-bot.stinkyboi.com/api/github/hook`

If the ingress hostname changes, update
[terragrunt.hcl](/paperclip/instances/default/projects/b8fb2ae2-3438-4684-a280-29433f75dab0/f85626fa-7e0f-4539-83cf-7d409ba3269e/homelab/terraform/live/homelab/variables/policy-bot/config/terragrunt.hcl)
and the GitHub App URLs together before redeploying.

Traefik intentionally does not publish the root path for `policy-bot`, so the
homepage stays unrouted from the public internet while the GitHub callback,
webhook, and pull request details UI remain reachable. The current
`policy-bot` build redirects unauthenticated details requests through
`/api/github/auth`, so there is no separate public `/login` route to expose.

The app also needs the repository and organization permissions documented in the
upstream project along with these subscribed events:

- `check_run`
- `issue_comment`
- `merge_group`
- `pull_request`
- `pull_request_review`
- `status`
- `workflow_run`

## Notes from the latest survey

As of April 5, 2026:

- `10.1.0.199`, `10.1.0.200`, `10.1.0.201`, and `10.1.0.202` were reachable
  over SSH and reported `nomad`, `consul`, `docker`, and `tailscaled` as
  `active`.
- `acer` joined the control plane as `consul-primary` and `nomad-primary`, and
  Traefik now serves the public ingress ports from `10.1.0.199`.
- Dokploy health checks passed through the new ingress node. `paperclip` still
  needs follow-up because its embedded PostgreSQL initialization failed during
  rollout.

See [docs/runbooks/bootstrap.md](/Users/themanofrod/github-repositories/homelab/docs/runbooks/bootstrap.md)
for the expected bring-up sequence.

## FleetDM

FleetDM is routed publicly at `https://fleet.stinkyboi.com` through Traefik,
with TLS terminated at the ingress and Fleet listening on HTTP inside the Nomad
allocation. The Nomad job keeps MySQL, Redis, and Fleet co-located on
`nomad-primary` and stores their state in the `fleetdm_data` host volume.

Before the job can start, create the FleetDM SSM parameters listed above.
Generate `/homelab/fleetdm/server_private_key` with `openssl rand -base64 32`.
