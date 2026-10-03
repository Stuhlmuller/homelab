# Network isolation candidate

Unregistered; no automatic sync. See
[the rollout and containment runbook](../../../../docs/network-enforcement.md).

- `engine/`: digest-pinned kube-router firewall-only DaemonSet and read-only RBAC.
- `policies/`: transitional compatibility grants, agent egress and synthetic
  recovery deny-all policy. Real archives are prohibited.
- `rollback/`: emergency permissive policies; applying these removes containment.
- `applications.yaml`: individually selected manual Argo Application declarations;
  never sync all three together.
- `policy-inventory.json`: audited source policy specifications; live/chart drift
  must be checked separately.

Render all three directories and run `scripts/ci/network-isolation-test.py`.
Use the default preview of `scripts/network-isolation-rollout.py`; execution
requires separate approval of the exact main commit and each phase.
