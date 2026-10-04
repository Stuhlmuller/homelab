# SOC 2 readiness scope

HOME-30 adds the [proposed system boundary](../../compliance/soc2/scope.md)
and a revision-bound source inventory with synthetic completeness tests.
It is an internal self-assessment, with delegated scope approval, independent
QA reproduction and Auditor acceptance still pending. It makes no operating
effectiveness or certification claim.

Follow [[../workloads/inventory]], [[../architecture/cluster-topology]],
[[../architecture/gitops-flow]], [[../architecture/storage-and-state]] and
[[../architecture/secrets-and-identity]] to reconcile the described boundary.
The proposal includes suspended workloads and retained data, and distinguishes
open recovery/network/monitoring PRs from merged or operating controls.

Known gaps and decision owners are in the scope and evidence packet. Before
changing the boundary, regenerate the source inventory, review dependencies and
obtain the delegated scope decision. This adds no live collection or deployment.
