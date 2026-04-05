# Homelab Monorepo

This repository manages a Debian-based Nomad homelab running on three Zima
boards:

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
├── Makefile
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
- Tailscale is managed as host software so the entire LAN remains reachable over
  the tailnet.
- `zimaboard-0` advertises the `10.1.0.0/24` subnet into Tailscale; the Debian
  hosts themselves do not accept tailnet routes during bootstrap.
- Traefik is pinned to `nomad-0` so `80` and `443` stay stable while the
  three-node control plane is degraded.
- All in-repo OpenTofu modules use enforced KMS-backed state and plan
  encryption.
- Secret values live in AWS SSM Parameter Store and are synced into Nomad
  variables at apply time.
- Runtime workloads consume secret files or `_FILE` paths instead of injecting
  secret values directly into task environments.

## Validation

Run these checks before planning or applying:

```bash
make validate
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
   - `/homelab/paperclip/better_auth_secret`
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

- `make validate` validates the repository and script syntax locally.
- `make validate-ssm` validates AWS auth and required SSM parameters.
- `make validate-live-cluster` validates host reachability and Nomad/Consul health.
- `make validate-live-workloads` validates Nomad jobs, Nomad variables, Tailscale,
  Traefik, Dokploy, Paperclip, and Policy Bot after deployment.
- `make deploy-live` runs the local validators, live preflight checks, rolling
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

`policy-bot` uses Tailscale Funnel only for these public endpoints on
`https://traefik.tail67beb.ts.net`:

- `/api/github/auth`
- `/api/github/hook`

Before the Nomad job can start successfully, create a GitHub App and store the
generated credentials in AWS SSM Parameter Store using the names above. In the
GitHub App settings, use these URLs:

- User authorization callback URL:
  `https://traefik.tail67beb.ts.net/api/github/auth`
- Webhook URL:
  `https://traefik.tail67beb.ts.net/api/github/hook`

The Funnel is reconciled on `zimaboard-0` and proxies only those two paths to
`http://127.0.0.1:18080`. The root path is intentionally not published through
Funnel. If the ingress node's MagicDNS hostname changes, update
[terragrunt.hcl](/Users/themanofrod/.codex/worktrees/f11b/homelab/terraform/live/homelab/variables/policy-bot/config/terragrunt.hcl)
and the GitHub App URLs together before redeploying.

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

As of April 4, 2026:

- `10.1.0.200`, `10.1.0.201`, and `10.1.0.202` were reachable and responded to
  the read-only survey checks.
- `nomad`, `consul`, `docker`, and `tailscaled` all reported `active` on each
  node.
- Consul membership showed all three servers alive in the `homelab`
  datacenter.

See [docs/runbooks/bootstrap.md](/Users/themanofrod/github-repositories/homelab/docs/runbooks/bootstrap.md)
for the expected bring-up sequence.
