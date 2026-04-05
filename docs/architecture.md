# Architecture

## Nodes

- `acer` (`10.1.0.199`)
- `zimaboard-0` (`10.1.0.200`)
- `zimaboard-1` (`10.1.0.201`)
- `zimaboard-2` (`10.1.0.202`)

Each node is expected to run:

- Debian 13
- Docker
- Consul server and client agent
- Nomad server and client agent
- Tailscale daemon

## Control plane

- Consul provides service discovery for Nomad workloads and Traefik.
- Nomad runs both system services and application workloads.
- Terragrunt/OpenTofu registers jobs, CSI volumes, and Nomad variables.
- OpenTofu state and plans are encrypted with AWS KMS-backed module encryption.
- Secret values are read from AWS SSM Parameter Store during OpenTofu apply and
  then written into Nomad variables for cluster-local consumption.

## Networking

- Traefik is the only reverse proxy for HTTP(S) workloads.
- TLS certificates are obtained through ACME DNS-01 and stored on shared NFS
  storage so the active Traefik allocation can move without losing state.
- Tailscale provides private access to the cluster.
- `acer` is the primary LAN-side Nomad and HTTP ingress node.
- `zimaboard-0` remains the intended subnet router for `10.1.0.0/24` until the
  primary server completes first-time Tailscale enrollment and route approval.

## Storage

- Shared application data is registered in Nomad as the `shared-data` CSI
  volume backed by `10.1.0.2:/data`.
- Host volumes under `/opt/nomad/volumes` are used for node-local state where
  appropriate.

## Deployment layers

- `ansible/` is responsible for package installation, systemd services, repo
  configuration, Nomad/Consul config files, and host directories.
- `terraform/live/homelab/` is responsible for deployment ordering and secrets
  registration in Nomad.
- `nomad/jobs/` is the source of truth for jobspecs.
- `scripts/deploy-live.sh` is the canonical live rollout entry point and uses
  explicit preflight and smoke-check scripts.
