# Bootstrap Runbook

1. Confirm all nodes are reachable over SSH.
2. Review `ansible/inventories/production/hosts.yml`.
3. Confirm the AWS SSM parameters exist for the current environment, including
   `/homelab/tailscale/auth_key` if Tailscale enrollment is required.
4. Install the required Ansible collections:
   `ansible-galaxy collection install -r ansible/collections/requirements.yml`
5. Ensure the Ansible controller runtime has the AWS SDK libraries:
   `pipx inject ansible boto3 botocore`
6. Ensure the local AWS CLI session is valid:
   `aws sts get-caller-identity`
7. Run `make ansible-syntax`.
8. Run `make bootstrap`.
9. Verify:
   - `systemctl status consul nomad docker tailscaled`
   - `nomad server members`
   - `consul members`

For repeatable live rollouts, prefer:

```bash
./scripts/deploy-live.sh
```

If a single node is down but the remaining two servers still hold quorum, use:

```bash
ALLOW_DEGRADED_CLUSTER=1 ./scripts/deploy-live.sh
```

Do not deploy Nomad jobs until quorum and host reachability are stable. As of
April 4, 2026, `10.1.0.201` is still down, so a full control-plane bootstrap is
blocked until that node returns.
